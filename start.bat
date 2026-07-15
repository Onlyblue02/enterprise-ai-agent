@echo off
setlocal
cd /d "%~dp0"
echo Starting Enterprise AI Agent...
.venv\Scripts\python.exe -m streamlit run app.py
pause
