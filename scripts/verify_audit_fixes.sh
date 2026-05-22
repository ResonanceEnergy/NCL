#!/bin/bash
# Quick verification of the 2026-05-22 audit fixes.
# Used during dev; safe to keep around.
TOK=QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU
PY=/opt/homebrew/bin/python3

echo '=== TEST 1: /portfolio/positions ==='
curl -s -m 10 -H "Authorization: Bearer $TOK" 'http://127.0.0.1:8800/portfolio/positions' > /tmp/pos.json
$PY <<'PYEOF'
import json
d=json.load(open('/tmp/pos.json'))
ps=d.get('positions',[])
print(f"total_positions={d.get('total_positions')}")
for p in ps[:3]:
    print(f"  {p['symbol']:18}: last_price={p.get('last_price')}  quote_ok={p.get('quote_ok')}  daily_pl_pct={p.get('daily_pl_pct')}")
PYEOF

echo
echo '=== TEST 2: /portfolio/accounts ==='
curl -s -m 10 -H "Authorization: Bearer $TOK" 'http://127.0.0.1:8800/portfolio/accounts' > /tmp/acc.json
$PY <<'PYEOF'
import json
d=json.load(open('/tmp/acc.json'))
for a in d.get('accounts',[]):
    print(f"  {a['broker']:13} {a['label']:18} positions_count={a.get('positions_count')}")
PYEOF

echo
echo '=== TEST 3: /portfolio/options-flow ==='
curl -s -m 10 -H "Authorization: Bearer $TOK" 'http://127.0.0.1:8800/portfolio/options-flow?limit=5&min_premium=100000&hours=24' > /tmp/opt.json
$PY <<'PYEOF'
import json
d=json.load(open('/tmp/opt.json'))
meta=d.get('_meta',{})
print(f"meta: raw={meta.get('raw_count')} filtered={meta.get('filtered_count')} tickers={meta.get('ticker_count')} portfolio_matches={meta.get('portfolio_match_count')}")
for r in d.get('rows',[])[:5]:
    print(f"  {r['ticker']:6} prem=${r['total_premium_usd']:>12,.0f}  trades={r['trade_count']:>3}  C/P={r['call_put_ratio']:.2f}  held={r['is_held_in_portfolio']}")
PYEOF

echo
echo '=== TEST 4: /predictions ==='
curl -s -m 10 -H "Authorization: Bearer $TOK" 'http://127.0.0.1:8800/predictions?limit=2' > /tmp/pred.json
$PY <<'PYEOF'
import json
d=json.load(open('/tmp/pred.json'))
for p in d.get('predictions',[])[:2]:
    print(f"  topic={p.get('topic'):20} direction={p.get('direction')} models={p.get('models')} linked_signals={len(p.get('linked_signals',[]))}")
print('_meta:', d.get('_meta'))
PYEOF

echo
echo '=== TEST 5: /youtube/reports/recent ==='
curl -s -m 10 -H "Authorization: Bearer $TOK" 'http://127.0.0.1:8800/youtube/reports/recent?limit=10' > /tmp/yt.json
$PY <<'PYEOF'
import json
d=json.load(open('/tmp/yt.json'))
seen={}
for r in d.get('reports',[]):
    vid=r.get('video_id') or '(no-vid)'
    seen[vid]=seen.get(vid,0)+1
    print(f"  vid={vid:14} type={r.get('report_type'):10} insights={r.get('insights_count'):>3} fn={r.get('filename','')[:60]}")
dup=[v for v,c in seen.items() if c>1 and v!='(no-vid)']
print(f"duplicate_video_ids={dup}")
print('_meta:', d.get('_meta'))
PYEOF
