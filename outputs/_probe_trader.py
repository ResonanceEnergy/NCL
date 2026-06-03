import json
from collections import Counter

ti = '/Users/natrix/dev/NCL/data/portfolio/trade_ideas.jsonl'
ideas = []
with open(ti) as fp:
    for line in fp:
        if line.strip():
            try: ideas.append(json.loads(line))
            except: pass

def daystr(i):
    for k in ('emitted_at','created_at','ts','date','timestamp'):
        v = i.get(k) or (i.get('idea') or {}).get(k)
        if v: return str(v)[:10]
    return ''

today = [i for i in ideas if daystr(i)=='2026-06-03']
print(f'trade_ideas.jsonl total={len(ideas)} today={len(today)}')

asset = Counter(); dirs = Counter(); rights = Counter(); strats = Counter()
for i in today:
    sub = i.get('idea') if isinstance(i.get('idea'), dict) else i
    asset[sub.get('asset_type') or '?'] += 1
    dirs[sub.get('direction') or '?'] += 1
    rights[str(sub.get('option_right') or '-')] += 1
    strats[sub.get('strategy') or '?'] += 1
print(f'  asset_type: {dict(asset)}')
print(f'  direction:  {dict(dirs)}')
print(f'  option_right: {dict(rights)}')
print(f'  strategy:   {dict(strats)}')

print('---last 8 today---')
for i in today[-8:]:
    sub = i.get('idea') if isinstance(i.get('idea'), dict) else i
    fmt = '  {0:<6} {1:<8} {2:<5} right={3:<4} strat={4:<14} stop_type={5} src={6}'
    print(fmt.format(
        str(sub.get('ticker') or '?'),
        str(sub.get('asset_type') or '?'),
        str(sub.get('direction') or '?'),
        str(sub.get('option_right') or '-'),
        str(sub.get('strategy') or '?'),
        str(sub.get('stop_type') or '?'),
        str(sub.get('source') or '?'),
    ))

# any puts today across all sources?
puts_today = [i for i in today if (i.get('idea') or i).get('option_right') in ('put','PUT')]
print(f'PUT ideas today: {len(puts_today)}')
for p in puts_today:
    sub = p.get('idea') if isinstance(p.get('idea'), dict) else p
    print(f"  PUT {sub.get('ticker')} {sub.get('option_strike')} dte={sub.get('option_dte')} src={sub.get('source')}")
