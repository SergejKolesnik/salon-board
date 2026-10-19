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

    def test_master_can_create_and_select_client_without_resetting_appointment(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        js = (ROOT / "static/js/master.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/master.css").read_text(encoding="utf-8")
        worker = (ROOT / "static/sw.js").read_text(encoding="utf-8")

        self.assertIn('@app.post("/api/clients", status_code=201)', source)
        self.assertIn('button.textContent="+ Додати клієнта"', js)
        self.assertIn('fetch("/api/clients",{method:"POST"', js)
        self.assertIn('selectClient(Number(client.id),fullName,client.phone||"")', js)
        self.assertNotIn('openAddModal(', js[js.index("async function saveNewClient"):])
        self.assertIn(".add-client-btn", css)
        self.assertIn('salon-board-shell-v16', worker)

    def test_mobile_appointment_actions_client_picker_and_calendar_cues(self):
        js = (ROOT / "static/js/master.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/master.css").read_text(encoding="utf-8")

        self.assertIn('[onclick*="closeModal"]', js)
        self.assertIn('safeOn("fClient","focus",showRecentClients)', js)
        self.assertIn('fetch("/api/clients")', js)
        self.assertIn("appointmentCountLabel", js)
        self.assertIn("autoPositionVisibleMobileDay", js)
        self.assertIn("mobileDaysAutoPositioned", js)
        self.assertIn(".cal-day-count", css)
        self.assertIn("grid-template-columns:minmax(0,1fr) minmax(0,1fr)", css)

    def test_client_selection_sorting_and_optional_detail_reminders(self):
        js = (ROOT / "static/js/master.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/master.css").read_text(encoding="utf-8")

        suggestions = js[js.index("function showClientSuggestions"):js.index("function hideClientSuggestions")]
        self.assertIn('item.addEventListener("click"', suggestions)
        self.assertNotIn('onclick="selectClient', suggestions)
        self.assertIn('localeCompare(b.name,"uk"', js)
        self.assertIn("missingDetails", js)
        self.assertIn("Телефон і дата народження бажані", js)
        self.assertIn(".new-client-hint", css)

    def test_contact_picker_and_duplicate_phone_reuse(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        js = (ROOT / "static/js/master.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/master.css").read_text(encoding="utf-8")

        self.assertIn('navigator.contacts.select(contactPickerProperties,{multiple:false})', js)
        self.assertIn('window.isSecureContext&&"contacts" in navigator', js)
        self.assertIn('id="contactPickerBtn"', js)
        self.assertNotIn('class="contact-picker-btn hidden"', js)
        self.assertIn("Відкрийте сайт salon-board.onrender.com у Google Chrome", js)
        self.assertIn("findClientByExactPhone", js)
        self.assertIn('res.status===409&&payload.phone', js)
        self.assertIn('id="appointmentContactBtn"', js)
        self.assertIn("pickAppointmentContact", js)
        self.assertIn("Клієнта знайдено в базі та додано до запису", js)
        appointment_picker = js[js.index("async function pickAppointmentContact"):js.index("function ensureClientCreatorUi")]
        self.assertIn('fetch("/api/clients",{method:"POST"', appointment_picker)
        self.assertIn("Клієнта додано до бази й поточного запису", appointment_picker)
        self.assertIn("selectClient(Number(client.id)", appointment_picker)
        self.assertIn(".contact-picker-btn", css)
        self.assertIn(".client-entry-actions", css)
        self.assertIn("WHERE c.deleted_at IS NULL", source)
        self.assertIn("WHERE deleted_at IS NULL AND (", source)

    def test_phone_normalization_contract(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "normalize_phone")
        namespace = {"re": __import__("re")}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), namespace)
        normalize = namespace["normalize_phone"]

        for value in ("050 123 45 67", "+38 (050) 123-45-67", "380501234567", "80501234567", "501234567"):
            self.assertEqual(normalize(value), "+380501234567")
        self.assertEqual(normalize(""), "")
        self.assertEqual(normalize("+48 123 456 789"), "+48 123 456 789")
        self.assertIn("Normalize existing client phones", source)
        self.assertIn('normalize_phone(data.get("phone") or "")', source)

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
