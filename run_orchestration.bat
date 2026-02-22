@echo off
cd /d "C:\Users\gripa\OneDrive - Grip and Ripp\SuperAgency-Shared"
python -c "import asyncio; from conductor_agent import ConductorAgent; asyncio.run(ConductorAgent().orchestrate_cycle())"
