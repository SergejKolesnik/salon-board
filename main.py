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
        """CREATE TABLE IF NOT EXISTS clients (id INTEGER PRIMARY KEY AUTOINCREMENT, first_name TEXT NOT NULL, last_name TEXT DEFAULT '', phone TEXT DEFAULT '', birthday TEXT DEFAULT '',
       telegram_chat_id TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
        )""",
    ])
    # Migration: add phone column if not exists
    try:
        turso_exec("ALTER TABLE appointments ADD COLUMN phone TEXT DEFAULT ''", [])
    except Exception:
        pass
    # Migration: add client_id column to appointments
    try:
    turso_exec("ALTER TABLE appointments ADD COLUMN client_id INTEGER", [])
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

MASTER_HTML = __import__('base64').b64decode('PCFET0NUWVBFIGh0bWw+CjxodG1sIGxhbmc9InVrIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9IlVURi04Ij4KPG1ldGEgbmFtZT0idmlld3BvcnQiIGNvbnRlbnQ9IndpZHRoPWRldmljZS13aWR0aCxpbml0aWFsLXNjYWxlPTEsdmlld3BvcnQtZml0PWNvdmVyIj4KPG1ldGEgbmFtZT0ibW9iaWxlLXdlYi1hcHAtY2FwYWJsZSIgY29udGVudD0ieWVzIj4KPG1ldGEgbmFtZT0iYXBwbGUtbW9iaWxlLXdlYi1hcHAtY2FwYWJsZSIgY29udGVudD0ieWVzIj4KPG1ldGEgbmFtZT0iYXBwbGUtbW9iaWxlLXdlYi1hcHAtc3RhdHVzLWJhci1zdHlsZSIgY29udGVudD0iYmxhY2stdHJhbnNsdWNlbnQiPgo8bWV0YSBuYW1lPSJhcHBsZS1tb2JpbGUtd2ViLWFwcC10aXRsZSIgY29udGVudD0iQm9keSBCYWxhbmNlIj4KPG1ldGEgbmFtZT0idGhlbWUtY29sb3IiIGNvbnRlbnQ9IiMwMEM4QjQiPgo8bGluayByZWw9Im1hbmlmZXN0IiBocmVmPSIvbWFuaWZlc3QuanNvbiI+CjxsaW5rIHJlbD0iYXBwbGUtdG91Y2gtaWNvbiIgaHJlZj0iL2FwaS9pY29uIj4KPHRpdGxlPkJvZHkgQmFsYW5jZSDigJQg0JzRltC5INGA0L7Qt9C60LvQsNC0PC90aXRsZT4KPGxpbmsgaHJlZj0iaHR0cHM6Ly9mb250cy5nb29nbGVhcGlzLmNvbS9jc3MyP2ZhbWlseT1Nb250c2VycmF0OndnaHRANTAwOzYwMDs3MDA7ODAwJmZhbWlseT1JbnRlcjp3Z2h0QDQwMDs1MDA7NjAwJmRpc3BsYXk9c3dhcCIgcmVsPSJzdHlsZXNoZWV0Ij4KPGxpbmsgcmVsPSJzdHlsZXNoZWV0IiBocmVmPSIvc3RhdGljL2Nzcy9tYXN0ZXIuY3NzIj4KPC9oZWFkPgo8Ym9keT4KPGRpdiBjbGFzcz0iYXBwIj4KPGRpdiBjbGFzcz0idG9wYmFyIj4KICA8YSBocmVmPSIvbG9naW4iIHN0eWxlPSJkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVyIj48aW1nIHNyYz0iZGF0YTppbWFnZS9zdmcreG1sO2Jhc2U2NCxQRDk0Yld3Z2RtVnljMmx2YmowaU1TNHdJaUJsYm1OdlpHbHVaejBpVlZSR0xUZ2lQejRLUEhOMlp5QnBaRDBpVEdGNVpYSmZNU0lnWkdGMFlTMXVZVzFsUFNKTVlYbGxjaUF4SWlCNGJXeHVjejBpYUhSMGNEb3ZMM2QzZHk1M015NXZjbWN2TWpBd01DOXpkbWNpSUhacFpYZENiM2c5SWpBZ01DQXlNVFV6SURFd09EQWlQZ29nSUR4a1pXWnpQZ29nSUNBZ1BITjBlV3hsUGdvZ0lDQWdJQ0F1WTJ4ekxURWdld29nSUNBZ0lDQWdJR1pwYkd3NklDTXdaR1V3WkRZN0NpQWdJQ0FnSUgwS0NpQWdJQ0FnSUM1amJITXRNaUI3Q2lBZ0lDQWdJQ0FnWm1sc2JEb2dJMlptWm1abVpqc0tJQ0FnSUNBZ2ZRb2dJQ0FnUEM5emRIbHNaVDRLSUNBOEwyUmxabk0rQ2lBZ1BIQmhkR2dnWTJ4aGMzTTlJbU5zY3kweElpQmtQU0pOTXpnMExqSXpMREl4TkM0NU9XTXRNVEF1T0RFdE5TNDFOUzB4TUM0NE1TdzBNaTR6TVMweE1DNDRNU3cwTWk0ek1TMHhNQzQ0TVN3eU5TNDVOUzB5TVM0Mk1pd3lPQzR4TVMweU1TNDJNaXd5T0M0eE1TMHhNaTQ1TnkwNExqWTFMVEV3TGpneExUUTNMalUzTFRFd0xqZ3hMVFEzTGpVM0xURTFMakUwTFRVMkxqSXlMRFF6TGpJMExUVTRMak00TERRekxqSTBMVFU0TGpNNExEQXNNQzB5TVM0Mk1pMDRMalkxTFRNNExqa3lMRFl1TkRrdE1qTXVNREVzTWpBdU1UUXRNVGN1TXl3Mk1pNDNMVGd1TmpVc09EZ3VOalVzT0M0Mk5Td3lOUzQ1TlN3eU1TNDJNaXd4TlM0eE5Dd3lNUzQyTWl3eE5TNHhOQzB4TWk0NU55d3hOeTR6TFRJMUxqazFMREV5TGprM0xUSTFMamsxTERFeUxqazNMVEk0TGpFeExUWXVORGt0TXpndU9USXRNaTR4Tmkwek9DNDVNaTB5TGpFMkxUTXdMakkzTERFeUxqazNMVEl4TGpZeUxEWTNMakF6TFRFMUxqRTBMRGc0TGpZMUxEWXVORGtzTWpFdU5qSXNNekl1TkRNc09USXVPVGNzTXpJdU5ETXNPVEl1T1RjdE9DNDJOU3cyTGpRNUxURTVMalEyTERJMUxqazFMVEUxTGpFMExEUXhMakE0TERRdU16SXNNVFV1TVRRc01qVXVPVFVzTXpJdU5ETXNNell1TnpZc01qRXVOaklzTVRBdU9ERXRNVEF1T0RFdE9DNDJOUzAwTnk0MU55MDRMalkxTFRRM0xqVTNiQzB5TkM0ME5pMDJNaTQyTm1NdE1TNHhOaTB6TGpReExUSXVNVFl0Tmk0NE5pMHlMams0TFRFd0xqTTNMVE11TWpFdE1UTXVOamN0TWpJdU1qa3ROekV1T0RNdE1URXVORGd0T1RjdU56Z3NNVEV1TURrdE1qWXVOak1zTkRjdU5UY3RNVGN1TXl3ME55NDFOeTB4Tnk0ekxEUXhMakE0TERndU5qVXNORGt1TnpNdE5Ea3VOek1zTkRrdU56TXRORGt1TnpNc01UQXVPREV0TVRBdU9ERXNNVEl1T1RjdE16Z3VPVElzTWk0eE5pMDBOQzQwTjFwTk16SXhMalV6TERVeU1TNHdPR013TERFd0xqZ3hMREFzTVRVdU1UUXROaTQwT1N3eE1pNDVOM010TVRRdU5EUXRNVFF1T1RrdE1USXVPVGN0TWpNdU56aGpNaTR4TmkweE1pNDVOeXd4TUM0NE1TMHlNUzQyTWl3eE1DNDRNUzB5TVM0Mk1pd3dMREFzT0M0Mk5Td3lNUzQyTWl3NExqWTFMRE15TGpReldpSXZQZ29nSUR4d1lYUm9JR05zWVhOelBTSmpiSE10TVNJZ1pEMGlUVE00TXk0NE5Td3lOamt1TWpsekxUUXVNeklzTXpBdU1qY3RNak11Tnpnc05qUXVPRFpqTFRFNUxqUTJMRE0wTGpVNUxUUTJMalE1TERnekxqSTBMVFEyTGpRNUxERTFNQzR5TjJ3MExqTXlMVFF1TXpJc05DNHpNaTAwTGpNeWN6SXVNVFl0TVRJdU9UY3NPQzQyTlMwME15NHlOR00yTGpRNUxUTXdMakkzTERJM0xqQXpMVFl6TGpjNExEUXhMakE0TFRreUxqazNMREV5TGpJekxUSTFMalFzTVRRdU1EVXROVEl1T1Rjc01URXVPRGt0TnpBdU1qZGFJaTgrQ2lBZ1BIQmhkR2dnWTJ4aGMzTTlJbU5zY3kweElpQmtQU0pOTXpNeExqWTFMRGczT0M0Mk5ITTFOaTQ1TVMweE1EWXVOelVzTnpJdU1EUXRNVE01TGpFNFl6RTFMakUwTFRNeUxqUXpMRFF3TFRFeE1TNHpOU3d6TWk0ME15MHhOakF0Tmk0NE5TMDBOQzR3TkMweU1DNDFOQzAzTmk0M05pMDFNaTQ1TnkwNE9TNDNNeTB6TVM0eE5pMHhNaTQwTnkwMk1TNDJNaTA1TGpjekxUY3dMakkzTFRFdU1EaHNMVEl1TVRZdE5pNDBPWE15TlM0d015MHlNUzQyTWl3NE1DNDJNaTAxTGpReFl6VTFMalU1TERFMkxqSXlMRGN4TGpneExEZzJMalE1TERjeExqZ3hMREV4TkM0MU9Td3dMRE14TGpNdE15NDRPU3d4TURBdU1UZ3RORE11TWpRc01UWXlMakUyTFRRd0xqVTFMRFl6TGpnMkxUZzRMakkyTERFeU5TNHhNeTA0T0M0eU5pd3hNalV1TVROYUlpOCtDaUFnUEhCaGRHZ2dZMnhoYzNNOUltTnNjeTB4SWlCa1BTSk5Nekl5TGpJekxEUTNOeTQ1TTNNdE5TNDBNUzB5T1M0eE9Td3hPQzR6T0MwME1HTXlNeTQzT0MweE1DNDRNU3c0Tnk0MU55MHhNUzQ0T1N3NU55NHpMVFk1TGpFNUxERXhMalEyTFRZM0xqUTVMVFE1TGpFeExUWXpMalV4TFRRNUxqRXhMVFl6TGpVeExEQXNNQ3cxTkM0MU9TMHlPQzQxTnl3M01TNDRNU3d5T1M0NU9Td3hNQzQ0TVN3ek5pNDNOaTB4TWk0NU55dzROaTQwT1MwM01TNHpOU3c1T1M0ME5pMDFNeTR3Tnl3eE1TNDNPUzAxTkM0d05Td3hOUzR4TkMwMk55NHdNeXcwTXk0eU5Gb2lMejRLSUNBOGNHRjBhQ0JqYkdGemN6MGlZMnh6TFRFaUlHUTlJazA0TURZc056TTRZelU0TERRd0xERXhOeTR5T1N3MU9TNHhPQ3d4TkRRc05qa3NNVFkyTERZeExETXlNaXczTkN3ek1qSXNOelFzTlRRd0xEY3lMRFk0TUM0d01pMHhNRFl1T0Rrc05qZ3dMakF5TFRFd05pNDRPUzB5TXpBdU9UZ3NNVFUyTGpFeExUYzVOaTQ1Tnl3MU15NHdNUzA1TURJdU1ESXNNekF1T0RrdE16Z3RPQzB4TVRVdE1qVXRNak15TFRneklpOCtDaUFnUEhCaGRHZ2dZMnhoYzNNOUltTnNjeTB4SWlCa1BTSk5PREl6TGpFc056VTFMakEwWXkweU5pNHpNeXd5Tnk0M05TMDJNUzR5T1N3ME9TNHdNeTB4TURRdU9Ea3NOak11T0RNdE16Y3VORE1zTVRJdU5Ea3ROell1T1RJc01UZ3VOek10TVRFNExqUTJMREU0TGpjekxUSTNMakUxTERBdE5UTXVNamN0Tmk0d01pMDNPQzR6TmkweE9DNHdOQzB6TWk0d09DMHhOUzR5TmkwME9DNHhNeTB6Tmk0ek1TMDBPQzR4TXkwMk15NHhOQ3d3TFRNd0xqazRMREV6TGpFMkxUVTJMalF6TERNNUxqUTVMVGMyTGpNeUxERXhMamt5TFRndU56Z3NNalF1TWpjdE1UVXVNemNzTXpjdU1ESXRNVGt1Tnpjc01USXVOelV0TkM0ek9Td3lOaTR4TWkwM0xqQTFMRFF3TGpFeExUY3VPVGdzTmk0NU9TMHhPQzQxTERFMUxqY3pMVFF3TGpBeExESTJMakl5TFRZMExqVXpMREV3TGpRNUxUSTBMalV4TERJeExqWXlMVFEyTGpBeUxETXhMamt4TFRZM0xqTXNNeTR5T1MwMkxqUTNMRGd0TVRZc01UUXRNallzTVRBdU1qa3RNVGN1TVRZc01qQXRNekVzTWpRdE16VXNNVGN1TlRFdE1UY3VOVEVzTXpZdE1UVXNNell0TVRVc01Dd3dMVEl1T1Rrc01pNHlOQzB4TXk0ME9Dd3hOUzQzTmkwekxqVTBMRFF1TlRVdE5pNDRPQ3c1TGpJM0xUa3VPVGtzTVRRdU1UTXRNelV1T0RNc05UVXVPVFV0TlRZdU1EY3NNVEEyTGpNNUxUZzNMalk0TERFM055NDVOQ3c1TWk0MU5Td3hMamcxTERFMk1TNDBOQ3d5TlM0eU1pd3lNRFl1Tnl3M01DNHdPQ3d4TXk0eE5pMHhPUzQ0T0N3eE9TNDNOQzB6T0M0eE5pd3hPUzQzTkMwMU5DNDRNU3d3TFRJNUxqRTBMVEUzTGpRNUxUVXlMakEwTFRVeUxqUTFMVFk0TGpZNUxURTFMakUyTFRZdU9UY3ROVEF1TURFdE1UY3VORGd0TnpZdU9EUXRNakl1TkMweU1TNHlNaTB6TGpnNUxUSTNMVFV0TWpjdE5Td3dMREFzT0M0NU5DMHpMakU1TERJeExUY3NNVGt0Tml3eU5pMDRMRE0zTFRFeUxEUTFMalkwTFRFMkxqWXNOekV1TmpFdE1qa3VNRElzT1RNdU9UY3ROVEl1T0RJc09TNDBOaTA1TGpjeExERTBMakU1TFRFNExqVXNNVFF1TVRrdE1qWXVNemNzTUMweE5pNDJOUzB4T1M0eE15MHlPUzR4TkMwMU55NHpPQzB6Tnk0ME55MHlOUzQ1TVMwMUxqVTFMVFV5TGpZMkxUZ3VNek10T0RBdU1qRXRPQzR6TXkwM015NDJOQ3d3TFRFME1DNDVPU3d4TUM0NU1pMHlNRFV1TlRjc05EQXVPVGd0TWk0ME55NDVNeTB4Tml3NUxURTJMRGtzTUN3d0xEZ3VNek10TVRFdU16TXNNVFV0TVRnc09TMDVMREU1TFRFM0xETXpMVEkwTERReUxqYzRMVEU1TGpRekxEYzNMamN5TFRJNExqRXNNVFF6TGprMUxUSTRMakVzTXprdU5Ea3NNQ3czTmk0d09TdzBMakUyTERFd09TNDRNeXd4TWk0ME9TdzFNaTQyTlN3eE1pNDBPU3czT0M0NU9Dd3pNaTR6T0N3M09DNDVPQ3cxT1M0Mk55d3dMREl5TGpJdE1UWXVNRFFzTkRJdU16TXRORGd1TVRNc05qQXVNemN0TWpNdU5EVXNNVE11TkRJdE5EZ3VNelFzTWpJdU5qY3ROelF1TmpZc01qY3VOelVzTWprdU1pdzNMalF4TERVMExqTXNNVGd1TWpnc056VXVNamNzTXpJdU5qRXNNamd1Tnprc01Ua3VORE1zTkRNdU1Ua3NOREl1Tnprc05ETXVNVGtzTnpBdU1EZ3NNQ3d5TWk0eUxURXdMakE0TERRMkxqQXpMVE13TGpJekxEY3hMalEzVFRVMk1DNDROeXc0TURndU5EZGpMUzQ0Tnk0d05TMHpMamczTFRrdU5EWXRNeTQ0TnkweU1TNDVOU3d3TFRJd0xqZ3lMRFF1TkRrdE5UWXVOamtzTWpVdU5EWXRNVEUwTGpBMUxUVTBMamN4TERFd0xqRTRMVGd5TGpBMkxETTRMall6TFRneUxqQTJMRGcxTGpNMExEQXNNakF1T0RJc01USXVOVFFzTXpjdU5EY3NNemN1TmpRc05Ea3VPVFlzTVRrdU56UXNPUzQzTVN3ME1DNHpNU3d4TkM0MU55dzJNUzQzTERFMExqVTNMRGt4TGpNeUxEQXNNVFl3TGpJeExUSTRMakl4TERJd05pNDNMVGcwTGpZMUxUSXpMakEwTFRJeExqYzBMVFV5TGpBMExUTTRMamcyTFRnM0xUVXhMak0xTFRNeUxqVXRNVEV1TlRZdE5qVXVNaTB4Tnk0ek5TMDVPQzR4TFRFM0xqTTFhQzA0TGprMVl5MHpMakE0TERBdE5pNHdOeTR5TkMwNExqazFMalk1TFRJMExqWTRMRFU0TGpjMUxUUXlMalEwTERFeE9DNDBPQzAwTWk0ME5Dd3hNemd1T0RNaUx6NEtJQ0E4Wno0S0lDQWdJRHh3WVhSb0lHTnNZWE56UFNKamJITXRNaUlnWkQwaVRUZzVOaTR5T0N3Mk1qVXVNREYyTFRZMExqZzFhRE0wTGpZMVl6Z3VPVFlzTUN3eE5TNDFOaXd4TGpVNUxERTVMamd6TERRdU56Y3NOQzR5Tml3ekxqRTRMRFl1TXprc055NHlOQ3cyTGpNNUxERXlMakU0TERBc015NHlOeTB1T1RFc05pNHhPUzB5TGpjekxEZ3VOelV0TVM0NE1pd3lMalUyTFRRdU5EWXNOQzQxT1MwM0xqa3lMRFl1TURjdE15NDBOaXd4TGpRNExUY3VOeklzTWk0eU1pMHhNaTQzT1N3eUxqSXliREV1T0RVdE5XTTFMakEyTERBc09TNDBNeTQzTVN3eE15NHhNU3d5TGpFekxETXVOamNzTVM0ME1pdzJMalV5TERNdU5EY3NPQzQxTWl3MkxqRTJMREl1TURFc01pNDJPU3d6TGpBeExEVXVPVElzTXk0d01TdzVMalk0TERBc05TNDJNaTB5TGpNekxERXdMVFl1T1Rrc01UTXVNVFl0TkM0Mk5pd3pMakUxTFRFeExqUTNMRFF1TnpJdE1qQXVORE1zTkM0M01tZ3RNell1TlZwTk9URTNMamM0TERZd09TNDNNbWd4TXk0eE5tTXlMalF4TERBc05DNHlNaTB1TkRNc05TNDBNaTB4TGpNc01TNHlMUzQ0Tml3eExqZ3hMVEl1TVRNc01TNDRNUzB6TGpoekxTNDJMVEl1T1RNdE1TNDRNUzB6TGpoakxURXVNaTB1T0RZdE15NHdNUzB4TGpNdE5TNDBNaTB4TGpOb0xURTBMalkwZGkweE5DNDBOV2d4TVM0Mk4yTXlMalEzTERBc05DNHlPQzB1TkRJc05TNDBNaTB4TGpJMUxERXVNVFF0TGpnekxERXVOekV0TWk0d01pd3hMamN4TFRNdU5UZHpMUzQxTnkweUxqZ3hMVEV1TnpFdE15NDJNV010TVM0eE5DMHVPQzB5TGprMUxURXVNaTAxTGpReUxURXVNbWd0TVRBdU1UbDJNelF1TWpoYUlpOCtDaUFnSUNBOGNHRjBhQ0JqYkdGemN6MGlZMnh6TFRJaUlHUTlJazB4TURJNUxqYzRMRFl5Tmk0ME9XTXROUzR6TVN3d0xURXdMakl4TFM0NE15MHhOQzQyT0MweUxqVXROQzQwT0MweExqWTNMVGd1TXpVdE5DNHdNeTB4TVM0Mk15MDNMakE1TFRNdU1qY3RNeTR3TmkwMUxqZ3lMVFl1TmpVdE55NDJOQzB4TUM0M09TMHhMamd5TFRRdU1UUXRNaTQzTXkwNExqWTFMVEl1TnpNdE1UTXVOVE56TGpreExUa3VORFlzTWk0M015MHhNeTQxTjJNeExqZ3lMVFF1TVRFc05DNHpOeTAzTGpZNUxEY3VOalF0TVRBdU56VXNNeTR5TnkwekxqQTJMRGN1TVRVdE5TNDBNaXd4TVM0Mk15MDNMakE1TERRdU5EZ3RNUzQyTnl3NUxqTTBMVEl1TlN3eE5DNDFPUzB5TGpWek1UQXVNVGt1T0RNc01UUXVOalFzTWk0MVl6UXVORFVzTVM0Mk55dzRMak14TERRdU1ETXNNVEV1TlRnc055NHdPU3d6TGpJM0xETXVNRFlzTlM0NE1pdzJMalkwTERjdU5qUXNNVEF1TnpVc01TNDRNaXcwTGpFeExESXVOek1zT0M0Mk15d3lMamN6TERFekxqVTNjeTB1T1RFc09TNHpPUzB5TGpjekxERXpMalV6WXkweExqZ3lMRFF1TVRRdE5DNHpOeXczTGpjMExUY3VOalFzTVRBdU56a3RNeTR5Tnl3ekxqQTJMVGN1TVRNc05TNDBNaTB4TVM0MU9DdzNMakE1TFRRdU5EVXNNUzQyTnkwNUxqTXNNaTQxTFRFMExqVTBMREl1TlZwTk1UQXlPUzQyT1N3Mk1EZ3VPR015TGpBMExEQXNNeTQ1TkMwdU16Y3NOUzQzTFRFdU1URXNNUzQzTmkwdU56UXNNeTR6TFRFdU9ERXNOQzQyTXkwekxqSXNNUzR6TXkweExqTTVMREl1TXpZdE15NHdPU3d6TGpFdE5TNHhMamMwTFRJdU1ERXNNUzR4TVMwMExqSTRMREV1TVRFdE5pNDRNWE10TGpNM0xUUXVPQzB4TGpFeExUWXVPREZqTFM0M05DMHlMakF4TFRFdU56Z3RNeTQzTVMwekxqRXROUzR4TFRFdU16TXRNUzR6T1MweUxqZzNMVEl1TkRVdE5DNDJNeTB6TGpJdE1TNDNOaTB1TnpRdE15NDJOaTB4TGpFeExUVXVOeTB4TGpFeGN5MHpMamswTGpNM0xUVXVOeXd4TGpFeExUTXVNeXd4TGpneExUUXVOak1zTXk0eVl5MHhMak16TERFdU16a3RNaTR6Tml3ekxqQTVMVE11TVN3MUxqRXRMamMwTERJdU1ERXRNUzR4TVN3MExqSTRMVEV1TVRFc05pNDRNWE11TXpjc05DNDRMREV1TVRFc05pNDRNV011TnpRc01pNHdNU3d4TGpjM0xETXVOekVzTXk0eExEVXVNU3d4TGpNekxERXVNemtzTWk0NE55d3lMalEyTERRdU5qTXNNeTR5Y3pNdU5qWXNNUzR4TVN3MUxqY3NNUzR4TVZvaUx6NEtJQ0FnSUR4d1lYUm9JR05zWVhOelBTSmpiSE10TWlJZ1pEMGlUVEV4TURJdU1EUXNOakkxTGpBeGRpMDJOQzQ0Tldnek1TNDVObU0zTGpJekxEQXNNVE11TlRrc01TNHpNU3d4T1M0d09Dd3pMamswTERVdU5Td3lMall6TERrdU56a3NOaTR6TlN3eE1pNDRPQ3d4TVM0eE5pd3pMakE1TERRdU9ESXNOQzQyTXl3eE1DNDFOaXcwTGpZekxERTNMakl6Y3kweExqVTBMREV5TGpVeUxUUXVOak1zTVRjdU16ZGpMVE11TURrc05DNDROUzAzTGpNNExEZ3VOVGt0TVRJdU9EZ3NNVEV1TWpFdE5TNDFMREl1TmpNdE1URXVPRFlzTXk0NU5DMHhPUzR3T0N3ekxqazBhQzB6TVM0NU5scE5NVEV5TXk0NU1TdzJNRGN1T1Rab09TNHhOMk16TGpBNUxEQXNOUzQzT1MwdU5Ua3NPQzR4TVMweExqYzJMREl1TXpJdE1TNHhOeXcwTGpFeUxUSXVPVElzTlM0ME1pMDFMakl6TERFdU15MHlMak15TERFdU9UVXROUzR4TkN3eExqazFMVGd1TkRoekxTNDJOUzAyTGpBMUxURXVPVFV0T0M0ek5HTXRNUzR6TFRJdU1qZ3RNeTR4TFRRdU1ERXROUzQwTWkwMUxqRTVMVEl1TXpJdE1TNHhOeTAxTGpBeUxURXVOell0T0M0eE1TMHhMamMyYUMwNUxqRTNkak13TGpjMldpSXZQZ29nSUNBZ1BIQmhkR2dnWTJ4aGMzTTlJbU5zY3kweUlpQmtQU0pOTVRJeU1DNHlOU3cyTWpVdU1ERjJMVEk0TGpRMGJEVXNNVE11TURZdE1qa3VORFl0TkRrdU5EZG9Nak11TURkc01Ua3VPVElzTXpNdU9ERm9MVEV6TGpRemJESXdMakV0TXpNdU9ERm9NakV1TVRKc0xUSTVMakkzTERRNUxqUTNMRFF1T0RJdE1UTXVNRFoyTWpndU5EUm9MVEl4TGpnMldpSXZQZ29nSUNBZ1BIQmhkR2dnWTJ4aGMzTTlJbU5zY3kweUlpQmtQU0pOTVRNMU1pNDNNeXcyTWpVdU1ERjJMVFkwTGpnMWFETTBMalkxWXpndU9UWXNNQ3d4TlM0MU5pd3hMalU1TERFNUxqZ3pMRFF1Tnpjc05DNHlOaXd6TGpFNExEWXVNemtzTnk0eU5DdzJMak01TERFeUxqRTRMREFzTXk0eU55MHVPVEVzTmk0eE9TMHlMamN6TERndU56VXRNUzQ0TWl3eUxqVTJMVFF1TkRZc05DNDFPUzAzTGpreUxEWXVNRGN0TXk0ME5pd3hMalE0TFRjdU56SXNNaTR5TWkweE1pNDNPU3d5TGpJeWJERXVPRFV0TldNMUxqQTJMREFzT1M0ME15NDNNU3d4TXk0eE1Td3lMakV6TERNdU5qY3NNUzQwTWl3MkxqVXlMRE11TkRjc09DNDFNaXcyTGpFMkxESXVNREVzTWk0Mk9Td3pMakF4TERVdU9USXNNeTR3TVN3NUxqWTRMREFzTlM0Mk1pMHlMak16TERFd0xUWXVPVGtzTVRNdU1UWXROQzQyTml3ekxqRTFMVEV4TGpRM0xEUXVOekl0TWpBdU5ETXNOQzQzTW1ndE16WXVOVnBOTVRNM05DNHlNaXcyTURrdU56Sm9NVE11TVRaak1pNDBNU3d3TERRdU1qSXRMalF6TERVdU5ESXRNUzR6TERFdU1pMHVPRFlzTVM0NE1TMHlMakV6TERFdU9ERXRNeTQ0Y3kwdU5pMHlMamt6TFRFdU9ERXRNeTQ0WXkweExqSXRMamcyTFRNdU1ERXRNUzR6TFRVdU5ESXRNUzR6YUMweE5DNDJOSFl0TVRRdU5EVm9NVEV1Tmpkak1pNDBOeXd3TERRdU1qZ3RMalF5TERVdU5ESXRNUzR5TlN3eExqRTBMUzQ0TXl3eExqY3hMVEl1TURJc01TNDNNUzB6TGpVM2N5MHVOVGN0TWk0NE1TMHhMamN4TFRNdU5qRmpMVEV1TVRRdExqZ3RNaTQ1TlMweExqSXROUzQwTWkweExqSm9MVEV3TGpFNWRqTTBMakk0V2lJdlBnb2dJQ0FnUEhCaGRHZ2dZMnhoYzNNOUltTnNjeTB5SWlCa1BTSk5NVFEwTlM0d09TdzJNalV1TURGc01qZ3VNelV0TmpRdU9EVm9NakV1TkRsc01qZ3VNelVzTmpRdU9EVm9MVEl5TGpZeGJDMHlNQzQ1TkMwMU5DNDBOMmc0TGpVeWJDMHlNQzQ1TkN3MU5DNDBOMmd0TWpJdU1qTmFUVEUwTmpFdU9UWXNOakV6TGpjeGJEVXVOVFl0TVRVdU56Vm9Namt1T0ROc05TNDFOaXd4TlM0M05XZ3ROREF1T1RWYUlpOCtDaUFnSUNBOGNHRjBhQ0JqYkdGemN6MGlZMnh6TFRJaUlHUTlJazB4TlRVMExqWXNOakkxTGpBeGRpMDJOQzQ0TldneU1TNDROblkwTnk0NWFESTVMakk0ZGpFMkxqazFhQzAxTVM0eE5Gb2lMejRLSUNBZ0lEeHdZWFJvSUdOc1lYTnpQU0pqYkhNdE1pSWdaRDBpVFRFMk16TXVORFFzTmpJMUxqQXhiREk0TGpNMUxUWTBMamcxYURJeExqUTViREk0TGpNMUxEWTBMamcxYUMweU1pNDJNV3d0TWpBdU9UUXROVFF1TkRkb09DNDFNbXd0TWpBdU9UUXNOVFF1TkRkb0xUSXlMakl6V2sweE5qVXdMak1zTmpFekxqY3hiRFV1TlRZdE1UVXVOelZvTWprdU9ETnNOUzQxTml3eE5TNDNOV2d0TkRBdU9UVmFJaTgrQ2lBZ0lDQThjR0YwYUNCamJHRnpjejBpWTJ4ekxUSWlJR1E5SWsweE56UXlMamswTERZeU5TNHdNWFl0TmpRdU9EVm9NVGN1T1Rkc016SXVPVGdzTXprdU5EZG9MVGd1TXpSMkxUTTVMalEzYURJeExqTXhkalkwTGpnMWFDMHhOeTQ1TjJ3dE16SXVPVGd0TXprdU5EZG9PQzR6TkhZek9TNDBOMmd0TWpFdU16RmFJaTgrQ2lBZ0lDQThjR0YwYUNCamJHRnpjejBpWTJ4ekxUSWlJR1E5SWsweE9EYzRMamMxTERZeU5pNDBPV010TlM0eE9Td3dMVGt1T1RrdExqZ3lMVEUwTGpReExUSXVORFl0TkM0ME1pMHhMalkwTFRndU1qVXRNeTQ1TnkweE1TNDBPUzAzTFRNdU1qUXRNeTR3TWkwMUxqYzJMVFl1TmpFdE55NDFOUzB4TUM0M05TMHhMamM1TFRRdU1UUXRNaTQyT1MwNExqY3hMVEl1TmprdE1UTXVOekZ6TGpnNUxUa3VOVGNzTWk0Mk9TMHhNeTQzTVdNeExqYzVMVFF1TVRRc05DNHpNUzAzTGpjeUxEY3VOVFV0TVRBdU56VXNNeTR5TkMwekxqQXpMRGN1TURjdE5TNHpOaXd4TVM0ME9TMDJMams1TERRdU5ESXRNUzQyTkN3NUxqSXlMVEl1TkRZc01UUXVOREV0TWk0ME5pdzJMak0yTERBc01USXNNUzR4TVN3eE5pNDVNU3d6TGpNemN6Z3VPVGNzTlM0ME5Dd3hNaTR4T0N3NUxqWXpiQzB4TXk0NExERXlMak15WXkweExqa3lMVEl1TkRFdE5DNHdNeTAwTGpJNExUWXVNelV0TlM0MkxUSXVNekl0TVM0ek15MDBMamt6TFRFdU9Ua3ROeTQ0TXkweExqazVMVEl1TWprc01DMDBMak0xTGpNM0xUWXVNakVzTVM0eE1TMHhMamcxTGpjMExUTXVORFFzTVM0NE1pMDBMamMzTERNdU1qUXRNUzR6TXl3eExqUXlMVEl1TXpZc015NHhOQzB6TGpFc05TNHhOQzB1TnpRc01pNHdNUzB4TGpFeExEUXVNalV0TVM0eE1TdzJMamN5Y3k0ek55dzBMamN4TERFdU1URXNOaTQzTW1NdU56UXNNaTR3TVN3eExqYzNMRE11TnpJc015NHhMRFV1TVRRc01TNHpNeXd4TGpReUxESXVPVElzTWk0MUxEUXVOemNzTXk0eU5Dd3hMamcxTGpjMExETXVPVElzTVM0eE1TdzJMakl4TERFdU1URXNNaTQ1TERBc05TNDFNUzB1TmpZc055NDRNeTB4TGprNUxESXVNekl0TVM0ek15dzBMalF6TFRNdU1pdzJMak0xTFRVdU5qRnNNVE11T0N3eE1pNHpNbU10TXk0eU1TdzBMakUwTFRjdU1qY3NOeTR6TXkweE1pNHhPQ3c1TGpVNWN5MHhNQzQxTlN3ekxqTTRMVEUyTGpreExETXVNemhhSWk4K0NpQWdJQ0E4Y0dGMGFDQmpiR0Z6Y3owaVkyeHpMVElpSUdROUlrMHhPVFl6TGpRekxEWXdPQzQxTW1nek1pNDBNM1l4Tmk0ME9XZ3ROVE11T1RKMkxUWTBMamcxYURVeUxqY3hkakUyTGpRNWFDMHpNUzR5TW5Zek1TNDROMXBOTVRrMk1TNDVOQ3cxT0RRdU1qVm9Namd1T1RGMk1UVXVOelZvTFRJNExqa3hkaTB4TlM0M05Wb2lMejRLSUNBOEwyYytDand2YzNablBnPT0iIHN0eWxlPSJoZWlnaHQ6NzJweDt3aWR0aDphdXRvO2Rpc3BsYXk6YmxvY2siPjwvYT4KICA8ZGl2IGNsYXNzPSJzcGFjZXIiPjwvZGl2PgogIDxzcGFuIGlkPSJtYXN0ZXJOYW1lQmFkZ2UiIHN0eWxlPSJmb250LXNpemU6MTNweDtmb250LXdlaWdodDo2MDA7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtjb2xvcjp2YXIoLS1hY2NlbnQpIj48L3NwYW4+CjwvZGl2Pgo8ZGl2IGNsYXNzPSJkYXRlLW5hdiI+CiAgPGJ1dHRvbiBvbmNsaWNrPSJjaGFuZ2VQZXJpb2QoLTEpIj4mIzgyNDk7PC9idXR0b24+CiAgPGJ1dHRvbiBjbGFzcz0idG9kYXktYnRuIiBpZD0idG9kYXlCdG4iIG9uY2xpY2s9ImdvVG9kYXkoKSI+JiMxMjgxOTc7INCh0YzQvtCz0L7QtNC90ZY8L2J1dHRvbj4KICA8ZGl2IHN0eWxlPSJwb3NpdGlvbjpyZWxhdGl2ZTtkaXNwbGF5OmlubGluZS1ibG9jayI+CiAgICA8YnV0dG9uIG9uY2xpY2s9Im9wZW5EYXRlUGlja2VyKCkiIHN0eWxlPSJiYWNrZ3JvdW5kOnZhcigtLXN1cmZhY2UpO2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyKTtib3JkZXItcmFkaXVzOnZhcigtLXJhZGl1cy1zbSk7cGFkZGluZzo2cHggMTJweDtjdXJzb3I6cG9pbnRlcjtmb250LXNpemU6MTZweDtjb2xvcjp2YXIoLS1hY2NlbnQpIiB0aXRsZT0i0J7QsdGA0LDRgtC4INC00LDRgtGDIj4mIzEyODE5Nzs8L2J1dHRvbj4KICAgIDxpbnB1dCB0eXBlPSJkYXRlIiBpZD0iZGF0ZVBpY2tlciIgc3R5bGU9InBvc2l0aW9uOmFic29sdXRlO29wYWNpdHk6MDt0b3A6MDtsZWZ0OjA7d2lkdGg6MTAwJTtoZWlnaHQ6MTAwJTtjdXJzb3I6cG9pbnRlciIgb25jaGFuZ2U9ImdvVG9EYXRlKHRoaXMudmFsdWUpIj4KICA8L2Rpdj4KICA8YnV0dG9uIG9uY2xpY2s9ImNoYW5nZVBlcmlvZCgxKSI+JiM4MjUwOzwvYnV0dG9uPgogIDxzcGFuIGNsYXNzPSJ3ZWVrLWxhYmVsIiBpZD0id2Vla0xhYmVsIiBzdHlsZT0iZmxleDoxIj48L3NwYW4+CiAgPGRpdiBjbGFzcz0iZGVza3RvcC1vbmx5IiBzdHlsZT0iZGlzcGxheTpmbGV4O2dhcDo0cHg7bWFyZ2luLWxlZnQ6OHB4Ij4KICAgIDxidXR0b24gaWQ9InYxIiBvbmNsaWNrPSJzZXRWaWV3KDEpIiBzdHlsZT0icGFkZGluZzo1cHggMTBweDtib3JkZXItcmFkaXVzOjZweDtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7YmFja2dyb3VuZDp2YXIoLS1zdXJmYWNlKTtjb2xvcjp2YXIoLS1tdXRlZCk7Zm9udC1zaXplOjEycHg7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtmb250LXdlaWdodDo2MDA7Y3Vyc29yOnBvaW50ZXIiPjHQtDwvYnV0dG9uPgogICAgPGJ1dHRvbiBpZD0idjMiIG9uY2xpY2s9InNldFZpZXcoMykiIHN0eWxlPSJwYWRkaW5nOjVweCAxMHB4O2JvcmRlci1yYWRpdXM6NnB4O2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyKTtiYWNrZ3JvdW5kOnZhcigtLXN1cmZhY2UpO2NvbG9yOnZhcigtLW11dGVkKTtmb250LXNpemU6MTJweDtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2ZvbnQtd2VpZ2h0OjYwMDtjdXJzb3I6cG9pbnRlciI+M9C0PC9idXR0b24+CiAgICA8YnV0dG9uIGlkPSJ2NyIgb25jbGljaz0ic2V0Vmlldyg3KSIgc3R5bGU9InBhZGRpbmc6NXB4IDEwcHg7Ym9yZGVyLXJhZGl1czo2cHg7Ym9yZGVyOjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO2JhY2tncm91bmQ6dmFyKC0tYWNjZW50KTtjb2xvcjojMTIxMjE0O2JvcmRlci1jb2xvcjp2YXIoLS1hY2NlbnQpO2ZvbnQtc2l6ZToxMnB4O2ZvbnQtZmFtaWx5OnZhcigtLWZvbnQtaGVhZCk7Zm9udC13ZWlnaHQ6NjAwO2N1cnNvcjpwb2ludGVyIj430LQ8L2J1dHRvbj4KICA8L2Rpdj4KPC9kaXY+CjxkaXYgY2xhc3M9ImNvbnRlbnQiPgogIDxkaXYgY2xhc3M9IndlZWstd3JhcCI+PGRpdiBjbGFzcz0id2Vlay1ncmlkIiBpZD0id2Vla0dyaWQiPjwvZGl2PjwvZGl2Pgo8L2Rpdj4KPGRpdiBjbGFzcz0ibW9iaWxlLXdyYXAiPgogIDxkaXYgY2xhc3M9InNjcm9sbC1jYWxlbmRhciIgaWQ9InNjcm9sbENhbCI+CiAgICA8IS0tIEdlbmVyYXRlZCBieSBKUyAtLT4KICA8L2Rpdj4KPC9kaXY+CjxkaXYgY2xhc3M9InRvYXN0IiBpZD0idG9hc3QiPjwvZGl2PgoKCjxkaXYgY2xhc3M9Im92ZXJsYXkgaGlkZGVuIiBpZD0ibW9kYWxPdmVybGF5Ij4KPGRpdiBjbGFzcz0ibW9kYWwiPgo8aDIgaWQ9Im1vZGFsVGl0bGUiPtCd0L7QstC40Lkg0LfQsNC/0LjRgTwvaDI+CjxkaXYgY2xhc3M9ImZvcm0tcm93Ij48bGFiZWw+0JrQu9GW0ZTQvdGCPC9sYWJlbD48aW5wdXQgaWQ9ImZDbGllbnQiIHR5cGU9InRleHQiIHBsYWNlaG9sZGVyPSLQmtC70ZbRlNC90YIiPjwvZGl2Pgo8ZGl2IGNsYXNzPSJmb3JtLXJvdyI+PGxhYmVsPtCi0LXQu9C10YTQvtC9PC9sYWJlbD48aW5wdXQgaWQ9ImZQaG9uZSIgdHlwZT0idGVsIiBwbGFjZWhvbGRlcj0iKzM4ICgwX18pIF9fXy1fXy1fXyIgb25pbnB1dD0iZm10UGhvbmUodGhpcykiPjwvZGl2Pgo8ZGl2IGNsYXNzPSJmb3JtLXJvdyI+PGxhYmVsPtCf0L7RgdC70YPQs9CwPC9sYWJlbD48c2VsZWN0IGlkPSJmU2VydmljZSI+PC9zZWxlY3Q+PC9kaXY+CjxkaXYgY2xhc3M9ImZvcm0tcm93Ij48bGFiZWw+0JTQsNGC0LA8L2xhYmVsPjxpbnB1dCBpZD0iZkRhdGUiIHR5cGU9ImRhdGUiPjwvZGl2Pgo8ZGl2IGNsYXNzPSJmb3JtLTJjb2wiPgo8ZGl2IGNsYXNzPSJmb3JtLXJvdyI+PGxhYmVsPtCn0LDRgTwvbGFiZWw+CjxpbnB1dCBpZD0iZlRpbWUiIHR5cGU9InRpbWUiIHN0ZXA9IjkwMCIgb25jaGFuZ2U9InVwZGF0ZVRpbWVCdG5zKCkiPgo8ZGl2IGNsYXNzPSJ0aW1lLWdyaWQiIGlkPSJ0aW1lR3JpZCI+PC9kaXY+CjwvZGl2Pgo8ZGl2IGNsYXNzPSJmb3JtLXJvdyI+PGxhYmVsPtCi0YDQuNCy0LDQu9GW0YHRgtGMICjRhdCyKTwvbGFiZWw+CjxkaXYgY2xhc3M9ImR1ci1idG5zIiBpZD0iZHVyQnRucyI+CjxidXR0b24gdHlwZT0iYnV0dG9uIiBjbGFzcz0iZHVyLWJ0biIgb25jbGljaz0ic2V0RHVyKDMwKSI+MzAg0YXQsjwvYnV0dG9uPgo8YnV0dG9uIHR5cGU9ImJ1dHRvbiIgY2xhc3M9ImR1ci1idG4gYWN0aXZlIiBvbmNsaWNrPSJzZXREdXIoNjApIj4xINCz0L7QtDwvYnV0dG9uPgo8YnV0dG9uIHR5cGU9ImJ1dHRvbiIgY2xhc3M9ImR1ci1idG4iIG9uY2xpY2s9InNldER1cig5MCkiPjEuNSDQs9C+0LQ8L2J1dHRvbj4KPGJ1dHRvbiB0eXBlPSJidXR0b24iIGNsYXNzPSJkdXItYnRuIiBvbmNsaWNrPSJzZXREdXIoMTIwKSI+MiDQs9C+0LQ8L2J1dHRvbj4KPC9kaXY+CjxpbnB1dCBpZD0iZkR1cmF0aW9uIiB0eXBlPSJoaWRkZW4iIHZhbHVlPSI2MCI+CjwvZGl2Pgo8L2Rpdj4KPGRpdiBjbGFzcz0iZm9ybS1yb3ciPjxsYWJlbD7QndC+0YLQsNGC0LrQuDwvbGFiZWw+PHRleHRhcmVhIGlkPSJmTm90ZXMiIHJvd3M9IjMiPjwvdGV4dGFyZWE+PC9kaXY+CjxkaXYgY2xhc3M9Im1vZGFsLWZvb3RlciI+CjxidXR0b24gY2xhc3M9ImJ0biBidG4tZGFuZ2VyIGhpZGRlbiIgaWQ9ImRlbGV0ZUJ0biIgb25jbGljaz0iZGVsZXRlQXBwdCgpIj7QktC40LTQsNC70LjRgtC4PC9idXR0b24+CjxidXR0b24gY2xhc3M9ImJ0biIgb25jbGljaz0iY2xvc2VNb2RhbCgpIj7QodC60LDRgdGD0LLQsNGC0Lg8L2J1dHRvbj4KPGJ1dHRvbiBjbGFzcz0iYnRuIGJ0bi1wcmltYXJ5IiBvbmNsaWNrPSJzYXZlQXBwdCgpIj7Ql9Cx0LXRgNC10LPRgtC4PC9idXR0b24+CjwvZGl2PjwvZGl2PjwvZGl2Pgo8ZGl2IGNsYXNzPSJvdmVybGF5IGhpZGRlbiIgaWQ9ImRldGFpbE92ZXJsYXkiPgo8ZGl2IGNsYXNzPSJtb2RhbCI+CjxkaXYgY2xhc3M9ImRldGFpbC1iYXIiPjwvZGl2Pgo8aDIgaWQ9ImRldGFpbE5hbWUiPjwvaDI+CjxkaXYgaWQ9ImRldGFpbEJvZHkiPjwvZGl2Pgo8ZGl2IGNsYXNzPSJtb2RhbC1mb290ZXIiPgo8YnV0dG9uIGNsYXNzPSJidG4iIG9uY2xpY2s9ImNsb3NlRGV0YWlsKCkiPtCX0LDQutGA0LjRgtC4PC9idXR0b24+CjxidXR0b24gY2xhc3M9ImJ0biBidG4tcHJpbWFyeSIgaWQ9ImRldGFpbEVkaXRCdG4iPtCg0LXQtNCw0LPRg9Cy0LDRgtC4PC9idXR0b24+CjwvZGl2PjwvZGl2PjwvZGl2PgoKPHNjcmlwdCBzcmM9Ii9zdGF0aWMvanMvbWFzdGVyLmpzIiBkZWZlcj48L3NjcmlwdD4KPC9ib2R5Pgo8L2h0bWw+').decode()
