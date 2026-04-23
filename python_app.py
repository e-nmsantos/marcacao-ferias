from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from uuid import uuid4

import pandas as pd
import streamlit as st

from vacation_app.auth import DataStoreError, hash_password, normalize_employee_name, verify_password
from vacation_app.calendar_utils import (
    calculate_business_days,
    calculate_days,
    format_date,
    month_name_pt,
    portugal_holidays,
)
from vacation_app.constants import (
    ABSENCE_TYPES,
    BACKUP_DIR,
    DATA_FILE,
    DB_FILE,
    NAV_ADMIN,
    NAV_USER,
    NAV_VIEWER,
    STATUS_LABELS,
    STATUS_OPTIONS,
)
from vacation_app.excel_export import build_margarida_workbook
from vacation_app.reports import build_report_rows, report_period_label
from vacation_app.storage import (
    acquire_data_lock,
    build_data_payload,
    init_db,
    load_data,
    parse_payload,
    release_data_lock,
    save_data,
    validate_staff_list,
    validate_users_map,
)


def sync_state(vacations: list[dict], staff: list[dict], users: dict[str, dict]) -> None:
    st.session_state.vacations = vacations
    st.session_state.staff = staff
    st.session_state.users = users
    st.session_state.data_error = None
    st.session_state.data_mtime = DB_FILE.stat().st_mtime_ns if DB_FILE.exists() else None


