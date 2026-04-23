from __future__ import annotations

import base64
import hashlib
import hmac
import os

from vacation_app.constants import EMPLOYEE_NAME_ALIASES, PASSWORD_ITERATIONS


class DataStoreError(RuntimeError):
    pass


def build_password_hash(password: str, *, salt_b64: str, iterations: int = PASSWORD_ITERATIONS) -> str:
    salt = base64.b64decode(salt_b64)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt_b64}${base64.b64encode(digest).decode('ascii')}"


def hash_password(password: str) -> str:
    salt = base64.b64encode(os.urandom(16)).decode("ascii")
    return build_password_hash(password, salt_b64=salt, iterations=PASSWORD_ITERATIONS)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_b64, _ = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected_hash = build_password_hash(password, salt_b64=salt_b64, iterations=int(iterations_text))
    except Exception:
        return False
    return hmac.compare_digest(expected_hash, stored_hash)


def normalize_employee_name(name: str) -> str:
    return EMPLOYEE_NAME_ALIASES.get(name.strip(), name.strip())


def validate_user_account(username: str, item: dict, staff_names: set[str] | None = None) -> dict:
    if not isinstance(item, dict):
        raise DataStoreError("Conta de login inválida.")
    normalized_username = username.strip().lower()
    if not normalized_username:
        raise DataStoreError("Cada login precisa de utilizador.")
    role = str(item.get("role", "")).strip().lower()
    if role not in {"admin", "user", "viewer"}:
        raise DataStoreError(f"Role inválida para login {normalized_username}.")
    name = str(item.get("name", "")).strip()
    if not name:
        raise DataStoreError(f"O login {normalized_username} precisa de um nome.")
    password_hash = str(item.get("password_hash", "")).strip()
    if not password_hash:
        raise DataStoreError(f"O login {normalized_username} precisa de password.")
    if not verify_password("__validation_probe__", password_hash) and not password_hash.startswith("pbkdf2_sha256$"):
        raise DataStoreError(f"Password inválida para login {normalized_username}.")
    staff_name = normalize_employee_name(str(item.get("staff_name", "")).strip())
    if role == "user":
        if not staff_name:
            raise DataStoreError(f"O login {normalized_username} precisa de um colaborador associado.")
        if staff_names is not None and staff_name not in staff_names:
            raise DataStoreError(f"O login {normalized_username} referencia um colaborador inexistente: {staff_name}.")
    return {
        "password_hash": password_hash,
        "role": role,
        "name": name,
        "staff_name": staff_name,
    }
