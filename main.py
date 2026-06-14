"""
Cosmo — розклад косметологічного кабінету
Запуск: uvicorn main:app --reload
"""

import json, hashlib, secrets, os, urllib.request, urllib.error
from datetime import date, datetime, timedelta
from fastapi import FastAPI, HTTPException, Request, Response, Cookie, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
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
        """CREATE TABLE IF NOT EXISTS appointments (id INTEGER PRIMARY KEY AUTOINCREMENT, master_id INTEGER NOT NULL, client_name TEXT NOT NULL, phone TEXT DEFAULT '', service TEXT NOT NULL, appt_date TEXT NOT NULL, start_time TEXT NOT NULL, duration_min INTEGER NOT NULL DEFAULT 60, notes TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')))""",
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
    # Migration: add phone column if not exists
    try:
        turso_exec("ALTER TABLE appointments ADD COLUMN phone TEXT DEFAULT ''", [])
    except Exception:
        pass
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
    phone: str = ""
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
app.mount("/static", StaticFiles(directory="static"), name="static")
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

    def to_min(t): parts=t.split(":"); return int(parts[0])*60+int(parts[1])
    existing = turso("SELECT start_time, duration_min FROM appointments WHERE master_id=? AND appt_date=?", [a.master_id, a.appt_date])
    new_start = to_min(a.start_time)
    new_end = new_start + a.duration_min
    for row in existing:
        s = to_min(row["start_time"])
        e = s + int(row["duration_min"])
        if new_start < e and new_end > s:
            raise HTTPException(400, "Цей час вже зайнятий у майстра")
    turso_exec("INSERT INTO appointments (master_id,client_name,phone,service,appt_date,start_time,duration_min,notes) VALUES (?,?,?,?,?,?,?,?)",
                    [a.master_id, a.client_name, a.phone, a.service, a.appt_date, a.start_time, a.duration_min, a.notes])
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

