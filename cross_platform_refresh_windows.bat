@echo off
REM Super Agency Cross-Platform Refresh - Windows Task Scheduler Script
REM Runs every 5 minutes to sync with Quantum Quasar

echo [%DATE% %TIME%] Starting Cross-Platform Refresh on QUANTUM FORGE >> "%~dp0logs\refresh_scheduler.log"

REM Change to the shared directory
cd /d "%~dp0"

REM Run the Python refresh script
python "%~dp0cross_platform_refresh.py"

if %errorlevel% equ 0 (
    echo [%DATE% %TIME%] Refresh completed successfully >> "%~dp0logs\refresh_scheduler.log"
) else (
    echo [%DATE% %TIME%] Refresh failed with exit code: %errorlevel% >> "%~dp0logs\refresh_scheduler.log"
)

echo [%DATE% %TIME%] Cross-Platform Refresh cycle complete >> "%~dp0logs\refresh_scheduler.log"
echo. >> "%~dp0logs\refresh_scheduler.log"</content>
<parameter name="filePath">/Users/gripandripphdd/Library/CloudStorage/OneDrive-GripandRipp(2)/SuperAgency-Shared/cross_platform_refresh_windows.bat