@echo off
if exist "%~dp0dist\Q-Tracker\Q-Tracker.exe" start "" "%~dp0dist\Q-Tracker\Q-Tracker.exe" %*
if exist "%~dp0dist\Q-Tracker\Q-Tracker.exe" exit /b 0
if exist "%~dp0.venv\Scripts\pythonw.exe" start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py" %*
if exist "%~dp0.venv\Scripts\pythonw.exe" exit /b 0
echo Q-Tracker is not set up. Run setup.ps1 first.
exit /b 1
