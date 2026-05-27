#!/usr/bin/env python3
import collections
import json
import re


d = json.load(open("/tmp/brief.json"))
print("=== TOP-LEVEL KEYS ===")
for k in d.keys():
    v = d[k]
    if isinstance(v, str):
        print(f"  {k}: str len={len(v)}")
    elif isinstance(v, list):
        print(f"  {k}: list len={len(v)}")
    else:
        print(f"  {k}: {type(v).__name__} = {v!r}")

print()
print("=== TIMESTAMP-LIKE FIELDS ===")
for k in d.keys():
    if any(x in k.lower() for x in ("time", "date", "at", "gen")):
        print(f"  {k}: {d[k]!r}")

print()
print("=== TICKER FREQUENCY IN full_brief ===")
fb = d.get("full_brief", "")
tickers = re.findall(r"\$?([A-Z]{1,5})\b", fb)
exclude = {
    "NATRIX",
    "THE",
    "NCL",
    "EXECUTIVE",
    "SUMMARY",
    "BRIEF",
    "RISK",
    "ALERT",
    "MACRO",
    "LANE",
    "KEY",
    "SIGNALS",
    "TRADE",
    "IDEAS",
    "HEADLINE",
    "OPS",
    "EOD",
    "CSV",
    "DERP",
    "MAC",
    "ATR",
    "RSI",
    "MACD",
    "OHLC",
    "API",
    "URL",
    "JSON",
    "II",
    "III",
    "IV",
    "V",
    "I",
    "A",
    "AS",
    "AT",
    "IS",
    "IT",
    "TO",
    "OF",
    "OR",
    "IN",
    "ON",
    "BE",
    "BY",
    "NO",
    "PM",
    "AM",
    "ET",
    "PT",
    "CDT",
    "EST",
    "PST",
    "GMT",
    "UTC",
    "MIT",
    "NEW",
    "EXEC",
    "PMC",
    "PCR",
    "IV",
    "OI",
    "EPS",
    "PE",
    "PB",
    "DCA",
    "NFP",
    "GDP",
    "CPI",
    "PPI",
    "ETF",
    "ETFS",
    "FED",
    "FOMC",
}
ctr = collections.Counter(t for t in tickers if t not in exclude and len(t) >= 2)
print("Top 25 tickers in brief:")
for t, c in ctr.most_common(25):
    print(f"  {t}: {c}")

# Classify as index/ETF vs stock
index_etfs = {
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "VTI",
    "VOO",
    "VXX",
    "TLT",
    "IEF",
    "XLF",
    "XLK",
    "XLE",
    "XLV",
    "XLI",
    "XLP",
    "XLY",
    "XLB",
    "XLU",
    "XLRE",
    "XLC",
    "GLD",
    "SLV",
    "USO",
    "UNG",
}
print()
print("=== INDEX/ETF vs STOCK BIAS ===")
idx_cnt = sum(c for t, c in ctr.items() if t in index_etfs)
stk_cnt = sum(c for t, c in ctr.items() if t not in index_etfs)
print(f"  index/ETF references: {idx_cnt}")
print(f"  individual stock references: {stk_cnt}")
print(f"  ratio idx:stk = {idx_cnt}:{stk_cnt}")

print()
print("=== TRADE IDEAS (first 1200 chars) ===")
m = re.search(r"TRADE IDEAS?.*?(?=\n[A-Z ]{4,}\n|$)", fb, re.DOTALL)
if m:
    print(m.group(0)[:1200])
