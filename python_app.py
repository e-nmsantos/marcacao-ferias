from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

DATA_VERSION = 2
DATA_FILE = Path(__file__).with_name("data_store.json")
DB_FILE = Path(__file__).with_name("ferias.db")
BACKUP_DIR = Path(__file__).with_name("backups")
LOCK_FILE = Path(__file__).with_name("data_store.lock")
PASSWORD_ITERATIONS = 200_000

ABSENCE_TYPES = ["Férias", "Meio-dia", "Compensação", "Outro"]
STATUS_OPTIONS = ["all", "pending", "approved", "rejected"]
STATUS_LABELS = {
    "all": "Todos",
    "pending": "Pendente",
    "approved": "Aprovado",
    "rejected": "Rejeitado",
}
NAV_ADMIN = ["Calendário", "Pedidos", "Relatórios", "Pessoal", "Logins", "Backup"]
NAV_USER = ["Calendário", "Meus Pedidos"]
NAV_VIEWER = ["Calendário", "Pedidos", "Relatórios"]

DEFAULT_USERS = {
    "admin": {
        "password_hash": "pbkdf2_sha256$200000$Z1UP++hg6MmOpllD2XXe9A==$l5XjKw3K55JRP3UuhchkXQh6DOA5rg4JuMyx5q8EYJQ=",
        "role": "admin",
        "name": "Administrador",
    },
    "maria": {
        "password_hash": "pbkdf2_sha256$200000$wORkS9D6HW7pXF72d5rkEA==$aRFSfTi4ENvaWDKl5qrPuJntyvF3BzV7UmzuobdKrwI=",
        "role": "user",
        "name": "Maria",
    },
    "joao": {
        "password_hash": "pbkdf2_sha256$200000$CDyCSihP37kEQ3OpoF26lw==$I924cVDipxLShQMHQLZdYSaLpjbQPKvuBrtGomuArnk=",
        "role": "user",
        "name": "João",
    },
    "consulta": {
        "password_hash": "pbkdf2_sha256$200000$YebZRordTvC6IDp4crXIsg==$+Zw8GBqoiJSRTp998XC2R85o6Tq/8cVf4gvHFnB0nJ8=",
        "role": "viewer",
        "name": "Consulta",
    },
}

MUNICIPAL_HOLIDAYS = {
    "Nenhum": None,
    "Lisboa": (6, 13, "Santo António"),
    "Porto": (6, 24, "São João"),
    "Braga": (12, 8, "Imaculada Conceição (Municipal)"),
    "Coimbra": (7, 4, "Rainha Santa Isabel"),
}


class DataStoreError(RuntimeError):
    pass


def serialize_date(value: date) -> str:
    return value.isoformat()


def serialize_dt(value: datetime) -> str:
    return value.isoformat()


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


def validate_user_account(username: str, item: dict) -> dict:
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
    return {
        "password_hash": password_hash,
        "role": role,
        "name": name,
    }


def validate_users_map(items: object) -> dict[str, dict]:
    source = DEFAULT_USERS if items is None else items
    if not isinstance(source, dict):
        raise DataStoreError("A lista de logins está num formato inválido.")
    cleaned: dict[str, dict] = {}
    for username, raw in source.items():
        normalized_username = str(username).strip().lower()
        cleaned[normalized_username] = validate_user_account(normalized_username, raw)
    if "admin" not in cleaned:
        raise DataStoreError("Tem de existir pelo menos uma conta administradora.")
    return cleaned


def validate_staff_member(item: dict) -> dict:
    if not isinstance(item, dict):
        raise DataStoreError("Registo de colaborador inválido.")
    name = str(item.get("Nome", "")).strip()
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
    if out["end_date"] < out["start_date"]:
        raise DataStoreError("Pedido com intervalo de datas inválido.")
    if out.get("status") not in {"pending", "approved", "rejected"}:
        raise DataStoreError("Pedido com estado inválido.")
    out["employee_name"] = str(item.get("employee_name", "")).strip()
    if not out["employee_name"]:
        raise DataStoreError("Pedido sem nome de colaborador.")
    out["half_day"] = bool(item.get("half_day", False))
    out["created_by"] = str(item.get("created_by", "")).strip()
    out["team"] = str(item.get("team", "")).strip()
    out["absence_type"] = str(item.get("absence_type", "Férias")).strip() or "Férias"
    out["replacement_contact"] = str(item.get("replacement_contact", "")).strip()
    out["reason"] = str(item.get("reason", "")).strip()
    return out


def serialize_vacation(item: dict) -> dict:
    return {
        **item,
        "start_date": serialize_date(item["start_date"]),
        "end_date": serialize_date(item["end_date"]),
        "requested_at": serialize_dt(item["requested_at"]),
    }


def parse_payload(payload: object) -> tuple[list[dict], list[dict], dict[str, dict]]:
    if payload is None:
        return [], [], validate_users_map(None)
    if not isinstance(payload, dict):
        raise DataStoreError("O ficheiro de dados não contém um objeto JSON válido.")
    vacations_raw = payload.get("vacations", [])
    if not isinstance(vacations_raw, list):
        raise DataStoreError("A lista de pedidos está num formato inválido.")
    vacations = [deserialize_vacation(item) for item in vacations_raw]
    staff = validate_staff_list(payload.get("staff", []))
    users = validate_users_map(payload.get("users"))
    return vacations, staff, users


def load_json_data() -> tuple[list[dict], list[dict], dict[str, dict]]:
    if not DATA_FILE.exists():
        return [], [], validate_users_map(None)

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


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with connect_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def load_data() -> tuple[list[dict], list[dict], dict[str, dict]]:
    init_db()
    with connect_db() as connection:
        row = connection.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
    if row is not None:
        try:
            return parse_payload(json.loads(row["payload"]))
        except Exception as exc:
            if isinstance(exc, DataStoreError):
                raise
            raise DataStoreError("Estrutura de dados inválida na base de dados.") from exc
    if DATA_FILE.exists():
        vacations, staff, users = load_json_data()
        save_data(vacations, staff, users)
        return vacations, staff, users
    defaults = ([], [], validate_users_map(None))
    save_data(*defaults)
    return defaults


