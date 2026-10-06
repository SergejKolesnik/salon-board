import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]


class MultiServiceContractTests(unittest.TestCase):
    def test_schema_and_compatibility_contract_are_present(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS appointment_services", source)
        self.assertIn("service_id INTEGER", source)
        self.assertIn("service_name TEXT NOT NULL", source)
        self.assertIn("service_ids: list[int]", source)
        self.assertIn("Backfill legacy appointments", source)

    def test_master_ui_has_chips_and_catalog_management(self):
        js = (ROOT / "static/js/master.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/master.css").read_text(encoding="utf-8")
        for marker in ("serviceChips", "addSelectedService", "Керування послугами", "/api/services"):
            self.assertIn(marker, js)
        self.assertIn('ensureServicePickerUi(rowOf("fService"))', js)
        self.assertIn(".service-chip", css)

    def test_resolve_services_keeps_requested_order(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "resolve_services")
        namespace = {
            "HTTPException": type("HTTPException", (Exception,), {}),
            "turso": lambda sql, params: [
                {"id": "2", "name": "Пілінг", "price_cents": None, "duration_min": "45"},
                {"id": "1", "name": "Чистка", "price_cents": "1000", "duration_min": "60"},
            ],
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), namespace)
        rows, label = namespace["resolve_services"]([1, 2], "")
        self.assertEqual([row["id"] for row in rows], ["1", "2"])
        self.assertEqual(label, "Чистка + Пілінг")


if __name__ == "__main__":
    unittest.main()
