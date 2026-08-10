@echo off
if exist "%~dp0dist\AIUsageTracker\AIUsageTracker.exe" start "" "%~dp0dist\AIUsageTracker\AIUsageTracker.exe" %*
if exist "%~dp0dist\AIUsageTracker\AIUsageTracker.exe" exit /b 0
if exist "%~dp0.venv\Scripts\pythonw.exe" start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py" %*
if exist "%~dp0.venv\Scripts\pythonw.exe" exit /b 0
echo AIUsageTracker is not set up. Run setup.ps1 first.
exit /b 1
