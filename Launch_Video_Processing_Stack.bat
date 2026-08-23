@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"

call :try_python "%~dp0.venv\Scripts\python.exe"
if defined launcher_attempted exit /b !launcher_status!

call :try_python "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined launcher_attempted exit /b !launcher_status!

call :try_python "%ProgramFiles%\Python312\python.exe"
if defined launcher_attempted exit /b !launcher_status!

where py >nul 2>nul
if not errorlevel 1 (
    for /f "tokens=1,*" %%V in ('py -0p 2^>nul') do (
        set "registered_tag=%%V"
        if not "!registered_tag:3.12=!"=="!registered_tag!" (
            call :try_listed_python "%%W"
            if defined launcher_attempted exit /b !launcher_status!
        )
    )
    for /f "tokens=1,*" %%V in ('py -0p 2^>nul') do (
        call :try_listed_python "%%W"
        if defined launcher_attempted exit /b !launcher_status!
    )
)

for /f "delims=" %%D in ('dir /b /ad "%LOCALAPPDATA%\Programs\Python\Python3*" 2^>nul') do (
    call :try_python "%LOCALAPPDATA%\Programs\Python\%%D\python.exe"
    if defined launcher_attempted exit /b !launcher_status!
)

for /f "delims=" %%D in ('dir /b /ad "%ProgramFiles%\Python3*" 2^>nul') do (
    call :try_python "%ProgramFiles%\%%D\python.exe"
    if defined launcher_attempted exit /b !launcher_status!
)

for /f "delims=" %%P in ('where python 2^>nul') do (
    call :try_python "%%P"
    if defined launcher_attempted exit /b !launcher_status!
)

echo A Python 3.11+ environment with pywebview was not found. Python 3.12 is tested and recommended. Install requirements.txt, then run this launcher again.
pause
exit /b 1

:try_python
if not exist "%~1" exit /b 0
"%~1" -c "import sys, webview; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "launcher_attempted=1"
"%~1" -m application.launcher
set "launcher_status=!errorlevel!"
if not "!launcher_status!"=="0" pause
exit /b 0

:try_listed_python
set "listed_python=%~1"
if not defined listed_python exit /b 0
if "!listed_python:~0,2!"=="* " set "listed_python=!listed_python:~2!"
if "!listed_python:~-2!"==" *" set "listed_python=!listed_python:~0,-2!"
call :try_python "!listed_python!"
exit /b 0
