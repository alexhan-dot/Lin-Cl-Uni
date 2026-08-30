@echo off
REM Double-click launcher for Kangaroo Studio on Windows.
cd /d "%~dp0.."
python app\kangaroo_studio.py
if errorlevel 1 pause
