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
        "INSERT OR IGNORE INTO settings (key,value) VALUES ('pwd_reception','reception123')",
    ])
    rows = turso("SELECT COUNT(*) as cnt FROM masters")
    if int(rows[0]['cnt']) == 0:
        today = date.today().isoformat()
        for name, color, initials in [("Аня Мороз","#7F77DD","АМ"),("Катя Власюк","#1D9E75","КВ"),("Оля Петренко","#BA7517","ОП"),("Діана Сич","#D85A30","ДС")]:
            turso_exec("INSERT INTO masters (name,color,initials) VALUES (?,?,?)", [name,color,initials])
        for mid, name, svc, t, dur in [(1,"Марина К.","Масаж обличчя","09:00",60),(1,"Світлана О.","Брови","11:00",45),(1,"Олена Ж.","Ін'єкції","14:00",45),(2,"Лариса Н.","Чистка шкіри","10:00",60),(2,"Наталя В.","Ліфтинг","12:00",90),(3,"Тетяна Р.","Ботокс","09:00",60),(3,"Ірина М.","Мезотерапія","11:00",60),(4,"Вікторія Б.","Пілінг","10:00",60),(4,"Юлія Т.","Масаж","12:00",60),(4,"Галина С.","Чистка","14:00",60)]:
            turso_exec("INSERT INTO appointments (master_id,client_name,service,appt_date,start_time,duration_min) VALUES (?,?,?,?,?,?)", [mid,name,svc,today,t,dur])
        for i in range(1,5):
            turso_exec("INSERT INTO breaks (master_id,break_date,start_time,end_time,label) VALUES (?,?,?,?,?)", [i,today,"13:00","14:00","Обід"])


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

