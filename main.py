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
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --font: 'Nunito', sans-serif;
  --bg: #F7F5F2;
  --surface: #FFFFFF;
  --border: #E4E0DB;
  --text: #1A1916;
  --muted: #6B6860;
  --hint: #A8A49E;
  --accent: #5A4FD6;
  --accent-light: #EEEDFE;
  --accent-text: #3C3489;
  --danger: #D85A30;
  --danger-light: #FAECE7;
  --success: #1D9E75;
  --success-light: #E1F5EE;
  --radius: 10px;
  --radius-sm: 6px;
  --shadow: 0 1px 3px rgba(0,0,0,.08);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; font-family: var(--font); background: var(--bg); color: var(--text); font-size: 14px; }

/* LAYOUT */
.app { display: flex; flex-direction: column; height: 100vh; }
.topbar {
  display: flex; align-items: center; gap: 12px;
  padding: 0 16px; height: 52px;
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
.date-nav .today-btn { background: var(--accent); color: #fff; border-color: var(--accent); }
.date-label { font-size: 15px; font-weight: 700; min-width: 160px; }
.add-btn {
  margin-left: auto;
  background: var(--accent); color: #fff; border: none;
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
.time-col { font-size: 11px; color: var(--hint); text-align: right; padding: 0 8px 0 0; border-right: 1px solid var(--border); display: flex; align-items: flex-start; padding-top: 6px; }
.slot {
  border-right: 1px solid var(--border); border-bottom: 1px solid var(--border);
  min-height: 52px; position: relative; padding: 3px;
  transition: background .1s;
}
.slot:last-child { border-right: none; }
.slot.break-slot { background: repeating-linear-gradient(45deg, var(--bg), var(--bg) 4px, var(--surface) 4px, var(--surface) 8px); }
.slot:not(.break-slot):hover { background: var(--accent-light); cursor: pointer; }
.time-row { display: contents; }
.time-row .time-col { border-bottom: 1px solid var(--border); }

.appt {
  border-radius: var(--radius-sm); padding: 4px 7px; height: 100%;
  display: flex; flex-direction: column; justify-content: center;
  cursor: pointer; transition: filter .1s;
}
.appt:hover { filter: brightness(.95); }
.appt .aname { font-size: 12px; font-weight: 700; }
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
.form-row input:focus, .form-row select:focus, .form-row textarea:focus { border-color: var(--accent); }
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
.m-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.m-list { flex: 1; overflow-y: auto; padding: 12px; }
.m-slot { display: flex; gap: 10px; margin-bottom: 10px; align-items: flex-start; }
.m-time { font-size: 12px; color: var(--hint); min-width: 40px; padding-top: 6px; }
.m-card { flex: 1; border-radius: var(--radius-sm); padding: 8px 10px; cursor: pointer; }
.m-card .mc-name { font-size: 13px; font-weight: 700; }
.m-card .mc-svc { font-size: 12px; opacity: .75; }
.m-card .mc-dur { font-size: 11px; opacity: .6; }
.m-empty { font-size: 12px; color: var(--hint); font-style: italic; padding: 6px 10px; }
.m-fab-wrap { padding: 10px 12px; background: var(--surface); border-top: 1px solid var(--border); flex-shrink: 0; }
.m-fab { width: 100%; padding: 11px; background: var(--accent); color: #fff; border: none; border-radius: var(--radius); font-family: var(--font); font-size: 14px; font-weight: 700; cursor: pointer; }

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
  <h1>cosmo<span>.</span></h1>
  <div class="spacer"></div>
  <span class="desktop-only" style="font-size:12px;color:var(--muted)">косметологічний кабінет</span>
</div>

<!-- DESKTOP -->
<div class="main">
  <aside class="sidebar">
    <div class="sidebar-section">
      <div class="sidebar-label">Майстри</div>
      <div id="masterList"></div>
    </div>
  </aside>
  <div class="content">
    <div class="date-nav">
      <button onclick="changeDate(-1)">‹</button>
      <input type="date" id="datePicker" onchange="pickDate(this.value)" style="padding:5px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);font-family:var(--font);font-size:13px;background:var(--surface);color:var(--text);cursor:pointer;">
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
  // hex -> pastel bg
  const palettes = {
    '#7F77DD': {bg:'#EEEDFE', text:'#3C3489'},
    '#1D9E75': {bg:'#E1F5EE', text:'#085041'},
    '#BA7517': {bg:'#FAEEDA', text:'#633806'},
    '#D85A30': {bg:'#FAECE7', text:'#711B0C'},
    '#378ADD': {bg:'#E6F1FB', text:'#0C447C'},
    '#D4537E': {bg:'#FBEAF0', text:'#72243E'},
  };
  return palettes[hex] || {bg:'#F1EFE8', text:'#2C2C2A'};
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
      <div class="m-card" style="background:var(--bg);color:var(--hint);font-style:italic;padding:8px 10px">Обід / перерва</div>
    </div>`;
    const a = s.appt;
    return `<div class="m-slot">
      <div class="m-time">${a.start_time}</div>
      <div class="m-card" style="background:${pal.bg};color:${pal.text}" onclick="openDetail(${a.id})">
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

// ── INIT ───────────────────────────────────────────────────────────────
loadAll();
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return HTML
