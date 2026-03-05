@echo off
REM NCL Relay Server Windows Service Manager
REM Provides start/stop/status functionality for the NCL relay server

setlocal enabledelayedexpansion

REM Configuration
set RELAY_SCRIPT=%~dp0..\ZIPZ\NCL_AGENCY_Runtime_Mac_v1_LocalOnly\ncl_gbx_one_drop\runtime\relay_server.py
set LOG_FILE=%USERPROFILE%\NCL\audit\relay_server.log
set PID_FILE=%USERPROFILE%\NCL\audit\relay_server.pid
set PYTHON_EXE=python

REM Ensure audit directory exists
if not exist "%USERPROFILE%\NCL\audit" mkdir "%USERPROFILE%\NCL\audit"

REM Function to check if process is running
:check_running
if exist "%PID_FILE%" (
    set /p STORED_PID=<"%PID_FILE%"
    tasklist /FI "PID eq !STORED_PID!" 2>NUL | find /I /N "python.exe">NUL
    if !ERRORLEVEL! EQU 0 (
        echo Relay server is running (PID: !STORED_PID!)
        goto :eof
    ) else (
        echo Relay server not running (stale PID file)
        del "%PID_FILE%" 2>NUL
    )
) else (
    echo Relay server not running
)
goto :eof

REM Function to start the server
:start_server
echo Starting NCL Relay Server...
echo [%DATE% %TIME%] Starting relay server >> "%LOG_FILE%"

REM Check if already running
call :check_running
if exist "%PID_FILE%" (
    echo Relay server already running
    goto :eof
)

REM Start server in background
start /B "NCL Relay Server" %PYTHON_EXE% "%RELAY_SCRIPT%" >> "%LOG_FILE%" 2>&1

REM Wait a moment for startup
timeout /t 2 /nobreak >nul

REM Find the PID of the started process
for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq NCL Relay Server" ^| find "python.exe"') do (
    echo %%i > "%PID_FILE%"
    echo Relay server started with PID %%i
    goto :eof
)

echo Failed to determine PID - check log file
goto :eof

REM Function to stop the server
:stop_server
if not exist "%PID_FILE%" (
    echo No PID file found - server may not be running
    goto :eof
)

set /p PID=<"%PID_FILE%"
echo Stopping relay server (PID: %PID%)...

REM Try graceful shutdown first (if server supports it)
taskkill /PID %PID% /T >nul 2>&1

REM Wait for process to terminate
timeout /t 3 /nobreak >nul

REM Force kill if still running
tasklist /FI "PID eq %PID%" 2>NUL | find /I /N "python.exe">NUL
if !ERRORLEVEL! EQU 0 (
    echo Force stopping relay server...
    taskkill /PID %PID% /F /T >nul 2>&1
)

REM Clean up
del "%PID_FILE%" 2>NUL
echo [%DATE% %TIME%] Relay server stopped >> "%LOG_FILE%"
echo Relay server stopped
goto :eof

REM Main command processing
if "%1"=="start" (
    call :start_server
) else if "%1"=="stop" (
    call :stop_server
) else if "%1"=="status" (
    call :check_running
) else if "%1"=="restart" (
    call :stop_server
    timeout /t 2 /nobreak >nul
    call :start_server
) else (
    echo Usage: %0 {start^|stop^|status^|restart}
    echo.
    echo Commands:
    echo   start   - Start the NCL relay server
    echo   stop    - Stop the NCL relay server
    echo   status  - Check if relay server is running
    echo   restart - Restart the relay server
    echo.
    echo Log file: %LOG_FILE%
    echo PID file: %PID_FILE%
)

endlocal