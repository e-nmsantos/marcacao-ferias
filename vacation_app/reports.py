from __future__ import annotations

from datetime import date

from vacation_app.calendar_utils import calculate_business_days, calculate_days, format_date, month_name_pt
from vacation_app.constants import STATUS_LABELS


def report_period_label(year: int, month: int) -> str:
    if month == 0:
        return str(year)
    return f"{month_name_pt(month)} {year}"


def build_report_rows(
    vacations: list[dict],
    holidays: dict[date, str],
    year: int,
    month: int,
    team: str,
    statuses: list[str],
) -> list[dict]:
    rows: list[dict] = []
    for vacation in vacations:
        if vacation["status"] not in statuses:
            continue
        if team != "Todas" and vacation.get("team", "") != team:
            continue
        if month == 0:
            if vacation["start_date"].year != year and vacation["end_date"].year != year:
                continue
        else:
            period_start = date(year, month, 1)
            period_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            period_end = period_end.fromordinal(period_end.toordinal() - 1)
            if vacation["end_date"] < period_start or vacation["start_date"] > period_end:
                continue
        rows.append(
            {
                "Colaborador": vacation["employee_name"],
                "Equipa": vacation.get("team", ""),
                "Estado": STATUS_LABELS.get(vacation["status"], vacation["status"]),
                "Tipo": vacation.get("absence_type", "Férias"),
                "Início": format_date(vacation["start_date"]),
                "Fim": format_date(vacation["end_date"]),
                "Dias": calculate_days(vacation["start_date"], vacation["end_date"]),
                "Dias úteis": calculate_business_days(vacation["start_date"], vacation["end_date"], holidays),
                "Substituto": vacation.get("replacement_contact", ""),
                "Comentário": vacation.get("reason", ""),
                "Pedido em": vacation["requested_at"].strftime("%d/%m/%Y %H:%M"),
                "Aprovado em": vacation["approved_at"].strftime("%d/%m/%Y %H:%M") if vacation.get("approved_at") else "",
                "Aprovado por": vacation.get("approved_by", ""),
            }
        )
    rows.sort(key=lambda item: (item["Colaborador"], item["Início"]))
    return rows
