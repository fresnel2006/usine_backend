@echo off
title API Gestion de l usine
cd /d "%~dp0"
call venv\Scripts\activate.bat
uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
