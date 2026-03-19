@echo off
REM ═══════════════════════════════════════════════════════════════
REM  NCL Relay Server — Windows Launcher
REM  Starts the inter-pillar relay server on port 8787.
REM ═══════════════════════════════════════════════════════════════

cd /d "%~dp0\..\.."
python -m ncl_agency_runtime.runtime.relay_server %*
