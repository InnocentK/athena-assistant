@echo off
REM run.bat — Quick-start script for Athena Assistant (Windows)
REM Usage: run.bat [port]
REM Default port: 8000

setlocal

cd /d "%~dp0"

set PORT=%1
if "%PORT%"=="" set PORT=8000

REM Check for Python
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python not found. Please install Python 3.11 or later.
    exit /b 1
)

REM Create virtual environment if needed
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Install / update dependencies
echo Installing dependencies...
pip install --quiet -r requirements.txt

REM Ensure runtime directories exist
if not exist "logs" mkdir logs
if not exist "audit" mkdir audit
if not exist "data\carddav_staged" mkdir data\carddav_staged

REM Copy .env.example if .env is missing
if not exist ".env" (
    echo Notice: .env not found -- copying from .env.example. Edit it before running in production.
    copy .env.example .env >nul
)

echo Starting Athena Assistant on http://0.0.0.0:%PORT% ...
uvicorn main:app --reload --host 0.0.0.0 --port %PORT%
