@echo off
REM Electric Ice - Patent Clearing Runner (Windows)
REM Usage: run_clearing.bat [technology] [company]

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM Default parameters
set TECHNOLOGY=%1
if "%TECHNOLOGY%"=="" set TECHNOLOGY=electric vehicle battery management

set COMPANY=%2
if "%COMPANY%"=="" set COMPANY=Resonance Energy

echo 🧊 Electric Ice - Patent Clearing System
echo ========================================
echo Technology: %TECHNOLOGY%
echo Company: %COMPANY%
echo Started: %DATE% %TIME%
echo.

REM Check if virtual environment exists
if not exist "venv" (
    echo Setting up virtual environment...
    python -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install/update requirements
pip install -r requirements.txt

REM Run patent clearing analysis
echo Running patent clearing analysis...
python patent_clearing_system.py

echo.
echo ✅ Analysis complete!
echo Check the generated JSON file for results.

pause