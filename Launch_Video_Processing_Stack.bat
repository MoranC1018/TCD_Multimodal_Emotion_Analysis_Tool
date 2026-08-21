@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

call :try_python "%~dp0.venv\Scripts\python.exe"
if defined launcher_attempted exit /b !launcher_status!

call :try_python "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if defined launcher_attempted exit /b !launcher_status!

call :try_python "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined launcher_attempted exit /b !launcher_status!

where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys, webview; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "launcher_attempted=1"
        py -3 -m application.launcher
        set "launcher_status=!errorlevel!"
        if not "!launcher_status!"=="0" pause
        exit /b !launcher_status!
    )
)

where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys, webview; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "launcher_attempted=1"
        python -m application.launcher
        set "launcher_status=!errorlevel!"
        if not "!launcher_status!"=="0" pause
        exit /b !launcher_status!
    )
)

echo A Python 3.12+ environment with pywebview was not found. Install requirements.txt, then run this launcher again.
pause
exit /b 1

:try_python
if not exist "%~1" exit /b 0
"%~1" -c "import sys, webview; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "launcher_attempted=1"
"%~1" -m application.launcher
set "launcher_status=!errorlevel!"
if not "!launcher_status!"=="0" pause
exit /b 0
