"""Authenticated salon body-composition workflow.

This module intentionally contains no Withings OAuth secret handling. A future
server-side importer should create pending measurements through the same review
queue exposed here; staff must confirm a measurement before it joins a client record.
"""

import json
import uuid
from datetime import datetime, timedelta

from fastapi import Cookie, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


class SessionIn(BaseModel):
    client_id: int
    station_name: str = "Withings BodyScan 2"
    minutes: int = 5


def install_body_module(app, turso, turso_exec, get_session):
    # Separate tables prevent scale data from being accidentally mixed into appointments.
    turso_exec("""CREATE TABLE IF NOT EXISTS body_sessions (
      id TEXT PRIMARY KEY, client_id INTEGER NOT NULL, station_name TEXT NOT NULL,
      expires_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
      created_at TEXT DEFAULT (datetime('now'))
    )""")
    turso_exec("""CREATE TABLE IF NOT EXISTS body_measurements (
      id TEXT PRIMARY KEY, client_id INTEGER NOT NULL, session_id TEXT,
      station_name TEXT NOT NULL, recorded_at TEXT NOT NULL,
      weight_kg REAL, fat_percent REAL, muscle_kg REAL, visceral_fat INTEGER,
      source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      confirmed_at TEXT, confirmed_by TEXT, created_at TEXT DEFAULT (datetime('now'))
    )""")

    def session(token):
        current = get_session(token)
        if not current:
            raise HTTPException(401, "Не авторизовано")
        return current

    def client_name(client_id):
        rows = turso("SELECT first_name,last_name FROM clients WHERE id=? AND deleted_at IS NULL", [client_id])
        if not rows:
            raise HTTPException(404, "Клієнта не знайдено")
        return " ".join(part for part in [rows[0].get("first_name", ""), rows[0].get("last_name", "")] if part).strip()

    def expire_stale_sessions():
        """A shared consumer scale must never stay assigned after its short window."""
        now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        turso_exec("UPDATE body_sessions SET status='expired' WHERE status='active' AND expires_at<=?", [now])

    def to_measurement(row):
        result = dict(row)
        for key in ["weight_kg", "fat_percent", "muscle_kg"]:
            if result.get(key) not in (None, ""):
                result[key] = float(result[key])
        if result.get("visceral_fat") not in (None, ""):
            result["visceral_fat"] = int(result["visceral_fat"])
        result["client_id"] = int(result["client_id"])
        return result

    @app.get("/api/body/dashboard")
    def dashboard(token: str = Cookie(default=None)):
        current = session(token)
        expire_stale_sessions()
        clients = turso("SELECT id,first_name,last_name,phone FROM clients WHERE deleted_at IS NULL ORDER BY updated_at DESC,id DESC LIMIT 100")
        pending = turso("""SELECT m.*,c.first_name,c.last_name FROM body_measurements m
          JOIN clients c ON c.id=m.client_id WHERE m.status='pending' ORDER BY m.recorded_at DESC""")
        confirmed = turso("""SELECT m.*,c.first_name,c.last_name FROM body_measurements m
          JOIN clients c ON c.id=m.client_id WHERE m.status='confirmed' ORDER BY m.recorded_at DESC LIMIT 8""")
        active = turso("SELECT * FROM body_sessions WHERE status='active' ORDER BY created_at DESC LIMIT 1")
        return {"role": current.get("role"), "clients": [{**r, "id": int(r["id"])} for r in clients], "pending": [to_measurement(r) for r in pending], "confirmed": [to_measurement(r) for r in confirmed], "active_session": active[0] if active else None}

    @app.post("/api/body/sessions", status_code=201)
    def start_session(payload: SessionIn, token: str = Cookie(default=None)):
        session(token)
        if not 1 <= payload.minutes <= 15:
            raise HTTPException(400, "Тривалість сесії має бути від 1 до 15 хвилин")
        client_name(payload.client_id)
        turso_exec("UPDATE body_sessions SET status='closed' WHERE status='active'")
        identifier = str(uuid.uuid4())
        expires = (datetime.utcnow() + timedelta(minutes=payload.minutes)).replace(microsecond=0).isoformat() + "Z"
        turso_exec("INSERT INTO body_sessions (id,client_id,station_name,expires_at,status) VALUES (?,?,?,?,?)", [identifier, payload.client_id, payload.station_name, expires, "active"])
        return {"id": identifier, "client_id": payload.client_id, "client_name": client_name(payload.client_id), "expires_at": expires}

    @app.post("/api/body/sessions/{session_id}/close")
    def close_session(session_id: str, token: str = Cookie(default=None)):
        session(token)
        found = turso("SELECT id FROM body_sessions WHERE id=? AND status='active'", [session_id])
        if not found:
            raise HTTPException(404, "Активну сесію не знайдено")
        turso_exec("UPDATE body_sessions SET status='closed' WHERE id=?", [session_id])
        return {"ok": True}

    @app.post("/api/body/demo-import", status_code=201)
    def demo_import(token: str = Cookie(default=None)):
        """Temporary test path. Replace it with the Withings webhook/import worker."""
        session(token)
        expire_stale_sessions()
        sessions = turso("SELECT * FROM body_sessions WHERE status='active' ORDER BY created_at DESC LIMIT 1")
        if not sessions:
            raise HTTPException(409, "Спершу відкрийте сесію зважування")
        current = sessions[0]
        identifier = str(uuid.uuid4())
        now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        turso_exec("""INSERT INTO body_measurements
          (id,client_id,session_id,station_name,recorded_at,weight_kg,fat_percent,muscle_kg,visceral_fat,source,status)
          VALUES (?,?,?,?,?,?,?,?,?,?,?)""", [identifier, int(current["client_id"]), current["id"], current["station_name"], now, 67.4, 29.1, 24.8, 9, "demo", "pending"])
        return {"id": identifier, "status": "pending"}

    @app.post("/api/body/measurements/{measurement_id}/confirm")
    def confirm_measurement(measurement_id: str, token: str = Cookie(default=None)):
        current = session(token)
        found = turso("SELECT id FROM body_measurements WHERE id=? AND status='pending'", [measurement_id])
        if not found:
            raise HTTPException(404, "Вимір для підтвердження не знайдено")
        actor = current.get("role", "staff")
        turso_exec("UPDATE body_measurements SET status='confirmed',confirmed_at=datetime('now'),confirmed_by=? WHERE id=?", [actor, measurement_id])
        turso_exec("UPDATE body_sessions SET status='closed' WHERE id=(SELECT session_id FROM body_measurements WHERE id=?)", [measurement_id])
        return {"ok": True}

    @app.get("/api/body/client/{client_id}/history")
    def client_history(client_id: int, token: str = Cookie(default=None)):
        session(token)
        client_name(client_id)
        rows = turso("SELECT * FROM body_measurements WHERE client_id=? AND status='confirmed' ORDER BY recorded_at DESC", [client_id])
        return [to_measurement(row) for row in rows]

    @app.get("/body", response_class=HTMLResponse)
    def body_page(token: str = Cookie(default=None)):
        session(token)
        return HTMLResponse(BODY_HTML)


