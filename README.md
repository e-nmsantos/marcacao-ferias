# Leave Management (marcacao-ferias)

A leave and absence management app for small and medium-sized teams. Employees request time off in a few clicks, managers approve with a real-time view of the team, and administrators handle people, accounts, reports and backups.

Built with **Python** and **Streamlit**, with **SQLite** by default and optional **PostgreSQL** for shared, persistent deployments.

## Features

**Employees**
- Interactive calendar to pick leave dates
- Simple requests: absence type, optional comment, substitute
- Request status always visible (pending, approved, rejected)

**Managers**
- Approve or reject pending requests
- Team calendar with all approved absences
- Conflict alerts for days with many simultaneous absences
- Excel reports with statistics

**Administrators**
- Staff management (add, edit, deactivate)
- Account management with roles: `admin`, `user`, `viewer`
- Backup and restore (JSON), plus local snapshots
- Compensation days ("tolerância de ponto") counted as holidays
- Portuguese national holidays and municipal holidays by municipality
- Interface in Portuguese and English

## Quick start

Requirements: Python 3.11+

```bash
git clone https://github.com/e-nmsantos/marcacao-ferias.git
cd marcacao-ferias
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -e .
streamlit run python_app.py
```

The app opens at `http://127.0.0.1:8501`.

On first run, sign in with the administrator account and **change its password immediately**. Then add staff under **People** and create accounts under **Logins**.

## Configuration

| Setting | Behaviour |
|---|---|
| *(none)* | Local SQLite database (`ferias.db`) |
| `DATABASE_URL` or `POSTGRES_URL` | PostgreSQL as primary storage |
| Streamlit secrets: `DATABASE_URL` or `[database] url` | PostgreSQL on Streamlit Community Cloud |

Legacy JSON backups (`data_store.json`) can still be imported.

To share the app on a local network on Windows, run `set ALLOW_LAN=1` before `run_app.bat` and allow inbound traffic on port 8501.

## Deployment

**Docker**

```bash
docker-compose up -d     # app + optional PostgreSQL
docker-compose down
```

See [DOCKER.md](DOCKER.md) for environment variables, persistence, reverse proxy and health checks.

**Streamlit Community Cloud**: use `python_app.py` as the entry point and `requirements.txt` for dependencies. Configure an external PostgreSQL database (for example Neon) in the app's secrets, otherwise data can be lost when the instance is recreated.

## Security

- Passwords are stored as hashes, never in plain text
- Role-based access control (`admin`, `user`, `viewer`)
- Sessions validated at login

## Project structure

```
marcacao-ferias/
├── python_app.py          # Streamlit app
├── vacation_app/
│   ├── storage.py         # Persistence (SQLite / PostgreSQL)
│   ├── auth.py            # Authentication and hashing
│   ├── calendar_utils.py  # Calendar utilities
│   ├── constants.py       # Absence types, holidays
│   ├── excel_export.py    # Excel export
│   └── reports.py         # Reports
├── tests/test_core.py     # Unit tests
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Tests

```bash
python -m pytest -v
```

## Roadmap

- Google and Outlook calendar integration
- Email notifications
- Integration with HR systems

## Changelog

**v0.2.0 (May 2026)**: redesigned interface, PT/EN translations, accessibility improvements, compensation days, municipal holiday selector, clearer error handling.

**v0.1.0**: initial release with calendar, requests and reports.