def build_data_payload(vacations: list[dict], staff: list[dict], users: dict[str, dict]) -> dict:
    return {
        "version": DATA_VERSION,
        "exported_at": datetime.now().isoformat(),
        "vacations": [serialize_vacation(item) for item in vacations],
        "staff": staff,
        "users": users,
    }


def save_data(
    vacations: list[dict] | None = None,
    staff: list[dict] | None = None,
    users: dict[str, dict] | None = None,
) -> None:
    vacations = st.session_state.vacations if vacations is None else vacations
    staff = st.session_state.staff if staff is None else staff
    users = st.session_state.users if users is None else users
    payload = build_data_payload(vacations, staff, users)
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    init_db()
    with connect_db() as connection:
        connection.execute(
            """
            INSERT INTO app_state (id, payload, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (payload_text, datetime.now().isoformat()),
        )
        connection.commit()


def acquire_data_lock(timeout_seconds: float = 10.0, poll_interval: float = 0.1) -> None:
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
    LOCK_FILE.unlink(missing_ok=True)


def sync_state(vacations: list[dict], staff: list[dict], users: dict[str, dict]) -> None:
    st.session_state.vacations = vacations
    st.session_state.staff = staff
    st.session_state.users = users
    st.session_state.data_error = None
    st.session_state.data_mtime = DB_FILE.stat().st_mtime_ns if DB_FILE.exists() else None


def refresh_state_from_disk(force: bool = False) -> None:
    if not DB_FILE.exists() and not DATA_FILE.exists():
        if force or "vacations" not in st.session_state:
            sync_state([], [], validate_users_map(None))
        return
    init_db()
    current_mtime = DB_FILE.stat().st_mtime_ns if DB_FILE.exists() else None
    if not force and st.session_state.get("data_mtime") == current_mtime:
        return
    try:
        vacations, staff, users = load_data()
    except DataStoreError as exc:
        st.session_state.data_error = str(exc)
        return
    sync_state(vacations, staff, users)


def mutate_data(mutator) -> None:
    acquire_data_lock()
    payload = {
        "vacations": [],
        "staff": [],
        "users": validate_users_map(None),
    }
    try:
        has_storage = DB_FILE.exists() or DATA_FILE.exists()
        vacations, staff, users = load_data() if has_storage else ([], [], validate_users_map(None))
        payload["vacations"] = [dict(item) for item in vacations]
        payload["staff"] = [dict(item) for item in staff]
        payload["users"] = {username: dict(item) for username, item in users.items()}
        mutator(payload["vacations"], payload["staff"], payload["users"])
        validated_staff = validate_staff_list(payload["staff"])
        validated_users = validate_users_map(payload["users"])
        save_data(payload["vacations"], validated_staff, validated_users)
        sync_state(payload["vacations"], validated_staff, validated_users)
    finally:
        release_data_lock()


def init_state() -> None:
    if "vacations" not in st.session_state:
        st.session_state.vacations = []
    if "staff" not in st.session_state:
        st.session_state.staff = []
    if "users" not in st.session_state:
        st.session_state.users = validate_users_map(None)
    if "data_error" not in st.session_state:
        st.session_state.data_error = None
    if "data_mtime" not in st.session_state:
        st.session_state.data_mtime = None
    if "current_month" not in st.session_state:
        today = date.today()
        st.session_state.current_month = date(today.year, today.month, 1)
    if "selected_day" not in st.session_state:
        st.session_state.selected_day = date.today()
    if "range_start" not in st.session_state:
        st.session_state.range_start = date.today()
    if "range_end" not in st.session_state:
        st.session_state.range_end = date.today()
    if "conflict_limit" not in st.session_state:
        st.session_state.conflict_limit = 2
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "current_user" not in st.session_state:
        st.session_state.current_user = None
    if "main_nav" not in st.session_state:
        st.session_state.main_nav = "Calendário"
    if "new_request_start" not in st.session_state:
        st.session_state.new_request_start = date.today()
    if "new_request_end" not in st.session_state:
        st.session_state.new_request_end = date.today()
    if "new_request_absence_type" not in st.session_state:
        st.session_state.new_request_absence_type = ABSENCE_TYPES[0]
    if "new_request_half_day" not in st.session_state:
        st.session_state.new_request_half_day = False
    if "new_request_replacement" not in st.session_state:
        st.session_state.new_request_replacement = ""
    if "new_request_reason" not in st.session_state:
        st.session_state.new_request_reason = ""
    if "pending_new_request_reset" not in st.session_state:
        st.session_state.pending_new_request_reset = False
    if "pending_staff_reset" not in st.session_state:
        st.session_state.pending_staff_reset = False
    if "pending_login_reset" not in st.session_state:
        st.session_state.pending_login_reset = False
    if "staff_name" not in st.session_state:
        apply_staff_form_reset()
    if "login_name" not in st.session_state:
        apply_login_form_reset()
    refresh_state_from_disk(force=True)


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(180deg, #f8fafc 0%, #eef3f8 100%);
            color: #0f172a;
        }
        section[data-testid="stSidebar"] {
            background: #f8fafc;
            border-right: 1px solid #e2e8f0;
        }
        .soft-card {
            border: 1px solid #e2e8f0;
            border-radius: 18px;
            background: rgba(255,255,255,0.88);
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
            padding: 14px;
        }
        .page-kicker { color: #64748b; margin-top: -6px; }
        .stat-title { color: #64748b; font-size: 12px; }
        .stat-value { color: #0f172a; font-size: 26px; font-weight: 700; line-height: 1.1; }
        .badge-row { color: #475569; font-size: 11px; margin-top: 4px; }
        div[data-testid="stButton"] > button {
            border-radius: 12px;
            border: 1px solid #d6dcea;
            background: #ffffff;
            color: #0f172a !important;
            font-weight: 600;
        }
        div[data-testid="stButton"] > button[kind="primary"],
        div[data-testid="stFormSubmitButton"] > button {
            background: #dbeafe !important;
            border: 1px solid #93c5fd !important;
            color: #0f172a !important;
            font-weight: 700;
        }
        div[data-baseweb="input"] > div,
        div[data-baseweb="select"] > div,
        textarea,
        input {
            background: #ffffff !important;
            color: #0f172a !important;
            border-color: #cbd5e1 !important;
        }
        label[data-testid="stWidgetLabel"] p { color: #334155 !important; font-weight: 600; }
        .section-shell {
            background: rgba(255,255,255,0.72);
            border: 1px solid rgba(226,232,240,0.9);
            border-radius: 20px;
            padding: 16px;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.04);
        }
        .calendar-hint { color: #64748b; font-size: 12px; margin-bottom: 8px; }
        .calendar-meta {
            display: inline-block;
            font-size: 11px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 999px;
            margin-bottom: 8px;
        }
        .calendar-meta-today {
            background: #0f172a;
            color: #ffffff;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.18);
        }
        .calendar-meta-selection {
            background: #dbeafe;
            color: #1d4ed8;
            border: 1px solid #93c5fd;
        }
        .calendar-count {
            color: #334155;
            font-size: 11px;
            font-weight: 600;
            margin-top: 4px;
        }
        .danger-button-marker {
            display: none;
        }
        .danger-button-marker ~ div[data-testid="stButton"] > button {
            background: #cf7474 !important;
            border: 1px solid #cf7474 !important;
            color: #ffffff !important;
            font-weight: 700;
        }
        .danger-button-marker ~ div[data-testid="stButton"] > button:hover {
            background: #bf6666 !important;
            border-color: #bf6666 !important;
            color: #ffffff !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def current_user() -> dict | None:
    return st.session_state.current_user


def is_admin() -> bool:
    return bool(current_user()) and current_user().get("role") == "admin"


def is_user() -> bool:
    return bool(current_user()) and current_user().get("role") == "user"


def month_name_pt(month: int) -> str:
    months = [
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
    ]
    return months[month - 1]


def easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def portugal_holidays(year: int, municipality: str) -> dict[date, str]:
    easter = easter_date(year)
    holidays = {
        date(year, 1, 1): "Ano Novo",
        easter - timedelta(days=2): "Sexta-feira Santa",
        easter: "Páscoa",
        date(year, 4, 25): "Dia da Liberdade",
        date(year, 5, 1): "Dia do Trabalhador",
        easter + timedelta(days=60): "Corpo de Deus",
        date(year, 6, 10): "Dia de Portugal",
        date(year, 8, 15): "Assunção de Nossa Senhora",
        date(year, 10, 5): "Implantação da República",
        date(year, 11, 1): "Todos os Santos",
        date(year, 12, 1): "Restauração da Independência",
        date(year, 12, 8): "Imaculada Conceição",
        date(year, 12, 25): "Natal",
    }
    municipal = MUNICIPAL_HOLIDAYS.get(municipality)
    if municipal:
        month, day, label = municipal
        holidays[date(year, month, day)] = label
    return holidays


def format_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def calculate_days(start: date, end: date) -> int:
    return (end - start).days + 1


def calculate_business_days(start: date, end: date, holidays: dict[date, str]) -> int:
    current = start
    total = 0
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            total += 1
        current += timedelta(days=1)
    return total


def vacation_matches_filters(vacation: dict, team_filter: str, status_filter: str, scope: str) -> bool:
    if status_filter != "all" and vacation["status"] != status_filter:
        return False
    if team_filter != "Todas" and vacation.get("team", "") != team_filter:
        return False
    if scope == "mine" and vacation.get("created_by") != (current_user() or {}).get("username"):
        return False
    return True


def filtered_vacations(team_filter: str, status_filter: str, scope: str = "all") -> list[dict]:
    return [v for v in st.session_state.vacations if vacation_matches_filters(v, team_filter, status_filter, scope)]


def update_vacation_status(vacation_id: str, new_status: str) -> None:
    if not is_admin():
        raise DataStoreError("Só administradores podem aprovar ou rejeitar pedidos.")

    def apply_change(vacations: list[dict], _: list[dict], __: dict[str, dict]) -> None:
        for vacation in vacations:
            if vacation["id"] == vacation_id:
                vacation["status"] = new_status
                return
        raise DataStoreError("Pedido não encontrado para atualizar.")

    mutate_data(apply_change)


def delete_vacation(vacation_id: str) -> None:
    if not is_admin():
        raise DataStoreError("Só administradores podem eliminar pedidos.")

    def apply_change(vacations: list[dict], _: list[dict], __: dict[str, dict]) -> None:
        updated = [v for v in vacations if v["id"] != vacation_id]
        if len(updated) == len(vacations):
            raise DataStoreError("Pedido não encontrado para eliminar.")
        vacations[:] = updated

    mutate_data(apply_change)


def previous_month() -> None:
    current = st.session_state.current_month
    st.session_state.current_month = date(current.year - 1, 12, 1) if current.month == 1 else date(current.year, current.month - 1, 1)


def next_month() -> None:
    current = st.session_state.current_month
    st.session_state.current_month = date(current.year + 1, 1, 1) if current.month == 12 else date(current.year, current.month + 1, 1)


def this_month() -> None:
    today = date.today()
    st.session_state.current_month = date(today.year, today.month, 1)


def vacations_for_day(day: date, vacations: list[dict]) -> list[dict]:
    return [v for v in vacations if v["start_date"] <= day <= v["end_date"]]


def selected_range() -> tuple[date, date]:
    start = st.session_state.get("range_start", date.today())
    end = st.session_state.get("range_end", start)
    return (start, end) if start <= end else (end, start)


def select_calendar_day(day: date) -> None:
    start, end = selected_range()
    if start == end and day != start:
        start, end = (start, day) if start <= day else (day, start)
    else:
        start, end = day, day
    st.session_state.selected_day = day
    st.session_state.range_start = start
    st.session_state.range_end = end
    st.session_state.new_request_start = start
    st.session_state.new_request_end = end


def day_in_selected_range(day: date) -> bool:
    start, end = selected_range()
    return start <= day <= end


def apply_new_request_reset() -> None:
    today = st.session_state.get("selected_day", date.today())
    st.session_state.range_start = today
    st.session_state.range_end = today
    st.session_state.new_request_start = today
    st.session_state.new_request_end = today
    st.session_state.new_request_absence_type = ABSENCE_TYPES[0]
    st.session_state.new_request_half_day = False
    st.session_state.new_request_replacement = ""
    st.session_state.new_request_reason = ""


def request_new_request_reset() -> None:
    st.session_state.pending_new_request_reset = True


def apply_staff_form_reset() -> None:
    st.session_state.staff_name = ""
    st.session_state.staff_team = ""
    st.session_state.staff_role = ""
    st.session_state.staff_active = True


def request_staff_form_reset() -> None:
    st.session_state.pending_staff_reset = True


def apply_login_form_reset() -> None:
    st.session_state.login_name = ""
    st.session_state.login_username = ""
    st.session_state.login_password = ""
    st.session_state.login_role = "user"


def request_login_form_reset() -> None:
    st.session_state.pending_login_reset = True


def render_data_status() -> None:
    if st.session_state.get("data_error"):
        st.error(
            "Foram detetados problemas no armazenamento local. "
            f"{st.session_state.data_error} Corrija o ficheiro ou restaure um backup válido."
        )


def login_screen() -> None:
    left, center, right = st.columns([1.3, 1.8, 1.3])
    with center:
        st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
        st.subheader("Iniciar sessão")
        st.caption("Admin aprova e gere pessoal. Utilizador cria pedidos. Consulta apenas vê informação.")
        with st.form("login_form"):
            username = st.text_input("Utilizador")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Entrar", type="primary", use_container_width=True)
            if submitted:
                account = st.session_state.users.get(username.strip().lower())
                if account and verify_password(password, account["password_hash"]):
                    st.session_state.authenticated = True
                    st.session_state.current_user = {
                        "username": username.strip().lower(),
                        "name": account["name"],
                        "role": account["role"],
                    }
                    st.rerun()
                st.error("Credenciais inválidas.")
        st.caption("As credenciais são validadas localmente e já não são expostas na interface.")
        st.markdown("</div>", unsafe_allow_html=True)


def top_header() -> None:
    role = (current_user() or {}).get("role", "viewer")
    nav = NAV_ADMIN if role == "admin" else NAV_USER if role == "user" else NAV_VIEWER
    if st.session_state.main_nav not in nav:
        st.session_state.main_nav = nav[0]

    left, right = st.columns([3, 2])
    with left:
        st.title("Gestão de Férias")
        st.markdown("<div class='page-kicker'>Planeamento simples, visual limpo e pedidos organizados.</div>", unsafe_allow_html=True)
    with right:
        info_left, info_right = st.columns([3, 1])
        with info_left:
            user = current_user() or {}
            st.caption(f"Sessão: {user.get('name', '-')}")
        with info_right:
            if st.button("Sair", use_container_width=True):
                st.session_state.authenticated = False
                st.session_state.current_user = None
                st.rerun()
        st.radio("", options=nav, horizontal=True, label_visibility="collapsed", key="main_nav")


def render_stat_card(title: str, value: str, tone: str, subtitle: str = "") -> None:
    tone_bg = {
        "blue": "#dbeafe",
        "green": "#dcfce7",
        "orange": "#ffedd5",
        "pink": "#fce7f3",
        "violet": "#ede9fe",
    }.get(tone, "#ffffff")
    subtitle_html = f"<div class='badge-row'>{subtitle}</div>" if subtitle else ""
    st.markdown(
        f"<div class='soft-card' style='background:{tone_bg};'><div class='stat-title'>{title}</div><div class='stat-value'>{value}</div>{subtitle_html}</div>",
        unsafe_allow_html=True,
    )


def render_stats(vacations: list[dict], holidays: dict[date, str]) -> None:
    total = len(vacations)
    pending = sum(1 for v in vacations if v["status"] == "pending")
    approved = sum(1 for v in vacations if v["status"] == "approved")
    absent_today = sum(1 for v in vacations if v["status"] == "approved" and v["start_date"] <= date.today() <= v["end_date"])
    future_holidays = sorted([h for h in holidays if h >= date.today()])
    next_holiday = "Sem dados"
    if future_holidays:
        h = future_holidays[0]
        next_holiday = f"{format_date(h)} - {holidays[h]}"
    conflict_days = 0
    current = st.session_state.current_month
    for day in range(1, 32):
        try:
            d = date(current.year, current.month, day)
        except ValueError:
            continue
        approved_count = sum(1 for v in vacations if v["status"] == "approved" and v["start_date"] <= d <= v["end_date"])
        if approved_count >= st.session_state.conflict_limit:
            conflict_days += 1

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: render_stat_card("Total de pedidos", str(total), "blue")
    with c2: render_stat_card("Pendentes", str(pending), "orange")
    with c3: render_stat_card("Aprovados", str(approved), "green")
    with c4: render_stat_card("Ausentes hoje", str(absent_today), "pink")
    with c5: render_stat_card("Conflitos no mês", str(conflict_days), "violet")
    st.markdown(f"<div class='soft-card' style='margin-top:8px;'><span class='stat-title'>Próximo feriado</span><div style='font-weight:600;'>{next_holiday}</div></div>", unsafe_allow_html=True)


def render_calendar(vacations: list[dict], holidays: dict[date, str]) -> None:
    current = st.session_state.current_month
    range_start, range_end = selected_range()
    today = date.today()
    nav1, nav2, nav3, nav4 = st.columns([1, 2, 1, 1])
    with nav1: st.button("<", key="prev_month", on_click=previous_month, use_container_width=True)
    with nav2: st.markdown(f"### {month_name_pt(current.month)} {current.year}")
    with nav3: st.button("Hoje", key="this_month", on_click=this_month, use_container_width=True)
    with nav4: st.button(">", key="next_month", on_click=next_month, use_container_width=True)
    if range_start == range_end:
        st.caption(f"Período selecionado para pedido: {format_date(range_start)}")
    else:
        st.caption(f"Período selecionado para pedido: {format_date(range_start)} até {format_date(range_end)}")

    week_names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    cols = st.columns(7)
    for i, name in enumerate(week_names):
        cols[i].markdown(f"**{name}**")

    start_offset = current.weekday()
    next_first = date(current.year + 1, 1, 1) if current.month == 12 else date(current.year, current.month + 1, 1)
    days_in_month = (next_first - current).days
    cells: list[date | None] = [None] * start_offset + [date(current.year, current.month, d) for d in range(1, days_in_month + 1)]
    while len(cells) % 7 != 0:
        cells.append(None)

    for start in range(0, len(cells), 7):
        row = st.columns(7)
        for idx in range(7):
            cell = cells[start + idx]
            with row[idx]:
                if cell is None:
                    st.write("")
                    continue
                day_vacations = vacations_for_day(cell, vacations)
                approved = [v for v in day_vacations if v["status"] == "approved"]
                pending = [v for v in day_vacations if v["status"] == "pending"]
                flags = []
                style = "color:#0f172a; background:#eff6ff;"
                is_today = cell == today
                if is_today:
                    flags.append("Hoje")
                if cell in holidays:
                    flags.append("Feriado")
                    style = "color:#6b21a8; background:#f3e8ff;"
                if cell.weekday() >= 5:
                    flags.append("Fim de semana")
                    style = "color:#475569; background:#e2e8f0;" if cell not in holidays else "color:#7c2d12; background:#fef3c7;"
                if len(approved) >= st.session_state.conflict_limit:
                    flags.append("Conflito")
                selected = day_in_selected_range(cell)
                if is_today:
                    st.markdown("<div class='calendar-meta calendar-meta-today'>Hoje</div>", unsafe_allow_html=True)
                elif selected:
                    st.markdown("<div class='calendar-meta calendar-meta-selection'>Selecionado</div>", unsafe_allow_html=True)
                else:
                    st.markdown("<div style='height:27px;'></div>", unsafe_allow_html=True)
                button_label = f"{cell.day}"
                if st.button(
                    button_label,
                    key=f"day_{cell.isoformat()}",
                    use_container_width=True,
                    type="primary" if selected or is_today else "secondary",
                    on_click=select_calendar_day,
                    args=(cell,),
                ):
                    st.rerun()
                label = " • ".join(flags) if flags else "Dia útil"
                st.markdown(f"<div class='calendar-hint' style='{style} display:inline-block; padding:4px 8px; border-radius:999px;'>{label}</div>", unsafe_allow_html=True)
                day_summary: list[str] = []
                if approved:
                    day_summary.append(f"{len(approved)} aprovado{'s' if len(approved) != 1 else ''}")
                if pending:
                    day_summary.append(f"{len(pending)} pendente{'s' if len(pending) != 1 else ''}")
                if day_summary:
                    st.markdown(f"<div class='calendar-count'>{' • '.join(day_summary)}</div>", unsafe_allow_html=True)


def render_day_panel(vacations: list[dict], holidays: dict[date, str]) -> None:
    day = st.session_state.selected_day
    range_start, range_end = selected_range()
    day_vacations = vacations_for_day(day, vacations)
    approved = [v for v in day_vacations if v["status"] == "approved"]
    pending = [v for v in day_vacations if v["status"] == "pending"]
    st.subheader("Detalhe do dia")
    st.write(f"Data: {format_date(day)}")
    if range_start == range_end:
        st.caption(f"Seleção atual: {format_date(range_start)}")
    else:
        st.caption(f"Seleção atual: {format_date(range_start)} até {format_date(range_end)}")
    if day in holidays:
        st.info(f"Feriado: {holidays[day]}")
    if day.weekday() >= 5:
        st.caption("Fim de semana")
    if len(approved) >= st.session_state.conflict_limit:
        st.warning("Dia com risco de cobertura: muitas ausências aprovadas.")
    st.markdown("**Ausentes aprovados**")
    if approved:
        for vacation in approved:
            st.write(f"- {vacation['employee_name']} ({vacation.get('team', 'Sem equipa')})")
    else:
        st.caption("Sem ausências aprovadas.")
    st.markdown("**Pedidos pendentes**")
    if pending:
        for vacation in pending:
            st.write(f"- {vacation['employee_name']} ({vacation.get('absence_type', 'Férias')})")
    else:
        st.caption("Sem pedidos pendentes para este dia.")


def render_requests(vacations: list[dict], can_manage: bool) -> None:
    can_manage = bool(can_manage and is_admin())
    vacations = sorted(vacations, key=lambda v: (0 if v["status"] == "pending" else 1, -v["requested_at"].timestamp()))
    if not vacations:
        st.info("Ainda não existem pedidos de férias.")
        return
    for vacation in vacations:
        status = vacation["status"]
        duration = calculate_days(vacation["start_date"], vacation["end_date"])
        with st.container(border=True):
            st.markdown(
                f"**{vacation['employee_name']}**  |  {STATUS_LABELS.get(status, status)}\n\n"
                f"Tipo: {vacation.get('absence_type', 'Férias')}  \n"
                f"Período: {format_date(vacation['start_date'])} até {format_date(vacation['end_date'])}  \n"
                f"Duração: {duration} dias  \n"
                f"Pedido em: {vacation['requested_at'].strftime('%d/%m/%Y %H:%M')}"
            )
            st.caption(f"Equipa: {vacation.get('team', 'Sem equipa')}")
            if vacation.get("reason"):
                st.write(f"Motivo: {vacation['reason']}")
            if can_manage:
                a1, a2, a3 = st.columns(3)
                if status == "pending":
                    if a1.button("Aprovar", key=f"approve_{vacation['id']}"):
                        update_vacation_status(vacation["id"], "approved")
                        st.rerun()
                    if a2.button("Rejeitar", key=f"reject_{vacation['id']}"):
                        update_vacation_status(vacation["id"], "rejected")
                        st.rerun()
                if a3.button("Eliminar", key=f"delete_{vacation['id']}"):
                    delete_vacation(vacation["id"])
                    st.rerun()
            else:
                st.caption("Perfil de consulta: sem permissão para alterar pedidos.")


def render_login_management() -> None:
    st.subheader("Gestão de logins")
    st.caption("Só administradores podem criar ou remover contas. As contas de consulta usam o perfil `viewer`.")
    if st.session_state.pending_login_reset:
        apply_login_form_reset()
        st.session_state.pending_login_reset = False

    with st.form("add_login_form"):
        new_name = st.text_input("Nome", key="login_name")
        new_username = st.text_input("Utilizador", key="login_username")
        new_password = st.text_input("Password", type="password", key="login_password")
        new_role = st.selectbox(
            "Perfil",
            options=["user", "viewer", "admin"],
            format_func=lambda value: {
                "admin": "Administrador",
                "user": "Utilizador",
                "viewer": "Consulta",
            }[value],
            key="login_role",
        )
        submitted = st.form_submit_button("Criar login", use_container_width=True)
        if submitted:
            username = new_username.strip().lower()
            if not new_name.strip():
                st.error("O nome é obrigatório.")
            elif not username:
                st.error("O utilizador é obrigatório.")
            elif " " in username:
                st.error("O utilizador não pode ter espaços.")
            elif len(new_password) < 6:
                st.error("A password deve ter pelo menos 6 caracteres.")
            else:
                new_account = {
                    "name": new_name.strip(),
                    "role": new_role,
                    "password_hash": hash_password(new_password),
                }

                def apply_change(_: list[dict], __: list[dict], users: dict[str, dict]) -> None:
                    if username in users:
                        raise DataStoreError("Já existe um login com esse utilizador.")
                    users[username] = dict(new_account)

                mutate_data(apply_change)
                st.success("Login criado com sucesso.")
                request_login_form_reset()
                st.rerun()
    st.markdown("<div class='danger-button-marker'></div>", unsafe_allow_html=True)
    if st.button("Limpar", key="clear_login_form", use_container_width=True):
        request_login_form_reset()
        st.rerun()

    users_table = pd.DataFrame(
        [
            {
                "Utilizador": username,
                "Nome": account["name"],
                "Perfil": {"admin": "Administrador", "user": "Utilizador", "viewer": "Consulta"}[account["role"]],
            }
            for username, account in sorted(st.session_state.users.items())
        ]
    )
    st.dataframe(users_table, use_container_width=True, hide_index=True)

    removable_users = [username for username in sorted(st.session_state.users) if username != "admin"]
    if removable_users:
        remove_username = st.selectbox("Remover login", options=removable_users)
        if st.button("Remover login", use_container_width=True):
            def apply_change(_: list[dict], __: list[dict], users: dict[str, dict]) -> None:
                if remove_username not in users:
                    raise DataStoreError("Login não encontrado.")
                if (current_user() or {}).get("username") == remove_username:
                    raise DataStoreError("Não pode remover a conta com a sessão atual.")
                del users[remove_username]

            mutate_data(apply_change)
            st.success("Login removido com sucesso.")
            st.rerun()
    else:
        st.info("Não existem logins removíveis neste momento.")


def render_new_request_form(holidays: dict[date, str]) -> None:
    st.subheader("Novo pedido a partir do calendário")
    st.caption("Clique num dia para um pedido de 1 dia. Clique noutro dia para fechar um intervalo.")
    if st.session_state.pending_new_request_reset:
        apply_new_request_reset()
        st.session_state.pending_new_request_reset = False

    selected_staff = None
    range_start, range_end = selected_range()
    st.session_state.new_request_start = range_start
    st.session_state.new_request_end = range_end

    active_staff_names = sorted([p["Nome"] for p in st.session_state.staff if p.get("Ativo", True)])
    if is_admin() and active_staff_names:
        employee_name = st.selectbox("Colaborador", options=active_staff_names)
        selected_staff = next((p for p in st.session_state.staff if p["Nome"] == employee_name), None)
    elif is_user():
        employee_name = (current_user() or {}).get("name", "")
        st.text_input("Colaborador", value=employee_name, disabled=True)
    else:
        employee_name = st.text_input("Nome do colaborador")

    col_a, col_b = st.columns(2)
    with col_a:
        st.text_input("Data de início", value=format_date(range_start), disabled=True)
        absence_type = st.selectbox("Tipo de ausência", options=ABSENCE_TYPES, key="new_request_absence_type")
        half_day = st.checkbox("Meio dia", key="new_request_half_day", disabled=range_start != range_end)
    with col_b:
        st.text_input("Data de fim", value=format_date(range_end), disabled=True)
        replacement_contact = st.text_input("Substituto / contacto", key="new_request_replacement")
    reason = st.text_area("Comentário (opcional)", key="new_request_reason")

    total_days = calculate_days(range_start, range_end)
    business_days = calculate_business_days(range_start, range_end, holidays)
    weekend_or_holiday_days = total_days - business_days
    overlap_absent = sum(
        1
        for vacation in st.session_state.vacations
        if vacation["status"] == "approved"
        and vacation["start_date"] <= range_end
        and vacation["end_date"] >= range_start
    )

    st.markdown("**Resumo do pedido**")
    r1, r2, r3, r4 = st.columns(4)
    r1.info(f"Totais: {total_days}")
    r2.info(f"Úteis: {business_days}")
    r3.info(f"Não úteis: {weekend_or_holiday_days}")
    r4.info(f"Conflitos: {overlap_absent}")
    if overlap_absent >= st.session_state.conflict_limit:
        st.warning("Período com potencial conflito de cobertura.")
    if range_start != range_end and half_day:
        st.caption("O modo de meio dia só se aplica a pedidos de um único dia.")

    action_submit, action_clear = st.columns(2)
    submitted = action_submit.button("Submeter pedido", key="submit_new_request", type="primary", use_container_width=True)
    action_clear.markdown("<div class='danger-button-marker'></div>", unsafe_allow_html=True)
    cleared = action_clear.button("Limpar", key="clear_new_request_form", use_container_width=True)
    if cleared:
        request_new_request_reset()
        st.rerun()
    if submitted:
        if not employee_name.strip():
            st.error("Preencha o nome do colaborador.")
            return
        team_name = selected_staff.get("Equipa", "") if selected_staff else ""
        new_request = {
            "id": str(uuid4()),
            "employee_name": employee_name.strip(),
            "created_by": (current_user() or {}).get("username", ""),
            "team": team_name,
            "absence_type": absence_type,
            "start_date": range_start,
            "end_date": range_end,
            "status": "pending",
            "half_day": bool(half_day and range_start == range_end),
            "replacement_contact": replacement_contact.strip(),
            "reason": reason.strip(),
            "requested_at": datetime.now(),
        }

        def apply_change(vacations: list[dict], _: list[dict], __: dict[str, dict]) -> None:
            vacations.append(dict(new_request))

        mutate_data(apply_change)
        st.success("Pedido criado com sucesso.")
        request_new_request_reset()
        st.rerun()


def render_staff_table() -> None:
    st.subheader("Tabela de Pessoal")
    st.caption("Gestão da lista de colaboradores.")
    if st.session_state.pending_staff_reset:
        apply_staff_form_reset()
        st.session_state.pending_staff_reset = False
    add_col, remove_col = st.columns([2, 2])
    with add_col:
        new_name = st.text_input("Nome", key="staff_name")
        new_team = st.text_input("Equipa", key="staff_team")
        new_role = st.text_input("Função", key="staff_role")
        new_active = st.checkbox("Ativo", key="staff_active")
        action_submit, action_clear = st.columns(2)
        submitted = action_submit.button("Adicionar colaborador", key="submit_staff_form", use_container_width=True)
        action_clear.markdown("<div class='danger-button-marker'></div>", unsafe_allow_html=True)
        cleared = action_clear.button("Limpar", key="clear_staff_form", use_container_width=True)
        if cleared:
            request_staff_form_reset()
            st.rerun()
        if submitted:
            if not new_name.strip():
                st.error("O nome é obrigatório.")
            elif any(p["Nome"].lower() == new_name.strip().lower() for p in st.session_state.staff):
                st.error("Já existe um colaborador com esse nome.")
            else:
                new_member = {
                    "Nome": new_name.strip(),
                    "Equipa": new_team.strip(),
                    "Função": new_role.strip(),
                    "Ativo": bool(new_active),
                }

                def apply_change(_: list[dict], staff: list[dict], __: dict[str, dict]) -> None:
                    if any(p["Nome"].lower() == new_member["Nome"].lower() for p in staff):
                        raise DataStoreError("Já existe um colaborador com esse nome.")
                    staff.append(dict(new_member))

                mutate_data(apply_change)
                st.success("Colaborador adicionado.")
                request_staff_form_reset()
                st.rerun()
    with remove_col:
        if st.session_state.staff:
            remove_name = st.selectbox("Remover colaborador", options=[p["Nome"] for p in st.session_state.staff])
            if st.button("Remover", type="secondary"):
                def apply_change(_: list[dict], staff: list[dict], __: dict[str, dict]) -> None:
                    updated = [p for p in staff if p["Nome"] != remove_name]
                    if len(updated) == len(staff):
                        raise DataStoreError("Colaborador não encontrado para remover.")
                    staff[:] = updated

                mutate_data(apply_change)
                st.success("Colaborador removido.")
                st.rerun()
        else:
            st.info("Sem colaboradores para remover.")

    if not st.session_state.staff:
        st.info("Ainda não existem colaboradores na tabela de pessoal.")
        return

    edited_df = st.data_editor(
        pd.DataFrame(st.session_state.staff),
        use_container_width=True,
        num_rows="dynamic",
        key="staff_editor",
        column_config={
            "Nome": st.column_config.TextColumn(required=True),
            "Equipa": st.column_config.TextColumn(),
            "Função": st.column_config.TextColumn(),
            "Ativo": st.column_config.CheckboxColumn(),
        },
    )
    if st.button("Guardar alterações da tabela"):
        cleaned = []
        seen = set()
        for row in edited_df.to_dict(orient="records"):
            name = str(row.get("Nome", "")).strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            cleaned.append({"Nome": name, "Equipa": str(row.get("Equipa", "")).strip(), "Função": str(row.get("Função", "")).strip(), "Ativo": bool(row.get("Ativo", True))})

        def apply_change(_: list[dict], staff: list[dict], __: dict[str, dict]) -> None:
            staff[:] = cleaned

        mutate_data(apply_change)
        st.success("Tabela de pessoal atualizada.")
        st.rerun()


def report_period_label(year: int, month: int) -> str:
    if month == 0:
        return str(year)
    return f"{month_name_pt(month)} {year}"


def approved_report_rows(vacations: list[dict], holidays: dict[date, str], year: int, month: int, team: str) -> list[dict]:
    rows: list[dict] = []
    for vacation in vacations:
        if vacation["status"] != "approved":
            continue
        if team != "Todas" and vacation.get("team", "") != team:
            continue
        if month == 0:
            if vacation["start_date"].year != year and vacation["end_date"].year != year:
                continue
        else:
            period_start = date(year, month, 1)
            period_end = date(year + 1, 1, 1) - timedelta(days=1) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
            if vacation["end_date"] < period_start or vacation["start_date"] > period_end:
                continue
        total_days = calculate_days(vacation["start_date"], vacation["end_date"])
        business_days = calculate_business_days(vacation["start_date"], vacation["end_date"], holidays)
        rows.append(
            {
                "Colaborador": vacation["employee_name"],
                "Equipa": vacation.get("team", ""),
                "Tipo": vacation.get("absence_type", "Férias"),
                "Início": format_date(vacation["start_date"]),
                "Fim": format_date(vacation["end_date"]),
                "Dias": total_days,
                "Dias úteis": business_days,
                "Substituto": vacation.get("replacement_contact", ""),
                "Comentário": vacation.get("reason", ""),
                "Aprovado em": vacation["requested_at"].strftime("%d/%m/%Y %H:%M"),
            }
        )
    rows.sort(key=lambda item: (item["Colaborador"], item["Início"]))
    return rows


def render_reports() -> None:
    st.subheader("Relatórios")
    st.caption("Exportação de férias aprovadas para partilha com a chefia e controlo interno da equipa.")

    approved_vacations = [vacation for vacation in st.session_state.vacations if vacation["status"] == "approved"]
    if not approved_vacations:
        st.info("Ainda não existem férias aprovadas para relatório.")
        return

    teams = sorted({vacation.get("team", "").strip() for vacation in approved_vacations if vacation.get("team", "").strip()})
    team_options = ["Apoio"] + [team for team in teams if team != "Apoio"] if "Apoio" in teams else teams
    team_options = ["Todas"] + team_options
    current_year = date.today().year
    available_years = sorted(
        {
            vacation["start_date"].year
            for vacation in approved_vacations
        }
        | {vacation["end_date"].year for vacation in approved_vacations},
        reverse=True,
    )
    if current_year not in available_years:
        available_years.insert(0, current_year)

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        default_team_index = team_options.index("Apoio") if "Apoio" in team_options else 0
        selected_team = st.selectbox("Equipa do relatório", options=team_options, index=default_team_index)
    with filter_col2:
        selected_year = st.selectbox("Ano", options=available_years, index=0)
    with filter_col3:
        month_options = [0] + list(range(1, 13))
        selected_month = st.selectbox(
            "Mês",
            options=month_options,
            format_func=lambda value: "Ano completo" if value == 0 else month_name_pt(value),
            index=0,
        )

    holidays = portugal_holidays(selected_year, "Nenhum")
    rows = approved_report_rows(approved_vacations, holidays, selected_year, selected_month, selected_team)
    if not rows:
        st.info("Não existem férias aprovadas para os filtros escolhidos.")
        return

    detail_df = pd.DataFrame(rows)
    summary_df = (
        detail_df.groupby(["Colaborador", "Equipa"], as_index=False)[["Dias", "Dias úteis"]]
        .sum()
        .sort_values(["Equipa", "Colaborador"])
    )

    report_title = f"Férias aprovadas - {selected_team} - {report_period_label(selected_year, selected_month)}"
    st.markdown(f"**{report_title}**")

    stat1, stat2, stat3 = st.columns(3)
    stat1.info(f"Registos: {len(detail_df)}")
    stat2.info(f"Dias totais: {int(detail_df['Dias'].sum())}")
    stat3.info(f"Dias úteis: {int(detail_df['Dias úteis'].sum())}")

    st.markdown("**Resumo por colaborador**")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    st.markdown("**Detalhe aprovado**")
    st.dataframe(detail_df, use_container_width=True, hide_index=True)

    csv_data = detail_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Descarregar relatório CSV",
        data=csv_data,
        file_name=f"relatorio_ferias_{selected_team.lower()}_{selected_year}_{selected_month or 'ano'}.csv",
        mime="text/csv",
        use_container_width=True,
    )


def build_backup_payload() -> dict:
    return build_data_payload(st.session_state.vacations, st.session_state.staff, st.session_state.users)


def restore_payload(payload: dict) -> bool:
    try:
        vacations, staff, users = parse_payload(payload)

        def apply_change(
            current_vacations: list[dict], current_staff: list[dict], current_users: dict[str, dict]
        ) -> None:
            current_vacations[:] = [dict(v) for v in vacations]
            current_staff[:] = [dict(member) for member in staff]
            current_users.clear()
            current_users.update({username: dict(item) for username, item in users.items()})

        mutate_data(apply_change)
        return True
    except (DataStoreError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def render_backup_tools() -> None:
    st.subheader("Backup e restauro")
    payload = build_backup_payload()
    backup_text = json.dumps(payload, ensure_ascii=False, indent=2)
    st.download_button(
        "Descarregar backup (.json)",
        data=backup_text,
        file_name=f"backup_ferias_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
        use_container_width=True,
    )
    if st.button("Criar snapshot local", use_container_width=True):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUP_DIR / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        backup_path.write_text(backup_text, encoding="utf-8")
        st.success(f"Snapshot criado em {backup_path.name}")
    uploaded = st.file_uploader("Restaurar de ficheiro", type=["json"])
    if uploaded is not None and st.button("Restaurar backup", type="primary", use_container_width=True):
        try:
            payload = json.loads(uploaded.getvalue().decode("utf-8"))
        except Exception:
            st.error("Backup inválido.")
            return
        if restore_payload(payload):
            st.success("Backup restaurado com sucesso.")
            st.rerun()
        else:
            st.error("Estrutura de backup inválida.")


def render_filters() -> tuple[str, str, int]:
    teams = sorted({p.get("Equipa", "").strip() for p in st.session_state.staff if p.get("Equipa", "").strip()})
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        team_filter = st.selectbox("Filtro por equipa", ["Todas"] + teams)
    with c2:
        status_filter = st.selectbox("Estado", options=STATUS_OPTIONS, format_func=lambda x: STATUS_LABELS[x])
    with c3:
        st.session_state.conflict_limit = st.number_input("Limite conflito", min_value=1, max_value=20, value=st.session_state.conflict_limit, step=1)
    return team_filter, status_filter, st.session_state.conflict_limit


def main() -> None:
    st.set_page_config(page_title="Gestão de Férias", page_icon="📅", layout="wide")
    init_state()
    apply_styles()

    if not st.session_state.authenticated:
        st.title("Gestão de Férias")
        st.caption("Autenticação necessária")
        render_data_status()
        login_screen()
        return

    refresh_state_from_disk()
    top_header()
    render_data_status()
    team_filter, status_filter, _ = render_filters()
    holidays = portugal_holidays(st.session_state.current_month.year, "Nenhum")
    scope = "all" if is_admin() or (current_user() or {}).get("role") == "viewer" else "mine"
    visible_vacations = filtered_vacations(team_filter, status_filter, scope=scope)
    nav = NAV_ADMIN if is_admin() else NAV_USER if is_user() else NAV_VIEWER
    current_page = st.session_state.get("main_nav", nav[0])

    st.markdown("<div class='section-shell'>", unsafe_allow_html=True)

    if current_page == "Calendário":
        render_stats(visible_vacations, holidays)
        left, right = st.columns([3, 1.4])
        with left:
            render_calendar(visible_vacations, holidays)
        with right:
            render_day_panel(visible_vacations, holidays)
            if is_admin() or is_user():
                st.divider()
                render_new_request_form(holidays)
    elif current_page == "Pedidos":
        if is_admin():
            st.caption("Nesta vista os pedidos pendentes aparecem primeiro e só administradores podem aprovar ou rejeitar.")
        render_requests(visible_vacations, can_manage=is_admin())
    elif current_page == "Meus Pedidos":
        mine = filtered_vacations(team_filter, status_filter, scope="mine")
        render_requests(mine, can_manage=False)
    elif current_page == "Relatórios" and (is_admin() or (current_user() or {}).get("role") == "viewer"):
        render_reports()
    elif current_page == "Pessoal" and is_admin():
        render_staff_table()
    elif current_page == "Logins" and is_admin():
        render_login_management()
    elif current_page == "Backup" and is_admin():
        render_backup_tools()
    else:
        st.info("Secção indisponível para o perfil atual.")

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
