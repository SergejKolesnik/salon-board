"""Server-side Withings OAuth and measurement import.

The browser never receives a Withings client secret or refresh token.  Imports
are intentionally written as *pending* Body measurements: a salon employee
still has to confirm the reading before it becomes part of a client record.
"""

import hashlib
import json
import os
import secrets
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Cookie, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel


WITHINGS_OAUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
WITHINGS_API_URL = "https://wbsapi.withings.net/v2/measure"
WITHINGS_TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"


class ConnectIn(BaseModel):
    client_id: int


def install_withings_module(app, turso, turso_exec, get_session):
    """Register routes. Missing optional Withings settings only disables OAuth."""
    turso_exec("""CREATE TABLE IF NOT EXISTS withings_connections (
      id TEXT PRIMARY KEY, client_id INTEGER, connection_mode TEXT NOT NULL,
      station_name TEXT, state_hash TEXT UNIQUE, state_expires_at TEXT,
      withings_user_id TEXT, token_ciphertext TEXT, token_expires_at TEXT,
      status TEXT NOT NULL DEFAULT 'awaiting_oauth', created_at TEXT DEFAULT (datetime('now')),
      updated_at TEXT DEFAULT (datetime('now'))
    )""")

    def settings():
        values = {
            "client_id": os.environ.get("WITHINGS_CLIENT_ID", ""),
            "client_secret": os.environ.get("WITHINGS_CLIENT_SECRET", ""),
            "redirect_uri": os.environ.get("WITHINGS_REDIRECT_URI", ""),
            "encryption_key": os.environ.get("WITHINGS_TOKEN_ENCRYPTION_KEY", ""),
        }
        return values

    def configured():
        values = settings()
        if not all(values.values()):
            return False
        try:
            Fernet(values["encryption_key"].encode())
        except (ValueError, TypeError):
            return False
        return True

    def require_login(token):
        current = get_session(token)
        if not current:
            raise HTTPException(401, "Не авторизовано")
        return current

    def require_admin(token):
        current = require_login(token)
        if current.get("role") != "admin":
            raise HTTPException(403, "Підключення Withings налаштовує лише адміністратор")
        return current

    def require_config():
        if not configured():
            raise HTTPException(503, "Withings OAuth ще не налаштовано на сервері")
        return settings()

    def client_exists(client_id):
        rows = turso("SELECT id FROM clients WHERE id=? AND deleted_at IS NULL", [client_id])
        if not rows:
            raise HTTPException(404, "Клієнта не знайдено")

    def encode(payload):
        return Fernet(settings()["encryption_key"].encode()).encrypt(json.dumps(payload).encode()).decode()

    def decode(value):
        try:
            return json.loads(Fernet(settings()["encryption_key"].encode()).decrypt(value.encode()).decode())
        except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(502, "Не вдалося прочитати захищене з’єднання Withings") from exc

    def post_form(url, data):
        body = urllib.parse.urlencode(data).encode()
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except Exception as exc:
            raise HTTPException(502, "Withings тимчасово недоступний") from exc

    def token_for(connection):
        values = settings()
        token = decode(connection["token_ciphertext"])
        expires_at = connection.get("token_expires_at") or ""
        if expires_at and expires_at > datetime.utcnow().replace(microsecond=0).isoformat() + "Z":
            return token["access_token"]
        refreshed = post_form(WITHINGS_TOKEN_URL, {
            "action": "requesttoken", "grant_type": "refresh_token", "client_id": values["client_id"],
            "client_secret": values["client_secret"], "refresh_token": token["refresh_token"],
        })
        if refreshed.get("status") != 0 or not refreshed.get("body", {}).get("access_token"):
            raise HTTPException(502, "Withings не оновив доступ. Підключіть акаунт повторно.")
        token = refreshed["body"]
        expires = (datetime.utcnow() + timedelta(seconds=int(token.get("expires_in", 10800)))).replace(microsecond=0).isoformat() + "Z"
        turso_exec("UPDATE withings_connections SET token_ciphertext=?,token_expires_at=?,updated_at=datetime('now') WHERE id=?", [encode(token), expires, connection["id"]])
        return token["access_token"]

    def read_latest_group(access_token):
        response = post_form(WITHINGS_API_URL, {
            "action": "getmeas", "access_token": access_token,
            "meastypes": "1,5,6,8,76,77,88", "category": "1", "limit": "1",
        })
        if response.get("status") != 0:
            raise HTTPException(502, "Withings не повернув вимір")
        groups = response.get("body", {}).get("measuregrps", [])
        if not groups:
            raise HTTPException(404, "У Withings ще немає нового виміру")
        return groups[0]

    def parse_group(group):
        # Values in the Withings API are stored as value × 10^unit.
        measures = {}
        for measure in group.get("measures", []):
            measures[int(measure.get("type", 0))] = float(measure.get("value", 0)) * (10 ** int(measure.get("unit", 0)))
        weight = measures.get(1)
        if weight is None:
            raise HTTPException(422, "У відповіді Withings немає ваги")
        timestamp = datetime.utcfromtimestamp(int(group.get("date", 0))).replace(microsecond=0).isoformat() + "Z"
        return {
            "weight_kg": round(weight, 2), "fat_percent": measures.get(6),
            "muscle_kg": measures.get(76) or measures.get(77),
            "visceral_fat": measures.get(88), "recorded_at": timestamp,
            "group_id": str(group.get("grpid", group.get("date"))),
        }

    def import_measurement(connection, client_id, session_id=None, station_name="Withings"): 
        if connection.get("status") != "connected":
            raise HTTPException(409, "З’єднання Withings ще не завершено")
        value = parse_group(read_latest_group(token_for(connection)))
        source = "withings:" + connection["id"] + ":" + value["group_id"]
        existing = turso("SELECT id FROM body_measurements WHERE source=?", [source])
        if existing:
            return {"id": existing[0]["id"], "status": "already_pending", "deduplicated": True}
        identifier = str(uuid.uuid4())
        turso_exec("""INSERT INTO body_measurements
          (id,client_id,session_id,station_name,recorded_at,weight_kg,fat_percent,muscle_kg,visceral_fat,source,status)
          VALUES (?,?,?,?,?,?,?,?,?,?,?)""", [identifier, client_id, session_id, station_name, value["recorded_at"], value["weight_kg"], value["fat_percent"], value["muscle_kg"], value["visceral_fat"], source, "pending"])
        return {"id": identifier, "status": "pending", "deduplicated": False}

    @app.get("/api/withings/status")
    def status(token: str = Cookie(default=None)):
        require_login(token)
        return {"configured": configured()}

    @app.post("/api/withings/connect")
    def connect(payload: ConnectIn, token: str = Cookie(default=None)):
        require_admin(token)
        values = require_config()
        client_exists(payload.client_id)
        raw_state = secrets.token_urlsafe(32)
        connection_id = str(uuid.uuid4())
        expires = (datetime.utcnow() + timedelta(minutes=10)).replace(microsecond=0).isoformat() + "Z"
        turso_exec("""INSERT INTO withings_connections (id,client_id,connection_mode,state_hash,state_expires_at,status)
          VALUES (?,?,?,?,?,?)""", [connection_id, payload.client_id, "personal", hashlib.sha256(raw_state.encode()).hexdigest(), expires, "awaiting_oauth"])
        query = urllib.parse.urlencode({"response_type": "code", "client_id": values["client_id"], "redirect_uri": values["redirect_uri"], "scope": "user.metrics", "state": raw_state})
        return {"authorize_url": WITHINGS_OAUTH_URL + "?" + query}

    @app.post("/api/withings/station/connect")
    def connect_station(token: str = Cookie(default=None)):
        """Connect the salon-owned Withings account, never a client account."""
        require_admin(token)
        values = require_config()
        raw_state = secrets.token_urlsafe(32)
        connection_id = str(uuid.uuid4())
        expires = (datetime.utcnow() + timedelta(minutes=10)).replace(microsecond=0).isoformat() + "Z"
        turso_exec("""INSERT INTO withings_connections (id,connection_mode,station_name,state_hash,state_expires_at,status)
          VALUES (?,?,?,?,?,?)""", [connection_id, "station", "Withings BodyScan 2", hashlib.sha256(raw_state.encode()).hexdigest(), expires, "awaiting_oauth"])
        query = urllib.parse.urlencode({"response_type": "code", "client_id": values["client_id"], "redirect_uri": values["redirect_uri"], "scope": "user.metrics", "state": raw_state})
        return {"authorize_url": WITHINGS_OAUTH_URL + "?" + query}

    @app.get("/api/withings/callback")
    def callback(code: str = Query(...), state: str = Query(...)):
        rows = turso("SELECT * FROM withings_connections WHERE state_hash=? AND status='awaiting_oauth'", [hashlib.sha256(state.encode()).hexdigest()])
        if not rows or rows[0].get("state_expires_at", "") <= datetime.utcnow().replace(microsecond=0).isoformat() + "Z":
            raise HTTPException(400, "Посилання на підключення Withings застаріло")
        connection = rows[0]
        values = require_config()
        exchanged = post_form(WITHINGS_TOKEN_URL, {"action": "requesttoken", "grant_type": "authorization_code", "client_id": values["client_id"], "client_secret": values["client_secret"], "code": code, "redirect_uri": values["redirect_uri"]})
        body = exchanged.get("body", {})
        if exchanged.get("status") != 0 or not body.get("access_token") or not body.get("refresh_token"):
            raise HTTPException(502, "Withings не підтвердив доступ")
        expires = (datetime.utcnow() + timedelta(seconds=int(body.get("expires_in", 10800)))).replace(microsecond=0).isoformat() + "Z"
        turso_exec("""UPDATE withings_connections SET withings_user_id=?,token_ciphertext=?,token_expires_at=?,
          status='connected',state_hash=NULL,state_expires_at=NULL,updated_at=datetime('now') WHERE id=?""", [str(body.get("userid", "")), encode(body), expires, connection["id"]])
        return RedirectResponse("/body?withings=connected", status_code=303)

    @app.post("/api/withings/sync/client/{client_id}")
    def sync_client(client_id: int, token: str = Cookie(default=None)):
        require_login(token)
        require_config()
        rows = turso("SELECT * FROM withings_connections WHERE client_id=? AND connection_mode='personal' AND status='connected' ORDER BY updated_at DESC LIMIT 1", [client_id])
        if not rows:
            raise HTTPException(404, "Для цього клієнта немає підключеного Withings")
        return import_measurement(rows[0], client_id, station_name="Особистий Withings")

    @app.post("/api/withings/station/sync")
    def sync_station(token: str = Cookie(default=None)):
        """Import only into the client selected by the currently open salon session."""
        require_login(token)
        require_config()
        sessions = turso("SELECT * FROM body_sessions WHERE status='active' ORDER BY created_at DESC LIMIT 1")
        if not sessions:
            raise HTTPException(409, "Спершу відкрийте сесію зважування для конкретного клієнта")
        current = sessions[0]
        if current.get("expires_at", "") <= datetime.utcnow().replace(microsecond=0).isoformat() + "Z":
            turso_exec("UPDATE body_sessions SET status='expired' WHERE id=?", [current["id"]])
            raise HTTPException(409, "Сесія зважування вже завершилась")
        rows = turso("SELECT * FROM withings_connections WHERE connection_mode='station' AND status='connected' ORDER BY updated_at DESC LIMIT 1")
        if not rows:
            raise HTTPException(404, "Салонний акаунт Withings ще не підключено")
        return import_measurement(rows[0], int(current["client_id"]), current["id"], current["station_name"])
