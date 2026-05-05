Demo — Gestao de Férias

Visual assets generated:
- screenshots/01-login.png
- screenshots/02-calendar.png
- screenshots/03-pedidos.png
- screenshots/04-relatorios.png
- screenshots/05-pessoal.png
- screenshots/06-logins.png
- screenshots/07-backup.png
- MOCKUP.md
- mockup.html

Quick start (Windows PowerShell):

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run python_app.py
```

Files of interest for the demo:
- `python_app.py` — entrada Streamlit (UI)
- `vacation_app/` — backend (auth, calendar_utils, storage, reports, excel_export)
- `app-mockup.svg`, `test-image.png` — visual assets

Notes:
- To test the packaging of `vacation_app`, run `pip install -e .` in the repo root to install the package in editable mode.
- For development, use Python 3.11+.
