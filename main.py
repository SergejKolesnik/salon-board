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

MASTER_HTML = __import__('base64').b64decode('PCFET0NUWVBFIGh0bWw+CjxodG1sIGxhbmc9InVrIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9IlVURi04Ij4KPG1ldGEgbmFtZT0idmlld3BvcnQiIGNvbnRlbnQ9IndpZHRoPWRldmljZS13aWR0aCxpbml0aWFsLXNjYWxlPTEsdmlld3BvcnQtZml0PWNvdmVyIj4KPG1ldGEgbmFtZT0ibW9iaWxlLXdlYi1hcHAtY2FwYWJsZSIgY29udGVudD0ieWVzIj4KPG1ldGEgbmFtZT0iYXBwbGUtbW9iaWxlLXdlYi1hcHAtY2FwYWJsZSIgY29udGVudD0ieWVzIj4KPG1ldGEgbmFtZT0iYXBwbGUtbW9iaWxlLXdlYi1hcHAtc3RhdHVzLWJhci1zdHlsZSIgY29udGVudD0iYmxhY2stdHJhbnNsdWNlbnQiPgo8bWV0YSBuYW1lPSJhcHBsZS1tb2JpbGUtd2ViLWFwcC10aXRsZSIgY29udGVudD0iQm9keSBCYWxhbmNlIj4KPG1ldGEgbmFtZT0idGhlbWUtY29sb3IiIGNvbnRlbnQ9IiMwMEM4QjQiPgo8bGluayByZWw9Im1hbmlmZXN0IiBocmVmPSIvbWFuaWZlc3QuanNvbiI+CjxsaW5rIHJlbD0iYXBwbGUtdG91Y2gtaWNvbiIgaHJlZj0iL2FwaS9pY29uIj4KPHRpdGxlPkJvZHkgQmFsYW5jZSDigJQg0JzRltC5INGA0L7Qt9C60LvQsNC0PC90aXRsZT4KPGxpbmsgaHJlZj0iaHR0cHM6Ly9mb250cy5nb29nbGVhcGlzLmNvbS9jc3MyP2ZhbWlseT1Nb250c2VycmF0OndnaHRANTAwOzYwMDs3MDA7ODAwJmZhbWlseT1JbnRlcjp3Z2h0QDQwMDs1MDA7NjAwJmRpc3BsYXk9c3dhcCIgcmVsPSJzdHlsZXNoZWV0Ij4KPHN0eWxlPgoqe2JveC1zaXppbmc6Ym9yZGVyLWJveDttYXJnaW46MDtwYWRkaW5nOjB9Cjpyb290ey0tYmc6IzEyMTIxNDstLXN1cmZhY2U6IzFFMUUyMjstLXN1cmZhY2UyOiMyMjIyMjc7LS1ib3JkZXI6IzJFMkUzNjstLXRleHQ6I0U0RTRFNzstLW11dGVkOiNBMUExQUE7LS1oaW50OiM3MTcxN0E7LS1hY2NlbnQ6IzAwQzhCNDstLWFjY2VudC1saWdodDpyZ2JhKDAsMjAwLDE4MCwwLjE1KTstLWRhbmdlcjojRjg3MTcxOy0tZGFuZ2VyLWxpZ2h0OnJnYmEoMjQ4LDExMywxMTMsLjEyKTstLXJhZGl1czoxMnB4Oy0tcmFkaXVzLXNtOjhweDstLXNoYWRvdzowIDRweCAxMnB4IHJnYmEoMCwwLDAsLjUpOy0tZm9udDonSW50ZXInLHNhbnMtc2VyaWY7LS1mb250LWhlYWQ6J01vbnRzZXJyYXQnLHNhbnMtc2VyaWZ9Cmh0bWwsYm9keXtoZWlnaHQ6MTAwJTtmb250LWZhbWlseTp2YXIoLS1mb250KTtiYWNrZ3JvdW5kOnZhcigtLWJnKTtjb2xvcjp2YXIoLS10ZXh0KTtmb250LXNpemU6MTRweH0KLmFwcHtkaXNwbGF5OmZsZXg7ZmxleC1kaXJlY3Rpb246Y29sdW1uO2hlaWdodDoxMDB2aH0KLnRvcGJhcntkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2dhcDoxNnB4O3BhZGRpbmc6MCAyMHB4O2hlaWdodDo2NHB4O2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZSk7Ym9yZGVyLWJvdHRvbToxcHggc29saWQgdmFyKC0tYm9yZGVyKTtmbGV4LXNocmluazowfQoudG9wYmFyIGltZ3toZWlnaHQ6NDhweDt3aWR0aDphdXRvfQouc3BhY2Vye2ZsZXg6MX0KLmRhdGUtbmF2e2Rpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7Z2FwOjhweDtwYWRkaW5nOjEycHggMjBweDtmbGV4LXNocmluazowO2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZTIpO2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWJvcmRlcil9Ci5kYXRlLW5hdiBidXR0b257YmFja2dyb3VuZDp2YXIoLS1zdXJmYWNlKTtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7Ym9yZGVyLXJhZGl1czp2YXIoLS1yYWRpdXMtc20pO3BhZGRpbmc6NnB4IDEycHg7Y3Vyc29yOnBvaW50ZXI7Zm9udC1mYW1pbHk6dmFyKC0tZm9udCk7Zm9udC1zaXplOjEzcHg7Y29sb3I6dmFyKC0tdGV4dCl9Ci50b2RheS1idG57YmFja2dyb3VuZDp2YXIoLS1hY2NlbnQpIWltcG9ydGFudDtjb2xvcjojMTIxMjE0IWltcG9ydGFudDtib3JkZXItY29sb3I6dmFyKC0tYWNjZW50KSFpbXBvcnRhbnQ7Zm9udC13ZWlnaHQ6NzAwIWltcG9ydGFudH0KLndlZWstbGFiZWx7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtmb250LXNpemU6MTVweDtmb250LXdlaWdodDo3MDA7Y29sb3I6dmFyKC0tdGV4dCl9Ci5jb250ZW50e2ZsZXg6MTtvdmVyZmxvdzphdXRvO3BhZGRpbmc6MTZweCAyMHB4fQoud2Vlay13cmFwe2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZSk7Ym9yZGVyLXJhZGl1czp2YXIoLS1yYWRpdXMpO2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyKTtvdmVyZmxvdy14OmF1dG99Ci53ZWVrLWdyaWR7ZGlzcGxheTpncmlkO2dyaWQtdGVtcGxhdGUtY29sdW1uczo1MnB4IHJlcGVhdCg3LDFmcil9Ci53aHtwYWRkaW5nOjEwcHggNnB4O3RleHQtYWxpZ246Y2VudGVyO2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7Ym9yZGVyLXJpZ2h0OjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZSk7cG9zaXRpb246c3RpY2t5O3RvcDowO3otaW5kZXg6Mn0KLndoOmxhc3QtY2hpbGR7Ym9yZGVyLXJpZ2h0Om5vbmV9Ci53aC1kYXl7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtmb250LXNpemU6MTFweDtmb250LXdlaWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0ZWQpO3RleHQtdHJhbnNmb3JtOnVwcGVyY2FzZTtsZXR0ZXItc3BhY2luZzouNXB4fQoud2gtZGF0ZXtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2ZvbnQtc2l6ZToyMHB4O2ZvbnQtd2VpZ2h0OjgwMDtjb2xvcjp2YXIoLS10ZXh0KX0KLndoLnRvZGF5IC53aC1kYXRle2NvbG9yOnZhcigtLWFjY2VudCl9Ci53aC50b2RheXtib3JkZXItYm90dG9tOjJweCBzb2xpZCB2YXIoLS1hY2NlbnQpfQoudGltZS1jb2x7Zm9udC1zaXplOjEycHg7Y29sb3I6dmFyKC0taGludCk7dGV4dC1hbGlnbjpyaWdodDtwYWRkaW5nOjAgOHB4IDAgMDtib3JkZXItcmlnaHQ6MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7ZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmZsZXgtc3RhcnQ7cGFkZGluZy10b3A6NXB4O2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7aGVpZ2h0OjU2cHg7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKX0KLnNsb3R7Ym9yZGVyLXJpZ2h0OjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7aGVpZ2h0OjU2cHg7cGFkZGluZzozcHg7Y3Vyc29yOnBvaW50ZXI7dHJhbnNpdGlvbjpiYWNrZ3JvdW5kIC4xc30KLnNsb3Q6bGFzdC1jaGlsZHtib3JkZXItcmlnaHQ6bm9uZX0KLnNsb3Q6aG92ZXJ7YmFja2dyb3VuZDp2YXIoLS1hY2NlbnQtbGlnaHQpfQouc2xvdC5icmVhay1zbG90e2JhY2tncm91bmQ6cmVwZWF0aW5nLWxpbmVhci1ncmFkaWVudCg0NWRlZywjMkEyQTMwLCMyQTJBMzAgNXB4LCMyMjIyMjcgNXB4LCMyMjIyMjcgMTBweCk7Y3Vyc29yOmRlZmF1bHR9Ci5zbG90LmJyZWFrLXNsb3Q6aG92ZXJ7YmFja2dyb3VuZDpyZXBlYXRpbmctbGluZWFyLWdyYWRpZW50KDQ1ZGVnLCMyQTJBMzAsIzJBMkEzMCA1cHgsIzIyMjIyNyA1cHgsIzIyMjIyNyAxMHB4KX0KLmFwcHR7Ym9yZGVyLXJhZGl1czo2cHg7cGFkZGluZzo0cHggOHB4IDRweCAxMXB4O2hlaWdodDoxMDAlO2Rpc3BsYXk6ZmxleDtmbGV4LWRpcmVjdGlvbjpjb2x1bW47anVzdGlmeS1jb250ZW50OmNlbnRlcjtjdXJzb3I6cG9pbnRlcjtib3JkZXItbGVmdDozcHggc29saWQgdmFyKC0tYWNjZW50KTtiYWNrZ3JvdW5kOnZhcigtLWFjY2VudC1saWdodCk7Ym94LXNoYWRvdzp2YXIoLS1zaGFkb3cpfQouYXBwdDpob3ZlcntmaWx0ZXI6YnJpZ2h0bmVzcygxLjEpfQouYXBwdCAuYW57Zm9udC1zaXplOjEycHg7Zm9udC13ZWlnaHQ6NzAwO2ZvbnQtZmFtaWx5OnZhcigtLWZvbnQtaGVhZCk7Y29sb3I6dmFyKC0tYWNjZW50KTt3aGl0ZS1zcGFjZTpub3dyYXA7b3ZlcmZsb3c6aGlkZGVuO3RleHQtb3ZlcmZsb3c6ZWxsaXBzaXN9Ci5hcHB0IC5hc3tmb250LXNpemU6MTFweDtjb2xvcjp2YXIoLS1tdXRlZCk7d2hpdGUtc3BhY2U6bm93cmFwO292ZXJmbG93OmhpZGRlbjt0ZXh0LW92ZXJmbG93OmVsbGlwc2lzfQouYXBwdCAuYWR7Zm9udC1zaXplOjEwcHg7Y29sb3I6dmFyKC0taGludCl9Ci5vdmVybGF5e3Bvc2l0aW9uOmZpeGVkO2luc2V0OjA7YmFja2dyb3VuZDpyZ2JhKDAsMCwwLC41KTtkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2p1c3RpZnktY29udGVudDpjZW50ZXI7ei1pbmRleDoxMDA7cGFkZGluZzoxNnB4fQoub3ZlcmxheS5oaWRkZW57ZGlzcGxheTpub25lfQoubW9kYWx7YmFja2dyb3VuZDp2YXIoLS1zdXJmYWNlKTtib3JkZXItcmFkaXVzOnZhcigtLXJhZGl1cyk7cGFkZGluZzoyNHB4O3dpZHRoOjEwMCU7bWF4LXdpZHRoOjQwMHB4O2JveC1zaGFkb3c6MCA4cHggMzJweCByZ2JhKDAsMCwwLC42KTtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcil9Ci5tb2RhbCBoMntmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2ZvbnQtc2l6ZToxNnB4O2ZvbnQtd2VpZ2h0OjcwMDttYXJnaW4tYm90dG9tOjE2cHh9Ci5mb3JtLXJvd3ttYXJnaW4tYm90dG9tOjEycHh9Ci5mb3JtLXJvdyBsYWJlbHtkaXNwbGF5OmJsb2NrO2ZvbnQtc2l6ZToxMXB4O2ZvbnQtd2VpZ2h0OjYwMDtjb2xvcjp2YXIoLS1tdXRlZCk7bWFyZ2luLWJvdHRvbTo0cHg7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTt0ZXh0LXRyYW5zZm9ybTp1cHBlcmNhc2U7bGV0dGVyLXNwYWNpbmc6LjNweH0KLmZvcm0tcm93IGlucHV0LC5mb3JtLXJvdyBzZWxlY3QsLmZvcm0tcm93IHRleHRhcmVhe3dpZHRoOjEwMCU7cGFkZGluZzo5cHggMTFweDtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7Ym9yZGVyLXJhZGl1czp2YXIoLS1yYWRpdXMtc20pO2ZvbnQtZmFtaWx5OnZhcigtLWZvbnQpO2ZvbnQtc2l6ZToxM3B4O2JhY2tncm91bmQ6dmFyKC0tYmcpO2NvbG9yOnZhcigtLXRleHQpO291dGxpbmU6bm9uZTt0cmFuc2l0aW9uOmJvcmRlci1jb2xvciAuMTJzfQouZm9ybS1yb3cgaW5wdXQ6Zm9jdXMsLmZvcm0tcm93IHNlbGVjdDpmb2N1c3tib3JkZXItY29sb3I6dmFyKC0tYWNjZW50KTtib3gtc2hhZG93OjAgMCAwIDJweCByZ2JhKDAsMjAwLDE4MCwuMTUpfQouZm9ybS0yY29se2Rpc3BsYXk6Z3JpZDtncmlkLXRlbXBsYXRlLWNvbHVtbnM6MWZyIDFmcjtnYXA6MTJweH0KLm1vZGFsLWZvb3RlcntkaXNwbGF5OmZsZXg7Z2FwOjhweDttYXJnaW4tdG9wOjE2cHg7anVzdGlmeS1jb250ZW50OmZsZXgtZW5kfQouYnRue3BhZGRpbmc6OHB4IDE2cHg7Ym9yZGVyLXJhZGl1czp2YXIoLS1yYWRpdXMtc20pO2N1cnNvcjpwb2ludGVyO2ZvbnQtZmFtaWx5OnZhcigtLWZvbnQtaGVhZCk7Zm9udC1zaXplOjEzcHg7Zm9udC13ZWlnaHQ6NjAwO2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyKTtiYWNrZ3JvdW5kOnZhcigtLXN1cmZhY2UpO2NvbG9yOnZhcigtLXRleHQpfQouYnRuOmhvdmVye2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZTIpfQouYnRuLXByaW1hcnl7YmFja2dyb3VuZDp2YXIoLS1hY2NlbnQpO2NvbG9yOiMxMjEyMTQ7Ym9yZGVyLWNvbG9yOnZhcigtLWFjY2VudCl9Ci5idG4tZGFuZ2Vye2JhY2tncm91bmQ6dmFyKC0tZGFuZ2VyLWxpZ2h0KTtjb2xvcjp2YXIoLS1kYW5nZXIpO2JvcmRlci1jb2xvcjpyZ2JhKDI0OCwxMTMsMTEzLC4zKX0KLmRldGFpbC1iYXJ7aGVpZ2h0OjRweDtib3JkZXItcmFkaXVzOjJweDtiYWNrZ3JvdW5kOnZhcigtLWFjY2VudCk7bWFyZ2luLWJvdHRvbToxNnB4fQouZGV0YWlsLXJvd3tkaXNwbGF5OmZsZXg7Z2FwOjEwcHg7bWFyZ2luLWJvdHRvbTo4cHh9Ci5kbHtmb250LXNpemU6MTFweDtjb2xvcjp2YXIoLS1tdXRlZCk7bWluLXdpZHRoOjgwcHg7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTt0ZXh0LXRyYW5zZm9ybTp1cHBlcmNhc2V9Ci5kdntmb250LXNpemU6MTRweDtmb250LXdlaWdodDo1MDB9Ci5tb2JpbGUtd3JhcHtkaXNwbGF5Om5vbmU7ZmxleC1kaXJlY3Rpb246Y29sdW1uO2ZsZXg6MTtvdmVyZmxvdzpoaWRkZW59Ci5zY3JvbGwtY2FsZW5kYXJ7ZGlzcGxheTpmbGV4O2ZsZXg6MTtvdmVyZmxvdy14OmF1dG87b3ZlcmZsb3cteTpoaWRkZW47c2Nyb2xsLXNuYXAtdHlwZTp4IG1hbmRhdG9yeTstd2Via2l0LW92ZXJmbG93LXNjcm9sbGluZzp0b3VjaDtzY3JvbGxiYXItd2lkdGg6bm9uZX0KLnNjcm9sbC1jYWxlbmRhcjo6LXdlYmtpdC1zY3JvbGxiYXJ7ZGlzcGxheTpub25lfQouY2FsLWRheS1jb2x7ZmxleDowIDAgY2FsYygxMDAlLzMpO3Njcm9sbC1zbmFwLWFsaWduOnN0YXJ0O2Rpc3BsYXk6ZmxleDtmbGV4LWRpcmVjdGlvbjpjb2x1bW47Ym9yZGVyLXJpZ2h0OjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO21pbi13aWR0aDowfQouY2FsLWRheS1jb2w6bGFzdC1jaGlsZHtib3JkZXItcmlnaHQ6bm9uZX0KLmNhbC1kYXktaGVhZGVye3BhZGRpbmc6OHB4IDZweDt0ZXh0LWFsaWduOmNlbnRlcjtib3JkZXItYm90dG9tOjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZSk7cG9zaXRpb246c3RpY2t5O3RvcDowO3otaW5kZXg6MjtmbGV4LXNocmluazowfQouY2FsLWRheS1uYW1le2ZvbnQtc2l6ZToxMHB4O2ZvbnQtd2VpZ2h0OjcwMDtjb2xvcjp2YXIoLS1tdXRlZCk7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTt0ZXh0LXRyYW5zZm9ybTp1cHBlcmNhc2U7bGV0dGVyLXNwYWNpbmc6LjVweH0KLmNhbC1kYXktbnVte2ZvbnQtc2l6ZToyMnB4O2ZvbnQtd2VpZ2h0OjgwMDtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2NvbG9yOnZhcigtLXRleHQpO2xpbmUtaGVpZ2h0OjF9Ci5jYWwtZGF5LWNvbC50b2RheSAuY2FsLWRheS1udW17Y29sb3I6dmFyKC0tYWNjZW50KX0KLmNhbC1kYXktY29sLnRvZGF5IC5jYWwtZGF5LWhlYWRlcntib3JkZXItYm90dG9tOjJweCBzb2xpZCB2YXIoLS1hY2NlbnQpfQouY2FsLXNsb3Rze2ZsZXg6MTtvdmVyZmxvdy15OmF1dG87cGFkZGluZy1ib3R0b206ODBweH0KLmNhbC1zbG90e2Rpc3BsYXk6ZmxleDtnYXA6NHB4O21pbi1oZWlnaHQ6NTJweDtib3JkZXItYm90dG9tOjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO3BhZGRpbmc6NHB4IDRweCA0cHggMnB4O2N1cnNvcjpwb2ludGVyO3RyYW5zaXRpb246YmFja2dyb3VuZCAuMXM7cG9zaXRpb246cmVsYXRpdmV9Ci5jYWwtc2xvdDpob3ZlcntiYWNrZ3JvdW5kOnZhcigtLWFjY2VudC1saWdodCl9Ci5jYWwtc2xvdC10aW1le2ZvbnQtc2l6ZToxMHB4O2NvbG9yOnZhcigtLWhpbnQpO2ZvbnQtZmFtaWx5OnZhcigtLWZvbnQtaGVhZCk7d2lkdGg6MzRweDtmbGV4LXNocmluazowO3BhZGRpbmctdG9wOjJweDt0ZXh0LWFsaWduOnJpZ2h0O3BhZGRpbmctcmlnaHQ6NHB4fQouY2FsLXNsb3QtY29udGVudHtmbGV4OjE7bWluLXdpZHRoOjB9Ci5jYWwtYXBwdHtib3JkZXItcmFkaXVzOjVweDtwYWRkaW5nOjRweCA2cHg7Ym9yZGVyLWxlZnQ6M3B4IHNvbGlkIHZhcigtLWFjY2VudCk7YmFja2dyb3VuZDp2YXIoLS1hY2NlbnQtbGlnaHQpO2N1cnNvcjpwb2ludGVyfQouY2FsLWFwcHQtbmFtZXtmb250LXNpemU6MTFweDtmb250LXdlaWdodDo3MDA7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtjb2xvcjp2YXIoLS1hY2NlbnQpO3doaXRlLXNwYWNlOm5vd3JhcDtvdmVyZmxvdzpoaWRkZW47dGV4dC1vdmVyZmxvdzplbGxpcHNpc30KLmNhbC1hcHB0LXN2Y3tmb250LXNpemU6MTBweDtjb2xvcjp2YXIoLS1tdXRlZCk7d2hpdGUtc3BhY2U6bm93cmFwO292ZXJmbG93OmhpZGRlbjt0ZXh0LW92ZXJmbG93OmVsbGlwc2lzfQouY2FsLWFwcHQtZHVye2ZvbnQtc2l6ZTo5cHg7Y29sb3I6dmFyKC0taGludCl9Ci5jYWwtYnJlYWt7Ym9yZGVyLXJhZGl1czo1cHg7cGFkZGluZzo0cHggNnB4O2JhY2tncm91bmQ6IzJBMkEzMDtib3JkZXItbGVmdDozcHggc29saWQgIzc4MzUwRjtmb250LXNpemU6MTBweDtjb2xvcjojRjU5RTBCfQouY2FsLWZhYntwb3NpdGlvbjpmaXhlZDtib3R0b206MTZweDtsZWZ0OjUwJTt0cmFuc2Zvcm06dHJhbnNsYXRlWCgtNTAlKTtwYWRkaW5nOjEzcHggMzJweDtiYWNrZ3JvdW5kOnZhcigtLWFjY2VudCk7Y29sb3I6IzEyMTIxNDtib3JkZXI6bm9uZTtib3JkZXItcmFkaXVzOjI0cHg7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtmb250LXNpemU6MTRweDtmb250LXdlaWdodDo3MDA7Y3Vyc29yOnBvaW50ZXI7Ym94LXNoYWRvdzowIDRweCAxNnB4IHJnYmEoMCwyMDAsMTgwLC40KTt6LWluZGV4OjUwO3doaXRlLXNwYWNlOm5vd3JhcH0KLm0tZW1wdHl7dGV4dC1hbGlnbjpjZW50ZXI7cGFkZGluZzo0MHB4IDIwcHg7Y29sb3I6dmFyKC0taGludCk7Zm9udC1zdHlsZTppdGFsaWN9Ci50b2FzdHtwb3NpdGlvbjpmaXhlZDtib3R0b206MjBweDtsZWZ0OjUwJTt0cmFuc2Zvcm06dHJhbnNsYXRlWCgtNTAlKTtiYWNrZ3JvdW5kOiMxQTE5MTY7Y29sb3I6I2ZmZjtwYWRkaW5nOjEwcHggMjBweDtib3JkZXItcmFkaXVzOjIwcHg7Zm9udC1zaXplOjEzcHg7b3BhY2l0eTowO3RyYW5zaXRpb246b3BhY2l0eSAuMnM7cG9pbnRlci1ldmVudHM6bm9uZTt6LWluZGV4OjIwMH0KLnRvYXN0LnNob3d7b3BhY2l0eToxfQouaGlkZGVue2Rpc3BsYXk6bm9uZSFpbXBvcnRhbnR9Ci5kZXNrdG9wLW9ubHl7ZGlzcGxheTpub25lfQpAbWVkaWEobWluLXdpZHRoOjc2OXB4KXsuZGVza3RvcC1vbmx5e2Rpc3BsYXk6ZmxleCFpbXBvcnRhbnR9fQpAbWVkaWEobWF4LXdpZHRoOjc2OHB4KXsuY29udGVudHtkaXNwbGF5Om5vbmUhaW1wb3J0YW50fS5tb2JpbGUtd3JhcHtkaXNwbGF5OmZsZXghaW1wb3J0YW50fX0KCi50aW1lLWdyaWR7ZGlzcGxheTpmbGV4O2ZsZXgtd3JhcDp3cmFwO2dhcDo0cHg7bWFyZ2luLXRvcDo2cHh9Ci50aW1lLWJ0bntwYWRkaW5nOjRweCA4cHg7YmFja2dyb3VuZDp2YXIoLS1zdXJmYWNlMik7Ym9yZGVyOjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO2JvcmRlci1yYWRpdXM6NXB4O2ZvbnQtc2l6ZToxMXB4O2ZvbnQtZmFtaWx5OnZhcigtLWZvbnQtaGVhZCk7Y29sb3I6dmFyKC0tbXV0ZWQpO2N1cnNvcjpwb2ludGVyfQoudGltZS1idG46aG92ZXJ7YmFja2dyb3VuZDp2YXIoLS1hY2NlbnQtbGlnaHQpO2NvbG9yOnZhcigtLWFjY2VudCk7Ym9yZGVyLWNvbG9yOnZhcigtLWFjY2VudCl9Ci50aW1lLWJ0bi5hY3RpdmV7YmFja2dyb3VuZDp2YXIoLS1hY2NlbnQpO2NvbG9yOiMxMjEyMTQ7Ym9yZGVyLWNvbG9yOnZhcigtLWFjY2VudCl9Cjwvc3R5bGU+CjwvaGVhZD4KPGJvZHk+CjxkaXYgY2xhc3M9ImFwcCI+CjxkaXYgY2xhc3M9InRvcGJhciI+CiAgPGEgaHJlZj0iL2xvZ2luIiBzdHlsZT0iZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlciI+PGltZyBzcmM9ImRhdGE6aW1hZ2Uvc3ZnK3htbDtiYXNlNjQsUEQ5NGJXd2dkbVZ5YzJsdmJqMGlNUzR3SWlCbGJtTnZaR2x1WnowaVZWUkdMVGdpUHo0S1BITjJaeUJwWkQwaVRHRjVaWEpmTVNJZ1pHRjBZUzF1WVcxbFBTSk1ZWGxsY2lBeElpQjRiV3h1Y3owaWFIUjBjRG92TDNkM2R5NTNNeTV2Y21jdk1qQXdNQzl6ZG1jaUlIWnBaWGRDYjNnOUlqQWdNQ0F5TVRVeklERXdPREFpUGdvZ0lEeGtaV1p6UGdvZ0lDQWdQSE4wZVd4bFBnb2dJQ0FnSUNBdVkyeHpMVEVnZXdvZ0lDQWdJQ0FnSUdacGJHdzZJQ013WkdVd1pEWTdDaUFnSUNBZ0lIMEtDaUFnSUNBZ0lDNWpiSE10TWlCN0NpQWdJQ0FnSUNBZ1ptbHNiRG9nSTJVelpUUmxPRHNLSUNBZ0lDQWdmUW9nSUNBZ1BDOXpkSGxzWlQ0S0lDQThMMlJsWm5NK0NpQWdQSEJoZEdnZ1kyeGhjM005SW1Oc2N5MHhJaUJrUFNKTk16ZzBMakl6TERJeE5DNDVPV010TVRBdU9ERXROUzQxTlMweE1DNDRNU3cwTWk0ek1TMHhNQzQ0TVN3ME1pNHpNUzB4TUM0NE1Td3lOUzQ1TlMweU1TNDJNaXd5T0M0eE1TMHlNUzQyTWl3eU9DNHhNUzB4TWk0NU55MDRMalkxTFRFd0xqZ3hMVFEzTGpVM0xURXdMamd4TFRRM0xqVTNMVEUxTGpFMExUVTJMakl5TERRekxqSTBMVFU0TGpNNExEUXpMakkwTFRVNExqTTRMREFzTUMweU1TNDJNaTA0TGpZMUxUTTRMamt5TERZdU5Ea3RNak11TURFc01qQXVNVFF0TVRjdU15dzJNaTQzTFRndU5qVXNPRGd1TmpVc09DNDJOU3d5TlM0NU5Td3lNUzQyTWl3eE5TNHhOQ3d5TVM0Mk1pd3hOUzR4TkMweE1pNDVOeXd4Tnk0ekxUSTFMamsxTERFeUxqazNMVEkxTGprMUxERXlMamszTFRJNExqRXhMVFl1TkRrdE16Z3VPVEl0TWk0eE5pMHpPQzQ1TWkweUxqRTJMVE13TGpJM0xERXlMamszTFRJeExqWXlMRFkzTGpBekxURTFMakUwTERnNExqWTFMRFl1TkRrc01qRXVOaklzTXpJdU5ETXNPVEl1T1Rjc016SXVORE1zT1RJdU9UY3RPQzQyTlN3MkxqUTVMVEU1TGpRMkxESTFMamsxTFRFMUxqRTBMRFF4TGpBNExEUXVNeklzTVRVdU1UUXNNalV1T1RVc016SXVORE1zTXpZdU56WXNNakV1TmpJc01UQXVPREV0TVRBdU9ERXRPQzQyTlMwME55NDFOeTA0TGpZMUxUUTNMalUzYkMweU5DNDBOaTAyTWk0Mk5tTXRNUzR4TmkwekxqUXhMVEl1TVRZdE5pNDROaTB5TGprNExURXdMak0zTFRNdU1qRXRNVE11TmpjdE1qSXVNamt0TnpFdU9ETXRNVEV1TkRndE9UY3VOemdzTVRFdU1Ea3RNall1TmpNc05EY3VOVGN0TVRjdU15dzBOeTQxTnkweE55NHpMRFF4TGpBNExEZ3VOalVzTkRrdU56TXRORGt1TnpNc05Ea3VOek10TkRrdU56TXNNVEF1T0RFdE1UQXVPREVzTVRJdU9UY3RNemd1T1RJc01pNHhOaTAwTkM0ME4xcE5Nekl4TGpVekxEVXlNUzR3T0dNd0xERXdMamd4TERBc01UVXVNVFF0Tmk0ME9Td3hNaTQ1TjNNdE1UUXVORFF0TVRRdU9Ua3RNVEl1T1RjdE1qTXVOemhqTWk0eE5pMHhNaTQ1Tnl3eE1DNDRNUzB5TVM0Mk1pd3hNQzQ0TVMweU1TNDJNaXd3TERBc09DNDJOU3d5TVM0Mk1pdzRMalkxTERNeUxqUXpXaUl2UGdvZ0lEeHdZWFJvSUdOc1lYTnpQU0pqYkhNdE1TSWdaRDBpVFRNNE15NDROU3d5TmprdU1qbHpMVFF1TXpJc016QXVNamN0TWpNdU56Z3NOalF1T0RaakxURTVMalEyTERNMExqVTVMVFEyTGpRNUxEZ3pMakkwTFRRMkxqUTVMREUxTUM0eU4ydzBMak15TFRRdU16SXNOQzR6TWkwMExqTXljekl1TVRZdE1USXVPVGNzT0M0Mk5TMDBNeTR5TkdNMkxqUTVMVE13TGpJM0xESTNMakF6TFRZekxqYzRMRFF4TGpBNExUa3lMamszTERFeUxqSXpMVEkxTGpRc01UUXVNRFV0TlRJdU9UY3NNVEV1T0RrdE56QXVNamRhSWk4K0NpQWdQSEJoZEdnZ1kyeGhjM005SW1Oc2N5MHhJaUJrUFNKTk16TXhMalkxTERnM09DNDJOSE0xTmk0NU1TMHhNRFl1TnpVc056SXVNRFF0TVRNNUxqRTRZekUxTGpFMExUTXlMalF6TERRd0xURXhNUzR6TlN3ek1pNDBNeTB4TmpBdE5pNDROUzAwTkM0d05DMHlNQzQxTkMwM05pNDNOaTAxTWk0NU55MDRPUzQzTXkwek1TNHhOaTB4TWk0ME55MDJNUzQyTWkwNUxqY3pMVGN3TGpJM0xURXVNRGhzTFRJdU1UWXROaTQwT1hNeU5TNHdNeTB5TVM0Mk1pdzRNQzQyTWkwMUxqUXhZelUxTGpVNUxERTJMakl5TERjeExqZ3hMRGcyTGpRNUxEY3hMamd4TERFeE5DNDFPU3d3TERNeExqTXRNeTQ0T1N3eE1EQXVNVGd0TkRNdU1qUXNNVFl5TGpFMkxUUXdMalUxTERZekxqZzJMVGc0TGpJMkxERXlOUzR4TXkwNE9DNHlOaXd4TWpVdU1UTmFJaTgrQ2lBZ1BIQmhkR2dnWTJ4aGMzTTlJbU5zY3kweElpQmtQU0pOTXpJeUxqSXpMRFEzTnk0NU0zTXROUzQwTVMweU9TNHhPU3d4T0M0ek9DMDBNR015TXk0M09DMHhNQzQ0TVN3NE55NDFOeTB4TVM0NE9TdzVOeTR6TFRZNUxqRTVMREV4TGpRMkxUWTNMalE1TFRRNUxqRXhMVFl6TGpVeExUUTVMakV4TFRZekxqVXhMREFzTUN3MU5DNDFPUzB5T0M0MU55dzNNUzQ0TVN3eU9TNDVPU3d4TUM0NE1Td3pOaTQzTmkweE1pNDVOeXc0Tmk0ME9TMDNNUzR6TlN3NU9TNDBOaTAxTXk0d055d3hNUzQzT1MwMU5DNHdOU3d4TlM0eE5DMDJOeTR3TXl3ME15NHlORm9pTHo0S0lDQThjR0YwYUNCamJHRnpjejBpWTJ4ekxURWlJR1E5SWswNE1EWXNOek00WXpVNExEUXdMREV4Tnk0eU9TdzFPUzR4T0N3eE5EUXNOamtzTVRZMkxEWXhMRE15TWl3M05Dd3pNaklzTnpRc05UUXdMRGN5TERZNE1DNHdNaTB4TURZdU9Ea3NOamd3TGpBeUxURXdOaTQ0T1MweU16QXVPVGdzTVRVMkxqRXhMVGM1Tmk0NU55dzFNeTR3TVMwNU1ESXVNRElzTXpBdU9Ea3RNemd0T0MweE1UVXRNalV0TWpNeUxUZ3pJaTgrQ2lBZ1BIQmhkR2dnWTJ4aGMzTTlJbU5zY3kweElpQmtQU0pOT0RJekxqRXNOelUxTGpBMFl5MHlOaTR6TXl3eU55NDNOUzAyTVM0eU9TdzBPUzR3TXkweE1EUXVPRGtzTmpNdU9ETXRNemN1TkRNc01USXVORGt0TnpZdU9USXNNVGd1TnpNdE1URTRMalEyTERFNExqY3pMVEkzTGpFMUxEQXROVE11TWpjdE5pNHdNaTAzT0M0ek5pMHhPQzR3TkMwek1pNHdPQzB4TlM0eU5pMDBPQzR4TXkwek5pNHpNUzAwT0M0eE15MDJNeTR4TkN3d0xUTXdMams0TERFekxqRTJMVFUyTGpRekxETTVMalE1TFRjMkxqTXlMREV4TGpreUxUZ3VOemdzTWpRdU1qY3RNVFV1TXpjc016Y3VNREl0TVRrdU56Y3NNVEl1TnpVdE5DNHpPU3d5Tmk0eE1pMDNMakExTERRd0xqRXhMVGN1T1Rnc05pNDVPUzB4T0M0MUxERTFMamN6TFRRd0xqQXhMREkyTGpJeUxUWTBMalV6TERFd0xqUTVMVEkwTGpVeExESXhMall5TFRRMkxqQXlMRE14TGpreExUWTNMak1zTXk0eU9TMDJMalEzTERndE1UWXNNVFF0TWpZc01UQXVNamt0TVRjdU1UWXNNakF0TXpFc01qUXRNelVzTVRjdU5URXRNVGN1TlRFc016WXRNVFVzTXpZdE1UVXNNQ3d3TFRJdU9Ua3NNaTR5TkMweE15NDBPQ3d4TlM0M05pMHpMalUwTERRdU5UVXROaTQ0T0N3NUxqSTNMVGt1T1Rrc01UUXVNVE10TXpVdU9ETXNOVFV1T1RVdE5UWXVNRGNzTVRBMkxqTTVMVGczTGpZNExERTNOeTQ1TkN3NU1pNDFOU3d4TGpnMUxERTJNUzQwTkN3eU5TNHlNaXd5TURZdU55dzNNQzR3T0N3eE15NHhOaTB4T1M0NE9Dd3hPUzQzTkMwek9DNHhOaXd4T1M0M05DMDFOQzQ0TVN3d0xUSTVMakUwTFRFM0xqUTVMVFV5TGpBMExUVXlMalExTFRZNExqWTVMVEUxTGpFMkxUWXVPVGN0TlRBdU1ERXRNVGN1TkRndE56WXVPRFF0TWpJdU5DMHlNUzR5TWkwekxqZzVMVEkzTFRVdE1qY3ROU3d3TERBc09DNDVOQzB6TGpFNUxESXhMVGNzTVRrdE5pd3lOaTA0TERNM0xURXlMRFExTGpZMExURTJMallzTnpFdU5qRXRNamt1TURJc09UTXVPVGN0TlRJdU9ESXNPUzQwTmkwNUxqY3hMREUwTGpFNUxURTRMalVzTVRRdU1Ua3RNall1TXpjc01DMHhOaTQyTlMweE9TNHhNeTB5T1M0eE5DMDFOeTR6T0Mwek55NDBOeTB5TlM0NU1TMDFMalUxTFRVeUxqWTJMVGd1TXpNdE9EQXVNakV0T0M0ek15MDNNeTQyTkN3d0xURTBNQzQ1T1N3eE1DNDVNaTB5TURVdU5UY3NOREF1T1RndE1pNDBOeTQ1TXkweE5pdzVMVEUyTERrc01Dd3dMRGd1TXpNdE1URXVNek1zTVRVdE1UZ3NPUzA1TERFNUxURTNMRE16TFRJMExEUXlMamM0TFRFNUxqUXpMRGMzTGpjeUxUSTRMakVzTVRRekxqazFMVEk0TGpFc016a3VORGtzTUN3M05pNHdPU3cwTGpFMkxERXdPUzQ0TXl3eE1pNDBPU3cxTWk0Mk5Td3hNaTQwT1N3M09DNDVPQ3d6TWk0ek9DdzNPQzQ1T0N3MU9TNDJOeXd3TERJeUxqSXRNVFl1TURRc05ESXVNek10TkRndU1UTXNOakF1TXpjdE1qTXVORFVzTVRNdU5ESXRORGd1TXpRc01qSXVOamN0TnpRdU5qWXNNamN1TnpVc01qa3VNaXczTGpReExEVTBMak1zTVRndU1qZ3NOelV1TWpjc016SXVOakVzTWpndU56a3NNVGt1TkRNc05ETXVNVGtzTkRJdU56a3NORE11TVRrc056QXVNRGdzTUN3eU1pNHlMVEV3TGpBNExEUTJMakF6TFRNd0xqSXpMRGN4TGpRM1RUVTJNQzQ0Tnl3NE1EZ3VORGRqTFM0NE55NHdOUzB6TGpnM0xUa3VORFl0TXk0NE55MHlNUzQ1TlN3d0xUSXdMamd5TERRdU5Ea3ROVFl1Tmprc01qVXVORFl0TVRFMExqQTFMVFUwTGpjeExERXdMakU0TFRneUxqQTJMRE00TGpZekxUZ3lMakEyTERnMUxqTTBMREFzTWpBdU9ESXNNVEl1TlRRc016Y3VORGNzTXpjdU5qUXNORGt1T1RZc01Ua3VOelFzT1M0M01TdzBNQzR6TVN3eE5DNDFOeXcyTVM0M0xERTBMalUzTERreExqTXlMREFzTVRZd0xqSXhMVEk0TGpJeExESXdOaTQzTFRnMExqWTFMVEl6TGpBMExUSXhMamMwTFRVeUxqQTBMVE00TGpnMkxUZzNMVFV4TGpNMUxUTXlMalV0TVRFdU5UWXROalV1TWkweE55NHpOUzA1T0M0eExURTNMak0xYUMwNExqazFZeTB6TGpBNExEQXROaTR3Tnk0eU5DMDRMamsxTGpZNUxUSTBMalk0TERVNExqYzFMVFF5TGpRMExERXhPQzQwT0MwME1pNDBOQ3d4TXpndU9ETWlMejRLSUNBOFp6NEtJQ0FnSUR4d1lYUm9JR05zWVhOelBTSmpiSE10TWlJZ1pEMGlUVGc1Tmk0eU9DdzJNalV1TURGMkxUWTBMamcxYURNMExqWTFZemd1T1RZc01Dd3hOUzQxTml3eExqVTVMREU1TGpnekxEUXVOemNzTkM0eU5pd3pMakU0TERZdU16a3NOeTR5TkN3MkxqTTVMREV5TGpFNExEQXNNeTR5TnkwdU9URXNOaTR4T1MweUxqY3pMRGd1TnpVdE1TNDRNaXd5TGpVMkxUUXVORFlzTkM0MU9TMDNMamt5TERZdU1EY3RNeTQwTml3eExqUTRMVGN1TnpJc01pNHlNaTB4TWk0M09Td3lMakl5YkRFdU9EVXROV00xTGpBMkxEQXNPUzQwTXk0M01Td3hNeTR4TVN3eUxqRXpMRE11Tmpjc01TNDBNaXcyTGpVeUxETXVORGNzT0M0MU1pdzJMakUyTERJdU1ERXNNaTQyT1N3ekxqQXhMRFV1T1RJc015NHdNU3c1TGpZNExEQXNOUzQyTWkweUxqTXpMREV3TFRZdU9Ua3NNVE11TVRZdE5DNDJOaXd6TGpFMUxURXhMalEzTERRdU56SXRNakF1TkRNc05DNDNNbWd0TXpZdU5WcE5PVEUzTGpjNExEWXdPUzQzTW1neE15NHhObU15TGpReExEQXNOQzR5TWkwdU5ETXNOUzQwTWkweExqTXNNUzR5TFM0NE5pd3hMamd4TFRJdU1UTXNNUzQ0TVMwekxqaHpMUzQyTFRJdU9UTXRNUzQ0TVMwekxqaGpMVEV1TWkwdU9EWXRNeTR3TVMweExqTXROUzQwTWkweExqTm9MVEUwTGpZMGRpMHhOQzQwTldneE1TNDJOMk15TGpRM0xEQXNOQzR5T0MwdU5ESXNOUzQwTWkweExqSTFMREV1TVRRdExqZ3pMREV1TnpFdE1pNHdNaXd4TGpjeExUTXVOVGR6TFM0MU55MHlMamd4TFRFdU56RXRNeTQyTVdNdE1TNHhOQzB1T0MweUxqazFMVEV1TWkwMUxqUXlMVEV1TW1ndE1UQXVNVGwyTXpRdU1qaGFJaTgrQ2lBZ0lDQThjR0YwYUNCamJHRnpjejBpWTJ4ekxUSWlJR1E5SWsweE1ESTVMamM0TERZeU5pNDBPV010TlM0ek1Td3dMVEV3TGpJeExTNDRNeTB4TkM0Mk9DMHlMalV0TkM0ME9DMHhMalkzTFRndU16VXROQzR3TXkweE1TNDJNeTAzTGpBNUxUTXVNamN0TXk0d05pMDFMamd5TFRZdU5qVXROeTQyTkMweE1DNDNPUzB4TGpneUxUUXVNVFF0TWk0M015MDRMalkxTFRJdU56TXRNVE11TlROekxqa3hMVGt1TkRZc01pNDNNeTB4TXk0MU4yTXhMamd5TFRRdU1URXNOQzR6TnkwM0xqWTVMRGN1TmpRdE1UQXVOelVzTXk0eU55MHpMakEyTERjdU1UVXROUzQwTWl3eE1TNDJNeTAzTGpBNUxEUXVORGd0TVM0Mk55dzVMak0wTFRJdU5Td3hOQzQxT1MweUxqVnpNVEF1TVRrdU9ETXNNVFF1TmpRc01pNDFZelF1TkRVc01TNDJOeXc0TGpNeExEUXVNRE1zTVRFdU5UZ3NOeTR3T1N3ekxqSTNMRE11TURZc05TNDRNaXcyTGpZMExEY3VOalFzTVRBdU56VXNNUzQ0TWl3MExqRXhMREl1TnpNc09DNDJNeXd5TGpjekxERXpMalUzY3kwdU9URXNPUzR6T1MweUxqY3pMREV6TGpVell5MHhMamd5TERRdU1UUXROQzR6Tnl3M0xqYzBMVGN1TmpRc01UQXVOemt0TXk0eU55d3pMakEyTFRjdU1UTXNOUzQwTWkweE1TNDFPQ3czTGpBNUxUUXVORFVzTVM0Mk55MDVMak1zTWk0MUxURTBMalUwTERJdU5WcE5NVEF5T1M0Mk9TdzJNRGd1T0dNeUxqQTBMREFzTXk0NU5DMHVNemNzTlM0M0xURXVNVEVzTVM0M05pMHVOelFzTXk0ekxURXVPREVzTkM0Mk15MHpMaklzTVM0ek15MHhMak01TERJdU16WXRNeTR3T1N3ekxqRXROUzR4TGpjMExUSXVNREVzTVM0eE1TMDBMakk0TERFdU1URXROaTQ0TVhNdExqTTNMVFF1T0MweExqRXhMVFl1T0RGakxTNDNOQzB5TGpBeExURXVOemd0TXk0M01TMHpMakV0TlM0eExURXVNek10TVM0ek9TMHlMamczTFRJdU5EVXROQzQyTXkwekxqSXRNUzQzTmkwdU56UXRNeTQyTmkweExqRXhMVFV1TnkweExqRXhjeTB6TGprMExqTTNMVFV1Tnl3eExqRXhMVE11TXl3eExqZ3hMVFF1TmpNc015NHlZeTB4TGpNekxERXVNemt0TWk0ek5pd3pMakE1TFRNdU1TdzFMakV0TGpjMExESXVNREV0TVM0eE1TdzBMakk0TFRFdU1URXNOaTQ0TVhNdU16Y3NOQzQ0TERFdU1URXNOaTQ0TVdNdU56UXNNaTR3TVN3eExqYzNMRE11TnpFc015NHhMRFV1TVN3eExqTXpMREV1TXprc01pNDROeXd5TGpRMkxEUXVOak1zTXk0eWN6TXVOallzTVM0eE1TdzFMamNzTVM0eE1Wb2lMejRLSUNBZ0lEeHdZWFJvSUdOc1lYTnpQU0pqYkhNdE1pSWdaRDBpVFRFeE1ESXVNRFFzTmpJMUxqQXhkaTAyTkM0NE5XZ3pNUzQ1Tm1NM0xqSXpMREFzTVRNdU5Ua3NNUzR6TVN3eE9TNHdPQ3d6TGprMExEVXVOU3d5TGpZekxEa3VOemtzTmk0ek5Td3hNaTQ0T0N3eE1TNHhOaXd6TGpBNUxEUXVPRElzTkM0Mk15d3hNQzQxTml3MExqWXpMREUzTGpJemN5MHhMalUwTERFeUxqVXlMVFF1TmpNc01UY3VNemRqTFRNdU1Ea3NOQzQ0TlMwM0xqTTRMRGd1TlRrdE1USXVPRGdzTVRFdU1qRXROUzQxTERJdU5qTXRNVEV1T0RZc015NDVOQzB4T1M0d09Dd3pMamswYUMwek1TNDVObHBOTVRFeU15NDVNU3cyTURjdU9UWm9PUzR4TjJNekxqQTVMREFzTlM0M09TMHVOVGtzT0M0eE1TMHhMamMyTERJdU16SXRNUzR4Tnl3MExqRXlMVEl1T1RJc05TNDBNaTAxTGpJekxERXVNeTB5TGpNeUxERXVPVFV0TlM0eE5Dd3hMamsxTFRndU5EaHpMUzQyTlMwMkxqQTFMVEV1T1RVdE9DNHpOR010TVM0ekxUSXVNamd0TXk0eExUUXVNREV0TlM0ME1pMDFMakU1TFRJdU16SXRNUzR4TnkwMUxqQXlMVEV1TnpZdE9DNHhNUzB4TGpjMmFDMDVMakUzZGpNd0xqYzJXaUl2UGdvZ0lDQWdQSEJoZEdnZ1kyeGhjM005SW1Oc2N5MHlJaUJrUFNKTk1USXlNQzR5TlN3Mk1qVXVNREYyTFRJNExqUTBiRFVzTVRNdU1EWXRNamt1TkRZdE5Ea3VORGRvTWpNdU1EZHNNVGt1T1RJc016TXVPREZvTFRFekxqUXpiREl3TGpFdE16TXVPREZvTWpFdU1USnNMVEk1TGpJM0xEUTVMalEzTERRdU9ESXRNVE11TURaMk1qZ3VORFJvTFRJeExqZzJXaUl2UGdvZ0lDQWdQSEJoZEdnZ1kyeGhjM005SW1Oc2N5MHlJaUJrUFNKTk1UTTFNaTQzTXl3Mk1qVXVNREYyTFRZMExqZzFhRE0wTGpZMVl6Z3VPVFlzTUN3eE5TNDFOaXd4TGpVNUxERTVMamd6TERRdU56Y3NOQzR5Tml3ekxqRTRMRFl1TXprc055NHlOQ3cyTGpNNUxERXlMakU0TERBc015NHlOeTB1T1RFc05pNHhPUzB5TGpjekxEZ3VOelV0TVM0NE1pd3lMalUyTFRRdU5EWXNOQzQxT1MwM0xqa3lMRFl1TURjdE15NDBOaXd4TGpRNExUY3VOeklzTWk0eU1pMHhNaTQzT1N3eUxqSXliREV1T0RVdE5XTTFMakEyTERBc09TNDBNeTQzTVN3eE15NHhNU3d5TGpFekxETXVOamNzTVM0ME1pdzJMalV5TERNdU5EY3NPQzQxTWl3MkxqRTJMREl1TURFc01pNDJPU3d6TGpBeExEVXVPVElzTXk0d01TdzVMalk0TERBc05TNDJNaTB5TGpNekxERXdMVFl1T1Rrc01UTXVNVFl0TkM0Mk5pd3pMakUxTFRFeExqUTNMRFF1TnpJdE1qQXVORE1zTkM0M01tZ3RNell1TlZwTk1UTTNOQzR5TWl3Mk1Ea3VOekpvTVRNdU1UWmpNaTQwTVN3d0xEUXVNakl0TGpRekxEVXVOREl0TVM0ekxERXVNaTB1T0RZc01TNDRNUzB5TGpFekxERXVPREV0TXk0NGN5MHVOaTB5TGprekxURXVPREV0TXk0NFl5MHhMakl0TGpnMkxUTXVNREV0TVM0ekxUVXVOREl0TVM0emFDMHhOQzQyTkhZdE1UUXVORFZvTVRFdU5qZGpNaTQwTnl3d0xEUXVNamd0TGpReUxEVXVOREl0TVM0eU5Td3hMakUwTFM0NE15d3hMamN4TFRJdU1ESXNNUzQzTVMwekxqVTNjeTB1TlRjdE1pNDRNUzB4TGpjeExUTXVOakZqTFRFdU1UUXRMamd0TWk0NU5TMHhMakl0TlM0ME1pMHhMakpvTFRFd0xqRTVkak0wTGpJNFdpSXZQZ29nSUNBZ1BIQmhkR2dnWTJ4aGMzTTlJbU5zY3kweUlpQmtQU0pOTVRRME5TNHdPU3cyTWpVdU1ERnNNamd1TXpVdE5qUXVPRFZvTWpFdU5EbHNNamd1TXpVc05qUXVPRFZvTFRJeUxqWXhiQzB5TUM0NU5DMDFOQzQwTjJnNExqVXliQzB5TUM0NU5DdzFOQzQwTjJndE1qSXVNak5hVFRFME5qRXVPVFlzTmpFekxqY3hiRFV1TlRZdE1UVXVOelZvTWprdU9ETnNOUzQxTml3eE5TNDNOV2d0TkRBdU9UVmFJaTgrQ2lBZ0lDQThjR0YwYUNCamJHRnpjejBpWTJ4ekxUSWlJR1E5SWsweE5UVTBMallzTmpJMUxqQXhkaTAyTkM0NE5XZ3lNUzQ0Tm5ZME55NDVhREk1TGpJNGRqRTJMamsxYUMwMU1TNHhORm9pTHo0S0lDQWdJRHh3WVhSb0lHTnNZWE56UFNKamJITXRNaUlnWkQwaVRURTJNek11TkRRc05qSTFMakF4YkRJNExqTTFMVFkwTGpnMWFESXhMalE1YkRJNExqTTFMRFkwTGpnMWFDMHlNaTQyTVd3dE1qQXVPVFF0TlRRdU5EZG9PQzQxTW13dE1qQXVPVFFzTlRRdU5EZG9MVEl5TGpJeldrMHhOalV3TGpNc05qRXpMamN4YkRVdU5UWXRNVFV1TnpWb01qa3VPRE5zTlM0MU5pd3hOUzQzTldndE5EQXVPVFZhSWk4K0NpQWdJQ0E4Y0dGMGFDQmpiR0Z6Y3owaVkyeHpMVElpSUdROUlrMHhOelF5TGprMExEWXlOUzR3TVhZdE5qUXVPRFZvTVRjdU9UZHNNekl1T1Rnc016a3VORGRvTFRndU16UjJMVE01TGpRM2FESXhMak14ZGpZMExqZzFhQzB4Tnk0NU4yd3RNekl1T1RndE16a3VORGRvT0M0ek5IWXpPUzQwTjJndE1qRXVNekZhSWk4K0NpQWdJQ0E4Y0dGMGFDQmpiR0Z6Y3owaVkyeHpMVElpSUdROUlrMHhPRGM0TGpjMUxEWXlOaTQwT1dNdE5TNHhPU3d3TFRrdU9Ua3RMamd5TFRFMExqUXhMVEl1TkRZdE5DNDBNaTB4TGpZMExUZ3VNalV0TXk0NU55MHhNUzQwT1MwM0xUTXVNalF0TXk0d01pMDFMamMyTFRZdU5qRXROeTQxTlMweE1DNDNOUzB4TGpjNUxUUXVNVFF0TWk0Mk9TMDRMamN4TFRJdU5qa3RNVE11TnpGekxqZzVMVGt1TlRjc01pNDJPUzB4TXk0M01XTXhMamM1TFRRdU1UUXNOQzR6TVMwM0xqY3lMRGN1TlRVdE1UQXVOelVzTXk0eU5DMHpMakF6TERjdU1EY3ROUzR6Tml3eE1TNDBPUzAyTGprNUxEUXVOREl0TVM0Mk5DdzVMakl5TFRJdU5EWXNNVFF1TkRFdE1pNDBOaXcyTGpNMkxEQXNNVElzTVM0eE1Td3hOaTQ1TVN3ekxqTXpjemd1T1Rjc05TNDBOQ3d4TWk0eE9DdzVMall6YkMweE15NDRMREV5TGpNeVl5MHhMamt5TFRJdU5ERXROQzR3TXkwMExqSTRMVFl1TXpVdE5TNDJMVEl1TXpJdE1TNHpNeTAwTGprekxURXVPVGt0Tnk0NE15MHhMams1TFRJdU1qa3NNQzAwTGpNMUxqTTNMVFl1TWpFc01TNHhNUzB4TGpnMUxqYzBMVE11TkRRc01TNDRNaTAwTGpjM0xETXVNalF0TVM0ek15d3hMalF5TFRJdU16WXNNeTR4TkMwekxqRXNOUzR4TkMwdU56UXNNaTR3TVMweExqRXhMRFF1TWpVdE1TNHhNU3cyTGpjeWN5NHpOeXcwTGpjeExERXVNVEVzTmk0M01tTXVOelFzTWk0d01Td3hMamMzTERNdU56SXNNeTR4TERVdU1UUXNNUzR6TXl3eExqUXlMREl1T1RJc01pNDFMRFF1Tnpjc015NHlOQ3d4TGpnMUxqYzBMRE11T1RJc01TNHhNU3cyTGpJeExERXVNVEVzTWk0NUxEQXNOUzQxTVMwdU5qWXNOeTQ0TXkweExqazVMREl1TXpJdE1TNHpNeXcwTGpRekxUTXVNaXcyTGpNMUxUVXVOakZzTVRNdU9Dd3hNaTR6TW1NdE15NHlNU3cwTGpFMExUY3VNamNzTnk0ek15MHhNaTR4T0N3NUxqVTVjeTB4TUM0MU5Td3pMak00TFRFMkxqa3hMRE11TXpoYUlpOCtDaUFnSUNBOGNHRjBhQ0JqYkdGemN6MGlZMnh6TFRJaUlHUTlJazB4T1RZekxqUXpMRFl3T0M0MU1tZ3pNaTQwTTNZeE5pNDBPV2d0TlRNdU9USjJMVFkwTGpnMWFEVXlMamN4ZGpFMkxqUTVhQzB6TVM0eU1uWXpNUzQ0TjFwTk1UazJNUzQ1TkN3MU9EUXVNalZvTWpndU9URjJNVFV1TnpWb0xUSTRMamt4ZGkweE5TNDNOVm9pTHo0S0lDQThMMmMrQ2p3dmMzWm5QZz09IiBhbHQ9IkJvZHkgQmFsYW5jZSI+PC9hPgogIDxkaXYgY2xhc3M9InNwYWNlciI+PC9kaXY+CiAgPHNwYW4gaWQ9Im1hc3Rlck5hbWVCYWRnZSIgc3R5bGU9ImZvbnQtc2l6ZToxM3B4O2ZvbnQtd2VpZ2h0OjYwMDtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2NvbG9yOnZhcigtLWFjY2VudCkiPjwvc3Bhbj4KPC9kaXY+CjxkaXYgY2xhc3M9ImRhdGUtbmF2Ij4KICA8YnV0dG9uIG9uY2xpY2s9ImNoYW5nZVBlcmlvZCgtMSkiPiYjODI0OTs8L2J1dHRvbj4KICA8ZGl2IHN0eWxlPSJwb3NpdGlvbjpyZWxhdGl2ZTtkaXNwbGF5OmlubGluZS1ibG9jayI+CiAgICA8YnV0dG9uIGNsYXNzPSJ0b2RheS1idG4iIGlkPSJ0b2RheUJ0biIgb25jbGljaz0ib3BlbkRhdGVQaWNrZXIoKSI+JiMxMjgxOTc7INCh0YzQvtCz0L7QtNC90ZY8L2J1dHRvbj4KICAgIDxpbnB1dCB0eXBlPSJkYXRlIiBpZD0iZGF0ZVBpY2tlciIgc3R5bGU9InBvc2l0aW9uOmFic29sdXRlO29wYWNpdHk6MDt0b3A6MDtsZWZ0OjA7d2lkdGg6MTAwJTtoZWlnaHQ6MTAwJTtjdXJzb3I6cG9pbnRlciIgb25jaGFuZ2U9ImdvVG9EYXRlKHRoaXMudmFsdWUpIj4KICA8L2Rpdj4KICA8YnV0dG9uIG9uY2xpY2s9ImNoYW5nZVBlcmlvZCgxKSI+JiM4MjUwOzwvYnV0dG9uPgogIDxzcGFuIGNsYXNzPSJ3ZWVrLWxhYmVsIiBpZD0id2Vla0xhYmVsIiBzdHlsZT0iZmxleDoxIj48L3NwYW4+CiAgPGRpdiBjbGFzcz0iZGVza3RvcC1vbmx5IiBzdHlsZT0iZGlzcGxheTpmbGV4O2dhcDo0cHg7bWFyZ2luLWxlZnQ6OHB4Ij4KICAgIDxidXR0b24gaWQ9InYxIiBvbmNsaWNrPSJzZXRWaWV3KDEpIiBzdHlsZT0icGFkZGluZzo1cHggMTBweDtib3JkZXItcmFkaXVzOjZweDtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWJvcmRlcik7YmFja2dyb3VuZDp2YXIoLS1zdXJmYWNlKTtjb2xvcjp2YXIoLS1tdXRlZCk7Zm9udC1zaXplOjEycHg7Zm9udC1mYW1pbHk6dmFyKC0tZm9udC1oZWFkKTtmb250LXdlaWdodDo2MDA7Y3Vyc29yOnBvaW50ZXIiPjHQtDwvYnV0dG9uPgogICAgPGJ1dHRvbiBpZD0idjMiIG9uY2xpY2s9InNldFZpZXcoMykiIHN0eWxlPSJwYWRkaW5nOjVweCAxMHB4O2JvcmRlci1yYWRpdXM6NnB4O2JvcmRlcjoxcHggc29saWQgdmFyKC0tYm9yZGVyKTtiYWNrZ3JvdW5kOnZhcigtLXN1cmZhY2UpO2NvbG9yOnZhcigtLW11dGVkKTtmb250LXNpemU6MTJweDtmb250LWZhbWlseTp2YXIoLS1mb250LWhlYWQpO2ZvbnQtd2VpZ2h0OjYwMDtjdXJzb3I6cG9pbnRlciI+M9C0PC9idXR0b24+CiAgICA8YnV0dG9uIGlkPSJ2NyIgb25jbGljaz0ic2V0Vmlldyg3KSIgc3R5bGU9InBhZGRpbmc6NXB4IDEwcHg7Ym9yZGVyLXJhZGl1czo2cHg7Ym9yZGVyOjFweCBzb2xpZCB2YXIoLS1ib3JkZXIpO2JhY2tncm91bmQ6dmFyKC0tYWNjZW50KTtjb2xvcjojMTIxMjE0O2JvcmRlci1jb2xvcjp2YXIoLS1hY2NlbnQpO2ZvbnQtc2l6ZToxMnB4O2ZvbnQtZmFtaWx5OnZhcigtLWZvbnQtaGVhZCk7Zm9udC13ZWlnaHQ6NjAwO2N1cnNvcjpwb2ludGVyIj430LQ8L2J1dHRvbj4KICA8L2Rpdj4KPC9kaXY+CjxkaXYgY2xhc3M9ImNvbnRlbnQiPgogIDxkaXYgY2xhc3M9IndlZWstd3JhcCI+PGRpdiBjbGFzcz0id2Vlay1ncmlkIiBpZD0id2Vla0dyaWQiPjwvZGl2PjwvZGl2Pgo8L2Rpdj4KPGRpdiBjbGFzcz0ibW9iaWxlLXdyYXAiPgogIDxkaXYgY2xhc3M9InNjcm9sbC1jYWxlbmRhciIgaWQ9InNjcm9sbENhbCI+CiAgICA8IS0tIEdlbmVyYXRlZCBieSBKUyAtLT4KICA8L2Rpdj4KPC9kaXY+CjxkaXYgY2xhc3M9InRvYXN0IiBpZD0idG9hc3QiPjwvZGl2Pgo8c2NyaXB0Pgpjb25zdCBIT1VSUz1BcnJheS5mcm9tKHtsZW5ndGg6MTB9LChfLGkpPT5gJHtTdHJpbmcoaSs5KS5wYWRTdGFydCgyLCIwIil9OjAwYCk7CmNvbnN0IERBWVM9WyLQndC0Iiwi0J/QvSIsItCS0YIiLCLQodGAIiwi0KfRgiIsItCf0YIiLCLQodCxIl07CmNvbnN0IE1PTlRIUz1bItGB0ZbRh9C90Y8iLCLQu9GO0YLQvtCz0L4iLCLQsdC10YDQtdC30L3RjyIsItC60LLRltGC0L3RjyIsItGC0YDQsNCy0L3RjyIsItGH0LXRgNCy0L3RjyIsItC70LjQv9C90Y8iLCLRgdC10YDQv9C90Y8iLCLQstC10YDQtdGB0L3RjyIsItC20L7QstGC0L3RjyIsItC70LjRgdGC0L7Qv9Cw0LTQsCIsItCz0YDRg9C00L3RjyJdOwpsZXQgYXBwb2ludG1lbnRzPVtdLGJyZWFrcz1bXSxtYXN0ZXJJZD1udWxsLHNlcnZpY2VzPVtdOwpsZXQgdmlld0RheXM9NyxwZXJpb2RTdGFydD1nZXRNb25kYXkobmV3IERhdGUoKSk7CmxldCB3ZWVrU3RhcnQ9Z2V0TW9uZGF5KG5ldyBEYXRlKCkpOwpsZXQgZWRpdGluZ0lkPW51bGwsbW9iaWxlRGF5PW5ldyBEYXRlKCk7CgpmdW5jdGlvbiBzZXRWaWV3KG4pewogIHZpZXdEYXlzPW47CiAgaWYobj09PTEpIHBlcmlvZFN0YXJ0PW5ldyBEYXRlKG1vYmlsZURheSk7CiAgZWxzZSBpZihuPT09Myl7IGNvbnN0IGQ9bmV3IERhdGUobW9iaWxlRGF5KTsgZC5zZXREYXRlKGQuZ2V0RGF0ZSgpLTEpOyBwZXJpb2RTdGFydD1kOyB9CiAgZWxzZSBwZXJpb2RTdGFydD1nZXRNb25kYXkobmV3IERhdGUoKSk7CiAgd2Vla1N0YXJ0PW5ldyBEYXRlKHBlcmlvZFN0YXJ0KTsKICBbInYxIiwidjMiLCJ2NyJdLmZvckVhY2goaWQ9PnsKICAgIGNvbnN0IGVsPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKGlkKTsKICAgIGlmKGVsKXtlbC5zdHlsZS5iYWNrZ3JvdW5kPWlkPT09InYiK24/InZhcigtLWFjY2VudCkiOiJ2YXIoLS1zdXJmYWNlKSI7ZWwuc3R5bGUuY29sb3I9aWQ9PT0idiIrbj8iIzEyMTIxNCI6InZhcigtLW11dGVkKSI7ZWwuc3R5bGUuYm9yZGVyQ29sb3I9aWQ9PT0idiIrbj8idmFyKC0tYWNjZW50KSI6InZhcigtLWJvcmRlcikiO30KICB9KTsKICBsb2FkV2VlaygpOwp9CmZ1bmN0aW9uIGNoYW5nZVBlcmlvZChkKXtwZXJpb2RTdGFydD1hZGREYXlzKHBlcmlvZFN0YXJ0LGQqdmlld0RheXMpO3dlZWtTdGFydD1uZXcgRGF0ZShwZXJpb2RTdGFydCk7bG9hZFdlZWsoKTt9CmZ1bmN0aW9uIGdldE1vbmRheShkKXtjb25zdCByPW5ldyBEYXRlKGQpLGRheT1yLmdldERheSgpLGRpZmY9ci5nZXREYXRlKCktZGF5KyhkYXk9PT0wPy02OjEpO3Iuc2V0RGF0ZShkaWZmKTtyLnNldEhvdXJzKDAsMCwwLDApO3JldHVybiByO30KZnVuY3Rpb24gaXNvRGF0ZShkKXtyZXR1cm4gZC50b0lTT1N0cmluZygpLnNsaWNlKDAsMTApO30KZnVuY3Rpb24gYWRkRGF5cyhkLG4pe2NvbnN0IHI9bmV3IERhdGUoZCk7ci5zZXREYXRlKHIuZ2V0RGF0ZSgpK24pO3JldHVybiByO30KZnVuY3Rpb24gZm10RGF0ZShpc28pe2NvbnN0W3ksbSxkYXldPWlzby5zcGxpdCgiLSIpO3JldHVybiBgJHtwYXJzZUludChkYXkpfSAke01PTlRIU1twYXJzZUludChtKS0xXX1gO30KZnVuY3Rpb24gdG9NaW4odCl7Y29uc3RbaCxtXT10LnNwbGl0KCI6IikubWFwKE51bWJlcik7cmV0dXJuIGgqNjArbTt9CmFzeW5jIGZ1bmN0aW9uIGxvYWRXZWVrKCl7CiAgaWYoIW1hc3RlcklkKXsKICAgIGNvbnN0IG1lPWF3YWl0IGZldGNoKCIvYXBpL21lIikudGhlbihyPT5yLmpzb24oKSk7CiAgICBpZihtZS5tYXN0ZXJfaWQpIG1hc3RlcklkPW1lLm1hc3Rlcl9pZDsKICAgIGVsc2UgeyBjb25zdCBtcz1hd2FpdCBmZXRjaCgiL2FwaS9tYXN0ZXJzIikudGhlbihyPT5yLmpzb24oKSk7aWYobXMubGVuZ3RoKW1hc3RlcklkPW1zWzBdLmlkOyB9CiAgfQogIGlmKCFtYXN0ZXJJZClyZXR1cm47CiAgLy8g0J7QvdC+0LLQu9GO0ZTQvNC+INGW0Lwn0Y8g0LzQsNC50YHRgtGA0LAg0LIg0YXQtdC00LXRgNGWCiAgaWYoIXdpbmRvdy5fbWFzdGVyTmFtZSl7CiAgICBjb25zdCBtZT1hd2FpdCBmZXRjaCgiL2FwaS9tZSIpLnRoZW4ocj0+ci5qc29uKCkpOwogICAgaWYobWUubmFtZSl7d2luZG93Ll9tYXN0ZXJOYW1lPW1lLm5hbWU7Y29uc3QgYj1kb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibWFzdGVyTmFtZUJhZGdlIik7aWYoYiliLnRleHRDb250ZW50PW1lLm5hbWU7fQogIH0KICAvLyDQntC90L7QstC70Y7RlNC80L4g0LrQvdC+0L/QutGDINCh0YzQvtCz0L7QtNC90ZYKICAoZnVuY3Rpb24oKXsKICAgIGNvbnN0IG5vdz1uZXcgRGF0ZSgpOwogICAgY29uc3QgZGF5cz1bItCd0LQiLCLQn9C9Iiwi0JLRgiIsItCh0YAiLCLQp9GCIiwi0J/RgiIsItCh0LEiXTsKICAgIGNvbnN0IG1vbnRocz1bItGB0ZbRhyIsItC70Y7RgiIsItCx0LXRgCIsItC60LLRliIsItGC0YDQsCIsItGH0LXRgCIsItC70LjQvyIsItGB0LXRgCIsItCy0LXRgCIsItC20L7QsiIsItC70LjRgSIsItCz0YDRgyJdOwogICAgY29uc3QgYnRuPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJ0b2RheUJ0biIpOwogICAgaWYoYnRuKSBidG4uaW5uZXJIVE1MPSImIzEyODE5NzsgIitkYXlzW25vdy5nZXREYXkoKV0rIiwgIitub3cuZ2V0RGF0ZSgpKyIgIittb250aHNbbm93LmdldE1vbnRoKCldOwogIH0pKCk7CiAgaWYoIXNlcnZpY2VzLmxlbmd0aCl7c2VydmljZXM9YXdhaXQgZmV0Y2goIi9hcGkvc2VydmljZXMiKS50aGVuKHI9PnIuanNvbigpKTt1cGRhdGVEYXRhbGlzdCgpO30KICBjb25zdCBpc01vYmlsZT13aW5kb3cuaW5uZXJXaWR0aDw9NjQwOwogIGNvbnN0IGxvYWREYXlzPWlzTW9iaWxlPzE0OnZpZXdEYXlzOwogIGNvbnN0IGxvYWRTdGFydD1pc01vYmlsZT9hZGREYXlzKHBlcmlvZFN0YXJ0LC0xKTpwZXJpb2RTdGFydDsKICBjb25zdCBkYXlzPUFycmF5LmZyb20oe2xlbmd0aDpsb2FkRGF5c30sKF8saSk9Pmlzb0RhdGUoYWRkRGF5cyhsb2FkU3RhcnQsaSkpKTsKICBjb25zdCBmcm9tPWRheXNbMF0sdG89ZGF5c1tkYXlzLmxlbmd0aC0xXTsKICBjb25zdFthcCxicl09YXdhaXQgUHJvbWlzZS5hbGwoWwogICAgZmV0Y2goYC9hcGkvYXBwb2ludG1lbnRzL3JhbmdlP21hc3Rlcl9pZD0ke21hc3RlcklkfSZmcm9tX2RhdGU9JHtmcm9tfSZ0b19kYXRlPSR7dG99YCkudGhlbihyPT5yLmpzb24oKSksCiAgICBmZXRjaChgL2FwaS9icmVha3MvcmFuZ2U/bWFzdGVyX2lkPSR7bWFzdGVySWR9JmZyb21fZGF0ZT0ke2Zyb219JnRvX2RhdGU9JHt0b31gKS50aGVuKHI9PnIuanNvbigpKSwKICBdKTsKICBhcHBvaW50bWVudHM9YXA7YnJlYWtzPWJyO3JlbmRlckFsbCgpOwp9CmZ1bmN0aW9uIHVwZGF0ZURhdGFsaXN0KCl7CiAgY29uc3Qgc2VsPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmU2VydmljZSIpOwogIGlmKHNlbCYmc2VydmljZXMubGVuZ3RoKSBzZWwuaW5uZXJIVE1MPXNlcnZpY2VzLm1hcChzPT5gPG9wdGlvbiB2YWx1ZT0iJHtzLm5hbWV9Ij4ke3MubmFtZX08L29wdGlvbj5gKS5qb2luKCIiKTsKfQpmdW5jdGlvbiByZW5kZXJBbGwoKXsKICBjb25zdCBkYXlzPUFycmF5LmZyb20oe2xlbmd0aDp2aWV3RGF5c30sKF8saSk9PmFkZERheXMocGVyaW9kU3RhcnQsaSkpOwogIGNvbnN0IHRvZGF5PWlzb0RhdGUobmV3IERhdGUoKSk7CiAgY29uc3QgZj1mbXREYXRlKGlzb0RhdGUoZGF5c1swXSkpLHQ9dmlld0RheXM+MT9mbXREYXRlKGlzb0RhdGUoZGF5c1tkYXlzLmxlbmd0aC0xXSkpOiIiOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJ3ZWVrTGFiZWwiKS50ZXh0Q29udGVudD12aWV3RGF5cz09PTE/YCR7REFZU1tkYXlzWzBdLmdldERheSgpXX0sICR7Zm10RGF0ZShpc29EYXRlKGRheXNbMF0pKX1gOihgJHtmfSDigJQgJHt0fWApOwogIHJlbmRlckdyaWQoZGF5cyx0b2RheSk7CiAgcmVuZGVyU2Nyb2xsQ2FsZW5kYXIoKTsKfQoKZnVuY3Rpb24gcmVuZGVyR3JpZChkYXlzLHRvZGF5KXsKICBjb25zdCBnPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJ3ZWVrR3JpZCIpOwogIGxldCBoPWA8ZGl2IGNsYXNzPSJ3aCI+PC9kaXY+YDsKICBkYXlzLmZvckVhY2goZD0+e2NvbnN0IGlzbz1pc29EYXRlKGQpLGlUPWlzbz09PXRvZGF5O2grPWA8ZGl2IGNsYXNzPSJ3aCR7aVQ/IiB0b2RheSI6IiJ9Ij48ZGl2IGNsYXNzPSJ3aC1kYXkiPiR7REFZU1tkLmdldERheSgpXX08L2Rpdj48ZGl2IGNsYXNzPSJ3aC1kYXRlIj4ke2QuZ2V0RGF0ZSgpfTwvZGl2PjwvZGl2PmA7fSk7CiAgSE9VUlMuZm9yRWFjaChocj0+ewogICAgaCs9YDxkaXYgY2xhc3M9InRpbWUtY29sIj4ke2hyfTwvZGl2PmA7CiAgICBkYXlzLmZvckVhY2goZD0+ewogICAgICBjb25zdCBpc289aXNvRGF0ZShkKTsKICAgICAgY29uc3QgaXNCPWJyZWFrcy5zb21lKGI9PmIuYnJlYWtfZGF0ZT09PWlzbyYmdG9NaW4oYi5zdGFydF90aW1lKTw9dG9NaW4oaHIpJiZ0b01pbihiLmVuZF90aW1lKT50b01pbihocikpOwogICAgICBjb25zdCBhcD1hcHBvaW50bWVudHMuZmluZChhPT5hLmFwcHRfZGF0ZT09PWlzbyYmYS5zdGFydF90aW1lPT09aHIpOwogICAgICBpZihpc0Ipe2grPWA8ZGl2IGNsYXNzPSJzbG90IGJyZWFrLXNsb3QiPjwvZGl2PmA7fQogICAgICBlbHNlIGlmKGFwKXtoKz1gPGRpdiBjbGFzcz0ic2xvdCI+PGRpdiBjbGFzcz0iYXBwdCIgb25jbGljaz0ib3BlbkRldGFpbCgke2FwLmlkfSkiPjxkaXYgY2xhc3M9ImFuIj4ke2FwLmNsaWVudF9uYW1lfTwvZGl2PjxkaXYgY2xhc3M9ImFzIj4ke2FwLnNlcnZpY2V9PC9kaXY+PGRpdiBjbGFzcz0iYWQiPiR7YXAuZHVyYXRpb25fbWlufSDRhdCyPC9kaXY+PC9kaXY+PC9kaXY+YDt9CiAgICAgIGVsc2V7aCs9YDxkaXYgY2xhc3M9InNsb3QiIG9uY2xpY2s9Im9wZW5BZGRPblNsb3QoJyR7aXNvfScsJyR7aHJ9JykiPjwvZGl2PmA7fQogICAgfSk7CiAgfSk7CiAgZy5pbm5lckhUTUw9aDsKfQpmdW5jdGlvbiByZW5kZXJNb2JpbGVEYXlzKGRheXMsdG9kYXkpe30KZnVuY3Rpb24gcmVuZGVyTW9iaWxlTGlzdCgpe30KCmZ1bmN0aW9uIHJlbmRlclNjcm9sbENhbGVuZGFyKCl7CiAgY29uc3QgY2FsPWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJzY3JvbGxDYWwiKTsKICBpZighY2FsKXJldHVybjsKICBjb25zdCB0b2RheT1pc29EYXRlKG5ldyBEYXRlKCkpOwogIC8vIFNob3cgMTQgZGF5cyBzdGFydGluZyBmcm9tIHBlcmlvZFN0YXJ0IC0gMSAoc28gY3VycmVudCBkYXkgaXMgaW4gbWlkZGxlIGNvbHVtbikKICBjb25zdCBzdGFydERheT1hZGREYXlzKHBlcmlvZFN0YXJ0LC0xKTsKICBjb25zdCBudW1EYXlzPTE0OwogIGNvbnN0IGhvdXJzPUFycmF5LmZyb20oe2xlbmd0aDo5fSwoXyxpKT0+U3RyaW5nKGkrMTApLnBhZFN0YXJ0KDIsIjAiKSsiOjAwIik7CgogIC8vIFJlbW92ZSBvbGQgZmFiIGlmIGV4aXN0cwogIGNvbnN0IG9sZEZhYj1kb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiY2FsRmFiIik7CiAgaWYob2xkRmFiKW9sZEZhYi5yZW1vdmUoKTsKCiAgY2FsLmlubmVySFRNTD1BcnJheS5mcm9tKHtsZW5ndGg6bnVtRGF5c30sKF8sZGkpPT57CiAgICBjb25zdCBkPWFkZERheXMoc3RhcnREYXksZGkpOwogICAgY29uc3QgaXNvPWlzb0RhdGUoZCk7CiAgICBjb25zdCBpc1RvZGF5PWlzbz09PXRvZGF5OwogICAgY29uc3QgZGE9YXBwb2ludG1lbnRzLmZpbHRlcihhPT5hLmFwcHRfZGF0ZT09PWlzbyk7CiAgICBjb25zdCBkYj1icmVha3MuZmlsdGVyKGI9PmIuYnJlYWtfZGF0ZT09PWlzbyk7CiAgICBjb25zdCBzbG90cz1ob3Vycy5tYXAoaHI9PnsKICAgICAgY29uc3QgaXNCPWRiLnNvbWUoYj0+dG9NaW4oYi5zdGFydF90aW1lKTw9dG9NaW4oaHIpJiZ0b01pbihiLmVuZF90aW1lKT50b01pbihocikpOwogICAgICBjb25zdCBhcD1kYS5maW5kKGE9PmEuc3RhcnRfdGltZT09PWhyKTsKICAgICAgbGV0IGlubmVyPSIiOwogICAgICBpZihpc0IpIGlubmVyPWA8ZGl2IGNsYXNzPSJjYWwtYnJlYWsiPtCf0LXRgNC10YDQstCwPC9kaXY+YDsKICAgICAgZWxzZSBpZihhcCkgaW5uZXI9YDxkaXYgY2xhc3M9ImNhbC1hcHB0IiBvbmNsaWNrPSJldmVudC5zdG9wUHJvcGFnYXRpb24oKTtvcGVuRGV0YWlsKCR7YXAuaWR9KSI+PGRpdiBjbGFzcz0iY2FsLWFwcHQtbmFtZSI+JHthcC5jbGllbnRfbmFtZX08L2Rpdj48ZGl2IGNsYXNzPSJjYWwtYXBwdC1zdmMiPiR7YXAuc2VydmljZX08L2Rpdj48ZGl2IGNsYXNzPSJjYWwtYXBwdC1kdXIiPiR7YXAuZHVyYXRpb25fbWlufdGF0LI8L2Rpdj48L2Rpdj5gOwogICAgICByZXR1cm4gYDxkaXYgY2xhc3M9ImNhbC1zbG90IiBvbmNsaWNrPSJvcGVuQWRkT25TbG90KCcke2lzb30nLCcke2hyfScpIj48ZGl2IGNsYXNzPSJjYWwtc2xvdC10aW1lIj4ke2hyfTwvZGl2PjxkaXYgY2xhc3M9ImNhbC1zbG90LWNvbnRlbnQiPiR7aW5uZXJ9PC9kaXY+PC9kaXY+YDsKICAgIH0pLmpvaW4oIiIpOwogICAgcmV0dXJuIGA8ZGl2IGNsYXNzPSJjYWwtZGF5LWNvbCR7aXNUb2RheT8iIHRvZGF5IjoiIn0iPgogICAgICA8ZGl2IGNsYXNzPSJjYWwtZGF5LWhlYWRlciI+PGRpdiBjbGFzcz0iY2FsLWRheS1uYW1lIj4ke0RBWVNbZC5nZXREYXkoKV19PC9kaXY+PGRpdiBjbGFzcz0iY2FsLWRheS1udW0iPiR7ZC5nZXREYXRlKCl9PC9kaXY+PC9kaXY+CiAgICAgIDxkaXYgY2xhc3M9ImNhbC1zbG90cyI+JHtzbG90c308L2Rpdj4KICAgIDwvZGl2PmA7CiAgfSkuam9pbigiIik7CgogIC8vIFNjcm9sbCB0byB0b2RheSAoM3JkIGNvbHVtbiA9IGluZGV4IDEgd2hpY2ggaXMgcGVyaW9kU3RhcnQpCiAgc2V0VGltZW91dCgoKT0+ewogICAgY29uc3QgY29scz1jYWwucXVlcnlTZWxlY3RvckFsbCgiLmNhbC1kYXktY29sIik7CiAgICBpZihjb2xzWzFdKSBjb2xzWzFdLnNjcm9sbEludG9WaWV3KHtiZWhhdmlvcjoiaW5zdGFudCIsaW5saW5lOiJzdGFydCJ9KTsKICB9LDUwKTsKCiAgLy8gQWRkIEZBQgogIGNvbnN0IGZhYj1kb2N1bWVudC5jcmVhdGVFbGVtZW50KCJidXR0b24iKTsKICBmYWIuaWQ9ImNhbEZhYiI7CiAgZmFiLmNsYXNzTmFtZT0iY2FsLWZhYiI7CiAgZmFiLnRleHRDb250ZW50PSIrINCd0L7QstC40Lkg0LfQsNC/0LjRgSI7CiAgZmFiLm9uY2xpY2s9KCk9Pm9wZW5BZGRNb2RhbChpc29EYXRlKHBlcmlvZFN0YXJ0KSwiMTA6MDAiKTsKICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yKCIubW9iaWxlLXdyYXAiKS5hcHBlbmRDaGlsZChmYWIpOwp9CmZ1bmN0aW9uIGNoYW5nZVdlZWsoZCl7d2Vla1N0YXJ0PWFkZERheXMod2Vla1N0YXJ0LGQqNyk7bG9hZFdlZWsoKTt9CmZ1bmN0aW9uIGdvVG9kYXkoKXsKICBwZXJpb2RTdGFydD12aWV3RGF5cz09PTc/Z2V0TW9uZGF5KG5ldyBEYXRlKCkpOm5ldyBEYXRlKCk7CiAgd2Vla1N0YXJ0PW5ldyBEYXRlKHBlcmlvZFN0YXJ0KTsKICBtb2JpbGVEYXk9bmV3IERhdGUoKTsKICBsb2FkV2VlaygpOwp9CmZ1bmN0aW9uIG9wZW5EYXRlUGlja2VyKCl7CiAgY29uc3QgZHA9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImRhdGVQaWNrZXIiKTsKICBkcC52YWx1ZT1pc29EYXRlKHBlcmlvZFN0YXJ0KTsKICBkcC5zaG93UGlja2VyJiZkcC5zaG93UGlja2VyKCk7Cn0KZnVuY3Rpb24gZ29Ub0RhdGUoaXNvKXsKICBpZighaXNvKXJldHVybjsKICBwZXJpb2RTdGFydD1uZXcgRGF0ZShpc28rIlQxMjowMDowMCIpOwogIHdlZWtTdGFydD1uZXcgRGF0ZShwZXJpb2RTdGFydCk7CiAgbW9iaWxlRGF5PW5ldyBEYXRlKHBlcmlvZFN0YXJ0KTsKICBsb2FkV2VlaygpOwp9CmZ1bmN0aW9uIHNldE1vYmlsZURheShpc28pe21vYmlsZURheT1uZXcgRGF0ZShpc28rIlQxMjowMDowMCIpO30KZnVuY3Rpb24gb3BlbkFkZE1vZGFsKGRhdGUsdGltZSl7CiAgZWRpdGluZ0lkPW51bGw7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoIm1vZGFsVGl0bGUiKS50ZXh0Q29udGVudD0i0J3QvtCy0LjQuSDQt9Cw0L/QuNGBIjsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZGVsZXRlQnRuIikuY2xhc3NMaXN0LmFkZCgiaGlkZGVuIik7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZDbGllbnQiKS52YWx1ZT0iIjsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZlNlcnZpY2UiKS52YWx1ZT0iIjsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZkRhdGUiKS52YWx1ZT1kYXRlfHxpc29EYXRlKG1vYmlsZURheXx8bmV3IERhdGUoKSk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZUaW1lIikudmFsdWU9dGltZXx8IjEwOjAwIjsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZkR1cmF0aW9uIikudmFsdWU9IjYwIjsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZk5vdGVzIikudmFsdWU9IiI7CiAgYnVpbGRUaW1lR3JpZCgpO3VwZGF0ZVRpbWVCdG5zKCk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoIm1vZGFsT3ZlcmxheSIpLmNsYXNzTGlzdC5yZW1vdmUoImhpZGRlbiIpOwogIC8vIEZvY3VzIG9uIGNsaWVudCBuYW1lIGZpZWxkCiAgc2V0VGltZW91dCgoKT0+ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZDbGllbnQiKS5mb2N1cygpLDEwMCk7Cn0KZnVuY3Rpb24gb3BlbkFkZE9uU2xvdChkYXRlLHRpbWUpe29wZW5BZGRNb2RhbChkYXRlLHRpbWUpO30KZnVuY3Rpb24gY2xvc2VNb2RhbCgpe2RvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJtb2RhbE92ZXJsYXkiKS5jbGFzc0xpc3QuYWRkKCJoaWRkZW4iKTt9CmZ1bmN0aW9uIG9wZW5EZXRhaWwoaWQpewogIGNvbnN0IGE9YXBwb2ludG1lbnRzLmZpbmQoeD0+eC5pZD09aWQpO2lmKCFhKXJldHVybjsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZGV0YWlsTmFtZSIpLnRleHRDb250ZW50PWEuY2xpZW50X25hbWU7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImRldGFpbEJvZHkiKS5pbm5lckhUTUw9YDxkaXYgY2xhc3M9ImRldGFpbC1yb3ciPjxzcGFuIGNsYXNzPSJkbCI+0J/QvtGB0LvRg9Cz0LA8L3NwYW4+PHNwYW4gY2xhc3M9ImR2Ij4ke2Euc2VydmljZX08L3NwYW4+PC9kaXY+PGRpdiBjbGFzcz0iZGV0YWlsLXJvdyI+PHNwYW4gY2xhc3M9ImRsIj7QlNCw0YLQsDwvc3Bhbj48c3BhbiBjbGFzcz0iZHYiPiR7Zm10RGF0ZShhLmFwcHRfZGF0ZSl9PC9zcGFuPjwvZGl2PjxkaXYgY2xhc3M9ImRldGFpbC1yb3ciPjxzcGFuIGNsYXNzPSJkbCI+0KfQsNGBPC9zcGFuPjxzcGFuIGNsYXNzPSJkdiI+JHthLnN0YXJ0X3RpbWV9LCAke2EuZHVyYXRpb25fbWlufSDRhdCyPC9zcGFuPjwvZGl2PiR7YS5ub3Rlcz9gPGRpdiBjbGFzcz0iZGV0YWlsLXJvdyI+PHNwYW4gY2xhc3M9ImRsIj7QndC+0YLQsNGC0LrQuDwvc3Bhbj48c3BhbiBjbGFzcz0iZHYiPiR7YS5ub3Rlc308L3NwYW4+PC9kaXY+YDoiIn1gOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJkZXRhaWxFZGl0QnRuIikub25jbGljaz0oKT0+ewogICAgZWRpdGluZ0lkPWEuaWQ7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibW9kYWxUaXRsZSIpLnRleHRDb250ZW50PSLQoNC10LTQsNCz0YPQstCw0YLQuCI7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZGVsZXRlQnRuIikuY2xhc3NMaXN0LnJlbW92ZSgiaGlkZGVuIik7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZkNsaWVudCIpLnZhbHVlPWEuY2xpZW50X25hbWU7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZlNlcnZpY2UiKS52YWx1ZT1hLnNlcnZpY2U7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZkRhdGUiKS52YWx1ZT1hLmFwcHRfZGF0ZTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmVGltZSIpLnZhbHVlPWEuc3RhcnRfdGltZTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmRHVyYXRpb24iKS52YWx1ZT1hLmR1cmF0aW9uX21pbjsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmTm90ZXMiKS52YWx1ZT1hLm5vdGVzfHwiIjsKICAgIGNsb3NlRGV0YWlsKCk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibW9kYWxPdmVybGF5IikuY2xhc3NMaXN0LnJlbW92ZSgiaGlkZGVuIik7CiAgfTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZGV0YWlsT3ZlcmxheSIpLmNsYXNzTGlzdC5yZW1vdmUoImhpZGRlbiIpOwp9CmZ1bmN0aW9uIGNsb3NlRGV0YWlsKCl7ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImRldGFpbE92ZXJsYXkiKS5jbGFzc0xpc3QuYWRkKCJoaWRkZW4iKTt9CmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJtb2RhbE92ZXJsYXkiKS5hZGRFdmVudExpc3RlbmVyKCJjbGljayIsZT0+e2lmKGUudGFyZ2V0PT09ZS5jdXJyZW50VGFyZ2V0KWNsb3NlTW9kYWwoKTt9KTsKZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImRldGFpbE92ZXJsYXkiKS5hZGRFdmVudExpc3RlbmVyKCJjbGljayIsZT0+e2lmKGUudGFyZ2V0PT09ZS5jdXJyZW50VGFyZ2V0KWNsb3NlRGV0YWlsKCk7fSk7CmFzeW5jIGZ1bmN0aW9uIHNhdmVBcHB0KCl7CiAgY29uc3QgYm9keT17bWFzdGVyX2lkOm1hc3RlcklkLGNsaWVudF9uYW1lOmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmQ2xpZW50IikudmFsdWUudHJpbSgpLHNlcnZpY2U6ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZTZXJ2aWNlIikudmFsdWUudHJpbSgpLGFwcHRfZGF0ZTpkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZkRhdGUiKS52YWx1ZSxzdGFydF90aW1lOmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmVGltZSIpLnZhbHVlLGR1cmF0aW9uX21pbjpwYXJzZUludChkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZkR1cmF0aW9uIikudmFsdWUpLG5vdGVzOmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmTm90ZXMiKS52YWx1ZS50cmltKCl9OwogIGlmKCFib2R5LmNsaWVudF9uYW1lfHwhYm9keS5zZXJ2aWNlKXthbGVydCgi0JfQsNC/0L7QstC90ZbRgtGMINGW0LxcdTAwMjfRjyDRliDQv9C+0YHQu9GD0LPRgyIpO3JldHVybjt9CiAgY29uc3QgdXJsPWVkaXRpbmdJZD9gL2FwaS9hcHBvaW50bWVudHMvJHtlZGl0aW5nSWR9YDoiL2FwaS9hcHBvaW50bWVudHMiOwogIGNvbnN0IHJlcz1hd2FpdCBmZXRjaCh1cmwse21ldGhvZDplZGl0aW5nSWQ/IlBVVCI6IlBPU1QiLGhlYWRlcnM6eyJDb250ZW50LVR5cGUiOiJhcHBsaWNhdGlvbi9qc29uIn0sYm9keTpKU09OLnN0cmluZ2lmeShib2R5KX0pOwogIGlmKCFyZXMub2spe2NvbnN0IGU9YXdhaXQgcmVzLmpzb24oKTthbGVydChlLmRldGFpbHx8ItCf0L7QvNC40LvQutCwIik7cmV0dXJuO30KICBjbG9zZU1vZGFsKCk7c2hvd1RvYXN0KGVkaXRpbmdJZD8i0J7QvdC+0LLQu9C10L3QviI6ItCX0LHQtdGA0LXQttC10L3QviIpOwogIG1vYmlsZURheT1uZXcgRGF0ZShib2R5LmFwcHRfZGF0ZSsiVDEyOjAwOjAwIik7CiAgYXdhaXQgbG9hZFdlZWsoKTsKfQphc3luYyBmdW5jdGlvbiBkZWxldGVBcHB0KCl7CiAgaWYoIWVkaXRpbmdJZHx8IWNvbmZpcm0oItCS0LjQtNCw0LvQuNGC0Lgg0LfQsNC/0LjRgT8iKSlyZXR1cm47CiAgYXdhaXQgZmV0Y2goYC9hcGkvYXBwb2ludG1lbnRzLyR7ZWRpdGluZ0lkfWAse21ldGhvZDoiREVMRVRFIn0pOwogIGNsb3NlTW9kYWwoKTtzaG93VG9hc3QoItCS0LjQtNCw0LvQtdC90L4iKTthd2FpdCBsb2FkV2VlaygpOwp9CmZ1bmN0aW9uIHNob3dUb2FzdChtc2cpe2NvbnN0IHQ9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoInRvYXN0Iik7dC50ZXh0Q29udGVudD1tc2c7dC5jbGFzc0xpc3QuYWRkKCJzaG93Iik7c2V0VGltZW91dCgoKT0+dC5jbGFzc0xpc3QucmVtb3ZlKCJzaG93IiksMjUwMCk7fQovLyBGb3JjZSBtb2JpbGUgbGF5b3V0IGNoZWNrCmZ1bmN0aW9uIGFwcGx5TGF5b3V0KCl7CiAgY29uc3QgaXNNb2JpbGU9d2luZG93LmlubmVyV2lkdGg8PTc2OHx8KCdvbnRvdWNoc3RhcnQnIGluIHdpbmRvdyYmd2luZG93LmlubmVyV2lkdGg8PTEwMjQpOwogIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3IoIi5jb250ZW50Iikuc3R5bGUuZGlzcGxheT1pc01vYmlsZT8ibm9uZSI6IiI7CiAgZG9jdW1lbnQucXVlcnlTZWxlY3RvcigiLm1vYmlsZS13cmFwIikuc3R5bGUuZGlzcGxheT1pc01vYmlsZT8iZmxleCI6Im5vbmUiOwp9CmFwcGx5TGF5b3V0KCk7CndpbmRvdy5hZGRFdmVudExpc3RlbmVyKCJyZXNpemUiLGFwcGx5TGF5b3V0KTsKPC9zY3JpcHQ+Cgo8ZGl2IGNsYXNzPSJvdmVybGF5IGhpZGRlbiIgaWQ9Im1vZGFsT3ZlcmxheSI+CjxkaXYgY2xhc3M9Im1vZGFsIj4KPGgyIGlkPSJtb2RhbFRpdGxlIj7QndC+0LLQuNC5INC30LDQv9C40YE8L2gyPgo8ZGl2IGNsYXNzPSJmb3JtLXJvdyI+PGxhYmVsPtCa0LvRltGU0L3RgjwvbGFiZWw+PGlucHV0IGlkPSJmQ2xpZW50IiB0eXBlPSJ0ZXh0IiBwbGFjZWhvbGRlcj0i0JrQu9GW0ZTQvdGCIj48L2Rpdj4KPGRpdiBjbGFzcz0iZm9ybS1yb3ciPjxsYWJlbD7Qn9C+0YHQu9GD0LPQsDwvbGFiZWw+PHNlbGVjdCBpZD0iZlNlcnZpY2UiPjwvc2VsZWN0PjwvZGl2Pgo8ZGl2IGNsYXNzPSJmb3JtLXJvdyI+PGxhYmVsPtCU0LDRgtCwPC9sYWJlbD48aW5wdXQgaWQ9ImZEYXRlIiB0eXBlPSJkYXRlIj48L2Rpdj4KPGRpdiBjbGFzcz0iZm9ybS0yY29sIj4KPGRpdiBjbGFzcz0iZm9ybS1yb3ciPjxsYWJlbD7Qp9Cw0YE8L2xhYmVsPgo8aW5wdXQgaWQ9ImZUaW1lIiB0eXBlPSJ0aW1lIiBzdGVwPSI5MDAiIG9uY2hhbmdlPSJ1cGRhdGVUaW1lQnRucygpIj4KPGRpdiBjbGFzcz0idGltZS1ncmlkIiBpZD0idGltZUdyaWQiPjwvZGl2Pgo8L2Rpdj4KPGRpdiBjbGFzcz0iZm9ybS1yb3ciPjxsYWJlbD7QotGA0LjQstCw0LvRltGB0YLRjCAo0YXQsik8L2xhYmVsPjxpbnB1dCBpZD0iZkR1cmF0aW9uIiB0eXBlPSJudW1iZXIiIG1pbj0iMTUiIHN0ZXA9IjE1IiB2YWx1ZT0iNjAiPjwvZGl2Pgo8L2Rpdj4KPGRpdiBjbGFzcz0iZm9ybS1yb3ciPjxsYWJlbD7QndC+0YLQsNGC0LrQuDwvbGFiZWw+PHRleHRhcmVhIGlkPSJmTm90ZXMiIHJvd3M9IjMiPjwvdGV4dGFyZWE+PC9kaXY+CjxkaXYgY2xhc3M9Im1vZGFsLWZvb3RlciI+CjxidXR0b24gY2xhc3M9ImJ0biBidG4tZGFuZ2VyIGhpZGRlbiIgaWQ9ImRlbGV0ZUJ0biIgb25jbGljaz0iZGVsZXRlQXBwdCgpIj7QktC40LTQsNC70LjRgtC4PC9idXR0b24+CjxidXR0b24gY2xhc3M9ImJ0biIgb25jbGljaz0iY2xvc2VNb2RhbCgpIj7QodC60LDRgdGD0LLQsNGC0Lg8L2J1dHRvbj4KPGJ1dHRvbiBjbGFzcz0iYnRuIGJ0bi1wcmltYXJ5IiBvbmNsaWNrPSJzYXZlQXBwdCgpIj7Ql9Cx0LXRgNC10LPRgtC4PC9idXR0b24+CjwvZGl2PjwvZGl2PjwvZGl2Pgo8ZGl2IGNsYXNzPSJvdmVybGF5IGhpZGRlbiIgaWQ9ImRldGFpbE92ZXJsYXkiPgo8ZGl2IGNsYXNzPSJtb2RhbCI+CjxkaXYgY2xhc3M9ImRldGFpbC1iYXIiPjwvZGl2Pgo8aDIgaWQ9ImRldGFpbE5hbWUiPjwvaDI+CjxkaXYgaWQ9ImRldGFpbEJvZHkiPjwvZGl2Pgo8ZGl2IGNsYXNzPSJtb2RhbC1mb290ZXIiPgo8YnV0dG9uIGNsYXNzPSJidG4iIG9uY2xpY2s9ImNsb3NlRGV0YWlsKCkiPtCX0LDQutGA0LjRgtC4PC9idXR0b24+CjxidXR0b24gY2xhc3M9ImJ0biBidG4tcHJpbWFyeSIgaWQ9ImRldGFpbEVkaXRCdG4iPtCg0LXQtNCw0LPRg9Cy0LDRgtC4PC9idXR0b24+CjwvZGl2PjwvZGl2PjwvZGl2Pgo8c2NyaXB0Pgpsb2FkV2VlaygpOwovLyBUaW1lIHF1aWNrLXBpY2sgYnV0dG9ucwpmdW5jdGlvbiBidWlsZFRpbWVHcmlkKCl7CiAgY29uc3QgZ3JpZD1kb2N1bWVudC5nZXRFbGVtZW50QnlJZCgidGltZUdyaWQiKTsKICBpZighZ3JpZClyZXR1cm47CiAgY29uc3QgdGltZXM9WyIwOTowMCIsIjA5OjMwIiwiMTA6MDAiLCIxMDozMCIsIjExOjAwIiwiMTE6MzAiLCIxMjowMCIsIjEyOjMwIiwiMTM6MDAiLCIxMzozMCIsIjE0OjAwIiwiMTQ6MzAiLCIxNTowMCIsIjE1OjMwIiwiMTY6MDAiLCIxNjozMCIsIjE3OjAwIiwiMTc6MzAiLCIxODowMCJdOwogIGdyaWQuaW5uZXJIVE1MPXRpbWVzLm1hcCh0PT5gPGJ1dHRvbiB0eXBlPSJidXR0b24iIGNsYXNzPSJ0aW1lLWJ0biIgb25jbGljaz0ic2VsZWN0VGltZSgnJHt0fScpIj4ke3R9PC9idXR0b24+YCkuam9pbigiIik7Cn0KZnVuY3Rpb24gc2VsZWN0VGltZSh0KXsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZlRpbWUiKS52YWx1ZT10OwogIHVwZGF0ZVRpbWVCdG5zKCk7Cn0KZnVuY3Rpb24gdXBkYXRlVGltZUJ0bnMoKXsKICBjb25zdCBjdXI9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZUaW1lIikudmFsdWU7CiAgZG9jdW1lbnQucXVlcnlTZWxlY3RvckFsbCgiLnRpbWUtYnRuIikuZm9yRWFjaChiPT57CiAgICBiLmNsYXNzTGlzdC50b2dnbGUoImFjdGl2ZSIsYi50ZXh0Q29udGVudD09PWN1cik7CiAgfSk7Cn0KZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoIm1vZGFsT3ZlcmxheSIpLm9uY2xpY2s9ZnVuY3Rpb24oZSl7aWYoZS50YXJnZXQ9PT10aGlzKWNsb3NlTW9kYWwoKTt9Owpkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZGV0YWlsT3ZlcmxheSIpLm9uY2xpY2s9ZnVuY3Rpb24oZSl7aWYoZS50YXJnZXQ9PT10aGlzKWNsb3NlRGV0YWlsKCk7fTsKZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImRldGFpbEVkaXRCdG4iKS5vbmNsaWNrPWZ1bmN0aW9uKCl7CiAgdmFyIGE9d2luZG93Ll9jdXJBcHB0O2lmKCFhKXJldHVybjsKICBlZGl0aW5nSWQ9YS5pZDsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibW9kYWxUaXRsZSIpLnRleHRDb250ZW50PSLQoNC10LTQsNCz0YPQstCw0YLQuCI7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImRlbGV0ZUJ0biIpLmNsYXNzTGlzdC5yZW1vdmUoImhpZGRlbiIpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmQ2xpZW50IikudmFsdWU9YS5jbGllbnRfbmFtZTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZlNlcnZpY2UiKS52YWx1ZT1hLnNlcnZpY2U7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZEYXRlIikudmFsdWU9YS5hcHB0X2RhdGU7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoImZUaW1lIikudmFsdWU9YS5zdGFydF90aW1lOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCJmRHVyYXRpb24iKS52YWx1ZT1hLmR1cmF0aW9uX21pbjsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgiZk5vdGVzIikudmFsdWU9YS5ub3Rlc3x8IiI7CiAgY2xvc2VEZXRhaWwoKTsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgibW9kYWxPdmVybGF5IikuY2xhc3NMaXN0LnJlbW92ZSgiaGlkZGVuIik7Cn07Cjwvc2NyaXB0Pgo8L2JvZHk+CjwvaHRtbD4=').decode()
