Demo — Gestao de Férias

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
