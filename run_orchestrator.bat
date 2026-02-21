@echo off
cd /d "c:\Users\gripa\OneDrive - Grip and Ripp\Super Agency\Super-Agency"
echo Starting GitHub Orchestrator...
c:\Python314\python.exe github_orchestrator.py
echo.
echo Orchestrator completed. Check logs/github_orchestrator_* for results.
pause