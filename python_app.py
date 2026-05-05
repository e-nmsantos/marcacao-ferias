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
)
from vacation_app.performance import cached_portugal_holidays
from vacation_app.constants import (
    ABSENCE_TYPES,
    BACKUP_DIR,
    MUNICIPAL_HOLIDAYS,
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
    get_storage_token,
    has_storage_source,
    load_data,
    parse_payload,
    release_data_lock,
    save_data,
    validate_staff_list,
    validate_users_map,
)
from vacation_app.audit import log_mutation

# Simple UI translations and i18n helper
TRANSLATIONS = {
    "pt": {
        "title": "Gestão de Férias",
        "sidebar_brand": "Gestão de Férias",
        "logout": "Sair",
        "hero_eyebrow": "Gestão de férias",
        "hero_title": "Pedidos rápidos. Aprovação clara. Visão em tempo real.",
        "hero_copy": "Painel simples para colaboradores e gestores — solicitações autónomas, estado claro e relatórios prontos.",
        "language_pt": "Português",
        "language_en": "English",
    },
    "en": {
        "title": "Leave Management",
        "sidebar_brand": "Leave Manager",
        "logout": "Sign out",
        "hero_eyebrow": "Leave management",
        "hero_title": "Fast requests. Clear approvals. Real-time view.",
        "hero_copy": "Simple dashboard for employees and managers — autonomous requests, clear status and ready reports.",
        "language_pt": "Português",
        "language_en": "English",
        "new_request_subheader": "✏️ New request from calendar",
        "new_request_caption": "Click a day for a single-day request. Click another day to close a range.",
        "submit_request": "Submit request",
        "clear_request": "Clear",
        "fill_employee_name": "Please provide employee name.",
        "account_needs_staff": "Your account needs to be linked to a staff member.",
    },
}


def t(key: str) -> str:
    lang = st.session_state.get("lang", "pt")
    return TRANSLATIONS.get(lang, TRANSLATIONS["pt"]).get(key, key)


def sync_state(vacations: list[dict], staff: list[dict], users: dict[str, dict], storage_token: str | None = None) -> None:
    st.session_state.vacations = vacations
    st.session_state.staff = staff
    st.session_state.users = users
    st.session_state.data_error = None
    st.session_state.data_mtime = storage_token if storage_token is not None else get_storage_token()


def refresh_state_from_disk(force: bool = False) -> None:
    if not has_storage_source():
        if force or "vacations" not in st.session_state:
            sync_state([], [], validate_users_map(None, []))
        return
    current_mtime = get_storage_token()
    if not force and st.session_state.get("data_mtime") == current_mtime:
        return
    try:
        vacations, staff, users = load_data()
    except DataStoreError as exc:
        st.session_state.data_error = str(exc)
        return
    sync_state(vacations, staff, users, storage_token=current_mtime)


