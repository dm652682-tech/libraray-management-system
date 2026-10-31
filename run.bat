@echo off
REM One-click start for Windows. Double-click this file.
cd /d "%~dp0"
if not exist .venv (
    echo Creating virtual environment...
    py -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate
pip install -q -r requirements.txt
if "%SECRET_KEY%"=="" set SECRET_KEY=change-me-to-a-long-random-text
start "" http://127.0.0.1:5000
python app.py
pause
