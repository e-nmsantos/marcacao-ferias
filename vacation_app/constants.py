from __future__ import annotations

from pathlib import Path

DATA_VERSION = 3
DATA_FILE = Path(__file__).resolve().parent.parent / "data_store.json"
DB_FILE = Path(__file__).resolve().parent.parent / "ferias.db"
BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
LOCK_FILE = Path(__file__).resolve().parent.parent / "data_store.lock"
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
        "staff_name": "",
    },
    "consulta": {
        "password_hash": "pbkdf2_sha256$200000$YebZRordTvC6IDp4crXIsg==$+Zw8GBqoiJSRTp998XC2R85o6Tq/8cVf4gvHFnB0nJ8=",
        "role": "viewer",
        "name": "Consulta",
        "staff_name": "",
    },
}

EMPLOYEE_NAME_ALIASES = {
    "MR": "Mónica Romão",
}

MUNICIPAL_HOLIDAYS = {
    "Nenhum": None,
    "Lisboa": (6, 13, "Santo António"),
    "Porto": (6, 24, "São João"),
    "Braga": (12, 8, "Imaculada Conceição (Municipal)"),
    "Coimbra": (7, 4, "Rainha Santa Isabel"),
}
