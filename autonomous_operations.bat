@echo off
REM Super Agency Autonomous Operations
REM Automated GitHub integration and portfolio management

echo 🤖 Super Agency Autonomous Operations
echo =====================================

set ROOT_DIR=%~dp0
set GITHUB_ORCHESTRATOR=%ROOT_DIR%github_orchestrator.py

echo 📍 Root directory: %ROOT_DIR%
echo 🎯 Running GitHub orchestrator...

REM Run the GitHub orchestrator
python "%GITHUB_ORCHESTRATOR%"

if %errorlevel% equ 0 (
    echo ✅ Autonomous operations completed successfully!
) else (
    echo ❌ Autonomous operations failed with exit code: %errorlevel%
)

echo.
echo 📊 Check logs in the 'logs' directory for detailed results
echo 🔄 Next run: Scheduled for daily execution
pause