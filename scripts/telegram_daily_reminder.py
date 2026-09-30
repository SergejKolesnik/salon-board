import os
from datetime import datetime
from zoneinfo import ZoneInfo

BOT_TOKEN = os.environ.get("BODY_BALANCE_BOT_TOKEN", "")
KYIV_TZ = ZoneInfo("Europe/Kyiv")

if __name__ == "__main__":
    print("telegram reminder placeholder", bool(BOT_TOKEN), datetime.now(KYIV_TZ).isoformat())
