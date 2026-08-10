@echo off
REM Single-instance guard (Bug #3 fix): check if widget is already running
REM Uses window title "AI Token Widget" set in taskbar_widget.py CreateWindowExW
tasklist /FI "WINDOWTITLE eq AI Token Widget" | find "pythonw" >nul
if %errorlevel%==0 (
    echo [!] AI Token Widget is already running. Exiting.
    exit /b
)
start "" pythonw "%~dp0taskbar_widget.py"
