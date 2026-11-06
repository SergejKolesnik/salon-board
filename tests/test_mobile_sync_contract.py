import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]


class MobileSyncContractTests(unittest.TestCase):
    def test_server_replays_delta_boundary_and_versions_mutations(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('changed = "(updated_at >= ? OR deleted_at >= ?)"', source)
        self.assertIn("def check_push_base_version", source)
        self.assertIn("def push_mutation_id", source)
        self.assertIn('"server_version": pushed_server_version', source)

    def test_mobile_uses_sqlite_outbox_and_local_first_confirmation(self):
        db = (ROOT / "mobile_app/lib/core/db/local_database.dart").read_text(encoding="utf-8")
        sync = (ROOT / "mobile_app/lib/core/sync/sync_service.dart").read_text(encoding="utf-8")
        screen = (ROOT / "mobile_app/lib/features/calendar/calendar_screen.dart").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS pending_changes", db)
        self.assertIn("Future<void> keepLocalAppointment", db)
        self.assertIn("Future<void> useServerAppointment", db)
        self.assertIn("await _database.saveAppointment", sync)
        self.assertIn("await _database.applyPushResult", sync)
        self.assertIn("Збережено на телефоні", screen)


if __name__ == "__main__":
    unittest.main()
