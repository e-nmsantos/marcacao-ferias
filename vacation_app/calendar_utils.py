from __future__ import annotations

from datetime import date, timedelta

from vacation_app.constants import MUNICIPAL_HOLIDAYS


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


def holidays_for_period(start: date, end: date, municipality: str = "Nenhum") -> dict[date, str]:
    years = range(start.year, end.year + 1)
    holidays: dict[date, str] = {}
    for year in years:
        holidays.update(portugal_holidays(year, municipality))
    return holidays


def format_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def calculate_days(start: date, end: date) -> int:
    return (end - start).days + 1


def calculate_business_days(start: date, end: date, holidays: dict[date, str] | None = None) -> int:
    holiday_map = holidays or holidays_for_period(start, end)
    current = start
    total = 0
    while current <= end:
        if current.weekday() < 5 and current not in holiday_map:
            total += 1
        current += timedelta(days=1)
    return total
