#!/usr/bin/env python3
import json, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT/'config'/'settings.json').read_text(encoding='utf-8'))
PORT = ROOT/'portfolio.json'
portfolio = json.loads(PORT.read_text(encoding='utf-8')) if PORT.exists() else {'repositories':[]}
repos_base = Path(CONFIG.get('repos_base','./repos')).resolve()
T = ROOT/'templates'/'ncl'
created=[]; missing=[]
for r in portfolio.get('repositories', []):
    rr = repos_base / r['name']; ncl = rr/'.ncl'
    if not rr.exists():
        missing.append((r['name'],'not_cloned'))
        continue
    for p in [ncl, rr/'playbooks', rr/'adr', rr/'tests']:
        p.mkdir(parents=True, exist_ok=True)
    files = {
        ncl/'mandate.yaml': T/'mandate.template.yaml',
        ncl/'agents.json': T/'agents.template.json',
        ncl/'events.schema.json': T/'events.schema.json',
        ncl/'policies.md': T/'policies.md',
        rr/'playbooks'/'Incident.md': None,
        rr/'adr'/'ADR-000-template.md': None,
    }
    for dst, src in files.items():
        if not dst.exists():
            if src and src.exists(): shutil.copyfile(src, dst)
            else: dst.write_text('# TODO: fill', encoding='utf-8')
            created.append(str(dst))
print(f'[OK] Self-heal complete. Created/ensured {len(created)} files. Missing clones: {len([m for m in missing if m[1]=="not_cloned"]) }')
