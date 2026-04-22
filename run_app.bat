@echo off
setlocal

cd /d "%~dp0"
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"
set "STREAMLIT_SERVER_ADDRESS=127.0.0.1"
if /I "%ALLOW_LAN%"=="1" set "STREAMLIT_SERVER_ADDRESS=0.0.0.0"

if not exist ".streamlit" mkdir ".streamlit"
> ".streamlit\config.toml" (
  echo [browser]
  echo gatherUsageStats = false
  echo.
  echo [theme]
  echo base = "light"
  echo primaryColor = "#5E81AC"
  echo backgroundColor = "#ECEFF4"
  echo secondaryBackgroundColor = "#E5E9F0"
  echo textColor = "#2E3440"
)
> ".streamlit\credentials.toml" (
  echo [general]
  echo email = ""
)

echo [1/3] A verificar Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo Python nao encontrado no PATH.
  echo Instale o Python e tente novamente.
  pause
  exit /b 1
)

echo [2/3] A verificar dependencias...
if not exist "venv" (
  echo A criar ambiente virtual isolado...
  python -m venv venv
)
call venv\Scripts\activate

python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
  echo Streamlit nao encontrado. A instalar dependencias...
  echo A tentar com timeout/retries alargados...
  python -m pip install -r requirements-python.txt --default-timeout 120 --retries 10 --no-cache-dir
  if errorlevel 1 (
    echo Primeira tentativa falhou. A tentar com index explicito do PyPI...
    python -m pip install -r requirements-python.txt --index-url https://pypi.org/simple --trusted-host pypi.org --trusted-host files.pythonhosted.org --default-timeout 120 --retries 10 --no-cache-dir
    if errorlevel 1 (
      echo Falha ao instalar dependencias.
      echo.
      echo Possiveis causas:
      echo 1^) Sem acesso a internet
      echo 2^) Proxy/firewall corporativa a bloquear pypi.org
      echo 3^) DNS ou ligacao instavel
      echo.
      echo Se estiver em rede corporativa, configure proxy para pip e tente novamente.
      pause
      exit /b 1
    )
  )
)

echo [3/3] A iniciar aplicacao...
echo Endereco configurado: %STREAMLIT_SERVER_ADDRESS%:8501
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R ":8501\>" ^| findstr LISTENING') do (
  echo A libertar porto 8501 ^(PID %%a^)...
  taskkill /PID %%a /F >nul 2>&1
)
python -m streamlit run python_app.py --browser.gatherUsageStats=false --server.address=%STREAMLIT_SERVER_ADDRESS% --server.port=8501
if errorlevel 1 (
  echo.
  echo A aplicacao terminou com erro.
  pause
  exit /b 1
)

echo.
echo Aplicacao terminada.
pause

endlocal
