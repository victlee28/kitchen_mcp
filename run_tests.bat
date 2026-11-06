@echo off
rem Run every automated check on Windows. Usage: run_tests.bat [setup]
rem   setup  -> first install the project and dev tools (pydantic, numpy, pillow, jsonschema, mcp, pyright)
rem Needs Python 3.11 or newer on PATH (py -3.11 also works). Node is optional (only for tests\js).
setlocal
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3.11
if /i "%1"=="setup" (
  %PY% -m pip install -e ".[dev]" || goto :fail
)
echo === Python tests (includes architecture, golden, errors, pyright ratchet) ===
%PY% -W ignore -m unittest discover -s tests || goto :fail
where node >nul 2>nul
if %errorlevel%==0 (
  echo === Node tests ===
  node --test tests\js\menu-logic.test.mjs || goto :fail
) else (
  echo Node not found: skipping tests\js
)
echo.
echo ALL CHECKS PASSED
exit /b 0
:fail
echo.
echo CHECKS FAILED
exit /b 1
