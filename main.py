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
    # Призначити базовий шаблон
    tpl = turso("SELECT id FROM role_templates WHERE name='Майстер-базовий'")
    if tpl:
        turso_exec("INSERT OR REPLACE INTO master_roles (master_id,template_id) VALUES (?,?)", [int(rid), int(tpl[0]['id'])])
    return {"id": int(rid), **m.dict()}

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
    return [{**r, 'id': int(r['id']), 'can_view_all': bool(int(r['can_view_all'] or 0)),
             'can_add_any': bool(int(r['can_add_any'] or 0)), 'can_edit_others': bool(int(r['can_edit_others'] or 0))} for r in rows]

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
    rid = turso_exec("INSERT INTO appointments (master_id,client_name,service,appt_date,start_time,duration_min,notes) VALUES (?,?,?,?,?,?,?)",
                    [a.master_id, a.client_name, a.service, a.appt_date, a.start_time, a.duration_min, a.notes])
    rows = turso("SELECT a.*,m.name as master_name,m.color,m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.id=?", [rid])
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
init();
</script>
</body>
</html>"""

MASTER_HTML = '<!DOCTYPE html>\n<html lang="uk">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n<meta name="mobile-web-app-capable" content="yes">\n<meta name="apple-mobile-web-app-capable" content="yes">\n<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">\n<meta name="apple-mobile-web-app-title" content="Body Balance">\n<meta name="theme-color" content="#00C8B4">\n<link rel="manifest" href="/manifest.json">\n<link rel="apple-touch-icon" href="/api/icon">\n<title>Body Balance — Мій розклад</title>\n<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">\n<style>\n*{box-sizing:border-box;margin:0;padding:0}\n:root{--bg:#121214;--surface:#1E1E22;--surface2:#222227;--border:#2E2E36;--text:#E4E4E7;--muted:#A1A1AA;--hint:#71717A;--accent:#00C8B4;--accent-light:rgba(0,200,180,0.15);--danger:#F87171;--danger-light:rgba(248,113,113,.12);--radius:12px;--radius-sm:8px;--shadow:0 4px 12px rgba(0,0,0,.5);--font:\'Inter\',sans-serif;--font-head:\'Montserrat\',sans-serif}\nhtml,body{height:100%;font-family:var(--font);background:var(--bg);color:var(--text);font-size:14px}\n.app{display:flex;flex-direction:column;height:100vh}\n.topbar{display:flex;align-items:center;gap:16px;padding:0 20px;height:64px;background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0}\n.topbar img{height:48px;width:auto}\n.spacer{flex:1}\n.date-nav{display:flex;align-items:center;gap:8px;padding:12px 20px;flex-shrink:0;background:var(--surface2);border-bottom:1px solid var(--border)}\n.date-nav button{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 12px;cursor:pointer;font-family:var(--font);font-size:13px;color:var(--text)}\n.today-btn{background:var(--accent)!important;color:#121214!important;border-color:var(--accent)!important;font-weight:700!important}\n.week-label{font-family:var(--font-head);font-size:15px;font-weight:700;color:var(--text)}\n.content{flex:1;overflow:auto;padding:16px 20px}\n.week-wrap{background:var(--surface);border-radius:var(--radius);border:1px solid var(--border);overflow-x:auto}\n.week-grid{display:grid;grid-template-columns:52px repeat(7,1fr)}\n.wh{padding:10px 6px;text-align:center;border-bottom:1px solid var(--border);border-right:1px solid var(--border);background:var(--surface);position:sticky;top:0;z-index:2}\n.wh:last-child{border-right:none}\n.wh-day{font-family:var(--font-head);font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}\n.wh-date{font-family:var(--font-head);font-size:20px;font-weight:800;color:var(--text)}\n.wh.today .wh-date{color:var(--accent)}\n.wh.today{border-bottom:2px solid var(--accent)}\n.time-col{font-size:12px;color:var(--hint);text-align:right;padding:0 8px 0 0;border-right:1px solid var(--border);display:flex;align-items:flex-start;padding-top:5px;border-bottom:1px solid var(--border);height:56px;font-family:var(--font-head)}\n.slot{border-right:1px solid var(--border);border-bottom:1px solid var(--border);height:56px;padding:3px;cursor:pointer;transition:background .1s}\n.slot:last-child{border-right:none}\n.slot:hover{background:var(--accent-light)}\n.slot.break-slot{background:repeating-linear-gradient(45deg,#2A2A30,#2A2A30 5px,#222227 5px,#222227 10px);cursor:default}\n.slot.break-slot:hover{background:repeating-linear-gradient(45deg,#2A2A30,#2A2A30 5px,#222227 5px,#222227 10px)}\n.appt{border-radius:6px;padding:4px 8px 4px 11px;height:100%;display:flex;flex-direction:column;justify-content:center;cursor:pointer;border-left:3px solid var(--accent);background:var(--accent-light);box-shadow:var(--shadow)}\n.appt:hover{filter:brightness(1.1)}\n.appt .an{font-size:12px;font-weight:700;font-family:var(--font-head);color:var(--accent);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n.appt .as{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n.appt .ad{font-size:10px;color:var(--hint)}\n.overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:100;padding:16px}\n.overlay.hidden{display:none}\n.modal{background:var(--surface);border-radius:var(--radius);padding:24px;width:100%;max-width:400px;box-shadow:0 8px 32px rgba(0,0,0,.6);border:1px solid var(--border)}\n.modal h2{font-family:var(--font-head);font-size:16px;font-weight:700;margin-bottom:16px}\n.form-row{margin-bottom:12px}\n.form-row label{display:block;font-size:11px;font-weight:600;color:var(--muted);margin-bottom:4px;font-family:var(--font-head);text-transform:uppercase;letter-spacing:.3px}\n.form-row input,.form-row select,.form-row textarea{width:100%;padding:9px 11px;border:1px solid var(--border);border-radius:var(--radius-sm);font-family:var(--font);font-size:13px;background:var(--bg);color:var(--text);outline:none;transition:border-color .12s}\n.form-row input:focus,.form-row select:focus{border-color:var(--accent);box-shadow:0 0 0 2px rgba(0,200,180,.15)}\n.form-2col{display:grid;grid-template-columns:1fr 1fr;gap:12px}\n.modal-footer{display:flex;gap:8px;margin-top:16px;justify-content:flex-end}\n.btn{padding:8px 16px;border-radius:var(--radius-sm);cursor:pointer;font-family:var(--font-head);font-size:13px;font-weight:600;border:1px solid var(--border);background:var(--surface);color:var(--text)}\n.btn:hover{background:var(--surface2)}\n.btn-primary{background:var(--accent);color:#121214;border-color:var(--accent)}\n.btn-danger{background:var(--danger-light);color:var(--danger);border-color:rgba(248,113,113,.3)}\n.detail-bar{height:4px;border-radius:2px;background:var(--accent);margin-bottom:16px}\n.detail-row{display:flex;gap:10px;margin-bottom:8px}\n.dl{font-size:11px;color:var(--muted);min-width:80px;font-family:var(--font-head);text-transform:uppercase}\n.dv{font-size:14px;font-weight:500}\n.mobile-wrap{display:none;flex-direction:column;flex:1;overflow:hidden}\n.scroll-calendar{display:flex;flex:1;overflow-x:auto;overflow-y:hidden;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;scrollbar-width:none}\n.scroll-calendar::-webkit-scrollbar{display:none}\n.cal-day-col{flex:0 0 calc(100%/3);scroll-snap-align:start;display:flex;flex-direction:column;border-right:1px solid var(--border);min-width:0}\n.cal-day-col:last-child{border-right:none}\n.cal-day-header{padding:8px 6px;text-align:center;border-bottom:1px solid var(--border);background:var(--surface);position:sticky;top:0;z-index:2;flex-shrink:0}\n.cal-day-name{font-size:10px;font-weight:700;color:var(--muted);font-family:var(--font-head);text-transform:uppercase;letter-spacing:.5px}\n.cal-day-num{font-size:22px;font-weight:800;font-family:var(--font-head);color:var(--text);line-height:1}\n.cal-day-col.today .cal-day-num{color:var(--accent)}\n.cal-day-col.today .cal-day-header{border-bottom:2px solid var(--accent)}\n.cal-slots{flex:1;overflow-y:auto;padding-bottom:80px}\n.cal-slot{display:flex;gap:4px;min-height:52px;border-bottom:1px solid var(--border);padding:4px 4px 4px 2px;cursor:pointer;transition:background .1s;position:relative}\n.cal-slot:hover{background:var(--accent-light)}\n.cal-slot-time{font-size:10px;color:var(--hint);font-family:var(--font-head);width:34px;flex-shrink:0;padding-top:2px;text-align:right;padding-right:4px}\n.cal-slot-content{flex:1;min-width:0}\n.cal-appt{border-radius:5px;padding:4px 6px;border-left:3px solid var(--accent);background:var(--accent-light);cursor:pointer}\n.cal-appt-name{font-size:11px;font-weight:700;font-family:var(--font-head);color:var(--accent);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n.cal-appt-svc{font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n.cal-appt-dur{font-size:9px;color:var(--hint)}\n.cal-break{border-radius:5px;padding:4px 6px;background:#2A2A30;border-left:3px solid #78350F;font-size:10px;color:#F59E0B}\n.cal-fab{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);padding:13px 32px;background:var(--accent);color:#121214;border:none;border-radius:24px;font-family:var(--font-head);font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 4px 16px rgba(0,200,180,.4);z-index:50;white-space:nowrap}\n.m-empty{text-align:center;padding:40px 20px;color:var(--hint);font-style:italic}\n.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1A1916;color:#fff;padding:10px 20px;border-radius:20px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:200}\n.toast.show{opacity:1}\n.hidden{display:none!important}\n.desktop-only{display:none}\n@media(min-width:769px){.desktop-only{display:flex!important}}\n@media(max-width:768px){.content{display:none!important}.mobile-wrap{display:flex!important}}\n</style>\n</head>\n<body>\n<div class="app">\n<div class="topbar">\n  <img src="data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyBpZD0iTGF5ZXJfMSIgZGF0YS1uYW1lPSJMYXllciAxIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyMTUzIDEwODAiPgogIDxkZWZzPgogICAgPHN0eWxlPgogICAgICAuY2xzLTEgewogICAgICAgIGZpbGw6ICMwZGUwZDY7CiAgICAgIH0KCiAgICAgIC5jbHMtMiB7CiAgICAgICAgZmlsbDogI2UzZTRlODsKICAgICAgfQogICAgPC9zdHlsZT4KICA8L2RlZnM+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMzg0LjIzLDIxNC45OWMtMTAuODEtNS41NS0xMC44MSw0Mi4zMS0xMC44MSw0Mi4zMS0xMC44MSwyNS45NS0yMS42MiwyOC4xMS0yMS42MiwyOC4xMS0xMi45Ny04LjY1LTEwLjgxLTQ3LjU3LTEwLjgxLTQ3LjU3LTE1LjE0LTU2LjIyLDQzLjI0LTU4LjM4LDQzLjI0LTU4LjM4LDAsMC0yMS42Mi04LjY1LTM4LjkyLDYuNDktMjMuMDEsMjAuMTQtMTcuMyw2Mi43LTguNjUsODguNjUsOC42NSwyNS45NSwyMS42MiwxNS4xNCwyMS42MiwxNS4xNC0xMi45NywxNy4zLTI1Ljk1LDEyLjk3LTI1Ljk1LDEyLjk3LTI4LjExLTYuNDktMzguOTItMi4xNi0zOC45Mi0yLjE2LTMwLjI3LDEyLjk3LTIxLjYyLDY3LjAzLTE1LjE0LDg4LjY1LDYuNDksMjEuNjIsMzIuNDMsOTIuOTcsMzIuNDMsOTIuOTctOC42NSw2LjQ5LTE5LjQ2LDI1Ljk1LTE1LjE0LDQxLjA4LDQuMzIsMTUuMTQsMjUuOTUsMzIuNDMsMzYuNzYsMjEuNjIsMTAuODEtMTAuODEtOC42NS00Ny41Ny04LjY1LTQ3LjU3bC0yNC40Ni02Mi42NmMtMS4xNi0zLjQxLTIuMTYtNi44Ni0yLjk4LTEwLjM3LTMuMjEtMTMuNjctMjIuMjktNzEuODMtMTEuNDgtOTcuNzgsMTEuMDktMjYuNjMsNDcuNTctMTcuMyw0Ny41Ny0xNy4zLDQxLjA4LDguNjUsNDkuNzMtNDkuNzMsNDkuNzMtNDkuNzMsMTAuODEtMTAuODEsMTIuOTctMzguOTIsMi4xNi00NC40N1pNMzIxLjUzLDUyMS4wOGMwLDEwLjgxLDAsMTUuMTQtNi40OSwxMi45N3MtMTQuNDQtMTQuOTktMTIuOTctMjMuNzhjMi4xNi0xMi45NywxMC44MS0yMS42MiwxMC44MS0yMS42MiwwLDAsOC42NSwyMS42Miw4LjY1LDMyLjQzWiIvPgogIDxwYXRoIGNsYXNzPSJjbHMtMSIgZD0iTTM4My44NSwyNjkuMjlzLTQuMzIsMzAuMjctMjMuNzgsNjQuODZjLTE5LjQ2LDM0LjU5LTQ2LjQ5LDgzLjI0LTQ2LjQ5LDE1MC4yN2w0LjMyLTQuMzIsNC4zMi00LjMyczIuMTYtMTIuOTcsOC42NS00My4yNGM2LjQ5LTMwLjI3LDI3LjAzLTYzLjc4LDQxLjA4LTkyLjk3LDEyLjIzLTI1LjQsMTQuMDUtNTIuOTcsMTEuODktNzAuMjdaIi8+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMzMxLjY1LDg3OC42NHM1Ni45MS0xMDYuNzUsNzIuMDQtMTM5LjE4YzE1LjE0LTMyLjQzLDQwLTExMS4zNSwzMi40My0xNjAtNi44NS00NC4wNC0yMC41NC03Ni43Ni01Mi45Ny04OS43My0zMS4xNi0xMi40Ny02MS42Mi05LjczLTcwLjI3LTEuMDhsLTIuMTYtNi40OXMyNS4wMy0yMS42Miw4MC42Mi01LjQxYzU1LjU5LDE2LjIyLDcxLjgxLDg2LjQ5LDcxLjgxLDExNC41OSwwLDMxLjMtMy44OSwxMDAuMTgtNDMuMjQsMTYyLjE2LTQwLjU1LDYzLjg2LTg4LjI2LDEyNS4xMy04OC4yNiwxMjUuMTNaIi8+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMzIyLjIzLDQ3Ny45M3MtNS40MS0yOS4xOSwxOC4zOC00MGMyMy43OC0xMC44MSw4Ny41Ny0xMS44OSw5Ny4zLTY5LjE5LDExLjQ2LTY3LjQ5LTQ5LjExLTYzLjUxLTQ5LjExLTYzLjUxLDAsMCw1NC41OS0yOC41Nyw3MS44MSwyOS45OSwxMC44MSwzNi43Ni0xMi45Nyw4Ni40OS03MS4zNSw5OS40Ni01My4wNywxMS43OS01NC4wNSwxNS4xNC02Ny4wMyw0My4yNFoiLz4KICA8cGF0aCBjbGFzcz0iY2xzLTEiIGQ9Ik04MDYsNzM4YzU4LDQwLDExNy4yOSw1OS4xOCwxNDQsNjksMTY2LDYxLDMyMiw3NCwzMjIsNzQsNTQwLDcyLDY4MC4wMi0xMDYuODksNjgwLjAyLTEwNi44OS0yMzAuOTgsMTU2LjExLTc5Ni45Nyw1My4wMS05MDIuMDIsMzAuODktMzgtOC0xMTUtMjUtMjMyLTgzIi8+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNODIzLjEsNzU1LjA0Yy0yNi4zMywyNy43NS02MS4yOSw0OS4wMy0xMDQuODksNjMuODMtMzcuNDMsMTIuNDktNzYuOTIsMTguNzMtMTE4LjQ2LDE4LjczLTI3LjE1LDAtNTMuMjctNi4wMi03OC4zNi0xOC4wNC0zMi4wOC0xNS4yNi00OC4xMy0zNi4zMS00OC4xMy02My4xNCwwLTMwLjk4LDEzLjE2LTU2LjQzLDM5LjQ5LTc2LjMyLDExLjkyLTguNzgsMjQuMjctMTUuMzcsMzcuMDItMTkuNzcsMTIuNzUtNC4zOSwyNi4xMi03LjA1LDQwLjExLTcuOTgsNi45OS0xOC41LDE1LjczLTQwLjAxLDI2LjIyLTY0LjUzLDEwLjQ5LTI0LjUxLDIxLjYyLTQ2LjAyLDMxLjkxLTY3LjMsMy4yOS02LjQ3LDgtMTYsMTQtMjYsMTAuMjktMTcuMTYsMjAtMzEsMjQtMzUsMTcuNTEtMTcuNTEsMzYtMTUsMzYtMTUsMCwwLTIuOTksMi4yNC0xMy40OCwxNS43Ni0zLjU0LDQuNTUtNi44OCw5LjI3LTkuOTksMTQuMTMtMzUuODMsNTUuOTUtNTYuMDcsMTA2LjM5LTg3LjY4LDE3Ny45NCw5Mi41NSwxLjg1LDE2MS40NCwyNS4yMiwyMDYuNyw3MC4wOCwxMy4xNi0xOS44OCwxOS43NC0zOC4xNiwxOS43NC01NC44MSwwLTI5LjE0LTE3LjQ5LTUyLjA0LTUyLjQ1LTY4LjY5LTE1LjE2LTYuOTctNTAuMDEtMTcuNDgtNzYuODQtMjIuNC0yMS4yMi0zLjg5LTI3LTUtMjctNSwwLDAsOC45NC0zLjE5LDIxLTcsMTktNiwyNi04LDM3LTEyLDQ1LjY0LTE2LjYsNzEuNjEtMjkuMDIsOTMuOTctNTIuODIsOS40Ni05LjcxLDE0LjE5LTE4LjUsMTQuMTktMjYuMzcsMC0xNi42NS0xOS4xMy0yOS4xNC01Ny4zOC0zNy40Ny0yNS45MS01LjU1LTUyLjY2LTguMzMtODAuMjEtOC4zMy03My42NCwwLTE0MC45OSwxMC45Mi0yMDUuNTcsNDAuOTgtMi40Ny45My0xNiw5LTE2LDksMCwwLDguMzMtMTEuMzMsMTUtMTgsOS05LDE5LTE3LDMzLTI0LDQyLjc4LTE5LjQzLDc3LjcyLTI4LjEsMTQzLjk1LTI4LjEsMzkuNDksMCw3Ni4wOSw0LjE2LDEwOS44MywxMi40OSw1Mi42NSwxMi40OSw3OC45OCwzMi4zOCw3OC45OCw1OS42NywwLDIyLjItMTYuMDQsNDIuMzMtNDguMTMsNjAuMzctMjMuNDUsMTMuNDItNDguMzQsMjIuNjctNzQuNjYsMjcuNzUsMjkuMiw3LjQxLDU0LjMsMTguMjgsNzUuMjcsMzIuNjEsMjguNzksMTkuNDMsNDMuMTksNDIuNzksNDMuMTksNzAuMDgsMCwyMi4yLTEwLjA4LDQ2LjAzLTMwLjIzLDcxLjQ3TTU2MC44Nyw4MDguNDdjLS44Ny4wNS0zLjg3LTkuNDYtMy44Ny0yMS45NSwwLTIwLjgyLDQuNDktNTYuNjksMjUuNDYtMTE0LjA1LTU0LjcxLDEwLjE4LTgyLjA2LDM4LjYzLTgyLjA2LDg1LjM0LDAsMjAuODIsMTIuNTQsMzcuNDcsMzcuNjQsNDkuOTYsMTkuNzQsOS43MSw0MC4zMSwxNC41Nyw2MS43LDE0LjU3LDkxLjMyLDAsMTYwLjIxLTI4LjIxLDIwNi43LTg0LjY1LTIzLjA0LTIxLjc0LTUyLjA0LTM4Ljg2LTg3LTUxLjM1LTMyLjUtMTEuNTYtNjUuMi0xNy4zNS05OC4xLTE3LjM1aC04Ljk1Yy0zLjA4LDAtNi4wNy4yNC04Ljk1LjY5LTI0LjY4LDU4Ljc1LTQyLjQ0LDExOC40OC00Mi40NCwxMzguODMiLz4KICA8Zz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTg5Ni4yOCw2MjUuMDF2LTY0Ljg1aDM0LjY1YzguOTYsMCwxNS41NiwxLjU5LDE5LjgzLDQuNzcsNC4yNiwzLjE4LDYuMzksNy4yNCw2LjM5LDEyLjE4LDAsMy4yNy0uOTEsNi4xOS0yLjczLDguNzUtMS44MiwyLjU2LTQuNDYsNC41OS03LjkyLDYuMDctMy40NiwxLjQ4LTcuNzIsMi4yMi0xMi43OSwyLjIybDEuODUtNWM1LjA2LDAsOS40My43MSwxMy4xMSwyLjEzLDMuNjcsMS40Miw2LjUyLDMuNDcsOC41Miw2LjE2LDIuMDEsMi42OSwzLjAxLDUuOTIsMy4wMSw5LjY4LDAsNS42Mi0yLjMzLDEwLTYuOTksMTMuMTYtNC42NiwzLjE1LTExLjQ3LDQuNzItMjAuNDMsNC43MmgtMzYuNVpNOTE3Ljc4LDYwOS43MmgxMy4xNmMyLjQxLDAsNC4yMi0uNDMsNS40Mi0xLjMsMS4yLS44NiwxLjgxLTIuMTMsMS44MS0zLjhzLS42LTIuOTMtMS44MS0zLjhjLTEuMi0uODYtMy4wMS0xLjMtNS40Mi0xLjNoLTE0LjY0di0xNC40NWgxMS42N2MyLjQ3LDAsNC4yOC0uNDIsNS40Mi0xLjI1LDEuMTQtLjgzLDEuNzEtMi4wMiwxLjcxLTMuNTdzLS41Ny0yLjgxLTEuNzEtMy42MWMtMS4xNC0uOC0yLjk1LTEuMi01LjQyLTEuMmgtMTAuMTl2MzQuMjhaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xMDI5Ljc4LDYyNi40OWMtNS4zMSwwLTEwLjIxLS44My0xNC42OC0yLjUtNC40OC0xLjY3LTguMzUtNC4wMy0xMS42My03LjA5LTMuMjctMy4wNi01LjgyLTYuNjUtNy42NC0xMC43OS0xLjgyLTQuMTQtMi43My04LjY1LTIuNzMtMTMuNTNzLjkxLTkuNDYsMi43My0xMy41N2MxLjgyLTQuMTEsNC4zNy03LjY5LDcuNjQtMTAuNzUsMy4yNy0zLjA2LDcuMTUtNS40MiwxMS42My03LjA5LDQuNDgtMS42Nyw5LjM0LTIuNSwxNC41OS0yLjVzMTAuMTkuODMsMTQuNjQsMi41YzQuNDUsMS42Nyw4LjMxLDQuMDMsMTEuNTgsNy4wOSwzLjI3LDMuMDYsNS44Miw2LjY0LDcuNjQsMTAuNzUsMS44Miw0LjExLDIuNzMsOC42MywyLjczLDEzLjU3cy0uOTEsOS4zOS0yLjczLDEzLjUzYy0xLjgyLDQuMTQtNC4zNyw3Ljc0LTcuNjQsMTAuNzktMy4yNywzLjA2LTcuMTMsNS40Mi0xMS41OCw3LjA5LTQuNDUsMS42Ny05LjMsMi41LTE0LjU0LDIuNVpNMTAyOS42OSw2MDguOGMyLjA0LDAsMy45NC0uMzcsNS43LTEuMTEsMS43Ni0uNzQsMy4zLTEuODEsNC42My0zLjIsMS4zMy0xLjM5LDIuMzYtMy4wOSwzLjEtNS4xLjc0LTIuMDEsMS4xMS00LjI4LDEuMTEtNi44MXMtLjM3LTQuOC0xLjExLTYuODFjLS43NC0yLjAxLTEuNzgtMy43MS0zLjEtNS4xLTEuMzMtMS4zOS0yLjg3LTIuNDUtNC42My0zLjItMS43Ni0uNzQtMy42Ni0xLjExLTUuNy0xLjExcy0zLjk0LjM3LTUuNywxLjExLTMuMywxLjgxLTQuNjMsMy4yYy0xLjMzLDEuMzktMi4zNiwzLjA5LTMuMSw1LjEtLjc0LDIuMDEtMS4xMSw0LjI4LTEuMTEsNi44MXMuMzcsNC44LDEuMTEsNi44MWMuNzQsMi4wMSwxLjc3LDMuNzEsMy4xLDUuMSwxLjMzLDEuMzksMi44NywyLjQ2LDQuNjMsMy4yczMuNjYsMS4xMSw1LjcsMS4xMVoiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTExMDIuMDQsNjI1LjAxdi02NC44NWgzMS45NmM3LjIzLDAsMTMuNTksMS4zMSwxOS4wOCwzLjk0LDUuNSwyLjYzLDkuNzksNi4zNSwxMi44OCwxMS4xNiwzLjA5LDQuODIsNC42MywxMC41Niw0LjYzLDE3LjIzcy0xLjU0LDEyLjUyLTQuNjMsMTcuMzdjLTMuMDksNC44NS03LjM4LDguNTktMTIuODgsMTEuMjEtNS41LDIuNjMtMTEuODYsMy45NC0xOS4wOCwzLjk0aC0zMS45NlpNMTEyMy45MSw2MDcuOTZoOS4xN2MzLjA5LDAsNS43OS0uNTksOC4xMS0xLjc2LDIuMzItMS4xNyw0LjEyLTIuOTIsNS40Mi01LjIzLDEuMy0yLjMyLDEuOTUtNS4xNCwxLjk1LTguNDhzLS42NS02LjA1LTEuOTUtOC4zNGMtMS4zLTIuMjgtMy4xLTQuMDEtNS40Mi01LjE5LTIuMzItMS4xNy01LjAyLTEuNzYtOC4xMS0xLjc2aC05LjE3djMwLjc2WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTIyMC4yNSw2MjUuMDF2LTI4LjQ0bDUsMTMuMDYtMjkuNDYtNDkuNDdoMjMuMDdsMTkuOTIsMzMuODFoLTEzLjQzbDIwLjEtMzMuODFoMjEuMTJsLTI5LjI3LDQ5LjQ3LDQuODItMTMuMDZ2MjguNDRoLTIxLjg2WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTM1Mi43Myw2MjUuMDF2LTY0Ljg1aDM0LjY1YzguOTYsMCwxNS41NiwxLjU5LDE5LjgzLDQuNzcsNC4yNiwzLjE4LDYuMzksNy4yNCw2LjM5LDEyLjE4LDAsMy4yNy0uOTEsNi4xOS0yLjczLDguNzUtMS44MiwyLjU2LTQuNDYsNC41OS03LjkyLDYuMDctMy40NiwxLjQ4LTcuNzIsMi4yMi0xMi43OSwyLjIybDEuODUtNWM1LjA2LDAsOS40My43MSwxMy4xMSwyLjEzLDMuNjcsMS40Miw2LjUyLDMuNDcsOC41Miw2LjE2LDIuMDEsMi42OSwzLjAxLDUuOTIsMy4wMSw5LjY4LDAsNS42Mi0yLjMzLDEwLTYuOTksMTMuMTYtNC42NiwzLjE1LTExLjQ3LDQuNzItMjAuNDMsNC43MmgtMzYuNVpNMTM3NC4yMiw2MDkuNzJoMTMuMTZjMi40MSwwLDQuMjItLjQzLDUuNDItMS4zLDEuMi0uODYsMS44MS0yLjEzLDEuODEtMy44cy0uNi0yLjkzLTEuODEtMy44Yy0xLjItLjg2LTMuMDEtMS4zLTUuNDItMS4zaC0xNC42NHYtMTQuNDVoMTEuNjdjMi40NywwLDQuMjgtLjQyLDUuNDItMS4yNSwxLjE0LS44MywxLjcxLTIuMDIsMS43MS0zLjU3cy0uNTctMi44MS0xLjcxLTMuNjFjLTEuMTQtLjgtMi45NS0xLjItNS40Mi0xLjJoLTEwLjE5djM0LjI4WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTQ0NS4wOSw2MjUuMDFsMjguMzUtNjQuODVoMjEuNDlsMjguMzUsNjQuODVoLTIyLjYxbC0yMC45NC01NC40N2g4LjUybC0yMC45NCw1NC40N2gtMjIuMjNaTTE0NjEuOTYsNjEzLjcxbDUuNTYtMTUuNzVoMjkuODNsNS41NiwxNS43NWgtNDAuOTVaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xNTU0LjYsNjI1LjAxdi02NC44NWgyMS44NnY0Ny45aDI5LjI4djE2Ljk1aC01MS4xNFoiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTE2MzMuNDQsNjI1LjAxbDI4LjM1LTY0Ljg1aDIxLjQ5bDI4LjM1LDY0Ljg1aC0yMi42MWwtMjAuOTQtNTQuNDdoOC41MmwtMjAuOTQsNTQuNDdoLTIyLjIzWk0xNjUwLjMsNjEzLjcxbDUuNTYtMTUuNzVoMjkuODNsNS41NiwxNS43NWgtNDAuOTVaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xNzQyLjk0LDYyNS4wMXYtNjQuODVoMTcuOTdsMzIuOTgsMzkuNDdoLTguMzR2LTM5LjQ3aDIxLjMxdjY0Ljg1aC0xNy45N2wtMzIuOTgtMzkuNDdoOC4zNHYzOS40N2gtMjEuMzFaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xODc4Ljc1LDYyNi40OWMtNS4xOSwwLTkuOTktLjgyLTE0LjQxLTIuNDYtNC40Mi0xLjY0LTguMjUtMy45Ny0xMS40OS03LTMuMjQtMy4wMi01Ljc2LTYuNjEtNy41NS0xMC43NS0xLjc5LTQuMTQtMi42OS04LjcxLTIuNjktMTMuNzFzLjg5LTkuNTcsMi42OS0xMy43MWMxLjc5LTQuMTQsNC4zMS03LjcyLDcuNTUtMTAuNzUsMy4yNC0zLjAzLDcuMDctNS4zNiwxMS40OS02Ljk5LDQuNDItMS42NCw5LjIyLTIuNDYsMTQuNDEtMi40Niw2LjM2LDAsMTIsMS4xMSwxNi45MSwzLjMzczguOTcsNS40NCwxMi4xOCw5LjYzbC0xMy44LDEyLjMyYy0xLjkyLTIuNDEtNC4wMy00LjI4LTYuMzUtNS42LTIuMzItMS4zMy00LjkzLTEuOTktNy44My0xLjk5LTIuMjksMC00LjM1LjM3LTYuMjEsMS4xMS0xLjg1Ljc0LTMuNDQsMS44Mi00Ljc3LDMuMjQtMS4zMywxLjQyLTIuMzYsMy4xNC0zLjEsNS4xNC0uNzQsMi4wMS0xLjExLDQuMjUtMS4xMSw2Ljcycy4zNyw0LjcxLDEuMTEsNi43MmMuNzQsMi4wMSwxLjc3LDMuNzIsMy4xLDUuMTQsMS4zMywxLjQyLDIuOTIsMi41LDQuNzcsMy4yNCwxLjg1Ljc0LDMuOTIsMS4xMSw2LjIxLDEuMTEsMi45LDAsNS41MS0uNjYsNy44My0xLjk5LDIuMzItMS4zMyw0LjQzLTMuMiw2LjM1LTUuNjFsMTMuOCwxMi4zMmMtMy4yMSw0LjE0LTcuMjcsNy4zMy0xMi4xOCw5LjU5cy0xMC41NSwzLjM4LTE2LjkxLDMuMzhaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xOTYzLjQzLDYwOC41MmgzMi40M3YxNi40OWgtNTMuOTJ2LTY0Ljg1aDUyLjcxdjE2LjQ5aC0zMS4yMnYzMS44N1pNMTk2MS45NCw1ODQuMjVoMjguOTF2MTUuNzVoLTI4Ljkxdi0xNS43NVoiLz4KICA8L2c+Cjwvc3ZnPg==" alt="Body Balance">\n  <div class="spacer"></div>\n  <a href="/" style="font-size:12px;color:var(--hint);text-decoration:none;font-family:var(--font-head)">Адмін &#8594;</a>\n</div>\n<div class="date-nav">\n  <button onclick="changePeriod(-1)">&#8249;</button>\n  <div style="position:relative;display:inline-block">\n    <button class="today-btn" onclick="openDatePicker()">&#128197; Сьогодні</button>\n    <input type="date" id="datePicker" style="position:absolute;opacity:0;top:0;left:0;width:100%;height:100%;cursor:pointer" onchange="goToDate(this.value)">\n  </div>\n  <button onclick="changePeriod(1)">&#8250;</button>\n  <span class="week-label" id="weekLabel" style="flex:1"></span>\n  <div class="desktop-only" style="display:flex;gap:4px;margin-left:8px">\n    <button id="v1" onclick="setView(1)" style="padding:5px 10px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--muted);font-size:12px;font-family:var(--font-head);font-weight:600;cursor:pointer">1д</button>\n    <button id="v3" onclick="setView(3)" style="padding:5px 10px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--muted);font-size:12px;font-family:var(--font-head);font-weight:600;cursor:pointer">3д</button>\n    <button id="v7" onclick="setView(7)" style="padding:5px 10px;border-radius:6px;border:1px solid var(--border);background:var(--accent);color:#121214;border-color:var(--accent);font-size:12px;font-family:var(--font-head);font-weight:600;cursor:pointer">7д</button>\n  </div>\n</div>\n<div class="content">\n  <div class="week-wrap"><div class="week-grid" id="weekGrid"></div></div>\n</div>\n<div class="mobile-wrap">\n  <div class="scroll-calendar" id="scrollCal">\n    <!-- Generated by JS -->\n  </div>\n</div>\n<div class="toast" id="toast"></div>\n<script>\nconst HOURS=Array.from({length:10},(_,i)=>`${String(i+9).padStart(2,"0")}:00`);\nconst DAYS=["Нд","Пн","Вт","Ср","Чт","Пт","Сб"];\nconst MONTHS=["січня","лютого","березня","квітня","травня","червня","липня","серпня","вересня","жовтня","листопада","грудня"];\nlet appointments=[],breaks=[],masterId=null,services=[];\nlet viewDays=7,periodStart=getMonday(new Date());\nlet weekStart=getMonday(new Date());\nlet editingId=null,mobileDay=new Date();\n\nfunction setView(n){\n  viewDays=n;\n  if(n===1) periodStart=new Date(mobileDay);\n  else if(n===3){ const d=new Date(mobileDay); d.setDate(d.getDate()-1); periodStart=d; }\n  else periodStart=getMonday(new Date());\n  weekStart=new Date(periodStart);\n  ["v1","v3","v7"].forEach(id=>{\n    const el=document.getElementById(id);\n    if(el){el.style.background=id==="v"+n?"var(--accent)":"var(--surface)";el.style.color=id==="v"+n?"#121214":"var(--muted)";el.style.borderColor=id==="v"+n?"var(--accent)":"var(--border)";}\n  });\n  loadWeek();\n}\nfunction changePeriod(d){periodStart=addDays(periodStart,d*viewDays);weekStart=new Date(periodStart);loadWeek();}\nfunction getMonday(d){const r=new Date(d),day=r.getDay(),diff=r.getDate()-day+(day===0?-6:1);r.setDate(diff);r.setHours(0,0,0,0);return r;}\nfunction isoDate(d){return d.toISOString().slice(0,10);}\nfunction addDays(d,n){const r=new Date(d);r.setDate(r.getDate()+n);return r;}\nfunction fmtDate(iso){const[y,m,day]=iso.split("-");return `${parseInt(day)} ${MONTHS[parseInt(m)-1]}`;}\nfunction toMin(t){const[h,m]=t.split(":").map(Number);return h*60+m;}\nasync function loadWeek(){\n  if(!masterId){const ms=await fetch("/api/masters").then(r=>r.json());if(ms.length)masterId=ms[0].id;}\n  if(!masterId)return;\n  if(!services.length){services=await fetch("/api/services").then(r=>r.json());updateDatalist();}\n  const isMobile=window.innerWidth<=640;\n  const loadDays=isMobile?14:viewDays;\n  const loadStart=isMobile?addDays(periodStart,-1):periodStart;\n  const days=Array.from({length:loadDays},(_,i)=>isoDate(addDays(loadStart,i)));\n  const from=days[0],to=days[days.length-1];\n  const[ap,br]=await Promise.all([\n    fetch(`/api/appointments/range?master_id=${masterId}&from_date=${from}&to_date=${to}`).then(r=>r.json()),\n    fetch(`/api/breaks/range?master_id=${masterId}&from_date=${from}&to_date=${to}`).then(r=>r.json()),\n  ]);\n  appointments=ap;breaks=br;renderAll();\n}\nfunction updateDatalist(){\n  const dl=document.getElementById("serviceList");\n  if(dl&&services.length) dl.innerHTML=services.map(s=>`<option value="${s.name}">`).join("");\n}\nfunction renderAll(){\n  const days=Array.from({length:viewDays},(_,i)=>addDays(periodStart,i));\n  const today=isoDate(new Date());\n  const f=fmtDate(isoDate(days[0])),t=viewDays>1?fmtDate(isoDate(days[days.length-1])):"";\n  document.getElementById("weekLabel").textContent=viewDays===1?`${DAYS[days[0].getDay()]}, ${fmtDate(isoDate(days[0]))}`:(`${f} — ${t}`);\n  renderGrid(days,today);\n  renderScrollCalendar();\n}\n\nfunction renderGrid(days,today){\n  const g=document.getElementById("weekGrid");\n  let h=`<div class="wh"></div>`;\n  days.forEach(d=>{const iso=isoDate(d),iT=iso===today;h+=`<div class="wh${iT?" today":""}"><div class="wh-day">${DAYS[d.getDay()]}</div><div class="wh-date">${d.getDate()}</div></div>`;});\n  HOURS.forEach(hr=>{\n    h+=`<div class="time-col">${hr}</div>`;\n    days.forEach(d=>{\n      const iso=isoDate(d);\n      const isB=breaks.some(b=>b.break_date===iso&&toMin(b.start_time)<=toMin(hr)&&toMin(b.end_time)>toMin(hr));\n      const ap=appointments.find(a=>a.appt_date===iso&&a.start_time===hr);\n      if(isB){h+=`<div class="slot break-slot"></div>`;}\n      else if(ap){h+=`<div class="slot"><div class="appt" onclick="openDetail(${ap.id})"><div class="an">${ap.client_name}</div><div class="as">${ap.service}</div><div class="ad">${ap.duration_min} хв</div></div></div>`;}\n      else{h+=`<div class="slot" onclick="openAddOnSlot(\'${iso}\',\'${hr}\')"></div>`;}\n    });\n  });\n  g.innerHTML=h;\n}\nfunction renderMobileDays(days,today){}\nfunction renderMobileList(){}\n\nfunction renderScrollCalendar(){\n  const cal=document.getElementById("scrollCal");\n  if(!cal)return;\n  const today=isoDate(new Date());\n  // Show 14 days starting from periodStart - 1 (so current day is in middle column)\n  const startDay=addDays(periodStart,-1);\n  const numDays=14;\n  const hours=Array.from({length:9},(_,i)=>String(i+10).padStart(2,"0")+":00");\n\n  // Remove old fab if exists\n  const oldFab=document.getElementById("calFab");\n  if(oldFab)oldFab.remove();\n\n  cal.innerHTML=Array.from({length:numDays},(_,di)=>{\n    const d=addDays(startDay,di);\n    const iso=isoDate(d);\n    const isToday=iso===today;\n    const da=appointments.filter(a=>a.appt_date===iso);\n    const db=breaks.filter(b=>b.break_date===iso);\n    const slots=hours.map(hr=>{\n      const isB=db.some(b=>toMin(b.start_time)<=toMin(hr)&&toMin(b.end_time)>toMin(hr));\n      const ap=da.find(a=>a.start_time===hr);\n      let inner="";\n      if(isB) inner=`<div class="cal-break">Перерва</div>`;\n      else if(ap) inner=`<div class="cal-appt" onclick="event.stopPropagation();openDetail(${ap.id})"><div class="cal-appt-name">${ap.client_name}</div><div class="cal-appt-svc">${ap.service}</div><div class="cal-appt-dur">${ap.duration_min}хв</div></div>`;\n      return `<div class="cal-slot" onclick="openAddOnSlot(\'${iso}\',\'${hr}\')"><div class="cal-slot-time">${hr}</div><div class="cal-slot-content">${inner}</div></div>`;\n    }).join("");\n    return `<div class="cal-day-col${isToday?" today":""}">\n      <div class="cal-day-header"><div class="cal-day-name">${DAYS[d.getDay()]}</div><div class="cal-day-num">${d.getDate()}</div></div>\n      <div class="cal-slots">${slots}</div>\n    </div>`;\n  }).join("");\n\n  // Scroll to today (3rd column = index 1 which is periodStart)\n  setTimeout(()=>{\n    const cols=cal.querySelectorAll(".cal-day-col");\n    if(cols[1]) cols[1].scrollIntoView({behavior:"instant",inline:"start"});\n  },50);\n\n  // Add FAB\n  const fab=document.createElement("button");\n  fab.id="calFab";\n  fab.className="cal-fab";\n  fab.textContent="+ Новий запис";\n  fab.onclick=()=>openAddModal(isoDate(periodStart),"10:00");\n  document.querySelector(".mobile-wrap").appendChild(fab);\n}\nfunction changeWeek(d){weekStart=addDays(weekStart,d*7);loadWeek();}\nfunction goToday(){\n  periodStart=viewDays===7?getMonday(new Date()):new Date();\n  weekStart=new Date(periodStart);\n  mobileDay=new Date();\n  loadWeek();\n}\nfunction openDatePicker(){\n  const dp=document.getElementById("datePicker");\n  dp.value=isoDate(periodStart);\n  dp.showPicker&&dp.showPicker();\n}\nfunction goToDate(iso){\n  if(!iso)return;\n  periodStart=new Date(iso+"T12:00:00");\n  weekStart=new Date(periodStart);\n  mobileDay=new Date(periodStart);\n  loadWeek();\n}\nfunction setMobileDay(iso){mobileDay=new Date(iso+"T12:00:00");}\nfunction openAddModal(date,time){\n  editingId=null;\n  document.getElementById("modalTitle").textContent="Новий запис";\n  document.getElementById("deleteBtn").classList.add("hidden");\n  document.getElementById("fClient").value="";\n  document.getElementById("fService").value="";\n  document.getElementById("fDate").value=date||isoDate(mobileDay||new Date());\n  document.getElementById("fTime").value=time||"10:00";\n  document.getElementById("fDuration").value="60";\n  document.getElementById("fNotes").value="";\n  document.getElementById("modalOverlay").classList.remove("hidden");\n  // Focus on client name field\n  setTimeout(()=>document.getElementById("fClient").focus(),100);\n}\nfunction openAddOnSlot(date,time){openAddModal(date,time);}\nfunction closeModal(){document.getElementById("modalOverlay").classList.add("hidden");}\nfunction openDetail(id){\n  const a=appointments.find(x=>x.id==id);if(!a)return;\n  document.getElementById("detailName").textContent=a.client_name;\n  document.getElementById("detailBody").innerHTML=`<div class="detail-row"><span class="dl">Послуга</span><span class="dv">${a.service}</span></div><div class="detail-row"><span class="dl">Дата</span><span class="dv">${fmtDate(a.appt_date)}</span></div><div class="detail-row"><span class="dl">Час</span><span class="dv">${a.start_time}, ${a.duration_min} хв</span></div>${a.notes?`<div class="detail-row"><span class="dl">Нотатки</span><span class="dv">${a.notes}</span></div>`:""}`;\n  document.getElementById("detailEditBtn").onclick=()=>{\n    editingId=a.id;\n    document.getElementById("modalTitle").textContent="Редагувати";\n    document.getElementById("deleteBtn").classList.remove("hidden");\n    document.getElementById("fClient").value=a.client_name;\n    document.getElementById("fService").value=a.service;\n    document.getElementById("fDate").value=a.appt_date;\n    document.getElementById("fTime").value=a.start_time;\n    document.getElementById("fDuration").value=a.duration_min;\n    document.getElementById("fNotes").value=a.notes||"";\n    closeDetail();\n    document.getElementById("modalOverlay").classList.remove("hidden");\n  };\n  document.getElementById("detailOverlay").classList.remove("hidden");\n}\nfunction closeDetail(){document.getElementById("detailOverlay").classList.add("hidden");}\ndocument.getElementById("modalOverlay")&&document.getElementById("modalOverlay").addEventListener("click",e=>{if(e.target===e.currentTarget)closeModal();});\ndocument.getElementById("detailOverlay")&&document.getElementById("detailOverlay").addEventListener("click",e=>{if(e.target===e.currentTarget)closeDetail();});\nasync function saveAppt(){\n  const body={master_id:masterId,client_name:document.getElementById("fClient").value.trim(),service:document.getElementById("fService").value.trim(),appt_date:document.getElementById("fDate").value,start_time:document.getElementById("fTime").value,duration_min:parseInt(document.getElementById("fDuration").value),notes:document.getElementById("fNotes").value.trim()};\n  if(!body.client_name||!body.service){alert("Заповніть ім\\u0027я і послугу");return;}\n  const url=editingId?`/api/appointments/${editingId}`:"/api/appointments";\n  const res=await fetch(url,{method:editingId?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});\n  if(!res.ok){const e=await res.json();alert(e.detail||"Помилка");return;}\n  closeModal();showToast(editingId?"Оновлено":"Збережено");\n  mobileDay=new Date(body.appt_date+"T12:00:00");\n  await loadWeek();\n}\nasync function deleteAppt(){\n  if(!editingId||!confirm("Видалити запис?"))return;\n  await fetch(`/api/appointments/${editingId}`,{method:"DELETE"});\n  closeModal();showToast("Видалено");await loadWeek();\n}\nfunction showToast(msg){const t=document.getElementById("toast");t.textContent=msg;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),2500);}\n// Force mobile layout check\nfunction applyLayout(){\n  const isMobile=window.innerWidth<=768||(\'ontouchstart\' in window&&window.innerWidth<=1024);\n  document.querySelector(".content").style.display=isMobile?"none":"";\n  document.querySelector(".mobile-wrap").style.display=isMobile?"flex":"none";\n}\napplyLayout();\nwindow.addEventListener("resize",applyLayout);\nsetTimeout(loadWeek,0);\n</script>\n\n<div class="overlay hidden" id="modalOverlay">\n  <div class="modal">\n    <h2 id="modalTitle">Новий запис</h2>\n    <div class="form-row"><label>Клієнт</label><input id="fClient" type="text" placeholder="Ім&apos;я клієнта"></div>\n    <div class="form-row" id="serviceList"><label>Послуга</label><select id="fService"></select></div>\n    <div class="form-row"><label>Дата</label><input id="fDate" type="date"></div>\n    <div class="form-2col">\n      <div class="form-row"><label>Час</label><input id="fTime" type="time" step="900"></div>\n      <div class="form-row"><label>Тривалість (хв)</label><input id="fDuration" type="number" min="15" step="15" value="60"></div>\n    </div>\n    <div class="form-row"><label>Нотатки</label><textarea id="fNotes" rows="3" placeholder="Додаткова інформація..."></textarea></div>\n    <div class="modal-footer">\n      <button class="btn btn-danger hidden" id="deleteBtn" onclick="deleteAppt()">Видалити</button>\n      <button class="btn" onclick="closeModal()">Скасувати</button>\n      <button class="btn btn-primary" onclick="saveAppt()">Зберегти</button>\n    </div>\n  </div>\n</div>\n<div class="overlay hidden" id="detailOverlay">\n  <div class="modal">\n    <div class="detail-bar"></div>\n    <h2 id="detailName"></h2>\n    <div id="detailBody"></div>\n    <div class="modal-footer">\n      <button class="btn" onclick="closeDetail()">Закрити</button>\n      <button class="btn btn-primary" id="detailEditBtn" onclick="editFromDetail()">Редагувати</button>\n    </div>\n  </div>\n</div>\n</body>\n</html>'
