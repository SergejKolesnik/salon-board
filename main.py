"""
Cosmo — розклад косметологічного кабінету
Запуск: uvicorn main:app --reload
"""

import sqlite3, json
from datetime import date, datetime, timedelta
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional

# ─── БД ────────────────────────────────────────────────────────────────────────

DB = "cosmo.db"

@contextmanager
def get_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS masters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT '#7F77DD',
            initials TEXT NOT NULL DEFAULT '??'
        );

        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL REFERENCES masters(id),
            client_name TEXT NOT NULL,
            service TEXT NOT NULL,
            appt_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            duration_min INTEGER NOT NULL DEFAULT 60,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS breaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL REFERENCES masters(id),
            break_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            label TEXT DEFAULT 'Обід'
        );
        """)

        # Демо-дані якщо порожньо
        count = db.execute("SELECT COUNT(*) FROM masters").fetchone()[0]
        if count == 0:
            db.executemany(
                "INSERT INTO masters (name, color, initials) VALUES (?,?,?)",
                [
                    ("Аня Мороз",   "#7F77DD", "АМ"),
                    ("Катя Власюк", "#1D9E75", "КВ"),
                    ("Оля Петренко","#BA7517", "ОП"),
                    ("Діана Сич",   "#D85A30", "ДС"),
                ]
            )
            today = date.today().isoformat()
            db.executemany(
                "INSERT INTO appointments (master_id,client_name,service,appt_date,start_time,duration_min) VALUES (?,?,?,?,?,?)",
                [
                    (1,"Марина К.","Масаж обличчя", today,"09:00",60),
                    (1,"Світлана О.","Брови",        today,"11:00",45),
                    (1,"Олена Ж.","Ін'єкції",        today,"14:00",45),
                    (2,"Лариса Н.","Чистка шкіри",  today,"10:00",60),
                    (2,"Наталя В.","Ліфтинг",        today,"12:00",90),
                    (3,"Тетяна Р.","Ботокс",         today,"09:00",60),
                    (3,"Ірина М.","Мезотерапія",     today,"11:00",60),
                    (4,"Вікторія Б.","Пілінг",       today,"10:00",60),
                    (4,"Юлія Т.","Масаж",            today,"12:00",60),
                    (4,"Галина С.","Чистка",         today,"14:00",60),
                ]
            )
            db.executemany(
                "INSERT INTO breaks (master_id,break_date,start_time,end_time,label) VALUES (?,?,?,?,?)",
                [(i, today, "13:00","14:00","Обід") for i in range(1,5)]
            )


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


# ─── REST API ──────────────────────────────────────────────────────────────────

@app.get("/api/masters")
def list_masters():
    with get_db() as db:
        rows = db.execute("SELECT * FROM masters ORDER BY id").fetchall()
        return [dict(r) for r in rows]

@app.post("/api/masters", status_code=201)
def create_master(m: MasterIn):
    with get_db() as db:
        cur = db.execute("INSERT INTO masters (name,color,initials) VALUES (?,?,?)", (m.name, m.color, m.initials))
        return {"id": cur.lastrowid, **m.dict()}

@app.put("/api/masters/{master_id}")
def update_master(master_id: int, m: MasterIn):
    with get_db() as db:
        existing = db.execute("SELECT * FROM masters WHERE id=?", (master_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Майстра не знайдено")
        db.execute("UPDATE masters SET name=?,color=?,initials=? WHERE id=?",
                   (m.name, m.color, m.initials, master_id))
        return {"id": master_id, **m.dict()}

@app.delete("/api/masters/{master_id}")
def delete_master(master_id: int):
    with get_db() as db:
        db.execute("DELETE FROM appointments WHERE master_id=?", (master_id,))
        db.execute("DELETE FROM breaks WHERE master_id=?", (master_id,))
        db.execute("DELETE FROM masters WHERE id=?", (master_id,))
        return {"ok": True}

@app.get("/api/appointments")
def list_appointments(date: str = None):
    with get_db() as db:
        if date:
            rows = db.execute(
                "SELECT a.*, m.name as master_name, m.color, m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.appt_date=? ORDER BY a.start_time",
                (date,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT a.*, m.name as master_name, m.color, m.initials FROM appointments a JOIN masters m ON a.master_id=m.id ORDER BY a.appt_date, a.start_time"
            ).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/appointments", status_code=201)
def create_appointment(a: AppointmentIn):
    # Перевірка перетину
    with get_db() as db:
        existing = db.execute(
            "SELECT id, start_time, duration_min FROM appointments WHERE master_id=? AND appt_date=?",
            (a.master_id, a.appt_date)
        ).fetchall()

        def to_min(t): h,m = map(int, t.split(":")); return h*60+m
        new_start = to_min(a.start_time)
        new_end   = new_start + a.duration_min

        for row in existing:
            s = to_min(row["start_time"])
            e = s + row["duration_min"]
            if new_start < e and new_end > s:
                raise HTTPException(400, "Цей час вже зайнятий у майстра")

        cur = db.execute(
            "INSERT INTO appointments (master_id,client_name,service,appt_date,start_time,duration_min,notes) VALUES (?,?,?,?,?,?,?)",
            (a.master_id, a.client_name, a.service, a.appt_date, a.start_time, a.duration_min, a.notes)
        )
        row = db.execute("SELECT a.*,m.name as master_name,m.color,m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.id=?", (cur.lastrowid,)).fetchone()
        return dict(row)

@app.put("/api/appointments/{appt_id}")
def update_appointment(appt_id: int, a: AppointmentUpdate):
    with get_db() as db:
        existing = db.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Запис не знайдено")
        data = dict(existing)
        for k, v in a.dict(exclude_none=True).items():
            data[k] = v
        db.execute(
            "UPDATE appointments SET client_name=?,service=?,appt_date=?,start_time=?,duration_min=?,notes=? WHERE id=?",
            (data["client_name"], data["service"], data["appt_date"], data["start_time"], data["duration_min"], data["notes"], appt_id)
        )
        row = db.execute("SELECT a.*,m.name as master_name,m.color,m.initials FROM appointments a JOIN masters m ON a.master_id=m.id WHERE a.id=?", (appt_id,)).fetchone()
        return dict(row)

@app.delete("/api/appointments/{appt_id}")
def delete_appointment(appt_id: int):
    with get_db() as db:
        db.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
        return {"ok": True}

@app.get("/api/breaks")
def list_breaks(date: str = None):
    with get_db() as db:
        if date:
            rows = db.execute("SELECT * FROM breaks WHERE break_date=?", (date,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM breaks").fetchall()
        return [dict(r) for r in rows]


# ─── FRONTEND ──────────────────────────────────────────────────────────────────

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
      <div onclick="openSettingsModal()" style="display:flex;align-items:center;gap:8px;padding:8px 8px;border-radius:8px;cursor:pointer;transition:background .12s" onmouseover="this.style.background='var(--surface2)'" onmouseout="this.style.background=''">
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
    <h2 style="font-family:'Montserrat',sans-serif;margin-bottom:16px">⚙️ Налаштування майстрів</h2>
    <div id="masterEditList" style="margin-bottom:16px"></div>
    <button class="btn" style="width:100%;margin-bottom:8px;border-style:dashed;color:var(--accent);border-color:var(--accent)" onclick="addNewMasterRow()">+ Додати майстра</button>
    <div class="modal-footer">
      <button class="btn" onclick="closeSettings()">Закрити</button>
      <button class="btn btn-primary" onclick="saveMasterSettings()">Зберегти зміни</button>
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

async function loadAll() {
  const dateStr = isoDate(currentDate);
  [masters, appointments, breaks] = await Promise.all([
    fetch('/api/masters').then(r=>r.json()),
    fetch(`/api/appointments?date=${dateStr}`).then(r=>r.json()),
    fetch(`/api/breaks?date=${dateStr}`).then(r=>r.json()),
  ]);
  if (visibleMasters.size === 0) masters.forEach(m => visibleMasters.add(m.id));
  if (!mobileMasterId && masters.length) mobileMasterId = masters[0].id;
  renderAll();
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
  document.getElementById('detailEditBtn').onclick = () => openEditModal(a);
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
    const initials = m.name.split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase() || '??';
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

// ── INIT ───────────────────────────────────────────────────────────────
loadAll();
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return HTML
