"""NCL GBX Doctrine Builder

Usage:
  python build.py

Generates:
  - dist/ncl_dox_gbx_001.md
  - dist/insights_150.json
  - dist/insights_150.csv
"""

import csv
import json
from pathlib import Path

HERE = Path(__file__).parent
DIST = HERE / "dist"
DIST.mkdir(exist_ok=True)

# Load embedded data
with open(HERE / "src" / "insights_150.json", encoding="utf-8") as f:
    insights = json.load(f)

# Build markdown
md_lines = [
    "# NCL Doctrine — iPhone Glass Brick Exploitation (GBX)",
    "",
    "**Doctrine ID:** NCL-DOX-GBX-001",
    "**Revision:** 1.0",
    "",
    "## Purpose",
    "Use the iPhone as NCL’s primary **UI + router + sensor hub**, capturing **high-signal, low-invasion** data streams via **consent, metadata-first collection, and event extraction**, enabling a local-first path toward symbiosis.",  # noqa: RUF001
    "",
    "## Non‑Negotiables",  # noqa: RUF001
    "- Local-first default; cloud optional.",
    "- Metadata-first; avoid content capture.",
    "- Event extraction > raw streams.",
    "- No keylogging/screen recording by default.",
    "- If audio is used: label-only sensing and speech-filtering posture.",
    "- Consent registry + kill switch + retention tiers.",
    "",
    "## The 150 Insights",
    "",
]
for item in insights:
    md_lines.append(f"{item['id']}. **({item['tag']}) {item['title']}** — {item['description']}")

(DIST / "ncl_dox_gbx_001.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

# Copy JSON
(DIST / "insights_150.json").write_text(json.dumps(insights, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

# Write CSV
with open(DIST / "insights_150.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["id", "tag", "title", "description"])
    w.writeheader()
    for row in insights:
        w.writerow(row)

print("Built doctrine + datasets into ./dist")