def require_auth(token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess:
        raise HTTPException(401, "Не авторизовано")
    return sess

def require_edit(token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess or sess["role"] not in ("admin", "reception"):
        raise HTTPException(403, "Недостатньо прав")
    return sess


# ─── REST API ──────────────────────────────────────────────────────────────────

@app.get("/api/masters")
def list_masters():
    rows = turso("SELECT * FROM masters ORDER BY id")
    return [{**r, 'id': int(r['id'])} for r in rows]

@app.post("/api/masters", status_code=201)
def create_master(m: MasterIn):
    rid = turso_exec("INSERT INTO masters (name,color,initials) VALUES (?,?,?)", [m.name, m.color, m.initials])
    return {"id": int(rid), **m.dict()}

@app.put("/api/masters/{master_id}")
def update_master(master_id: int, m: MasterIn):
    rows = turso("SELECT id FROM masters WHERE id=?", [master_id])
    if not rows:
        raise HTTPException(404, "Майстра не знайдено")
    turso_exec("UPDATE masters SET name=?,color=?,initials=? WHERE id=?", [m.name, m.color, m.initials, master_id])
    return {"id": master_id, **m.dict()}

@app.delete("/api/masters/{master_id}")
def delete_master(master_id: int):
    turso_exec("DELETE FROM appointments WHERE master_id=?", [master_id])
    turso_exec("DELETE FROM breaks WHERE master_id=?", [master_id])
    turso_exec("DELETE FROM masters WHERE id=?", [master_id])
    return {"ok": True}

@app.get("/api/appointments")
def list_appointments(date: str = None):
    if date:
        rows = turso("SELECT a.*, m.name as master_name, m.color, m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.appt_date=? ORDER BY a.start_time", [date])
    else:
        rows = turso("SELECT a.*, m.name as master_name, m.color, m.initials FROM appointments a JOIN masters m ON a.master_id=m.id ORDER BY a.appt_date, a.start_time")
    return [{**r, 'id': int(r['id']), 'master_id': int(r['master_id']), 'duration_min': int(r['duration_min'])} for r in rows]

@app.post("/api/appointments", status_code=201)
def create_appointment(a: AppointmentIn):
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
def update_appointment(appt_id: int, a: AppointmentUpdate):
    rows = turso("SELECT * FROM appointments WHERE id=?", [appt_id])
    if not rows:
        raise HTTPException(404, "Запис не знайдено")
    data = rows[0]
    for k, v in a.dict(exclude_none=True).items():
        data[k] = v
    turso_exec("UPDATE appointments SET client_name=?,service=?,appt_date=?,start_time=?,duration_min=?,notes=? WHERE id=?",
              [data["client_name"], data["service"], data["appt_date"], data["start_time"], data["duration_min"], data["notes"], appt_id])
    rows2 = turso("SELECT a.*,m.name as master_name,m.color,m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.id=?", [appt_id])
    r = rows2[0]
    return {**r, 'id': int(r['id']), 'master_id': int(r['master_id']), 'duration_min': int(r['duration_min'])}

@app.delete("/api/appointments/{appt_id}")
def delete_appointment(appt_id: int):
    turso_exec("DELETE FROM appointments WHERE id=?", [appt_id])
    return {"ok": True}

@app.get("/api/breaks")
def list_breaks(date: str = None):
    if date:
        rows = turso("SELECT * FROM breaks WHERE break_date=?", [date])
    else:
        rows = turso("SELECT * FROM breaks")
    return [{**r, 'id': int(r['id']), 'master_id': int(r['master_id'])} for r in rows]


# ─── FRONTEND ──────────────────────────────────────────────────────────────────


LOGIN_HTML = r"""<!DOCTYPE html>
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
.logo{text-align:center;margin-bottom:28px}
.logo img{height:60px;width:auto}
h2{font-family:'Montserrat',sans-serif;font-size:18px;font-weight:700;margin-bottom:20px;color:#E4E4E7;text-align:center}
.role-tabs{display:flex;gap:6px;margin-bottom:20px;background:#121214;border-radius:10px;padding:4px}
.role-tab{flex:1;padding:8px;text-align:center;border-radius:7px;cursor:pointer;font-size:12px;font-weight:600;color:#71717A;font-family:'Montserrat',sans-serif;transition:all .15s}
.role-tab.active{background:#1E1E22;color:#00C8B4;box-shadow:0 1px 4px rgba(0,0,0,.4)}
.field{margin-bottom:14px}
.field label{display:block;font-size:12px;font-weight:600;color:#A1A1AA;margin-bottom:5px}
.field select,.field input{width:100%;padding:10px 12px;background:#121214;border:1px solid #2E2E36;border-radius:8px;color:#E4E4E7;font-family:'Inter',sans-serif;font-size:14px;outline:none;transition:border-color .15s}
.field select:focus,.field input:focus{border-color:#00C8B4;box-shadow:0 0 0 2px rgba(0,200,180,.15)}
.btn{width:100%;padding:12px;background:#00C8B4;color:#121214;border:none;border-radius:8px;font-family:'Montserrat',sans-serif;font-size:14px;font-weight:700;cursor:pointer;transition:opacity .15s;margin-top:4px}
.btn:hover{opacity:.88}
.err{color:#F87171;font-size:12px;margin-top:10px;text-align:center;min-height:18px}
.master-field{display:none}
</style>
</head>
<body>
<div class="card">
  <div class="logo"><img src="data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyBpZD0iTGF5ZXJfMSIgZGF0YS1uYW1lPSJMYXllciAxIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyMTUzIDEwODAiPgogIDxkZWZzPgogICAgPHN0eWxlPgogICAgICAuY2xzLTEgewogICAgICAgIGZpbGw6ICMwZGUwZDY7CiAgICAgIH0KCiAgICAgIC5jbHMtMiB7CiAgICAgICAgZmlsbDogI2UzZTRlODsKICAgICAgfQogICAgPC9zdHlsZT4KICA8L2RlZnM+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMzg0LjIzLDIxNC45OWMtMTAuODEtNS41NS0xMC44MSw0Mi4zMS0xMC44MSw0Mi4zMS0xMC44MSwyNS45NS0yMS42MiwyOC4xMS0yMS42MiwyOC4xMS0xMi45Ny04LjY1LTEwLjgxLTQ3LjU3LTEwLjgxLTQ3LjU3LTE1LjE0LTU2LjIyLDQzLjI0LTU4LjM4LDQzLjI0LTU4LjM4LDAsMC0yMS42Mi04LjY1LTM4LjkyLDYuNDktMjMuMDEsMjAuMTQtMTcuMyw2Mi43LTguNjUsODguNjUsOC42NSwyNS45NSwyMS42MiwxNS4xNCwyMS42MiwxNS4xNC0xMi45NywxNy4zLTI1Ljk1LDEyLjk3LTI1Ljk1LDEyLjk3LTI4LjExLTYuNDktMzguOTItMi4xNi0zOC45Mi0yLjE2LTMwLjI3LDEyLjk3LTIxLjYyLDY3LjAzLTE1LjE0LDg4LjY1LDYuNDksMjEuNjIsMzIuNDMsOTIuOTcsMzIuNDMsOTIuOTctOC42NSw2LjQ5LTE5LjQ2LDI1Ljk1LTE1LjE0LDQxLjA4LDQuMzIsMTUuMTQsMjUuOTUsMzIuNDMsMzYuNzYsMjEuNjIsMTAuODEtMTAuODEtOC42NS00Ny41Ny04LjY1LTQ3LjU3bC0yNC40Ni02Mi42NmMtMS4xNi0zLjQxLTIuMTYtNi44Ni0yLjk4LTEwLjM3LTMuMjEtMTMuNjctMjIuMjktNzEuODMtMTEuNDgtOTcuNzgsMTEuMDktMjYuNjMsNDcuNTctMTcuMyw0Ny41Ny0xNy4zLDQxLjA4LDguNjUsNDkuNzMtNDkuNzMsNDkuNzMtNDkuNzMsMTAuODEtMTAuODEsMTIuOTctMzguOTIsMi4xNi00NC40N1pNMzIxLjUzLDUyMS4wOGMwLDEwLjgxLDAsMTUuMTQtNi40OSwxMi45N3MtMTQuNDQtMTQuOTktMTIuOTctMjMuNzhjMi4xNi0xMi45NywxMC44MS0yMS42MiwxMC44MS0yMS42MiwwLDAsOC42NSwyMS42Miw4LjY1LDMyLjQzWiIvPgogIDxwYXRoIGNsYXNzPSJjbHMtMSIgZD0iTTM4My44NSwyNjkuMjlzLTQuMzIsMzAuMjctMjMuNzgsNjQuODZjLTE5LjQ2LDM0LjU5LTQ2LjQ5LDgzLjI0LTQ2LjQ5LDE1MC4yN2w0LjMyLTQuMzIsNC4zMi00LjMyczIuMTYtMTIuOTcsOC42NS00My4yNGM2LjQ5LTMwLjI3LDI3LjAzLTYzLjc4LDQxLjA4LTkyLjk3LDEyLjIzLTI1LjQsMTQuMDUtNTIuOTcsMTEuODktNzAuMjdaIi8+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMzMxLjY1LDg3OC42NHM1Ni45MS0xMDYuNzUsNzIuMDQtMTM5LjE4YzE1LjE0LTMyLjQzLDQwLTExMS4zNSwzMi40My0xNjAtNi44NS00NC4wNC0yMC41NC03Ni43Ni01Mi45Ny04OS43My0zMS4xNi0xMi40Ny02MS42Mi05LjczLTcwLjI3LTEuMDhsLTIuMTYtNi40OXMyNS4wMy0yMS42Miw4MC42Mi01LjQxYzU1LjU5LDE2LjIyLDcxLjgxLDg2LjQ5LDcxLjgxLDExNC41OSwwLDMxLjMtMy44OSwxMDAuMTgtNDMuMjQsMTYyLjE2LTQwLjU1LDYzLjg2LTg4LjI2LDEyNS4xMy04OC4yNiwxMjUuMTNaIi8+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMzIyLjIzLDQ3Ny45M3MtNS40MS0yOS4xOSwxOC4zOC00MGMyMy43OC0xMC44MSw4Ny41Ny0xMS44OSw5Ny4zLTY5LjE5LDExLjQ2LTY3LjQ5LTQ5LjExLTYzLjUxLTQ5LjExLTYzLjUxLDAsMCw1NC41OS0yOC41Nyw3MS44MSwyOS45OSwxMC44MSwzNi43Ni0xMi45Nyw4Ni40OS03MS4zNSw5OS40Ni01My4wNywxMS43OS01NC4wNSwxNS4xNC02Ny4wMyw0My4yNFoiLz4KICA8cGF0aCBjbGFzcz0iY2xzLTEiIGQ9Ik04MDYsNzM4YzU4LDQwLDExNy4yOSw1OS4xOCwxNDQsNjksMTY2LDYxLDMyMiw3NCwzMjIsNzQsNTQwLDcyLDY4MC4wMi0xMDYuODksNjgwLjAyLTEwNi44OS0yMzAuOTgsMTU2LjExLTc5Ni45Nyw1My4wMS05MDIuMDIsMzAuODktMzgtOC0xMTUtMjUtMjMyLTgzIi8+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNODIzLjEsNzU1LjA0Yy0yNi4zMywyNy43NS02MS4yOSw0OS4wMy0xMDQuODksNjMuODMtMzcuNDMsMTIuNDktNzYuOTIsMTguNzMtMTE4LjQ2LDE4LjczLTI3LjE1LDAtNTMuMjctNi4wMi03OC4zNi0xOC4wNC0zMi4wOC0xNS4yNi00OC4xMy0zNi4zMS00OC4xMy02My4xNCwwLTMwLjk4LDEzLjE2LTU2LjQzLDM5LjQ5LTc2LjMyLDExLjkyLTguNzgsMjQuMjctMTUuMzcsMzcuMDItMTkuNzcsMTIuNzUtNC4zOSwyNi4xMi03LjA1LDQwLjExLTcuOTgsNi45OS0xOC41LDE1LjczLTQwLjAxLDI2LjIyLTY0LjUzLDEwLjQ5LTI0LjUxLDIxLjYyLTQ2LjAyLDMxLjkxLTY3LjMsMy4yOS02LjQ3LDgtMTYsMTQtMjYsMTAuMjktMTcuMTYsMjAtMzEsMjQtMzUsMTcuNTEtMTcuNTEsMzYtMTUsMzYtMTUsMCwwLTIuOTksMi4yNC0xMy40OCwxNS43Ni0zLjU0LDQuNTUtNi44OCw5LjI3LTkuOTksMTQuMTMtMzUuODMsNTUuOTUtNTYuMDcsMTA2LjM5LTg3LjY4LDE3Ny45NCw5Mi41NSwxLjg1LDE2MS40NCwyNS4yMiwyMDYuNyw3MC4wOCwxMy4xNi0xOS44OCwxOS43NC0zOC4xNiwxOS43NC01NC44MSwwLTI5LjE0LTE3LjQ5LTUyLjA0LTUyLjQ1LTY4LjY5LTE1LjE2LTYuOTctNTAuMDEtMTcuNDgtNzYuODQtMjIuNC0yMS4yMi0zLjg5LTI3LTUtMjctNSwwLDAsOC45NC0zLjE5LDIxLTcsMTktNiwyNi04LDM3LTEyLDQ1LjY0LTE2LjYsNzEuNjEtMjkuMDIsOTMuOTctNTIuODIsOS40Ni05LjcxLDE0LjE5LTE4LjUsMTQuMTktMjYuMzcsMC0xNi42NS0xOS4xMy0yOS4xNC01Ny4zOC0zNy40Ny0yNS45MS01LjU1LTUyLjY2LTguMzMtODAuMjEtOC4zMy03My42NCwwLTE0MC45OSwxMC45Mi0yMDUuNTcsNDAuOTgtMi40Ny45My0xNiw5LTE2LDksMCwwLDguMzMtMTEuMzMsMTUtMTgsOS05LDE5LTE3LDMzLTI0LDQyLjc4LTE5LjQzLDc3LjcyLTI4LjEsMTQzLjk1LTI4LjEsMzkuNDksMCw3Ni4wOSw0LjE2LDEwOS44MywxMi40OSw1Mi42NSwxMi40OSw3OC45OCwzMi4zOCw3OC45OCw1OS42NywwLDIyLjItMTYuMDQsNDIuMzMtNDguMTMsNjAuMzctMjMuNDUsMTMuNDItNDguMzQsMjIuNjctNzQuNjYsMjcuNzUsMjkuMiw3LjQxLDU0LjMsMTguMjgsNzUuMjcsMzIuNjEsMjguNzksMTkuNDMsNDMuMTksNDIuNzksNDMuMTksNzAuMDgsMCwyMi4yLTEwLjA4LDQ2LjAzLTMwLjIzLDcxLjQ3TTU2MC44Nyw4MDguNDdjLS44Ny4wNS0zLjg3LTkuNDYtMy44Ny0yMS45NSwwLTIwLjgyLDQuNDktNTYuNjksMjUuNDYtMTE0LjA1LTU0LjcxLDEwLjE4LTgyLjA2LDM4LjYzLTgyLjA2LDg1LjM0LDAsMjAuODIsMTIuNTQsMzcuNDcsMzcuNjQsNDkuOTYsMTkuNzQsOS43MSw0MC4zMSwxNC41Nyw2MS43LDE0LjU3LDkxLjMyLDAsMTYwLjIxLTI4LjIxLDIwNi43LTg0LjY1LTIzLjA0LTIxLjc0LTUyLjA0LTM4Ljg2LTg3LTUxLjM1LTMyLjUtMTEuNTYtNjUuMi0xNy4zNS05OC4xLTE3LjM1aC04Ljk1Yy0zLjA4LDAtNi4wNy4yNC04Ljk1LjY5LTI0LjY4LDU4Ljc1LTQyLjQ0LDExOC40OC00Mi40NCwxMzguODMiLz4KICA8Zz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTg5Ni4yOCw2MjUuMDF2LTY0Ljg1aDM0LjY1YzguOTYsMCwxNS41NiwxLjU5LDE5LjgzLDQuNzcsNC4yNiwzLjE4LDYuMzksNy4yNCw2LjM5LDEyLjE4LDAsMy4yNy0uOTEsNi4xOS0yLjczLDguNzUtMS44MiwyLjU2LTQuNDYsNC41OS03LjkyLDYuMDctMy40NiwxLjQ4LTcuNzIsMi4yMi0xMi43OSwyLjIybDEuODUtNWM1LjA2LDAsOS40My43MSwxMy4xMSwyLjEzLDMuNjcsMS40Miw2LjUyLDMuNDcsOC41Miw2LjE2LDIuMDEsMi42OSwzLjAxLDUuOTIsMy4wMSw5LjY4LDAsNS42Mi0yLjMzLDEwLTYuOTksMTMuMTYtNC42NiwzLjE1LTExLjQ3LDQuNzItMjAuNDMsNC43MmgtMzYuNVpNOTE3Ljc4LDYwOS43MmgxMy4xNmMyLjQxLDAsNC4yMi0uNDMsNS40Mi0xLjMsMS4yLS44NiwxLjgxLTIuMTMsMS44MS0zLjhzLS42LTIuOTMtMS44MS0zLjhjLTEuMi0uODYtMy4wMS0xLjMtNS40Mi0xLjNoLTE0LjY0di0xNC40NWgxMS42N2MyLjQ3LDAsNC4yOC0uNDIsNS40Mi0xLjI1LDEuMTQtLjgzLDEuNzEtMi4wMiwxLjcxLTMuNTdzLS41Ny0yLjgxLTEuNzEtMy42MWMtMS4xNC0uOC0yLjk1LTEuMi01LjQyLTEuMmgtMTAuMTl2MzQuMjhaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xMDI5Ljc4LDYyNi40OWMtNS4zMSwwLTEwLjIxLS44My0xNC42OC0yLjUtNC40OC0xLjY3LTguMzUtNC4wMy0xMS42My03LjA5LTMuMjctMy4wNi01LjgyLTYuNjUtNy42NC0xMC43OS0xLjgyLTQuMTQtMi43My04LjY1LTIuNzMtMTMuNTNzLjkxLTkuNDYsMi43My0xMy41N2MxLjgyLTQuMTEsNC4zNy03LjY5LDcuNjQtMTAuNzUsMy4yNy0zLjA2LDcuMTUtNS40MiwxMS42My03LjA5LDQuNDgtMS42Nyw5LjM0LTIuNSwxNC41OS0yLjVzMTAuMTkuODMsMTQuNjQsMi41YzQuNDUsMS42Nyw4LjMxLDQuMDMsMTEuNTgsNy4wOSwzLjI3LDMuMDYsNS44Miw2LjY0LDcuNjQsMTAuNzUsMS44Miw0LjExLDIuNzMsOC42MywyLjczLDEzLjU3cy0uOTEsOS4zOS0yLjczLDEzLjUzYy0xLjgyLDQuMTQtNC4zNyw3Ljc0LTcuNjQsMTAuNzktMy4yNywzLjA2LTcuMTMsNS40Mi0xMS41OCw3LjA5LTQuNDUsMS42Ny05LjMsMi41LTE0LjU0LDIuNVpNMTAyOS42OSw2MDguOGMyLjA0LDAsMy45NC0uMzcsNS43LTEuMTEsMS43Ni0uNzQsMy4zLTEuODEsNC42My0zLjIsMS4zMy0xLjM5LDIuMzYtMy4wOSwzLjEtNS4xLjc0LTIuMDEsMS4xMS00LjI4LDEuMTEtNi44MXMtLjM3LTQuOC0xLjExLTYuODFjLS43NC0yLjAxLTEuNzgtMy43MS0zLjEtNS4xLTEuMzMtMS4zOS0yLjg3LTIuNDUtNC42My0zLjItMS43Ni0uNzQtMy42Ni0xLjExLTUuNy0xLjExcy0zLjk0LjM3LTUuNywxLjExLTMuMywxLjgxLTQuNjMsMy4yYy0xLjMzLDEuMzktMi4zNiwzLjA5LTMuMSw1LjEtLjc0LDIuMDEtMS4xMSw0LjI4LTEuMTEsNi44MXMuMzcsNC44LDEuMTEsNi44MWMuNzQsMi4wMSwxLjc3LDMuNzEsMy4xLDUuMSwxLjMzLDEuMzksMi44NywyLjQ2LDQuNjMsMy4yczMuNjYsMS4xMSw1LjcsMS4xMVoiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTExMDIuMDQsNjI1LjAxdi02NC44NWgzMS45NmM3LjIzLDAsMTMuNTksMS4zMSwxOS4wOCwzLjk0LDUuNSwyLjYzLDkuNzksNi4zNSwxMi44OCwxMS4xNiwzLjA5LDQuODIsNC42MywxMC41Niw0LjYzLDE3LjIzcy0xLjU0LDEyLjUyLTQuNjMsMTcuMzdjLTMuMDksNC44NS03LjM4LDguNTktMTIuODgsMTEuMjEtNS41LDIuNjMtMTEuODYsMy45NC0xOS4wOCwzLjk0aC0zMS45NlpNMTEyMy45MSw2MDcuOTZoOS4xN2MzLjA5LDAsNS43OS0uNTksOC4xMS0xLjc2LDIuMzItMS4xNyw0LjEyLTIuOTIsNS40Mi01LjIzLDEuMy0yLjMyLDEuOTUtNS4xNCwxLjk1LTguNDhzLS42NS02LjA1LTEuOTUtOC4zNGMtMS4zLTIuMjgtMy4xLTQuMDEtNS40Mi01LjE5LTIuMzItMS4xNy01LjAyLTEuNzYtOC4xMS0xLjc2aC05LjE3djMwLjc2WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTIyMC4yNSw2MjUuMDF2LTI4LjQ0bDUsMTMuMDYtMjkuNDYtNDkuNDdoMjMuMDdsMTkuOTIsMzMuODFoLTEzLjQzbDIwLjEtMzMuODFoMjEuMTJsLTI5LjI3LDQ5LjQ3LDQuODItMTMuMDZ2MjguNDRoLTIxLjg2WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTM1Mi43Myw2MjUuMDF2LTY0Ljg1aDM0LjY1YzguOTYsMCwxNS41NiwxLjU5LDE5LjgzLDQuNzcsNC4yNiwzLjE4LDYuMzksNy4yNCw2LjM5LDEyLjE4LDAsMy4yNy0uOTEsNi4xOS0yLjczLDguNzUtMS44MiwyLjU2LTQuNDYsNC41OS03LjkyLDYuMDctMy40NiwxLjQ4LTcuNzIsMi4yMi0xMi43OSwyLjIybDEuODUtNWM1LjA2LDAsOS40My43MSwxMy4xMSwyLjEzLDMuNjcsMS40Miw2LjUyLDMuNDcsOC41Miw2LjE2LDIuMDEsMi42OSwzLjAxLDUuOTIsMy4wMSw5LjY4LDAsNS42Mi0yLjMzLDEwLTYuOTksMTMuMTYtNC42NiwzLjE1LTExLjQ3LDQuNzItMjAuNDMsNC43MmgtMzYuNVpNMTM3NC4yMiw2MDkuNzJoMTMuMTZjMi40MSwwLDQuMjItLjQzLDUuNDItMS4zLDEuMi0uODYsMS44MS0yLjEzLDEuODEtMy44cy0uNi0yLjkzLTEuODEtMy44Yy0xLjItLjg2LTMuMDEtMS4zLTUuNDItMS4zaC0xNC42NHYtMTQuNDVoMTEuNjdjMi40NywwLDQuMjgtLjQyLDUuNDItMS4yNSwxLjE0LS44MywxLjcxLTIuMDIsMS43MS0zLjU3cy0uNTctMi44MS0xLjcxLTMuNjFjLTEuMTQtLjgtMi45NS0xLjItNS40Mi0xLjJoLTEwLjE5djM0LjI4WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTQ0NS4wOSw2MjUuMDFsMjguMzUtNjQuODVoMjEuNDlsMjguMzUsNjQuODVoLTIyLjYxbC0yMC45NC01NC40N2g4LjUybC0yMC45NCw1NC40N2gtMjIuMjNaTTE0NjEuOTYsNjEzLjcxbDUuNTYtMTUuNzVoMjkuODNsNS41NiwxNS43NWgtNDAuOTVaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xNTU0LjYsNjI1LjAxdi02NC44NWgyMS44NnY0Ny45aDI5LjI4djE2Ljk1aC01MS4xNFoiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTE2MzMuNDQsNjI1LjAxbDI4LjM1LTY0Ljg1aDIxLjQ5bDI4LjM1LDY0Ljg1aC0yMi42MWwtMjAuOTQtNTQuNDdoOC41MmwtMjAuOTQsNTQuNDdoLTIyLjIzWk0xNjUwLjMsNjEzLjcxbDUuNTYtMTUuNzVoMjkuODNsNS41NiwxNS43NWgtNDAuOTVaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xNzQyLjk0LDYyNS4wMXYtNjQuODVoMTcuOTdsMzIuOTgsMzkuNDdoLTguMzR2LTM5LjQ3aDIxLjMxdjY0Ljg1aC0xNy45N2wtMzIuOTgtMzkuNDdoOC4zNHYzOS40N2gtMjEuMzFaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xODc4Ljc1LDYyNi40OWMtNS4xOSwwLTkuOTktLjgyLTE0LjQxLTIuNDYtNC40Mi0xLjY0LTguMjUtMy45Ny0xMS40OS03LTMuMjQtMy4wMi01Ljc2LTYuNjEtNy41NS0xMC43NS0xLjc5LTQuMTQtMi42OS04LjcxLTIuNjktMTMuNzFzLjg5LTkuNTcsMi42OS0xMy43MWMxLjc5LTQuMTQsNC4zMS03LjcyLDcuNTUtMTAuNzUsMy4yNC0zLjAzLDcuMDctNS4zNiwxMS40OS02Ljk5LDQuNDItMS42NCw5LjIyLTIuNDYsMTQuNDEtMi40Niw2LjM2LDAsMTIsMS4xMSwxNi45MSwzLjMzczguOTcsNS40NCwxMi4xOCw5LjYzbC0xMy44LDEyLjMyYy0xLjkyLTIuNDEtNC4wMy00LjI4LTYuMzUtNS42LTIuMzItMS4zMy00LjkzLTEuOTktNy44My0xLjk5LTIuMjksMC00LjM1LjM3LTYuMjEsMS4xMS0xLjg1Ljc0LTMuNDQsMS44Mi00Ljc3LDMuMjQtMS4zMywxLjQyLTIuMzYsMy4xNC0zLjEsNS4xNC0uNzQsMi4wMS0xLjExLDQuMjUtMS4xMSw2Ljcycy4zNyw0LjcxLDEuMTEsNi43MmMuNzQsMi4wMSwxLjc3LDMuNzIsMy4xLDUuMTQsMS4zMywxLjQyLDIuOTIsMi41LDQuNzcsMy4yNCwxLjg1Ljc0LDMuOTIsMS4xMSw2LjIxLDEuMTEsMi45LDAsNS41MS0uNjYsNy44My0xLjk5LDIuMzItMS4zMyw0LjQzLTMuMiw2LjM1LTUuNjFsMTMuOCwxMi4zMmMtMy4yMSw0LjE0LTcuMjcsNy4zMy0xMi4xOCw5LjU5cy0xMC41NSwzLjM4LTE2LjkxLDMuMzhaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xOTYzLjQzLDYwOC41MmgzMi40M3YxNi40OWgtNTMuOTJ2LTY0Ljg1aDUyLjcxdjE2LjQ5aC0zMS4yMnYzMS44N1pNMTk2MS45NCw1ODQuMjVoMjguOTF2MTUuNzVoLTI4Ljkxdi0xNS43NVoiLz4KICA8L2c+Cjwvc3ZnPg==" style="height:60px;width:auto" alt="Body Balance"></div>
  <h2>Вхід у систему</h2>
  <div class="role-tabs">
    <div class="role-tab active" onclick="setRole('admin')">Адмін</div>
    <div class="role-tab" onclick="setRole('reception')">Рецепція</div>
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
let currentRole = 'admin';
async function init() {
  const res = await fetch('/api/masters');
  const masters = await res.json();
  const sel = document.getElementById('masterSelect');
  sel.innerHTML = masters.map(m=>`<option value="${m.id}">${m.name}</option>`).join('');
}
function setRole(role) {
  currentRole = role;
  document.querySelectorAll('.role-tab').forEach((t,i)=>{
    t.classList.toggle('active', ['admin','reception','master'][i]===role);
  });
  document.getElementById('masterField').style.display = role==='master' ? 'block' : 'none';
}
async function doLogin() {
  const pwd = document.getElementById('pwd').value;
  const masterId = currentRole==='master' ? parseInt(document.getElementById('masterSelect').value) : null;
  const err = document.getElementById('errMsg');
  err.textContent = '';
  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({password: pwd, master_id: masterId})
    });
    if (res.ok) {
      window.location.href = '/';
    } else {
      const data = await res.json();
      err.textContent = data.detail || 'Невірний пароль';
    }
  } catch(e) {
    err.textContent = "Помилка з'єднання";
  }
}
init();
</script>
</body>
</html>
"""

HTML = r"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cosmo — розклад</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {
  --font-head: 'Montserrat', sans-serif;
  --font: 'Inter', sans-serif;
  --bg: #121214;
  --surface: #1E1E22;
  --surface2: #222227;
  --border: #2E2E36;
  --text: #E4E4E7;
  --muted: #A1A1AA;
  --hint: #71717A;
  --accent: #00C8B4;
  --accent-light: rgba(0,200,180,0.15);
  --accent-text: #00E5CE;
  --danger: #F87171;
  --danger-light: rgba(248,113,113,0.15);
  --success: #34D399;
  --success-light: rgba(52,211,153,0.12);
  --radius: 14px;
  --radius-sm: 8px;
  --shadow: 0 4px 12px rgba(0,0,0,.5);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; font-family: var(--font); background: var(--bg); color: var(--text); font-size: 14px; }
h1,h2,.sidebar-label,.date-label,.grid-header-cell,.m-tab,.topbar-title { font-family: var(--font-head); }

/* LAYOUT */
.app { display: flex; flex-direction: column; height: 100vh; }
.topbar {
  display: flex; align-items: center; gap: 16px;
  padding: 0 24px; height: 72px;
  background: var(--surface); border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.topbar h1 { font-size: 17px; font-weight: 700; letter-spacing: -.3px; }
.topbar h1 span { color: var(--accent); }
.spacer { flex: 1; }
.main { display: flex; flex: 1; overflow: hidden; }
.sidebar {
  width: 200px; flex-shrink: 0;
  background: var(--surface); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; overflow-y: auto;
  padding: 12px 8px;
}
.content { flex: 1; overflow: auto; padding: 16px; }

/* SIDEBAR */
.sidebar-section { margin-bottom: 20px; }
.sidebar-label { font-size: 11px; font-weight: 700; color: var(--hint); letter-spacing: .6px; text-transform: uppercase; padding: 0 8px; margin-bottom: 8px; }
.master-chip {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: var(--radius-sm);
  cursor: pointer; transition: background .12s;
  user-select: none;
}
.master-chip:hover { background: var(--bg); }
.master-chip.hidden { opacity: .4; }
.avatar {
  width: 28px; height: 28px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; flex-shrink: 0;
}
.master-chip-name { font-size: 13px; font-weight: 500; }

/* DATE NAV */
.date-nav { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
.date-nav button {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 5px 10px;
  cursor: pointer; font-family: var(--font); font-size: 13px;
  transition: background .12s;
}
.date-nav button:hover { background: var(--bg); }
.date-nav .today-btn { background: var(--accent); color: #121214; border-color: var(--accent); box-shadow: 0 0 14px rgba(0,200,180,.45); font-family: var(--font-head); font-weight: 700; }
.date-label { font-size: 15px; font-weight: 700; min-width: 160px; }
.add-btn {
  margin-left: auto;
  background: var(--accent); color: #121214; border: none; font-family: var(--font-head); font-weight: 700;
  border-radius: var(--radius-sm); padding: 7px 14px;
  cursor: pointer; font-family: var(--font); font-size: 13px; font-weight: 600;
  display: flex; align-items: center; gap: 5px; transition: opacity .12s;
}
.add-btn:hover { opacity: .88; }

/* GRID */
.schedule-wrap { background: var(--surface); border-radius: var(--radius); border: 1px solid var(--border); overflow-x: auto; }
.schedule-grid { display: grid; min-width: 500px; }
.grid-header { display: contents; }
.grid-header-cell {
  padding: 10px 8px; font-size: 12px; font-weight: 700; color: var(--muted);
  text-align: center; border-bottom: 1px solid var(--border);
  position: sticky; top: 0; background: var(--surface); z-index: 2;
}
.grid-header-cell .av { margin: 0 auto 4px; }
.time-col { font-size: 13px; color: var(--hint); text-align: right; padding: 0 8px 0 0; border-right: 1px solid var(--border); display: flex; align-items: flex-start; padding-top: 6px; }
.slot {
  border-right: 1px solid var(--border); border-bottom: 1px solid var(--border);
  min-height: 52px; position: relative; padding: 3px;
  transition: background .1s;
}
.slot:last-child { border-right: none; }
.slot.break-slot { background: repeating-linear-gradient(45deg, #2A2A30, #2A2A30 5px, #222227 5px, #222227 10px); }
.slot.break-slot::after { content: ''; display: block; }
.slot:not(.break-slot):hover { background: var(--accent-light); cursor: pointer; }
.time-row { display: contents; }
.time-row .time-col { border-bottom: 1px solid var(--border); }

.appt {
  border-radius: var(--radius-sm); padding: 4px 7px 4px 10px; height: 100%;
  display: flex; flex-direction: column; justify-content: center;
  cursor: pointer; transition: filter .15s, box-shadow .15s;
  border-left: 3px solid transparent;
  box-shadow: var(--shadow);
}
.appt:hover { filter: brightness(1.1); box-shadow: 0 6px 20px rgba(0,0,0,.6); }
.appt .aname { font-size: 14px; font-weight: 700; font-family: var(--font-head); }
.appt .asvc { font-size: 11px; opacity: .75; }
.appt .adur { font-size: 10px; opacity: .6; }

/* MODAL */
.overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.35);
  display: flex; align-items: center; justify-content: center;
  z-index: 100; padding: 16px;
}
.overlay.hidden { display: none; }
.modal {
  background: var(--surface); border-radius: var(--radius);
  padding: 24px; width: 100%; max-width: 420px;
  box-shadow: 0 8px 32px rgba(0,0,0,.15);
}
.modal h2 { font-size: 16px; font-weight: 700; margin-bottom: 16px; }
.form-row { margin-bottom: 12px; }
.form-row label { display: block; font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 4px; }
.form-row input, .form-row select, .form-row textarea {
  width: 100%; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: var(--radius-sm); font-family: var(--font); font-size: 14px;
  background: var(--bg); color: var(--text); outline: none;
  transition: border-color .12s;
}
.form-row input:focus, .form-row select:focus, .form-row textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(0,200,180,.2); }
.form-row textarea { resize: vertical; min-height: 60px; }
.form-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.modal-footer { display: flex; gap: 8px; margin-top: 16px; justify-content: flex-end; }
.btn { padding: 8px 16px; border-radius: var(--radius-sm); cursor: pointer; font-family: var(--font); font-size: 13px; font-weight: 600; border: 1px solid var(--border); background: var(--surface); transition: background .12s; }
.btn:hover { background: var(--bg); }
.btn-primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.btn-primary:hover { opacity: .88; background: var(--accent); }
.btn-danger { background: var(--danger-light); color: var(--danger); border-color: #F0997B; }
.error-msg { font-size: 12px; color: var(--danger); margin-top: 8px; }

/* DETAIL MODAL */
.detail-row { display: flex; gap: 8px; margin-bottom: 8px; align-items: baseline; }
.detail-row .dl { font-size: 12px; color: var(--muted); min-width: 90px; }
.detail-row .dv { font-size: 14px; font-weight: 500; }
.detail-color-bar { height: 4px; border-radius: 2px; margin-bottom: 16px; }

/* MOBILE */
.mobile-view { display: none; flex-direction: column; height: 100%; }
.m-tabs { display: flex; overflow-x: auto; border-bottom: 1px solid var(--border); background: var(--surface); flex-shrink: 0; }
.m-tab {
  padding: 10px 14px; font-size: 13px; font-weight: 600; color: var(--muted);
  cursor: pointer; white-space: nowrap; border-bottom: 2px solid transparent;
  flex-shrink: 0;
}
.m-tab.active { color: var(--accent); border-bottom-color: var(--accent); font-family: var(--font-head); }
.m-list { flex: 1; overflow-y: auto; padding: 12px; }
.m-slot { display: flex; gap: 10px; margin-bottom: 10px; align-items: flex-start; }
.m-time { font-size: 12px; color: var(--hint); min-width: 40px; padding-top: 6px; }
.m-card { flex: 1; border-radius: var(--radius-sm); padding: 8px 10px; cursor: pointer; }
.m-card .mc-name { font-size: 13px; font-weight: 700; }
.m-card .mc-svc { font-size: 12px; opacity: .75; }
.m-card .mc-dur { font-size: 11px; opacity: .6; }
.m-empty { font-size: 12px; color: var(--hint); font-style: italic; padding: 6px 10px; }
.m-fab-wrap { padding: 10px 12px; background: var(--surface); border-top: 1px solid var(--border); flex-shrink: 0; }
.m-fab { width: 100%; padding: 11px; background: var(--accent); color: #121214; border: none; border-radius: var(--radius); font-family: var(--font); font-size: 14px; font-weight: 700; cursor: pointer; }

/* TOAST */
.toast {
  position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
  background: #1A1916; color: #fff; padding: 10px 20px; border-radius: 20px;
  font-size: 13px; font-weight: 500; z-index: 200; opacity: 0;
  transition: opacity .2s; pointer-events: none;
}
.toast.show { opacity: 1; }

@media (max-width: 600px) {
  .app > .topbar .desktop-only { display: none; }
  .main { display: none; }
  .mobile-view { display: flex; }
}
</style>
</head>
<body>
<div class="app">

<div class="topbar">
  <div style="cursor:pointer;height:56px;display:flex;align-items:center" onclick="showAllMasters()" title="Усі майстри">
  <img src="data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyBpZD0iTGF5ZXJfMSIgZGF0YS1uYW1lPSJMYXllciAxIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyMTUzIDEwODAiPgogIDxkZWZzPgogICAgPHN0eWxlPgogICAgICAuY2xzLTEgewogICAgICAgIGZpbGw6ICMwZGUwZDY7CiAgICAgIH0KCiAgICAgIC5jbHMtMiB7CiAgICAgICAgZmlsbDogI2UzZTRlODsKICAgICAgfQogICAgPC9zdHlsZT4KICA8L2RlZnM+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMzg0LjIzLDIxNC45OWMtMTAuODEtNS41NS0xMC44MSw0Mi4zMS0xMC44MSw0Mi4zMS0xMC44MSwyNS45NS0yMS42MiwyOC4xMS0yMS42MiwyOC4xMS0xMi45Ny04LjY1LTEwLjgxLTQ3LjU3LTEwLjgxLTQ3LjU3LTE1LjE0LTU2LjIyLDQzLjI0LTU4LjM4LDQzLjI0LTU4LjM4LDAsMC0yMS42Mi04LjY1LTM4LjkyLDYuNDktMjMuMDEsMjAuMTQtMTcuMyw2Mi43LTguNjUsODguNjUsOC42NSwyNS45NSwyMS42MiwxNS4xNCwyMS42MiwxNS4xNC0xMi45NywxNy4zLTI1Ljk1LDEyLjk3LTI1Ljk1LDEyLjk3LTI4LjExLTYuNDktMzguOTItMi4xNi0zOC45Mi0yLjE2LTMwLjI3LDEyLjk3LTIxLjYyLDY3LjAzLTE1LjE0LDg4LjY1LDYuNDksMjEuNjIsMzIuNDMsOTIuOTcsMzIuNDMsOTIuOTctOC42NSw2LjQ5LTE5LjQ2LDI1Ljk1LTE1LjE0LDQxLjA4LDQuMzIsMTUuMTQsMjUuOTUsMzIuNDMsMzYuNzYsMjEuNjIsMTAuODEtMTAuODEtOC42NS00Ny41Ny04LjY1LTQ3LjU3bC0yNC40Ni02Mi42NmMtMS4xNi0zLjQxLTIuMTYtNi44Ni0yLjk4LTEwLjM3LTMuMjEtMTMuNjctMjIuMjktNzEuODMtMTEuNDgtOTcuNzgsMTEuMDktMjYuNjMsNDcuNTctMTcuMyw0Ny41Ny0xNy4zLDQxLjA4LDguNjUsNDkuNzMtNDkuNzMsNDkuNzMtNDkuNzMsMTAuODEtMTAuODEsMTIuOTctMzguOTIsMi4xNi00NC40N1pNMzIxLjUzLDUyMS4wOGMwLDEwLjgxLDAsMTUuMTQtNi40OSwxMi45N3MtMTQuNDQtMTQuOTktMTIuOTctMjMuNzhjMi4xNi0xMi45NywxMC44MS0yMS42MiwxMC44MS0yMS42MiwwLDAsOC42NSwyMS42Miw4LjY1LDMyLjQzWiIvPgogIDxwYXRoIGNsYXNzPSJjbHMtMSIgZD0iTTM4My44NSwyNjkuMjlzLTQuMzIsMzAuMjctMjMuNzgsNjQuODZjLTE5LjQ2LDM0LjU5LTQ2LjQ5LDgzLjI0LTQ2LjQ5LDE1MC4yN2w0LjMyLTQuMzIsNC4zMi00LjMyczIuMTYtMTIuOTcsOC42NS00My4yNGM2LjQ5LTMwLjI3LDI3LjAzLTYzLjc4LDQxLjA4LTkyLjk3LDEyLjIzLTI1LjQsMTQuMDUtNTIuOTcsMTEuODktNzAuMjdaIi8+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMzMxLjY1LDg3OC42NHM1Ni45MS0xMDYuNzUsNzIuMDQtMTM5LjE4YzE1LjE0LTMyLjQzLDQwLTExMS4zNSwzMi40My0xNjAtNi44NS00NC4wNC0yMC41NC03Ni43Ni01Mi45Ny04OS43My0zMS4xNi0xMi40Ny02MS42Mi05LjczLTcwLjI3LTEuMDhsLTIuMTYtNi40OXMyNS4wMy0yMS42Miw4MC42Mi01LjQxYzU1LjU5LDE2LjIyLDcxLjgxLDg2LjQ5LDcxLjgxLDExNC41OSwwLDMxLjMtMy44OSwxMDAuMTgtNDMuMjQsMTYyLjE2LTQwLjU1LDYzLjg2LTg4LjI2LDEyNS4xMy04OC4yNiwxMjUuMTNaIi8+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMzIyLjIzLDQ3Ny45M3MtNS40MS0yOS4xOSwxOC4zOC00MGMyMy43OC0xMC44MSw4Ny41Ny0xMS44OSw5Ny4zLTY5LjE5LDExLjQ2LTY3LjQ5LTQ5LjExLTYzLjUxLTQ5LjExLTYzLjUxLDAsMCw1NC41OS0yOC41Nyw3MS44MSwyOS45OSwxMC44MSwzNi43Ni0xMi45Nyw4Ni40OS03MS4zNSw5OS40Ni01My4wNywxMS43OS01NC4wNSwxNS4xNC02Ny4wMyw0My4yNFoiLz4KICA8cGF0aCBjbGFzcz0iY2xzLTEiIGQ9Ik04MDYsNzM4YzU4LDQwLDExNy4yOSw1OS4xOCwxNDQsNjksMTY2LDYxLDMyMiw3NCwzMjIsNzQsNTQwLDcyLDY4MC4wMi0xMDYuODksNjgwLjAyLTEwNi44OS0yMzAuOTgsMTU2LjExLTc5Ni45Nyw1My4wMS05MDIuMDIsMzAuODktMzgtOC0xMTUtMjUtMjMyLTgzIi8+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNODIzLjEsNzU1LjA0Yy0yNi4zMywyNy43NS02MS4yOSw0OS4wMy0xMDQuODksNjMuODMtMzcuNDMsMTIuNDktNzYuOTIsMTguNzMtMTE4LjQ2LDE4LjczLTI3LjE1LDAtNTMuMjctNi4wMi03OC4zNi0xOC4wNC0zMi4wOC0xNS4yNi00OC4xMy0zNi4zMS00OC4xMy02My4xNCwwLTMwLjk4LDEzLjE2LTU2LjQzLDM5LjQ5LTc2LjMyLDExLjkyLTguNzgsMjQuMjctMTUuMzcsMzcuMDItMTkuNzcsMTIuNzUtNC4zOSwyNi4xMi03LjA1LDQwLjExLTcuOTgsNi45OS0xOC41LDE1LjczLTQwLjAxLDI2LjIyLTY0LjUzLDEwLjQ5LTI0LjUxLDIxLjYyLTQ2LjAyLDMxLjkxLTY3LjMsMy4yOS02LjQ3LDgtMTYsMTQtMjYsMTAuMjktMTcuMTYsMjAtMzEsMjQtMzUsMTcuNTEtMTcuNTEsMzYtMTUsMzYtMTUsMCwwLTIuOTksMi4yNC0xMy40OCwxNS43Ni0zLjU0LDQuNTUtNi44OCw5LjI3LTkuOTksMTQuMTMtMzUuODMsNTUuOTUtNTYuMDcsMTA2LjM5LTg3LjY4LDE3Ny45NCw5Mi41NSwxLjg1LDE2MS40NCwyNS4yMiwyMDYuNyw3MC4wOCwxMy4xNi0xOS44OCwxOS43NC0zOC4xNiwxOS43NC01NC44MSwwLTI5LjE0LTE3LjQ5LTUyLjA0LTUyLjQ1LTY4LjY5LTE1LjE2LTYuOTctNTAuMDEtMTcuNDgtNzYuODQtMjIuNC0yMS4yMi0zLjg5LTI3LTUtMjctNSwwLDAsOC45NC0zLjE5LDIxLTcsMTktNiwyNi04LDM3LTEyLDQ1LjY0LTE2LjYsNzEuNjEtMjkuMDIsOTMuOTctNTIuODIsOS40Ni05LjcxLDE0LjE5LTE4LjUsMTQuMTktMjYuMzcsMC0xNi42NS0xOS4xMy0yOS4xNC01Ny4zOC0zNy40Ny0yNS45MS01LjU1LTUyLjY2LTguMzMtODAuMjEtOC4zMy03My42NCwwLTE0MC45OSwxMC45Mi0yMDUuNTcsNDAuOTgtMi40Ny45My0xNiw5LTE2LDksMCwwLDguMzMtMTEuMzMsMTUtMTgsOS05LDE5LTE3LDMzLTI0LDQyLjc4LTE5LjQzLDc3LjcyLTI4LjEsMTQzLjk1LTI4LjEsMzkuNDksMCw3Ni4wOSw0LjE2LDEwOS44MywxMi40OSw1Mi42NSwxMi40OSw3OC45OCwzMi4zOCw3OC45OCw1OS42NywwLDIyLjItMTYuMDQsNDIuMzMtNDguMTMsNjAuMzctMjMuNDUsMTMuNDItNDguMzQsMjIuNjctNzQuNjYsMjcuNzUsMjkuMiw3LjQxLDU0LjMsMTguMjgsNzUuMjcsMzIuNjEsMjguNzksMTkuNDMsNDMuMTksNDIuNzksNDMuMTksNzAuMDgsMCwyMi4yLTEwLjA4LDQ2LjAzLTMwLjIzLDcxLjQ3TTU2MC44Nyw4MDguNDdjLS44Ny4wNS0zLjg3LTkuNDYtMy44Ny0yMS45NSwwLTIwLjgyLDQuNDktNTYuNjksMjUuNDYtMTE0LjA1LTU0LjcxLDEwLjE4LTgyLjA2LDM4LjYzLTgyLjA2LDg1LjM0LDAsMjAuODIsMTIuNTQsMzcuNDcsMzcuNjQsNDkuOTYsMTkuNzQsOS43MSw0MC4zMSwxNC41Nyw2MS43LDE0LjU3LDkxLjMyLDAsMTYwLjIxLTI4LjIxLDIwNi43LTg0LjY1LTIzLjA0LTIxLjc0LTUyLjA0LTM4Ljg2LTg3LTUxLjM1LTMyLjUtMTEuNTYtNjUuMi0xNy4zNS05OC4xLTE3LjM1aC04Ljk1Yy0zLjA4LDAtNi4wNy4yNC04Ljk1LjY5LTI0LjY4LDU4Ljc1LTQyLjQ0LDExOC40OC00Mi40NCwxMzguODMiLz4KICA8Zz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTg5Ni4yOCw2MjUuMDF2LTY0Ljg1aDM0LjY1YzguOTYsMCwxNS41NiwxLjU5LDE5LjgzLDQuNzcsNC4yNiwzLjE4LDYuMzksNy4yNCw2LjM5LDEyLjE4LDAsMy4yNy0uOTEsNi4xOS0yLjczLDguNzUtMS44MiwyLjU2LTQuNDYsNC41OS03LjkyLDYuMDctMy40NiwxLjQ4LTcuNzIsMi4yMi0xMi43OSwyLjIybDEuODUtNWM1LjA2LDAsOS40My43MSwxMy4xMSwyLjEzLDMuNjcsMS40Miw2LjUyLDMuNDcsOC41Miw2LjE2LDIuMDEsMi42OSwzLjAxLDUuOTIsMy4wMSw5LjY4LDAsNS42Mi0yLjMzLDEwLTYuOTksMTMuMTYtNC42NiwzLjE1LTExLjQ3LDQuNzItMjAuNDMsNC43MmgtMzYuNVpNOTE3Ljc4LDYwOS43MmgxMy4xNmMyLjQxLDAsNC4yMi0uNDMsNS40Mi0xLjMsMS4yLS44NiwxLjgxLTIuMTMsMS44MS0zLjhzLS42LTIuOTMtMS44MS0zLjhjLTEuMi0uODYtMy4wMS0xLjMtNS40Mi0xLjNoLTE0LjY0di0xNC40NWgxMS42N2MyLjQ3LDAsNC4yOC0uNDIsNS40Mi0xLjI1LDEuMTQtLjgzLDEuNzEtMi4wMiwxLjcxLTMuNTdzLS41Ny0yLjgxLTEuNzEtMy42MWMtMS4xNC0uOC0yLjk1LTEuMi01LjQyLTEuMmgtMTAuMTl2MzQuMjhaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xMDI5Ljc4LDYyNi40OWMtNS4zMSwwLTEwLjIxLS44My0xNC42OC0yLjUtNC40OC0xLjY3LTguMzUtNC4wMy0xMS42My03LjA5LTMuMjctMy4wNi01LjgyLTYuNjUtNy42NC0xMC43OS0xLjgyLTQuMTQtMi43My04LjY1LTIuNzMtMTMuNTNzLjkxLTkuNDYsMi43My0xMy41N2MxLjgyLTQuMTEsNC4zNy03LjY5LDcuNjQtMTAuNzUsMy4yNy0zLjA2LDcuMTUtNS40MiwxMS42My03LjA5LDQuNDgtMS42Nyw5LjM0LTIuNSwxNC41OS0yLjVzMTAuMTkuODMsMTQuNjQsMi41YzQuNDUsMS42Nyw4LjMxLDQuMDMsMTEuNTgsNy4wOSwzLjI3LDMuMDYsNS44Miw2LjY0LDcuNjQsMTAuNzUsMS44Miw0LjExLDIuNzMsOC42MywyLjczLDEzLjU3cy0uOTEsOS4zOS0yLjczLDEzLjUzYy0xLjgyLDQuMTQtNC4zNyw3Ljc0LTcuNjQsMTAuNzktMy4yNywzLjA2LTcuMTMsNS40Mi0xMS41OCw3LjA5LTQuNDUsMS42Ny05LjMsMi41LTE0LjU0LDIuNVpNMTAyOS42OSw2MDguOGMyLjA0LDAsMy45NC0uMzcsNS43LTEuMTEsMS43Ni0uNzQsMy4zLTEuODEsNC42My0zLjIsMS4zMy0xLjM5LDIuMzYtMy4wOSwzLjEtNS4xLjc0LTIuMDEsMS4xMS00LjI4LDEuMTEtNi44MXMtLjM3LTQuOC0xLjExLTYuODFjLS43NC0yLjAxLTEuNzgtMy43MS0zLjEtNS4xLTEuMzMtMS4zOS0yLjg3LTIuNDUtNC42My0zLjItMS43Ni0uNzQtMy42Ni0xLjExLTUuNy0xLjExcy0zLjk0LjM3LTUuNywxLjExLTMuMywxLjgxLTQuNjMsMy4yYy0xLjMzLDEuMzktMi4zNiwzLjA5LTMuMSw1LjEtLjc0LDIuMDEtMS4xMSw0LjI4LTEuMTEsNi44MXMuMzcsNC44LDEuMTEsNi44MWMuNzQsMi4wMSwxLjc3LDMuNzEsMy4xLDUuMSwxLjMzLDEuMzksMi44NywyLjQ2LDQuNjMsMy4yczMuNjYsMS4xMSw1LjcsMS4xMVoiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTExMDIuMDQsNjI1LjAxdi02NC44NWgzMS45NmM3LjIzLDAsMTMuNTksMS4zMSwxOS4wOCwzLjk0LDUuNSwyLjYzLDkuNzksNi4zNSwxMi44OCwxMS4xNiwzLjA5LDQuODIsNC42MywxMC41Niw0LjYzLDE3LjIzcy0xLjU0LDEyLjUyLTQuNjMsMTcuMzdjLTMuMDksNC44NS03LjM4LDguNTktMTIuODgsMTEuMjEtNS41LDIuNjMtMTEuODYsMy45NC0xOS4wOCwzLjk0aC0zMS45NlpNMTEyMy45MSw2MDcuOTZoOS4xN2MzLjA5LDAsNS43OS0uNTksOC4xMS0xLjc2LDIuMzItMS4xNyw0LjEyLTIuOTIsNS40Mi01LjIzLDEuMy0yLjMyLDEuOTUtNS4xNCwxLjk1LTguNDhzLS42NS02LjA1LTEuOTUtOC4zNGMtMS4zLTIuMjgtMy4xLTQuMDEtNS40Mi01LjE5LTIuMzItMS4xNy01LjAyLTEuNzYtOC4xMS0xLjc2aC05LjE3djMwLjc2WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTIyMC4yNSw2MjUuMDF2LTI4LjQ0bDUsMTMuMDYtMjkuNDYtNDkuNDdoMjMuMDdsMTkuOTIsMzMuODFoLTEzLjQzbDIwLjEtMzMuODFoMjEuMTJsLTI5LjI3LDQ5LjQ3LDQuODItMTMuMDZ2MjguNDRoLTIxLjg2WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTM1Mi43Myw2MjUuMDF2LTY0Ljg1aDM0LjY1YzguOTYsMCwxNS41NiwxLjU5LDE5LjgzLDQuNzcsNC4yNiwzLjE4LDYuMzksNy4yNCw2LjM5LDEyLjE4LDAsMy4yNy0uOTEsNi4xOS0yLjczLDguNzUtMS44MiwyLjU2LTQuNDYsNC41OS03LjkyLDYuMDctMy40NiwxLjQ4LTcuNzIsMi4yMi0xMi43OSwyLjIybDEuODUtNWM1LjA2LDAsOS40My43MSwxMy4xMSwyLjEzLDMuNjcsMS40Miw2LjUyLDMuNDcsOC41Miw2LjE2LDIuMDEsMi42OSwzLjAxLDUuOTIsMy4wMSw5LjY4LDAsNS42Mi0yLjMzLDEwLTYuOTksMTMuMTYtNC42NiwzLjE1LTExLjQ3LDQuNzItMjAuNDMsNC43MmgtMzYuNVpNMTM3NC4yMiw2MDkuNzJoMTMuMTZjMi40MSwwLDQuMjItLjQzLDUuNDItMS4zLDEuMi0uODYsMS44MS0yLjEzLDEuODEtMy44cy0uNi0yLjkzLTEuODEtMy44Yy0xLjItLjg2LTMuMDEtMS4zLTUuNDItMS4zaC0xNC42NHYtMTQuNDVoMTEuNjdjMi40NywwLDQuMjgtLjQyLDUuNDItMS4yNSwxLjE0LS44MywxLjcxLTIuMDIsMS43MS0zLjU3cy0uNTctMi44MS0xLjcxLTMuNjFjLTEuMTQtLjgtMi45NS0xLjItNS40Mi0xLjJoLTEwLjE5djM0LjI4WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTQ0NS4wOSw2MjUuMDFsMjguMzUtNjQuODVoMjEuNDlsMjguMzUsNjQuODVoLTIyLjYxbC0yMC45NC01NC40N2g4LjUybC0yMC45NCw1NC40N2gtMjIuMjNaTTE0NjEuOTYsNjEzLjcxbDUuNTYtMTUuNzVoMjkuODNsNS41NiwxNS43NWgtNDAuOTVaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xNTU0LjYsNjI1LjAxdi02NC44NWgyMS44NnY0Ny45aDI5LjI4djE2Ljk1aC01MS4xNFoiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTE2MzMuNDQsNjI1LjAxbDI4LjM1LTY0Ljg1aDIxLjQ5bDI4LjM1LDY0Ljg1aC0yMi42MWwtMjAuOTQtNTQuNDdoOC41MmwtMjAuOTQsNTQuNDdoLTIyLjIzWk0xNjUwLjMsNjEzLjcxbDUuNTYtMTUuNzVoMjkuODNsNS41NiwxNS43NWgtNDAuOTVaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xNzQyLjk0LDYyNS4wMXYtNjQuODVoMTcuOTdsMzIuOTgsMzkuNDdoLTguMzR2LTM5LjQ3aDIxLjMxdjY0Ljg1aC0xNy45N2wtMzIuOTgtMzkuNDdoOC4zNHYzOS40N2gtMjEuMzFaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xODc4Ljc1LDYyNi40OWMtNS4xOSwwLTkuOTktLjgyLTE0LjQxLTIuNDYtNC40Mi0xLjY0LTguMjUtMy45Ny0xMS40OS03LTMuMjQtMy4wMi01Ljc2LTYuNjEtNy41NS0xMC43NS0xLjc5LTQuMTQtMi42OS04LjcxLTIuNjktMTMuNzFzLjg5LTkuNTcsMi42OS0xMy43MWMxLjc5LTQuMTQsNC4zMS03LjcyLDcuNTUtMTAuNzUsMy4yNC0zLjAzLDcuMDctNS4zNiwxMS40OS02Ljk5LDQuNDItMS42NCw5LjIyLTIuNDYsMTQuNDEtMi40Niw2LjM2LDAsMTIsMS4xMSwxNi45MSwzLjMzczguOTcsNS40NCwxMi4xOCw5LjYzbC0xMy44LDEyLjMyYy0xLjkyLTIuNDEtNC4wMy00LjI4LTYuMzUtNS42LTIuMzItMS4zMy00LjkzLTEuOTktNy44My0xLjk5LTIuMjksMC00LjM1LjM3LTYuMjEsMS4xMS0xLjg1Ljc0LTMuNDQsMS44Mi00Ljc3LDMuMjQtMS4zMywxLjQyLTIuMzYsMy4xNC0zLjEsNS4xNC0uNzQsMi4wMS0xLjExLDQuMjUtMS4xMSw2Ljcycy4zNyw0LjcxLDEuMTEsNi43MmMuNzQsMi4wMSwxLjc3LDMuNzIsMy4xLDUuMTQsMS4zMywxLjQyLDIuOTIsMi41LDQuNzcsMy4yNCwxLjg1Ljc0LDMuOTIsMS4xMSw2LjIxLDEuMTEsMi45LDAsNS41MS0uNjYsNy44My0xLjk5LDIuMzItMS4zMyw0LjQzLTMuMiw2LjM1LTUuNjFsMTMuOCwxMi4zMmMtMy4yMSw0LjE0LTcuMjcsNy4zMy0xMi4xOCw5LjU5cy0xMC41NSwzLjM4LTE2LjkxLDMuMzhaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xOTYzLjQzLDYwOC41MmgzMi40M3YxNi40OWgtNTMuOTJ2LTY0Ljg1aDUyLjcxdjE2LjQ5aC0zMS4yMnYzMS44N1pNMTk2MS45NCw1ODQuMjVoMjguOTF2MTUuNzVoLTI4Ljkxdi0xNS43NVoiLz4KICA8L2c+Cjwvc3ZnPg==" style="height:56px;width:auto;object-fit:contain" alt="Body Balance">
</div>
  <div class="spacer"></div>
  <div class="desktop-only" style="text-align:right;line-height:1.4">
  <div style="font-family:'Montserrat',sans-serif;font-size:13px;font-weight:600;color:#E4E4E7;letter-spacing:.3px">Краса — це мистецтво.</div>
  <div style="font-family:'Inter',sans-serif;font-size:11px;color:#00C8B4;letter-spacing:.5px">Ми створюємо його щодня</div>
</div>
<div style="display:flex;align-items:center;gap:8px;margin-left:12px">
  <span id="roleBadge" style="display:none;font-size:11px;font-weight:700;font-family:'Montserrat',sans-serif;background:rgba(0,200,180,.15);color:#00C8B4;padding:3px 10px;border-radius:20px;border:1px solid rgba(0,200,180,.3)"></span>
  <button id="logoutBtn" onclick="doLogout()" style="display:none;background:rgba(248,113,113,.12);border:1px solid rgba(248,113,113,.3);border-radius:7px;padding:5px 12px;color:#F87171;font-family:'Montserrat',sans-serif;font-size:12px;font-weight:600;cursor:pointer">Вийти</button>
</div>
</div>

<!-- DESKTOP -->
<div class="main">
  <aside class="sidebar">
    <div class="sidebar-section">
      <div class="sidebar-label" style="font-family:'Montserrat',sans-serif">Майстри</div>
      <div id="allMastersChip" onclick="showAllMasters()" style="display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:8px;cursor:pointer;margin-bottom:4px;background:var(--accent-light);border:1px solid rgba(0,200,180,.3)">
        <div style="width:28px;height:28px;border-radius:50%;background:rgba(0,200,180,.2);display:flex;align-items:center;justify-content:center;font-size:14px">⊞</div>
        <span style="font-size:13px;font-weight:600;color:var(--accent);font-family:'Montserrat',sans-serif">Усі майстри</span>
      </div>
      <div id="masterList"></div>
    </div>
    <div style="margin-top:auto;padding-top:12px;border-top:1px solid var(--border)">
      <div id="settingsBtn" onclick="openSettingsModalFull()" style="display:flex;align-items:center;gap:8px;padding:8px 8px;border-radius:8px;cursor:pointer;transition:background .12s" onmouseover="this.style.background='var(--surface2)'" onmouseout="this.style.background=''">
        <div style="width:28px;height:28px;border-radius:50%;background:rgba(255,255,255,.06);display:flex;align-items:center;justify-content:center;font-size:16px">⚙️</div>
        <span style="font-size:13px;font-weight:500;color:var(--muted);font-family:'Montserrat',sans-serif">Налаштування</span>
      </div>
    </div>
  </aside>
  <div class="content">
    <div class="date-nav">
      <button onclick="changeDate(-1)">‹</button>
      <input type="date" id="datePicker" onchange="pickDate(this.value)" style="padding:5px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);font-family:var(--font);font-size:13px;background:var(--surface2);color:var(--text);cursor:pointer;color-scheme:dark;">
      <button onclick="changeDate(1)">›</button>
      <button class="today-btn" onclick="goToday()">Сьогодні</button>
      <span class="date-label" id="dateLabel"></span>
      <button class="add-btn" onclick="openAddModal()">+ Новий запис клієнта</button>
    </div>
    <div class="schedule-wrap">
      <div class="schedule-grid" id="scheduleGrid"></div>
    </div>
  </div>
</div>

<!-- MOBILE -->
<div class="mobile-view">
  <div class="m-tabs" id="mobileTabs"></div>
  <div class="m-list" id="mobileList"></div>
  <div class="m-fab-wrap">
    <button class="m-fab" onclick="openAddModal()">+ Новий запис</button>
  </div>
</div>

</div><!-- .app -->

<!-- MODAL: ADD/EDIT -->
<div class="overlay hidden" id="modalOverlay">
  <div class="modal">
    <h2 id="modalTitle">Новий запис</h2>
    <div class="form-row">
      <label>Майстер</label>
      <select id="fMaster"></select>
    </div>
    <div class="form-row">
      <label>Ім'я клієнта</label>
      <input id="fClient" type="text" placeholder="Ім'я та прізвище">
    </div>
    <div class="form-row">
      <label>Послуга</label>
      <input id="fService" type="text" placeholder="Масаж обличчя, ботокс...">
    </div>
    <div class="form-2col">
      <div class="form-row">
        <label>Дата</label>
        <input id="fDate" type="date">
      </div>
      <div class="form-row">
        <label>Час</label>
        <input id="fTime" type="time">
      </div>
    </div>
    <div class="form-row">
      <label>Тривалість (хв)</label>
      <select id="fDuration">
        <option value="30">30 хв</option>
        <option value="45">45 хв</option>
        <option value="60" selected>60 хв</option>
        <option value="90">90 хв</option>
        <option value="120">120 хв</option>
      </select>
    </div>
    <div class="form-row">
      <label>Нотатки</label>
      <textarea id="fNotes" placeholder="Додаткова інформація..."></textarea>
    </div>
    <div class="error-msg hidden" id="formError"></div>
    <div class="modal-footer">
      <button class="btn btn-danger hidden" id="deleteBtn" onclick="deleteAppt()">Видалити</button>
      <button class="btn" onclick="closeModal()">Скасувати</button>
      <button class="btn btn-primary" onclick="saveAppt()">Зберегти</button>
    </div>
  </div>
</div>

<!-- MODAL: DETAIL VIEW -->
<div class="overlay hidden" id="detailOverlay">
  <div class="modal">
    <div class="detail-color-bar" id="detailBar"></div>
    <h2 id="detailName"></h2>
    <div id="detailBody"></div>
    <div class="modal-footer">
      <button class="btn" onclick="closeDetail()">Закрити</button>
      <button class="btn btn-primary" id="detailEditBtn">Редагувати</button>
    </div>
  </div>
</div>

<!-- MODAL: SETTINGS / MASTERS EDITOR -->
<div class="overlay hidden" id="settingsOverlay">
  <div class="modal" style="max-width:520px;max-height:80vh;overflow-y:auto">
    <div style="display:flex;gap:8px;margin-bottom:16px">
      <button onclick="showSettingsTab('masters')" id="tabMasters" style="flex:1;padding:8px;border-radius:8px;border:none;background:var(--accent);color:#121214;font-family:'Montserrat',sans-serif;font-size:12px;font-weight:700;cursor:pointer">👥 Майстри</button>
      <button onclick="showSettingsTab('passwords')" id="tabPasswords" style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--border);background:transparent;color:var(--muted);font-family:'Montserrat',sans-serif;font-size:12px;font-weight:600;cursor:pointer">🔑 Паролі</button>
    </div>
    <div id="settingsTabMasters">
    <h2 style="font-family:'Montserrat',sans-serif;margin-bottom:16px">👥 Майстри</h2>
    <div id="masterEditList" style="margin-bottom:16px"></div>
    <button class="btn" style="width:100%;margin-bottom:8px;border-style:dashed;color:var(--accent);border-color:var(--accent)" onclick="addNewMasterRow()">+ Додати майстра</button>
    </div>
    <div id="settingsTabPasswords" style="display:none">
    <h2 style="font-family:'Montserrat',sans-serif;margin-bottom:16px">🔑 Паролі входу</h2>
    <div style="margin-bottom:12px">
      <label style="font-size:12px;font-weight:600;color:var(--muted);display:block;margin-bottom:4px">Пароль адміна</label>
      <input id="pwdAdmin" type="text" style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:var(--font);font-size:13px">
    </div>
    <div style="margin-bottom:12px">
      <label style="font-size:12px;font-weight:600;color:var(--muted);display:block;margin-bottom:4px">Пароль рецепції</label>
      <input id="pwdReception" type="text" style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:var(--font);font-size:13px">
    </div>
    <div id="masterPasswordsList" style="margin-bottom:12px"></div>
    </div>
    <div class="modal-footer">
      <button class="btn" onclick="closeSettings()">Закрити</button>
      <button class="btn btn-primary" onclick="saveAllSettings()">Зберегти зміни</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const HOURS = Array.from({length:10}, (_,i) => `${String(i+9).padStart(2,'0')}:00`);
const DURATIONS = [30,45,60,90,120];

let masters = [], appointments = [], breaks = [];
let currentDate = new Date();
let visibleMasters = new Set();
let editingId = null;
let mobileMasterId = null;

function isoDate(d) {
  return d.toISOString().slice(0,10);
}

function formatDateUa(iso) {
  const [y,m,day] = iso.split('-');
  const months = ['','січня','лютого','березня','квітня','травня','червня',
    'липня','серпня','вересня','жовтня','листопада','грудня'];
  const days = ['неділя','понеділок','вівторок','середа','четвер','п\'ятниця','субота'];
  const d = new Date(iso);
  return `${parseInt(day)} ${months[parseInt(m)]}, ${days[d.getDay()]}`;
}

function toMin(t) { const [h,m] = t.split(':').map(Number); return h*60+m; }

function lighten(hex) {
  // dark pastel palettes for dark theme
  const palettes = {
    '#7F77DD': {bg:'rgba(110,68,255,0.15)', text:'#A78BFA', border:'#7C3AED'},
    '#1D9E75': {bg:'rgba(52,211,153,0.12)', text:'#34D399', border:'#059669'},
    '#BA7517': {bg:'rgba(251,191,36,0.12)', text:'#FCD34D', border:'#D97706'},
    '#D85A30': {bg:'rgba(248,113,113,0.12)', text:'#FCA5A5', border:'#DC2626'},
    '#378ADD': {bg:'rgba(96,165,250,0.12)', text:'#93C5FD', border:'#2563EB'},
    '#D4537E': {bg:'rgba(244,114,182,0.12)', text:'#F9A8D4', border:'#DB2777'},
    '#00C8B4': {bg:'rgba(0,200,180,0.12)', text:'#00E5CE', border:'#00C8B4'},
    '#E879A0': {bg:'rgba(232,121,160,0.12)', text:'#F9A8D4', border:'#E879A0'},
    '#F59E0B': {bg:'rgba(245,158,11,0.12)', text:'#FCD34D', border:'#F59E0B'},
  };
  return palettes[hex] || {bg:'rgba(255,255,255,0.07)', text:'#E4E4E7', border:'#52525B'};
}

// ── FETCH ──────────────────────────────────────────────────────────────

let currentRole = 'guest';
let currentMasterId = null;

async function loadAll() {
  const dateStr = isoDate(currentDate);
  const [me, mastersData, apptsData, breaksData] = await Promise.all([
    fetch('/api/me').then(r=>r.json()),
    fetch('/api/masters').then(r=>r.json()),
    fetch(`/api/appointments?date=${dateStr}`).then(r=>r.json()),
    fetch(`/api/breaks?date=${dateStr}`).then(r=>r.json()),
  ]);
  currentRole = me.role || 'guest';
  currentMasterId = me.master_id || null;
  masters = mastersData;
  appointments = apptsData;
  breaks = breaksData;

  // Master sees only themselves by default
  if (currentRole === 'master' && currentMasterId) {
    visibleMasters = new Set([currentMasterId]);
  } else if (visibleMasters.size === 0) {
    masters.forEach(m => visibleMasters.add(m.id));
  }
  if (!mobileMasterId && masters.length) mobileMasterId = masters[0].id;
  applyRoleUI();
  renderAll();
}

function applyRoleUI() {
  const canEdit = currentRole === 'admin' || currentRole === 'reception';
  // Hide add button for masters
  document.querySelectorAll('.add-btn, .m-fab').forEach(el => {
    el.style.display = canEdit ? '' : 'none';
  });
  // Hide settings for non-admins
  const settingsBtn = document.getElementById('settingsBtn');
  if (settingsBtn) settingsBtn.style.display = currentRole === 'admin' ? '' : 'none';
  // Show logout button always
  document.getElementById('logoutBtn').style.display = '';
  // Show role badge
  const badge = document.getElementById('roleBadge');
  if (badge) {
    const labels = {admin:'Адмін', reception:'Рецепція', master:'Майстер'};
    badge.textContent = labels[currentRole] || '';
    badge.style.display = currentRole !== 'guest' ? '' : 'none';
  }
}

async function loadData() {
  const dateStr = isoDate(currentDate);
  [appointments, breaks] = await Promise.all([
    fetch(`/api/appointments?date=${dateStr}`).then(r=>r.json()),
    fetch(`/api/breaks?date=${dateStr}`).then(r=>r.json()),
  ]);
  renderAll();
}

// ── RENDER ─────────────────────────────────────────────────────────────

function renderAll() {
  renderSidebar();
  renderGrid();
  renderMobile();
  const iso = isoDate(currentDate);
  document.getElementById('dateLabel').textContent = formatDateUa(iso);
  document.getElementById('datePicker').value = iso;
}

function renderSidebar() {
  const el = document.getElementById('masterList');
  el.innerHTML = masters.map(m => {
    const pal = lighten(m.color);
    const hidden = !visibleMasters.has(m.id) ? 'hidden' : '';
    return `<div class="master-chip ${hidden}" onclick="toggleMaster(${m.id})">
      <div class="avatar av" style="background:${pal.bg};color:${pal.text}">${m.initials}</div>
      <span class="master-chip-name">${m.name.split(' ')[0]}</span>
    </div>`;
  }).join('');
}

function renderGrid() {
  const grid = document.getElementById('scheduleGrid');
  const visible = masters.filter(m => visibleMasters.has(m.id));
  const cols = visible.length + 1;
  grid.style.gridTemplateColumns = `52px repeat(${visible.length}, 1fr)`;

  let html = '';

  // Header
  html += `<div class="grid-header-cell"></div>`;
  visible.forEach(m => {
    const pal = lighten(m.color);
    html += `<div class="grid-header-cell">
      <div class="avatar av" style="background:${pal.bg};color:${pal.text}">${m.initials}</div>
      ${m.name.split(' ')[0]}
    </div>`;
  });

  // Rows
  HOURS.forEach(hour => {
    const hMin = toMin(hour);
    html += `<div class="time-row">`;
    html += `<div class="time-col">${hour}</div>`;
    visible.forEach(m => {
      const isBreak = breaks.some(b => b.master_id===m.id && toMin(b.start_time)<=hMin && toMin(b.end_time)>hMin);
      const appt = appointments.find(a => a.master_id===m.id && a.start_time===hour);
      let slotClass = 'slot';
      if (isBreak) slotClass += ' break-slot';
      let inner = '';
      if (appt) {
        const pal = lighten(m.color);
        inner = `<div class="appt" style="background:${pal.bg};color:${pal.text}" onclick="openDetail(${appt.id})">
          <div class="aname">${appt.client_name}</div>
          <div class="asvc">${appt.service}</div>
          <div class="adur">${appt.duration_min} хв</div>
        </div>`;
      } else if (!isBreak) {
        inner = `<div style="height:100%" onclick="openAddOnSlot('${isoDate(currentDate)}','${hour}',${m.id})"></div>`;
      }
      html += `<div class="${slotClass}">${inner}</div>`;
    });
    html += `</div>`;
  });

  grid.innerHTML = html;
}

function renderMobile() {
  const tabs = document.getElementById('mobileTabs');
  const list = document.getElementById('mobileList');
  tabs.innerHTML = masters.map(m =>
    `<div class="m-tab ${m.id===mobileMasterId?'active':''}" onclick="setMobileTab(${m.id})">${m.name.split(' ')[0]}</div>`
  ).join('');

  const master = masters.find(m=>m.id===mobileMasterId);
  if (!master) { list.innerHTML=''; return; }
  const pal = lighten(master.color);

  let slots = [...HOURS].map(h => {
    const appt = appointments.find(a=>a.master_id===mobileMasterId && a.start_time===h);
    const isBreak = breaks.some(b=>b.master_id===mobileMasterId && toMin(b.start_time)<=toMin(h) && toMin(b.end_time)>toMin(h));
    return {h, appt, isBreak};
  }).filter(s=>s.appt||s.isBreak);

  if (!slots.length) {
    list.innerHTML = `<div style="padding:24px;text-align:center;color:var(--hint)">Записів на цей день немає</div>`;
    return;
  }

  list.innerHTML = slots.map(s => {
    if (s.isBreak) return `<div class="m-slot">
      <div class="m-time">${s.h}</div>
      <div class="m-card" style="background:#2A2A30;color:#F59E0B;font-style:italic;padding:8px 10px;border-left:3px solid #78350F">⏸ Перерва</div>
    </div>`;
    const a = s.appt;
    return `<div class="m-slot">
      <div class="m-time">${a.start_time}</div>
      <div class="m-card" style="background:${pal.bg};color:${pal.text};border-left:3px solid ${pal.border};box-shadow:0 4px 12px rgba(0,0,0,.4)" onclick="openDetail(${a.id})">
        <div class="mc-name">${a.client_name}</div>
        <div class="mc-svc">${a.service}</div>
        <div class="mc-dur">${a.duration_min} хв</div>
      </div>
    </div>`;
  }).join('');
}

// ── CONTROLS ───────────────────────────────────────────────────────────

function changeDate(delta) {
  currentDate.setDate(currentDate.getDate()+delta);
  loadData();
}
function goToday() {
  currentDate = new Date();
  loadData();
}
function pickDate(val) {
  if (!val) return;
  const [y,m,d] = val.split('-').map(Number);
  currentDate = new Date(y, m-1, d);
  loadData();
}
function toggleMaster(id) {
  if (visibleMasters.has(id)) { visibleMasters.delete(id); }
  else { visibleMasters.add(id); }
  renderAll();
}
function showAllMasters() {
  masters.forEach(m => visibleMasters.add(m.id));
  renderAll();
}
function setMobileTab(id) {
  mobileMasterId = id;
  renderMobile();
}

// ── MODALS ─────────────────────────────────────────────────────────────

function populateMasterSelect() {
  const sel = document.getElementById('fMaster');
  sel.innerHTML = masters.map(m=>`<option value="${m.id}">${m.name}</option>`).join('');
}

function openAddModal() {
  editingId = null;
  document.getElementById('modalTitle').textContent = 'Новий запис';
  document.getElementById('deleteBtn').classList.add('hidden');
  document.getElementById('fClient').value = '';
  document.getElementById('fService').value = '';
  document.getElementById('fDate').value = isoDate(currentDate);
  document.getElementById('fTime').value = '10:00';
  document.getElementById('fDuration').value = '60';
  document.getElementById('fNotes').value = '';
  document.getElementById('formError').classList.add('hidden');
  populateMasterSelect();
  document.getElementById('modalOverlay').classList.remove('hidden');
}

function openAddOnSlot(date, time, masterId) {
  if (currentRole !== 'admin' && currentRole !== 'reception') return;
  openAddModal();
  document.getElementById('fDate').value = date;
  document.getElementById('fTime').value = time;
  document.getElementById('fMaster').value = masterId;
}

function openEditModal(appt) {
  editingId = appt.id;
  document.getElementById('modalTitle').textContent = 'Редагувати запис';
  document.getElementById('deleteBtn').classList.remove('hidden');
  populateMasterSelect();
  document.getElementById('fMaster').value = appt.master_id;
  document.getElementById('fClient').value = appt.client_name;
  document.getElementById('fService').value = appt.service;
  document.getElementById('fDate').value = appt.appt_date;
  document.getElementById('fTime').value = appt.start_time;
  document.getElementById('fDuration').value = appt.duration_min;
  document.getElementById('fNotes').value = appt.notes||'';
  document.getElementById('formError').classList.add('hidden');
  document.getElementById('detailOverlay').classList.add('hidden');
  document.getElementById('modalOverlay').classList.remove('hidden');
}

function closeModal() { document.getElementById('modalOverlay').classList.add('hidden'); }

function openDetail(id) {
  const a = appointments.find(x=>x.id===id);
  if (!a) return;
  const m = masters.find(x=>x.id===a.master_id);
  const pal = lighten(m.color);
  document.getElementById('detailBar').style.background = m.color;
  document.getElementById('detailName').textContent = a.client_name;
  document.getElementById('detailBody').innerHTML = `
    <div class="detail-row"><span class="dl">Майстер</span><span class="dv">${a.master_name}</span></div>
    <div class="detail-row"><span class="dl">Послуга</span><span class="dv">${a.service}</span></div>
    <div class="detail-row"><span class="dl">Дата</span><span class="dv">${formatDateUa(a.appt_date)}</span></div>
    <div class="detail-row"><span class="dl">Час</span><span class="dv">${a.start_time}, ${a.duration_min} хв</span></div>
    ${a.notes ? `<div class="detail-row"><span class="dl">Нотатки</span><span class="dv">${a.notes}</span></div>` : ''}
  `;
  const editBtn = document.getElementById('detailEditBtn');
  const canEdit = currentRole === 'admin' || currentRole === 'reception';
  editBtn.style.display = canEdit ? '' : 'none';
  editBtn.onclick = () => openEditModal(a);
  document.getElementById('detailOverlay').classList.remove('hidden');
}

function closeDetail() { document.getElementById('detailOverlay').classList.add('hidden'); }

// close on overlay click
document.getElementById('modalOverlay').addEventListener('click', e => { if(e.target===e.currentTarget) closeModal(); });
document.getElementById('detailOverlay').addEventListener('click', e => { if(e.target===e.currentTarget) closeDetail(); });

// ── SAVE / DELETE ──────────────────────────────────────────────────────

async function saveAppt() {
  const body = {
    master_id: parseInt(document.getElementById('fMaster').value),
    client_name: document.getElementById('fClient').value.trim(),
    service: document.getElementById('fService').value.trim(),
    appt_date: document.getElementById('fDate').value,
    start_time: document.getElementById('fTime').value,
    duration_min: parseInt(document.getElementById('fDuration').value),
    notes: document.getElementById('fNotes').value.trim(),
  };
  if (!body.client_name || !body.service || !body.appt_date || !body.start_time) {
    showError('Заповніть усі обов\'язкові поля'); return;
  }
  try {
    const url = editingId ? `/api/appointments/${editingId}` : '/api/appointments';
    const method = editingId ? 'PUT' : 'POST';
    const res = await fetch(url, { method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
    if (!res.ok) { const e=await res.json(); showError(e.detail||'Помилка'); return; }
    closeModal();
    showToast(editingId ? 'Запис оновлено' : 'Запис створено');
    await loadData();
  } catch(e) { showError('Помилка з\'єднання'); }
}

async function deleteAppt() {
  if (!editingId) return;
  if (!confirm('Видалити цей запис?')) return;
  await fetch(`/api/appointments/${editingId}`, {method:'DELETE'});
  closeModal();
  showToast('Запис видалено');
  await loadData();
}

function showError(msg) {
  const el = document.getElementById('formError');
  el.textContent = msg;
  el.classList.remove('hidden');
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), 2500);
}


// ── SETTINGS ────────────────────────────────────────────────────────────────

let pendingMasters = [];

function openSettingsModal() {
  pendingMasters = JSON.parse(JSON.stringify(masters));
  renderMasterEditList();
  document.getElementById('settingsOverlay').classList.remove('hidden');
}

function closeSettings() {
  document.getElementById('settingsOverlay').classList.add('hidden');
}

function renderMasterEditList() {
  const colors = ['#7F77DD','#1D9E75','#BA7517','#D85A30','#378ADD','#D4537E','#00C8B4','#E879A0','#F59E0B'];
  const el = document.getElementById('masterEditList');
  el.innerHTML = pendingMasters.map((m, i) => `
    <div style="display:flex;gap:8px;align-items:center;padding:8px;background:var(--surface2);border-radius:8px;margin-bottom:8px">
      <div style="width:28px;height:28px;border-radius:50%;background:${m.color};display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;flex-shrink:0">${m.initials}</div>
      <input value="${m.name}" oninput="pendingMasters[${i}].name=this.value;pendingMasters[${i}].initials=this.value.split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase()" style="flex:1;padding:6px 8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:var(--font);font-size:13px">
      <select onchange="pendingMasters[${i}].color=this.value" style="padding:6px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:var(--font)">
        ${colors.map(col => `<option value="${col}" ${m.color===col?'selected':''} style="background:${col}">${col}</option>`).join('')}
      </select>
      <button onclick="pendingMasters.splice(${i},1);renderMasterEditList()" style="background:var(--danger-light);border:none;border-radius:6px;padding:6px 10px;color:var(--danger);cursor:pointer;font-size:16px">✕</button>
    </div>
  `).join('');
}

function addNewMasterRow() {
  const colors = ['#7F77DD','#1D9E75','#BA7517','#D85A30','#378ADD','#D4537E','#00C8B4','#E879A0','#F59E0B'];
  pendingMasters.push({id: null, name: 'Новий майстер', color: colors[pendingMasters.length % colors.length], initials: 'НМ'});
  renderMasterEditList();
}

async function saveMasterSettings() {
  // Delete removed masters
  const currentIds = new Set(pendingMasters.filter(m=>m.id).map(m=>m.id));
  for (const m of masters) {
    if (!currentIds.has(m.id)) {
      await fetch(`/api/masters/${m.id}`, { method: 'DELETE' });
    }
  }
  // Create new / update existing
  for (const m of pendingMasters) {
    const words = m.name.trim().split(/\s+/);
    const initials = words.length >= 2
      ? (words[0][0] + words[1][0]).toUpperCase()
      : (words[0].slice(0,2)).toUpperCase() || '??';
    if (!m.id) {
      await fetch('/api/masters', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: m.name, color: m.color, initials})
      });
    } else {
      await fetch(`/api/masters/${m.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: m.name, color: m.color, initials})
      });
    }
  }
  closeSettings();
  showToast('Налаштування збережено');
  await loadAll();
}

document.getElementById('settingsOverlay').addEventListener('click', e => { if(e.target===e.currentTarget) closeSettings(); });

async function doLogout() {
  await fetch('/api/logout', {method:'POST'});
  window.location.href = '/login';
}

function showSettingsTab(tab) {
  document.getElementById('settingsTabMasters').style.display = tab==='masters' ? '' : 'none';
  document.getElementById('settingsTabPasswords').style.display = tab==='passwords' ? '' : 'none';
  document.getElementById('tabMasters').style.background = tab==='masters' ? 'var(--accent)' : 'transparent';
  document.getElementById('tabMasters').style.color = tab==='masters' ? '#121214' : 'var(--muted)';
  document.getElementById('tabMasters').style.border = tab==='masters' ? 'none' : '1px solid var(--border)';
  document.getElementById('tabPasswords').style.background = tab==='passwords' ? 'var(--accent)' : 'transparent';
  document.getElementById('tabPasswords').style.color = tab==='passwords' ? '#121214' : 'var(--muted)';
  document.getElementById('tabPasswords').style.border = tab==='passwords' ? 'none' : '1px solid var(--border)';
}

async function openSettingsModalFull() {
  pendingMasters = JSON.parse(JSON.stringify(masters));
  renderMasterEditList();
  // Load passwords
  try {
    const res = await fetch('/api/settings/passwords');
    if (res.ok) {
      const pwds = await res.json();
      document.getElementById('pwdAdmin').value = pwds.pwd_admin || '';
      document.getElementById('pwdReception').value = pwds.pwd_reception || '';
      // Master passwords
      const mlist = document.getElementById('masterPasswordsList');
      mlist.innerHTML = '<div style="font-size:12px;font-weight:600;color:var(--muted);margin-bottom:8px">Паролі майстрів</div>' +
        masters.map(m => `<div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
          <div style="width:28px;height:28px;border-radius:50%;background:rgba(0,200,180,.15);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#00C8B4;flex-shrink:0">${m.initials}</div>
          <span style="font-size:13px;min-width:100px;color:var(--text)">${m.name}</span>
          <input type="text" id="pwd_master_${m.id}" value="${pwds['pwd_master_'+m.id]||''}" placeholder="Пароль..." style="flex:1;padding:6px 8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:var(--font);font-size:12px">
        </div>`).join('');
    }
  } catch(e) {}
  document.getElementById('settingsOverlay').classList.remove('hidden');
}

async function saveAllSettings() {
  // Save masters
  await saveMasterSettings();
  // Save passwords
  const pwdAdmin = document.getElementById('pwdAdmin').value.trim();
  const pwdReception = document.getElementById('pwdReception').value.trim();
  if (pwdAdmin) await fetch('/api/settings/password', {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({role:'admin', password:pwdAdmin})});
  if (pwdReception) await fetch('/api/settings/password', {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({role:'reception', password:pwdReception})});
  for (const m of masters) {
    const input = document.getElementById(`pwd_master_${m.id}`);
    if (input && input.value.trim()) {
      await fetch('/api/settings/password', {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({role:'master', master_id:m.id, password:input.value.trim()})});
    }
  }
  showToast('Все збережено!');
}

// ── INIT ───────────────────────────────────────────────────────────────
loadAll();
</script>
</body>
</html>
"""

# ─── AUTH API ──────────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    password: str
    master_id: Optional[int] = None

@app.post("/api/login")
def login(data: LoginIn, response: Response):
    pwd_admin = get_setting("pwd_admin")
    pwd_reception = get_setting("pwd_reception")

    if data.password == pwd_admin:
        token = create_session("admin")
        response.set_cookie("token", token, httponly=False, samesite="none", max_age=86400*30, secure=True)
        return {"role": "admin", "master_id": None}
    elif data.password == pwd_reception:
        token = create_session("reception")
        response.set_cookie("token", token, httponly=False, samesite="none", max_age=86400*30, secure=True)
        return {"role": "reception", "master_id": None}
    elif data.master_id:
        # Check master password: stored as pwd_master_{id}
        master_rows = turso("SELECT * FROM masters WHERE id=?", [data.master_id])
        if not master_rows:
            raise HTTPException(400, "Майстра не знайдено")
        pwd_master = get_setting(f"pwd_master_{data.master_id}")
        if not pwd_master or data.password != pwd_master:
            raise HTTPException(401, "Невірний пароль")
        token = create_session("master", data.master_id)
        response.set_cookie("token", token, httponly=False, samesite="none", max_age=86400*30, secure=True)
        return {"role": "master", "master_id": data.master_id}
    else:
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
    return sess

class PasswordIn(BaseModel):
    role: str
    master_id: Optional[int] = None
    password: str

@app.put("/api/settings/password")
def set_password(data: PasswordIn, sess=Depends(require_auth)):
    if sess["role"] != "admin":
        raise HTTPException(403, "Тільки адмін може змінювати паролі")
    if data.role == "admin":
        key = "pwd_admin"
    elif data.role == "reception":
        key = "pwd_reception"
    elif data.role == "master" and data.master_id:
        key = f"pwd_master_{data.master_id}"
    else:
        raise HTTPException(400, "Невірні параметри")
    turso_exec("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", [key, data.password])
    return {"ok": True}

@app.get("/api/settings/passwords")
def get_passwords(sess=Depends(require_auth)):
    if sess["role"] != "admin":
        raise HTTPException(403, "Тільки адмін")
    rows = turso("SELECT key, value FROM settings WHERE key LIKE 'pwd_%'")
    return {r["key"]: r["value"] for r in rows}



@app.get("/api/appointments/range")
def appointments_range(master_id: int, from_date: str = None, to_date: str = None):
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

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return LOGIN_HTML

@app.get("/", response_class=HTMLResponse)
def index(token: str = Cookie(default=None)):
    sess = get_session(token)
    if not sess:
        return RedirectResponse("/login")
    return HTML

MASTER_HTML = '<!DOCTYPE html>\n<html lang="uk">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Body Balance — Мій розклад</title>\n<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">\n<style>\n*{box-sizing:border-box;margin:0;padding:0}\n:root{--bg:#121214;--surface:#1E1E22;--surface2:#222227;--border:#2E2E36;--text:#E4E4E7;--muted:#A1A1AA;--hint:#71717A;--accent:#00C8B4;--accent-light:rgba(0,200,180,0.15);--danger:#F87171;--danger-light:rgba(248,113,113,.12);--radius:12px;--radius-sm:8px;--shadow:0 4px 12px rgba(0,0,0,.5);--font:\'Inter\',sans-serif;--font-head:\'Montserrat\',sans-serif}\nhtml,body{height:100%;font-family:var(--font);background:var(--bg);color:var(--text);font-size:14px}\n.app{display:flex;flex-direction:column;height:100vh}\n.topbar{display:flex;align-items:center;gap:16px;padding:0 20px;height:64px;background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0}\n.topbar img{height:48px;width:auto}\n.spacer{flex:1}\n.date-nav{display:flex;align-items:center;gap:8px;padding:12px 20px;flex-shrink:0;background:var(--surface2);border-bottom:1px solid var(--border)}\n.date-nav button{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 12px;cursor:pointer;font-family:var(--font);font-size:13px;color:var(--text)}\n.today-btn{background:var(--accent)!important;color:#121214!important;border-color:var(--accent)!important;font-weight:700!important}\n.week-label{font-family:var(--font-head);font-size:15px;font-weight:700;color:var(--text)}\n.content{flex:1;overflow:auto;padding:16px 20px}\n.week-wrap{background:var(--surface);border-radius:var(--radius);border:1px solid var(--border);overflow-x:auto}\n.week-grid{display:grid;grid-template-columns:52px repeat(7,1fr)}\n.wh{padding:10px 6px;text-align:center;border-bottom:1px solid var(--border);border-right:1px solid var(--border);background:var(--surface);position:sticky;top:0;z-index:2}\n.wh:last-child{border-right:none}\n.wh-day{font-family:var(--font-head);font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}\n.wh-date{font-family:var(--font-head);font-size:20px;font-weight:800;color:var(--text)}\n.wh.today .wh-date{color:var(--accent)}\n.wh.today{border-bottom:2px solid var(--accent)}\n.time-col{font-size:12px;color:var(--hint);text-align:right;padding:0 8px 0 0;border-right:1px solid var(--border);display:flex;align-items:flex-start;padding-top:5px;border-bottom:1px solid var(--border);height:56px;font-family:var(--font-head)}\n.slot{border-right:1px solid var(--border);border-bottom:1px solid var(--border);height:56px;padding:3px;cursor:pointer;transition:background .1s}\n.slot:last-child{border-right:none}\n.slot:hover{background:var(--accent-light)}\n.slot.break-slot{background:repeating-linear-gradient(45deg,#2A2A30,#2A2A30 5px,#222227 5px,#222227 10px);cursor:default}\n.slot.break-slot:hover{background:repeating-linear-gradient(45deg,#2A2A30,#2A2A30 5px,#222227 5px,#222227 10px)}\n.appt{border-radius:6px;padding:4px 8px 4px 11px;height:100%;display:flex;flex-direction:column;justify-content:center;cursor:pointer;border-left:3px solid var(--accent);background:var(--accent-light);box-shadow:var(--shadow)}\n.appt:hover{filter:brightness(1.1)}\n.appt .an{font-size:12px;font-weight:700;font-family:var(--font-head);color:var(--accent);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n.appt .as{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n.appt .ad{font-size:10px;color:var(--hint)}\n.overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:100;padding:16px}\n.overlay.hidden{display:none}\n.modal{background:var(--surface);border-radius:var(--radius);padding:24px;width:100%;max-width:400px;box-shadow:0 8px 32px rgba(0,0,0,.6);border:1px solid var(--border)}\n.modal h2{font-family:var(--font-head);font-size:16px;font-weight:700;margin-bottom:16px}\n.form-row{margin-bottom:12px}\n.form-row label{display:block;font-size:11px;font-weight:600;color:var(--muted);margin-bottom:4px;font-family:var(--font-head);text-transform:uppercase;letter-spacing:.3px}\n.form-row input,.form-row select,.form-row textarea{width:100%;padding:9px 11px;border:1px solid var(--border);border-radius:var(--radius-sm);font-family:var(--font);font-size:13px;background:var(--bg);color:var(--text);outline:none;transition:border-color .12s}\n.form-row input:focus,.form-row select:focus{border-color:var(--accent);box-shadow:0 0 0 2px rgba(0,200,180,.15)}\n.form-2col{display:grid;grid-template-columns:1fr 1fr;gap:12px}\n.modal-footer{display:flex;gap:8px;margin-top:16px;justify-content:flex-end}\n.btn{padding:8px 16px;border-radius:var(--radius-sm);cursor:pointer;font-family:var(--font-head);font-size:13px;font-weight:600;border:1px solid var(--border);background:var(--surface);color:var(--text)}\n.btn:hover{background:var(--surface2)}\n.btn-primary{background:var(--accent);color:#121214;border-color:var(--accent)}\n.btn-danger{background:var(--danger-light);color:var(--danger);border-color:rgba(248,113,113,.3)}\n.detail-bar{height:4px;border-radius:2px;background:var(--accent);margin-bottom:16px}\n.detail-row{display:flex;gap:10px;margin-bottom:8px}\n.dl{font-size:11px;color:var(--muted);min-width:80px;font-family:var(--font-head);text-transform:uppercase}\n.dv{font-size:14px;font-weight:500}\n.mobile-wrap{display:none;flex-direction:column;flex:1;overflow:hidden}\n.m-daylist{display:flex;overflow-x:auto;padding:10px 16px;gap:8px;border-bottom:1px solid var(--border);flex-shrink:0}\n.m-day{display:flex;flex-direction:column;align-items:center;padding:8px 12px;border-radius:var(--radius-sm);cursor:pointer;min-width:48px;border:1px solid transparent}\n.m-day.active{background:var(--accent-light);border-color:rgba(0,200,180,.3)}\n.m-day.today .m-date{color:var(--accent)}\n.m-dayname{font-size:10px;color:var(--muted);font-family:var(--font-head);font-weight:600;text-transform:uppercase}\n.m-date{font-size:18px;font-weight:800;font-family:var(--font-head)}\n.m-list{flex:1;overflow-y:auto;padding:12px 16px}\n.m-slot{display:flex;gap:10px;margin-bottom:10px}\n.m-time{font-size:12px;color:var(--hint);min-width:40px;padding-top:6px;font-family:var(--font-head)}\n.m-card{flex:1;border-radius:var(--radius-sm);padding:9px 12px;cursor:pointer;border-left:3px solid var(--accent);background:var(--accent-light);box-shadow:var(--shadow)}\n.m-card .mc-name{font-size:13px;font-weight:700;font-family:var(--font-head);color:var(--accent)}\n.m-card .mc-svc{font-size:12px;color:var(--muted)}\n.m-card .mc-dur{font-size:11px;color:var(--hint)}\n.m-fab-wrap{padding:12px 16px;border-top:1px solid var(--border);flex-shrink:0}\n.m-fab{width:100%;padding:12px;background:var(--accent);color:#121214;border:none;border-radius:var(--radius);font-family:var(--font-head);font-size:14px;font-weight:700;cursor:pointer}\n.m-empty{text-align:center;padding:40px 20px;color:var(--hint);font-style:italic}\n.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1A1916;color:#fff;padding:10px 20px;border-radius:20px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:200}\n.toast.show{opacity:1}\n.hidden{display:none!important}\n@media(max-width:640px){.content{display:none}.mobile-wrap{display:flex}}\n</style>\n</head>\n<body>\n<div class="app">\n<div class="topbar">\n  <img src="data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyBpZD0iTGF5ZXJfMSIgZGF0YS1uYW1lPSJMYXllciAxIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyMTUzIDEwODAiPgogIDxkZWZzPgogICAgPHN0eWxlPgogICAgICAuY2xzLTEgewogICAgICAgIGZpbGw6ICMwZGUwZDY7CiAgICAgIH0KCiAgICAgIC5jbHMtMiB7CiAgICAgICAgZmlsbDogI2UzZTRlODsKICAgICAgfQogICAgPC9zdHlsZT4KICA8L2RlZnM+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMzg0LjIzLDIxNC45OWMtMTAuODEtNS41NS0xMC44MSw0Mi4zMS0xMC44MSw0Mi4zMS0xMC44MSwyNS45NS0yMS42MiwyOC4xMS0yMS42MiwyOC4xMS0xMi45Ny04LjY1LTEwLjgxLTQ3LjU3LTEwLjgxLTQ3LjU3LTE1LjE0LTU2LjIyLDQzLjI0LTU4LjM4LDQzLjI0LTU4LjM4LDAsMC0yMS42Mi04LjY1LTM4LjkyLDYuNDktMjMuMDEsMjAuMTQtMTcuMyw2Mi43LTguNjUsODguNjUsOC42NSwyNS45NSwyMS42MiwxNS4xNCwyMS42MiwxNS4xNC0xMi45NywxNy4zLTI1Ljk1LDEyLjk3LTI1Ljk1LDEyLjk3LTI4LjExLTYuNDktMzguOTItMi4xNi0zOC45Mi0yLjE2LTMwLjI3LDEyLjk3LTIxLjYyLDY3LjAzLTE1LjE0LDg4LjY1LDYuNDksMjEuNjIsMzIuNDMsOTIuOTcsMzIuNDMsOTIuOTctOC42NSw2LjQ5LTE5LjQ2LDI1Ljk1LTE1LjE0LDQxLjA4LDQuMzIsMTUuMTQsMjUuOTUsMzIuNDMsMzYuNzYsMjEuNjIsMTAuODEtMTAuODEtOC42NS00Ny41Ny04LjY1LTQ3LjU3bC0yNC40Ni02Mi42NmMtMS4xNi0zLjQxLTIuMTYtNi44Ni0yLjk4LTEwLjM3LTMuMjEtMTMuNjctMjIuMjktNzEuODMtMTEuNDgtOTcuNzgsMTEuMDktMjYuNjMsNDcuNTctMTcuMyw0Ny41Ny0xNy4zLDQxLjA4LDguNjUsNDkuNzMtNDkuNzMsNDkuNzMtNDkuNzMsMTAuODEtMTAuODEsMTIuOTctMzguOTIsMi4xNi00NC40N1pNMzIxLjUzLDUyMS4wOGMwLDEwLjgxLDAsMTUuMTQtNi40OSwxMi45N3MtMTQuNDQtMTQuOTktMTIuOTctMjMuNzhjMi4xNi0xMi45NywxMC44MS0yMS42MiwxMC44MS0yMS42MiwwLDAsOC42NSwyMS42Miw4LjY1LDMyLjQzWiIvPgogIDxwYXRoIGNsYXNzPSJjbHMtMSIgZD0iTTM4My44NSwyNjkuMjlzLTQuMzIsMzAuMjctMjMuNzgsNjQuODZjLTE5LjQ2LDM0LjU5LTQ2LjQ5LDgzLjI0LTQ2LjQ5LDE1MC4yN2w0LjMyLTQuMzIsNC4zMi00LjMyczIuMTYtMTIuOTcsOC42NS00My4yNGM2LjQ5LTMwLjI3LDI3LjAzLTYzLjc4LDQxLjA4LTkyLjk3LDEyLjIzLTI1LjQsMTQuMDUtNTIuOTcsMTEuODktNzAuMjdaIi8+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMzMxLjY1LDg3OC42NHM1Ni45MS0xMDYuNzUsNzIuMDQtMTM5LjE4YzE1LjE0LTMyLjQzLDQwLTExMS4zNSwzMi40My0xNjAtNi44NS00NC4wNC0yMC41NC03Ni43Ni01Mi45Ny04OS43My0zMS4xNi0xMi40Ny02MS42Mi05LjczLTcwLjI3LTEuMDhsLTIuMTYtNi40OXMyNS4wMy0yMS42Miw4MC42Mi01LjQxYzU1LjU5LDE2LjIyLDcxLjgxLDg2LjQ5LDcxLjgxLDExNC41OSwwLDMxLjMtMy44OSwxMDAuMTgtNDMuMjQsMTYyLjE2LTQwLjU1LDYzLjg2LTg4LjI2LDEyNS4xMy04OC4yNiwxMjUuMTNaIi8+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNMzIyLjIzLDQ3Ny45M3MtNS40MS0yOS4xOSwxOC4zOC00MGMyMy43OC0xMC44MSw4Ny41Ny0xMS44OSw5Ny4zLTY5LjE5LDExLjQ2LTY3LjQ5LTQ5LjExLTYzLjUxLTQ5LjExLTYzLjUxLDAsMCw1NC41OS0yOC41Nyw3MS44MSwyOS45OSwxMC44MSwzNi43Ni0xMi45Nyw4Ni40OS03MS4zNSw5OS40Ni01My4wNywxMS43OS01NC4wNSwxNS4xNC02Ny4wMyw0My4yNFoiLz4KICA8cGF0aCBjbGFzcz0iY2xzLTEiIGQ9Ik04MDYsNzM4YzU4LDQwLDExNy4yOSw1OS4xOCwxNDQsNjksMTY2LDYxLDMyMiw3NCwzMjIsNzQsNTQwLDcyLDY4MC4wMi0xMDYuODksNjgwLjAyLTEwNi44OS0yMzAuOTgsMTU2LjExLTc5Ni45Nyw1My4wMS05MDIuMDIsMzAuODktMzgtOC0xMTUtMjUtMjMyLTgzIi8+CiAgPHBhdGggY2xhc3M9ImNscy0xIiBkPSJNODIzLjEsNzU1LjA0Yy0yNi4zMywyNy43NS02MS4yOSw0OS4wMy0xMDQuODksNjMuODMtMzcuNDMsMTIuNDktNzYuOTIsMTguNzMtMTE4LjQ2LDE4LjczLTI3LjE1LDAtNTMuMjctNi4wMi03OC4zNi0xOC4wNC0zMi4wOC0xNS4yNi00OC4xMy0zNi4zMS00OC4xMy02My4xNCwwLTMwLjk4LDEzLjE2LTU2LjQzLDM5LjQ5LTc2LjMyLDExLjkyLTguNzgsMjQuMjctMTUuMzcsMzcuMDItMTkuNzcsMTIuNzUtNC4zOSwyNi4xMi03LjA1LDQwLjExLTcuOTgsNi45OS0xOC41LDE1LjczLTQwLjAxLDI2LjIyLTY0LjUzLDEwLjQ5LTI0LjUxLDIxLjYyLTQ2LjAyLDMxLjkxLTY3LjMsMy4yOS02LjQ3LDgtMTYsMTQtMjYsMTAuMjktMTcuMTYsMjAtMzEsMjQtMzUsMTcuNTEtMTcuNTEsMzYtMTUsMzYtMTUsMCwwLTIuOTksMi4yNC0xMy40OCwxNS43Ni0zLjU0LDQuNTUtNi44OCw5LjI3LTkuOTksMTQuMTMtMzUuODMsNTUuOTUtNTYuMDcsMTA2LjM5LTg3LjY4LDE3Ny45NCw5Mi41NSwxLjg1LDE2MS40NCwyNS4yMiwyMDYuNyw3MC4wOCwxMy4xNi0xOS44OCwxOS43NC0zOC4xNiwxOS43NC01NC44MSwwLTI5LjE0LTE3LjQ5LTUyLjA0LTUyLjQ1LTY4LjY5LTE1LjE2LTYuOTctNTAuMDEtMTcuNDgtNzYuODQtMjIuNC0yMS4yMi0zLjg5LTI3LTUtMjctNSwwLDAsOC45NC0zLjE5LDIxLTcsMTktNiwyNi04LDM3LTEyLDQ1LjY0LTE2LjYsNzEuNjEtMjkuMDIsOTMuOTctNTIuODIsOS40Ni05LjcxLDE0LjE5LTE4LjUsMTQuMTktMjYuMzcsMC0xNi42NS0xOS4xMy0yOS4xNC01Ny4zOC0zNy40Ny0yNS45MS01LjU1LTUyLjY2LTguMzMtODAuMjEtOC4zMy03My42NCwwLTE0MC45OSwxMC45Mi0yMDUuNTcsNDAuOTgtMi40Ny45My0xNiw5LTE2LDksMCwwLDguMzMtMTEuMzMsMTUtMTgsOS05LDE5LTE3LDMzLTI0LDQyLjc4LTE5LjQzLDc3LjcyLTI4LjEsMTQzLjk1LTI4LjEsMzkuNDksMCw3Ni4wOSw0LjE2LDEwOS44MywxMi40OSw1Mi42NSwxMi40OSw3OC45OCwzMi4zOCw3OC45OCw1OS42NywwLDIyLjItMTYuMDQsNDIuMzMtNDguMTMsNjAuMzctMjMuNDUsMTMuNDItNDguMzQsMjIuNjctNzQuNjYsMjcuNzUsMjkuMiw3LjQxLDU0LjMsMTguMjgsNzUuMjcsMzIuNjEsMjguNzksMTkuNDMsNDMuMTksNDIuNzksNDMuMTksNzAuMDgsMCwyMi4yLTEwLjA4LDQ2LjAzLTMwLjIzLDcxLjQ3TTU2MC44Nyw4MDguNDdjLS44Ny4wNS0zLjg3LTkuNDYtMy44Ny0yMS45NSwwLTIwLjgyLDQuNDktNTYuNjksMjUuNDYtMTE0LjA1LTU0LjcxLDEwLjE4LTgyLjA2LDM4LjYzLTgyLjA2LDg1LjM0LDAsMjAuODIsMTIuNTQsMzcuNDcsMzcuNjQsNDkuOTYsMTkuNzQsOS43MSw0MC4zMSwxNC41Nyw2MS43LDE0LjU3LDkxLjMyLDAsMTYwLjIxLTI4LjIxLDIwNi43LTg0LjY1LTIzLjA0LTIxLjc0LTUyLjA0LTM4Ljg2LTg3LTUxLjM1LTMyLjUtMTEuNTYtNjUuMi0xNy4zNS05OC4xLTE3LjM1aC04Ljk1Yy0zLjA4LDAtNi4wNy4yNC04Ljk1LjY5LTI0LjY4LDU4Ljc1LTQyLjQ0LDExOC40OC00Mi40NCwxMzguODMiLz4KICA8Zz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTg5Ni4yOCw2MjUuMDF2LTY0Ljg1aDM0LjY1YzguOTYsMCwxNS41NiwxLjU5LDE5LjgzLDQuNzcsNC4yNiwzLjE4LDYuMzksNy4yNCw2LjM5LDEyLjE4LDAsMy4yNy0uOTEsNi4xOS0yLjczLDguNzUtMS44MiwyLjU2LTQuNDYsNC41OS03LjkyLDYuMDctMy40NiwxLjQ4LTcuNzIsMi4yMi0xMi43OSwyLjIybDEuODUtNWM1LjA2LDAsOS40My43MSwxMy4xMSwyLjEzLDMuNjcsMS40Miw2LjUyLDMuNDcsOC41Miw2LjE2LDIuMDEsMi42OSwzLjAxLDUuOTIsMy4wMSw5LjY4LDAsNS42Mi0yLjMzLDEwLTYuOTksMTMuMTYtNC42NiwzLjE1LTExLjQ3LDQuNzItMjAuNDMsNC43MmgtMzYuNVpNOTE3Ljc4LDYwOS43MmgxMy4xNmMyLjQxLDAsNC4yMi0uNDMsNS40Mi0xLjMsMS4yLS44NiwxLjgxLTIuMTMsMS44MS0zLjhzLS42LTIuOTMtMS44MS0zLjhjLTEuMi0uODYtMy4wMS0xLjMtNS40Mi0xLjNoLTE0LjY0di0xNC40NWgxMS42N2MyLjQ3LDAsNC4yOC0uNDIsNS40Mi0xLjI1LDEuMTQtLjgzLDEuNzEtMi4wMiwxLjcxLTMuNTdzLS41Ny0yLjgxLTEuNzEtMy42MWMtMS4xNC0uOC0yLjk1LTEuMi01LjQyLTEuMmgtMTAuMTl2MzQuMjhaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xMDI5Ljc4LDYyNi40OWMtNS4zMSwwLTEwLjIxLS44My0xNC42OC0yLjUtNC40OC0xLjY3LTguMzUtNC4wMy0xMS42My03LjA5LTMuMjctMy4wNi01LjgyLTYuNjUtNy42NC0xMC43OS0xLjgyLTQuMTQtMi43My04LjY1LTIuNzMtMTMuNTNzLjkxLTkuNDYsMi43My0xMy41N2MxLjgyLTQuMTEsNC4zNy03LjY5LDcuNjQtMTAuNzUsMy4yNy0zLjA2LDcuMTUtNS40MiwxMS42My03LjA5LDQuNDgtMS42Nyw5LjM0LTIuNSwxNC41OS0yLjVzMTAuMTkuODMsMTQuNjQsMi41YzQuNDUsMS42Nyw4LjMxLDQuMDMsMTEuNTgsNy4wOSwzLjI3LDMuMDYsNS44Miw2LjY0LDcuNjQsMTAuNzUsMS44Miw0LjExLDIuNzMsOC42MywyLjczLDEzLjU3cy0uOTEsOS4zOS0yLjczLDEzLjUzYy0xLjgyLDQuMTQtNC4zNyw3Ljc0LTcuNjQsMTAuNzktMy4yNywzLjA2LTcuMTMsNS40Mi0xMS41OCw3LjA5LTQuNDUsMS42Ny05LjMsMi41LTE0LjU0LDIuNVpNMTAyOS42OSw2MDguOGMyLjA0LDAsMy45NC0uMzcsNS43LTEuMTEsMS43Ni0uNzQsMy4zLTEuODEsNC42My0zLjIsMS4zMy0xLjM5LDIuMzYtMy4wOSwzLjEtNS4xLjc0LTIuMDEsMS4xMS00LjI4LDEuMTEtNi44MXMtLjM3LTQuOC0xLjExLTYuODFjLS43NC0yLjAxLTEuNzgtMy43MS0zLjEtNS4xLTEuMzMtMS4zOS0yLjg3LTIuNDUtNC42My0zLjItMS43Ni0uNzQtMy42Ni0xLjExLTUuNy0xLjExcy0zLjk0LjM3LTUuNywxLjExLTMuMywxLjgxLTQuNjMsMy4yYy0xLjMzLDEuMzktMi4zNiwzLjA5LTMuMSw1LjEtLjc0LDIuMDEtMS4xMSw0LjI4LTEuMTEsNi44MXMuMzcsNC44LDEuMTEsNi44MWMuNzQsMi4wMSwxLjc3LDMuNzEsMy4xLDUuMSwxLjMzLDEuMzksMi44NywyLjQ2LDQuNjMsMy4yczMuNjYsMS4xMSw1LjcsMS4xMVoiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTExMDIuMDQsNjI1LjAxdi02NC44NWgzMS45NmM3LjIzLDAsMTMuNTksMS4zMSwxOS4wOCwzLjk0LDUuNSwyLjYzLDkuNzksNi4zNSwxMi44OCwxMS4xNiwzLjA5LDQuODIsNC42MywxMC41Niw0LjYzLDE3LjIzcy0xLjU0LDEyLjUyLTQuNjMsMTcuMzdjLTMuMDksNC44NS03LjM4LDguNTktMTIuODgsMTEuMjEtNS41LDIuNjMtMTEuODYsMy45NC0xOS4wOCwzLjk0aC0zMS45NlpNMTEyMy45MSw2MDcuOTZoOS4xN2MzLjA5LDAsNS43OS0uNTksOC4xMS0xLjc2LDIuMzItMS4xNyw0LjEyLTIuOTIsNS40Mi01LjIzLDEuMy0yLjMyLDEuOTUtNS4xNCwxLjk1LTguNDhzLS42NS02LjA1LTEuOTUtOC4zNGMtMS4zLTIuMjgtMy4xLTQuMDEtNS40Mi01LjE5LTIuMzItMS4xNy01LjAyLTEuNzYtOC4xMS0xLjc2aC05LjE3djMwLjc2WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTIyMC4yNSw2MjUuMDF2LTI4LjQ0bDUsMTMuMDYtMjkuNDYtNDkuNDdoMjMuMDdsMTkuOTIsMzMuODFoLTEzLjQzbDIwLjEtMzMuODFoMjEuMTJsLTI5LjI3LDQ5LjQ3LDQuODItMTMuMDZ2MjguNDRoLTIxLjg2WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTM1Mi43Myw2MjUuMDF2LTY0Ljg1aDM0LjY1YzguOTYsMCwxNS41NiwxLjU5LDE5LjgzLDQuNzcsNC4yNiwzLjE4LDYuMzksNy4yNCw2LjM5LDEyLjE4LDAsMy4yNy0uOTEsNi4xOS0yLjczLDguNzUtMS44MiwyLjU2LTQuNDYsNC41OS03LjkyLDYuMDctMy40NiwxLjQ4LTcuNzIsMi4yMi0xMi43OSwyLjIybDEuODUtNWM1LjA2LDAsOS40My43MSwxMy4xMSwyLjEzLDMuNjcsMS40Miw2LjUyLDMuNDcsOC41Miw2LjE2LDIuMDEsMi42OSwzLjAxLDUuOTIsMy4wMSw5LjY4LDAsNS42Mi0yLjMzLDEwLTYuOTksMTMuMTYtNC42NiwzLjE1LTExLjQ3LDQuNzItMjAuNDMsNC43MmgtMzYuNVpNMTM3NC4yMiw2MDkuNzJoMTMuMTZjMi40MSwwLDQuMjItLjQzLDUuNDItMS4zLDEuMi0uODYsMS44MS0yLjEzLDEuODEtMy44cy0uNi0yLjkzLTEuODEtMy44Yy0xLjItLjg2LTMuMDEtMS4zLTUuNDItMS4zaC0xNC42NHYtMTQuNDVoMTEuNjdjMi40NywwLDQuMjgtLjQyLDUuNDItMS4yNSwxLjE0LS44MywxLjcxLTIuMDIsMS43MS0zLjU3cy0uNTctMi44MS0xLjcxLTMuNjFjLTEuMTQtLjgtMi45NS0xLjItNS40Mi0xLjJoLTEwLjE5djM0LjI4WiIvPgogICAgPHBhdGggY2xhc3M9ImNscy0yIiBkPSJNMTQ0NS4wOSw2MjUuMDFsMjguMzUtNjQuODVoMjEuNDlsMjguMzUsNjQuODVoLTIyLjYxbC0yMC45NC01NC40N2g4LjUybC0yMC45NCw1NC40N2gtMjIuMjNaTTE0NjEuOTYsNjEzLjcxbDUuNTYtMTUuNzVoMjkuODNsNS41NiwxNS43NWgtNDAuOTVaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xNTU0LjYsNjI1LjAxdi02NC44NWgyMS44NnY0Ny45aDI5LjI4djE2Ljk1aC01MS4xNFoiLz4KICAgIDxwYXRoIGNsYXNzPSJjbHMtMiIgZD0iTTE2MzMuNDQsNjI1LjAxbDI4LjM1LTY0Ljg1aDIxLjQ5bDI4LjM1LDY0Ljg1aC0yMi42MWwtMjAuOTQtNTQuNDdoOC41MmwtMjAuOTQsNTQuNDdoLTIyLjIzWk0xNjUwLjMsNjEzLjcxbDUuNTYtMTUuNzVoMjkuODNsNS41NiwxNS43NWgtNDAuOTVaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xNzQyLjk0LDYyNS4wMXYtNjQuODVoMTcuOTdsMzIuOTgsMzkuNDdoLTguMzR2LTM5LjQ3aDIxLjMxdjY0Ljg1aC0xNy45N2wtMzIuOTgtMzkuNDdoOC4zNHYzOS40N2gtMjEuMzFaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xODc4Ljc1LDYyNi40OWMtNS4xOSwwLTkuOTktLjgyLTE0LjQxLTIuNDYtNC40Mi0xLjY0LTguMjUtMy45Ny0xMS40OS03LTMuMjQtMy4wMi01Ljc2LTYuNjEtNy41NS0xMC43NS0xLjc5LTQuMTQtMi42OS04LjcxLTIuNjktMTMuNzFzLjg5LTkuNTcsMi42OS0xMy43MWMxLjc5LTQuMTQsNC4zMS03LjcyLDcuNTUtMTAuNzUsMy4yNC0zLjAzLDcuMDctNS4zNiwxMS40OS02Ljk5LDQuNDItMS42NCw5LjIyLTIuNDYsMTQuNDEtMi40Niw2LjM2LDAsMTIsMS4xMSwxNi45MSwzLjMzczguOTcsNS40NCwxMi4xOCw5LjYzbC0xMy44LDEyLjMyYy0xLjkyLTIuNDEtNC4wMy00LjI4LTYuMzUtNS42LTIuMzItMS4zMy00LjkzLTEuOTktNy44My0xLjk5LTIuMjksMC00LjM1LjM3LTYuMjEsMS4xMS0xLjg1Ljc0LTMuNDQsMS44Mi00Ljc3LDMuMjQtMS4zMywxLjQyLTIuMzYsMy4xNC0zLjEsNS4xNC0uNzQsMi4wMS0xLjExLDQuMjUtMS4xMSw2Ljcycy4zNyw0LjcxLDEuMTEsNi43MmMuNzQsMi4wMSwxLjc3LDMuNzIsMy4xLDUuMTQsMS4zMywxLjQyLDIuOTIsMi41LDQuNzcsMy4yNCwxLjg1Ljc0LDMuOTIsMS4xMSw2LjIxLDEuMTEsMi45LDAsNS41MS0uNjYsNy44My0xLjk5LDIuMzItMS4zMyw0LjQzLTMuMiw2LjM1LTUuNjFsMTMuOCwxMi4zMmMtMy4yMSw0LjE0LTcuMjcsNy4zMy0xMi4xOCw5LjU5cy0xMC41NSwzLjM4LTE2LjkxLDMuMzhaIi8+CiAgICA8cGF0aCBjbGFzcz0iY2xzLTIiIGQ9Ik0xOTYzLjQzLDYwOC41MmgzMi40M3YxNi40OWgtNTMuOTJ2LTY0Ljg1aDUyLjcxdjE2LjQ5aC0zMS4yMnYzMS44N1pNMTk2MS45NCw1ODQuMjVoMjguOTF2MTUuNzVoLTI4Ljkxdi0xNS43NVoiLz4KICA8L2c+Cjwvc3ZnPg==" alt="Body Balance">\n  <div class="spacer"></div>\n  <a href="/" style="font-size:12px;color:var(--hint);text-decoration:none;font-family:var(--font-head)">Адмін &#8594;</a>\n</div>\n<div class="date-nav">\n  <button onclick="changeWeek(-1)">&#8249;</button>\n  <button class="today-btn" onclick="goToday()">&#128197; Сьогодні</button>\n  <button onclick="changeWeek(1)">&#8250;</button>\n  <span class="week-label" id="weekLabel"></span>\n</div>\n<div class="content">\n  <div class="week-wrap"><div class="week-grid" id="weekGrid"></div></div>\n</div>\n<div class="mobile-wrap">\n  <div class="m-daylist" id="mDayList"></div>\n  <div class="m-list" id="mList"></div>\n  <div class="m-fab-wrap"><button class="m-fab" onclick="openAddModal()">+ Новий запис</button></div>\n</div>\n</div>\n<div class="overlay hidden" id="modalOverlay">\n<div class="modal">\n  <h2 id="modalTitle">Новий запис</h2>\n  <div class="form-row"><label>Ім\'я клієнта</label><input id="fClient" type="text" placeholder="Ім\'я клієнта"></div>\n  <div class="form-row"><label>Послуга</label><input id="fService" type="text" placeholder="Масаж, ботокс..."></div>\n  <div class="form-2col">\n    <div class="form-row"><label>Дата</label><input id="fDate" type="date"></div>\n    <div class="form-row"><label>Час</label><input id="fTime" type="time"></div>\n  </div>\n  <div class="form-row"><label>Тривалість</label>\n    <select id="fDuration"><option value="30">30 хв</option><option value="45">45 хв</option><option value="60" selected>60 хв</option><option value="90">90 хв</option><option value="120">120 хв</option></select>\n  </div>\n  <div class="form-row"><label>Нотатки</label><textarea id="fNotes" rows="2" placeholder="Додатково..."></textarea></div>\n  <div class="modal-footer">\n    <button class="btn btn-danger hidden" id="deleteBtn" onclick="deleteAppt()">Видалити</button>\n    <button class="btn" onclick="closeModal()">Скасувати</button>\n    <button class="btn btn-primary" onclick="saveAppt()">Зберегти</button>\n  </div>\n</div>\n</div>\n<div class="overlay hidden" id="detailOverlay">\n<div class="modal">\n  <div class="detail-bar"></div>\n  <h2 id="detailName"></h2>\n  <div id="detailBody"></div>\n  <div class="modal-footer">\n    <button class="btn" onclick="closeDetail()">Закрити</button>\n    <button class="btn btn-primary" id="detailEditBtn">Редагувати</button>\n  </div>\n</div>\n</div>\n<div class="toast" id="toast"></div>\n<script>\nconst HOURS=Array.from({length:10},(_,i)=>`${String(i+9).padStart(2,"0")}:00`);\nconst DAYS=["Нд","Пн","Вт","Ср","Чт","Пт","Сб"];\nconst MONTHS=["січня","лютого","березня","квітня","травня","червня","липня","серпня","вересня","жовтня","листопада","грудня"];\nlet appointments=[],breaks=[],masterId=null;\nlet weekStart=getMonday(new Date());\nlet editingId=null,mobileDay=new Date();\nfunction getMonday(d){const r=new Date(d),day=r.getDay(),diff=r.getDate()-day+(day===0?-6:1);r.setDate(diff);r.setHours(0,0,0,0);return r;}\nfunction isoDate(d){return d.toISOString().slice(0,10);}\nfunction addDays(d,n){const r=new Date(d);r.setDate(r.getDate()+n);return r;}\nfunction fmtDate(iso){const[y,m,day]=iso.split("-");return `${parseInt(day)} ${MONTHS[parseInt(m)-1]}`;}\nfunction toMin(t){const[h,m]=t.split(":").map(Number);return h*60+m;}\nasync function loadWeek(){\n  if(!masterId){const ms=await fetch("/api/masters").then(r=>r.json());if(ms.length)masterId=ms[0].id;}\n  if(!masterId)return;\n  const days=Array.from({length:7},(_,i)=>isoDate(addDays(weekStart,i)));\n  const from=days[0],to=days[6];\n  const[ap,br]=await Promise.all([\n    fetch(`/api/appointments/range?master_id=${masterId}&from_date=${from}&to_date=${to}`).then(r=>r.json()),\n    fetch(`/api/breaks/range?master_id=${masterId}&from_date=${from}&to_date=${to}`).then(r=>r.json()),\n  ]);\n  appointments=ap;breaks=br;renderAll();\n}\nfunction renderAll(){\n  const days=Array.from({length:7},(_,i)=>addDays(weekStart,i));\n  const today=isoDate(new Date());\n  const f=fmtDate(isoDate(days[0])),t=fmtDate(isoDate(days[6]));\n  document.getElementById("weekLabel").textContent=`${f} — ${t}`;\n  renderGrid(days,today);renderMobileDays(days,today);renderMobileList();\n}\nfunction renderGrid(days,today){\n  const g=document.getElementById("weekGrid");\n  let h=`<div class="wh"></div>`;\n  days.forEach(d=>{const iso=isoDate(d),iT=iso===today;h+=`<div class="wh${iT?" today":""}"><div class="wh-day">${DAYS[d.getDay()]}</div><div class="wh-date">${d.getDate()}</div></div>`;});\n  HOURS.forEach(hr=>{\n    h+=`<div class="time-col">${hr}</div>`;\n    days.forEach(d=>{\n      const iso=isoDate(d);\n      const isB=breaks.some(b=>b.break_date===iso&&toMin(b.start_time)<=toMin(hr)&&toMin(b.end_time)>toMin(hr));\n      const ap=appointments.find(a=>a.appt_date===iso&&a.start_time===hr);\n      if(isB){h+=`<div class="slot break-slot"></div>`;}\n      else if(ap){h+=`<div class="slot"><div class="appt" onclick="openDetail(${ap.id})"><div class="an">${ap.client_name}</div><div class="as">${ap.service}</div><div class="ad">${ap.duration_min} хв</div></div></div>`;}\n      else{h+=`<div class="slot" onclick="openAddOnSlot(\'${iso}\',\'${hr}\')"></div>`;}\n    });\n  });\n  g.innerHTML=h;\n}\nfunction renderMobileDays(days,today){\n  const mIso=isoDate(mobileDay);\n  document.getElementById("mDayList").innerHTML=days.map(d=>{\n    const iso=isoDate(d),iT=iso===today,iA=iso===mIso;\n    return `<div class="m-day${iT?" today":""}${iA?" active":""}" onclick="setMobileDay(\'${iso}\')"><div class="m-dayname">${DAYS[d.getDay()]}</div><div class="m-date">${d.getDate()}</div></div>`;\n  }).join("");\n}\nfunction renderMobileList(){\n  const iso=isoDate(mobileDay),el=document.getElementById("mList");\n  const da=appointments.filter(a=>a.appt_date===iso).sort((a,b)=>a.start_time.localeCompare(b.start_time));\n  const db=breaks.filter(b=>b.break_date===iso);\n  if(!da.length&&!db.length){el.innerHTML=`<div class="m-empty">Записів немає<br><small>Натисніть кнопку нижче</small></div>`;return;}\n  const items=[...da.map(a=>({t:"a",time:a.start_time,d:a})),...db.map(b=>({t:"b",time:b.start_time,d:b}))].sort((a,b)=>a.time.localeCompare(b.time));\n  el.innerHTML=items.map(i=>{\n    if(i.t==="b")return `<div class="m-slot"><div class="m-time">${i.d.start_time}</div><div class="m-card" style="background:#2A2A30;border-left-color:#78350F;color:#F59E0B">Перерва</div></div>`;\n    const a=i.d;return `<div class="m-slot"><div class="m-time">${a.start_time}</div><div class="m-card" onclick="openDetail(${a.id})"><div class="mc-name">${a.client_name}</div><div class="mc-svc">${a.service}</div><div class="mc-dur">${a.duration_min} хв</div></div></div>`;\n  }).join("");\n}\nfunction changeWeek(d){weekStart=addDays(weekStart,d*7);loadWeek();}\nfunction goToday(){weekStart=getMonday(new Date());mobileDay=new Date();loadWeek();}\nfunction setMobileDay(iso){mobileDay=new Date(iso+"T12:00:00");renderMobileDays(Array.from({length:7},(_,i)=>addDays(weekStart,i)),isoDate(new Date()));renderMobileList();}\nfunction openAddModal(date,time){\n  editingId=null;\n  document.getElementById("modalTitle").textContent="Новий запис";\n  document.getElementById("deleteBtn").classList.add("hidden");\n  document.getElementById("fClient").value="";\n  document.getElementById("fService").value="";\n  document.getElementById("fDate").value=date||isoDate(mobileDay||new Date());\n  document.getElementById("fTime").value=time||"10:00";\n  document.getElementById("fDuration").value="60";\n  document.getElementById("fNotes").value="";\n  document.getElementById("modalOverlay").classList.remove("hidden");\n}\nfunction openAddOnSlot(date,time){openAddModal(date,time);}\nfunction closeModal(){document.getElementById("modalOverlay").classList.add("hidden");}\nfunction openDetail(id){\n  const a=appointments.find(x=>x.id==id);if(!a)return;\n  document.getElementById("detailName").textContent=a.client_name;\n  document.getElementById("detailBody").innerHTML=`<div class="detail-row"><span class="dl">Послуга</span><span class="dv">${a.service}</span></div><div class="detail-row"><span class="dl">Дата</span><span class="dv">${fmtDate(a.appt_date)}</span></div><div class="detail-row"><span class="dl">Час</span><span class="dv">${a.start_time}, ${a.duration_min} хв</span></div>${a.notes?`<div class="detail-row"><span class="dl">Нотатки</span><span class="dv">${a.notes}</span></div>`:""}`;\n  document.getElementById("detailEditBtn").onclick=()=>{\n    editingId=a.id;\n    document.getElementById("modalTitle").textContent="Редагувати";\n    document.getElementById("deleteBtn").classList.remove("hidden");\n    document.getElementById("fClient").value=a.client_name;\n    document.getElementById("fService").value=a.service;\n    document.getElementById("fDate").value=a.appt_date;\n    document.getElementById("fTime").value=a.start_time;\n    document.getElementById("fDuration").value=a.duration_min;\n    document.getElementById("fNotes").value=a.notes||"";\n    closeDetail();\n    document.getElementById("modalOverlay").classList.remove("hidden");\n  };\n  document.getElementById("detailOverlay").classList.remove("hidden");\n}\nfunction closeDetail(){document.getElementById("detailOverlay").classList.add("hidden");}\ndocument.getElementById("modalOverlay").addEventListener("click",e=>{if(e.target===e.currentTarget)closeModal();});\ndocument.getElementById("detailOverlay").addEventListener("click",e=>{if(e.target===e.currentTarget)closeDetail();});\nasync function saveAppt(){\n  const body={master_id:masterId,client_name:document.getElementById("fClient").value.trim(),service:document.getElementById("fService").value.trim(),appt_date:document.getElementById("fDate").value,start_time:document.getElementById("fTime").value,duration_min:parseInt(document.getElementById("fDuration").value),notes:document.getElementById("fNotes").value.trim()};\n  if(!body.client_name||!body.service){alert("Заповніть ім\\u0027я і послугу");return;}\n  const url=editingId?`/api/appointments/${editingId}`:"/api/appointments";\n  const res=await fetch(url,{method:editingId?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});\n  if(!res.ok){const e=await res.json();alert(e.detail||"Помилка");return;}\n  closeModal();showToast(editingId?"Оновлено":"Збережено");\n  mobileDay=new Date(body.appt_date+"T12:00:00");\n  await loadWeek();\n}\nasync function deleteAppt(){\n  if(!editingId||!confirm("Видалити запис?"))return;\n  await fetch(`/api/appointments/${editingId}`,{method:"DELETE"});\n  closeModal();showToast("Видалено");await loadWeek();\n}\nfunction showToast(msg){const t=document.getElementById("toast");t.textContent=msg;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),2500);}\nloadWeek();\n</script>\n</body>\n</html>'

@app.get("/master", response_class=HTMLResponse)
def master_page():
    return MASTER_HTML

