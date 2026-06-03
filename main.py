"""
Cosmo — розклад косметологічного кабінету
Запуск: uvicorn main:app --reload
"""

import json, hashlib, secrets, os, urllib.request, urllib.error
from datetime import date, datetime, timedelta
from fastapi import FastAPI, HTTPException, Request, Response, Cookie, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional

# ─── TURSO DB ──────────────────────────────────────────────────────────────────

TURSO_URL = os.environ.get('TURSO_URL', 'https://salon-board-sergejkolesnik.aws-eu-west-1.turso.io')
TURSO_TOKEN = os.environ.get('TURSO_TOKEN', 'eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODA0MDgyMDksImlkIjoiMDE5ZTg4OTItZTYwMS03NWRmLWE1ZjQtNzZiN2Q5YzkyZTcyIiwicmlkIjoiZWQ0YmQxZTAtMmZmZS00MDZlLWEyZGUtYTkzN2E3YmZjODlhIn0.KrVUUpG7zyHB-lr-zONJp3jZLjgMcWyLE4eaD0GqdeqIFsEMZEsy-WPe1rEY4FoAlSrIPIYGDJY4i-WsL3BqCA')

def turso(sql: str, params=None):
    """Execute single SQL statement, return rows list."""
    stmt = {'sql': sql}
    if params:
        args = []
        for p in params:
            if p is None:
                args.append({'type': 'null'})
            elif isinstance(p, int):
                args.append({'type': 'integer', 'value': str(p)})
            elif isinstance(p, float):
                args.append({'type': 'float', 'value': str(p)})
            else:
                args.append({'type': 'text', 'value': str(p)})
        stmt['args'] = args
    payload = json.dumps({'requests': [{'type': 'execute', 'stmt': stmt}, {'type': 'close'}]}).encode()
    req = urllib.request.Request(
        f'{TURSO_URL}/v2/pipeline', data=payload,
        headers={'Authorization': f'Bearer {TURSO_TOKEN}', 'Content-Type': 'application/json'},
        method='POST'
    )
    with urllib.request.urlopen(req) as r:
        data = json.load(r)
    result = data['results'][0]['response']['result']
    cols = [c['name'] for c in result['cols']]
    return [dict(zip(cols, [v.get('value') for v in row])) for row in result['rows']]

def turso_exec(sql: str, params=None):
    """Execute and return lastInsertRowid."""
    stmt = {'sql': sql}
    if params:
        args = []
        for p in params:
            if p is None:
                args.append({'type': 'null'})
            elif isinstance(p, int):
                args.append({'type': 'integer', 'value': str(p)})
            elif isinstance(p, float):
                args.append({'type': 'float', 'value': str(p)})
            else:
                args.append({'type': 'text', 'value': str(p)})
        stmt['args'] = args
    payload = json.dumps({'requests': [{'type': 'execute', 'stmt': stmt}, {'type': 'close'}]}).encode()
    req = urllib.request.Request(
        f'{TURSO_URL}/v2/pipeline', data=payload,
        headers={'Authorization': f'Bearer {TURSO_TOKEN}', 'Content-Type': 'application/json'},
        method='POST'
    )
    with urllib.request.urlopen(req) as r:
        data = json.load(r)
    return data['results'][0]['response']['result'].get('lastInsertRowid')

def turso_batch(statements):
    """Execute multiple SQL statements in one request."""
    requests = [{'type': 'execute', 'stmt': {'sql': s}} for s in statements]
    requests.append({'type': 'close'})
    payload = json.dumps({'requests': requests}).encode()
    req = urllib.request.Request(
        f'{TURSO_URL}/v2/pipeline', data=payload,
        headers={'Authorization': f'Bearer {TURSO_TOKEN}', 'Content-Type': 'application/json'},
        method='POST'
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)

def init_db():
    turso_batch([
        """CREATE TABLE IF NOT EXISTS masters (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '#7F77DD', initials TEXT NOT NULL DEFAULT '??')""",
        """CREATE TABLE IF NOT EXISTS appointments (id INTEGER PRIMARY KEY AUTOINCREMENT, master_id INTEGER NOT NULL, client_name TEXT NOT NULL, service TEXT NOT NULL, appt_date TEXT NOT NULL, start_time TEXT NOT NULL, duration_min INTEGER NOT NULL DEFAULT 60, notes TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')))""",
        """CREATE TABLE IF NOT EXISTS breaks (id INTEGER PRIMARY KEY AUTOINCREMENT, master_id INTEGER NOT NULL, break_date TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL, label TEXT DEFAULT 'Обід')""",
        """CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, role TEXT NOT NULL, master_id INTEGER, created_at TEXT DEFAULT (datetime('now')))""",
        "INSERT OR IGNORE INTO settings (key,value) VALUES ('pwd_admin','admin123')",
        """CREATE TABLE IF NOT EXISTS services (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, sort_order INTEGER DEFAULT 0)""",
        # role_templates: шаблони прав
        """CREATE TABLE IF NOT EXISTS role_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            can_view_all INTEGER NOT NULL DEFAULT 0,
            can_add_any INTEGER NOT NULL DEFAULT 0,
            can_edit_others INTEGER NOT NULL DEFAULT 0
        )""",
        # master_roles: прив'язка майстра до шаблону
        """CREATE TABLE IF NOT EXISTS master_roles (
            master_id INTEGER PRIMARY KEY,
            template_id INTEGER NOT NULL
        )""",
    ])
    # Default services
    svc_rows = turso("SELECT COUNT(*) as cnt FROM services")
    if int(svc_rows[0]["cnt"]) == 0:
        for i, name in enumerate(["Чистка шкіри","Пілінг","ГАК","Ботокс / філери","Полінуклеотіди","Догляд","Дерматологія","Псоролайт","Консультація"]):
            turso_exec("INSERT INTO services (name, sort_order) VALUES (?,?)", [name, i])
    # Default role templates
    tpl_rows = turso("SELECT COUNT(*) as cnt FROM role_templates")
    if int(tpl_rows[0]["cnt"]) == 0:
        turso_batch([
            "INSERT INTO role_templates (name,can_view_all,can_add_any,can_edit_others) VALUES ('Майстер-базовий',0,0,0)",
            "INSERT INTO role_templates (name,can_view_all,can_add_any,can_edit_others) VALUES ('Майстер-старший',1,1,0)",
            "INSERT INTO role_templates (name,can_view_all,can_add_any,can_edit_others) VALUES ('Рецепція',1,1,1)",
        ])




# ─── API MODELS ────────────────────────────────────────────────────────────────

class AppointmentIn(BaseModel):
    master_id: int
    client_name: str
    service: str
    appt_date: str
    start_time: str
    duration_min: int = 60
    notes: str = ""

class AppointmentUpdate(BaseModel):
    client_name: Optional[str] = None
    service: Optional[str] = None
    appt_date: Optional[str] = None
    start_time: Optional[str] = None
    duration_min: Optional[int] = None
    notes: Optional[str] = None

class MasterIn(BaseModel):
    name: str
    color: str = "#7F77DD"
    initials: str = "??"

class LoginIn(BaseModel):
    password: str
    master_id: Optional[int] = None

class PasswordIn(BaseModel):
    master_id: int
    password: str

class RoleTemplateIn(BaseModel):
    name: str
    can_view_all: bool = False
    can_add_any: bool = False
    can_edit_others: bool = False

class MasterRoleIn(BaseModel):
    master_id: int
    template_id: int

# ─── APP ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Cosmo Schedule")
init_db()

# ─── AUTH HELPERS ──────────────────────────────────────────────────────────────

def get_setting(key: str) -> str:
    rows = turso("SELECT value FROM settings WHERE key=?", [key])
    return rows[0]['value'] if rows else ""

def create_session(role: str, master_id: int = None) -> str:
    token = secrets.token_hex(32)
    turso_exec("INSERT INTO sessions (token,role,master_id) VALUES (?,?,?)", [token, role, master_id])
    return token

def get_session(token: str = Cookie(default=None)):
    if not token:
        return None
    rows = turso("SELECT role, master_id FROM sessions WHERE token=?", [token])
    if not rows:
        return None
    r = rows[0]
    return {'role': r['role'], 'master_id': int(r['master_id']) if r['master_id'] else None}

def get_master_perms(master_id: int) -> dict:
    """Повертає права майстра на основі його шаблону."""
    rows = turso("""
        SELECT t.can_view_all, t.can_add_any, t.can_edit_others, t.name as template_name
        FROM master_roles mr JOIN role_templates t ON mr.template_id=t.id
        WHERE mr.master_id=?
    """, [master_id])
    if rows:
        r = rows[0]
        return {
            'can_view_all': bool(int(r['can_view_all'] or 0)),
            'can_add_any': bool(int(r['can_add_any'] or 0)),
            'can_edit_others': bool(int(r['can_edit_others'] or 0)),
            'template_name': r['template_name'],
        }
    # За замовчуванням — базові права
    return {'can_view_all': False, 'can_add_any': False, 'can_edit_others': False, 'template_name': 'Майстер-базовий'}

