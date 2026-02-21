#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT/'portfolio.json'
portfolio = json.loads(PORT.read_text(encoding='utf-8')) if PORT.exists() else {'repositories':[]}
now = datetime.now(timezone.utc)
CORE_L = {'ResonanceEnergy_SuperAgency','NCC','NCL','AZ'}
for r in portfolio.get('repositories', []):
    updated = r.get('updatedAt')
    try:
        dt = datetime.fromisoformat(updated.replace('Z','+00:00')) if updated else None
    except Exception:
        dt = None
    days = (now - dt).days if dt else 999
    activity = max(0, 100 - min(100, days))
    tier = r.get('tier','TBD'); risk = (r.get('risk_tier') or 'TBD').upper()
    if r['name'] in CORE_L:
        tier = 'L'
    else:
        tier = 'L' if activity>=60 else ('M' if activity>=20 else 'S')
        if risk=='HIGH' and tier=='L': tier='M'
    r['tier'] = tier
PORT.write_text(json.dumps(portfolio, indent=2), encoding='utf-8')
print('[OK] Auto-tiering complete.')