def mutate_data(mutator) -> None:
    acquire_data_lock()
    payload = {
        "vacations": [],
        "staff": [],
        "users": validate_users_map(None, []),
    }
    try:
        has_storage = has_storage_source()
        vacations, staff, users = load_data() if has_storage else ([], [], validate_users_map(None, []))
        payload["vacations"] = [dict(item) for item in vacations]
        payload["staff"] = [dict(item) for item in staff]
        payload["users"] = {username: dict(item) for username, item in users.items()}
        # Run the mutator (may raise DataStoreError for business rule violations)
        mutator(payload["vacations"], payload["staff"], payload["users"])
        validated_staff = validate_staff_list(payload["staff"])
        validated_users = validate_users_map(payload["users"], validated_staff)
        try:
            updated_at = save_data(payload["vacations"], validated_staff, validated_users)
        except DataStoreError as exc:
            st.session_state.data_error = str(exc)
            raise
        sync_state(payload["vacations"], validated_staff, validated_users, storage_token=updated_at)
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
    if "pending_main_nav_change" not in st.session_state:
        st.session_state.pending_main_nav_change = None
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
    if "selected_municipality" not in st.session_state:
        st.session_state.selected_municipality = "Nenhum"
    if "lang" not in st.session_state:
        st.session_state.lang = "pt"
    refresh_state_from_disk(force=True)


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 50%, #eef3f8 100%);
            color: #0f172a;
        }
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
            border-right: 1px solid #e2e8f0;
        }
        section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
            padding-top: 1.2rem;
        }
        .sidebar-shell {
            background: linear-gradient(180deg, #0f172a 0%, #111827 100%);
            border-radius: 24px;
            padding: 18px;
            color: #e2e8f0;
            box-shadow: 0 18px 40px rgba(15, 23, 42, 0.18);
        }
        .sidebar-brand {
            color: #ffffff;
            font-size: 24px;
            font-weight: 800;
            line-height: 1.1;
        }
        .sidebar-brand-sub {
            color: #94a3b8;
            font-size: 13px;
            margin-top: 4px;
        }
        .sidebar-section-title {
            color: #cbd5e1;
            font-size: 12px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin: 14px 0 8px;
        }
        .sidebar-metric-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        .sidebar-metric {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(148,163,184,0.18);
            border-radius: 18px;
            padding: 12px;
        }
        .sidebar-metric-label {
            color: #94a3b8;
            font-size: 11px;
            font-weight: 700;
        }
        .sidebar-metric-value {
            color: #ffffff;
            font-size: 24px;
            font-weight: 800;
            line-height: 1.1;
            margin-top: 4px;
        }
        .sidebar-metric-note {
            color: #cbd5e1;
            font-size: 11px;
            margin-top: 4px;
        }
        .nav-chip {
            display: block;
            width: 100%;
            text-align: left;
            padding: 12px 14px;
            margin-bottom: 8px;
            border-radius: 16px;
            border: 1px solid rgba(148,163,184,0.16);
            background: rgba(255,255,255,0.05);
            color: #e2e8f0 !important;
            font-weight: 700;
        }
        .nav-chip:hover {
            background: rgba(255,255,255,0.10) !important;
            border-color: rgba(191,219,254,0.28) !important;
        }
        .nav-chip-active {
            background: linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%);
            border-color: #93c5fd;
            color: #ffffff !important;
        }
        .sidebar-action {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(148,163,184,0.18);
            border-radius: 18px;
            padding: 12px;
            margin-top: 10px;
        }
        .sidebar-action-title {
            color: #ffffff;
            font-size: 14px;
            font-weight: 800;
        }
        .sidebar-action-text {
            color: #cbd5e1;
            font-size: 12px;
            line-height: 1.5;
            margin-top: 4px;
        }
        .soft-card {
            border: 1px solid #e2e8f0;
            border-radius: 18px;
            background: rgba(255,255,255,0.92);
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
            backdrop-filter: blur(10px);
            padding: 14px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .soft-card:hover {
            box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
            border-color: #cbd5e1;
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
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        }
        div[data-testid="stButton"] > button:hover {
            background: #f1f5f9 !important;
            border-color: #cbd5e1 !important;
            box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
        }
        div[data-testid="stButton"] > button[kind="primary"],
        div[data-testid="stFormSubmitButton"] > button {
            background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%) !important;
            border: 1px solid #93c5fd !important;
            color: #0f172a !important;
            font-weight: 700;
            box-shadow: 0 4px 12px rgba(29, 78, 216, 0.12);
        }
        div[data-testid="stButton"] > button[kind="primary"]:hover,
        div[data-testid="stFormSubmitButton"] > button:hover {
            background: linear-gradient(135deg, #bfdbfe 0%, #93c5fd 100%) !important;
            box-shadow: 0 6px 16px rgba(29, 78, 216, 0.18);
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
            background: rgba(255,255,255,0.82);
            border: 1px solid rgba(226,232,240,0.9);
            border-radius: 20px;
            padding: 16px;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.04);
            backdrop-filter: blur(8px);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            animation: fadeInUp 0.4s ease-out;
        }
        @keyframes fadeInUp {
            from {
                opacity: 0;
                transform: translateY(8px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
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
        .hero-shell {
            border: 1px solid rgba(226,232,240,0.95);
            border-radius: 24px;
            background:
                radial-gradient(circle at top right, rgba(219,234,254,0.95), transparent 34%),
                linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(248,250,252,0.94) 100%);
            box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
            padding: 20px;
            margin: 12px 0 16px;
        }
        .hero-grid {
            display: grid;
            grid-template-columns: 1.5fr 1fr;
            gap: 18px;
            align-items: start;
        }
        .hero-eyebrow {
            color: #1d4ed8;
            font-size: 12px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .hero-title {
            color: #0f172a;
            font-size: 30px;
            line-height: 1.05;
            font-weight: 800;
            margin: 6px 0 8px;
        }
        .hero-copy {
            color: #334155;
            font-size: 15px;
            line-height: 1.6;
            max-width: 64ch;
        }
        .hero-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 14px;
        }
        .hero-pill {
            border-radius: 999px;
            padding: 7px 12px;
            background: #ffffff;
            border: 1px solid #dbeafe;
            color: #1e3a8a;
            font-size: 12px;
            font-weight: 700;
        }
        .hero-steps {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
            margin-top: 16px;
        }
        .hero-step {
            border-radius: 18px;
            border: 1px solid #e2e8f0;
            background: rgba(255,255,255,0.92);
            padding: 12px;
        }
        .hero-step-number {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border-radius: 999px;
            background: #dbeafe;
            color: #1d4ed8;
            font-weight: 800;
            margin-bottom: 8px;
        }
        .hero-step-title {
            color: #0f172a;
            font-weight: 700;
            font-size: 13px;
            margin-bottom: 4px;
        }
        .hero-step-text {
            color: #475569;
            font-size: 12px;
            line-height: 1.45;
        }
        .hero-metrics {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
        }
        .hero-metric {
            border-radius: 18px;
            border: 1px solid #dbeafe;
            background: rgba(255,255,255,0.96);
            padding: 14px;
        }
        .hero-metric-label {
            color: #64748b;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .hero-metric-value {
            color: #0f172a;
            font-size: 24px;
            line-height: 1.1;
            font-weight: 800;
            margin-top: 4px;
        }
        .hero-metric-note {
            color: #475569;
            font-size: 12px;
            margin-top: 4px;
        }
        .hero-actions {
            margin-top: 12px;
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
        }
        .hero-action {
            border: 1px solid #cbd5e1;
            border-radius: 16px;
            padding: 12px;
            background: #ffffff;
        }
        .hero-action-title {
            color: #0f172a;
            font-weight: 800;
            font-size: 13px;
            margin-bottom: 4px;
        }
        .hero-action-text {
            color: #475569;
            font-size: 12px;
            line-height: 1.45;
        }
        .login-pitch {
            border-radius: 20px;
            border: 1px solid #e2e8f0;
            background: linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(248,250,252,0.94) 100%);
            box-shadow: 0 14px 30px rgba(15, 23, 42, 0.06);
            padding: 18px;
        }
        .login-pitch-title {
            color: #0f172a;
            font-size: 18px;
            font-weight: 800;
            margin-bottom: 8px;
        }
        .login-pitch-text {
            color: #475569;
            font-size: 14px;
            line-height: 1.55;
            margin-bottom: 14px;
        }
        .login-pitch-list {
            display: grid;
            gap: 10px;
        }
        .login-pitch-item {
            display: flex;
            gap: 10px;
            align-items: flex-start;
            border-radius: 14px;
            border: 1px solid #e2e8f0;
            background: rgba(255,255,255,0.96);
            padding: 12px;
        }
        .login-pitch-badge {
            width: 24px;
            height: 24px;
            border-radius: 999px;
            background: #dbeafe;
            color: #1d4ed8;
            font-size: 12px;
            font-weight: 800;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex: 0 0 auto;
        }
        .login-pitch-item-title {
            color: #0f172a;
            font-size: 13px;
            font-weight: 700;
        }
        .login-pitch-item-text {
            color: #475569;
            font-size: 12px;
            line-height: 1.45;
            margin-top: 2px;
        }
        .calendar-hint { color: #64748b; font-size: 12px; margin-bottom: 8px; }
        .status-badge {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .status-pending {
            background: #fed7aa;
            color: #92400e;
            border: 1px solid #fdba74;
        }
        .status-approved {
            background: #dcfce7;
            color: #166534;
            border: 1px solid #bbf7d0;
        }
        .status-rejected {
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #fca5a5;
        }
        .request-card {
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            background: rgba(255,255,255,0.94);
            padding: 14px;
            margin-bottom: 10px;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .request-card:hover {
            border-color: #cbd5e1;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
        }
        .request-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .request-title {
            color: #0f172a;
            font-weight: 700;
            font-size: 14px;
        }
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
        .sr-only {
            position: absolute !important;
            width: 1px !important;
            height: 1px !important;
            padding: 0 !important;
            margin: -1px !important;
            overflow: hidden !important;
            clip: rect(0, 0, 0, 0) !important;
            white-space: nowrap !important;
            border: 0 !important;
        }
        .calendar-shell {
            padding: 12px;
            border-radius: 18px;
            background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(249,250,251,0.9));
            border: 1px solid rgba(226,232,240,0.95);
            box-shadow: 0 14px 36px rgba(15,23,42,0.06);
            margin-top: 12px;
        }
        .calendar-shell .stButton>button {
            min-height: 42px;
            font-weight:700;
            border-radius: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def current_user() -> dict | None:
    return st.session_state.current_user


def set_main_nav(page: str) -> None:
        """Set pending nav change (will be applied before radio widget instantiation)."""
        st.session_state.pending_main_nav_change = page


def dashboard_metrics(vacations: list[dict], holidays: dict[date, str]) -> dict[str, str | int]:
        pending = sum(1 for vacation in vacations if vacation["status"] == "pending")
        approved = sum(1 for vacation in vacations if vacation["status"] == "approved")
        today_absences = sum(
                1
                for vacation in vacations
                if vacation["status"] == "approved" and vacation["start_date"] <= date.today() <= vacation["end_date"]
        )
        future_holidays = sorted([holiday for holiday in holidays if holiday >= date.today()])
        next_holiday = "Sem feriados próximos"
        if future_holidays:
                holiday = future_holidays[0]
                next_holiday = f"{format_date(holiday)} - {holidays[holiday]}"

        current = st.session_state.current_month
        conflict_days = 0
        for day in range(1, 32):
                try:
                        current_day = date(current.year, current.month, day)
                except ValueError:
                        continue
                approved_count = sum(
                        1
                        for vacation in vacations
                        if vacation["status"] == "approved" and vacation["start_date"] <= current_day <= vacation["end_date"]
                )
                if approved_count >= st.session_state.conflict_limit:
                        conflict_days += 1

        return {
                "pending": pending,
                "approved": approved,
                "today_absences": today_absences,
                "conflict_days": conflict_days,
                "next_holiday": next_holiday,
        }


def render_login_pitch() -> None:
        st.markdown(
                """
                <div class='login-pitch'>
                    <div class='login-pitch-title'>Pedido simples, estado visível, gestão mais rápida</div>
                    <div class='login-pitch-text'>
                        Esta aplicação junta o essencial que se vê em soluções como MarQHR, Factorial ou Cegid Visualtime:
                        pedidos autónomos, acompanhamento em tempo real e uma visão clara para a equipa.
                    </div>
                    <div class='login-pitch-list'>
                        <div class='login-pitch-item'>
                            <div class='login-pitch-badge'>1</div>
                            <div>
                                <div class='login-pitch-item-title'>Pedido em poucos cliques</div>
                                <div class='login-pitch-item-text'>O colaborador seleciona o período e submete sem e-mails ou passos manuais.</div>
                            </div>
                        </div>
                        <div class='login-pitch-item'>
                            <div class='login-pitch-badge'>2</div>
                            <div>
                                <div class='login-pitch-item-title'>Estado sempre claro</div>
                                <div class='login-pitch-item-text'>Pedidos pendentes, aprovados ou rejeitados ficam visíveis no mesmo local.</div>
                            </div>
                        </div>
                        <div class='login-pitch-item'>
                            <div class='login-pitch-badge'>3</div>
                            <div>
                                <div class='login-pitch-item-title'>Controlo operacional</div>
                                <div class='login-pitch-item-text'>Gestão de equipa, relatórios e backups para reduzir risco e trabalho repetitivo.</div>
                            </div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
        )


def render_dashboard_hero(vacations: list[dict], holidays: dict[date, str], current_page: str) -> None:
        metrics = dashboard_metrics(vacations, holidays)
        role = (current_user() or {}).get("role", "viewer")
        next_page = "Pedidos" if current_page == "Calendário" and role == "admin" else "Meus Pedidos" if role == "user" else "Relatórios"
        action_label = "Ir para pedidos" if next_page == "Pedidos" else "Ver os meus pedidos" if next_page == "Meus Pedidos" else "Abrir relatórios"
        action_hint = "Aprovar ou rejeitar solicitações" if next_page == "Pedidos" else "Acompanhar o estado dos pedidos" if next_page == "Meus Pedidos" else "Exportar e rever estatísticas"

        st.markdown(
                f"""
                <div class='hero-shell'>
                    <div class='hero-grid'>
                        <div>
                            <div class='hero-eyebrow'>{t('hero_eyebrow')}</div>
                            <div class='hero-title'>{t('hero_title')}</div>
                            <div class='hero-copy'>
                                {t('hero_copy')}
                            </div>
                            <div class='hero-pills'>
                                <span class='hero-pill'>Pedido autónomo</span>
                                <span class='hero-pill'>Estado em tempo real</span>
                                <span class='hero-pill'>Relatórios prontos</span>
                                <span class='hero-pill'>Backup e restauro</span>
                            </div>
                            <div class='hero-steps'>
                                <div class='hero-step'>
                                    <div class='hero-step-number'>1</div>
                                    <div class='hero-step-title'>Escolher datas</div>
                                    <div class='hero-step-text'>Seleciona um dia ou um intervalo diretamente no calendário.</div>
                                </div>
                                <div class='hero-step'>
                                    <div class='hero-step-number'>2</div>
                                    <div class='hero-step-title'>Submeter pedido</div>
                                    <div class='hero-step-text'>O pedido entra no sistema com o tipo de ausência e comentários.</div>
                                </div>
                                <div class='hero-step'>
                                    <div class='hero-step-number'>3</div>
                                    <div class='hero-step-title'>Acompanhar estado</div>
                                    <div class='hero-step-text'>A aprovação, rejeição e conflitos ficam visíveis sem sair da app.</div>
                                </div>
                            </div>
                        </div>
                        <div>
                            <div class='hero-metrics'>
                                <div class='hero-metric'>
                                    <div class='hero-metric-label'>Pedidos pendentes</div>
                                    <div class='hero-metric-value'>{metrics['pending']}</div>
                                    <div class='hero-metric-note'>Aguardam validação da equipa responsável.</div>
                                </div>
                                <div class='hero-metric'>
                                    <div class='hero-metric-label'>Aprovados</div>
                                    <div class='hero-metric-value'>{metrics['approved']}</div>
                                    <div class='hero-metric-note'>Pedidos já confirmados no sistema.</div>
                                </div>
                                <div class='hero-metric'>
                                    <div class='hero-metric-label'>Ausentes hoje</div>
                                    <div class='hero-metric-value'>{metrics['today_absences']}</div>
                                    <div class='hero-metric-note'>Colaboradores fora do serviço no dia atual.</div>
                                </div>
                                <div class='hero-metric'>
                                    <div class='hero-metric-label'>Dias com conflito</div>
                                    <div class='hero-metric-value'>{metrics['conflict_days']}</div>
                                    <div class='hero-metric-note'>No mês em foco, com base no limite configurado.</div>
                                </div>
                            </div>
                            <div class='hero-action' style='margin-top:10px;'>
                                <div class='hero-action-title'>Próximo feriado</div>
                                <div class='hero-action-text'>{metrics['next_holiday']}</div>
                            </div>
                        </div>
                    </div>
                    <div class='hero-actions'>
                        <div class='hero-action'>
                            <div class='hero-action-title'>{action_label}</div>
                            <div class='hero-action-text'>{action_hint}</div>
                        </div>
                        <div class='hero-action'>
                            <div class='hero-action-title'>Visão da equipa</div>
                            <div class='hero-action-text'>Calendário, pedidos e relatórios alinhados numa única experiência.</div>
                        </div>
                        <div class='hero-action'>
                            <div class='hero-action-title'>Menos trabalho manual</div>
                            <div class='hero-action-text'>Menos e-mails, menos folhas soltas, mais controlo operacional.</div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
        )

        if st.button(action_label, key=f"hero_action_{next_page}", type="primary"):
                set_main_nav(next_page)
                st.rerun()


def is_admin() -> bool:
    return bool(current_user()) and current_user().get("role") == "admin"


def get_status_emoji(status: str) -> str:
    emojis = {
        "pending": "⏳",
        "approved": "✅",
        "rejected": "❌",
    }
    return emojis.get(status, "📋")


def get_absence_emoji(absence_type: str) -> str:
    emojis = {
        "Férias": "🏖️",
        "Meio-dia": "☀️",
        "Compensação": "⚡",
        "Outro": "📌",
    }
    return emojis.get(absence_type, "📅")


def add_compensations_to_holidays(vacations: list[dict], holidays: dict[date, str]) -> dict[date, str]:
    """Add approved 'Compensação' (time-off compensation) as holidays so they don't count as business days."""
    result = dict(holidays)  # Create a copy to avoid modifying the original
    for vacation in vacations:
        if vacation.get("absence_type") == "Compensação" and vacation.get("status") == "approved":
            start_date = vacation.get("start_date")
            end_date = vacation.get("end_date")
            if start_date and end_date:
                current = start_date
                while current <= end_date:
                    result[current] = "Tolerância de Ponto"
                    current += timedelta(days=1)
    return result


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
                    old_status = vacation["status"]
                    vacation["status"] = new_status
                    if new_status == "approved":
                        vacation["approved_at"] = datetime.now()
                        vacation["approved_by"] = (current_user() or {}).get("username", "")
                    else:
                        vacation["approved_at"] = None
                        vacation["approved_by"] = ""
                    # Log the mutation
                    log_mutation(
                        action="status_change",
                        entity="vacation",
                        entity_id=vacation_id,
                        username=(current_user() or {}).get("username"),
                        details={"old_status": old_status, "new_status": new_status, "employee": vacation.get("employee_name")},
                    )
    mutate_data(apply_change)


def delete_vacation(vacation_id: str) -> None:
    if not is_admin():
        raise DataStoreError("Só administradores podem eliminar pedidos.")

    def apply_change(vacations: list[dict], _: list[dict], __: dict[str, dict]) -> None:
        updated = [v for v in vacations if v["id"] != vacation_id]
        if len(updated) == len(vacations):
            raise DataStoreError("Pedido não encontrado para eliminar.")
            deleted = next((v for v in vacations if v["id"] == vacation_id), None)
            # Log the deletion
            if deleted:
                log_mutation(
                    action="delete",
                    entity="vacation",
                    entity_id=vacation_id,
                    username=(current_user() or {}).get("username"),
                    details={"employee": deleted.get("employee_name"), "period": f"{deleted.get('start_date')} to {deleted.get('end_date')}"},
                )

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


def sync_range_from_new_request_dates() -> None:
    start = st.session_state.get("new_request_start", date.today())
    end = st.session_state.get("new_request_end", start)
    if start <= end:
        normalized_start, normalized_end = start, end
    else:
        normalized_start, normalized_end = end, start
    st.session_state.new_request_start = normalized_start
    st.session_state.new_request_end = normalized_end
    st.session_state.range_start = normalized_start
    st.session_state.range_end = normalized_end
    st.session_state.selected_day = normalized_end
    st.session_state.current_month = date(normalized_end.year, normalized_end.month, 1)


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
    left, center, right = st.columns([1.1, 1.6, 1.3])
    with center:
        st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
        st.subheader("Iniciar sessão")
        st.caption("Admin aprova e gere pessoal. Utilizador cria pedidos. Consulta apenas vê informação.")
        with st.form("login_form"):
            username = st.text_input("Utilizador")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Entrar", type="primary", width='stretch')
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
    with right:
        render_login_pitch()


def top_header() -> None:
    role = (current_user() or {}).get("role", "viewer")
    nav = NAV_ADMIN if role == "admin" else NAV_USER if role == "user" else NAV_VIEWER
    if st.session_state.main_nav not in nav:
        st.session_state.main_nav = nav[0]

    left, right = st.columns([3, 2])
    with left:
        st.title(t("title"))
        st.markdown("<div class='page-kicker'>Planeamento simples, visual limpo e pedidos organizados.</div>", unsafe_allow_html=True)
    with right:
        info_left, info_right = st.columns([3, 1])
        with info_left:
            user = current_user() or {}
            st.caption(f"Sessão: {user.get('name', '-')}")
        with info_right:
            if st.button(t("logout"), width='stretch'):
                st.session_state.authenticated = False
                st.session_state.current_user = None
                st.rerun()


def render_sidebar_navigation(vacations: list[dict], holidays: dict[date, str]) -> None:
    # Apply any pending nav change before instantiating the radio widget
    if st.session_state.pending_main_nav_change:
        st.session_state.main_nav = st.session_state.pending_main_nav_change
        st.session_state.pending_main_nav_change = None
    
    role = (current_user() or {}).get("role", "viewer")
    nav = NAV_ADMIN if role == "admin" else NAV_USER if role == "user" else NAV_VIEWER
    if st.session_state.main_nav not in nav:
        st.session_state.main_nav = nav[0]

    pending = sum(1 for vacation in vacations if vacation["status"] == "pending")
    approved = sum(1 for vacation in vacations if vacation["status"] == "approved")
    next_holiday = "Sem feriados próximos"
    future_holidays = sorted([holiday for holiday in holidays if holiday >= date.today()])
    if future_holidays:
        holiday = future_holidays[0]
        next_holiday = f"{format_date(holiday)} - {holidays[holiday]}"

    st.sidebar.markdown(
        f"""
        <div class='sidebar-shell'>
            <div class='sidebar-brand'>📅 {t('sidebar_brand')}</div>
            <div class='sidebar-brand-sub'>Visão compacta, ações rápidas e leitura clara.</div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.markdown("<div class='sidebar-section-title'>Navegação</div>", unsafe_allow_html=True)
    icons = {
        "Calendário": "📆",
        "Pedidos": "📨",
        "Meus Pedidos": "📨",
        "Relatórios": "📊",
        "Pessoal": "👥",
        "Logins": "🔐",
        "Backup": "💾",
    }
    def nav_label(x: str) -> str:
        return f"{icons.get(x, '•')}  {x}"

    st.sidebar.radio(
        "Navegação",
        options=nav,
        key="main_nav",
        format_func=nav_label,
        label_visibility="collapsed",
    )

    st.sidebar.markdown("<div class='sidebar-section-title'>Resumo rápido</div>", unsafe_allow_html=True)
    st.sidebar.markdown(
        f"""
        <div class='sidebar-metric-grid'>
            <div class='sidebar-metric'>
                <div class='sidebar-metric-label'>Pendentes</div>
                <div class='sidebar-metric-value'>{pending}</div>
                <div class='sidebar-metric-note'>A aguardar validação</div>
            </div>
            <div class='sidebar-metric'>
                <div class='sidebar-metric-label'>Aprovados</div>
                <div class='sidebar-metric-value'>{approved}</div>
                <div class='sidebar-metric-note'>Já confirmados</div>
            </div>
        </div>
        <div class='sidebar-action'>
            <div class='sidebar-action-title'>Próximo feriado</div>
            <div class='sidebar-action-text'>{next_holiday}</div>
        </div>
        <div class='sidebar-action'>
            <div class='sidebar-action-title'>Menu atual</div>
            <div class='sidebar-action-text'>{st.session_state.main_nav}</div>
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    quick_label = "Abrir pedidos" if role == "admin" else "Ver pedidos" if role == "user" else "Abrir relatórios"
    quick_target = "Pedidos" if role == "admin" else "Meus Pedidos" if role == "user" else "Relatórios"
    if st.sidebar.button(quick_label, key="sidebar_quick_action", type="primary", width='stretch'):
        set_main_nav(quick_target)
        st.rerun()

    # Language selector
    lang_options = [TRANSLATIONS['pt']['language_pt'], TRANSLATIONS['pt']['language_en']]
    current_index = 0 if st.session_state.lang == 'pt' else 1
    sel = st.sidebar.selectbox("Idioma", options=lang_options, index=current_index, key="ui_lang")
    st.session_state.lang = 'pt' if sel == TRANSLATIONS['pt']['language_pt'] else 'en'

    # Admin quick action: mark a manual compensação (tolerância de ponto)
    if is_admin():
        st.sidebar.markdown("<hr>", unsafe_allow_html=True)
        st.sidebar.markdown("<div style='font-weight:700; margin-bottom:6px;'>Marcar tolerância de ponto (admin)</div>", unsafe_allow_html=True)
        manual_tol = st.sidebar.date_input("Data (tolerância)", value=date.today(), key="manual_tol_date")
        tol_label = st.sidebar.text_input("Rótulo", value="Tolerância de Ponto (Admin)", key="manual_tol_label")
        if st.sidebar.button("Marcar tolerância", key="mark_tol_action", width='stretch'):
            def apply_tol(vacations: list[dict], staff: list[dict], users: dict[str, dict]) -> None:
                vacations.append(
                    {
                        "id": str(uuid4()),
                        "employee_name": tol_label,
                        "start_date": manual_tol,
                        "end_date": manual_tol,
                        "absence_type": "Compensação",
                        "status": "approved",
                        "requested_at": datetime.now(),
                        "approved_at": datetime.now(),
                        "approved_by": (current_user() or {}).get("username", "admin"),
                        "created_by": (current_user() or {}).get("username", "admin"),
                        "team": "",
                        "reason": "Marca manual de tolerância",
                    }
                )
            try:
                mutate_data(apply_tol)
                st.sidebar.success("Tolerância marcada com sucesso.")
                st.experimental_rerun()
            except DataStoreError as exc:
                st.sidebar.error(f"Falha ao marcar tolerância: {exc}")

    st.sidebar.markdown("</div>", unsafe_allow_html=True)


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
    st.markdown("<div class='section-shell calendar-shell'>", unsafe_allow_html=True)
    nav1, nav2, nav3, nav4 = st.columns([1, 2, 1, 1])
    with nav1: st.button("<", key="prev_month", on_click=previous_month, width='stretch')
    with nav2: st.markdown(f"### {month_name_pt(current.month)} {current.year}")
    with nav3: st.button("Hoje", key="this_month", on_click=this_month, width='stretch')
    with nav4: st.button(">", key="next_month", on_click=next_month, width='stretch')
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
                    holiday_label = holidays[cell]
                    flags.append(holiday_label if holiday_label == "Tolerância de Ponto" else "Feriado")
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
                    width='stretch',
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
    st.markdown("</div>", unsafe_allow_html=True)


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
        status_emoji = get_status_emoji(status)
        absence_emoji = get_absence_emoji(vacation.get('absence_type', 'Férias'))
        
        st.markdown(
            f"""
            <div class='request-card'>
                <div class='request-header'>
                    <div class='request-title'>{absence_emoji} {vacation['employee_name']}</div>
                    <span class='status-badge status-{status}'>{status_emoji} {STATUS_LABELS.get(status, status).upper()}</span>
                </div>
                <div style='color: #475569; font-size: 13px; line-height: 1.6;'>
                    <strong>Tipo:</strong> {vacation.get('absence_type', 'Férias')} | <strong>Duração:</strong> {duration} dias<br>
                    <strong>Período:</strong> {format_date(vacation['start_date'])} até {format_date(vacation['end_date'])}<br>
                    <strong>Equipa:</strong> {vacation.get('team', 'Sem equipa')} | <strong>Pedido em:</strong> {vacation['requested_at'].strftime('%d/%m/%Y %H:%M')}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
        if vacation.get("reason"):
            st.caption(f"💬 Comentário: {vacation['reason']}")
        
        if can_manage:
            a1, a2, a3 = st.columns(3)
            if status == "pending":
                if a1.button("✅ Aprovar", key=f"approve_{vacation['id']}"):
                    update_vacation_status(vacation["id"], "approved")
                    st.rerun()
                if a2.button("❌ Rejeitar", key=f"reject_{vacation['id']}"):
                    update_vacation_status(vacation["id"], "rejected")
                    st.rerun()
            if a3.button("🗑️ Eliminar", key=f"delete_{vacation['id']}"):
                delete_vacation(vacation["id"])
                st.rerun()
        else:
            st.caption("🔒 Perfil de consulta: sem permissão para alterar pedidos.")
        
        st.divider()


def render_login_management() -> None:
    st.subheader("🔐 Gestão de logins")
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
        submitted = st.form_submit_button("Criar login", width='stretch')
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

                try:
                    mutate_data(apply_change)
                    st.success("Login criado com sucesso.")
                except DataStoreError as exc:
                    st.error(str(exc))
                request_login_form_reset()
                st.rerun()
    if st.button("Limpar", key="clear_login_form", width='stretch'):
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
    st.dataframe(users_table, width='stretch', hide_index=True)
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
            submitted_edit = st.form_submit_button("Guardar alterações do login", width='stretch')
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

                    try:
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
                    except DataStoreError as exc:
                        st.error(str(exc))

    removable_users = [username for username in sorted(st.session_state.users) if username != "admin"]
    if removable_users:
        remove_username = st.selectbox("Remover login", options=removable_users)
        if st.button("Remover login", width='stretch'):
            def apply_change(_: list[dict], __: list[dict], users: dict[str, dict]) -> None:
                if remove_username not in users:
                    raise DataStoreError("Login não encontrado.")
                if (current_user() or {}).get("username") == remove_username:
                    raise DataStoreError("Não pode remover a conta com a sessão atual.")
                del users[remove_username]

            try:
                mutate_data(apply_change)
                st.success("Login removido com sucesso.")
                st.rerun()
            except DataStoreError as exc:
                st.error(str(exc))
    else:
        st.info("Não existem logins removíveis neste momento.")


def render_new_request_form(holidays: dict[date, str]) -> None:
    st.subheader(t("new_request_subheader") if st.session_state.lang == 'en' else "✏️ Novo pedido a partir do calendário")
    st.caption(t("new_request_caption") if st.session_state.lang == 'en' else "Clique num dia para um pedido de 1 dia. Clique noutro dia para fechar um intervalo.")
    if st.session_state.pending_new_request_reset:
        apply_new_request_reset()
        st.session_state.pending_new_request_reset = False

    selected_staff = None
    range_start, range_end = selected_range()

    active_staff_names = sorted([p["Nome"] for p in st.session_state.staff if p.get("Ativo", True)])
    if is_admin() and active_staff_names:
        st.markdown("<span class='sr-only'>Colaborador selector</span>", unsafe_allow_html=True)
        employee_name = st.selectbox("Colaborador", options=active_staff_names)
        selected_staff = next((p for p in st.session_state.staff if p["Nome"] == employee_name), None)
    elif is_user():
        selected_staff = current_user_staff()
        employee_name = selected_staff["Nome"] if selected_staff else (current_user() or {}).get("staff_name", "")
        st.markdown("<span class='sr-only'>Colaborador</span>", unsafe_allow_html=True)
        st.text_input("Colaborador", value=employee_name, disabled=True)
    else:
        st.markdown("<span class='sr-only'>Nome do colaborador</span>", unsafe_allow_html=True)
        employee_name = st.text_input("Nome do colaborador")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("<span class='sr-only'>Data de início</span>", unsafe_allow_html=True)
        st.date_input(
            "Data de início",
            value=st.session_state.new_request_start,
            key="new_request_start",
            format="DD/MM/YYYY",
            on_change=sync_range_from_new_request_dates,
        )
        absence_type = st.selectbox("Tipo de ausência", options=ABSENCE_TYPES, key="new_request_absence_type")
        half_day = st.checkbox("Meio dia", key="new_request_half_day", disabled=range_start != range_end)
    with col_b:
        st.markdown("<span class='sr-only'>Data de fim</span>", unsafe_allow_html=True)
        st.date_input(
            "Data de fim",
            value=st.session_state.new_request_end,
            key="new_request_end",
            format="DD/MM/YYYY",
            on_change=sync_range_from_new_request_dates,
        )
        replacement_contact = st.text_input("Substituto / contacto", key="new_request_replacement")
    reason = st.text_area("Comentário (opcional)", key="new_request_reason")

    range_start, range_end = selected_range()

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
    submitted = action_submit.button(t("submit_request") if st.session_state.lang == 'en' else "Submeter pedido", key="submit_new_request", type="primary", width='stretch')
    cleared = action_clear.button(t("clear_request") if st.session_state.lang == 'en' else "Limpar", key="clear_new_request_form", width='stretch')
    if cleared:
        request_new_request_reset()
        st.rerun()
    if submitted:
        if not employee_name.strip():
            st.error(t("fill_employee_name") if st.session_state.lang == 'en' else "Preencha o nome do colaborador.")
            return
        if is_user() and not selected_staff:
            st.error(t("account_needs_staff") if st.session_state.lang == 'en' else "A tua conta precisa de estar associada a uma pessoa do pessoal.")
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
            # Log the creation
            log_mutation(
                action="create",
                entity="vacation",
                entity_id=new_request["id"],
                username=new_request.get("created_by"),
                details={
                    "employee": new_request["employee_name"],
                    "absence_type": new_request["absence_type"],
                    "period": f"{new_request['start_date']} to {new_request['end_date']}",
                    "team": new_request.get("team"),
                },
            )

        try:
            mutate_data(apply_change)
            st.success("Pedido criado com sucesso.")
        except DataStoreError as exc:
            st.error(f"Falha ao criar pedido: {exc}")
            return
        request_new_request_reset()
        st.rerun()


def render_staff_table() -> None:
    st.subheader("👥 Tabela de Pessoal")
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
        submitted = action_submit.button("Adicionar colaborador", key="submit_staff_form", width='stretch')
        cleared = action_clear.button("Limpar", key="clear_staff_form", width='stretch')
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

                try:
                    mutate_data(apply_change)
                except DataStoreError as exc:
                    st.error(str(exc))
                else:
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

                try:
                    mutate_data(apply_change)
                except DataStoreError as exc:
                    st.error(str(exc))
                else:
                    st.success("Colaborador removido.")
                    st.rerun()
        else:
            st.info("Sem colaboradores para remover.")

    if not st.session_state.staff:
        st.info("Ainda não existem colaboradores na tabela de pessoal.")
        return

    edited_df = st.data_editor(
        pd.DataFrame(st.session_state.staff),
        width='stretch',
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

        try:
            mutate_data(apply_change)
        except DataStoreError as exc:
            st.error(str(exc))
        else:
            st.success("Tabela de pessoal atualizada.")
            st.rerun()


def render_reports() -> None:
    st.subheader("📊 Relatórios")
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
    st.dataframe(collaborator_df, width='stretch', hide_index=True)

    st.markdown("**Resumo por estado**")
    st.dataframe(summary_df, width='stretch', hide_index=True)

    if not approved_df.empty:
        st.markdown("**Férias autorizadas**")
        st.dataframe(approved_df, width='stretch', hide_index=True)
    if not pending_df.empty:
        st.markdown("**Férias pendentes**")
        st.dataframe(pending_df, width='stretch', hide_index=True)

    export_col1, export_col2 = st.columns(2)
    detail_csv_data = detail_df.to_csv(index=False).encode("utf-8-sig")
    summary_csv_data = collaborator_df.to_csv(index=False).encode("utf-8-sig")
    export_col1.download_button(
        "Descarregar detalhe CSV",
        data=detail_csv_data,
        file_name=f"relatorio_ferias_detalhe_{selected_team.lower()}_{selected_year}_{selected_month or 'ano'}.csv",
        mime="text/csv",
        width='stretch',
    )
    export_col2.download_button(
        "Descarregar resumo CSV",
        data=summary_csv_data,
        file_name=f"relatorio_ferias_resumo_{selected_team.lower()}_{selected_year}_{selected_month or 'ano'}.csv",
        mime="text/csv",
        width='stretch',
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
                width='stretch',
            )
    else:
        st.info("Não existem férias aprovadas para gerar o mapa anual com os filtros atuais.")

    st.markdown("**Detalhe completo do relatório**")
    st.dataframe(detail_df, width='stretch', hide_index=True)

    csv_data = detail_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Descarregar relatório completo CSV",
        data=csv_data,
        file_name=f"relatorio_ferias_{selected_team.lower()}_{selected_year}_{selected_month or 'ano'}.csv",
        mime="text/csv",
        width='stretch',
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
    st.subheader("💾 Backup e restauro")
    payload = build_backup_payload()
    backup_text = json.dumps(payload, ensure_ascii=False, indent=2)
    st.download_button(
        "Descarregar backup (.json)",
        data=backup_text,
        file_name=f"backup_ferias_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
        width='stretch',
    )
    if st.button("Criar snapshot local", width='stretch'):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUP_DIR / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        backup_path.write_text(backup_text, encoding="utf-8")
        st.success(f"Snapshot criado em {backup_path.name}")
    uploaded = st.file_uploader("Restaurar de ficheiro", type=["json"])
    if uploaded is not None and st.button("Restaurar backup", type="primary", width='stretch'):
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
    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
    with c1:
        team_filter = st.selectbox("Filtro por equipa", ["Todas"] + teams)
    with c2:
        status_filter = st.selectbox("Estado", options=STATUS_OPTIONS, format_func=lambda x: STATUS_LABELS[x])
    with c3:
        st.session_state.conflict_limit = st.number_input("Limite conflito", min_value=1, max_value=20, value=st.session_state.conflict_limit, step=1)
    with c4:
        st.session_state.selected_municipality = st.selectbox(
            "Feriado municipal",
            options=list(MUNICIPAL_HOLIDAYS.keys()),
            key="municipality_selector"
        )
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
    holidays = cached_portugal_holidays(st.session_state.current_month.year, st.session_state.selected_municipality)
    # Add approved compensations as holidays (they don't count as business days)
    holidays = add_compensations_to_holidays(st.session_state.vacations, holidays)
    scope = "all" if is_admin() or (current_user() or {}).get("role") == "viewer" else "mine"
    visible_vacations = filtered_vacations(team_filter, status_filter, scope=scope)
    render_sidebar_navigation(visible_vacations, holidays)
    nav = NAV_ADMIN if is_admin() else NAV_USER if is_user() else NAV_VIEWER
    current_page = st.session_state.get("main_nav", nav[0])

    if current_page == "Calendário":
        render_dashboard_hero(visible_vacations, holidays, current_page)
    else:
        page_subtitle = {
            "Pedidos": "Aprovações e rejeições em destaque.",
            "Meus Pedidos": "Acompanhar o estado dos teus pedidos.",
            "Relatórios": "Análise e exportação dos dados.",
            "Pessoal": "Gestão da equipa e associações.",
            "Logins": "Contas, perfis e permissões.",
            "Backup": "Exportação e restauro seguro.",
        }.get(current_page, "")
        st.markdown(
            f"""
            <div class='soft-card' style='margin-bottom: 16px;'>
                <div class='stat-title'>SECÇÃO ATUAL</div>
                <div class='stat-value' style='font-size: 24px; margin-top: 4px;'>{current_page}</div>
                <div class='badge-row'>{page_subtitle}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

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
