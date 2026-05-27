#!/usr/bin/env python3
"""Full QA dump of /tmp/brief.json — structure + content + claims."""

import collections
import json
import re


d = json.load(open("/tmp/brief.json"))

print("=" * 78)
print("STRUCTURAL OVERVIEW")
print("=" * 78)
print(f"date: {d.get('date')}")
print(f"generated_at: {d.get('generated_at')}")
print(f"brief_id: {d.get('brief_id')}")
print(f"total_signals: {d.get('total_signals')}")
print(f"pipeline_meta: {d.get('pipeline_meta')}")
print(f"executive_summary length: {len(d.get('executive_summary', ''))}")
print(f"full_brief length: {len(d.get('full_brief', ''))}")
print(f"risk_alerts count: {len(d.get('risk_alerts', []))}")

print()
print("=" * 78)
print("EXECUTIVE SUMMARY")
print("=" * 78)
print(d.get("executive_summary", ""))

print()
print("=" * 78)
print("FULL BRIEF")
print("=" * 78)
print(d.get("full_brief", ""))

print()
print("=" * 78)
print("QUALITY METRICS")
print("=" * 78)
fb = d.get("full_brief", "")
es = d.get("executive_summary", "")

md_in_es = sum(1 for ch in ("**", "##", "__") if ch in es)
md_in_fb = sum(1 for ch in ("**", "##", "__") if ch in fb)
print(f"markdown leaks in exec_summary: {md_in_es}")
print(f"markdown leaks in full_brief:   {md_in_fb}")

stub_re = re.compile(r"signals quiet|no signals|insufficient data|stub", re.IGNORECASE)
print(f"stub phrases in full_brief:    {len(stub_re.findall(fb))}")

# Ticker analysis
ticker_re = re.compile(r"\$?\b([A-Z]{2,5})\b")
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
    "PMC",
    "PCR",
    "OI",
    "EPS",
    "PE",
    "DCA",
    "NFP",
    "GDP",
    "CPI",
    "PPI",
    "ETF",
    "ETFS",
    "FED",
    "FOMC",
    "TICKER",
    "THESIS",
    "TARGET",
    "SOURCES",
    "ENTRY",
    "STOP",
    "TIMEFRAME",
    "STRUCTURE",
    "PLAY",
    "STOCK",
    "SETUP",
    "OPTIONS",
    "FUTURES",
    "TOPIC",
    "WHY",
    "PRE",
    "POST",
    "RVOL",
    "VWAP",
    "BLS",
    "CME",
    "MOVERS",
    "POTENTIAL",
    "DAILY",
    "TODAYS",
    "RESEARCH",
    "TOPICS",
    "EMERGING",
    "OPPORTUNITIES",
    "AND",
    "RISKS",
    "MOVEMENTS",
    "HIGH",
    "LOW",
    "TO",
    "OF",
    "OR",
    "IN",
    "ON",
    "AT",
    "BY",
    "UTC",
    "INVESTIGATE",
    "MAX",
    "MGMT",
    "DECEMBER",
    "NOVEMBER",
    "OCTOBER",
    "SEPTEMBER",
    "AUGUST",
    "JULY",
    "JUNE",
    "MAY",
    "APRIL",
    "MARCH",
    "FEBRUARY",
    "JANUARY",
}
tickers = ticker_re.findall(fb)
ctr = collections.Counter(t for t in tickers if t not in exclude and len(t) >= 2)
print()
print("Top 20 tickers (filtered):")
for t, c in ctr.most_common(20):
    print(f"  {t}: {c}")

# Citation count
sig_ids = re.findall(r"\b[0-9a-f]{6,8}\b", fb)
unique_ids = set(sig_ids)
print()
print(f"signal_id citations in full_brief: {len(sig_ids)} total, {len(unique_ids)} unique")

# Trade ideas tickers + classification
broad_etfs = {
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
    "XLC",
    "XLRE",
    "GLD",
    "SLV",
    "USO",
    "UNG",
    "ARKK",
    "SMH",
    "SOXX",
}
ti_re = re.compile(r"TICKER:\s*(\$?[A-Z.]+)")
ti_tickers = ti_re.findall(fb)
print()
print(f"Trade-idea tickers: {ti_tickers}")
etfs_in_ti = [t for t in ti_tickers if t.lstrip("$") in broad_etfs]
stocks_in_ti = [t for t in ti_tickers if t.lstrip("$") not in broad_etfs]
print(f"  ETFs: {etfs_in_ti}")
print(f"  Stocks: {stocks_in_ti}")
print(f"  Quota check (rule 7a: at most 1 ETF): {'PASS' if len(etfs_in_ti) <= 1 else 'FAIL'}")
