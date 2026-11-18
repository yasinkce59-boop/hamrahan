@echo off
cd /d "%~dp0"
if not exist .venv (py -3 -m venv .venv)
call .venv\Scripts\activate
python -m pip install -r requirements.txt
set SESSION_SECRET=REPLACE-WITH-A-LONG-RANDOM-SECRET
python -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
