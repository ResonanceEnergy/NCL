import json
d = json.load(open("/tmp/_brief_fire_out.json"))
a = d.get("archive") or {}
print("brief_id:", a.get("brief_id"))
print("md_path:", a.get("md_path"))
print("memory_unit_id_pending:", a.get("memory_unit_id_pending"))
print("ideas_to_register:", a.get("ideas_to_register"))
print("elapsed_s:", a.get("elapsed_s"))
print()
lanes = d.get("lanes") or {}
ti = (lanes.get("portfolio") or {}).get("trade_ideas") or []
print(f"trade_ideas count: {len(ti)}")
for i, x in enumerate(ti):
    print(f"  {i+1}. type={x.get('type'):8s} ticker={(x.get('ticker') or '?'):6s} sources={x.get('sources')}")
import json as _json
text = _json.dumps(d)
print()
print(f'literal "sig_id" in envelope: {text.count(chr(34) + "sig_id" + chr(34))}')
