@echo off
setlocal
rem Web editor cuc bo: http://localhost:8080/web/
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Khong thay .venv. Chay: python -m venv .venv
    pause
    exit /b 1
)
set "PY=%~dp0.venv\Scripts\python.exe"

rem Cai/cap nhat thu vien neu thieu (numpy, pillow, pydantic, mcp)
"%PY%" -c "import numpy, PIL, pydantic, mcp" 2>nul || "%PY%" -m pip install -e "%~dp0."

if not exist "%~dp0logs" mkdir "%~dp0logs"
set "PYTHONUTF8=1"
set "URL=http://localhost:8080/web/"
echo Mo %URL%
start "" "%URL%"
echo Log: logs\web.log  (Ctrl+C de dung)
"%PY%" "%~dp0web_server.py" >> "%~dp0logs\web.log" 2>&1
pause
