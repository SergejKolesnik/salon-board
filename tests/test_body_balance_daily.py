import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.body_balance_daily import run_daily_reminder


class BodyBalanceReminderTests(unittest.TestCase):
    def setUp(self):
        os.environ["BODY_BALANCE_BOT_TOKEN"] = "test-token"

    def test_sends_once_and_deduplicates(self):
        settings = {}
        sent = []
        rows = [{"start_time": "10:30", "client_name": "Анна", "service": "Масаж", "master_name": "Оксана"}]

        def query(sql, params):
            if "FROM appointments" in sql:
                return rows
            return [{"value": settings[params[0]]}] if params[0] in settings else []

        def execute(sql, params):
            settings[params[0]] = params[1]

        now = datetime(2026, 10, 1, 10, 0, tzinfo=ZoneInfo("Europe/Kyiv"))
        first = run_daily_reminder(query, execute, now=now, send=lambda *args: sent.append(args))
        second = run_daily_reminder(query, execute, now=now, send=lambda *args: sent.append(args))

        self.assertTrue(first["sent"])
        self.assertEqual(second["reason"], "already_sent")
        self.assertEqual(len(sent), 1)
        self.assertIn("Всього записів: 1", sent[0][2])

    def test_no_appointments_does_not_send(self):
        sent = []
        result = run_daily_reminder(
            lambda sql, params: [],
            lambda sql, params: None,
            now=datetime(2026, 10, 1, tzinfo=ZoneInfo("Europe/Kyiv")),
            send=lambda *args: sent.append(args),
        )
        self.assertEqual(result["reason"], "no_appointments")
        self.assertFalse(sent)


if __name__ == "__main__":
    unittest.main()