def require_auth(token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess:
        raise HTTPException(401, "Не авторизовано")
    return sess

def require_admin(token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess or sess["role"] != "admin":
        raise HTTPException(403, "Тільки адмін")
    return sess

# ─── REST API ──────────────────────────────────────────────────────────────────

@app.get("/api/masters")
def list_masters():
    rows = turso("SELECT * FROM masters ORDER BY id")
    result = []
    for r in rows:
        mid = int(r['id'])
        perms = get_master_perms(mid)
        # Знайти пароль
        pwd_row = turso("SELECT value FROM settings WHERE key=?", [f"pwd_master_{mid}"])
        result.append({
            **r, 'id': mid,
            'template_name': perms['template_name'],
            'has_password': bool(pwd_row),
        })
    return result

@app.post("/api/masters", status_code=201)
def create_master(m: MasterIn, sess=Depends(require_admin)):
    rid = turso_exec("INSERT INTO masters (name,color,initials) VALUES (?,?,?)", [m.name, m.color, m.initials])
    try:
        master_id = int(rid) if rid is not None else None
    except (ValueError, TypeError):
        master_id = None
    if not master_id:
        rows = turso("SELECT id FROM masters WHERE name=? ORDER BY id DESC LIMIT 1", [m.name])
        if rows and rows[0].get('id') is not None:
            try: master_id = int(rows[0]['id'])
            except: pass
    if not master_id:
        raise HTTPException(500, "Не вдалося отримати id майстра")
    # Знаходимо або створюємо базовий шаблон
    tpl = turso("SELECT id FROM role_templates WHERE name='Майстер-базовий'")
    if not tpl:
        # Шаблони відсутні — відновлюємо дефолтні
        turso_batch([
            "INSERT OR IGNORE INTO role_templates (name,can_view_all,can_add_any,can_edit_others) VALUES ('Майстер-базовий',0,0,0)",
            "INSERT OR IGNORE INTO role_templates (name,can_view_all,can_add_any,can_edit_others) VALUES ('Майстер-старший',1,1,0)",
            "INSERT OR IGNORE INTO role_templates (name,can_view_all,can_add_any,can_edit_others) VALUES ('Рецепція',1,1,1)",
        ])
        tpl = turso("SELECT id FROM role_templates WHERE name='Майстер-базовий'")
    if tpl:
        tpl_id = tpl[0].get('id')
        if tpl_id is not None:
            turso_exec("INSERT OR REPLACE INTO master_roles (master_id,template_id) VALUES (?,?)", [master_id, int(tpl_id)])
    return {"id": master_id, **m.dict()}

@app.put("/api/masters/{master_id}")
def update_master(master_id: int, m: MasterIn, sess=Depends(require_admin)):
    rows = turso("SELECT id FROM masters WHERE id=?", [master_id])
    if not rows:
        raise HTTPException(404, "Майстра не знайдено")
    turso_exec("UPDATE masters SET name=?,color=?,initials=? WHERE id=?", [m.name, m.color, m.initials, master_id])
    return {"id": master_id, **m.dict()}

@app.delete("/api/masters/{master_id}")
def delete_master(master_id: int, sess=Depends(require_admin)):
    turso_exec("DELETE FROM appointments WHERE master_id=?", [master_id])
    turso_exec("DELETE FROM breaks WHERE master_id=?", [master_id])
    turso_exec("DELETE FROM master_roles WHERE master_id=?", [master_id])
    turso_exec("DELETE FROM masters WHERE id=?", [master_id])
    return {"ok": True}

# ─── ROLE TEMPLATES ────────────────────────────────────────────────────────────

@app.get("/api/role-templates")
def list_role_templates(sess=Depends(require_admin)):
    rows = turso("SELECT * FROM role_templates ORDER BY id")
    if not rows:
        turso_batch([
            "INSERT OR IGNORE INTO role_templates (name,can_view_all,can_add_any,can_edit_others) VALUES ('Майстер-базовий',0,0,0)",
            "INSERT OR IGNORE INTO role_templates (name,can_view_all,can_add_any,can_edit_others) VALUES ('Майстер-старший',1,1,0)",
            "INSERT OR IGNORE INTO role_templates (name,can_view_all,can_add_any,can_edit_others) VALUES ('Рецепція',1,1,1)",
        ])
        rows = turso("SELECT * FROM role_templates ORDER BY id")
    result = []
    for r in rows:
        rid = r.get('id')
        if rid is None: continue
        result.append({'id': int(rid), 'name': r.get('name',''), 'can_view_all': bool(int(r.get('can_view_all') or 0)), 'can_add_any': bool(int(r.get('can_add_any') or 0)), 'can_edit_others': bool(int(r.get('can_edit_others') or 0))})
    return result

@app.post("/api/role-templates", status_code=201)
def create_role_template(t: RoleTemplateIn, sess=Depends(require_admin)):
    rid = turso_exec("INSERT INTO role_templates (name,can_view_all,can_add_any,can_edit_others) VALUES (?,?,?,?)",
                     [t.name, int(t.can_view_all), int(t.can_add_any), int(t.can_edit_others)])
    return {"id": int(rid), **t.dict()}

@app.put("/api/role-templates/{tpl_id}")
def update_role_template(tpl_id: int, t: RoleTemplateIn, sess=Depends(require_admin)):
    turso_exec("UPDATE role_templates SET name=?,can_view_all=?,can_add_any=?,can_edit_others=? WHERE id=?",
               [t.name, int(t.can_view_all), int(t.can_add_any), int(t.can_edit_others), tpl_id])
    return {"id": tpl_id, **t.dict()}

@app.delete("/api/role-templates/{tpl_id}")
def delete_role_template(tpl_id: int, sess=Depends(require_admin)):
    # Не видаляти якщо є майстри з цим шаблоном
    used = turso("SELECT COUNT(*) as cnt FROM master_roles WHERE template_id=?", [tpl_id])
    if int(used[0]['cnt']) > 0:
        raise HTTPException(400, "Шаблон використовується майстрами")
    turso_exec("DELETE FROM role_templates WHERE id=?", [tpl_id])
    return {"ok": True}

@app.put("/api/masters/{master_id}/role")
def set_master_role(master_id: int, data: MasterRoleIn, sess=Depends(require_admin)):
    turso_exec("INSERT OR REPLACE INTO master_roles (master_id,template_id) VALUES (?,?)", [master_id, data.template_id])
    return {"ok": True}

@app.put("/api/masters/{master_id}/password")
def set_master_password(master_id: int, data: PasswordIn, sess=Depends(require_admin)):
    if not data.password:
        raise HTTPException(400, "Пароль не може бути порожнім")
    turso_exec("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", [f"pwd_master_{master_id}", data.password])
    return {"ok": True}

# ─── APPOINTMENTS ──────────────────────────────────────────────────────────────

@app.get("/api/appointments")
def list_appointments(date: str = None, token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess:
        raise HTTPException(401, "Не авторизовано")
    if sess['role'] == 'admin':
        # Адмін бачить всіх
        if date:
            rows = turso("SELECT a.*, m.name as master_name, m.color, m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.appt_date=? ORDER BY a.start_time", [date])
        else:
            rows = turso("SELECT a.*, m.name as master_name, m.color, m.initials FROM appointments a JOIN masters m ON a.master_id=m.id ORDER BY a.appt_date, a.start_time")
    elif sess['role'] == 'master' and sess['master_id']:
        perms = get_master_perms(sess['master_id'])
        if perms['can_view_all']:
            if date:
                rows = turso("SELECT a.*, m.name as master_name, m.color, m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.appt_date=? ORDER BY a.start_time", [date])
            else:
                rows = turso("SELECT a.*, m.name as master_name, m.color, m.initials FROM appointments a JOIN masters m ON a.master_id=m.id ORDER BY a.appt_date, a.start_time")
        else:
            # Бачить тільки своїх
            if date:
                rows = turso("SELECT a.*, m.name as master_name, m.color, m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.master_id=? AND a.appt_date=? ORDER BY a.start_time", [sess['master_id'], date])
            else:
                rows = turso("SELECT a.*, m.name as master_name, m.color, m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.master_id=? ORDER BY a.appt_date, a.start_time", [sess['master_id']])
    else:
        rows = []
    return [{**r, 'id': int(r['id']), 'master_id': int(r['master_id']), 'duration_min': int(r['duration_min'])} for r in rows]

@app.post("/api/appointments", status_code=201)
def create_appointment(a: AppointmentIn, token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess:
        raise HTTPException(401, "Не авторизовано")
    # Перевірка прав на додавання
    if sess['role'] == 'master' and sess['master_id']:
        perms = get_master_perms(sess['master_id'])
        if not perms['can_add_any'] and a.master_id != sess['master_id']:
            raise HTTPException(403, "Можна додавати записи лише собі")
    elif sess['role'] not in ('admin', 'master'):
        raise HTTPException(403, "Недостатньо прав")

    def to_min(t): h,m = map(int, t.split(":")); return h*60+m
    existing = turso("SELECT start_time, duration_min FROM appointments WHERE master_id=? AND appt_date=?", [a.master_id, a.appt_date])
    new_start = to_min(a.start_time)
    new_end = new_start + a.duration_min
    for row in existing:
        s = to_min(row["start_time"])
        e = s + int(row["duration_min"])
        if new_start < e and new_end > s:
            raise HTTPException(400, "Цей час вже зайнятий у майстра")
    turso_exec("INSERT INTO appointments (master_id,client_name,service,appt_date,start_time,duration_min,notes) VALUES (?,?,?,?,?,?,?)",
                    [a.master_id, a.client_name, a.service, a.appt_date, a.start_time, a.duration_min, a.notes])
    rows = turso("SELECT a.*,m.name as master_name,m.color,m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.master_id=? AND a.appt_date=? AND a.start_time=? ORDER BY a.id DESC LIMIT 1",
                 [a.master_id, a.appt_date, a.start_time])
    if not rows:
        return {"ok": True, "master_id": a.master_id, "client_name": a.client_name, "service": a.service, "appt_date": a.appt_date, "start_time": a.start_time, "duration_min": a.duration_min, "notes": a.notes}
    r = rows[0]
    return {**r, 'id': int(r['id']), 'master_id': int(r['master_id']), 'duration_min': int(r['duration_min'])}

@app.put("/api/appointments/{appt_id}")
def update_appointment(appt_id: int, a: AppointmentUpdate, token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess:
        raise HTTPException(401, "Не авторизовано")
    rows = turso("SELECT * FROM appointments WHERE id=?", [appt_id])
    if not rows:
        raise HTTPException(404, "Запис не знайдено")
    existing = rows[0]
    # Перевірка прав на редагування
    if sess['role'] == 'master' and sess['master_id']:
        perms = get_master_perms(sess['master_id'])
        if not perms['can_edit_others'] and int(existing['master_id']) != sess['master_id']:
            raise HTTPException(403, "Можна редагувати лише свої записи")
    elif sess['role'] not in ('admin', 'master'):
        raise HTTPException(403, "Недостатньо прав")
    data = dict(existing)
    for k, v in a.dict(exclude_none=True).items():
        data[k] = v
    turso_exec("UPDATE appointments SET client_name=?,service=?,appt_date=?,start_time=?,duration_min=?,notes=? WHERE id=?",
              [data["client_name"], data["service"], data["appt_date"], data["start_time"], data["duration_min"], data["notes"], appt_id])
    rows2 = turso("SELECT a.*,m.name as master_name,m.color,m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.id=?", [appt_id])
    r = rows2[0]
    return {**r, 'id': int(r['id']), 'master_id': int(r['master_id']), 'duration_min': int(r['duration_min'])}

@app.delete("/api/appointments/{appt_id}")
def delete_appointment(appt_id: int, token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess:
        raise HTTPException(401, "Не авторизовано")
    rows = turso("SELECT * FROM appointments WHERE id=?", [appt_id])
    if not rows:
        raise HTTPException(404)
    existing = rows[0]
    if sess['role'] == 'master' and sess['master_id']:
        perms = get_master_perms(sess['master_id'])
        if not perms['can_edit_others'] and int(existing['master_id']) != sess['master_id']:
            raise HTTPException(403, "Можна видаляти лише свої записи")
    turso_exec("DELETE FROM appointments WHERE id=?", [appt_id])
    return {"ok": True}

@app.get("/api/breaks")
def list_breaks(date: str = None):
    if date:
        rows = turso("SELECT * FROM breaks WHERE break_date=?", [date])
    else:
        rows = turso("SELECT * FROM breaks")
    return [{**r, 'id': int(r['id']), 'master_id': int(r['master_id'])} for r in rows]

@app.get("/api/appointments/range")
def appointments_range(master_id: int, from_date: str = None, to_date: str = None, token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess:
        raise HTTPException(401, "Не авторизовано")
    # Перевірка чи може бачити цього майстра
    if sess['role'] == 'master' and sess['master_id']:
        perms = get_master_perms(sess['master_id'])
        if not perms['can_view_all'] and master_id != sess['master_id']:
            raise HTTPException(403, "Доступ заборонено")
    if from_date and to_date:
        rows = turso("SELECT a.*, m.name as master_name, m.color, m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.master_id=? AND a.appt_date>=? AND a.appt_date<=? ORDER BY a.appt_date, a.start_time", [master_id, from_date, to_date])
    else:
        rows = turso("SELECT a.*, m.name as master_name, m.color, m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.master_id=? ORDER BY a.appt_date, a.start_time", [master_id])
    return [{**r, 'id': int(r['id']), 'master_id': int(r['master_id']), 'duration_min': int(r['duration_min'])} for r in rows]

@app.get("/api/breaks/range")
def breaks_range(master_id: int, from_date: str = None, to_date: str = None):
    if from_date and to_date:
        rows = turso("SELECT * FROM breaks WHERE master_id=? AND break_date>=? AND break_date<=?", [master_id, from_date, to_date])
    else:
        rows = turso("SELECT * FROM breaks WHERE master_id=?", [master_id])
    return [{**r, 'id': int(r['id']), 'master_id': int(r['master_id'])} for r in rows]

@app.get("/api/services")
def list_services():
    rows = turso("SELECT * FROM services ORDER BY sort_order, id")
    return [{**r, 'id': int(r['id']), 'sort_order': int(r['sort_order'] or 0)} for r in rows]

class ServiceIn(BaseModel):
    name: str
    sort_order: int = 0

@app.post("/api/services", status_code=201)
def create_service(s: ServiceIn, sess=Depends(require_admin)):
    rid = turso_exec("INSERT INTO services (name, sort_order) VALUES (?,?)", [s.name, s.sort_order])
    return {"id": int(rid), "name": s.name, "sort_order": s.sort_order}

@app.put("/api/services/{svc_id}")
def update_service(svc_id: int, s: ServiceIn, sess=Depends(require_admin)):
    turso_exec("UPDATE services SET name=?, sort_order=? WHERE id=?", [s.name, s.sort_order, svc_id])
    return {"id": svc_id, "name": s.name, "sort_order": s.sort_order}

@app.delete("/api/services/{svc_id}")
def delete_service(svc_id: int, sess=Depends(require_admin)):
    turso_exec("DELETE FROM services WHERE id=?", [svc_id])
    return {"ok": True}

# ─── AUTH ──────────────────────────────────────────────────────────────────────

@app.post("/api/login")
def login(data: LoginIn, response: Response):
    pwd_admin = get_setting("pwd_admin")
    if data.password == pwd_admin:
        token = create_session("admin")
        response.set_cookie("token", token, httponly=False, samesite="none", max_age=86400*30, secure=True)
        return {"role": "admin", "master_id": None}
    # Перевірка паролю майстра
    if data.master_id:
        pwd_master = get_setting(f"pwd_master_{data.master_id}")
        if pwd_master and data.password == pwd_master:
            token = create_session("master", data.master_id)
            response.set_cookie("token", token, httponly=False, samesite="none", max_age=86400*30, secure=True)
            perms = get_master_perms(data.master_id)
            return {"role": "master", "master_id": data.master_id, "perms": perms}
    raise HTTPException(401, "Невірний пароль")

@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("token")
    return {"ok": True}

@app.get("/api/me")
def me(token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess:
        return {"role": "guest"}
    if sess['role'] == 'master' and sess['master_id']:
        perms = get_master_perms(sess['master_id'])
        # Отримати ім'я майстра
        rows = turso("SELECT name FROM masters WHERE id=?", [sess['master_id']])
        name = rows[0]['name'] if rows else ""
        return {**sess, 'perms': perms, 'name': name}
    return sess

@app.put("/api/settings/password")
def set_admin_password(data: dict, sess=Depends(require_admin)):
    pwd = data.get("password", "")
    if not pwd:
        raise HTTPException(400, "Пароль не може бути порожнім")
    turso_exec("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ["pwd_admin", pwd])
    return {"ok": True}

@app.get("/api/settings/passwords")
def get_passwords(sess=Depends(require_admin)):
    rows = turso("SELECT key, value FROM settings WHERE key LIKE 'pwd_%'")
    return {r["key"]: r["value"] for r in rows}

@app.delete("/api/clear-demo")
def clear_demo():
    turso_exec("DELETE FROM appointments")
    turso_exec("DELETE FROM breaks")
    turso_exec("DELETE FROM sessions")
    return {"ok": True}

# ─── MANIFEST / ICON ───────────────────────────────────────────────────────────

import json as _json, base64 as _b64

MANIFEST = {
    "name": "Body Balance", "short_name": "Body Balance",
    "description": "Розклад косметологічного кабінету",
    "start_url": "/master", "display": "standalone",
    "background_color": "#121214", "theme_color": "#00C8B4",
    "orientation": "portrait",
    "icons": [
        {"src": "/api/icon", "sizes": "192x192", "type": "image/svg+xml"},
        {"src": "/api/icon", "sizes": "512x512", "type": "image/svg+xml", "purpose": "any maskable"}
    ]
}

@app.get("/manifest.json")
def manifest():
    from fastapi.responses import Response as FR
    return FR(content=_json.dumps(MANIFEST), media_type="application/manifest+json")

@app.get("/api/icon")
def get_icon():
    from fastapi.responses import Response as FR
    # Використовуємо іконку з оригінального файлу
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="80" fill="#121214"/><text x="256" y="320" font-size="240" text-anchor="middle" fill="#00C8B4" font-family="Arial">B</text></svg>'
    return FR(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})

# ─── PAGES ─────────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return LOGIN_HTML

@app.get("/", response_class=HTMLResponse)
def index(token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess:
        return RedirectResponse("/login")
    if sess['role'] != 'admin':
        return RedirectResponse("/master")
    return ADMIN_HTML

@app.get("/master", response_class=HTMLResponse)
def master_page(token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess:
        return RedirectResponse("/login")
    return MASTER_HTML


LOGIN_HTML = """<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Body Balance — Вхід</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:#121214;color:#E4E4E7;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:#1E1E22;border:1px solid #2E2E36;border-radius:16px;padding:36px 32px;width:100%;max-width:380px;box-shadow:0 8px 32px rgba(0,0,0,.5)}
.logo{text-align:center;margin-bottom:28px;font-family:'Montserrat',sans-serif;font-size:22px;font-weight:800;color:#00C8B4}
h2{font-family:'Montserrat',sans-serif;font-size:18px;font-weight:700;margin-bottom:20px;color:#E4E4E7;text-align:center}
.role-tabs{display:flex;gap:6px;margin-bottom:20px;background:#121214;border-radius:10px;padding:4px}
.role-tab{flex:1;padding:8px;text-align:center;border-radius:7px;cursor:pointer;font-size:12px;font-weight:600;color:#71717A;font-family:'Montserrat',sans-serif;transition:all .15s}
.role-tab.active{background:#1E1E22;color:#00C8B4;box-shadow:0 1px 4px rgba(0,0,0,.4)}
.field{margin-bottom:14px}
.field label{display:block;font-size:12px;font-weight:600;color:#A1A1AA;margin-bottom:5px;text-transform:uppercase;font-family:'Montserrat',sans-serif}
.field select,.field input{width:100%;padding:10px 12px;background:#121214;border:1px solid #2E2E36;border-radius:8px;color:#E4E4E7;font-family:'Inter',sans-serif;font-size:14px;outline:none;transition:border-color .15s}
.field select:focus,.field input:focus{border-color:#00C8B4}
.btn{width:100%;padding:12px;background:#00C8B4;color:#121214;border:none;border-radius:8px;font-family:'Montserrat',sans-serif;font-size:14px;font-weight:700;cursor:pointer;transition:opacity .15s;margin-top:4px}
.btn:hover{opacity:.88}
.err{color:#F87171;font-size:12px;margin-top:10px;text-align:center;min-height:18px}
.master-field{display:none}
</style>
</head>
<body>
<div class="card">
  <div class="logo">Body Balance</div>
  <h2>Вхід у систему</h2>
  <div class="role-tabs">
    <div class="role-tab active" onclick="setRole('admin')">Адмін</div>
    <div class="role-tab" onclick="setRole('master')">Майстер</div>
  </div>
  <div class="master-field field" id="masterField">
    <label>Оберіть майстра</label>
    <select id="masterSelect"></select>
  </div>
  <div class="field">
    <label>Пароль</label>
    <input type="password" id="pwd" placeholder="Введіть пароль" onkeydown="if(event.key==='Enter')doLogin()">
  </div>
  <button class="btn" onclick="doLogin()">Увійти</button>
  <div class="err" id="errMsg"></div>
</div>
<script>
let currentRole='admin';
async function init(){
  const res=await fetch('/api/masters');
  const masters=await res.json();
  const sel=document.getElementById('masterSelect');
  sel.innerHTML=masters.map(m=>`<option value="${m.id}">${m.name}</option>`).join('');
}
function setRole(role){
  currentRole=role;
  document.querySelectorAll('.role-tab').forEach((t,i)=>{t.classList.toggle('active',['admin','master'][i]===role);});
  document.getElementById('masterField').style.display=role==='master'?'block':'none';
}
async function doLogin(){
  const pwd=document.getElementById('pwd').value;
  const masterId=currentRole==='master'?parseInt(document.getElementById('masterSelect').value):null;
  const err=document.getElementById('errMsg');
  err.textContent='';
  try{
    const res=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pwd,master_id:masterId})});
    if(res.ok){
      const data=await res.json();
      window.location.href=data.role==='admin'?'/':'/master';
    }else{
      const data=await res.json();
      err.textContent=data.detail||'Невірний пароль';
    }
  }catch(e){err.textContent="Помилка з'єднання";}
}
init();
</script>
</body>
</html>"""


ADMIN_HTML = """<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Body Balance — Адмін</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#121214;--surface:#1E1E22;--surface2:#222227;--border:#2E2E36;--text:#E4E4E7;--muted:#A1A1AA;--hint:#71717A;--accent:#00C8B4;--accent-light:rgba(0,200,180,.15);--danger:#F87171;--danger-light:rgba(248,113,113,.12);--radius:12px;--radius-sm:8px;--font:'Inter',sans-serif;--font-head:'Montserrat',sans-serif}
html,body{min-height:100vh;font-family:var(--font);background:var(--bg);color:var(--text);font-size:14px}
.topbar{display:flex;align-items:center;gap:16px;padding:0 24px;height:64px;background:var(--surface);border-bottom:1px solid var(--border)}
.topbar-logo{font-family:var(--font-head);font-size:18px;font-weight:800;color:var(--accent)}
.spacer{flex:1}
.role-badge{font-size:11px;font-weight:700;font-family:var(--font-head);background:var(--accent-light);color:var(--accent);padding:3px 10px;border-radius:20px;border:1px solid rgba(0,200,180,.3)}
.logout-btn{background:var(--danger-light);border:1px solid rgba(248,113,113,.3);border-radius:7px;padding:5px 12px;color:var(--danger);font-family:var(--font-head);font-size:12px;font-weight:600;cursor:pointer}
.main{max-width:860px;margin:0 auto;padding:32px 20px}
h1{font-family:var(--font-head);font-size:22px;font-weight:800;margin-bottom:6px}
.subtitle{color:var(--muted);font-size:14px;margin-bottom:32px}
.tabs{display:flex;gap:4px;margin-bottom:24px;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:4px}
.tab{flex:1;padding:8px;text-align:center;border-radius:7px;cursor:pointer;font-size:13px;font-weight:600;color:var(--hint);font-family:var(--font-head);transition:all .15s}
.tab.active{background:var(--surface2);color:var(--accent)}
.tab-content{display:none}.tab-content.active{display:block}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:24px;margin-bottom:20px}
.card-title{font-family:var(--font-head);font-size:15px;font-weight:700;margin-bottom:16px}
.master-row{display:flex;align-items:center;gap:10px;padding:12px 0;border-bottom:1px solid var(--border)}
.master-row:last-child{border-bottom:none}
.av{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0}
.master-info{flex:1}
.master-name{font-size:14px;font-weight:600}
.master-meta{font-size:12px;color:var(--muted);margin-top:2px}
.badge{display:inline-block;font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;font-family:var(--font-head)}
.badge-tpl{background:var(--accent-light);color:var(--accent);border:1px solid rgba(0,200,180,.25)}
.badge-nopwd{background:var(--danger-light);color:var(--danger);border:1px solid rgba(248,113,113,.2)}
.badge-haspwd{background:rgba(52,211,153,.12);color:#34D399;border:1px solid rgba(52,211,153,.2)}
.btn-sm{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:5px 12px;color:var(--muted);font-family:var(--font-head);font-size:12px;cursor:pointer;transition:all .15s}
.btn-sm:hover{color:var(--text);border-color:var(--accent)}
.btn-del{background:var(--danger-light);border:1px solid rgba(248,113,113,.2);border-radius:6px;padding:5px 10px;color:var(--danger);font-family:var(--font-head);font-size:12px;cursor:pointer}
.add-btn{width:100%;margin-top:12px;padding:10px;background:transparent;border:1px dashed rgba(0,200,180,.4);border-radius:var(--radius-sm);color:var(--accent);font-family:var(--font-head);font-size:13px;font-weight:600;cursor:pointer}
.add-btn:hover{background:var(--accent-light)}
.tpl-row{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border)}
.tpl-row:last-child{border-bottom:none}
.tpl-name{flex:1;font-size:14px;font-weight:500}
.tpl-perms{display:flex;gap:6px;flex-wrap:wrap}
.perm-tag{font-size:10px;font-weight:600;padding:2px 7px;border-radius:12px;font-family:var(--font-head)}
.perm-yes{background:rgba(52,211,153,.12);color:#34D399;border:1px solid rgba(52,211,153,.2)}
.perm-no{background:var(--surface2);color:var(--hint);border:1px solid var(--border)}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:100;padding:16px}
.overlay.hidden{display:none}
.modal{background:var(--surface);border-radius:var(--radius);padding:24px;width:100%;max-width:420px;border:1px solid var(--border)}
.modal h2{font-family:var(--font-head);font-size:16px;font-weight:700;margin-bottom:16px}
.form-row{margin-bottom:12px}
.form-row label{display:block;font-size:11px;font-weight:600;color:var(--muted);margin-bottom:4px;font-family:var(--font-head);text-transform:uppercase}
.form-row input,.form-row select{width:100%;padding:9px 11px;border:1px solid var(--border);border-radius:var(--radius-sm);font-family:var(--font);font-size:13px;background:var(--bg);color:var(--text);outline:none}
.form-row input:focus,.form-row select:focus{border-color:var(--accent)}
.check-row{display:flex;align-items:center;gap:8px;padding:6px 0}
.check-row input[type=checkbox]{width:16px;height:16px;accent-color:var(--accent);cursor:pointer}
.check-row label{font-size:13px;color:var(--text);cursor:pointer}
.modal-footer{display:flex;gap:8px;margin-top:16px;justify-content:flex-end}
.btn{padding:8px 16px;border-radius:var(--radius-sm);cursor:pointer;font-family:var(--font-head);font-size:13px;font-weight:600;border:1px solid var(--border);background:var(--surface);color:var(--text)}
.btn-primary{background:var(--accent);color:#121214;border-color:var(--accent)}
.btn-danger-sm{background:var(--danger-light);color:var(--danger);border:1px solid rgba(248,113,113,.3);padding:8px 16px;border-radius:var(--radius-sm);cursor:pointer;font-family:var(--font-head);font-size:13px;font-weight:600}
.colors{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.color-dot{width:26px;height:26px;border-radius:50%;cursor:pointer;border:3px solid transparent}
.color-dot.selected{border-color:#fff}
.pwd-row{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.pwd-row label{font-size:12px;font-weight:600;color:var(--muted);font-family:var(--font-head);min-width:120px;text-transform:uppercase}
.pwd-row input{flex:1;padding:8px 10px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font);font-size:13px;outline:none}
.pwd-row input:focus{border-color:var(--accent)}
.save-btn{padding:9px 20px;background:var(--accent);color:#121214;border:none;border-radius:var(--radius-sm);font-family:var(--font-head);font-size:13px;font-weight:700;cursor:pointer}
.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1A1916;color:#fff;padding:10px 20px;border-radius:20px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:200}
.toast.show{opacity:1}
.hidden{display:none!important}
.svc-row{display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid var(--border)}
.svc-row:last-child{border-bottom:none}
.svc-name{flex:1;font-size:13px}
.link-wrap{padding:12px;background:var(--accent-light);border-radius:var(--radius-sm);border:1px solid rgba(0,200,180,.2);margin-bottom:12px;display:flex;align-items:center;gap:10px}
.link-url{font-size:13px;color:var(--accent);font-family:var(--font-head);flex:1;word-break:break-all}
.copy-btn{font-size:11px;padding:5px 10px;background:var(--accent);color:#121214;border:none;border-radius:4px;cursor:pointer;font-weight:700;white-space:nowrap}
</style>
</head>
<body>
<div class="topbar">
  <span class="topbar-logo">Body Balance</span>
  <div class="spacer"></div>
  <span class="role-badge">Адмін</span>
  <button class="logout-btn" onclick="doLogout()">Вийти</button>
</div>
<div class="main">
  <h1>Панель адміністратора</h1>
  <p class="subtitle">Управління майстрами, ролями та налаштуваннями</p>
  <div class="tabs">
    <div class="tab active" onclick="switchTab('masters')">Майстри</div>
    <div class="tab" onclick="switchTab('roles')">Шаблони ролей</div>
    <div class="tab" onclick="switchTab('services')">Послуги</div>
    <div class="tab" onclick="switchTab('settings')">Налаштування</div>
  </div>

  <!-- MASTERS TAB -->
  <div class="tab-content active" id="tab-masters">
    <div class="card">
      <div class="card-title">&#128279; Посилання для майстра</div>
      <div class="link-wrap">
        <span class="link-url" id="masterLinkUrl"></span>
        <button class="copy-btn" onclick="copyLink()">Копіювати</button>
      </div>
      <p style="font-size:12px;color:var(--hint)">Надішліть це посилання майстру — без паролю, просто відкрити.</p>
    </div>
    <div class="card">
      <div class="card-title">&#128101; Майстри</div>
      <div id="masterList"></div>
      <button class="add-btn" onclick="openAddMaster()">+ Додати майстра</button>
    </div>
  </div>

  <!-- ROLES TAB -->
  <div class="tab-content" id="tab-roles">
    <div class="card">
      <div class="card-title">&#128274; Шаблони ролей</div>
      <p style="font-size:13px;color:var(--muted);margin-bottom:16px">Шаблон визначає що може робити майстер. Призначається кожному майстру індивідуально.</p>
      <div id="templateList"></div>
      <button class="add-btn" onclick="openAddTemplate()">+ Новий шаблон</button>
    </div>
  </div>

  <!-- SERVICES TAB -->
  <div class="tab-content" id="tab-services">
    <div class="card">
      <div class="card-title">&#128137; Послуги</div>
      <div id="serviceList" style="margin-bottom:10px"></div>
      <div style="display:flex;gap:8px">
        <input id="newSvcName" type="text" placeholder="Назва нової послуги..." style="flex:1;padding:8px 10px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font);font-size:13px;outline:none">
        <button onclick="addService()" style="padding:8px 16px;background:var(--accent);color:#121214;border:none;border-radius:var(--radius-sm);font-family:var(--font-head);font-size:13px;font-weight:700;cursor:pointer">+</button>
      </div>
    </div>
  </div>

  <!-- SETTINGS TAB -->
  <div class="tab-content" id="tab-settings">
    <div class="card">
      <div class="card-title">&#128273; Пароль адміна</div>
      <div class="pwd-row"><label>Адмін</label><input id="pwdAdmin" type="text" placeholder="Новий пароль..."></div>
      <button class="save-btn" onclick="saveAdminPwd()">Зберегти пароль</button>
    </div>
  </div>
</div>

<!-- MASTER MODAL -->
<div class="overlay hidden" id="masterModal">
<div class="modal">
  <h2 id="masterModalTitle">Новий майстер</h2>
  <div class="form-row"><label>Повне ім'я</label><input id="mName" type="text" placeholder="Ім'я Прізвище"></div>
  <div class="form-row"><label>Ініціали (2 літери)</label><input id="mInitials" type="text" maxlength="2" placeholder="ІП"></div>
  <div class="form-row"><label>Колір</label><div class="colors" id="colorPicker"></div></div>
  <div class="form-row"><label>Шаблон ролі</label><select id="mTemplate"></select></div>
  <div class="form-row"><label>Пароль для входу</label><input id="mPassword" type="text" placeholder="Залиште порожнім щоб не змінювати"></div>
  <div class="modal-footer">
    <button class="btn-danger-sm hidden" id="mDelBtn" onclick="deleteMaster()">Видалити</button>
    <button class="btn" onclick="closeMasterModal()">Скасувати</button>
    <button class="btn btn-primary" onclick="saveMaster()">Зберегти</button>
  </div>
</div>
</div>

<!-- TEMPLATE MODAL -->
<div class="overlay hidden" id="templateModal">
<div class="modal">
  <h2 id="tplModalTitle">Новий шаблон</h2>
  <div class="form-row"><label>Назва шаблону</label><input id="tplName" type="text" placeholder="Наприклад: Майстер-старший"></div>
  <p style="font-size:12px;color:var(--muted);margin-bottom:8px;margin-top:4px">Права шаблону:</p>
  <div class="check-row"><input type="checkbox" id="tplViewAll"><label for="tplViewAll">Бачити розклад всіх майстрів</label></div>
  <div class="check-row"><input type="checkbox" id="tplAddAny"><label for="tplAddAny">Додавати клієнтів будь-якому майстру</label></div>
  <div class="check-row"><input type="checkbox" id="tplEditOthers"><label for="tplEditOthers">Редагувати та видаляти чужі записи</label></div>
  <div class="modal-footer">
    <button class="btn-danger-sm hidden" id="tplDelBtn" onclick="deleteTemplate()">Видалити</button>
    <button class="btn" onclick="closeTemplateModal()">Скасувати</button>
    <button class="btn btn-primary" onclick="saveTemplate()">Зберегти</button>
  </div>
</div>
</div>

<div class="toast" id="toast"></div>

<script>
const COLORS=['#00C8B4','#7F77DD','#1D9E75','#BA7517','#D85A30','#378ADD','#D4537E','#F59E0B'];
let masters=[],templates=[],services=[],editingMasterId=null,editingTplId=null,selectedColor=COLORS[0];

function pal(hex){const m={'#00C8B4':{bg:'rgba(0,200,180,.15)',text:'#00C8B4'},'#7F77DD':{bg:'rgba(110,68,255,.15)',text:'#A78BFA'},'#1D9E75':{bg:'rgba(52,211,153,.12)',text:'#34D399'},'#BA7517':{bg:'rgba(251,191,36,.12)',text:'#FCD34D'},'#D85A30':{bg:'rgba(248,113,113,.12)',text:'#FCA5A5'},'#378ADD':{bg:'rgba(96,165,250,.12)',text:'#93C5FD'},'#D4537E':{bg:'rgba(244,114,182,.12)',text:'#F9A8D4'},'#F59E0B':{bg:'rgba(245,158,11,.12)',text:'#FCD34D'}};return m[hex]||{bg:'rgba(255,255,255,.07)',text:'#E4E4E7'};}

function switchTab(name){
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',['masters','roles','services','settings'][i]===name));
  document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
}

async function init(){
  document.getElementById('masterLinkUrl').textContent=window.location.origin+'/master';
  await loadTemplates();
  await loadMasters();
  await loadServices();
  try{const p=await fetch('/api/settings/passwords').then(r=>r.json());document.getElementById('pwdAdmin').value=p.pwd_admin||'';}catch(e){}
}

async function loadTemplates(){
  templates=await fetch('/api/role-templates').then(r=>r.json());
  renderTemplates();
  // Оновити select у модалці майстра
  const sel=document.getElementById('mTemplate');
  if(sel) sel.innerHTML=templates.map(t=>`<option value="${t.id}">${t.name}</option>`).join('');
}

function renderTemplates(){
  const el=document.getElementById('templateList');
  if(!templates.length){el.innerHTML='<p style="color:var(--hint);font-size:13px">Немає шаблонів</p>';return;}
  el.innerHTML=templates.map(t=>{
    const perms=[
      `<span class="perm-tag ${t.can_view_all?'perm-yes':'perm-no'}">Бачить всіх</span>`,
      `<span class="perm-tag ${t.can_add_any?'perm-yes':'perm-no'}">Додає будь-кому</span>`,
      `<span class="perm-tag ${t.can_edit_others?'perm-yes':'perm-no'}">Редагує чужих</span>`,
    ].join('');
    return `<div class="tpl-row"><div style="flex:1"><div class="tpl-name">${t.name}</div><div class="tpl-perms" style="margin-top:4px">${perms}</div></div><button class="btn-sm" onclick="openEditTemplate(${t.id})">&#9999;&#65039;</button></div>`;
  }).join('');
}

async function loadMasters(){
  masters=await fetch('/api/masters').then(r=>r.json());
  const el=document.getElementById('masterList');
  if(!masters.length){el.innerHTML='<p style="color:var(--hint);font-size:13px;padding:8px 0">Майстрів ще немає</p>';return;}
  el.innerHTML=masters.map(m=>{
    const p=pal(m.color);
    const pwdBadge=m.has_password?'<span class="badge badge-haspwd">&#128274; пароль</span>':'<span class="badge badge-nopwd">&#128275; без паролю</span>';
    return `<div class="master-row"><div class="av" style="background:${p.bg};color:${p.text}">${m.initials}</div><div class="master-info"><div class="master-name">${m.name}</div><div class="master-meta"><span class="badge badge-tpl">${m.template_name}</span> ${pwdBadge}</div></div><button class="btn-sm" onclick="openEditMaster(${m.id})">&#9999;&#65039;</button></div>`;
  }).join('');
}

function openAddMaster(){editingMasterId=null;selectedColor=COLORS[0];document.getElementById('masterModalTitle').textContent='Новий майстер';document.getElementById('mDelBtn').classList.add('hidden');document.getElementById('mName').value='';document.getElementById('mInitials').value='';document.getElementById('mPassword').value='';renderColors();document.getElementById('masterModal').classList.remove('hidden');}
function openEditMaster(id){const m=masters.find(x=>x.id==id);if(!m)return;editingMasterId=id;selectedColor=m.color;document.getElementById('masterModalTitle').textContent='Редагувати майстра';document.getElementById('mDelBtn').classList.remove('hidden');document.getElementById('mName').value=m.name;document.getElementById('mInitials').value=m.initials;document.getElementById('mPassword').value='';const tpl=templates.find(t=>t.name===m.template_name);if(tpl)document.getElementById('mTemplate').value=tpl.id;renderColors();document.getElementById('masterModal').classList.remove('hidden');}
function renderColors(){document.getElementById('colorPicker').innerHTML=COLORS.map(c=>`<div class="color-dot${c===selectedColor?' selected':''}" style="background:${c}" onclick="selColor('${c}')"></div>`).join('');}
function selColor(c){selectedColor=c;renderColors();}
function closeMasterModal(){document.getElementById('masterModal').classList.add('hidden');}
function autoInit(n){const w=n.trim().split(/\\s+/);return w.length>=2?(w[0][0]+w[1][0]).toUpperCase():n.slice(0,2).toUpperCase();}
document.addEventListener('DOMContentLoaded',()=>{const el=document.getElementById('mName');if(el)el.addEventListener('input',function(){const a=autoInit(this.value);if(a)document.getElementById('mInitials').value=a;});});

async function saveMaster(){
  const name=document.getElementById('mName').value.trim();
  const initials=(document.getElementById('mInitials').value.trim().toUpperCase()||autoInit(name)).slice(0,2);
  const tplId=parseInt(document.getElementById('mTemplate').value);
  const pwd=document.getElementById('mPassword').value.trim();
  if(!name){alert('Введіть ім\\'я');return;}
  const url=editingMasterId?`/api/masters/${editingMasterId}`:'/api/masters';
  const res=await fetch(url,{method:editingMasterId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,color:selectedColor,initials})});
  if(!res.ok){alert('Помилка');return;}
  const saved=await res.json();
  const mid=saved.id||editingMasterId;
  // Зберегти шаблон
  await fetch(`/api/masters/${mid}/role`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({master_id:mid,template_id:tplId})});
  // Зберегти пароль якщо введено
  if(pwd){await fetch(`/api/masters/${mid}/password`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({master_id:mid,password:pwd})});}
  closeMasterModal();showToast(editingMasterId?'Оновлено':'Додано');await loadMasters();
}

async function deleteMaster(){if(editingMasterId&&confirm(`Видалити майстра?`)){await fetch(`/api/masters/${editingMasterId}`,{method:'DELETE'});closeMasterModal();showToast('Видалено');await loadMasters();}}

// Templates
function openAddTemplate(){editingTplId=null;document.getElementById('tplModalTitle').textContent='Новий шаблон';document.getElementById('tplDelBtn').classList.add('hidden');document.getElementById('tplName').value='';document.getElementById('tplViewAll').checked=false;document.getElementById('tplAddAny').checked=false;document.getElementById('tplEditOthers').checked=false;document.getElementById('templateModal').classList.remove('hidden');}
function openEditTemplate(id){const t=templates.find(x=>x.id==id);if(!t)return;editingTplId=id;document.getElementById('tplModalTitle').textContent='Редагувати шаблон';document.getElementById('tplDelBtn').classList.remove('hidden');document.getElementById('tplName').value=t.name;document.getElementById('tplViewAll').checked=t.can_view_all;document.getElementById('tplAddAny').checked=t.can_add_any;document.getElementById('tplEditOthers').checked=t.can_edit_others;document.getElementById('templateModal').classList.remove('hidden');}
function closeTemplateModal(){document.getElementById('templateModal').classList.add('hidden');}
async function saveTemplate(){
  const name=document.getElementById('tplName').value.trim();if(!name){alert('Введіть назву');return;}
  const data={name,can_view_all:document.getElementById('tplViewAll').checked,can_add_any:document.getElementById('tplAddAny').checked,can_edit_others:document.getElementById('tplEditOthers').checked};
  const url=editingTplId?`/api/role-templates/${editingTplId}`:'/api/role-templates';
  const res=await fetch(url,{method:editingTplId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(!res.ok){alert('Помилка');return;}
  closeTemplateModal();showToast(editingTplId?'Оновлено':'Додано');await loadTemplates();await loadMasters();
}
async function deleteTemplate(){if(!editingTplId||!confirm('Видалити шаблон?'))return;const res=await fetch(`/api/role-templates/${editingTplId}`,{method:'DELETE'});if(!res.ok){const e=await res.json();alert(e.detail||'Помилка');return;}closeTemplateModal();showToast('Видалено');await loadTemplates();}

// Services
async function loadServices(){
  services=await fetch('/api/services').then(r=>r.json());
  const el=document.getElementById('serviceList');
  if(!services.length){el.innerHTML='<p style="color:var(--hint);font-size:13px">Послуг ще немає</p>';return;}
  el.innerHTML=services.map(s=>`<div class="svc-row"><span class="svc-name">${s.name}</span><button onclick="renameService(${s.id},'${s.name.replace(/'/g,"\\'")}\')" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:16px;padding:2px 6px">&#9999;&#65039;</button><button onclick="deleteService(${s.id})" style="background:none;border:none;color:var(--danger);cursor:pointer;font-size:16px;padding:2px 6px">&#10005;</button></div>`).join('');
}
async function addService(){const name=document.getElementById('newSvcName').value.trim();if(!name)return;await fetch('/api/services',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,sort_order:services.length})});document.getElementById('newSvcName').value='';showToast('Послугу додано');await loadServices();}
async function deleteService(id){if(!confirm('Видалити послугу?'))return;await fetch(`/api/services/${id}`,{method:'DELETE'});showToast('Видалено');await loadServices();}
async function renameService(id,oldName){const name=prompt('Нова назва:',oldName);if(!name||name===oldName)return;const svc=services.find(s=>s.id===id);await fetch(`/api/services/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,sort_order:svc?.sort_order||0})});showToast('Оновлено');await loadServices();}

// Settings
async function saveAdminPwd(){const pwd=document.getElementById('pwdAdmin').value.trim();if(!pwd){alert('Введіть пароль');return;}await fetch('/api/settings/password',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pwd})});showToast('Збережено');}

function copyLink(){navigator.clipboard.writeText(window.location.origin+'/master');showToast('Посилання скопійовано!');}
async function doLogout(){await fetch('/api/logout',{method:'POST'});window.location.href='/login';}
function showToast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2500);}
document.getElementById('masterModal').addEventListener('click',e=>{if(e.target===e.currentTarget)closeMasterModal();});
document.getElementById('templateModal').addEventListener('click',e=>{if(e.target===e.currentTarget)closeTemplateModal();});
if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',init);}else{init();}
</script>
</body>
</html>"""

MASTER_HTML = __import__('base64').b64decode('PCFET0NUWVBFIGh0bWw+CjxodG1sIGxhbmc9InVrIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9IlVURi04Ij4KPG1ldGEgbmFtZT0idmlld3BvcnQiIGNvbnRlbnQ9IndpZHRoPWRldmljZS13aWR0aCxpbml0aWFsLXNjYWxlPTEsdmlld3BvcnQtZml0PWNvdmVyIj4KPG1ldGEgbmFtZT0ibW9iaWxlLXdlYi1hcHAtY2FwYWJsZSIgY29udGVudD0ieWVzIj4KPG1ldGEgbmFtZT0iYXBwbGUtbW9iaWxlLXdlYi1hcHAtY2FwYWJsZSIgY29udGVudD0ieWVzIj4KPG1ldGEgbmFtZT0iYXBwbGUtbW9iaWxlLXdlYi1hcHAtc3RhdHVzLWJhci1zdHlsZSIgY29udGVudD0iYmxhY2stdHJhbnNsdWNlbnQiPgo8bWV0YSBuYW1lPSJhcHBsZS1tb2JpbGUtd2ViLWFwcC10aXRsZSIgY29udGVudD0iQm9keSBCYWxhbmNlIj4KPG1ldGEgbmFtZT0idGhlbWUtY29sb3IiIGNvbnRlbnQ9IiMwMEM4QjQiPgo8bGluayByZWw9Im1hbmlmZXN0IiBocmVmPSIvbWFuaWZlc3QuanNvbiI+CjxsaW5rIHJlbD0iYXBwbGUtdG91Y2gtaWNvbiIgaHJlZj0iL2FwaS9pY29uIj4KPHRpdGxlPkJvZHkgQmFsYW5jZSDigJQg0JzRltC5INGA0L7Qt9C60LvQsNC0PC90aXRsZT4KPGxpbmsgaHJlZj0iaHR0cHM6Ly9mb250cy5nb29nbGVhcGlzLmNvbS9jc3MyP2ZhbWlseT1Nb250c2VycmF0OndnaHRANTAwOzYwMDs3MDA7ODAwJmZhbWlseT1JbnRlcjp3Z2h0QDQwMDs1MDA7NjAwJmRpc3BsYXk9c3dhcCIgcmVsPSJzdHlsZXNoZWV0Ij4KPHN0eWxlPgoqe2JveC1zaXppbmc6Ym9yZGVyLWJveDttYXJnaW46MDtwYWRkaW5nOjB9Cjpyb290ey0tYmc6IzEyMTIxNDstLXN1cmZhY2U6IzFFMUUyMjstLXN1cmZhY2UyOiMyMjIyMjc7LS1ib3JkZXI6IzJFMkUzNjstLXRleHQ6I0U0RTRFNzstLW11dGVkOiNBMUExQUE7LS1oaW50OiM3MTcxN0E7LS1hY2NlbnQ6IzAwQzhCNDstLWFjY2VudC1saWdodDpyZ2JhKDAsMjAwLDE4MCwwLjE1KTstLWRhbmdlcjojRjg3MTcxOy0tZGFuZ2VyLWxpZ2h0OnJnYmEoMjQ4LDExMywxMTMsLjEyKTstLXJhZGl1czoxMnB4Oy0tcmFkaXVzLXNtOjhweDstLXNoYWRvdzowIDRweCAxMnB4IHJnYmEoMCwwLDAsLjUpOy0tZm9udDonSW50ZXInLHNhbnMtc2VyaWY7LS1mb250LWhlYWQ6J01vbnRzZXJyYXQnLHNhbnMtc2VyaWZ9Cmh0bWwsYm9keXtoZWlnaHQ6MTAwJTtmb250LWZhbWlseTp2YXIoLS1mb250KTtiYWNrZ3JvdW5kOnZhcigtLWJnKTtjb2xvcjp2YXIoLS10ZXh0KTtmb250LXNpemU6MTRweH0KLmFwcHtkaXNwbGF5OmZsZXg7ZmxleC1kaXJlY3Rpb246Y29sdW1uO2hlaWdodDoxMDB2aH0KLnRvcGJhcntkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2dhcDoxNnB4O3BhZGRpbmc6MCAyMHB4O2hlaWdodDo4OHB4O2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZSk7Ym9yZGVyLWJvdHRvbToxcHggc29saWQgdmFyKC0tYm9yZGVyKTtmbGV4LXNocmluazowfQoudG9wYmFyIGltZ3toZWlnaHQ6NDhweDt3aWR0aDphdXRvfQouc3BhY2Vye2ZsZXg6MX0KLmRhdGUtbmF2e2Rpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7Z2FwOjhweDtwYWRkaW5nOjEycHggMjBweDtmbGV4LXNocmluazowO2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZTIpO2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWJvcmRlcil9Ci5kYXRlLW5hdiBidXR0b257YmFja2dyb3VuZDp2YXIoLS1zdXJmYWNlKTtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7Ym9yZGVyLXJhZGl1czp2YXIoLS1yYWRpdXMtc20pO3BhZGRpbmc6NnB4IDEycHg7Y3Vyc29yOnBvaW50ZXI7Zm9udC1mYW1pbHk6dmFyKC0tZm9udCk7Zm9udC1zaXplOjEzcHg7Y29sb3I6dmFyKC0tdGV4dCl9Ci50b2RheS1idG57YmFja2dyb3VuZDp2YXIoLS1hY2NlbnQpIWltcG9ydGFudDtjb2xvcjojMTIxMjE0IWltcG9ydGFudDtib3JkZXItY29sb3I6dmFyKC0tYWNjZW50KSFpbXBvcnRhbnQ7Zm9udC13ZWlnaHQ6NzAwIWltcG9ydGFudH0KLndlZWstbGFiZWx7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtmb250LXNpemU6MTVweDtmb250LXdlaWdodDo3MDA7Y29sb3I6dmFyKC0tdGV4dCl9Ci5jb250ZW50e2ZsZXg6MTtvdmVyZmxvdzphdXRvO3BhZGRpbmc6MTZweCAyMHB4fQoud2Vlay13cmFwe2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZSk7Ym9yZGVyLXJhZGl1czp2YXIoLS1yYWRpdXMpO2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyKTtvdmVyZmxvdy14OmF1dG99Ci53ZWVrLWdyaWR7ZGlzcGxheTpncmlkO2dyaWQtdGVtcGxhdGUtY29sdW1uczo1MnB4IHJlcGVhdCg3LDFmcil9Ci53aHtwYWRkaW5nOjEwcHggNnB4O3RleHQtYWxpZ246Y2VudGVyO2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7Ym9yZGVyLXJpZ2h0OjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZSk7cG9zaXRpb246c3RpY2t5O3RvcDowO3otaW5kZXg6Mn0KLndoOmxhc3QtY2hpbGR7Ym9yZGVyLXJpZ2h0Om5vbmV9Ci53aC1kYXl7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtmb250LXNpemU6MTFweDtmb250LXdlaWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0ZWQpO3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZTtsZXR0ZXItc3BhY2luZzouNXB4fQoud2gtZGF0ZXtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2ZvbnQtc2l6ZToyMHB4O2ZvbnQtd2VpZ2h0OjgwMDtjb2xvcjp2YXIoLS10ZXh0KX0KLndoLnRvZGF5IC53aC1kYXRle2NvbG9yOnZhcigtLWFjY2VudCl9Ci53aC50b2RheXtib3JkZXItYm90dG9tOjJweCBzb2xpZCB2YXIoLS1hY2NlbnQpfQoudGltZS1jb2x7Zm9udC1zaXplOjEycHg7Y29sb3I6dmFyKC0taGludCk7dGV4dC1hbGlnbjpyaWdodDtwYWRkaW5nOjAgOHB4IDAgMDtib3JkZXItcmlnaHQ6MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7ZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmZsZXgtc3RhcnQ7cGFkZGluZy10b3A6NXB4O2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7aGVpZ2h0OjExMHB4O2ZvbnQtZmFtaWx5OnZhcigtLWZvbnQtaGVhZCl9Ci5zbG90e2JvcmRlci1yaWdodDoxcHggc29saWQgdmFyKC0tYm9yZGVyKTtib3JkZXItYm90dG9tOjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO2hlaWdodDoxMTBweDtwYWRkaW5nOjNweDtjdXJzb3I6cG9pbnRlcjt0cmFuc2l0aW9uOmJhY2tncm91bmQgLjFzfQouc2xvdDpsYXN0LWNoaWxke2JvcmRlci1yaWdodDpub25lfQouc2xvdDpob3ZlcntiYWNrZ3JvdW5kOnZhcigtLWFjY2VudC1saWdodCl9Ci5zbG90LmJyZWFrLXNsb3R7YmFja2dyb3VuZDpyZXBlYXRpbmctbGluZWFyLWdyYWRpZW50KDQ1ZGVnLCMyQTJBMzAsIzJBMkEzMCA1cHgsIzIyMjIyNyA1cHgsIzIyMjIyNyAxMHB4KTtjdXJzb3I6ZGVmYXVsdH0KLnNsb3QuYnJlYWstc2xvdDpob3ZlcntiYWNrZ3JvdW5kOnJlcGVhdGluZy1saW5lYXItZ3JhZGllbnQoNDVkZWcsIzJBMkEzMCwjMkEyQTMwIDVweCwjMjIyMjI3IDVweCwjMjIyMjI3IDEwcHgpfQouYXBwdHtib3JkZXItcmFkaXVzOjZweDtwYWRkaW5nOjRweCA4cHggNHB4IDExcHg7aGVpZ2h0OjEwMCU7ZGlzcGxheTpmbGV4O2ZsZXgtZGlyZWN0aW9uOmNvbHVtbjtqdXN0aWZ5LWNvbnRlbnQ6Y2VudGVyO2N1cnNvcjpwb2ludGVyO2JvcmRlci1sZWZ0OjNweCBzb2xpZCB2YXIoLS1hY2NlbnQpO2JhY2tncm91bmQ6dmFyKC0tYWNjZW50LWxpZ2h0KTtib3gtc2hhZG93OnZhcigtLXNoYWRvdyl9Ci5hcHB0OmhvdmVye2ZpbHRlcjpicmlnaHRuZXNzKDEuMSl9Ci5hcHB0IC5hbntmb250LXNpemU6MTJweDtmb250LXdlaWdodDo3MDA7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtjb2xvcjp2YXIoLS1hY2NlbnQpO3doaXRlLXNwYWNlOm5vd3JhcDtvdmVyZmxvdzpoaWRkZW47dGV4dC1vdmVyZmxvdzplbGxpcHNpc30KLmFwcHQgLmFze2ZvbnQtc2l6ZToxMXB4O2NvbG9yOnZhcigtLW11dGVkKTt3aGl0ZS1zcGFjZTpub3dyYXA7b3ZlcmZsb3c6aGlkZGVuO3RleHQtb3ZlcmZsb3c6ZWxsaXBzaXN9Ci5hcHB0IC5hZHtmb250LXNpemU6MTBweDtjb2xvcjp2YXIoLS1oaW50KX0KLm92ZXJsYXl7cG9zaXRpb246Zml4ZWQ7aW5zZXQ6MDtiYWNrZ3JvdW5kOnJnYmEoMCwwLDAsLjUpO2Rpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7anVzdGlmeS1jb250ZW50OmNlbnRlcjt6LWluZGV4OjEwMDtwYWRkaW5nOjE2cHh9Ci5vdmVybGF5LmhpZGRlbntkaXNwbGF5Om5vbmV9Ci5tb2RhbHtiYWNrZ3JvdW5kOnZhcigtLXN1cmZhY2UpO2JvcmRlci1yYWRpdXM6dmFyKC0tcmFkaXVzKTtwYWRkaW5nOjI0cHg7d2lkdGg6MTAwJTttYXgtd2lkdGg6NDAwcHg7Ym94LXNoYWRvdzowIDhweCAzMnB4IHJnYmEoMCwwLDAsLjYpO2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyKX0KLm1vZGFsIGgye2ZvbnQtZmFtaWx5OnZhcigtLWZvbnQtaGVhZCk7Zm9udC1zaXplOjE2cHg7Zm9udC13ZWlnaHQ6NzAwO21hcmdpbi1ib3R0b206MTZweH0KLmZvcm0tcm93e21hcmdpbi1ib3R0b206MTJweH0KLmZvcm0tcm93IGxhYmVse2Rpc3BsYXk6YmxvY2s7Zm9udC1zaXplOjExcHg7Zm9udC13ZWlnaHQ6NjAwO2NvbG9yOnZhcigtLW11dGVkKTttYXJnaW4tYm90dG9tOjRweDtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZTtsZXR0ZXItc3BhY2luZzouM3B4fQouZm9ybS1yb3cgaW5wdXQsLmZvcm0tcm93IHNlbGVjdCwuZm9ybS1yb3cgdGV4dGFyZWF7d2lkdGg6MTAwJTtwYWRkaW5nOjlweCAxMXB4O2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyKTtib3JkZXItcmFkaXVzOnZhcigtLXJhZGl1cy1zbSk7Zm9udC1mYW1pbHk6dmFyKC0tZm9udCk7Zm9udC1zaXplOjEzcHg7YmFja2dyb3VuZDp2YXIoLS1iZyk7Y29sb3I6dmFyKC0tdGV4dCk7b3V0bGluZTpub25lO3RyYW5zaXRpb246Ym9yZGVyLWNvbG9yIC4xMnN9Ci5mb3JtLXJvdyBpbnB1dDpmb2N1cywuZm9ybS1yb3cgc2VsZWN0OmZvY3Vze2JvcmRlci1jb2xvcjp2YXIoLS1hY2NlbnQpO2JveC1zaGFkb3c6MCAwIDAgMnB4IHJnYmEoMCwyMDAsMTgwLC4xNSl9Ci5mb3JtLTJjb2x7ZGlzcGxheTpncmlkO2dyaWQtdGVtcGxhdGUtY29sdW1uczoxZnIgMWZyO2dhcDoxMnB4fQoubW9kYWwtZm9vdGVye2Rpc3BsYXk6ZmxleDtnYXA6OHB4O21hcmdpbi10b3A6MTZweDtqdXN0aWZ5LWNvbnRlbnQ6ZmxleC1lbmR9Ci5idG57cGFkZGluZzo4cHggMTZweDtib3JkZXItcmFkaXVzOnZhcigtLXJhZGl1cy1zbSk7Y3Vyc29yOnBvaW50ZXI7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtmb250LXNpemU6MTNweDtmb250LXdlaWdodDo2MDA7Ym9yZGVyOjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZSk7Y29sb3I6dmFyKC0tdGV4dCl9Ci5idG46aG92ZXJ7YmFja2dyb3VuZDp2YXIoLS1zdXJmYWNlMil9Ci5idG4tcHJpbWFyeXtiYWNrZ3JvdW5kOnZhcigtLWFjY2VudCkhaW1wb3J0YW50O2NvbG9yOiMxMjEyMTQhaW1wb3J0YW50O2JvcmRlci1jb2xvcjp2YXIoLS1hY2NlbnQpIWltcG9ydGFudH0KLmJ0bi1kYW5nZXJ7YmFja2dyb3VuZDp2YXIoLS1kYW5nZXItbGlnaHQpO2NvbG9yOnZhcigtLWRhbmdlcik7Ym9yZGVyLWNvbG9yOnJnYmEoMjQ4LDExMywxMTMsLjMpfQouZGV0YWlsLWJhcntoZWlnaHQ6NHB4O2JvcmRlci1yYWRpdXM6MnB4O2JhY2tncm91bmQ6dmFyKC0tYWNjZW50KTttYXJnaW4tYm90dG9tOjE2cHh9Ci5kZXRhaWwtcm93e2Rpc3BsYXk6ZmxleDtnYXA6MTBweDttYXJnaW4tYm90dG9tOjhweH0KLmRse2ZvbnQtc2l6ZToxMXB4O2NvbG9yOnZhcigtLW11dGVkKTttaW4td2lkdGg6ODBweDtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZX0KLmR2e2ZvbnQtc2l6ZToxNHB4O2ZvbnQtd2VpZ2h0OjUwMH0KLm1vYmlsZS13cmFwe2Rpc3BsYXk6bm9uZTtmbGV4LWRpcmVjdGlvbjpjb2x1bW47ZmxleDoxO292ZXJmbG93OmhpZGRlbn0KLnNjcm9sbC1jYWxlbmRhcntkaXNwbGF5OmZsZXg7ZmxleDoxO292ZXJmbG93LXg6YXV0bztvdmVyZmxvdy15OmhpZGRlbjtzY3JvbGwtc25hcC10eXBlOnggbWFuZGF0b3J5Oy13ZWJraXQtb3ZlcmZsb3ctc2Nyb2xsaW5nOnRvdWNoO3Njcm9sbGJhci13aWR0aDpub25lfQouc2Nyb2xsLWNhbGVuZGFyOjotd2Via2l0LXNjcm9sbGJhcntkaXNwbGF5Om5vbmV9Ci5jYWwtZGF5LWNvbHtmbGV4OjAgMCBjYWxjKDEwMCUvMyk7c2Nyb2xsLXNuYXAtYWxpZ246c3RhcnQ7ZGlzcGxheTpmbGV4O2ZsZXgtZGlyZWN0aW9uOmNvbHVtbjtib3JkZXItcmlnaHQ6MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7bWluLXdpZHRoOjB9Ci5jYWwtZGF5LWNvbDpsYXN0LWNoaWxke2JvcmRlci1yaWdodDpub25lfQouY2FsLWRheS1oZWFkZXJ7cGFkZGluZzo4cHggNnB4O3RleHQtYWxpZ246Y2VudGVyO2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7YmFja2dyb3VuZDp2YXIoLS1zdXJmYWNlKTtwb3NpdGlvbjpzdGlja3k7dG9wOjA7ei1pbmRleDoyO2ZsZXgtc2hyaW5rOjB9Ci5jYWwtZGF5LW5hbWV7Zm9udC1zaXplOjEwcHg7Zm9udC13ZWlnaHQ6NzAwO2NvbG9yOnZhcigtLW11dGVkKTtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZTtsZXR0ZXItc3BhY2luZzouNXB4fQouY2FsLWRheS1udW17Zm9udC1zaXplOjIycHg7Zm9udC13ZWlnaHQ6ODAwO2ZvbnQtZmFtaWx5OnZhcigtLWZvbnQtaGVhZCk7Y29sb3I6dmFyKC0tdGV4dCk7bGluZS1oZWlnaHQ6MX0KLmNhbC1kYXktY29sLnRvZGF5IC5jYWwtZGF5LW51bXtjb2xvcjp2YXIoLS1hY2NlbnQpfQouY2FsLWRheS1jb2wudG9kYXkgLmNhbC1kYXktaGVhZGVye2JvcmRlci1ib3R0b206MnB4IHNvbGlkIHZhcigtLWFjY2VudCl9Ci5jYWwtc2xvdHN7ZmxleDoxO292ZXJmbG93LXk6YXV0bztwYWRkaW5nLWJvdHRvbTo4MHB4fQouY2FsLXNsb3R7ZGlzcGxheTpmbGV4O2dhcDo0cHg7bWluLWhlaWdodDo1MnB4O2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7cGFkZGluZzo0cHggNHB4IDRweCAycHg7Y3Vyc29yOnBvaW50ZXI7dHJhbnNpdGlvbjpiYWNrZ3JvdW5kIC4xcztwb3NpdGlvbjpyZWxhdGl2ZX0KLmNhbC1zbG90OmhvdmVye2JhY2tncm91bmQ6dmFyKC0tYWNjZW50LWxpZ2h0KX0KLmNhbC1zbG90LXRpbWV7Zm9udC1zaXplOjEwcHg7Y29sb3I6dmFyKC0taGludCk7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTt3aWR0aDozNHB4O2ZsZXgtc2hyaW5rOjA7cGFkZGluZy10b3A6MnB4O3RleHQtYWxpZ246cmlnaHQ7cGFkZGluZy1yaWdodDo0cHh9Ci5jYWwtc2xvdC1jb250ZW50e2ZsZXg6MTttaW4td2lkdGg6MH0KLmNhbC1hcHB0e2JvcmRlci1yYWRpdXM6NXB4O3BhZGRpbmc6NHB4IDZweDtib3JkZXItbGVmdDozcHggc29saWQgdmFyKC0tYWNjZW50KTtiYWNrZ3JvdW5kOnZhcigtLWFjY2VudC1saWdodCk7Y3Vyc29yOnBvaW50ZXJ9Ci5jYWwtYXBwdC1uYW1le2ZvbnQtc2l6ZToxMXB4O2ZvbnQtd2VpZ2h0OjcwMDtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2NvbG9yOnZhcigtLWFjY2VudCk7d2hpdGUtc3BhY2U6bm93cmFwO292ZXJmbG93OmhpZGRlbjt0ZXh0LW92ZXJmbG93OmVsbGlwc2lzfQouY2FsLWFwcHQtc3Zje2ZvbnQtc2l6ZToxMHB4O2NvbG9yOnZhcigtLW11dGVkKTt3aGl0ZS1zcGFjZTpub3dyYXA7b3ZlcmZsb3c6aGlkZGVuO3RleHQtb3ZlcmZsb3c6ZWxsaXBzaXN9Ci5jYWwtYXBwdC1kdXJ7Zm9udC1zaXplOjlweDtjb2xvcjp2YXIoLS1oaW50KX0KLmNhbC1icmVha3tib3JkZXItcmFkaXVzOjVweDtwYWRkaW5nOjRweCA2cHg7YmFja2dyb3VuZDojMkEyQTMwO2JvcmRlci1sZWZ0OjNweCBzb2xpZCAjNzgzNTBGO2ZvbnQtc2l6ZToxMHB4O2NvbG9yOiNGNTlFMEJ9Ci5jYWwtZmFie3Bvc2l0aW9uOmZpeGVkO2JvdHRvbToxNnB4O2xlZnQ6NTAlO3RyYW5zZm9ybTp0cmFuc2xhdGVYKC01MCUpO3BhZGRpbmc6MTNweCAzMnB4O2JhY2tncm91bmQ6dmFyKC0tYWNjZW50KTtjb2xvcjojMTIxMjE0O2JvcmRlcjpub25lO2JvcmRlci1yYWRpdXM6MjRweDtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2ZvbnQtc2l6ZToxNHB4O2ZvbnQtd2VpZ2h0OjcwMDtjdXJzb3I6cG9pbnRlcjtib3gtc2hhZG93OjAgNHB4IDE2cHggcmdiYSgwLDIwMCwxODAsLjQpO3otaW5kZXg6NTA7d2hpdGUtc3BhY2U6bm93cmFwfQoubS1lbXB0eXt0ZXh0LWFsaWduOmNlbnRlcjtwYWRkaW5nOjQwcHggMjBweDtjb2xvcjp2YXIoLS1oaW50KTtmb250LXN0eWxlOml0YWxpY30KLnRvYXN0e3Bvc2l0aW9uOmZpeGVkO2JvdHRvbToyMHB4O2xlZnQ6NTAlO3RyYW5zZm9ybTp0cmFuc2xhdGVYKC01MCUpO2JhY2tncm91bmQ6IzFBMTkxNjtjb2xvcjojZmZmO3BhZGRpbmc6MTBweCAyMHB4O2JvcmRlci1yYWRpdXM6MjBweDtmb250LXNpemU6MTNweDtvcGFjaXR5OjA7dHJhbnNpdGlvbjpvcGFjaXR5IC4ycztwb2ludGVyLWV2ZW50czpub25lO3otaW5kZXg6MjAwfQoudG9hc3Quc2hvd3tvcGFjaXR5OjF9Ci5oaWRkZW57ZGlzcGxheTpub25lIWltcG9ydGFudH0KLmRlc2t0b3Atb25seXtkaXNwbGF5Om5vbmV9CkBtZWRpYShtaW4td2lkdGg6NzY5cHgpey5kZXNrdG9wLW9ubHl7ZGlzcGxheTpmbGV4IWltcG9ydGFudH19CkBtZWRpYShtYXgtd2lkdGg6NzY4cHgpey5jb250ZW50e2Rpc3BsYXk6bm9uZSFpbXBvcnRhbnR9Lm1vYmlsZS13cmFwe2Rpc3BsYXk6ZmxleCFpbXBvcnRhbnR9fQoKLnRpbWUtZ3JpZHtkaXNwbGF5OmZsZXg7ZmxleC13cmFwOndyYXA7Z2FwOjRweDttYXJnaW4tdG9wOjZweH0KLnRpbWUtYnRue3BhZGRpbmc6NHB4IDhweDtiYWNrZ3JvdW5kOnZhcigtLXN1cmZhY2UyKTtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7Ym9yZGVyLXJhZGl1czo1cHg7Zm9udC1zaXplOjExcHg7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtjb2xvcjp2YXIoLS1tdXRlZCk7Y3Vyc29yOnBvaW50ZXJ9Ci50aW1lLWJ0bjpob3ZlcntiYWNrZ3JvdW5kOnZhcigtLWFjY2VudC1saWdodCk7Y29sb3I6dmFyKC0tYWNjZW50KTtib3JkZXItY29sb3I6dmFyKC0tYWNjZW50KX0KLnRpbWUtYnRuLmFjdGl2ZXtiYWNrZ3JvdW5kOnZhcigtLWFjY2VudCk7Y29sb3I6IzEyMTIxNDtib3JkZXItY29sb3I6dmFyKC0tYWNjZW50KX0KCmlucHV0W3R5cGU9ImRhdGUiXTo6LXdlYmtpdC1jYWxlbmRhci1waWNrZXItaW5kaWNhdG9ye2ZpbHRlcjppbnZlcnQoMC43KSBzZXBpYSgxKSBzYXR1cmF0ZSg4KSBodWUtcm90YXRlKDEzMGRlZyk7b3BhY2l0eToxO2N1cnNvcjpwb2ludGVyO3dpZHRoOjE4cHg7aGVpZ2h0OjE4cHh9Cjwvc3R5bGU+CjwvaGVhZD4KPGJvZHk+CjxkaXYgY2xhc3M9ImFwcCI+CjxkaXYgY2xhc3M9InRvcGJhciI+CiAgPGEgaHJlZj0iL2xvZ2luIiBzdHlsZT0iZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlciI+PGltZyBzcmM9ImRhdGE6aW1hZ2Uvc3ZnK3htbDtiYXNlNjQsUEQ5NGJXd2dkbVZ5YzJsdmJqMGlNUzR3SWlCbGJtTnZaR2x1WnowaVZWUkdMVGdpUHo0S1BITjJaeUJwWkQwaVRHRjVaWEpmTVNJZ1pHRjBZUzF1WVcxbFBTSk1ZWGxsY2lBeElpQjRiV3h1Y3owaWFIUjBjRG92TDNkM2R5NTNNeTV2Y21jdk1qQXdNQzl6ZG1jaUlIWnBaWGRDYjNnOUlqQWdNQ0F5TVRVeklERXdPREFpUGdvZ0lEeGtaV1p6UGdvZ0lDQWdQSE4wZVd4bFBnb2dJQ0FnSUNBdVkyeHpMVEVnZXdvZ0lDQWdJQ0FnSUdacGJHdzZJQ013WkdVd1pEWTdDaUFnSUNBZ0lIMEtDaUFnSUNBZ0lDNWpiSE10TWlCN0NpQWdJQ0FnSUNBZ1ptbHNiRG9nSTJVelpUUmxPRHNLSUNBZ0lDQWdmUW9nSUNBZ1BDOXpkSGxzWlQ0S0lDQThMMlJsWm5NK0NpQWdQSEJoZEdnZ1kyeGhjM005SW1Oc2N5MHhJaUJrUFNKTk16ZzBMakl6TERJeE5DNDVPV010TVRBdU9ERXROUzQxTlMweE1DNDRNU3cwTWk0ek1TMHhNQzQ0TVN3ME1pNHpNUzB4TUM0NE1Td3lOUzQ1TlMweU1TNDJNaXd5T0M0eE1TMHlNUzQyTWl3eU9DNHhNUzB4TWk0NU55MDRMalkxTFRFd0xqZ3hMVFEzTGpVM0xURXdMamd4TFRRM0xqVTNMVEUxTGpFMExUVTJMakl5TERRekxqSTBMVFU0TGpNNExEUXpMakkwTFRVNExqTTRMREFzTUMweU1TNDJNaTA0TGpZMUxUTTRMamt5TERZdU5Ea3RNak11TURFc01qQXVNVFF0TVRjdU15dzJNaTQzTFRndU5qVXNPRGd1TmpVc09DNDJOU3d5TlM0NU5Td3lNUzQyTWl3eE5TNHhOQ3d5TVM0Mk1pd3hOUzR4TkMweE1pNDVOeXd4Tnk0ekxUSTFMamsxTERFeUxqazNMVEkxTGprMUxERXlMamszTFRJNExqRXhMVFl1TkRrdE16Z3VPVEl0TWk0eE5pMHpPQzQ1TWkweUxqRTJMVE13TGpJM0xERXlMamszTFRJeExqWXlMRFkzTGpBekxURTFMakUwTERnNExqWTFMRFl1TkRrc01qRXVOaklzTXpJdU5ETXNPVEl1T1Rjc016SXVORE1zT1RJdU9UY3RPQzQyTlN3MkxqUTVMVEU1TGpRMkxESTFMamsxTFRFMUxqRTBMRFF4TGpBNExEUXVNeklzTVRVdU1UUXNNalV1T1RVc016SXVORE1zTXpZdU56WXNNakV1TmpJc01UQXVPREV0TVRBdU9ERXRPQzQyTlMwME55NDFOeTA0TGpZMUxUUTNMalUzYkMweU5DNDBOaTAyTWk0Mk5tTXRNUzR4TmkwekxqUXhMVEl1TVRZdE5pNDROaTB5TGprNExURXdMak0zTFRNdU1qRXRNVE11TmpjdE1qSXVNamt0TnpFdU9ETXRNVEV1TkRndE9UY3VOemdzTVRFdU1Ea3RNall1TmpNc05EY3VOVGN0TVRjdU15dzBOeTQxTnkweE55NHpMRFF4TGpBNExEZ3VOalVzTkRrdU56TXRORGt1TnpNc05Ea3VOek10TkRrdU56TXNNVEF1T0RFdE1UQXVPREVzTVRJdU9UY3RNemd1T1RJc01pNHhOaTAwTkM0ME4xcE5Nekl4TGpVekxEVXlNUzR3T0dNd0xERXdMamd4TERBc01UVXVNVFF0Tmk0ME9Td3hNaTQ1TjNNdE1UUXVORFF0TVRRdU9Ua3RNVEl1T1RjdE1qTXVOemhqTWk0eE5pMHhNaTQ1Tnl3eE1DNDRNUzB5TVM0Mk1pd3hNQzQ0TVMweU1TNDJNaXd3TERBc09DNDJOU3d5TVM0Mk1pdzRMalkxTERNeUxqUXpXaUl2UGdvZ0lEeHdZWFJvSUdOc1lYTnpQU0pqYkhNdE1TSWdaRDBpVFRNNE15NDROU3d5TmprdU1qbHpMVFF1TXpJc016QXVNamN0TWpNdU56Z3NOalF1T0RaakxURTVMalEyTERNMExqVTVMVFEyTGpRNUxEZ3pMakkwTFRRMkxqUTVMREUxTUM0eU4ydzBMak15TFRRdU16SXNOQzR6TWkwMExqTXljekl1TVRZdE1USXVPVGNzT0M0Mk5TMDBNeTR5TkdNMkxqUTVMVE13TGpJM0xESTNMakF6TFRZekxqYzRMRFF4TGpBNExUa3lMamszTERFeUxqSXpMVEkxTGpRc01UUXVNRFV0TlRJdU9UY3NNVEV1T0RrdE56QXVNamRhSWk4K0NpQWdQSEJoZEdnZ1kyeGhjM005SW1Oc2N5MHhJaUJrUFNKTk16TXhMalkxTERnM09DNDJOSE0xTmk0NU1TMHhNRFl1TnpVc056SXVNRFF0TVRNNUxqRTRZekUxTGpFMExUTXlMalF6TERRd0xURXhNUzR6TlN3ek1pNDBNeTB4TmpBdE5pNDROUzAwTkM0d05DMHlNQzQxTkMwM05pNDNOaTAxTWk0NU55MDRPUzQzTXkwek1TNHhOaTB4TWk0ME55MDJNUzQyTWkwNUxqY3pMVGN3TGpJM0xURXVNRGhzTFRJdU1UWXROaTQwT1hNeU5TNHdNeTB5TVM0Mk1pdzRNQzQyTWkwMUxqUXhZelUxTGpVNUxERTJMakl5TERjeExqZ3hMRGcyTGpRNUxEY3hMamd4TERFeE5DNDFPU3d3TERNeExqTXRNeTQ0T1N3eE1EQXVNVGd0TkRNdU1qUXNNVFl5TGpFMkxUUXdMalUxTERZekxqZzJMVGc0TGpJMkxERXlOUzR4TXkwNE9DNHlOaXd4TWpVdU1UTmFJaTgrQ2lBZ1BIQmhkR2dnWTJ4aGMzTTlJbU5zY3kweElpQmtQU0pOTXpJeUxqSXpMRFEzTnk0NU0zTXROUzQwTVMweU9TNHhPU3d4T0M0ek9DMDBNR015TXk0M09DMHhNQzQ0TVN3NE55NDFOeTB4TVM0NE9TdzVOeTR6TFRZNUxqRTVMREV4TGpRMkxUWTNMalE1TFRRNUxqRXhMVFl6TGpVeExUUTVMakV4TFRZekxqVXhMREFzTUN3MU5DNDFPUzB5T0M0MU55dzNNUzQ0TVN3eU9TNDVPU3d4TUM0NE1Td3pOaTQzTmkweE1pNDVOeXc0Tmk0ME9TMDNNUzR6TlN3NU9TNDBOaTAxTXk0d055d3hNUzQzT1MwMU5DNHdOU3d4TlM0eE5DMDJOeTR3TXl3ME15NHlORm9pTHo0S0lDQThjR0YwYUNCamJHRnpjejBpWTJ4ekxURWlJR1E5SWswNE1EWXNOek00WXpVNExEUXdMREV4Tnk0eU9TdzFPUzR4T0N3eE5EUXNOamtzTVRZMkxEWXhMRE15TWl3M05Dd3pNaklzTnpRc05UUXdMRGN5TERZNE1DNHdNaTB4TURZdU9Ea3NOamd3TGpBeUxURXdOaTQ0T1MweU16QXVPVGdzTVRVMkxqRXhMVGM1Tmk0NU55dzFNeTR3TVMwNU1ESXVNRElzTXpBdU9Ea3RNemd0T0MweE1UVXRNalV0TWpNeUxUZ3pJaTgrQ2lBZ1BIQmhkR2dnWTJ4aGMzTTlJbU5zY3kweElpQmtQU0pOT0RJekxqRXNOelUxTGpBMFl5MHlOaTR6TXl3eU55NDNOUzAyTVM0eU9TdzBPUzR3TXkweE1EUXVPRGtzTmpNdU9ETXRNemN1TkRNc01USXVORGt0TnpZdU9USXNNVGd1TnpNdE1URTRMalEyTERFNExqY3pMVEkzTGpFMUxEQXROVE11TWpjdE5pNHdNaTAzT0M0ek5pMHhPQzR3TkMwek1pNHdPQzB4TlM0eU5pMDBPQzR4TXkwek5pNHpNUzAwT0M0eE15MDJNeTR4TkN3d0xUTXdMams0TERFekxqRTJMVFUyTGpRekxETTVMalE1TFRjMkxqTXlMREV4TGpreUxUZ3VOemdzTWpRdU1qY3RNVFV1TXpjc016Y3VNREl0TVRrdU56Y3NNVEl1TnpVdE5DNHpPU3d5Tmk0eE1pMDNMakExTERRd0xqRXhMVGN1T1Rnc05pNDVPUzB4T0M0MUxERTFMamN6TFRRd0xqQXhMREkyTGpJeUxUWTBMalV6TERFd0xqUTVMVEkwTGpVeExESXhMall5TFRRMkxqQXlMRE14TGpreExUWTNMak1zTXk0eU9TMDJMalEzTERndE1UWXNNVFF0TWpZc01UQXVNamt0TVRjdU1UWXNNakF0TXpFc01qUXRNelVzTVRjdU5URXRNVGN1TlRFc016WXRNVFVzTXpZdE1UVXNNQ3d3TFRJdU9Ua3NNaTR5TkMweE15NDBPQ3d4TlM0M05pMHpMalUwTERRdU5UVXROaTQ0T0N3NUxqSTNMVGt1T1Rrc01UUXVNVE10TXpVdU9ETXNOVFV1T1RVdE5UWXVNRGNzTVRBMkxqTTVMVGczTGpZNExERTNOeTQ1TkN3NU1pNDFOU3d4TGpnMUxERTJNUzQwTkN3eU5TNHlNaXd5TURZdU55dzNNQzR3T0N3eE15NHhOaTB4T1M0NE9Dd3hPUzQzTkMwek9DNHhOaXd4T1M0M05DMDFOQzQ0TVN3d0xUSTVMakUwTFRFM0xqUTVMVFV5TGpBMExUVXlMalExTFRZNExqWTVMVEUxTGpFMkxUWXVPVGN0TlRBdU1ERXRNVGN1TkRndE56WXVPRFF0TWpJdU5DMHlNUzR5TWkwekxqZzVMVEkzTFRVdE1qY3ROU3d3TERBc09DNDVOQzB6TGpFNUxESXhMVGNzTVRrdE5pd3lOaTA0TERNM0xURXlMRFExTGpZMExURTJMallzTnpFdU5qRXRNamt1TURJc09UTXVPVGN0TlRJdU9ESXNPUzQwTmkwNUxqY3hMREUwTGpFNUxURTRMalVzTVRRdU1Ua3RNall1TXpjc01DMHhOaTQyTlMweE9TNHhNeTB5T1M0eE5DMDFOeTR6T0Mwek55NDBOeTB5TlM0NU1TMDFMalUxTFRVeUxqWTJMVGd1TXpNdE9EQXVNakV0T0M0ek15MDNNeTQyTkN3d0xURTBNQzQ1T1N3eE1DNDVNaTB5TURVdU5UY3NOREF1T1RndE1pNDBOeTQ1TXkweE5pdzVMVEUyTERrc01Dd3dMRGd1TXpNdE1URXVNek1zTVRVdE1UZ3NPUzA1TERFNUxURTNMRE16TFRJMExEUXlMamM0TFRFNUxqUXpMRGMzTGpjeUxUSTRMakVzTVRRekxqazFMVEk0TGpFc016a3VORGtzTUN3M05pNHdPU3cwTGpFMkxERXdPUzQ0TXl3eE1pNDBPU3cxTWk0Mk5Td3hNaTQwT1N3M09DNDVPQ3d6TWk0ek9DdzNPQzQ1T0N3MU9TNDJOeXd3TERJeUxqSXRNVFl1TURRc05ESXVNek10TkRndU1UTXNOakF1TXpjdE1qTXVORFVzTVRNdU5ESXRORGd1TXpRc01qSXVOamN0TnpRdU5qWXNNamN1TnpVc01qa3VNaXczTGpReExEVTBMak1zTVRndU1qZ3NOelV1TWpjc016SXVOakVzTWpndU56a3NNVGt1TkRNc05ETXVNVGtzTkRJdU56a3NORE11TVRrc056QXVNRGdzTUN3eU1pNHlMVEV3TGpBNExEUTJMakF6TFRNd0xqSXpMRGN4TGpRM1RUVTJNQzQ0Tnl3NE1EZ3VORGRqTFM0NE55NHdOUzB6TGpnM0xUa3VORFl0TXk0NE55MHlNUzQ1TlN3d0xUSXdMamd5TERRdU5Ea3ROVFl1Tmprc01qVXVORFl0TVRFMExqQTFMVFUwTGpjeExERXdMakU0TFRneUxqQTJMRE00TGpZekxUZ3lMakEyTERnMUxqTTBMREFzTWpBdU9ESXNNVEl1TlRRc016Y3VORGNzTXpjdU5qUXNORGt1T1RZc01Ua3VOelFzT1M0M01TdzBNQzR6TVN3eE5DNDFOeXcyTVM0M0xERTBMalUzTERreExqTXlMREFzTVRZd0xqSXhMVEk0TGpJeExESXdOaTQzTFRnMExqWTFMVEl6TGpBMExUSXhMamMwTFRVeUxqQTBMVE00TGpnMkxUZzNMVFV4TGpNMUxUTXlMalV0TVRFdU5UWXROalV1TWkweE55NHpOUzA1T0M0eExURTNMak0xYUMwNExqazFZeTB6TGpBNExEQXROaTR3Tnk0eU5DMDRMamsxTGpZNUxUSTBMalk0TERVNExqYzFMVFF5TGpRMExERXhPQzQwT0MwME1pNDBOQ3d4TXpndU9ETWlMejRLSUNBOFp6NEtJQ0FnSUR4d1lYUm9JR05zWVhOelBTSmpiSE10TWlJZ1pEMGlUVGc1Tmk0eU9DdzJNalV1TURGMkxUWTBMamcxYURNMExqWTFZemd1T1RZc01Dd3hOUzQxTml3eExqVTVMREU1TGpnekxEUXVOemNzTkM0eU5pd3pMakU0TERZdU16a3NOeTR5TkN3MkxqTTVMREV5TGpFNExEQXNNeTR5TnkwdU9URXNOaTR4T1MweUxqY3pMRGd1TnpVdE1TNDRNaXd5TGpVMkxUUXVORFlzTkM0MU9TMDNMamt5TERZdU1EY3RNeTQwTml3eExqUTRMVGN1TnpJc01pNHlNaTB4TWk0M09Td3lMakl5YkRFdU9EVXROV00xTGpBMkxEQXNPUzQwTXk0M01Td3hNeTR4TVN3eUxqRXpMRE11Tmpjc01TNDBNaXcyTGpVeUxETXVORGNzT0M0MU1pdzJMakUyTERJdU1ERXNNaTQyT1N3ekxqQXhMRFV1T1RJc015NHdNU3c1TGpZNExEQXNOUzQyTWkweUxqTXpMREV3TFRZdU9Ua3NNVE11TVRZdE5DNDJOaXd6TGpFMUxURXhMalEzTERRdU56SXRNakF1TkRNc05DNDNNbWd0TXpZdU5WcE5PVEUzTGpjNExEWXdPUzQzTW1neE15NHhObU15TGpReExEQXNOQzR5TWkwdU5ETXNOUzQwTWkweExqTXNNUzR5TFM0NE5pd3hMamd4TFRJdU1UTXNNUzQ0TVMwekxqaHpMUzQyTFRJdU9UTXRNUzQ0TVMwekxqaGpMVEV1TWkwdU9EWXRNeTR3TVMweExqTXROUzQwTWkweExqTm9MVEUwTGpZMGRpMHhOQzQwTldneE1TNDJOMk15TGpRM0xEQXNOQzR5T0MwdU5ESXNOUzQwTWkweExqSTFMREV1TVRRdExqZ3pMREV1TnpFdE1pNHdNaXd4TGpjeExUTXVOVGR6TFM0MU55MHlMamd4TFRFdU56RXRNeTQyTVdNdE1TNHhOQzB1T0MweUxqazFMVEV1TWkwMUxqUXlMVEV1TW1ndE1UQXVNVGwyTXpRdU1qaGFJaTgrQ2lBZ0lDQThjR0YwYUNCamJHRnpjejBpWTJ4ekxUSWlJR1E5SWsweE1ESTVMamM0TERZeU5pNDBPV010TlM0ek1Td3dMVEV3TGpJeExTNDRNeTB4TkM0Mk9DMHlMalV0TkM0ME9DMHhMalkzTFRndU16VXROQzR3TXkweE1TNDJNeTAzTGpBNUxUTXVNamN0TXk0d05pMDFMamd5TFRZdU5qVXROeTQyTkMweE1DNDNPUzB4TGpneUxUUXVNVFF0TWk0M015MDRMalkxTFRJdU56TXRNVE11TlROekxqa3hMVGt1TkRZc01pNDNNeTB4TXk0MU4yTXhMamd5TFRRdU1URXNOQzR6TnkwM0xqWTVMRGN1TmpRdE1UQXVOelVzTXk0eU55MHpMakEyTERjdU1UVXROUzQwTWl3eE1TNDJNeTAzTGpBNUxEUXVORGd0TVM0Mk55dzVMak0wTFRJdU5Td3hOQzQxT1MweUxqVnpNVEF1TVRrdU9ETXNNVFF1TmpRc01pNDFZelF1TkRVc01TNDJOeXc0TGpNeExEUXVNRE1zTVRFdU5UZ3NOeTR3T1N3ekxqSTNMRE11TURZc05TNDRNaXcyTGpZMExEY3VOalFzTVRBdU56VXNNUzQ0TWl3MExqRXhMREl1TnpNc09DNDJNeXd5TGpjekxERXpMalUzY3kwdU9URXNPUzR6T1MweUxqY3pMREV6TGpVell5MHhMamd5TERRdU1UUXROQzR6Tnl3M0xqYzBMVGN1TmpRc01UQXVOemt0TXk0eU55d3pMakEyTFRjdU1UTXNOUzQwTWkweE1TNDFPQ3czTGpBNUxUUXVORFVzTVM0Mk55MDVMak1zTWk0MUxURTBMalUwTERJdU5WcE5NVEF5T1M0Mk9TdzJNRGd1T0dNeUxqQTBMREFzTXk0NU5DMHVNemNzTlM0M0xURXVNVEVzTVM0M05pMHVOelFzTXk0ekxURXVPREVzTkM0Mk15MHpMaklzTVM0ek15MHhMak01TERJdU16WXRNeTR3T1N3ekxqRXROUzR4TGpjMExUSXVNREVzTVM0eE1TMDBMakk0TERFdU1URXROaTQ0TVhNdExqTTNMVFF1T0MweExqRXhMVFl1T0RGakxTNDNOQzB5TGpBeExURXVOemd0TXk0M01TMHpMakV0TlM0eExURXVNek10TVM0ek9TMHlMamczTFRJdU5EVXROQzQyTXkwekxqSXRNUzQzTmkwdU56UXRNeTQyTmkweExqRXhMVFV1TnkweExqRXhjeTB6TGprMExqTTNMVFV1Tnl3eExqRXhMVE11TXl3eExqZ3hMVFF1TmpNc015NHlZeTB4TGpNekxERXVNemt0TWk0ek5pd3pMakE1TFRNdU1TdzFMakV0TGpjMExESXVNREV0TVM0eE1TdzBMakk0TFRFdU1URXNOaTQ0TVhNdU16Y3NOQzQ0TERFdU1URXNOaTQ0TVdNdU56UXNNaTR3TVN3eExqYzNMRE11TnpFc015NHhMRFV1TVN3eExqTXpMREV1TXprc01pNDROeXd5TGpRMkxEUXVOak1zTXk0eWN6TXVOallzTVM0eE1TdzFMamNzTVM0eE1Wb2lMejRLSUNBZ0lEeHdZWFJvSUdOc1lYTnpQU0pqYkhNdE1pSWdaRDBpVFRFeE1ESXVNRFFzTmpJMUxqQXhkaTAyTkM0NE5XZ3pNUzQ1Tm1NM0xqSXpMREFzTVRNdU5Ua3NNUzR6TVN3eE9TNHdPQ3d6TGprMExEVXVOU3d5TGpZekxEa3VOemtzTmk0ek5Td3hNaTQ0T0N3eE1TNHhOaXd6TGpBNUxEUXVPRElzTkM0Mk15d3hNQzQxTml3MExqWXpMREUzTGpJemN5MHhMalUwTERFeUxqVXlMVFF1TmpNc01UY3VNemRqTFRNdU1Ea3NOQzQ0TlMwM0xqTTRMRGd1TlRrdE1USXVPRGdzTVRFdU1qRXROUzQxTERJdU5qTXRNVEV1T0RZc015NDVOQzB4T1M0d09Dd3pMamswYUMwek1TNDVObHBOTVRFeU15NDVNU3cyTURjdU9UWm9PUzR4TjJNekxqQTVMREFzTlM0M09TMHVOVGtzT0M0eE1TMHhMamMyTERJdU16SXRNUzR4Tnl3MExqRXlMVEl1T1RJc05TNDBNaTAxTGpJekxERXVNeTB5TGpNeUxERXVPVFV0TlM0eE5Dd3hMamsxTFRndU5EaHpMUzQyTlMwMkxqQTFMVEV1T1RVdE9DNHpOR010TVM0ekxUSXVNamd0TXk0eExUUXVNREV0TlM0ME1pMDFMakU1TFRJdU16SXRNUzR4TnkwMUxqQXlMVEV1TnpZdE9DNHhNUzB4TGpjMmFDMDVMakUzZGpNd0xqYzJXaUl2UGdvZ0lDQWdQSEJoZEdnZ1kyeGhjM005SW1Oc2N5MHlJaUJrUFNKTk1USXlNQzR5TlN3Mk1qVXVNREYyTFRJNExqUTBiRFVzTVRNdU1EWXRNamt1TkRZdE5Ea3VORGRvTWpNdU1EZHNNVGt1T1RJc016TXVPREZvTFRFekxqUXpiREl3TGpFdE16TXVPREZvTWpFdU1USnNMVEk1TGpJM0xEUTVMalEzTERRdU9ESXRNVE11TURaMk1qZ3VORFJvTFRJeExqZzJXaUl2UGdvZ0lDQWdQSEJoZEdnZ1kyeGhjM005SW1Oc2N5MHlJaUJrUFNKTk1UTTFNaTQzTXl3Mk1qVXVNREYyTFRZMExqZzFhRE0wTGpZMVl6Z3VPVFlzTUN3eE5TNDFOaXd4TGpVNUxERTVMamd6TERRdU56Y3NOQzR5Tml3ekxqRTRMRFl1TXprc055NHlOQ3cyTGpNNUxERXlMakU0TERBc015NHlOeTB1T1RFc05pNHhPUzB5TGpjekxEZ3VOelV0TVM0NE1pd3lMalUyTFRRdU5EWXNOQzQxT1MwM0xqa3lMRFl1TURjdE15NDBOaXd4TGpRNExUY3VOeklzTWk0eU1pMHhNaTQzT1N3eUxqSXliREV1T0RVdE5XTTFMakEyTERBc09TNDBNeTQzTVN3eE15NHhNU3d5TGpFekxETXVOamNzTVM0ME1pdzJMalV5TERNdU5EY3NPQzQxTWl3MkxqRTJMREl1TURFc01pNDJPU3d6TGpBeExEVXVPVElzTXk0d01TdzVMalk0TERBc05TNDJNaTB5TGpNekxERXdMVFl1T1Rrc01UTXVNVFl0TkM0Mk5pd3pMakUxTFRFeExqUTNMRFF1TnpJdE1qQXVORE1zTkM0M01tZ3RNell1TlZwTk1UTTNOQzR5TWl3Mk1Ea3VOekpvTVRNdU1UWmpNaTQwTVN3d0xEUXVNakl0TGpRekxEVXVOREl0TVM0ekxERXVNaTB1T0RZc01TNDRNUzB5TGpFekxERXVPREV0TXk0NGN5MHVOaTB5TGprekxURXVPREV0TXk0NFl5MHhMakl0TGpnMkxUTXVNREV0TVM0ekxUVXVOREl0TVM0emFDMHhOQzQyTkhZdE1UUXVORFZvTVRFdU5qZGpNaTQwTnl3d0xEUXVNamd0TGpReUxEVXVOREl0TVM0eU5Td3hMakUwTFM0NE15d3hMamN4TFRJdU1ESXNNUzQzTVMwekxqVTNjeTB1TlRjdE1pNDRNUzB4TGpjeExUTXVOakZqTFRFdU1UUXRMamd0TWk0NU5TMHhMakl0TlM0ME1pMHhMakpvTFRFd0xqRTVkak0wTGpJNFdpSXZQZ29nSUNBZ1BIQmhkR2dnWTJ4aGMzTTlJbU5zY3kweUlpQmtQU0pOTVRRME5TNHdPU3cyTWpVdU1ERnNNamd1TXpVdE5qUXVPRFZvTWpFdU5EbHNNamd1TXpVc05qUXVPRFZvTFRJeUxqWXhiQzB5TUM0NU5DMDFOQzQwTjJnNExqVXliQzB5TUM0NU5DdzFOQzQwTjJndE1qSXVNak5hVFRFME5qRXVPVFlzTmpFekxqY3hiRFV1TlRZdE1UVXVOelZvTWprdU9ETnNOUzQxTml3eE5TNDNOV2d0TkRBdU9UVmFJaTgrQ2lBZ0lDQThjR0YwYUNCamJHRnpjejBpWTJ4ekxUSWlJR1E5SWsweE5UVTBMallzTmpJMUxqQXhkaTAyTkM0NE5XZ3lNUzQ0Tm5ZME55NDVhREk1TGpJNGRqRTJMamsxYUMwMU1TNHhORm9pTHo0S0lDQWdJRHh3WVhSb0lHTnNZWE56UFNKamJITXRNaUlnWkQwaVRURTJNek11TkRRc05qSTFMakF4YkRJNExqTTFMVFkwTGpnMWFESXhMalE1YkRJNExqTTFMRFkwTGpnMWFDMHlNaTQyTVd3dE1qQXVPVFF0TlRRdU5EZG9PQzQxTW13dE1qQXVPVFFzTlRRdU5EZG9MVEl5TGpJeldrMHhOalV3TGpNc05qRXpMamN4YkRVdU5UWXRNVFV1TnpWb01qa3VPRE5zTlM0MU5pd3hOUzQzTldndE5EQXVPVFZhSWk4K0NpQWdJQ0E4Y0dGMGFDQmpiR0Z6Y3owaVkyeHpMVElpSUdROUlrMHhOelF5TGprMExEWXlOUzR3TVhZdE5qUXVPRFZvTVRjdU9UZHNNekl1T1Rnc016a3VORGRvTFRndU16UjJMVE01TGpRM2FESXhMak14ZGpZMExqZzFhQzB4Tnk0NU4yd3RNekl1T1RndE16a3VORGRvT0M0ek5IWXpPUzQwTjJndE1qRXVNekZhSWk4K0NpQWdJQ0E4Y0dGMGFDQmpiR0Z6Y3owaVkyeHpMVElpSUdROUlrMHhPRGM0TGpjMUxEWXlOaTQwT1dNdE5TNHhPU3d3TFRrdU9Ua3RMamd5TFRFMExqUXhMVEl1TkRZdE5DNDBNaTB4TGpZMExUZ3VNalV0TXk0NU55MHhNUzQwT1MwM0xUTXVNalF0TXk0d01pMDFMamMyTFRZdU5qRXROeTQxTlMweE1DNDNOUzB4TGpjNUxUUXVNVFF0TWk0Mk9TMDRMamN4TFRJdU5qa3RNVE11TnpGekxqZzVMVGt1TlRjc01pNDJPUzB4TXk0M01XTXhMamM1TFRRdU1UUXNOQzR6TVMwM0xqY3lMRGN1TlRVdE1UQXVOelVzTXk0eU5DMHpMakF6TERjdU1EY3ROUzR6Tml3eE1TNDBPUzAyTGprNUxEUXVOREl0TVM0Mk5DdzVMakl5TFRJdU5EWXNNVFF1TkRFdE1pNDBOaXcyTGpNMkxEQXNNVElzTVM0eE1Td3hOaTQ1TVN3ekxqTXpjemd1T1Rjc05TNDBOQ3d4TWk0eE9DdzVMall6YkMweE15NDRMREV5TGpNeVl5MHhMamt5TFRJdU5ERXROQzR3TXkwMExqSTRMVFl1TXpVdE5TNDJMVEl1TXpJdE1TNHpNeTAwTGprekxURXVPVGt0Tnk0NE15MHhMams1TFRJdU1qa3NNQzAwTGpNMUxqTTNMVFl1TWpFc01TNHhNUzB4TGpnMUxqYzBMVE11TkRRc01TNDRNaTAwTGpjM0xETXVNalF0TVM0ek15d3hMalF5TFRJdU16WXNNeTR4TkMwekxqRXNOUzR4TkMwdU56UXNNaTR3TVMweExqRXhMRFF1TWpVdE1TNHhNU3cyTGpjeWN5NHpOeXcwTGpjeExERXVNVEVzTmk0M01tTXVOelFzTWk0d01Td3hMamMzTERNdU56SXNNeTR4TERVdU1UUXNNUzR6TXl3eExqUXlMREl1T1RJc01pNDFMRFF1Tnpjc015NHlOQ3d4TGpnMUxqYzBMRE11T1RJc01TNHhNU3cyTGpJeExERXVNVEVzTWk0NUxEQXNOUzQxTVMwdU5qWXNOeTQ0TXkweExqazVMREl1TXpJdE1TNHpNeXcwTGpRekxUTXVNaXcyTGpNMUxUVXVOakZzTVRNdU9Dd3hNaTR6TW1NdE15NHlNU3cwTGpFMExUY3VNamNzTnk0ek15MHhNaTR4T0N3NUxqVTVjeTB4TUM0MU5Td3pMak00TFRFMkxqa3hMRE11TXpoYUlpOCtDaUFnSUNBOGNHRjBhQ0JqYkdGemN6MGlZMnh6TFRJaUlHUTlJazB4T1RZekxqUXpMRFl3T0M0MU1tZ3pNaTQwTTNZeE5pNDBPV2d0TlRNdU9USjJMVFkwTGpnMWFEVXlMamN4ZGpFMkxqUTVhQzB6TVM0eU1uWXpNUzQ0TjFwTk1UazJNUzQ1TkN3MU9EUXVNalZvTWpndU9URjJNVFV1TnpWb0xUSTRMamt4ZGkweE5TNDNOVm9pTHo0S0lDQThMMmMrQ2p3dmMzWm5QZz09IiBhbHQ9IkJvZHkgQmFsYW5jZSI+PC9hPgogIDxkaXYgY2xhc3M9InNwYWNlciI+PC9kaXY+CiAgPHNwYW4gaWQ9Im1hc3Rlck5hbWVCYWRnZSIgc3R5bGU9ImZvbnQtc2l6ZToxM3B4O2ZvbnQtd2VpZ2h0OjYwMDtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2NvbG9yOnZhcigtLWFjY2VudCkiPjwvc3Bhbj4KPC9kaXY+CjxkaXYgY2xhc3M9ImRhdGUtbmF2Ij4KICA8YnV0dG9uIG9uY2xpY2s9ImNoYW5nZVBlcmlvZCgtMSkiPiYjODI0OTs8L2J1dHRvbj4KICA8YnV0dG9uIGNsYXNzPSJ0b2RheS1idG4iIGlkPSJ0b2RheUJ0biIgb25jbGljaz0iZ29Ub2RheSgpIj4mIzEyODE5Nzsg0KHRjNC+0LPQvtC00L3RljwvYnV0dG9uPgogIDxkaXYgc3R5bGU9InBvc2l0aW9uOnJlbGF0aXZlO2Rpc3BsYXk6aW5saW5lLWJsb2NrIj4KICAgIDxidXR0b24gb25jbGljaz0ib3BlbkRhdGVQaWNrZXIoKSIgc3R5bGU9ImJhY2tncm91bmQ6dmFyKC0tc3VyZmFjZSk7Ym9yZGVyOjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO2JvcmRlci1yYWRpdXM6dmFyKC0tcmFkaXVzLXNtKTtwYWRkaW5nOjZweCAxMnB4O2N1cnNvcjpwb2ludGVyO2ZvbnQtc2l6ZToxNnB4O2NvbG9yOnZhcigtLWFjY2VudCkiIHRpdGxlPSLQntCx0YDQsNGC0Lgg0LTQsNGC0YMiPiYjMTI4MTk3OzwvYnV0dG9uPgogICAgPGlucHV0IHR5cGU9ImRhdGUiIGlkPSJkYXRlUGlja2VyIiBzdHlsZT0icG9zaXRpb246YWJzb2x1dGU7b3BhY2l0eTowO3RvcDowO2xlZnQ6MDt3aWR0aDoxMDAlO2hlaWdodDoxMDAlO2N1cnNvcjpwb2ludGVyIiBvbmNoYW5nZT0iZ29Ub0RhdGUodGhpcy52YWx1ZSkiPgogIDwvZGl2PgogIDxidXR0b24gb25jbGljaz0iY2hhbmdlUGVyaW9kKDEpIj4mIzgyNTA7PC9idXR0b24+CiAgPHNwYW4gY2xhc3M9IndlZWstbGFiZWwiIGlkPSJ3ZWVrTGFiZWwiIHN0eWxlPSJmbGV4OjEiPjwvc3Bhbj4KICA8ZGl2IGNsYXNzPSJkZXNrdG9wLW9ubHkiIHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2FwOjRweDttYXJnaW4tbGVmdDo4cHgiPgogICAgPGJ1dHRvbiBpZD0idjEiIG9uY2xpY2s9InNldFZpZXcoMSkiIHN0eWxlPSJwYWRkaW5nOjVweCAxMHB4O2JvcmRlci1yYWRpdXM6NnB4O2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyKTtiYWNrZ3JvdW5kOnZhcigtLXN1cmZhY2UpO2NvbG9yOnZhcigtLW11dGVkKTtmb250LXNpemU6MTJweDtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2ZvbnQtd2VpZ2h0OjYwMDtjdXJzb3I6cG9pbnRlciI+MdC0PC9idXR0b24+CiAgICA8YnV0dG9uIGlkPSJ2MyIgb25jbGljaz0ic2V0VmlldygzKSIgc3R5bGU9InBhZGRpbmc6NXB4IDEwcHg7Ym9yZGVyLXJhZGl1czo2cHg7Ym9yZGVyOjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZSk7Y29sb3I6dmFyKC0tbXV0ZWQpO2ZvbnQtc2l6ZToxMnB4O2ZvbnQtZmFtaWx5OnZhcigtLWZvbnQtaGVhZCk7Zm9udC13ZWlnaHQ6NjAwO2N1cnNvcjpwb2ludGVyIj4z0LQ8L2J1dHRvbj4KICAgIDxidXR0b24gaWQ9InY3IiBvbmNsaWNrPSJzZXRWaWV3KDcpIiBzdHlsZT0icGFkZGluZzo1cHggMTBweDtib3JkZXItcmFkaXVzOjZweDtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7YmFja2dyb3VuZDp2YXIoLS1hY2NlbnQpO2NvbG9yOiMxMjEyMTQ7Ym9yZGVyLWNvbG9yOnZhcigtLWFjY2VudCk7Zm9udC1zaXplOjEycHg7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtmb250LXdlaWdodDo2MDA7Y3Vyc29yOnBvaW50ZXIiPjfQtDwvYnV0dG9uPgogIDwvZGl2Pgo8L2Rpdj4KPGRpdiBjbGFzcz0iY29udGVudCI+CiAgPGRpdiBjbGFzcz0id2Vlay13cmFwIj48ZGl2IGNsYXNzPSJ3ZWVrLWdyaWQiIGlkPSJ3ZWVrR3JpZCI+PC9kaXY+PC9kaXY+CjwvZGl2Pgo8ZGl2IGNsYXNzPSJtb2JpbGUtd3JhcCI+CiAgPGRpdiBjbGFzcz0ic2Nyb2xsLWNhbGVuZGFyIiBpZD0ic2Nyb2xsQ2FsIj4KICAgIDwhLS0gR2VuZXJhdGVkIGJ5IEpTIC0tPgogIDwvZGl2Pgo8L2Rpdj4KPGRpdiBjbGFzcz0idG9hc3QiIGlkPSJ0b2FzdCI+PC9kaXY+CjxzY3JpcHQ+CmNvbnN0IEhPVVJTPUFycmF5LmZyb20oe2xlbmd0aDoxMH0sKF8saSk9PmAke1N0cmluZyhpKzkpLnBhZFN0YXJ0KDIsIjAiKX06MDBgKTsKY29uc3QgREFZUz1bItCd0LQiLCLQn9C9Iiwi0JLRgiIsItCh0YAiLCLQp9GCIiwi0J/RgiIsItCh0LEiXTsKY29uc3QgTU9OVEhTPVsi0YHRltGH0L3RjyIsItC70Y7RgtC+0LPQviIsItCx0LXRgNC10LfQvdGPIiwi0LrQstGW0YLQvdGPIiwi0YLRgNCw0LLQvdGPIiwi0YfQtdGA0LLQvdGPIiwi0LvQuNC/0L3RjyIsItGB0LXRgNC/0L3RjyIsItCy0LXRgNC10YHQvdGPIiwi0LbQvtCy0YLQvdGPIiwi0LvQuNGB0YLQvtC/0LDQtNCwIiwi0LPRgNGD0LTQvdGPIl07CmxldCBhcHBvaW50bWVudHM9W10sYnJlYWtzPVtdLG1hc3RlcklkPW51bGwsc2VydmljZXM9W107CmxldCB2aWV3RGF5cz03LHBlcmlvZFN0YXJ0PWdldE1vbmRheShuZXcgRGF0ZSgpKTsKbGV0IHdlZWtTdGFydD1nZXRNb25kYXkobmV3IERhdGUoKSk7CmxldCBlZGl0aW5nSWQ9bnVsbCxtb2JpbGVEYXk9bmV3IERhdGUoKTsKCmZ1bmN0aW9uIHNldFZpZXcobil7CiAgdmlld0RheXM9bjsKICBpZihuPT09MSkgcGVyaW9kU3RhcnQ9bmV3IERhdGUobW9iaWxlRGF5KTsKICBlbHNlIGlmKG49PT0zKXsgY29uc3QgZD1uZXcgRGF0ZShtb2JpbGVEYXkpOyBkLnNldERhdGUoZC5nZXREYXRlKCktMSk7IHBlcmlvZFN0YXJ0PWQ7IH0KICBlbHNlIHBlcmlvZFN0YXJ0PWdldE1vbmRheShuZXcgRGF0ZSgpKTsKICB3ZWVrU3RhcnQ9bmV3IERhdGUocGVyaW9kU3RhcnQpOwogIFsidjEiLCJ2MyIsInY3Il0uZm9yRWFjaChpZD0+ewogICAgY29uc3QgZWw9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoaWQpOwogICAgaWYoZWwpe2VsLnN0eWxlLmJhY2tncm91bmQ9aWQ9PT0idiIrbj8idmFyKC0tYWNjZW50KSI6InZhcigtLXN1cmZhY2UpIjtlbC5zdHlsZS5jb2xvcj1pZD09PSJ2IituPyIjMTIxMjE0IjoidmFyKC0tbXV0ZWQpIjtlbC5zdHlsZS5ib3JkZXJDb2xvcj1pZD09PSJ2IituPyJ2YXIoLS1hY2NlbnQpIjoidmFyKC0tYm9yZGVyKSI7fQogIH0pOwogIGxvYWRXZWVrKCk7Cn0KZnVuY3Rpb24gY2hhbmdlUGVyaW9kKGQpe3BlcmlvZFN0YXJ0PWFkZERheXMocGVyaW9kU3RhcnQsZCp2aWV3RGF5cyk7d2Vla1N0YXJ0PW5ldyBEYXRlKHBlcmlvZFN0YXJ0KTtsb2FkV2VlaygpO30KZnVuY3Rpb24gZ2V0TW9uZGF5KGQpe2NvbnN0IHI9bmV3IERhdGUoZCksZGF5PXIuZ2V0RGF5KCksZGlmZj1yLmdldERhdGUoKS1kYXkrKGRheT09PTA/LTY6MSk7ci5zZXREYXRlKGRpZmYpO3Iuc2V0SG91cnMoMCwwLDAsMCk7cmV0dXJuIHI7fQpmdW5jdGlvbiBpc29EYXRlKGQpe3JldHVybiBkLnRvSVNPU3RyaW5nKCkuc2xpY2UoMCwxMCk7fQpmdW5jdGlvbiBhZGREYXlzKGQsbil7Y29uc3Qgcj1uZXcgRGF0ZShkKTtyLnNldERhdGUoci5nZXREYXRlKCkrbik7cmV0dXJuIHI7fQpmdW5jdGlvbiBmbXREYXRlKGlzbyl7Y29uc3RbeSxtLGRheV09aXNvLnNwbGl0KCItIik7cmV0dXJuIGAke3BhcnNlSW50KGRheSl9ICR7TU9OVEhTW3BhcnNlSW50KG0pLTFdfWA7fQpmdW5jdGlvbiB0b01pbih0KXtjb25zdFtoLG1dPXQuc3BsaXQoIjoiKS5tYXAoTnVtYmVyKTtyZXR1cm4gaCo2MCttO30KYXN5bmMgZnVuY3Rpb24gbG9hZFdlZWsoKXsKICBpZighbWFzdGVySWQpewogICAgY29uc3QgbWU9YXdhaXQgZmV0Y2goIi9hcGkvbWUiKS50aGVuKHI9PnIuanNvbigpKTsKICAgIGlmKG1lLm1hc3Rlcl9pZCkgbWFzdGVySWQ9bWUubWFzdGVyX2lkOwogICAgZWxzZSB7IGNvbnN0IG1zPWF3YWl0IGZldGNoKCIvYXBpL21hc3RlcnMiKS50aGVuKHI9PnIuanNvbigpKTtpZihtcy5sZW5ndGgpbWFzdGVySWQ9bXNbMF0uaWQ7IH0KICB9CiAgaWYoIW1hc3RlcklkKXJldHVybjsKICAvLyDQntC90L7QstC70Y7RlNC80L4g0ZbQvCfRjyDQvNCw0LnRgdGC0YDQsCDQsiDRhdC10LTQtdGA0ZYKICBpZighd2luZG93Ll9tYXN0ZXJOYW1lKXsKICAgIGNvbnN0IG1lPWF3YWl0IGZldGNoKCIvYXBpL21lIikudGhlbihyPT5yLmpzb24oKSk7CiAgICBpZihtZS5uYW1lKXt3aW5kb3cuX21hc3Rlck5hbWU9bWUubmFtZTtjb25zdCBiPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJtYXN0ZXJOYW1lQmFkZ2UiKTtpZihiKWIudGV4dENvbnRlbnQ9bWUubmFtZTt9CiAgfQogIC8vINCe0L3QvtCy0LvRjtGU0LzQviDQutC90L7Qv9C60YMg0KHRjNC+0LPQvtC00L3RlgogIChmdW5jdGlvbigpewogICAgY29uc3Qgbm93PW5ldyBEYXRlKCk7CiAgICBjb25zdCBkYXlzPVsi0J3QtCIsItCf0L0iLCLQktGCIiwi0KHRgCIsItCn0YIiLCLQn9GCIiwi0KHQsSJdOwogICAgY29uc3QgbW9udGhzPVsi0YHRltGHIiwi0LvRjtGCIiwi0LHQtdGAIiwi0LrQstGWIiwi0YLRgNCwIiwi0YfQtdGAIiwi0LvQuNC/Iiwi0YHQtdGAIiwi0LLQtdGAIiwi0LbQvtCyIiwi0LvQuNGBIiwi0LPRgNGDIl07CiAgICBjb25zdCBidG49ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoInRvZGF5QnRuIik7CiAgICBpZihidG4pIGJ0bi5pbm5lckhUTUw9IiYjMTI4MTk3OyAiK2RheXNbbm93LmdldERheSgpXSsiLCAiK25vdy5nZXREYXRlKCkrIiAiK21vbnRoc1tub3cuZ2V0TW9udGgoKV07CiAgfSkoKTsKICBpZighc2VydmljZXMubGVuZ3RoKXtzZXJ2aWNlcz1hd2FpdCBmZXRjaCgiL2FwaS9zZXJ2aWNlcyIpLnRoZW4ocj0+ci5qc29uKCkpO3VwZGF0ZURhdGFsaXN0KCk7fQogIGNvbnN0IGlzTW9iaWxlPXdpbmRvdy5pbm5lcldpZHRoPD02NDA7CiAgY29uc3QgbG9hZERheXM9aXNNb2JpbGU/MTQ6dmlld0RheXM7CiAgY29uc3QgbG9hZFN0YXJ0PWlzTW9iaWxlP2FkZERheXMocGVyaW9kU3RhcnQsLTEpOnBlcmlvZFN0YXJ0OwogIGNvbnN0IGRheXM9QXJyYXkuZnJvbSh7bGVuZ3RoOmxvYWREYXlzfSwoXyxpKT0+aXNvRGF0ZShhZGREYXlzKGxvYWRTdGFydCxpKSkpOwogIGNvbnN0IGZyb209ZGF5c1swXSx0bz1kYXlzW2RheXMubGVuZ3RoLTFdOwogIGNvbnN0W2FwLGJyXT1hd2FpdCBQcm9taXNlLmFsbChbCiAgICBmZXRjaChgL2FwaS9hcHBvaW50bWVudHMvcmFuZ2U/bWFzdGVyX2lkPSR7bWFzdGVySWR9JmZyb21fZGF0ZT0ke2Zyb219JnRvX2RhdGU9JHt0b31gKS50aGVuKHI9PnIuanNvbigpKSwKICAgIGZldGNoKGAvYXBpL2JyZWFrcy9yYW5nZT9tYXN0ZXJfaWQ9JHttYXN0ZXJJZH0mZnJvbV9kYXRlPSR7ZnJvbX0mdG9fZGF0ZT0ke3RvfWApLnRoZW4ocj0+ci5qc29uKCkpLAogIF0pOwogIGFwcG9pbnRtZW50cz1hcDticmVha3M9YnI7cmVuZGVyQWxsKCk7Cn0KZnVuY3Rpb24gdXBkYXRlRGF0YWxpc3QoKXsKICBjb25zdCBzZWw9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZTZXJ2aWNlIik7CiAgaWYoc2VsJiZzZXJ2aWNlcy5sZW5ndGgpIHNlbC5pbm5lckhUTUw9c2VydmljZXMubWFwKHM9PmA8b3B0aW9uIHZhbHVlPSIke3MubmFtZX0iPiR7cy5uYW1lfTwvb3B0aW9uPmApLmpvaW4oIiIpOwp9CmZ1bmN0aW9uIHJlbmRlckFsbCgpewogIGNvbnN0IGRheXM9QXJyYXkuZnJvbSh7bGVuZ3RoOnZpZXdEYXlzfSwoXyxpKT0+YWRkRGF5cyhwZXJpb2RTdGFydCxpKSk7CiAgY29uc3QgdG9kYXk9aXNvRGF0ZShuZXcgRGF0ZSgpKTsKICBjb25zdCBmPWZtdERhdGUoaXNvRGF0ZShkYXlzWzBdKSksdD12aWV3RGF5cz4xP2ZtdERhdGUoaXNvRGF0ZShkYXlzW2RheXMubGVuZ3RoLTFdKSk6IiI7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoIndlZWtMYWJlbCIpLnRleHRDb250ZW50PXZpZXdEYXlzPT09MT9gJHtEQVlTW2RheXNbMF0uZ2V0RGF5KCldfSwgJHtmbXREYXRlKGlzb0RhdGUoZGF5c1swXSkpfWA6KGAke2Z9IOKAlCAke3R9YCk7CiAgcmVuZGVyR3JpZChkYXlzLHRvZGF5KTsKICByZW5kZXJTY3JvbGxDYWxlbmRhcigpOwp9CgpmdW5jdGlvbiByZW5kZXJHcmlkKGRheXMsdG9kYXkpewogIGNvbnN0IGc9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoIndlZWtHcmlkIik7CiAgbGV0IGg9YDxkaXYgY2xhc3M9IndoIj48L2Rpdj5gOwogIGRheXMuZm9yRWFjaChkPT57Y29uc3QgaXNvPWlzb0RhdGUoZCksaVQ9aXNvPT09dG9kYXk7aCs9YDxkaXYgY2xhc3M9IndoJHtpVD8iIHRvZGF5IjoiIn0iPjxkaXYgY2xhc3M9IndoLWRheSI+JHtEQVlTW2QuZ2V0RGF5KCldfTwvZGl2PjxkaXYgY2xhc3M9IndoLWRhdGUiPiR7ZC5nZXREYXRlKCl9PC9kaXY+PC9kaXY+YDt9KTsKICBIT1VSUy5mb3JFYWNoKGhyPT57CiAgICBoKz1gPGRpdiBjbGFzcz0idGltZS1jb2wiPiR7aHJ9PC9kaXY+YDsKICAgIGRheXMuZm9yRWFjaChkPT57CiAgICAgIGNvbnN0IGlzbz1pc29EYXRlKGQpOwogICAgICBjb25zdCBpc0I9YnJlYWtzLnNvbWUoYj0+Yi5icmVha19kYXRlPT09aXNvJiZ0b01pbihiLnN0YXJ0X3RpbWUpPD10b01pbihocikmJnRvTWluKGIuZW5kX3RpbWUpPnRvTWluKGhyKSk7CiAgICAgIGNvbnN0IGFwPWFwcG9pbnRtZW50cy5maW5kKGE9PmEuYXBwdF9kYXRlPT09aXNvJiZhLnN0YXJ0X3RpbWU9PT1ocik7CiAgICAgIGlmKGlzQil7aCs9YDxkaXYgY2xhc3M9InNsb3QgYnJlYWstc2xvdCI+PC9kaXY+YDt9CiAgICAgIGVsc2UgaWYoYXApe2grPWA8ZGl2IGNsYXNzPSJzbG90Ij48ZGl2IGNsYXNzPSJhcHB0IiBvbmNsaWNrPSJvcGVuRGV0YWlsKCR7YXAuaWR9KSI+PGRpdiBjbGFzcz0iYW4iPiR7YXAuY2xpZW50X25hbWV9PC9kaXY+PGRpdiBjbGFzcz0iYXMiPiR7YXAuc2VydmljZX08L2Rpdj48ZGl2IGNsYXNzPSJhZCI+JHthcC5kdXJhdGlvbl9taW59INGF0LI8L2Rpdj48L2Rpdj48L2Rpdj5gO30KICAgICAgZWxzZXtoKz1gPGRpdiBjbGFzcz0ic2xvdCIgb25jbGljaz0ib3BlbkFkZE9uU2xvdCgnJHtpc299JywnJHtocn0nKSI+PC9kaXY+YDt9CiAgICB9KTsKICB9KTsKICBnLmlubmVySFRNTD1oOwp9CmZ1bmN0aW9uIHJlbmRlck1vYmlsZURheXMoZGF5cyx0b2RheSl7fQpmdW5jdGlvbiByZW5kZXJNb2JpbGVMaXN0KCl7fQoKZnVuY3Rpb24gcmVuZGVyU2Nyb2xsQ2FsZW5kYXIoKXsKICBjb25zdCBjYWw9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoInNjcm9sbENhbCIpOwogIGlmKCFjYWwpcmV0dXJuOwogIGNvbnN0IHRvZGF5PWlzb0RhdGUobmV3IERhdGUoKSk7CiAgLy8gU2hvdyAxNCBkYXlzIHN0YXJ0aW5nIGZyb20gcGVyaW9kU3RhcnQgLSAxIChzbyBjdXJyZW50IGRheSBpcyBpbiBtaWRkbGUgY29sdW1uKQogIGNvbnN0IHN0YXJ0RGF5PWFkZERheXMocGVyaW9kU3RhcnQsLTEpOwogIGNvbnN0IG51bURheXM9MTQ7CiAgY29uc3QgaG91cnM9QXJyYXkuZnJvbSh7bGVuZ3RoOjl9LChfLGkpPT5TdHJpbmcoaSsxMCkucGFkU3RhcnQoMiwiMCIpKyI6MDAiKTsKCiAgLy8gUmVtb3ZlIG9sZCBmYWIgaWYgZXhpc3RzCiAgY29uc3Qgb2xkRmFiPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJjYWxGYWIiKTsKICBpZihvbGRGYWIpb2xkRmFiLnJlbW92ZSgpOwoKICBjYWwuaW5uZXJIVE1MPUFycmF5LmZyb20oe2xlbmd0aDpudW1EYXlzfSwoXyxkaSk9PnsKICAgIGNvbnN0IGQ9YWRkRGF5cyhzdGFydERheSxkaSk7CiAgICBjb25zdCBpc289aXNvRGF0ZShkKTsKICAgIGNvbnN0IGlzVG9kYXk9aXNvPT09dG9kYXk7CiAgICBjb25zdCBkYT1hcHBvaW50bWVudHMuZmlsdGVyKGE9PmEuYXBwdF9kYXRlPT09aXNvKTsKICAgIGNvbnN0IGRiPWJyZWFrcy5maWx0ZXIoYj0+Yi5icmVha19kYXRlPT09aXNvKTsKICAgIGNvbnN0IHNsb3RzPWhvdXJzLm1hcChocj0+ewogICAgICBjb25zdCBpc0I9ZGIuc29tZShiPT50b01pbihiLnN0YXJ0X3RpbWUpPD10b01pbihocikmJnRvTWluKGIuZW5kX3RpbWUpPnRvTWluKGhyKSk7CiAgICAgIGNvbnN0IGFwPWRhLmZpbmQoYT0+YS5zdGFydF90aW1lPT09aHIpOwogICAgICBsZXQgaW5uZXI9IiI7CiAgICAgIGlmKGlzQikgaW5uZXI9YDxkaXYgY2xhc3M9ImNhbC1icmVhayI+0J/QtdGA0LXRgNCy0LA8L2Rpdj5gOwogICAgICBlbHNlIGlmKGFwKSBpbm5lcj1gPGRpdiBjbGFzcz0iY2FsLWFwcHQiIG9uY2xpY2s9ImV2ZW50LnN0b3BQcm9wYWdhdGlvbigpO29wZW5EZXRhaWwoJHthcC5pZH0pIj48ZGl2IGNsYXNzPSJjYWwtYXBwdC1uYW1lIj4ke2FwLmNsaWVudF9uYW1lfTwvZGl2PjxkaXYgY2xhc3M9ImNhbC1hcHB0LXN2YyI+JHthcC5zZXJ2aWNlfTwvZGl2PjxkaXYgY2xhc3M9ImNhbC1hcHB0LWR1ciI+JHthcC5kdXJhdGlvbl9taW590YXQsjwvZGl2PjwvZGl2PmA7CiAgICAgIHJldHVybiBgPGRpdiBjbGFzcz0iY2FsLXNsb3QiIG9uY2xpY2s9Im9wZW5BZGRPblNsb3QoJyR7aXNvfScsJyR7aHJ9JykiPjxkaXYgY2xhc3M9ImNhbC1zbG90LXRpbWUiPiR7aHJ9PC9kaXY+PGRpdiBjbGFzcz0iY2FsLXNsb3QtY29udGVudCI+JHtpbm5lcn08L2Rpdj48L2Rpdj5gOwogICAgfSkuam9pbigiIik7CiAgICByZXR1cm4gYDxkaXYgY2xhc3M9ImNhbC1kYXktY29sJHtpc1RvZGF5PyIgdG9kYXkiOiIifSI+CiAgICAgIDxkaXYgY2xhc3M9ImNhbC1kYXktaGVhZGVyIj48ZGl2IGNsYXNzPSJjYWwtZGF5LW5hbWUiPiR7REFZU1tkLmdldERheSgpXX08L2Rpdj48ZGl2IGNsYXNzPSJjYWwtZGF5LW51bSI+JHtkLmdldERhdGUoKX08L2Rpdj48L2Rpdj4KICAgICAgPGRpdiBjbGFzcz0iY2FsLXNsb3RzIj4ke3Nsb3RzfTwvZGl2PgogICAgPC9kaXY+YDsKICB9KS5qb2luKCIiKTsKCiAgLy8gU2Nyb2xsIHRvIHRvZGF5ICgzcmQgY29sdW1uID0gaW5kZXggMSB3aGljaCBpcyBwZXJpb2RTdGFydCkKICBzZXRUaW1lb3V0KCgpPT57CiAgICBjb25zdCBjb2xzPWNhbC5xdWVyeVNlbGVjdG9yQWxsKCIuY2FsLWRheS1jb2wiKTsKICAgIGlmKGNvbHNbMV0pIGNvbHNbMV0uc2Nyb2xsSW50b1ZpZXcoe2JlaGF2aW9yOiJpbnN0YW50IixpbmxpbmU6InN0YXJ0In0pOwogIH0sNTApOwoKICAvLyBBZGQgRkFCCiAgY29uc3QgZmFiPWRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoImJ1dHRvbiIpOwogIGZhYi5pZD0iY2FsRmFiIjsKICBmYWIuY2xhc3NOYW1lPSJjYWwtZmFiIjsKICBmYWIudGV4dENvbnRlbnQ9Iisg0J3QvtCy0LjQuSDQt9Cw0L/QuNGBIjsKICBmYWIub25jbGljaz0oKT0+b3BlbkFkZE1vZGFsKGlzb0RhdGUocGVyaW9kU3RhcnQpLCIxMDowMCIpOwogIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3IoIi5tb2JpbGUtd3JhcCIpLmFwcGVuZENoaWxkKGZhYik7Cn0KZnVuY3Rpb24gY2hhbmdlV2VlayhkKXt3ZWVrU3RhcnQ9YWRkRGF5cyh3ZWVrU3RhcnQsZCo3KTtsb2FkV2VlaygpO30KZnVuY3Rpb24gZ29Ub2RheSgpewogIHBlcmlvZFN0YXJ0PXZpZXdEYXlzPT09Nz9nZXRNb25kYXkobmV3IERhdGUoKSk6bmV3IERhdGUoKTsKICB3ZWVrU3RhcnQ9bmV3IERhdGUocGVyaW9kU3RhcnQpOwogIG1vYmlsZURheT1uZXcgRGF0ZSgpOwogIGxvYWRXZWVrKCk7Cn0KZnVuY3Rpb24gb3BlbkRhdGVQaWNrZXIoKXsKICBjb25zdCBkcD1kb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZGF0ZVBpY2tlciIpOwogIGRwLnZhbHVlPWlzb0RhdGUocGVyaW9kU3RhcnQpOwogIHRyeXtkcC5zaG93UGlja2VyKCk7fWNhdGNoKGUpe2RwLmNsaWNrKCk7fQp9CmZ1bmN0aW9uIGdvVG9EYXRlKGlzbyl7CiAgaWYoIWlzbylyZXR1cm47CiAgcGVyaW9kU3RhcnQ9bmV3IERhdGUoaXNvKyJUMTI6MDA6MDAiKTsKICB3ZWVrU3RhcnQ9bmV3IERhdGUocGVyaW9kU3RhcnQpOwogIG1vYmlsZURheT1uZXcgRGF0ZShwZXJpb2RTdGFydCk7CiAgbG9hZFdlZWsoKTsKfQpmdW5jdGlvbiBzZXRNb2JpbGVEYXkoaXNvKXttb2JpbGVEYXk9bmV3IERhdGUoaXNvKyJUMTI6MDA6MDAiKTt9CmZ1bmN0aW9uIG9wZW5BZGRNb2RhbChkYXRlLHRpbWUpewogIGVkaXRpbmdJZD1udWxsOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJtb2RhbFRpdGxlIikudGV4dENvbnRlbnQ9ItCd0L7QstC40Lkg0LfQsNC/0LjRgSI7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImRlbGV0ZUJ0biIpLmNsYXNzTGlzdC5hZGQoImhpZGRlbiIpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmQ2xpZW50IikudmFsdWU9IiI7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZTZXJ2aWNlIikudmFsdWU9IiI7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZEYXRlIikudmFsdWU9ZGF0ZXx8aXNvRGF0ZShtb2JpbGVEYXl8fG5ldyBEYXRlKCkpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmVGltZSIpLnZhbHVlPXRpbWV8fCIxMDowMCI7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZEdXJhdGlvbiIpLnZhbHVlPSI2MCI7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZOb3RlcyIpLnZhbHVlPSIiOwogIGJ1aWxkVGltZUdyaWQoKTt1cGRhdGVUaW1lQnRucygpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJtb2RhbE92ZXJsYXkiKS5jbGFzc0xpc3QucmVtb3ZlKCJoaWRkZW4iKTsKICAvLyBGb2N1cyBvbiBjbGllbnQgbmFtZSBmaWVsZAogIHNldFRpbWVvdXQoKCk9PmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmQ2xpZW50IikuZm9jdXMoKSwxMDApOwp9CmZ1bmN0aW9uIG9wZW5BZGRPblNsb3QoZGF0ZSx0aW1lKXtvcGVuQWRkTW9kYWwoZGF0ZSx0aW1lKTt9CmZ1bmN0aW9uIGNsb3NlTW9kYWwoKXtkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibW9kYWxPdmVybGF5IikuY2xhc3NMaXN0LmFkZCgiaGlkZGVuIik7fQpmdW5jdGlvbiBvcGVuRGV0YWlsKGlkKXsKICBjb25zdCBhPWFwcG9pbnRtZW50cy5maW5kKHg9PnguaWQ9PWlkKTtpZighYSlyZXR1cm47CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImRldGFpbE5hbWUiKS50ZXh0Q29udGVudD1hLmNsaWVudF9uYW1lOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJkZXRhaWxCb2R5IikuaW5uZXJIVE1MPWA8ZGl2IGNsYXNzPSJkZXRhaWwtcm93Ij48c3BhbiBjbGFzcz0iZGwiPtCf0L7RgdC70YPQs9CwPC9zcGFuPjxzcGFuIGNsYXNzPSJkdiI+JHthLnNlcnZpY2V9PC9zcGFuPjwvZGl2PjxkaXYgY2xhc3M9ImRldGFpbC1yb3ciPjxzcGFuIGNsYXNzPSJkbCI+0JTQsNGC0LA8L3NwYW4+PHNwYW4gY2xhc3M9ImR2Ij4ke2ZtdERhdGUoYS5hcHB0X2RhdGUpfTwvc3Bhbj48L2Rpdj48ZGl2IGNsYXNzPSJkZXRhaWwtcm93Ij48c3BhbiBjbGFzcz0iZGwiPtCn0LDRgTwvc3Bhbj48c3BhbiBjbGFzcz0iZHYiPiR7YS5zdGFydF90aW1lfSwgJHthLmR1cmF0aW9uX21pbn0g0YXQsjwvc3Bhbj48L2Rpdj4ke2Eubm90ZXM/YDxkaXYgY2xhc3M9ImRldGFpbC1yb3ciPjxzcGFuIGNsYXNzPSJkbCI+0J3QvtGC0LDRgtC60Lg8L3NwYW4+PHNwYW4gY2xhc3M9ImR2Ij4ke2Eubm90ZXN9PC9zcGFuPjwvZGl2PmA6IiJ9YDsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZGV0YWlsRWRpdEJ0biIpLm9uY2xpY2s9KCk9PnsKICAgIGVkaXRpbmdJZD1hLmlkOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoIm1vZGFsVGl0bGUiKS50ZXh0Q29udGVudD0i0KDQtdC00LDQs9GD0LLQsNGC0LgiOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImRlbGV0ZUJ0biIpLmNsYXNzTGlzdC5yZW1vdmUoImhpZGRlbiIpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZDbGllbnQiKS52YWx1ZT1hLmNsaWVudF9uYW1lOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZTZXJ2aWNlIikudmFsdWU9YS5zZXJ2aWNlOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZEYXRlIikudmFsdWU9YS5hcHB0X2RhdGU7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZlRpbWUiKS52YWx1ZT1hLnN0YXJ0X3RpbWU7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZkR1cmF0aW9uIikudmFsdWU9YS5kdXJhdGlvbl9taW47CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZk5vdGVzIikudmFsdWU9YS5ub3Rlc3x8IiI7CiAgICBjbG9zZURldGFpbCgpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoIm1vZGFsT3ZlcmxheSIpLmNsYXNzTGlzdC5yZW1vdmUoImhpZGRlbiIpOwogIH07CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImRldGFpbE92ZXJsYXkiKS5jbGFzc0xpc3QucmVtb3ZlKCJoaWRkZW4iKTsKfQpmdW5jdGlvbiBjbG9zZURldGFpbCgpe2RvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJkZXRhaWxPdmVybGF5IikuY2xhc3NMaXN0LmFkZCgiaGlkZGVuIik7fQpkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibW9kYWxPdmVybGF5IikuYWRkRXZlbnRMaXN0ZW5lcigiY2xpY2siLGU9PntpZihlLnRhcmdldD09PWUuY3VycmVudFRhcmdldCljbG9zZU1vZGFsKCk7fSk7CmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJkZXRhaWxPdmVybGF5IikuYWRkRXZlbnRMaXN0ZW5lcigiY2xpY2siLGU9PntpZihlLnRhcmdldD09PWUuY3VycmVudFRhcmdldCljbG9zZURldGFpbCgpO30pOwphc3luYyBmdW5jdGlvbiBzYXZlQXBwdCgpewogIGNvbnN0IGJvZHk9e21hc3Rlcl9pZDptYXN0ZXJJZCxjbGllbnRfbmFtZTpkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZkNsaWVudCIpLnZhbHVlLnRyaW0oKSxzZXJ2aWNlOmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmU2VydmljZSIpLnZhbHVlLnRyaW0oKSxhcHB0X2RhdGU6ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZEYXRlIikudmFsdWUsc3RhcnRfdGltZTpkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZlRpbWUiKS52YWx1ZSxkdXJhdGlvbl9taW46cGFyc2VJbnQoZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZEdXJhdGlvbiIpLnZhbHVlKSxub3Rlczpkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZk5vdGVzIikudmFsdWUudHJpbSgpfTsKICBpZighYm9keS5jbGllbnRfbmFtZXx8IWJvZHkuc2VydmljZSl7YWxlcnQoItCX0LDQv9C+0LLQvdGW0YLRjCDRltC8XHUwMDI30Y8g0ZYg0L/QvtGB0LvRg9Cz0YMiKTtyZXR1cm47fQogIGNvbnN0IHVybD1lZGl0aW5nSWQ/YC9hcGkvYXBwb2ludG1lbnRzLyR7ZWRpdGluZ0lkfWA6Ii9hcGkvYXBwb2ludG1lbnRzIjsKICBjb25zdCByZXM9YXdhaXQgZmV0Y2godXJsLHttZXRob2Q6ZWRpdGluZ0lkPyJQVVQiOiJQT1NUIixoZWFkZXJzOnsiQ29udGVudC1UeXBlIjoiYXBwbGljYXRpb24vanNvbiJ9LGJvZHk6SlNPTi5zdHJpbmdpZnkoYm9keSl9KTsKICBpZighcmVzLm9rKXtjb25zdCBlPWF3YWl0IHJlcy5qc29uKCk7YWxlcnQoZS5kZXRhaWx8fCLQn9C+0LzQuNC70LrQsCIpO3JldHVybjt9CiAgY2xvc2VNb2RhbCgpO3Nob3dUb2FzdChlZGl0aW5nSWQ/ItCe0L3QvtCy0LvQtdC90L4iOiLQl9Cx0LXRgNC10LbQtdC90L4iKTsKICBtb2JpbGVEYXk9bmV3IERhdGUoYm9keS5hcHB0X2RhdGUrIlQxMjowMDowMCIpOwogIGF3YWl0IGxvYWRXZWVrKCk7Cn0KYXN5bmMgZnVuY3Rpb24gZGVsZXRlQXBwdCgpewogIGlmKCFlZGl0aW5nSWR8fCFjb25maXJtKCLQktC40LTQsNC70LjRgtC4INC30LDQv9C40YE/IikpcmV0dXJuOwogIGF3YWl0IGZldGNoKGAvYXBpL2FwcG9pbnRtZW50cy8ke2VkaXRpbmdJZH1gLHttZXRob2Q6IkRFTEVURSJ9KTsKICBjbG9zZU1vZGFsKCk7c2hvd1RvYXN0KCLQktC40LTQsNC70LXQvdC+Iik7YXdhaXQgbG9hZFdlZWsoKTsKfQpmdW5jdGlvbiBzaG93VG9hc3QobXNnKXtjb25zdCB0PWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJ0b2FzdCIpO3QudGV4dENvbnRlbnQ9bXNnO3QuY2xhc3NMaXN0LmFkZCgic2hvdyIpO3NldFRpbWVvdXQoKCk9PnQuY2xhc3NMaXN0LnJlbW92ZSgic2hvdyIpLDI1MDApO30KLy8gRm9yY2UgbW9iaWxlIGxheW91dCBjaGVjawpmdW5jdGlvbiBhcHBseUxheW91dCgpewogIGNvbnN0IGlzTW9iaWxlPXdpbmRvdy5pbm5lcldpZHRoPD03Njh8fCgnb250b3VjaHN0YXJ0JyBpbiB3aW5kb3cmJndpbmRvdy5pbm5lcldpZHRoPD0xMDI0KTsKICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yKCIuY29udGVudCIpLnN0eWxlLmRpc3BsYXk9aXNNb2JpbGU/Im5vbmUiOiIiOwogIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3IoIi5tb2JpbGUtd3JhcCIpLnN0eWxlLmRpc3BsYXk9aXNNb2JpbGU/ImZsZXgiOiJub25lIjsKfQphcHBseUxheW91dCgpOwp3aW5kb3cuYWRkRXZlbnRMaXN0ZW5lcigicmVzaXplIixhcHBseUxheW91dCk7Cjwvc2NyaXB0PgoKPGRpdiBjbGFzcz0ib3ZlcmxheSBoaWRkZW4iIGlkPSJtb2RhbE92ZXJsYXkiPgo8ZGl2IGNsYXNzPSJtb2RhbCI+CjxoMiBpZD0ibW9kYWxUaXRsZSI+0J3QvtCy0LjQuSDQt9Cw0L/QuNGBPC9oMj4KPGRpdiBjbGFzcz0iZm9ybS1yb3ciPjxsYWJlbD7QmtC70ZbRlNC90YI8L2xhYmVsPjxpbnB1dCBpZD0iZkNsaWVudCIgdHlwZT0idGV4dCIgcGxhY2Vob2xkZXI9ItCa0LvRltGU0L3RgiI+PC9kaXY+CjxkaXYgY2xhc3M9ImZvcm0tcm93Ij48bGFiZWw+0J/QvtGB0LvRg9Cz0LA8L2xhYmVsPjxzZWxlY3QgaWQ9ImZTZXJ2aWNlIj48L3NlbGVjdD48L2Rpdj4KPGRpdiBjbGFzcz0iZm9ybS1yb3ciPjxsYWJlbD7QlNCw0YLQsDwvbGFiZWw+PGlucHV0IGlkPSJmRGF0ZSIgdHlwZT0iZGF0ZSI+PC9kaXY+CjxkaXYgY2xhc3M9ImZvcm0tMmNvbCI+CjxkaXYgY2xhc3M9ImZvcm0tcm93Ij48bGFiZWw+0KfQsNGBPC9sYWJlbD4KPGlucHV0IGlkPSJmVGltZSIgdHlwZT0idGltZSIgc3RlcD0iOTAwIiBvbmNoYW5nZT0idXBkYXRlVGltZUJ0bnMoKSI+CjxkaXYgY2xhc3M9InRpbWUtZ3JpZCIgaWQ9InRpbWVHcmlkIj48L2Rpdj4KPC9kaXY+CjxkaXYgY2xhc3M9ImZvcm0tcm93Ij48bGFiZWw+0KLRgNC40LLQsNC70ZbRgdGC0YwgKNGF0LIpPC9sYWJlbD48aW5wdXQgaWQ9ImZEdXJhdGlvbiIgdHlwZT0ibnVtYmVyIiBtaW49IjE1IiBzdGVwPSIxNSIgdmFsdWU9IjYwIj48L2Rpdj4KPC9kaXY+CjxkaXYgY2xhc3M9ImZvcm0tcm93Ij48bGFiZWw+0J3QvtGC0LDRgtC60Lg8L2xhYmVsPjx0ZXh0YXJlYSBpZD0iZk5vdGVzIiByb3dzPSIzIj48L3RleHRhcmVhPjwvZGl2Pgo8ZGl2IGNsYXNzPSJtb2RhbC1mb290ZXIiPgo8YnV0dG9uIGNsYXNzPSJidG4gYnRuLWRhbmdlciBoaWRkZW4iIGlkPSJkZWxldGVCdG4iIG9uY2xpY2s9ImRlbGV0ZUFwcHQoKSI+0JLQuNC00LDQu9C40YLQuDwvYnV0dG9uPgo8YnV0dG9uIGNsYXNzPSJidG4iIG9uY2xpY2s9ImNsb3NlTW9kYWwoKSI+0KHQutCw0YHRg9Cy0LDRgtC4PC9idXR0b24+CjxidXR0b24gY2xhc3M9ImJ0biBidG4tcHJpbWFyeSIgb25jbGljaz0ic2F2ZUFwcHQoKSI+0JfQsdC10YDQtdCz0YLQuDwvYnV0dG9uPgo8L2Rpdj48L2Rpdj48L2Rpdj4KPGRpdiBjbGFzcz0ib3ZlcmxheSBoaWRkZW4iIGlkPSJkZXRhaWxPdmVybGF5Ij4KPGRpdiBjbGFzcz0ibW9kYWwiPgo8ZGl2IGNsYXNzPSJkZXRhaWwtYmFyIj48L2Rpdj4KPGgyIGlkPSJkZXRhaWxOYW1lIj48L2gyPgo8ZGl2IGlkPSJkZXRhaWxCb2R5Ij48L2Rpdj4KPGRpdiBjbGFzcz0ibW9kYWwtZm9vdGVyIj4KPGJ1dHRvbiBjbGFzcz0iYnRuIiBvbmNsaWNrPSJjbG9zZURldGFpbCgpIj7Ql9Cw0LrRgNC40YLQuDwvYnV0dG9uPgo8YnV0dG9uIGNsYXNzPSJidG4gYnRuLXByaW1hcnkiIGlkPSJkZXRhaWxFZGl0QnRuIj7QoNC10LTQsNCz0YPQstCw0YLQuDwvYnV0dG9uPgo8L2Rpdj48L2Rpdj48L2Rpdj4KPHNjcmlwdD4KLy8gVGltZSBxdWljay1waWNrIGJ1dHRvbnMKZnVuY3Rpb24gYnVpbGRUaW1lR3JpZCgpewogIHZhciBncmlkPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJ0aW1lR3JpZCIpOwogIGlmKCFncmlkKXJldHVybjsKICB2YXIgdGltZXM9WyIwOTowMCIsIjA5OjMwIiwiMTA6MDAiLCIxMDozMCIsIjExOjAwIiwiMTE6MzAiLCIxMjowMCIsIjEyOjMwIiwiMTM6MDAiLCIxMzozMCIsIjE0OjAwIiwiMTQ6MzAiLCIxNTowMCIsIjE1OjMwIiwiMTY6MDAiLCIxNjozMCIsIjE3OjAwIiwiMTc6MzAiLCIxODowMCJdOwogIGdyaWQuaW5uZXJIVE1MPXRpbWVzLm1hcChmdW5jdGlvbih0KXtyZXR1cm4gJzxidXR0b24gdHlwZT0iYnV0dG9uIiBjbGFzcz0idGltZS1idG4iIG9uY2xpY2s9InNlbGVjdFRpbWUoXCcnICsgdCArICdcJykiPicrdCsnPC9idXR0b24+Jzt9KS5qb2luKCIiKTsKfQpmdW5jdGlvbiBzZWxlY3RUaW1lKHQpewogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmVGltZSIpLnZhbHVlPXQ7CiAgdXBkYXRlVGltZUJ0bnMoKTsKfQpmdW5jdGlvbiB1cGRhdGVUaW1lQnRucygpewogIHZhciBjdXI9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZUaW1lIikudmFsdWU7CiAgZG9jdW1lbnQucXVlcnlTZWxlY3RvckFsbCgiLnRpbWUtYnRuIikuZm9yRWFjaChmdW5jdGlvbihiKXsKICAgIGIuY2xhc3NMaXN0LnRvZ2dsZSgiYWN0aXZlIixiLnRleHRDb250ZW50PT09Y3VyKTsKICB9KTsKfQovLyBJbml0IG92ZXJsYXkgaGFuZGxlcnMgYW5kIGxvYWQgZ3JpZApmdW5jdGlvbiBzYWZlT24oaWQsZXZ0LGZuKXt2YXIgZWw9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoaWQpO2lmKGVsKWVsLmFkZEV2ZW50TGlzdGVuZXIoZXZ0LGZuKTt9CmZ1bmN0aW9uIHNhZmVDbGljayhpZCxmbil7dmFyIGVsPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKGlkKTtpZihlbCllbC5vbmNsaWNrPWZuO30Kc2FmZU9uKCJtb2RhbE92ZXJsYXkiLCJjbGljayIsZnVuY3Rpb24oZSl7aWYoZS50YXJnZXQ9PT10aGlzKWNsb3NlTW9kYWwoKTt9KTsKc2FmZU9uKCJkZXRhaWxPdmVybGF5IiwiY2xpY2siLGZ1bmN0aW9uKGUpe2lmKGUudGFyZ2V0PT09dGhpcyljbG9zZURldGFpbCgpO30pOwpzYWZlQ2xpY2soImRldGFpbEVkaXRCdG4iLGZ1bmN0aW9uKCl7CiAgdmFyIGE9d2luZG93Ll9jdXJBcHB0O2lmKCFhKXJldHVybjsKICBlZGl0aW5nSWQ9YS5pZDsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibW9kYWxUaXRsZSIpLnRleHRDb250ZW50PSLQoNC10LTQsNCz0YPQstCw0YLQuCI7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImRlbGV0ZUJ0biIpLmNsYXNzTGlzdC5yZW1vdmUoImhpZGRlbiIpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmQ2xpZW50IikudmFsdWU9YS5jbGllbnRfbmFtZTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZlNlcnZpY2UiKS52YWx1ZT1hLnNlcnZpY2U7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZEYXRlIikudmFsdWU9YS5hcHB0X2RhdGU7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZUaW1lIikudmFsdWU9YS5zdGFydF90aW1lOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmRHVyYXRpb24iKS52YWx1ZT1hLmR1cmF0aW9uX21pbjsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZk5vdGVzIikudmFsdWU9YS5ub3Rlc3x8IiI7CiAgY2xvc2VEZXRhaWwoKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibW9kYWxPdmVybGF5IikuY2xhc3NMaXN0LnJlbW92ZSgiaGlkZGVuIik7Cn0pOwpsb2FkV2VlaygpOwo8L3NjcmlwdD4KPC9ib2R5Pgo8L2h0bWw+').decode()
