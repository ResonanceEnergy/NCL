import json
d = json.load(open("/tmp/_brief_fire_out.json"))
a = d.get("archive") or {}
print("brief_id:", a.get("brief_id"))
print("md_path:", a.get("md_path"))
print("memory_unit_id:", a.get("memory_unit_id"))
print("ideas_registered:", a.get("ideas_registered"))
print("elapsed_s:", a.get("elapsed_s"))
print()
lanes = d.get("lanes") or {}
ti = (lanes.get("portfolio") or {}).get("trade_ideas") or []
print(f"trade_ideas count: {len(ti)}")
for i, x in enumerate(ti):
    print(f"  {i+1}. type={x.get('type'):8s} ticker={(x.get('ticker') or '?'):6s} sources={x.get('sources')}")
print()
print("== brief_council.py citation literal check ==")
# Walk the whole envelope and count any literal "sig_id" placeholders left
import json as _json
text = _json.dumps(d)
n_sig_id = text.count('"sig_id"')
n_real_hex = text.count('"sig_001"') + text.count('"sig_042"')
print(f'literal "sig_id" occurrences in envelope: {n_sig_id}')
print(f'literal placeholder examples (sig_001/sig_042): {n_real_hex}')
