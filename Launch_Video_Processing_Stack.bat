@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch_Video_Processing_Stack.ps1"
if errorlevel 1 pause