MASTER_HTML = __import__('base64').b64decode('PCFET0NUWVBFIGh0bWw+CjxodG1sIGxhbmc9InVrIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9IlVURi04Ij4KPG1ldGEgbmFtZT0idmlld3BvcnQiIGNvbnRlbnQ9IndpZHRoPWRldmljZS13aWR0aCxpbml0aWFsLXNjYWxlPTEsdmlld3BvcnQtZml0PWNvdmVyIj4KPG1ldGEgbmFtZT0ibW9iaWxlLXdlYi1hcHAtY2FwYWJsZSIgY29udGVudD0ieWVzIj4KPG1ldGEgbmFtZT0iYXBwbGUtbW9iaWxlLXdlYi1hcHAtY2FwYWJsZSIgY29udGVudD0ieWVzIj4KPG1ldGEgbmFtZT0iYXBwbGUtbW9iaWxlLXdlYi1hcHAtc3RhdHVzLWJhci1zdHlsZSIgY29udGVudD0iYmxhY2stdHJhbnNsdWNlbnQiPgo8bWV0YSBuYW1lPSJhcHBsZS1tb2JpbGUtd2ViLWFwcC10aXRsZSIgY29udGVudD0iQm9keSBCYWxhbmNlIj4KPG1ldGEgbmFtZT0idGhlbWUtY29sb3IiIGNvbnRlbnQ9IiMwMEM4QjQiPgo8bGluayByZWw9Im1hbmlmZXN0IiBocmVmPSIvbWFuaWZlc3QuanNvbiI+CjxsaW5rIHJlbD0iYXBwbGUtdG91Y2gtaWNvbiIgaHJlZj0iL2FwaS9pY29uIj4KPHRpdGxlPkJvZHkgQmFsYW5jZSDDosKAwpQgw5DCnMORwpbDkMK5IMORwoDDkMK+w5DCt8OQwrrDkMK7w5DCsMOQwrQ8L3RpdGxlPgo8bGluayBocmVmPSJodHRwczovL2ZvbnRzLmdvb2dsZWFwaXMuY29tL2NzczI/ZmFtaWx5PU1vbnRzZXJyYXQ6d2dodEA1MDA7NjAwOzcwMDs4MDAmZmFtaWx5PUludGVyOndnaHRANDAwOzUwMDs2MDAmZGlzcGxheT1zd2FwIiByZWw9InN0eWxlc2hlZXQiPgo8bGluayByZWw9InN0eWxlc2hlZXQiIGhyZWY9Ii9zdGF0aWMvY3NzL21hc3Rlci5jc3MiPgo8L2hlYWQ+Cjxib2R5Pgo8ZGl2IGNsYXNzPSJhcHAiPgo8ZGl2IGNsYXNzPSJ0b3BiYXIiPgogIDxhIGhyZWY9Ii9sb2dpbiIgc3R5bGU9ImRpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXIiPjxpbWcgc3JjPSJkYXRhOmltYWdlL3N2Zyt4bWw7YmFzZTY0LFBEOTRiV3dnZG1WeWMybHZiajBpTVM0d0lpQmxibU52WkdsdVp6MGlWVlJHTFRnaVB6NEtQSE4yWnlCcFpEMGlUR0Y1WlhKZk1TSWdaR0YwWVMxdVlXMWxQU0pNWVhsbGNpQXhJaUI0Yld4dWN6MGlhSFIwY0RvdkwzZDNkeTUzTXk1dmNtY3ZNakF3TUM5emRtY2lJSFpwWlhkQ2IzZzlJakFnTUNBeU1UVXpJREV3T0RBaVBnb2dJRHhrWldaelBnb2dJQ0FnUEhOMGVXeGxQZ29nSUNBZ0lDQXVZMnh6TFRFZ2V3b2dJQ0FnSUNBZ0lHWnBiR3c2SUNNd1pHVXdaRFk3Q2lBZ0lDQWdJSDBLQ2lBZ0lDQWdJQzVqYkhNdE1pQjdDaUFnSUNBZ0lDQWdabWxzYkRvZ0kyWm1abVptWmpzS0lDQWdJQ0FnZlFvZ0lDQWdQQzl6ZEhsc1pUNEtJQ0E4TDJSbFpuTStDaUFnUEhCaGRHZ2dZMnhoYzNNOUltTnNjeTB4SWlCa1BTSk5NemcwTGpJekxESXhOQzQ1T1dNdE1UQXVPREV0TlM0MU5TMHhNQzQ0TVN3ME1pNHpNUzB4TUM0NE1TdzBNaTR6TVMweE1DNDRNU3d5TlM0NU5TMHlNUzQyTWl3eU9DNHhNUzB5TVM0Mk1pd3lPQzR4TVMweE1pNDVOeTA0TGpZMUxURXdMamd4TFRRM0xqVTNMVEV3TGpneExUUTNMalUzTFRFMUxqRTBMVFUyTGpJeUxEUXpMakkwTFRVNExqTTRMRFF6TGpJMExUVTRMak00TERBc01DMHlNUzQyTWkwNExqWTFMVE00TGpreUxEWXVORGt0TWpNdU1ERXNNakF1TVRRdE1UY3VNeXcyTWk0M0xUZ3VOalVzT0RndU5qVXNPQzQyTlN3eU5TNDVOU3d5TVM0Mk1pd3hOUzR4TkN3eU1TNDJNaXd4TlM0eE5DMHhNaTQ1Tnl3eE55NHpMVEkxTGprMUxERXlMamszTFRJMUxqazFMREV5TGprM0xUSTRMakV4TFRZdU5Ea3RNemd1T1RJdE1pNHhOaTB6T0M0NU1pMHlMakUyTFRNd0xqSTNMREV5TGprM0xUSXhMall5TERZM0xqQXpMVEUxTGpFMExEZzRMalkxTERZdU5Ea3NNakV1TmpJc016SXVORE1zT1RJdU9UY3NNekl1TkRNc09USXVPVGN0T0M0Mk5TdzJMalE1TFRFNUxqUTJMREkxTGprMUxURTFMakUwTERReExqQTRMRFF1TXpJc01UVXVNVFFzTWpVdU9UVXNNekl1TkRNc016WXVOellzTWpFdU5qSXNNVEF1T0RFdE1UQXVPREV0T0M0Mk5TMDBOeTQxTnkwNExqWTFMVFEzTGpVM2JDMHlOQzQwTmkwMk1pNDJObU10TVM0eE5pMHpMalF4TFRJdU1UWXROaTQ0TmkweUxqazRMVEV3TGpNM0xUTXVNakV0TVRNdU5qY3RNakl1TWprdE56RXVPRE10TVRFdU5EZ3RPVGN1Tnpnc01URXVNRGt0TWpZdU5qTXNORGN1TlRjdE1UY3VNeXcwTnk0MU55MHhOeTR6TERReExqQTRMRGd1TmpVc05Ea3VOek10TkRrdU56TXNORGt1TnpNdE5Ea3VOek1zTVRBdU9ERXRNVEF1T0RFc01USXVPVGN0TXpndU9USXNNaTR4TmkwME5DNDBOMXBOTXpJeExqVXpMRFV5TVM0d09HTXdMREV3TGpneExEQXNNVFV1TVRRdE5pNDBPU3d4TWk0NU4zTXRNVFF1TkRRdE1UUXVPVGt0TVRJdU9UY3RNak11Tnpoak1pNHhOaTB4TWk0NU55d3hNQzQ0TVMweU1TNDJNaXd4TUM0NE1TMHlNUzQyTWl3d0xEQXNPQzQyTlN3eU1TNDJNaXc0TGpZMUxETXlMalF6V2lJdlBnb2dJRHh3WVhSb0lHTnNZWE56UFNKamJITXRNU0lnWkQwaVRUTTRNeTQ0TlN3eU5qa3VNamx6TFRRdU16SXNNekF1TWpjdE1qTXVOemdzTmpRdU9EWmpMVEU1TGpRMkxETTBMalU1TFRRMkxqUTVMRGd6TGpJMExUUTJMalE1TERFMU1DNHlOMncwTGpNeUxUUXVNeklzTkM0ek1pMDBMak15Y3pJdU1UWXRNVEl1T1Rjc09DNDJOUzAwTXk0eU5HTTJMalE1TFRNd0xqSTNMREkzTGpBekxUWXpMamM0TERReExqQTRMVGt5TGprM0xERXlMakl6TFRJMUxqUXNNVFF1TURVdE5USXVPVGNzTVRFdU9Ea3ROekF1TWpkYUlpOCtDaUFnUEhCaGRHZ2dZMnhoYzNNOUltTnNjeTB4SWlCa1BTSk5Nek14TGpZMUxEZzNPQzQyTkhNMU5pNDVNUzB4TURZdU56VXNOekl1TURRdE1UTTVMakU0WXpFMUxqRTBMVE15TGpRekxEUXdMVEV4TVM0ek5Td3pNaTQwTXkweE5qQXROaTQ0TlMwME5DNHdOQzB5TUM0MU5DMDNOaTQzTmkwMU1pNDVOeTA0T1M0M015MHpNUzR4TmkweE1pNDBOeTAyTVM0Mk1pMDVMamN6TFRjd0xqSTNMVEV1TURoc0xUSXVNVFl0Tmk0ME9YTXlOUzR3TXkweU1TNDJNaXc0TUM0Mk1pMDFMalF4WXpVMUxqVTVMREUyTGpJeUxEY3hMamd4TERnMkxqUTVMRGN4TGpneExERXhOQzQxT1N3d0xETXhMak10TXk0NE9Td3hNREF1TVRndE5ETXVNalFzTVRZeUxqRTJMVFF3TGpVMUxEWXpMamcyTFRnNExqSTJMREV5TlM0eE15MDRPQzR5Tml3eE1qVXVNVE5hSWk4K0NpQWdQSEJoZEdnZ1kyeGhjM005SW1Oc2N5MHhJaUJrUFNKTk16SXlMakl6TERRM055NDVNM010TlM0ME1TMHlPUzR4T1N3eE9DNHpPQzAwTUdNeU15NDNPQzB4TUM0NE1TdzROeTQxTnkweE1TNDRPU3c1Tnk0ekxUWTVMakU1TERFeExqUTJMVFkzTGpRNUxUUTVMakV4TFRZekxqVXhMVFE1TGpFeExUWXpMalV4TERBc01DdzFOQzQxT1MweU9DNDFOeXczTVM0NE1Td3lPUzQ1T1N3eE1DNDRNU3d6Tmk0M05pMHhNaTQ1Tnl3NE5pNDBPUzAzTVM0ek5TdzVPUzQwTmkwMU15NHdOeXd4TVM0M09TMDFOQzR3TlN3eE5TNHhOQzAyTnk0d015dzBNeTR5TkZvaUx6NEtJQ0E4Y0dGMGFDQmpiR0Z6Y3owaVkyeHpMVEVpSUdROUlrMDRNRFlzTnpNNFl6VTRMRFF3TERFeE55NHlPU3cxT1M0eE9Dd3hORFFzTmprc01UWTJMRFl4TERNeU1pdzNOQ3d6TWpJc056UXNOVFF3TERjeUxEWTRNQzR3TWkweE1EWXVPRGtzTmpnd0xqQXlMVEV3Tmk0NE9TMHlNekF1T1Rnc01UVTJMakV4TFRjNU5pNDVOeXcxTXk0d01TMDVNREl1TURJc016QXVPRGt0TXpndE9DMHhNVFV0TWpVdE1qTXlMVGd6SWk4K0NpQWdQSEJoZEdnZ1kyeGhjM005SW1Oc2N5MHhJaUJrUFNKTk9ESXpMakVzTnpVMUxqQTBZeTB5Tmk0ek15d3lOeTQzTlMwMk1TNHlPU3cwT1M0d015MHhNRFF1T0Rrc05qTXVPRE10TXpjdU5ETXNNVEl1TkRrdE56WXVPVElzTVRndU56TXRNVEU0TGpRMkxERTRMamN6TFRJM0xqRTFMREF0TlRNdU1qY3ROaTR3TWkwM09DNHpOaTB4T0M0d05DMHpNaTR3T0MweE5TNHlOaTAwT0M0eE15MHpOaTR6TVMwME9DNHhNeTAyTXk0eE5Dd3dMVE13TGprNExERXpMakUyTFRVMkxqUXpMRE01TGpRNUxUYzJMak15TERFeExqa3lMVGd1Tnpnc01qUXVNamN0TVRVdU16Y3NNemN1TURJdE1Ua3VOemNzTVRJdU56VXROQzR6T1N3eU5pNHhNaTAzTGpBMUxEUXdMakV4TFRjdU9UZ3NOaTQ1T1MweE9DNDFMREUxTGpjekxUUXdMakF4TERJMkxqSXlMVFkwTGpVekxERXdMalE1TFRJMExqVXhMREl4TGpZeUxUUTJMakF5TERNeExqa3hMVFkzTGpNc015NHlPUzAyTGpRM0xEZ3RNVFlzTVRRdE1qWXNNVEF1TWprdE1UY3VNVFlzTWpBdE16RXNNalF0TXpVc01UY3VOVEV0TVRjdU5URXNNell0TVRVc016WXRNVFVzTUN3d0xUSXVPVGtzTWk0eU5DMHhNeTQwT0N3eE5TNDNOaTB6TGpVMExEUXVOVFV0Tmk0NE9DdzVMakkzTFRrdU9Ua3NNVFF1TVRNdE16VXVPRE1zTlRVdU9UVXROVFl1TURjc01UQTJMak01TFRnM0xqWTRMREUzTnk0NU5DdzVNaTQxTlN3eExqZzFMREUyTVM0ME5Dd3lOUzR5TWl3eU1EWXVOeXczTUM0d09Dd3hNeTR4TmkweE9TNDRPQ3d4T1M0M05DMHpPQzR4Tml3eE9TNDNOQzAxTkM0NE1Td3dMVEk1TGpFMExURTNMalE1TFRVeUxqQTBMVFV5TGpRMUxUWTRMalk1TFRFMUxqRTJMVFl1T1RjdE5UQXVNREV0TVRjdU5EZ3ROell1T0RRdE1qSXVOQzB5TVM0eU1pMHpMamc1TFRJM0xUVXRNamN0TlN3d0xEQXNPQzQ1TkMwekxqRTVMREl4TFRjc01Ua3ROaXd5TmkwNExETTNMVEV5TERRMUxqWTBMVEUyTGpZc056RXVOakV0TWprdU1ESXNPVE11T1RjdE5USXVPRElzT1M0ME5pMDVMamN4TERFMExqRTVMVEU0TGpVc01UUXVNVGt0TWpZdU16Y3NNQzB4Tmk0Mk5TMHhPUzR4TXkweU9TNHhOQzAxTnk0ek9DMHpOeTQwTnkweU5TNDVNUzAxTGpVMUxUVXlMalkyTFRndU16TXRPREF1TWpFdE9DNHpNeTAzTXk0Mk5Dd3dMVEUwTUM0NU9Td3hNQzQ1TWkweU1EVXVOVGNzTkRBdU9UZ3RNaTQwTnk0NU15MHhOaXc1TFRFMkxEa3NNQ3d3TERndU16TXRNVEV1TXpNc01UVXRNVGdzT1MwNUxERTVMVEUzTERNekxUSTBMRFF5TGpjNExURTVMalF6TERjM0xqY3lMVEk0TGpFc01UUXpMamsxTFRJNExqRXNNemt1TkRrc01DdzNOaTR3T1N3MExqRTJMREV3T1M0NE15d3hNaTQwT1N3MU1pNDJOU3d4TWk0ME9TdzNPQzQ1T0N3ek1pNHpPQ3czT0M0NU9DdzFPUzQyTnl3d0xESXlMakl0TVRZdU1EUXNOREl1TXpNdE5EZ3VNVE1zTmpBdU16Y3RNak11TkRVc01UTXVOREl0TkRndU16UXNNakl1TmpjdE56UXVOallzTWpjdU56VXNNamt1TWl3M0xqUXhMRFUwTGpNc01UZ3VNamdzTnpVdU1qY3NNekl1TmpFc01qZ3VOemtzTVRrdU5ETXNORE11TVRrc05ESXVOemtzTkRNdU1Ua3NOekF1TURnc01Dd3lNaTR5TFRFd0xqQTRMRFEyTGpBekxUTXdMakl6TERjeExqUTNUVFUyTUM0NE55dzRNRGd1TkRkakxTNDROeTR3TlMwekxqZzNMVGt1TkRZdE15NDROeTB5TVM0NU5Td3dMVEl3TGpneUxEUXVORGt0TlRZdU5qa3NNalV1TkRZdE1URTBMakExTFRVMExqY3hMREV3TGpFNExUZ3lMakEyTERNNExqWXpMVGd5TGpBMkxEZzFMak0wTERBc01qQXVPRElzTVRJdU5UUXNNemN1TkRjc016Y3VOalFzTkRrdU9UWXNNVGt1TnpRc09TNDNNU3cwTUM0ek1Td3hOQzQxTnl3Mk1TNDNMREUwTGpVM0xEa3hMak15TERBc01UWXdMakl4TFRJNExqSXhMREl3Tmk0M0xUZzBMalkxTFRJekxqQTBMVEl4TGpjMExUVXlMakEwTFRNNExqZzJMVGczTFRVeExqTTFMVE15TGpVdE1URXVOVFl0TmpVdU1pMHhOeTR6TlMwNU9DNHhMVEUzTGpNMWFDMDRMamsxWXkwekxqQTRMREF0Tmk0d055NHlOQzA0TGprMUxqWTVMVEkwTGpZNExEVTRMamMxTFRReUxqUTBMREV4T0M0ME9DMDBNaTQwTkN3eE16Z3VPRE1pTHo0S0lDQThaejRLSUNBZ0lEeHdZWFJvSUdOc1lYTnpQU0pqYkhNdE1pSWdaRDBpVFRnNU5pNHlPQ3cyTWpVdU1ERjJMVFkwTGpnMWFETTBMalkxWXpndU9UWXNNQ3d4TlM0MU5pd3hMalU1TERFNUxqZ3pMRFF1Tnpjc05DNHlOaXd6TGpFNExEWXVNemtzTnk0eU5DdzJMak01TERFeUxqRTRMREFzTXk0eU55MHVPVEVzTmk0eE9TMHlMamN6TERndU56VXRNUzQ0TWl3eUxqVTJMVFF1TkRZc05DNDFPUzAzTGpreUxEWXVNRGN0TXk0ME5pd3hMalE0TFRjdU56SXNNaTR5TWkweE1pNDNPU3d5TGpJeWJERXVPRFV0TldNMUxqQTJMREFzT1M0ME15NDNNU3d4TXk0eE1Td3lMakV6TERNdU5qY3NNUzQwTWl3MkxqVXlMRE11TkRjc09DNDFNaXcyTGpFMkxESXVNREVzTWk0Mk9Td3pMakF4TERVdU9USXNNeTR3TVN3NUxqWTRMREFzTlM0Mk1pMHlMak16TERFd0xUWXVPVGtzTVRNdU1UWXROQzQyTml3ekxqRTFMVEV4TGpRM0xEUXVOekl0TWpBdU5ETXNOQzQzTW1ndE16WXVOVnBOT1RFM0xqYzRMRFl3T1M0M01tZ3hNeTR4Tm1NeUxqUXhMREFzTkM0eU1pMHVORE1zTlM0ME1pMHhMak1zTVM0eUxTNDROaXd4TGpneExUSXVNVE1zTVM0NE1TMHpMamh6TFM0MkxUSXVPVE10TVM0NE1TMHpMamhqTFRFdU1pMHVPRFl0TXk0d01TMHhMak10TlM0ME1pMHhMak5vTFRFMExqWTBkaTB4TkM0ME5XZ3hNUzQyTjJNeUxqUTNMREFzTkM0eU9DMHVORElzTlM0ME1pMHhMakkxTERFdU1UUXRMamd6TERFdU56RXRNaTR3TWl3eExqY3hMVE11TlRkekxTNDFOeTB5TGpneExURXVOekV0TXk0Mk1XTXRNUzR4TkMwdU9DMHlMamsxTFRFdU1pMDFMalF5TFRFdU1tZ3RNVEF1TVRsMk16UXVNamhhSWk4K0NpQWdJQ0E4Y0dGMGFDQmpiR0Z6Y3owaVkyeHpMVElpSUdROUlrMHhNREk1TGpjNExEWXlOaTQwT1dNdE5TNHpNU3d3TFRFd0xqSXhMUzQ0TXkweE5DNDJPQzB5TGpVdE5DNDBPQzB4TGpZM0xUZ3VNelV0TkM0d015MHhNUzQyTXkwM0xqQTVMVE11TWpjdE15NHdOaTAxTGpneUxUWXVOalV0Tnk0Mk5DMHhNQzQzT1MweExqZ3lMVFF1TVRRdE1pNDNNeTA0TGpZMUxUSXVOek10TVRNdU5UTnpMamt4TFRrdU5EWXNNaTQzTXkweE15NDFOMk14TGpneUxUUXVNVEVzTkM0ek55MDNMalk1TERjdU5qUXRNVEF1TnpVc015NHlOeTB6TGpBMkxEY3VNVFV0TlM0ME1pd3hNUzQyTXkwM0xqQTVMRFF1TkRndE1TNDJOeXc1TGpNMExUSXVOU3d4TkM0MU9TMHlMalZ6TVRBdU1Ua3VPRE1zTVRRdU5qUXNNaTQxWXpRdU5EVXNNUzQyTnl3NExqTXhMRFF1TURNc01URXVOVGdzTnk0d09Td3pMakkzTERNdU1EWXNOUzQ0TWl3MkxqWTBMRGN1TmpRc01UQXVOelVzTVM0NE1pdzBMakV4TERJdU56TXNPQzQyTXl3eUxqY3pMREV6TGpVM2N5MHVPVEVzT1M0ek9TMHlMamN6TERFekxqVXpZeTB4TGpneUxEUXVNVFF0TkM0ek55dzNMamMwTFRjdU5qUXNNVEF1TnprdE15NHlOeXd6TGpBMkxUY3VNVE1zTlM0ME1pMHhNUzQxT0N3M0xqQTVMVFF1TkRVc01TNDJOeTA1TGpNc01pNDFMVEUwTGpVMExESXVOVnBOTVRBeU9TNDJPU3cyTURndU9HTXlMakEwTERBc015NDVOQzB1TXpjc05TNDNMVEV1TVRFc01TNDNOaTB1TnpRc015NHpMVEV1T0RFc05DNDJNeTB6TGpJc01TNHpNeTB4TGpNNUxESXVNell0TXk0d09Td3pMakV0TlM0eExqYzBMVEl1TURFc01TNHhNUzAwTGpJNExERXVNVEV0Tmk0NE1YTXRMak0zTFRRdU9DMHhMakV4TFRZdU9ERmpMUzQzTkMweUxqQXhMVEV1TnpndE15NDNNUzB6TGpFdE5TNHhMVEV1TXpNdE1TNHpPUzB5TGpnM0xUSXVORFV0TkM0Mk15MHpMakl0TVM0M05pMHVOelF0TXk0Mk5pMHhMakV4TFRVdU55MHhMakV4Y3kwekxqazBMak0zTFRVdU55d3hMakV4TFRNdU15d3hMamd4TFRRdU5qTXNNeTR5WXkweExqTXpMREV1TXprdE1pNHpOaXd6TGpBNUxUTXVNU3cxTGpFdExqYzBMREl1TURFdE1TNHhNU3cwTGpJNExURXVNVEVzTmk0NE1YTXVNemNzTkM0NExERXVNVEVzTmk0NE1XTXVOelFzTWk0d01Td3hMamMzTERNdU56RXNNeTR4TERVdU1Td3hMak16TERFdU16a3NNaTQ0Tnl3eUxqUTJMRFF1TmpNc015NHljek11TmpZc01TNHhNU3cxTGpjc01TNHhNVm9pTHo0S0lDQWdJRHh3WVhSb0lHTnNZWE56UFNKamJITXRNaUlnWkQwaVRURXhNREl1TURRc05qSTFMakF4ZGkwMk5DNDROV2d6TVM0NU5tTTNMakl6TERBc01UTXVOVGtzTVM0ek1Td3hPUzR3T0N3ekxqazBMRFV1TlN3eUxqWXpMRGt1Tnprc05pNHpOU3d4TWk0NE9Dd3hNUzR4Tml3ekxqQTVMRFF1T0RJc05DNDJNeXd4TUM0MU5pdzBMall6TERFM0xqSXpjeTB4TGpVMExERXlMalV5TFRRdU5qTXNNVGN1TXpkakxUTXVNRGtzTkM0NE5TMDNMak00TERndU5Ua3RNVEl1T0Rnc01URXVNakV0TlM0MUxESXVOak10TVRFdU9EWXNNeTQ1TkMweE9TNHdPQ3d6TGprMGFDMHpNUzQ1TmxwTk1URXlNeTQ1TVN3Mk1EY3VPVFpvT1M0eE4yTXpMakE1TERBc05TNDNPUzB1TlRrc09DNHhNUzB4TGpjMkxESXVNekl0TVM0eE55dzBMakV5TFRJdU9USXNOUzQwTWkwMUxqSXpMREV1TXkweUxqTXlMREV1T1RVdE5TNHhOQ3d4TGprMUxUZ3VORGh6TFM0Mk5TMDJMakExTFRFdU9UVXRPQzR6TkdNdE1TNHpMVEl1TWpndE15NHhMVFF1TURFdE5TNDBNaTAxTGpFNUxUSXVNekl0TVM0eE55MDFMakF5TFRFdU56WXRPQzR4TVMweExqYzJhQzA1TGpFM2RqTXdMamMyV2lJdlBnb2dJQ0FnUEhCaGRHZ2dZMnhoYzNNOUltTnNjeTB5SWlCa1BTSk5NVEl5TUM0eU5TdzJNalV1TURGMkxUSTRMalEwYkRVc01UTXVNRFl0TWprdU5EWXRORGt1TkRkb01qTXVNRGRzTVRrdU9USXNNek11T0RGb0xURXpMalF6YkRJd0xqRXRNek11T0RGb01qRXVNVEpzTFRJNUxqSTNMRFE1TGpRM0xEUXVPREl0TVRNdU1EWjJNamd1TkRSb0xUSXhMamcyV2lJdlBnb2dJQ0FnUEhCaGRHZ2dZMnhoYzNNOUltTnNjeTB5SWlCa1BTSk5NVE0xTWk0M015dzJNalV1TURGMkxUWTBMamcxYURNMExqWTFZemd1T1RZc01Dd3hOUzQxTml3eExqVTVMREU1TGpnekxEUXVOemNzTkM0eU5pd3pMakU0TERZdU16a3NOeTR5TkN3MkxqTTVMREV5TGpFNExEQXNNeTR5TnkwdU9URXNOaTR4T1MweUxqY3pMRGd1TnpVdE1TNDRNaXd5TGpVMkxUUXVORFlzTkM0MU9TMDNMamt5TERZdU1EY3RNeTQwTml3eExqUTRMVGN1TnpJc01pNHlNaTB4TWk0M09Td3lMakl5YkRFdU9EVXROV00xTGpBMkxEQXNPUzQwTXk0M01Td3hNeTR4TVN3eUxqRXpMRE11Tmpjc01TNDBNaXcyTGpVeUxETXVORGNzT0M0MU1pdzJMakUyTERJdU1ERXNNaTQyT1N3ekxqQXhMRFV1T1RJc015NHdNU3c1TGpZNExEQXNOUzQyTWkweUxqTXpMREV3TFRZdU9Ua3NNVE11TVRZdE5DNDJOaXd6TGpFMUxURXhMalEzTERRdU56SXRNakF1TkRNc05DNDNNbWd0TXpZdU5WcE5NVE0zTkM0eU1pdzJNRGt1TnpKb01UTXVNVFpqTWk0ME1Td3dMRFF1TWpJdExqUXpMRFV1TkRJdE1TNHpMREV1TWkwdU9EWXNNUzQ0TVMweUxqRXpMREV1T0RFdE15NDRjeTB1TmkweUxqa3pMVEV1T0RFdE15NDRZeTB4TGpJdExqZzJMVE11TURFdE1TNHpMVFV1TkRJdE1TNHphQzB4TkM0Mk5IWXRNVFF1TkRWb01URXVOamRqTWk0ME55d3dMRFF1TWpndExqUXlMRFV1TkRJdE1TNHlOU3d4TGpFMExTNDRNeXd4TGpjeExUSXVNRElzTVM0M01TMHpMalUzY3kwdU5UY3RNaTQ0TVMweExqY3hMVE11TmpGakxURXVNVFF0TGpndE1pNDVOUzB4TGpJdE5TNDBNaTB4TGpKb0xURXdMakU1ZGpNMExqSTRXaUl2UGdvZ0lDQWdQSEJoZEdnZ1kyeGhjM005SW1Oc2N5MHlJaUJrUFNKTk1UUTBOUzR3T1N3Mk1qVXVNREZzTWpndU16VXROalF1T0RWb01qRXVORGxzTWpndU16VXNOalF1T0RWb0xUSXlMall4YkMweU1DNDVOQzAxTkM0ME4yZzRMalV5YkMweU1DNDVOQ3cxTkM0ME4yZ3RNakl1TWpOYVRURTBOakV1T1RZc05qRXpMamN4YkRVdU5UWXRNVFV1TnpWb01qa3VPRE5zTlM0MU5pd3hOUzQzTldndE5EQXVPVFZhSWk4K0NpQWdJQ0E4Y0dGMGFDQmpiR0Z6Y3owaVkyeHpMVElpSUdROUlrMHhOVFUwTGpZc05qSTFMakF4ZGkwMk5DNDROV2d5TVM0NE5uWTBOeTQ1YURJNUxqSTRkakUyTGprMWFDMDFNUzR4TkZvaUx6NEtJQ0FnSUR4d1lYUm9JR05zWVhOelBTSmpiSE10TWlJZ1pEMGlUVEUyTXpNdU5EUXNOakkxTGpBeGJESTRMak0xTFRZMExqZzFhREl4TGpRNWJESTRMak0xTERZMExqZzFhQzB5TWk0Mk1Xd3RNakF1T1RRdE5UUXVORGRvT0M0MU1td3RNakF1T1RRc05UUXVORGRvTFRJeUxqSXpXazB4TmpVd0xqTXNOakV6TGpjeGJEVXVOVFl0TVRVdU56Vm9Namt1T0ROc05TNDFOaXd4TlM0M05XZ3ROREF1T1RWYUlpOCtDaUFnSUNBOGNHRjBhQ0JqYkdGemN6MGlZMnh6TFRJaUlHUTlJazB4TnpReUxqazBMRFl5TlM0d01YWXROalF1T0RWb01UY3VPVGRzTXpJdU9UZ3NNemt1TkRkb0xUZ3VNelIyTFRNNUxqUTNhREl4TGpNeGRqWTBMamcxYUMweE55NDVOMnd0TXpJdU9UZ3RNemt1TkRkb09DNHpOSFl6T1M0ME4yZ3RNakV1TXpGYUlpOCtDaUFnSUNBOGNHRjBhQ0JqYkdGemN6MGlZMnh6TFRJaUlHUTlJazB4T0RjNExqYzFMRFl5Tmk0ME9XTXROUzR4T1N3d0xUa3VPVGt0TGpneUxURTBMalF4TFRJdU5EWXROQzQwTWkweExqWTBMVGd1TWpVdE15NDVOeTB4TVM0ME9TMDNMVE11TWpRdE15NHdNaTAxTGpjMkxUWXVOakV0Tnk0MU5TMHhNQzQzTlMweExqYzVMVFF1TVRRdE1pNDJPUzA0TGpjeExUSXVOamt0TVRNdU56RnpMamc1TFRrdU5UY3NNaTQyT1MweE15NDNNV014TGpjNUxUUXVNVFFzTkM0ek1TMDNMamN5TERjdU5UVXRNVEF1TnpVc015NHlOQzB6TGpBekxEY3VNRGN0TlM0ek5pd3hNUzQwT1MwMkxqazVMRFF1TkRJdE1TNDJOQ3c1TGpJeUxUSXVORFlzTVRRdU5ERXRNaTQwTml3MkxqTTJMREFzTVRJc01TNHhNU3d4Tmk0NU1Td3pMak16Y3pndU9UY3NOUzQwTkN3eE1pNHhPQ3c1TGpZemJDMHhNeTQ0TERFeUxqTXlZeTB4TGpreUxUSXVOREV0TkM0d015MDBMakk0TFRZdU16VXROUzQyTFRJdU16SXRNUzR6TXkwMExqa3pMVEV1T1RrdE55NDRNeTB4TGprNUxUSXVNamtzTUMwMExqTTFMak0zTFRZdU1qRXNNUzR4TVMweExqZzFMamMwTFRNdU5EUXNNUzQ0TWkwMExqYzNMRE11TWpRdE1TNHpNeXd4TGpReUxUSXVNellzTXk0eE5DMHpMakVzTlM0eE5DMHVOelFzTWk0d01TMHhMakV4TERRdU1qVXRNUzR4TVN3MkxqY3ljeTR6Tnl3MExqY3hMREV1TVRFc05pNDNNbU11TnpRc01pNHdNU3d4TGpjM0xETXVOeklzTXk0eExEVXVNVFFzTVM0ek15d3hMalF5TERJdU9USXNNaTQxTERRdU56Y3NNeTR5TkN3eExqZzFMamMwTERNdU9USXNNUzR4TVN3MkxqSXhMREV1TVRFc01pNDVMREFzTlM0MU1TMHVOallzTnk0NE15MHhMams1TERJdU16SXRNUzR6TXl3MExqUXpMVE11TWl3MkxqTTFMVFV1TmpGc01UTXVPQ3d4TWk0ek1tTXRNeTR5TVN3MExqRTBMVGN1TWpjc055NHpNeTB4TWk0eE9DdzVMalU1Y3kweE1DNDFOU3d6TGpNNExURTJMamt4TERNdU16aGFJaTgrQ2lBZ0lDQThjR0YwYUNCamJHRnpjejBpWTJ4ekxUSWlJR1E5SWsweE9UWXpMalF6TERZd09DNDFNbWd6TWk0ME0zWXhOaTQwT1dndE5UTXVPVEoyTFRZMExqZzFhRFV5TGpjeGRqRTJMalE1YUMwek1TNHlNbll6TVM0NE4xcE5NVGsyTVM0NU5DdzFPRFF1TWpWb01qZ3VPVEYyTVRVdU56Vm9MVEk0TGpreGRpMHhOUzQzTlZvaUx6NEtJQ0E4TDJjK0Nqd3ZjM1puUGc9PSIgc3R5bGU9ImhlaWdodDo3MnB4O3dpZHRoOmF1dG87ZGlzcGxheTpibG9jayI+PC9hPgogIDxkaXYgY2xhc3M9InNwYWNlciI+PC9kaXY+CiAgPHNwYW4gaWQ9Im1hc3Rlck5hbWVCYWRnZSIgc3R5bGU9ImZvbnQtc2l6ZToxM3B4O2ZvbnQtd2VpZ2h0OjYwMDtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2NvbG9yOnZhcigtLWFjY2VudCkiPjwvc3Bhbj4KPC9kaXY+CjxkaXYgY2xhc3M9ImRhdGUtbmF2Ij4KICA8YnV0dG9uIG9uY2xpY2s9ImNoYW5nZVBlcmlvZCgtMSkiPiYjODI0OTs8L2J1dHRvbj4KICA8YnV0dG9uIGNsYXNzPSJ0b2RheS1idG4iIGlkPSJ0b2RheUJ0biIgb25jbGljaz0iZ29Ub2RheSgpIj4mIzEyODE5Nzsgw5DCocORwozDkMK+w5DCs8OQwr7DkMK0w5DCvcORwpY8L2J1dHRvbj4KICA8ZGl2IHN0eWxlPSJwb3NpdGlvbjpyZWxhdGl2ZTtkaXNwbGF5OmlubGluZS1ibG9jayI+CiAgICA8YnV0dG9uIG9uY2xpY2s9Im9wZW5EYXRlUGlja2VyKCkiIHN0eWxlPSJiYWNrZ3JvdW5kOnZhcigtLXN1cmZhY2UpO2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyKTtib3JkZXItcmFkaXVzOnZhcigtLXJhZGl1cy1zbSk7cGFkZGluZzo2cHggMTJweDtjdXJzb3I6cG9pbnRlcjtmb250LXNpemU6MTZweDtjb2xvcjp2YXIoLS1hY2NlbnQpIiB0aXRsZT0iw5DCnsOQwrHDkcKAw5DCsMORwoLDkMK4IMOQwrTDkMKww5HCgsORwoMiPiYjMTI4MTk3OzwvYnV0dG9uPgogICAgPGlucHV0IHR5cGU9ImRhdGUiIGlkPSJkYXRlUGlja2VyIiBzdHlsZT0icG9zaXRpb246YWJzb2x1dGU7b3BhY2l0eTowO3RvcDowO2xlZnQ6MDt3aWR0aDoxMDAlO2hlaWdodDoxMDAlO2N1cnNvcjpwb2ludGVyIiBvbmNoYW5nZT0iZ29Ub0RhdGUodGhpcy52YWx1ZSkiPgogIDwvZGl2PgogIDxidXR0b24gb25jbGljaz0iY2hhbmdlUGVyaW9kKDEpIj4mIzgyNTA7PC9idXR0b24+CiAgPHNwYW4gY2xhc3M9IndlZWstbGFiZWwiIGlkPSJ3ZWVrTGFiZWwiIHN0eWxlPSJmbGV4OjEiPjwvc3Bhbj4KICA8ZGl2IGNsYXNzPSJkZXNrdG9wLW9ubHkiIHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2FwOjRweDttYXJnaW4tbGVmdDo4cHgiPgogICAgPGJ1dHRvbiBpZD0idjEiIG9uY2xpY2s9InNldFZpZXcoMSkiIHN0eWxlPSJwYWRkaW5nOjVweCAxMHB4O2JvcmRlci1yYWRpdXM6NnB4O2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyKTtiYWNrZ3JvdW5kOnZhcigtLXN1cmZhY2UpO2NvbG9yOnZhcigtLW11dGVkKTtmb250LXNpemU6MTJweDtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2ZvbnQtd2VpZ2h0OjYwMDtjdXJzb3I6cG9pbnRlciI+McOQwrQ8L2J1dHRvbj4KICAgIDxidXR0b24gaWQ9InYzIiBvbmNsaWNrPSJzZXRWaWV3KDMpIiBzdHlsZT0icGFkZGluZzo1cHggMTBweDtib3JkZXItcmFkaXVzOjZweDtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7YmFja2dyb3VuZDp2YXIoLS1zdXJmYWNlKTtjb2xvcjp2YXIoLS1tdXRlZCk7Zm9udC1zaXplOjEycHg7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtmb250LXdlaWdodDo2MDA7Y3Vyc29yOnBvaW50ZXIiPjPDkMK0PC9idXR0b24+CiAgICA8YnV0dG9uIGlkPSJ2NyIgb25jbGljaz0ic2V0Vmlldyg3KSIgc3R5bGU9InBhZGRpbmc6NXB4IDEwcHg7Ym9yZGVyLXJhZGl1czo2cHg7Ym9yZGVyOjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO2JhY2tncm91bmQ6dmFyKC0tYWNjZW50KTtjb2xvcjojMTIxMjE0O2JvcmRlci1jb2xvcjp2YXIoLS1hY2NlbnQpO2ZvbnQtc2l6ZToxMnB4O2ZvbnQtZmFtaWx5OnZhcigtLWZvbnQtaGVhZCk7Zm9udC13ZWlnaHQ6NjAwO2N1cnNvcjpwb2ludGVyIj43w5DCtDwvYnV0dG9uPgogIDwvZGl2Pgo8L2Rpdj4KPGRpdiBjbGFzcz0iY29udGVudCI+CiAgPGRpdiBjbGFzcz0id2Vlay13cmFwIj48ZGl2IGNsYXNzPSJ3ZWVrLWdyaWQiIGlkPSJ3ZWVrR3JpZCI+PC9kaXY+PC9kaXY+CjwvZGl2Pgo8ZGl2IGNsYXNzPSJtb2JpbGUtd3JhcCI+CiAgPGRpdiBjbGFzcz0ic2Nyb2xsLWNhbGVuZGFyIiBpZD0ic2Nyb2xsQ2FsIj4KICAgIDwhLS0gR2VuZXJhdGVkIGJ5IEpTIC0tPgogIDwvZGl2Pgo8L2Rpdj4KPGRpdiBjbGFzcz0idG9hc3QiIGlkPSJ0b2FzdCI+PC9kaXY+CgoKPGRpdiBjbGFzcz0ib3ZlcmxheSBoaWRkZW4iIGlkPSJtb2RhbE92ZXJsYXkiPgo8ZGl2IGNsYXNzPSJtb2RhbCI+CjxoMiBpZD0ibW9kYWxUaXRsZSI+w5DCncOQwr7DkMKyw5DCuMOQwrkgw5DCt8OQwrDDkMK/w5DCuMORwoE8L2gyPgo8ZGl2IGNsYXNzPSJmb3JtLXJvdyI+PGxhYmVsPsOQwprDkMK7w5HClsORwpTDkMK9w5HCgjwvbGFiZWw+PGlucHV0IGlkPSJmQ2xpZW50IiB0eXBlPSJ0ZXh0IiBwbGFjZWhvbGRlcj0iw5DCmsOQwrvDkcKWw5HClMOQwr3DkcKCIj48L2Rpdj4KPGRpdiBjbGFzcz0iZm9ybS1yb3ciPjxsYWJlbD7DkMKiw5DCtcOQwrvDkMK1w5HChMOQwr7DkMK9PC9sYWJlbD48aW5wdXQgaWQ9ImZQaG9uZSIgdHlwZT0idGVsIiBwbGFjZWhvbGRlcj0iKzM4ICgwX18pIF9fXy1fXy1fXyIgb25pbnB1dD0iZm10UGhvbmUodGhpcykiPjwvZGl2Pgo8ZGl2IGNsYXNzPSJmb3JtLXJvdyI+PGxhYmVsPsOQwp/DkMK+w5HCgcOQwrvDkcKDw5DCs8OQwrA8L2xhYmVsPjxzZWxlY3QgaWQ9ImZTZXJ2aWNlIj48L3NlbGVjdD48L2Rpdj4KPGRpdiBjbGFzcz0iZm9ybS1yb3ciPjxsYWJlbD7DkMKUw5DCsMORwoLDkMKwPC9sYWJlbD48aW5wdXQgaWQ9ImZEYXRlIiB0eXBlPSJkYXRlIj48L2Rpdj4KPGRpdiBjbGFzcz0iZm9ybS0yY29sIj4KPGRpdiBjbGFzcz0iZm9ybS1yb3ciPjxsYWJlbD7DkMKnw5DCsMORwoE8L2xhYmVsPgo8aW5wdXQgaWQ9ImZUaW1lIiB0eXBlPSJ0aW1lIiBzdGVwPSI5MDAiIG9uY2hhbmdlPSJ1cGRhdGVUaW1lQnRucygpIj4KPGRpdiBjbGFzcz0idGltZS1ncmlkIiBpZD0idGltZUdyaWQiPjwvZGl2Pgo8L2Rpdj4KPGRpdiBjbGFzcz0iZm9ybS1yb3ciPjxsYWJlbD7DkMKiw5HCgMOQwrjDkMKyw5DCsMOQwrvDkcKWw5HCgcORwoLDkcKMICjDkcKFw5DCsik8L2xhYmVsPgo8ZGl2IGNsYXNzPSJkdXItYnRucyIgaWQ9ImR1ckJ0bnMiPgo8YnV0dG9uIHR5cGU9ImJ1dHRvbiIgY2xhc3M9ImR1ci1idG4iIG9uY2xpY2s9InNldER1cigzMCkiPjMwIMORwoXDkMKyPC9idXR0b24+CjxidXR0b24gdHlwZT0iYnV0dG9uIiBjbGFzcz0iZHVyLWJ0biBhY3RpdmUiIG9uY2xpY2s9InNldER1cig2MCkiPjEgw5DCs8OQwr7DkMK0PC9idXR0b24+CjxidXR0b24gdHlwZT0iYnV0dG9uIiBjbGFzcz0iZHVyLWJ0biIgb25jbGljaz0ic2V0RHVyKDkwKSI+MS41IMOQwrPDkMK+w5DCtDwvYnV0dG9uPgo8YnV0dG9uIHR5cGU9ImJ1dHRvbiIgY2xhc3M9ImR1ci1idG4iIG9uY2xpY2s9InNldER1cigxMjApIj4yIMOQwrPDkMK+w5DCtDwvYnV0dG9uPgo8L2Rpdj4KPGlucHV0IGlkPSJmRHVyYXRpb24iIHR5cGU9ImhpZGRlbiIgdmFsdWU9IjYwIj4KPC9kaXY+CjwvZGl2Pgo8ZGl2IGNsYXNzPSJmb3JtLXJvdyI+PGxhYmVsPsOQwp3DkMK+w5HCgsOQwrDDkcKCw5DCusOQwrg8L2xhYmVsPjx0ZXh0YXJlYSBpZD0iZk5vdGVzIiByb3dzPSIzIj48L3RleHRhcmVhPjwvZGl2Pgo8ZGl2IGNsYXNzPSJtb2RhbC1mb290ZXIiPgo8YnV0dG9uIGNsYXNzPSJidG4gYnRuLWRhbmdlciBoaWRkZW4iIGlkPSJkZWxldGVCdG4iIG9uY2xpY2s9ImRlbGV0ZUFwcHQoKSI+w5DCksOQwrjDkMK0w5DCsMOQwrvDkMK4w5HCgsOQwrg8L2J1dHRvbj4KPGJ1dHRvbiBjbGFzcz0iYnRuIiBvbmNsaWNrPSJjbG9zZU1vZGFsKCkiPsOQwqHDkMK6w5DCsMORwoHDkcKDw5DCssOQwrDDkcKCw5DCuDwvYnV0dG9uPgo8YnV0dG9uIGNsYXNzPSJidG4gYnRuLXByaW1hcnkiIG9uY2xpY2s9InNhdmVBcHB0KCkiPsOQwpfDkMKxw5DCtcORwoDDkMK1w5DCs8ORwoLDkMK4PC9idXR0b24+CjwvZGl2PjwvZGl2PjwvZGl2Pgo8ZGl2IGNsYXNzPSJvdmVybGF5IGhpZGRlbiIgaWQ9ImRldGFpbE92ZXJsYXkiPgo8ZGl2IGNsYXNzPSJtb2RhbCI+CjxkaXYgY2xhc3M9ImRldGFpbC1iYXIiPjwvZGl2Pgo8aDIgaWQ9ImRldGFpbE5hbWUiPjwvaDI+CjxkaXYgaWQ9ImRldGFpbEJvZHkiPjwvZGl2Pgo8ZGl2IGNsYXNzPSJtb2RhbC1mb290ZXIiPgo8YnV0dG9uIGNsYXNzPSJidG4iIG9uY2xpY2s9ImNsb3NlRGV0YWlsKCkiPsOQwpfDkMKww5DCusORwoDDkMK4w5HCgsOQwrg8L2J1dHRvbj4KPGJ1dHRvbiBjbGFzcz0iYnRuIGJ0bi1wcmltYXJ5IiBpZD0iZGV0YWlsRWRpdEJ0biI+w5DCoMOQwrXDkMK0w5DCsMOQwrPDkcKDw5DCssOQwrDDkcKCw5DCuDwvYnV0dG9uPgo8L2Rpdj48L2Rpdj48L2Rpdj4KCjxzY3JpcHQgc3JjPSIvc3RhdGljL2pzL21hc3Rlci5qcyIgZGVmZXI+PC9zY3JpcHQ+CjwvYm9keT4KPC9odG1sPg==').decode()
