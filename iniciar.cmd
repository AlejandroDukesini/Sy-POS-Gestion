@echo off
rem Inicia POS-PY con el entorno de Python del proyecto (backend\.venv); lo crea si no existe.
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (
  echo Preparando el entorno de Python por primera vez...
  python -m venv .venv || exit /b 1
  .venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
)
.venv\Scripts\python.exe -m pospy %*
