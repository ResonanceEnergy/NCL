@echo off
REM ═══════════════════════════════════════════════════════════════
REM  NCL Autonomous Daemon — Windows Launcher
REM  Starts the self-organizing, 24/7 autonomous runtime.
REM ═══════════════════════════════════════════════════════════════
REM
REM  Usage:
REM    ncl_daemon.bat                  — Start daemon (5 min cycles)
REM    ncl_daemon.bat --single-cycle   — Run one cycle and exit
REM    ncl_daemon.bat --status         — Show daemon status
REM    ncl_daemon.bat --interval 60    — 1 min cycles (faster)
REM

cd /d "%~dp0\..\.."

echo.
echo  ================================================================
echo    NCL AUTONOMOUS DAEMON
echo    "Know the terrain, control the timing, sharpen the blade."
echo  ================================================================
echo.

python -m ncl_agency_runtime.runtime.autonomous_daemon %*
