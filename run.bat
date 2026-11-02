@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%~dp0vendor"
python -m streamlit run app.py
pause
