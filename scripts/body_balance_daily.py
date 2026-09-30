import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import turso

CHAT_ID = os.environ.get("BODY_BALANCE_CHAT_ID", "").strip()
KYIV = ZoneInfo("Europe/Kyiv")


def main():
    today = datetime.now(KYIV).strftime("%Y-%m-%d")
    rows = turso(
        """SELECT a.start_time, a.client_name, a.service, m.name AS master_name
           FROM appointments a
           JOIN masters m ON m.id=a.master_id
           WHERE a.appt_date=?
             AND (a.deleted_at IS NULL OR a.deleted_at='')
             AND COALESCE(a.status,'scheduled') NOT IN ('cancelled','canceled')
           ORDER BY a.start_time, a.id""",
        [today],
    )
    if not rows:
        print("No appointments today")
        return
    if not CHAT_ID:
        print("BODY_BALANCE_CHAT_ID is not configured")
        return
    print(f"Daily reminder ready for {len(rows)} appointments")


if __name__ == "__main__":
    main()
