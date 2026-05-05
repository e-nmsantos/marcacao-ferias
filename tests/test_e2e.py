"""End-to-end tests for vacation app workflow."""

import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

import pytest

from vacation_app.auth import hash_password, verify_password
from vacation_app.calendar_utils import calculate_business_days, calculate_days, portugal_holidays
from vacation_app.constants import ABSENCE_TYPES
from vacation_app.storage import (
    load_data,
    save_data,
)


@pytest.fixture
def temp_db():
    """Create temporary data store for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "data_store.json"
        # Create empty store
        initial_data = {
            "vacations": [],
            "staff": [],
            "users": {"admin": {"name": "Admin", "role": "admin", "password_hash": "", "staff_name": ""}},
        }
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, ensure_ascii=False, indent=2, default=str)
        
        # Temporarily override the data store path
        original_path = os.environ.get("DATA_STORE_PATH")
        os.environ["DATA_STORE_PATH"] = str(db_path)
        yield db_path
        # Restore original path
        if original_path:
            os.environ["DATA_STORE_PATH"] = original_path
        else:
            os.environ.pop("DATA_STORE_PATH", None)


class TestE2EWorkflow:
    """End-to-end workflow tests: login → request → approve → report."""

    def test_complete_vacation_workflow(self, temp_db):
        """Test full vacation request workflow."""
        # Step 1: Add staff member
        staff = [
            {
                "Nome": "João Silva",
                "Equipa": "Tech",
                "Função": "Developer",
                "Ativo": True,
            }
        ]

        # Step 2: Create login for user
        users = {
            "joao_silva": {
                "name": "João Silva",
                "role": "user",
                "password_hash": hash_password("senha123"),
                "staff_name": "João Silva",
            },
            "admin": {
                "name": "Admin User",
                "role": "admin",
                "password_hash": hash_password("admin123"),
                "staff_name": "",
            },
        }

        # Step 3: Verify password works
        assert verify_password("senha123", users["joao_silva"]["password_hash"])
        assert not verify_password("wrong_pass", users["joao_silva"]["password_hash"])

        # Step 4: Save initial data
        vacations = []
        save_data(vacations, staff, users)

        # Step 5: Create a vacation request
        request_id = "test-vacation-1"
        vacation = {
            "id": request_id,
            "employee_name": "João Silva",
            "team": "Tech",
            "absence_type": "Férias",
            "start_date": date(2026, 5, 15),
            "end_date": date(2026, 5, 22),
            "status": "pending",
            "half_day": False,
            "replacement_contact": "Maria",
            "reason": "Férias pessoais",
            "requested_at": datetime.now(),
            "approved_at": None,
            "approved_by": "",
            "created_by": "joao_silva",
        }
        vacations.append(vacation)
        save_data(vacations, staff, users)

        # Step 6: Load and verify request exists
        loaded_vacations, _, _ = load_data()
        assert len(loaded_vacations) == 1
        assert loaded_vacations[0]["employee_name"] == "João Silva"
        assert loaded_vacations[0]["status"] == "pending"

        # Step 7: Approve request (admin action)
        for v in loaded_vacations:
            if v["id"] == request_id:
                v["status"] = "approved"
                v["approved_at"] = datetime.now()
                v["approved_by"] = "admin"
        save_data(loaded_vacations, staff, users)

        # Step 8: Verify approval
        loaded_vacations, _, _ = load_data()
        assert loaded_vacations[0]["status"] == "approved"
        assert loaded_vacations[0]["approved_by"] == "admin"

        # Step 9: Calculate vacation metrics
        total_days = calculate_days(vacation["start_date"], vacation["end_date"])
        holidays = portugal_holidays(2026, "Nenhum")
        business_days = calculate_business_days(vacation["start_date"], vacation["end_date"], holidays)

        assert total_days == 8  # 15-22 Maio (inclusive)
        assert business_days > 0  # Should have business days

        # Step 10: Verify persistence
        loaded_vacations, loaded_staff, loaded_users = load_data()
        assert len(loaded_vacations) == 1
        assert loaded_vacations[0]["id"] == request_id
        assert loaded_staff == staff
        assert "joao_silva" in loaded_users

    def test_multiple_vacation_requests(self, temp_db):
        """Test handling multiple concurrent vacation requests."""
        staff = [
            {"Nome": "João Silva", "Equipa": "Tech", "Função": "Dev", "Ativo": True},
            {"Nome": "Maria Santos", "Equipa": "HR", "Função": "Manager", "Ativo": True},
        ]

        users = {
            "admin": {
                "name": "Admin",
                "role": "admin",
                "password_hash": hash_password("admin123"),
                "staff_name": "",
            },
            "joao": {
                "name": "João Silva",
                "role": "user",
                "password_hash": hash_password("pass"),
                "staff_name": "João Silva",
            },
            "maria": {
                "name": "Maria Santos",
                "role": "user",
                "password_hash": hash_password("pass"),
                "staff_name": "Maria Santos",
            },
        }

        # Create overlapping vacation requests
        vacations = [
            {
                "id": "vac-1",
                "employee_name": "João Silva",
                "team": "Tech",
                "absence_type": "Férias",
                "start_date": date(2026, 5, 15),
                "end_date": date(2026, 5, 20),
                "status": "approved",
                "half_day": False,
                "replacement_contact": "",
                "reason": "",
                "requested_at": datetime.now(),
                "approved_at": datetime.now(),
                "approved_by": "admin",
                "created_by": "joao",
            },
            {
                "id": "vac-2",
                "employee_name": "Maria Santos",
                "team": "HR",
                "absence_type": "Férias",
                "start_date": date(2026, 5, 18),
                "end_date": date(2026, 5, 25),
                "status": "pending",
                "half_day": False,
                "replacement_contact": "",
                "reason": "",
                "requested_at": datetime.now(),
                "approved_at": None,
                "approved_by": "",
                "created_by": "maria",
            },
        ]

        save_data(vacations, staff, users)
        loaded_vacations, _, _ = load_data()

        assert len(loaded_vacations) == 2
        assert sum(1 for v in loaded_vacations if v["status"] == "approved") == 1
        assert sum(1 for v in loaded_vacations if v["status"] == "pending") == 1

    def test_absence_type_handling(self, temp_db):
        """Test different absence types."""
        staff = [{"Nome": "Test User", "Equipa": "General", "Função": "Staff", "Ativo": True}]
        users = {
            "admin": {
                "name": "Admin",
                "role": "admin",
                "password_hash": hash_password("admin123"),
                "staff_name": "",
            },
            "test": {
                "name": "Test User",
                "role": "user",
                "password_hash": hash_password("pass"),
                "staff_name": "Test User",
            },
        }

        vacations = []
        for absence_type in ABSENCE_TYPES:
            vacations.append(
                {
                    "id": f"vac-{absence_type}",
                    "employee_name": "Test User",
                    "team": "General",
                    "absence_type": absence_type,
                    "start_date": date(2026, 6, 1),
                    "end_date": date(2026, 6, 5),
                    "status": "approved",
                    "half_day": False,
                    "replacement_contact": "",
                    "reason": "",
                    "requested_at": datetime.now(),
                    "approved_at": datetime.now(),
                    "approved_by": "admin",
                    "created_by": "test",
                }
            )

        save_data(vacations, staff, users)
        loaded_vacations, _, _ = load_data()

        assert len(loaded_vacations) == len(ABSENCE_TYPES)
        for vac in loaded_vacations:
            assert vac["absence_type"] in ABSENCE_TYPES