def refresh_state_from_disk(force: bool = False) -> None:
    if not DB_FILE.exists() and not DATA_FILE.exists():
        if force or "vacations" not in st.session_state:
            sync_state([], [], validate_users_map(None, []))
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
        "users": validate_users_map(None, []),
    }
    try:
        has_storage = DB_FILE.exists() or DATA_FILE.exists()
        vacations, staff, users = load_data() if has_storage else ([], [], validate_users_map(None, []))
        payload["vacations"] = [dict(item) for item in vacations]
        payload["staff"] = [dict(item) for item in staff]
        payload["users"] = {username: dict(item) for username, item in users.items()}
        mutator(payload["vacations"], payload["staff"], payload["users"])
        validated_staff = validate_staff_list(payload["staff"])
        validated_users = validate_users_map(payload["users"], validated_staff)
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
        st.session_state.users = validate_users_map(None, [])
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
    if "edit_login_target" not in st.session_state:
        st.session_state.edit_login_target = ""
    if "edit_login_name" not in st.session_state:
        st.session_state.edit_login_name = ""
    if "edit_login_role" not in st.session_state:
        st.session_state.edit_login_role = "user"
    if "edit_login_staff_name" not in st.session_state:
        st.session_state.edit_login_staff_name = "Sem associação"
    if "edit_login_password" not in st.session_state:
        st.session_state.edit_login_password = ""
    if "pending_edit_login_target" not in st.session_state:
        st.session_state.pending_edit_login_target = ""
    if "edit_login_selector" not in st.session_state:
        st.session_state.edit_login_selector = ""
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
        .brand-footer {
            margin-top: 18px;
            padding: 14px 18px;
            display: inline-block;
            border-radius: 14px;
            background: #0f172a;
            color: #ffffff;
            font-size: 14px;
            font-weight: 500;
            box-shadow: 0 12px 24px rgba(15, 23, 42, 0.16);
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
                if new_status == "approved":
                    vacation["approved_at"] = datetime.now()
                    vacation["approved_by"] = (current_user() or {}).get("username", "")
                else:
                    vacation["approved_at"] = None
                    vacation["approved_by"] = ""
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


def load_edit_login_form(username: str) -> None:
    account = st.session_state.users.get(username, {})
    st.session_state.edit_login_target = username
    st.session_state.edit_login_name = account.get("name", "")
    st.session_state.edit_login_role = account.get("role", "user")
    st.session_state.edit_login_staff_name = account.get("staff_name", "") or "Sem associação"
    st.session_state.edit_login_password = ""


def request_edit_login_load(username: str) -> None:
    st.session_state.pending_edit_login_target = username


def on_edit_login_selector_change() -> None:
    request_edit_login_load(st.session_state.edit_login_selector)


def current_user_staff() -> dict | None:
    user = current_user() or {}
    staff_name = normalize_employee_name(user.get("staff_name", ""))
    if not staff_name:
        return None
    return next((person for person in st.session_state.staff if person["Nome"] == staff_name), None)


def linked_accounts_for_staff(staff_name: str, users: dict[str, dict] | None = None) -> list[str]:
    source = st.session_state.users if users is None else users
    return sorted(
        username
        for username, account in source.items()
        if normalize_employee_name(account.get("staff_name", "")) == staff_name
    )


def linked_vacations_for_staff(staff_name: str, vacations: list[dict] | None = None) -> list[dict]:
    source = st.session_state.vacations if vacations is None else vacations
    return [vacation for vacation in source if normalize_employee_name(vacation["employee_name"]) == staff_name]


def ensure_staff_removal_allowed(staff_name: str, users: dict[str, dict] | None = None, vacations: list[dict] | None = None) -> None:
    linked_users = linked_accounts_for_staff(staff_name, users)
    linked_requests = linked_vacations_for_staff(staff_name, vacations)
    if linked_users or linked_requests:
        pieces = []
        if linked_users:
            pieces.append(f"logins associados: {', '.join(linked_users)}")
        if linked_requests:
            pieces.append(f"pedidos associados: {len(linked_requests)}")
        details = " | ".join(pieces)
        raise DataStoreError(
            f"Não pode remover ou renomear {staff_name} enquanto existirem ligações ativas. {details}."
        )


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
                        "staff_name": account.get("staff_name", ""),
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
    st.caption("Só administradores podem criar, editar ou remover contas. As contas de consulta usam o perfil `viewer`.")
    if st.session_state.pending_login_reset:
        apply_login_form_reset()
        st.session_state.pending_login_reset = False

    with st.form("add_login_form"):
        active_staff_names = sorted([person["Nome"] for person in st.session_state.staff if person.get("Ativo", True)])
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
        staff_options = ["Sem associação"] + active_staff_names
        selected_staff_name = st.selectbox("Colaborador associado", options=staff_options)
        submitted = st.form_submit_button("Criar login", use_container_width=True)
        if submitted:
            username = new_username.strip().lower()
            linked_staff_name = "" if selected_staff_name == "Sem associação" else selected_staff_name
            if not new_name.strip():
                st.error("O nome é obrigatório.")
            elif not username:
                st.error("O utilizador é obrigatório.")
            elif " " in username:
                st.error("O utilizador não pode ter espaços.")
            elif len(new_password) < 6:
                st.error("A password deve ter pelo menos 6 caracteres.")
            elif new_role == "user" and not linked_staff_name:
                st.error("As contas de utilizador têm de ficar associadas a uma pessoa do pessoal.")
            else:
                new_account = {
                    "name": new_name.strip(),
                    "role": new_role,
                    "password_hash": hash_password(new_password),
                    "staff_name": linked_staff_name,
                }

                def apply_change(_: list[dict], __: list[dict], users: dict[str, dict]) -> None:
                    if username in users:
                        raise DataStoreError("Já existe um login com esse utilizador.")
                    users[username] = dict(new_account)

                mutate_data(apply_change)
                st.success("Login criado com sucesso.")
                request_login_form_reset()
                st.rerun()
    if st.button("Limpar", key="clear_login_form", use_container_width=True):
        request_login_form_reset()
        st.rerun()

    users_table = pd.DataFrame(
        [
            {
                "Utilizador": username,
                "Nome": account["name"],
                "Perfil": {"admin": "Administrador", "user": "Utilizador", "viewer": "Consulta"}[account["role"]],
                "Colaborador": account.get("staff_name", "") or "-",
            }
            for username, account in sorted(st.session_state.users.items())
        ]
    )
    st.dataframe(users_table, use_container_width=True, hide_index=True)
    st.caption("As passwords atuais não podem ser visualizadas porque ficam guardadas em hash. Pode redefinir uma nova password abaixo.")

    editable_users = sorted(st.session_state.users)
    if editable_users:
        if not st.session_state.edit_login_selector or st.session_state.edit_login_selector not in editable_users:
            st.session_state.edit_login_selector = editable_users[0]
            request_edit_login_load(editable_users[0])
        if st.session_state.pending_edit_login_target:
            load_edit_login_form(st.session_state.pending_edit_login_target)
            st.session_state.pending_edit_login_target = ""

        selected_edit_username = st.selectbox(
            "Editar login",
            options=editable_users,
            key="edit_login_selector",
            on_change=on_edit_login_selector_change,
        )

        active_staff_names = sorted([person["Nome"] for person in st.session_state.staff if person.get("Ativo", True)])
        edit_staff_options = ["Sem associação"] + active_staff_names
        if st.session_state.edit_login_staff_name not in edit_staff_options:
            st.session_state.edit_login_staff_name = "Sem associação"

        with st.form("edit_login_form"):
            edit_name = st.text_input("Nome editável", key="edit_login_name")
            edit_role = st.selectbox(
                "Perfil editável",
                options=["user", "viewer", "admin"],
                format_func=lambda value: {
                    "admin": "Administrador",
                    "user": "Utilizador",
                    "viewer": "Consulta",
                }[value],
                key="edit_login_role",
            )
            edit_staff_name = st.selectbox("Colaborador associado", options=edit_staff_options, key="edit_login_staff_name")
            edit_password = st.text_input(
                "Nova password",
                type="password",
                key="edit_login_password",
                help="Deixe em branco para manter a password atual.",
            )
            submitted_edit = st.form_submit_button("Guardar alterações do login", use_container_width=True)
            if submitted_edit:
                linked_staff_name = "" if edit_staff_name == "Sem associação" else edit_staff_name
                if not edit_name.strip():
                    st.error("O nome é obrigatório.")
                elif edit_role == "user" and not linked_staff_name:
                    st.error("As contas de utilizador têm de ficar associadas a uma pessoa do pessoal.")
                elif edit_password and len(edit_password) < 6:
                    st.error("A nova password deve ter pelo menos 6 caracteres.")
                else:
                    def apply_change(_: list[dict], __: list[dict], users: dict[str, dict]) -> None:
                        if selected_edit_username not in users:
                            raise DataStoreError("Login não encontrado.")
                        users[selected_edit_username]["name"] = edit_name.strip()
                        users[selected_edit_username]["role"] = edit_role
                        users[selected_edit_username]["staff_name"] = linked_staff_name
                        if edit_password:
                            users[selected_edit_username]["password_hash"] = hash_password(edit_password)

                    mutate_data(apply_change)
                    if (current_user() or {}).get("username") == selected_edit_username:
                        st.session_state.current_user = {
                            **(current_user() or {}),
                            "name": edit_name.strip(),
                            "role": edit_role,
                            "staff_name": linked_staff_name,
                        }
                    request_edit_login_load(selected_edit_username)
                    st.success("Login atualizado com sucesso.")
                    st.rerun()

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
        selected_staff = current_user_staff()
        employee_name = selected_staff["Nome"] if selected_staff else (current_user() or {}).get("staff_name", "")
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
    cleared = action_clear.button("Limpar", key="clear_new_request_form", use_container_width=True)
    if cleared:
        request_new_request_reset()
        st.rerun()
    if submitted:
        if not employee_name.strip():
            st.error("Preencha o nome do colaborador.")
            return
        if is_user() and not selected_staff:
            st.error("A tua conta precisa de estar associada a uma pessoa do pessoal.")
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
            "approved_at": None,
            "approved_by": "",
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
                def apply_change(vacations: list[dict], staff: list[dict], users: dict[str, dict]) -> None:
                    ensure_staff_removal_allowed(remove_name, users, vacations)
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

        def apply_change(vacations: list[dict], staff: list[dict], users: dict[str, dict]) -> None:
            current_names = {member["Nome"] for member in staff}
            new_names = {member["Nome"] for member in cleaned}
            for removed_name in sorted(current_names - new_names):
                ensure_staff_removal_allowed(removed_name, users, vacations)
            staff[:] = cleaned

        mutate_data(apply_change)
        st.success("Tabela de pessoal atualizada.")
        st.rerun()


def render_reports() -> None:
    st.subheader("Relatórios")
    st.caption("Mapa de férias para partilha com a chefia e controlo interno da equipa.")

    report_vacations = [vacation for vacation in st.session_state.vacations if vacation["status"] in {"approved", "pending"}]
    if not report_vacations:
        st.info("Ainda não existem férias aprovadas ou pendentes para relatório.")
        return

    teams = sorted({vacation.get("team", "").strip() for vacation in report_vacations if vacation.get("team", "").strip()})
    team_options = ["Apoio"] + [team for team in teams if team != "Apoio"] if "Apoio" in teams else teams
    team_options = ["Todas"] + team_options
    current_year = date.today().year
    available_years = sorted(
        {
            vacation["start_date"].year
            for vacation in report_vacations
        }
        | {vacation["end_date"].year for vacation in report_vacations},
        reverse=True,
    )
    if current_year not in available_years:
        available_years.insert(0, current_year)

    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
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
    with filter_col4:
        selected_statuses = st.multiselect(
            "Estados",
            options=["approved", "pending"],
            default=["approved", "pending"],
            format_func=lambda value: STATUS_LABELS[value],
        )

    if not selected_statuses:
        st.info("Escolhe pelo menos um estado para gerar o relatório.")
        return
    rows = build_report_rows(report_vacations, {}, selected_year, selected_month, selected_team, selected_statuses)
    if not rows:
        st.info("Não existem registos para os filtros escolhidos.")
        return

    detail_df = pd.DataFrame(rows)
    summary_df = (
        detail_df.groupby(["Colaborador", "Equipa", "Estado"], as_index=False)[["Dias", "Dias úteis"]]
        .sum()
        .sort_values(["Equipa", "Colaborador", "Estado"])
    )
    approved_df = detail_df[detail_df["Estado"] == STATUS_LABELS["approved"]].copy()
    pending_df = detail_df[detail_df["Estado"] == STATUS_LABELS["pending"]].copy()
    collaborator_df = (
        detail_df.groupby(["Colaborador", "Equipa"], as_index=False)[["Dias", "Dias úteis"]]
        .sum()
        .sort_values(["Equipa", "Colaborador"])
    )

    selected_status_labels = ", ".join(STATUS_LABELS[status] for status in selected_statuses)
    report_title = f"Férias {selected_status_labels.lower()} - {selected_team} - {report_period_label(selected_year, selected_month)}"
    st.markdown(f"### {report_title}")
    st.caption(f"Emitido em {datetime.now().strftime('%d/%m/%Y %H:%M')} | Destinatário: Chefe de Gabinete")

    approved_count = int((detail_df["Estado"] == STATUS_LABELS["approved"]).sum())
    pending_count = int((detail_df["Estado"] == STATUS_LABELS["pending"]).sum())
    render_stats_cols = st.columns(4)
    with render_stats_cols[0]:
        render_stat_card("Registos", str(len(detail_df)), "blue", f"Equipa: {selected_team}")
    with render_stats_cols[1]:
        render_stat_card("Dias totais", str(int(detail_df["Dias"].sum())), "green", report_period_label(selected_year, selected_month))
    with render_stats_cols[2]:
        render_stat_card("Autorizados", str(approved_count), "pink", "Estado aprovado")
    with render_stats_cols[3]:
        render_stat_card("Pendentes", str(pending_count), "orange", "Aguarda validação")

    st.markdown("**Resumo por colaborador**")
    st.dataframe(collaborator_df, use_container_width=True, hide_index=True)

    st.markdown("**Resumo por estado**")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    if not approved_df.empty:
        st.markdown("**Férias autorizadas**")
        st.dataframe(approved_df, use_container_width=True, hide_index=True)
    if not pending_df.empty:
        st.markdown("**Férias pendentes**")
        st.dataframe(pending_df, use_container_width=True, hide_index=True)

    export_col1, export_col2 = st.columns(2)
    detail_csv_data = detail_df.to_csv(index=False).encode("utf-8-sig")
    summary_csv_data = collaborator_df.to_csv(index=False).encode("utf-8-sig")
    export_col1.download_button(
        "Descarregar detalhe CSV",
        data=detail_csv_data,
        file_name=f"relatorio_ferias_detalhe_{selected_team.lower()}_{selected_year}_{selected_month or 'ano'}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    export_col2.download_button(
        "Descarregar resumo CSV",
        data=summary_csv_data,
        file_name=f"relatorio_ferias_resumo_{selected_team.lower()}_{selected_year}_{selected_month or 'ano'}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    approved_map_vacations = [
        vacation
        for vacation in st.session_state.vacations
        if vacation["status"] == "approved"
        and (selected_team == "Todas" or vacation.get("team", "") == selected_team)
        and (vacation["start_date"].year == selected_year or vacation["end_date"].year == selected_year)
    ]
    st.markdown("**Mapa anual Margarida**")
    st.caption("Exporta um Excel anual no estilo do mapa de férias, preenchido apenas com férias aprovadas.")
    if approved_map_vacations:
        try:
            margarida_xlsx = build_margarida_workbook(
                st.session_state.vacations,
                st.session_state.staff,
                year=selected_year,
                team=selected_team,
                title_name="Margarida",
            )
        except RuntimeError:
            st.info("Para gerar o mapa Excel na cloud é preciso instalar a dependência `openpyxl`.")
        else:
            st.download_button(
                "Descarregar mapa Margarida (.xlsx)",
                data=margarida_xlsx,
                file_name=f"margarida_mapa_ferias_{selected_team.lower()}_{selected_year}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
    else:
        st.info("Não existem férias aprovadas para gerar o mapa anual com os filtros atuais.")

    st.markdown("**Detalhe completo do relatório**")
    st.dataframe(detail_df, use_container_width=True, hide_index=True)

    csv_data = detail_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Descarregar relatório completo CSV",
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


def render_brand_footer() -> None:
    st.markdown(f"<div class='brand-footer'>© {date.today().year} Nuno Santos</div>", unsafe_allow_html=True)


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
    render_brand_footer()


if __name__ == "__main__":
    main()
