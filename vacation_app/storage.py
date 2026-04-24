from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import date, datetime
from urllib.parse import urlparse

from vacation_app.auth import DataStoreError, normalize_employee_name, validate_user_account
from vacation_app.constants import DATA_FILE, DATA_VERSION, DB_FILE, DEFAULT_USERS, LOCK_FILE

POSTGRES_LOCK_KEY = 987654321
_POSTGRES_LOCK_CONNECTION = None


def _read_streamlit_secret() -> str:
    try:
        import streamlit as st
    except Exception:
        return ""
    try:
        if "DATABASE_URL" in st.secrets:
            return str(st.secrets["DATABASE_URL"]).strip()
        database_section = st.secrets.get("database")
        if database_section and "url" in database_section:
            return str(database_section["url"]).strip()
    except Exception:
        return ""
    return ""


def get_database_url() -> str:
    for key in ("DATABASE_URL", "POSTGRES_URL"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return _read_streamlit_secret()


def storage_backend() -> str:
    database_url = get_database_url()
    if database_url:
        scheme = urlparse(database_url).scheme.lower()
        if scheme in {"postgres", "postgresql"}:
            return "postgres"
    return "sqlite"


def has_external_storage() -> bool:
    return storage_backend() == "postgres"


def has_storage_source() -> bool:
    return has_external_storage() or DB_FILE.exists() or DATA_FILE.exists()


def serialize_date(value: date) -> str:
    return value.isoformat()


def serialize_dt(value: datetime) -> str:
    return value.isoformat()


def validate_staff_member(item: dict) -> dict:
    if not isinstance(item, dict):
        raise DataStoreError("Registo de colaborador inválido.")
    name = normalize_employee_name(str(item.get("Nome", "")).strip())
    if not name:
        raise DataStoreError("Cada colaborador precisa de um nome.")
    return {
        "Nome": name,
        "Equipa": str(item.get("Equipa", "")).strip(),
        "Função": str(item.get("Função", item.get("Funcao", ""))).strip(),
        "Ativo": bool(item.get("Ativo", True)),
    }


def validate_staff_list(items: object) -> list[dict]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise DataStoreError("A lista de colaboradores está num formato inválido.")
    cleaned: list[dict] = []
    seen: set[str] = set()
    for raw in items:
        staff_member = validate_staff_member(raw)
        normalized_name = staff_member["Nome"].lower()
        if normalized_name in seen:
            raise DataStoreError(f"Colaborador duplicado no armazenamento: {staff_member['Nome']}.")
        seen.add(normalized_name)
        cleaned.append(staff_member)
    return cleaned


def deserialize_vacation(item: dict) -> dict:
    if not isinstance(item, dict):
        raise DataStoreError("Pedido de férias inválido.")
    out = dict(item)
    out["start_date"] = date.fromisoformat(item["start_date"])
    out["end_date"] = date.fromisoformat(item["end_date"])
    out["requested_at"] = datetime.fromisoformat(item["requested_at"])
    approved_at = item.get("approved_at")
    out["approved_at"] = datetime.fromisoformat(approved_at) if approved_at else None
    if out["end_date"] < out["start_date"]:
        raise DataStoreError("Pedido com intervalo de datas inválido.")
    if out.get("status") not in {"pending", "approved", "rejected"}:
        raise DataStoreError("Pedido com estado inválido.")
    out["employee_name"] = normalize_employee_name(str(item.get("employee_name", "")).strip())
    if not out["employee_name"]:
        raise DataStoreError("Pedido sem nome de colaborador.")
    out["half_day"] = bool(item.get("half_day", False))
    out["created_by"] = str(item.get("created_by", "")).strip()
    out["team"] = str(item.get("team", "")).strip()
    out["absence_type"] = str(item.get("absence_type", "Férias")).strip() or "Férias"
    out["replacement_contact"] = str(item.get("replacement_contact", "")).strip()
    out["reason"] = str(item.get("reason", "")).strip()
    out["approved_by"] = str(item.get("approved_by", "")).strip()
    if out["status"] != "approved":
        out["approved_at"] = None
        out["approved_by"] = ""
    if out["employee_name"] == "Mónica Romão" and not out["team"]:
        out["team"] = "Apoio"
    return out


def serialize_vacation(item: dict) -> dict:
    return {
        **item,
        "start_date": serialize_date(item["start_date"]),
        "end_date": serialize_date(item["end_date"]),
        "requested_at": serialize_dt(item["requested_at"]),
        "approved_at": serialize_dt(item["approved_at"]) if item.get("approved_at") else None,
    }


def ensure_user_staff_links(staff: list[dict], users: dict[str, dict]) -> tuple[list[dict], dict[str, dict]]:
    staff_by_name = {member["Nome"].casefold(): dict(member) for member in validate_staff_list(staff)}
    normalized_users: dict[str, dict] = {}
    for username, raw in users.items():
        account = dict(raw)
        role = str(account.get("role", "")).strip().lower()
        staff_name = normalize_employee_name(str(account.get("staff_name", "")).strip())
        if role == "user" and not staff_name:
            candidate = normalize_employee_name(str(account.get("name", "")).strip())
            staff_name = candidate
        if role == "user" and staff_name:
            key = staff_name.casefold()
            if key not in staff_by_name:
                staff_by_name[key] = {"Nome": staff_name, "Equipa": "", "Função": "", "Ativo": True}
            account["staff_name"] = staff_by_name[key]["Nome"]
        else:
            account["staff_name"] = staff_name
        normalized_users[str(username).strip().lower()] = account
    cleaned_staff = sorted(staff_by_name.values(), key=lambda item: item["Nome"].casefold())
    return cleaned_staff, normalized_users


def validate_users_map(items: object, staff: list[dict]) -> dict[str, dict]:
    source = DEFAULT_USERS if items is None else items
    if not isinstance(source, dict):
        raise DataStoreError("A lista de logins está num formato inválido.")
    staff_names = {member["Nome"] for member in staff}
    cleaned: dict[str, dict] = {}
    for username, raw in source.items():
        normalized_username = str(username).strip().lower()
        cleaned[normalized_username] = validate_user_account(normalized_username, raw, staff_names)
    if "admin" not in cleaned:
        raise DataStoreError("Tem de existir pelo menos uma conta administradora.")
    return cleaned


def parse_payload(payload: object) -> tuple[list[dict], list[dict], dict[str, dict]]:
    if payload is None:
        return [], [], validate_users_map(None, [])
    if not isinstance(payload, dict):
        raise DataStoreError("O ficheiro de dados não contém um objeto JSON válido.")
    vacations_raw = payload.get("vacations", [])
    if not isinstance(vacations_raw, list):
        raise DataStoreError("A lista de pedidos está num formato inválido.")
    vacations = [deserialize_vacation(item) for item in vacations_raw]
    staff = validate_staff_list(payload.get("staff", []))
    users_raw = DEFAULT_USERS if payload.get("users") is None else payload.get("users")
    staff, users_raw = ensure_user_staff_links(staff, users_raw)
    users = validate_users_map(users_raw, staff)
    return vacations, staff, users


def build_data_payload(vacations: list[dict], staff: list[dict], users: dict[str, dict]) -> dict:
    return {
        "version": DATA_VERSION,
        "exported_at": datetime.now().isoformat(),
        "vacations": [serialize_vacation(item) for item in vacations],
        "staff": staff,
        "users": users,
    }


def load_json_data() -> tuple[list[dict], list[dict], dict[str, dict]]:
    if not DATA_FILE.exists():
        return [], [], validate_users_map(None, [])
    try:
        payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataStoreError(f"Não foi possível ler {DATA_FILE.name}: JSON inválido.") from exc
    except OSError as exc:
        raise DataStoreError(f"Não foi possível ler {DATA_FILE.name}.") from exc
    try:
        return parse_payload(payload)
    except Exception as exc:
        if isinstance(exc, DataStoreError):
            raise
        raise DataStoreError("Estrutura de dados inválida no armazenamento.") from exc


def connect_db():
    if storage_backend() == "postgres":
        database_url = get_database_url()
        if not database_url:
            raise DataStoreError("DATABASE_URL não configurada para armazenamento externo.")
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as exc:
            raise DataStoreError("A dependência psycopg não está instalada.") from exc
        connection = psycopg.connect(database_url, row_factory=dict_row)
        return connection
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with connect_db() as connection:
        if storage_backend() == "postgres":
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS staff (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    team TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    active BOOLEAN NOT NULL DEFAULT TRUE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    name TEXT NOT NULL,
                    staff_id BIGINT NULL REFERENCES staff(id) ON DELETE SET NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vacations (
                    id TEXT PRIMARY KEY,
                    employee_name TEXT NOT NULL,
                    staff_id BIGINT NULL REFERENCES staff(id) ON DELETE SET NULL,
                    created_by TEXT NULL DEFAULT '',
                    team TEXT NOT NULL DEFAULT '',
                    absence_type TEXT NOT NULL DEFAULT 'Férias',
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    half_day BOOLEAN NOT NULL DEFAULT FALSE,
                    replacement_contact TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    requested_at TEXT NOT NULL,
                    approved_at TEXT NULL,
                    approved_by TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT '',
                    happened_at TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_state (
                    id INTEGER PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        else:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS staff (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    team TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    name TEXT NOT NULL,
                    staff_id INTEGER NULL,
                    FOREIGN KEY (staff_id) REFERENCES staff(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS vacations (
                    id TEXT PRIMARY KEY,
                    employee_name TEXT NOT NULL,
                    staff_id INTEGER NULL,
                    created_by TEXT NULL DEFAULT '',
                    team TEXT NOT NULL DEFAULT '',
                    absence_type TEXT NOT NULL DEFAULT 'Férias',
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    half_day INTEGER NOT NULL DEFAULT 0,
                    replacement_contact TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    requested_at TEXT NOT NULL,
                    approved_at TEXT NULL,
                    approved_by TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (staff_id) REFERENCES staff(id) ON DELETE SET NULL,
                    FOREIGN KEY (created_by) REFERENCES users(username) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT '',
                    happened_at TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS app_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
        connection.commit()


def _has_relational_rows(connection: sqlite3.Connection) -> bool:
    return any(
        connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        for table in ("staff", "users", "vacations")
    )


def _load_legacy_db_data(connection: sqlite3.Connection) -> tuple[list[dict], list[dict], dict[str, dict]] | None:
    row = connection.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload"])
    return parse_payload(payload)


def _load_relational_data(connection: sqlite3.Connection) -> tuple[list[dict], list[dict], dict[str, dict]]:
    staff_order_sql = "SELECT name, team, role, active FROM staff ORDER BY LOWER(name), name"
    if storage_backend() == "sqlite":
        staff_order_sql = "SELECT name, team, role, active FROM staff ORDER BY name COLLATE NOCASE"
    staff_rows = connection.execute(
        staff_order_sql
    ).fetchall()
    staff = [
        {
            "Nome": row["name"],
            "Equipa": row["team"],
            "Função": row["role"],
            "Ativo": bool(row["active"]),
        }
        for row in staff_rows
    ]
    user_rows = connection.execute(
        """
        SELECT users.username, users.password_hash, users.role, users.name, staff.name AS staff_name
        FROM users
        LEFT JOIN staff ON staff.id = users.staff_id
        ORDER BY users.username
        """
    ).fetchall()
    users = {
        row["username"]: {
            "password_hash": row["password_hash"],
            "role": row["role"],
            "name": row["name"],
            "staff_name": row["staff_name"] or "",
        }
        for row in user_rows
    }
    vacation_rows = connection.execute(
        """
        SELECT id, employee_name, created_by, team, absence_type, start_date, end_date, status,
               half_day, replacement_contact, reason, requested_at, approved_at, approved_by
        FROM vacations
        ORDER BY requested_at DESC
        """
    ).fetchall()
    vacations = [
        deserialize_vacation(
            {
                "id": row["id"],
                "employee_name": row["employee_name"],
                "created_by": row["created_by"],
                "team": row["team"],
                "absence_type": row["absence_type"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "status": row["status"],
                "half_day": bool(row["half_day"]),
                "replacement_contact": row["replacement_contact"],
                "reason": row["reason"],
                "requested_at": row["requested_at"],
                "approved_at": row["approved_at"],
                "approved_by": row["approved_by"],
            }
        )
        for row in vacation_rows
    ]
    staff, users = ensure_user_staff_links(staff, users)
    users = validate_users_map(users, staff)
    return vacations, staff, users


def get_storage_token() -> str | None:
    if storage_backend() == "sqlite" and not DB_FILE.exists() and not DATA_FILE.exists():
        return None
    try:
        init_db()
        with connect_db() as connection:
            row = connection.execute("SELECT updated_at FROM app_state WHERE id = 1").fetchone()
            return None if row is None else str(row["updated_at"])
    except Exception:
        if storage_backend() == "sqlite" and DB_FILE.exists():
            return str(DB_FILE.stat().st_mtime_ns)
        return None


def save_data(vacations: list[dict], staff: list[dict], users: dict[str, dict]) -> None:
    validated_staff = validate_staff_list(staff)
    normalized_staff, normalized_users = ensure_user_staff_links(validated_staff, users)
    validated_users = validate_users_map(normalized_users, normalized_staff)
    serialized_vacations = [deserialize_vacation(serialize_vacation(item)) for item in vacations]
    init_db()
    backend = storage_backend()
    payload_text = json.dumps(build_data_payload(serialized_vacations, normalized_staff, validated_users), ensure_ascii=False, indent=2)
    updated_at = datetime.now().isoformat()
    with connect_db() as connection:
        connection.execute("BEGIN")
        connection.execute("DELETE FROM vacations")
        connection.execute("DELETE FROM users")
        connection.execute("DELETE FROM staff")
        for member in normalized_staff:
            if backend == "postgres":
                connection.execute(
                    "INSERT INTO staff (name, team, role, active) VALUES (%s, %s, %s, %s)",
                    (member["Nome"], member["Equipa"], member["Função"], bool(member["Ativo"])),
                )
            else:
                connection.execute(
                    "INSERT INTO staff (name, team, role, active) VALUES (?, ?, ?, ?)",
                    (member["Nome"], member["Equipa"], member["Função"], int(member["Ativo"])),
                )
        staff_ids = {
            row["name"]: row["id"]
            for row in connection.execute("SELECT id, name FROM staff").fetchall()
        }
        for username, account in validated_users.items():
            staff_id = staff_ids.get(account["staff_name"]) if account.get("staff_name") else None
            if backend == "postgres":
                connection.execute(
                    """
                    INSERT INTO users (username, password_hash, role, name, staff_id)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (username, account["password_hash"], account["role"], account["name"], staff_id),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO users (username, password_hash, role, name, staff_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (username, account["password_hash"], account["role"], account["name"], staff_id),
                )
        for vacation in serialized_vacations:
            staff_id = staff_ids.get(vacation["employee_name"])
            params = (
                vacation["id"],
                vacation["employee_name"],
                staff_id,
                vacation["created_by"],
                vacation["team"],
                vacation["absence_type"],
                serialize_date(vacation["start_date"]),
                serialize_date(vacation["end_date"]),
                vacation["status"],
                bool(vacation["half_day"]) if backend == "postgres" else int(vacation["half_day"]),
                vacation["replacement_contact"],
                vacation["reason"],
                serialize_dt(vacation["requested_at"]),
                serialize_dt(vacation["approved_at"]) if vacation.get("approved_at") else None,
                vacation.get("approved_by", ""),
            )
            if backend == "postgres":
                connection.execute(
                    """
                    INSERT INTO vacations (
                        id, employee_name, staff_id, created_by, team, absence_type, start_date, end_date,
                        status, half_day, replacement_contact, reason, requested_at, approved_at, approved_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    params,
                )
            else:
                connection.execute(
                    """
                    INSERT INTO vacations (
                        id, employee_name, staff_id, created_by, team, absence_type, start_date, end_date,
                        status, half_day, replacement_contact, reason, requested_at, approved_at, approved_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )
        if backend == "postgres":
            connection.execute(
                """
                INSERT INTO app_state (id, payload, updated_at)
                VALUES (1, %s, %s)
                ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at
                """,
                (payload_text, updated_at),
            )
        else:
            connection.execute(
                """
                INSERT INTO app_state (id, payload, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
                """,
                (payload_text, updated_at),
            )
        connection.commit()


def load_data() -> tuple[list[dict], list[dict], dict[str, dict]]:
    init_db()
    with connect_db() as connection:
        if _has_relational_rows(connection):
            return _load_relational_data(connection)
        legacy_data = _load_legacy_db_data(connection)
    if legacy_data is not None:
        save_data(*legacy_data)
        return legacy_data
    if DATA_FILE.exists():
        vacations, staff, users = load_json_data()
        save_data(vacations, staff, users)
        return vacations, staff, users
    defaults = ([], [], validate_users_map(None, []))
    save_data(*defaults)
    return defaults


def acquire_data_lock(timeout_seconds: float = 10.0, poll_interval: float = 0.1) -> None:
    global _POSTGRES_LOCK_CONNECTION
    if storage_backend() == "postgres":
        if _POSTGRES_LOCK_CONNECTION is not None:
            return
        connection = connect_db()
        try:
            connection.execute("SELECT pg_advisory_lock(%s)", (POSTGRES_LOCK_KEY,))
            _POSTGRES_LOCK_CONNECTION = connection
            return
        except Exception:
            connection.close()
            raise
    deadline = time.time() + timeout_seconds
    while True:
        try:
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(os.getpid()).encode("ascii", "ignore"))
            os.close(fd)
            return
        except FileExistsError:
            try:
                age_seconds = time.time() - LOCK_FILE.stat().st_mtime
                if age_seconds > timeout_seconds:
                    LOCK_FILE.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() >= deadline:
                raise DataStoreError("Não foi possível obter acesso exclusivo ao armazenamento de dados.")
            time.sleep(poll_interval)


def release_data_lock() -> None:
    global _POSTGRES_LOCK_CONNECTION
    if storage_backend() == "postgres":
        if _POSTGRES_LOCK_CONNECTION is not None:
            try:
                _POSTGRES_LOCK_CONNECTION.execute("SELECT pg_advisory_unlock(%s)", (POSTGRES_LOCK_KEY,))
            finally:
                _POSTGRES_LOCK_CONNECTION.close()
                _POSTGRES_LOCK_CONNECTION = None
        return
    LOCK_FILE.unlink(missing_ok=True)
