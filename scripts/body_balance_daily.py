"""Daily Body Balance reminder delivery.

The database and Telegram transport are injected so the reminder logic can be
tested without touching production data or sending real messages.
"""

import json
import os
import urllib.request
from datetime import datetime
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo


KYIV = ZoneInfo("Europe/Kyiv")
CHAT_ID = os.environ.get("BODY_BALANCE_CHAT_ID", "889237260").strip()
BOT_TOKEN_ENV = "BODY_BALANCE_BOT_TOKEN"


def format_reminder(rows: Sequence[Mapping[str, object]]) -> str:
    """Build one human-readable message for all appointments."""
    lines = ["🔔 Body Balance — записи на сьогодні", ""]
    for row in rows:
        master = f" — майстер {row['master_name']}" if row.get("master_name") else ""
        lines.append(
            f"{row.get('start_time', '')} — {row.get('client_name', '')} — "
            f"{row.get('service', '')}{master}"
        )
    lines.extend(["", f"Всього записів: {len(rows)}"])
    return "\n".join(lines)


def send_telegram_message(token: str, chat_id: str, text: str) -> None:
    """Send a message through Telegram without logging the bot token."""
    payload = json.dumps({"chat_id": chat_id, "text": text}, ensure_ascii=False).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the reminder")


def run_daily_reminder(
    query: Callable[[str, list], list],
    execute: Callable[[str, list], object],
    *,
    now: datetime | None = None,
    send: Callable[[str, str, str], None] = send_telegram_message,
) -> dict:
    """Send today's reminder once and record the successful delivery.

    The delivery marker is written only after Telegram accepts the message, so
    a failed send can be retried safely. Sequential repeated calls are no-ops.
    """
    current = (now or datetime.now(KYIV)).astimezone(KYIV)
    day = current.strftime("%Y-%m-%d")
    rows = query(
        """SELECT a.start_time, a.client_name, a.service, m.name AS master_name
           FROM appointments a
           JOIN masters m ON m.id = a.master_id
           WHERE a.appt_date = ?
             AND (a.deleted_at IS NULL OR a.deleted_at = '')
             AND COALESCE(a.status, 'scheduled') NOT IN ('cancelled', 'canceled')
           ORDER BY a.start_time, a.id""",
        [day],
    )
    if not rows:
        return {"sent": False, "reason": "no_appointments", "date": day}

    marker = f"body_balance_reminder_sent:{day}"
    if query("SELECT value FROM settings WHERE key = ?", [marker]):
        return {"sent": False, "reason": "already_sent", "date": day}

    token = os.environ.get(BOT_TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError(f"{BOT_TOKEN_ENV} is not configured")
    if not CHAT_ID:
        raise RuntimeError("BODY_BALANCE_CHAT_ID is not configured")

    send(token, CHAT_ID, format_reminder(rows))
    execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", [marker, current.isoformat()])
    return {"sent": True, "date": day, "count": len(rows)}


if __name__ == "__main__":
    from main import turso, turso_exec

    print(run_daily_reminder(turso, turso_exec))