BODY_HTML = r'''<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Salon Board · Вимірювання</title><style>
:root{--ink:#17242e;--muted:#64747e;--bg:#f5f7f6;--panel:#fff;--line:#dbe4e5;--deep:#142733;--mint:#19766a;--soft:#e5f3ef;--amber:#885e18;--amberbg:#fff4dd}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px Inter,system-ui,sans-serif}.bar{background:var(--deep);color:#fff;padding:15px max(20px,calc((100vw - 1060px)/2));display:flex;justify-content:space-between;gap:12px;align-items:center}.bar a{color:#bfe1d9;text-decoration:none;font-size:13px}.brand{font-weight:600}.wrap{max-width:1060px;margin:0 auto;padding:28px 20px}.head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:20px}h1{font-size:26px;margin:0 0 5px}p{color:var(--muted);margin:0}.grid{display:grid;grid-template-columns:1.15fr .85fr;gap:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px}h2{font-size:15px;margin:0 0 14px}.field{display:grid;gap:6px;margin:10px 0}label{font-size:12px;color:var(--muted)}select,input{padding:10px;border:1px solid var(--line);border-radius:8px;background:#fff}button{border:0;border-radius:8px;padding:10px 13px;background:var(--mint);color:#fff;font:inherit;font-weight:600;cursor:pointer}button.secondary{background:#e8eeee;color:var(--ink)}button:disabled{opacity:.5}.session{padding:13px;border:1px solid var(--line);border-radius:11px;margin-bottom:11px}.tag{display:inline-block;border-radius:999px;background:var(--soft);color:#176458;padding:4px 8px;font-size:11px;font-weight:600}.tag.wait{background:var(--amberbg);color:var(--amber)}.metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:12px 0}.metric{background:#f2f6f5;padding:10px;border-radius:8px}.metric b{font-size:17px;display:block}.metric span,.minor{font-size:12px;color:var(--muted)}.row{border-top:1px solid #e7eded;padding:11px 0;display:flex;justify-content:space-between;gap:12px}.row:first-child{border-top:0}.empty{color:var(--muted);border:1px dashed var(--line);border-radius:9px;padding:15px;text-align:center}.toast{position:fixed;right:18px;bottom:18px;background:#173d38;color:#eafff9;padding:12px 14px;border-radius:9px;display:none}.toast.show{display:block}@media(max-width:720px){.grid{grid-template-columns:1fr}.head{align-items:flex-start;flex-direction:column}}
</style></head><body><header class="bar"><span class="brand">SALON BOARD · вимірювання</span><a href="/">← Розклад</a></header><main class="wrap"><div class="head"><div><h1>Станція Withings</h1><p>Кожен результат додається до картки лише після підтвердження працівника.</p></div></div><div class="grid"><section class="card"><h2>Відкрити сесію зважування</h2><div class="field"><label>Клієнт</label><select id="client"></select></div><div class="field"><label>Тривалість</label><select id="minutes"><option value="5">5 хвилин</option><option value="10">10 хвилин</option></select></div><button id="start">Почати сесію</button><button class="secondary" id="connect-station" style="margin-left:7px">Підключити ваги салону</button><button class="secondary" id="sync-station" style="margin-top:7px">Отримати дані з ваг салону</button><button class="secondary" id="connect-withings" style="margin-top:7px">Підключити особистий Withings</button><button class="secondary" id="sync-withings" style="margin-top:7px">Отримати дані особистого Withings</button><p id="withings-hint" class="minor" style="margin-top:10px">Салонні ваги працюють лише в активній сесії. Особисті ваги також створюють запис, що очікує підтвердження.</p><div id="active" style="margin-top:15px"></div></section><section class="card"><h2>Вхідна черга</h2><div id="pending"></div></section></div><section class="card" style="margin-top:16px"><h2>Історія обраного клієнта</h2><div id="history" class="empty">Оберіть клієнта.</div></section><section class="card" style="margin-top:16px"><h2>Останні підтверджені виміри</h2><div id="confirmed"></div></section></main><div class="toast" id="toast"></div><script>
const $=s=>document.querySelector(s);let state={};const toast=t=>{$('#toast').textContent=t;$('#toast').classList.add('show');setTimeout(()=>$('#toast').classList.remove('show'),2200)};const name=r=>[r.first_name,r.last_name].filter(Boolean).join(' ');async function api(path,opt){const r=await fetch(path,opt);if(!r.ok)throw new Error((await r.json()).detail||'Помилка');return r.json()}function metrics(m){return `<div class="metrics"><div class="metric"><b>${m.weight_kg??'—'} кг</b><span>вага</span></div><div class="metric"><b>${m.fat_percent??'—'}%</b><span>жир</span></div><div class="metric"><b>${m.muscle_kg??'—'} кг</b><span>м’язи</span></div><div class="metric"><b>${m.visceral_fat??'—'}</b><span>вісцеральний жир</span></div></div>`}async function loadHistory(){const clientId=$('#client').value;if(!clientId){$('#history').textContent='Додайте клієнта в CRM, щоб бачити історію.';return}try{const rows=await api('/api/body/client/'+clientId+'/history');$('#history').innerHTML=rows.length?rows.slice(0,6).map((m,i)=>`<div class="row"><div><b>${m.weight_kg} кг</b><div class="minor">${new Date(m.recorded_at).toLocaleString('uk-UA')} · ${m.fat_percent??'—'}% жиру</div></div>${i===0?'<span class="tag">останній</span>':''}</div>`).join(''):'<div class="empty">Підтверджених вимірів для цього клієнта ще немає.</div>'}catch(e){$('#history').textContent=e.message}}function render(){const selected=$('#client').value;const s=$('#client');s.innerHTML=state.clients.map(c=>`<option value="${c.id}" ${String(c.id)===selected?'selected':''}>${name(c)} · ${c.phone||'без телефону'}</option>`).join('');const unavailable=!state.clients.length;$('#start').disabled=unavailable;['connect-station','sync-station','connect-withings','sync-withings'].forEach(id=>$('#'+id).disabled=unavailable);['connect-station','connect-withings'].forEach(id=>$('#'+id).style.display=state.role==='admin'?'':'none');$('#active').innerHTML=state.active_session?`<div class="session"><span class="tag">Сесія активна</span><p style="margin:9px 0">Станція: ${state.active_session.station_name}<br>до ${new Date(state.active_session.expires_at).toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'})}</p><button class="secondary" id="demo">Тестово отримати вимір</button><button class="secondary" id="close-session" style="margin-left:6px">Завершити сесію</button></div>`:'<div class="empty">Активної сесії немає.</div>';$('#pending').innerHTML=state.pending.length?state.pending.map(m=>`<div class="session"><span class="tag wait">Очікує підтвердження</span>${metrics(m)}<p>Запропоновано для: <b>${name(m)}</b></p><button data-id="${m.id}">Підтвердити для клієнта</button></div>`).join(''):'<div class="empty">Нових даних немає.</div>';$('#confirmed').innerHTML=state.confirmed.length?state.confirmed.map(m=>`<div class="row"><div><b>${name(m)}</b><div class="minor">${new Date(m.recorded_at).toLocaleString('uk-UA')}</div></div><b>${m.weight_kg} кг</b></div>`).join(''):'<div class="empty">Підтверджених вимірів ще немає.</div>';$('#demo')?.addEventListener('click',async()=>{try{await api('/api/body/demo-import',{method:'POST'});toast('Вимір надійшов у чергу');load()}catch(e){toast(e.message)}});$('#close-session')?.addEventListener('click',async()=>{try{await api('/api/body/sessions/'+state.active_session.id+'/close',{method:'POST'});toast('Сесію завершено');load()}catch(e){toast(e.message)}});document.querySelectorAll('[data-id]').forEach(b=>b.onclick=async()=>{await api('/api/body/measurements/'+b.dataset.id+'/confirm',{method:'POST'});toast('Вимір додано в картку');load()});s.onchange=loadHistory;loadHistory()}async function load(){try{state=await api('/api/body/dashboard');render()}catch(e){toast(e.message)}}$('#start').onclick=async()=>{try{await api('/api/body/sessions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({client_id:+$('#client').value,minutes:+$('#minutes').value})});toast('Сесію відкрито');load()}catch(e){toast(e.message)}};load();
async function setupWithings(){try{const status=await api('/api/withings/status');if(!status.configured){['connect-withings','sync-withings','connect-station','sync-station'].forEach(id=>$('#'+id).disabled=true);$('#withings-hint').textContent='Withings ще не налаштовано в середовищі сервера.';return}const connect=async path=>{try{const result=await api(path,{method:'POST',headers:{'content-type':'application/json'},body:path==='/api/withings/connect'?JSON.stringify({client_id:+$('#client').value}):undefined});location.href=result.authorize_url}catch(e){toast(e.message)}};$('#connect-withings').onclick=()=>connect('/api/withings/connect');$('#connect-station').onclick=()=>connect('/api/withings/station/connect');const sync=async path=>{try{const result=await api(path,{method:'POST'});toast(result.deduplicated?'Цей вимір уже є в черзі':'Вимір отримано у чергу');load()}catch(e){toast(e.message)}};$('#sync-withings').onclick=()=>sync('/api/withings/sync/client/'+$('#client').value);$('#sync-station').onclick=()=>sync('/api/withings/station/sync');if(new URLSearchParams(location.search).get('withings')==='connected')toast('Withings підключено. Дані можна синхронізувати з карткою клієнта.')}catch(e){['connect-withings','sync-withings','connect-station','sync-station'].forEach(id=>$('#'+id).disabled=true);$('#withings-hint').textContent='Статус Withings наразі недоступний.'}}setupWithings();
</script></body></html>'''
