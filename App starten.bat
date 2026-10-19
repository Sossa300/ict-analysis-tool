@echo off
rem Startet die ICT-Top-Down-Analyse im Browser (http://localhost:8501).
rem Zum Beenden dieses Fenster schliessen.
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
echo Starte ICT-Top-Down-Analyse ... (Fenster offen lassen, solange du die App nutzt)
"%PY%" -m streamlit run app.py
pause
