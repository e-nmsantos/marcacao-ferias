from __future__ import annotations

import json
import tempfile
import time
import unittest
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
import gc

from vacation_app.auth import hash_password, validate_user_account
from vacation_app.reports import build_report_rows
from vacation_app.storage import build_data_payload, load_data, parse_payload, save_data
import vacation_app.storage as storage


class StorageAndReportsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        storage.DB_FILE = root / "ferias.db"
        storage.DATA_FILE = root / "data_store.json"
        storage.LOCK_FILE = root / "data_store.lock"

    def tearDown(self) -> None:
        for attempt in range(5):
            try:
                self.temp_dir.cleanup()
                break
            except PermissionError:
                gc.collect()
                time.sleep(0.1)
                if attempt == 4:
                    raise

    def test_legacy_user_without_staff_is_normalized(self) -> None:
        payload = {
            "vacations": [],
            "staff": [],
            "users": {
                "admin": {
                    "password_hash": hash_password("admin123"),
                    "role": "admin",
                    "name": "Administrador",
                    "staff_name": "",
                },
                "maria": {
                    "password_hash": hash_password("maria123"),
                    "role": "user",
                    "name": "Maria",
                    "staff_name": "",
                },
            },
        }
        _, staff, users = parse_payload(payload)
        self.assertEqual(users["maria"]["staff_name"], "Maria")
        self.assertTrue(any(person["Nome"] == "Maria" for person in staff))

    def test_relational_storage_round_trip_preserves_approval_metadata(self) -> None:
        vacations = [
            {
                "id": "vac-1",
                "employee_name": "Mónica Romão",
                "created_by": "monica",
                "team": "Apoio",
                "absence_type": "Férias",
                "start_date": date(2026, 7, 17),
                "end_date": date(2026, 8, 3),
                "status": "approved",
                "half_day": False,
                "replacement_contact": "",
                "reason": "",
                "requested_at": datetime(2026, 4, 23, 10, 0),
                "approved_at": datetime(2026, 4, 24, 9, 30),
                "approved_by": "admin",
            }
        ]
        staff = [{"Nome": "Mónica Romão", "Equipa": "Apoio", "Função": "", "Ativo": True}]
        users = {
            "admin": {
                "password_hash": hash_password("admin123"),
                "role": "admin",
                "name": "Administrador",
                "staff_name": "",
            },
            "monica": {
                "password_hash": hash_password("monica123"),
                "role": "user",
                "name": "Mónica Romão",
                "staff_name": "Mónica Romão",
            },
        }
        save_data(vacations, staff, users)
        loaded_vacations, loaded_staff, loaded_users = load_data()
        self.assertEqual(loaded_users["monica"]["staff_name"], "Mónica Romão")
        self.assertEqual(loaded_staff[0]["Nome"], "Mónica Romão")
        self.assertEqual(loaded_vacations[0]["approved_by"], "admin")
        self.assertEqual(loaded_vacations[0]["approved_at"], datetime(2026, 4, 24, 9, 30))

    def test_load_data_falls_back_to_local_snapshot_when_postgres_fails(self) -> None:
        backup_payload = build_data_payload(
            [],
            [{"Nome": "Ana", "Equipa": "RH", "Função": "", "Ativo": True}],
            {
                "admin": {
                    "password_hash": hash_password("admin123"),
                    "role": "admin",
                    "name": "Administrador",
                    "staff_name": "",
                }
            },
        )
        storage.DATA_FILE.write_text(json.dumps(backup_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        class BrokenConnection:
            def execute(self, *args, **kwargs):
                raise Exception("database unavailable")

        @contextmanager
        def broken_connect_db():
            yield BrokenConnection()

        original_backend = storage.storage_backend
        original_init_db = storage.init_db
        original_connect_db = storage.connect_db
        try:
            storage.storage_backend = lambda: "postgres"
            storage.init_db = lambda: None
            storage.connect_db = broken_connect_db
            vacations, staff, users = load_data()
        finally:
            storage.storage_backend = original_backend
            storage.init_db = original_init_db
            storage.connect_db = original_connect_db

        self.assertEqual(vacations, [])
        self.assertEqual(staff[0]["Nome"], "Ana")
        self.assertIn("admin", users)

    def test_reports_use_clear_columns_and_cross_year_business_days(self) -> None:
        vacations = [
            {
                "id": "vac-2",
                "employee_name": "Mónica Romão",
                "created_by": "monica",
                "team": "Apoio",
                "absence_type": "Férias",
                "start_date": date(2026, 12, 30),
                "end_date": date(2027, 1, 4),
                "status": "approved",
                "half_day": False,
                "replacement_contact": "",
                "reason": "",
                "requested_at": datetime(2026, 11, 1, 9, 0),
                "approved_at": datetime(2026, 11, 2, 9, 15),
                "approved_by": "admin",
            },
            {
                "id": "vac-3",
                "employee_name": "Mónica Romão",
                "created_by": "monica",
                "team": "Apoio",
                "absence_type": "Férias",
                "start_date": date(2026, 8, 1),
                "end_date": date(2026, 8, 3),
                "status": "pending",
                "half_day": False,
                "replacement_contact": "",
                "reason": "",
                "requested_at": datetime(2026, 7, 1, 9, 0),
                "approved_at": None,
                "approved_by": "",
            },
        ]
        rows = build_report_rows(vacations, {}, 2026, 0, "Apoio", ["approved", "pending"])
        approved_row = next(row for row in rows if row["Estado"] == "Aprovado")
        pending_row = next(row for row in rows if row["Estado"] == "Pendente")
        self.assertEqual(approved_row["Dias úteis"], 3)
        self.assertEqual(approved_row["Pedido em"], "01/11/2026 09:00")
        self.assertEqual(approved_row["Aprovado em"], "02/11/2026 09:15")
        self.assertEqual(pending_row["Aprovado em"], "")

    def test_validate_user_requires_existing_staff_for_user_role(self) -> None:
        account = {
            "password_hash": hash_password("user123"),
            "role": "user",
            "name": "Maria",
            "staff_name": "Maria",
        }
        validated = validate_user_account("maria", account, {"Maria"})
        self.assertEqual(validated["staff_name"], "Maria")


if __name__ == "__main__":
    unittest.main()
