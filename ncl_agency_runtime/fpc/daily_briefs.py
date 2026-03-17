"""Specialized Daily Briefs — AZ Prime & C-Suite.

Three brief tiers built on the same data pipeline:

1. **HELIX Daily Brief** (public/team) — Audio/video clips, top 10 ranked topics
2. **AZ Daily Brief** (AZ_PRIME only) — System health + governance + strategic intel
3. **C-Suite Daily Brief** (executives) — ROI focus, risk-adjusted, 5 strategic headlines

All briefs consume data from:
- SignalScorer ranked predictions (FPC council output)
- Event log NDJSON (iPhone capture stream)
- System health checks (relay, daemon, prediction store)

Output format:
- Markdown (.md) and PDF (.pdf) written to date-sorted folders under
  ``reports/daily_briefs/<brief_type>/YYYYMMDD_HHMMSS/``

Usage::

    from ncl_agency_runtime.fpc.daily_briefs import AZBrief, CSuiteBrief

    # Generate + save to disk (markdown + PDF)
    az = AZBrief()
    paths = az.save()          # returns {"md": Path, "pdf": Path, "dir": Path}

    # Or just get the markdown string
    print(az.generate())
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPORTS_ROOT = Path("reports/daily_briefs")

# ── Shared helpers ───────────────────────────────────────────────────────────


def _save_brief(brief_type: str, markdown: str, timestamp: datetime) -> dict[str, Path]:
    """Write markdown + PDF to a date-sorted folder.

    Returns dict with keys ``md``, ``pdf``, ``dir``.
    """
    ts_label = timestamp.strftime("%Y%m%d_%H%M%S")
    out_dir = _REPORTS_ROOT / brief_type / ts_label
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / f"{brief_type}_{ts_label}.md"
    md_path.write_text(markdown, encoding="utf-8")

    pdf_path = out_dir / f"{brief_type}_{ts_label}.pdf"
    _render_pdf(markdown, pdf_path)

    return {"md": md_path, "pdf": pdf_path, "dir": out_dir}


def _render_pdf(markdown: str, out_path: Path) -> None:
    """Convert markdown text to a basic PDF via fpdf2."""
    try:
        from fpdf import FPDF  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("fpdf2 not installed — skipping PDF generation")
        return

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Strip emoji that the default font can't render
    _emoji_re = re.compile(
        "[\U0001f300-\U0001f9ff\U00002702-\U000027b0\U0000fe00-\U0000fe0f"
        "\U0000200d\U00002600-\U000026ff\U00002b50\U00002b55]+",
        flags=re.UNICODE,
    )

    # Map common Unicode to latin-1 safe equivalents
    _UNICODE_SUBS = {
        "\u2014": "--",   # em dash
        "\u2013": "-",    # en dash
        "\u2018": "'",    # left single quote
        "\u2019": "'",    # right single quote
        "\u201c": '"',    # left double quote
        "\u201d": '"',    # right double quote
        "\u2026": "...",  # ellipsis
        "\u2022": "*",    # bullet
        "\u00a0": " ",    # non-breaking space
    }

    def _sanitize(text: str) -> str:
        out = _emoji_re.sub("", text)
        for ch, repl in _UNICODE_SUBS.items():
            out = out.replace(ch, repl)
        # Drop any remaining non-latin-1 characters
        return out.encode("latin-1", errors="replace").decode("latin-1")

    for raw_line in markdown.split("\n"):
        line = _sanitize(raw_line).strip()

        # Headings
        if line.startswith("### "):
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(0, 6, line[4:])
            pdf.ln(2)
        elif line.startswith("## "):
            pdf.set_font("Helvetica", "B", 13)
            pdf.multi_cell(0, 7, line[3:])
            pdf.ln(3)
        elif line.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 8, line[2:])
            pdf.ln(4)

        # Horizontal rule
        elif line.startswith("---"):
            y = pdf.get_y()
            pdf.line(10, y, 200, y)
            pdf.ln(4)

        # Table rows (pipe-delimited)
        elif line.startswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if cells and all(set(c) <= {"-", " "} for c in cells):
                continue  # skip separator row
            pdf.set_font("Helvetica", "", 8)
            col_w = (pdf.w - 20) / max(len(cells), 1)
            for cell_text in cells:
                clean = cell_text.replace("**", "")
                pdf.cell(col_w, 5, clean[:30], border=1)
            pdf.ln()

        # Blockquote
        elif line.startswith(">"):
            pdf.set_font("Helvetica", "I", 9)
            pdf.multi_cell(0, 5, line.lstrip("> "))
            pdf.ln(1)

        # Bullet
        elif line.startswith("- ") or line.startswith("  - "):
            indent = 5 if line.startswith("  -") else 0
            pdf.set_font("Helvetica", "", 10)
            pdf.set_x(10 + indent)
            clean = line.lstrip(" -").replace("**", "")
            pdf.multi_cell(0, 5, f"  {clean}")
            pdf.ln(1)

        # Italic line (classification, footer)
        elif line.startswith("*") and line.endswith("*"):
            pdf.set_font("Helvetica", "I", 9)
            pdf.multi_cell(0, 5, line.strip("*"))
            pdf.ln(2)

        # Normal text
        elif line:
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, line.replace("**", ""))
            pdf.ln(1)

    pdf.output(str(out_path))


def _load_event_counts(date_str: str) -> dict[str, int]:
    """Load event type counts from NDJSON log for a given date."""
    event_log = Path("data/event_log") / f"{date_str}.ndjson"
    counts: dict[str, int] = {}
    if not event_log.exists():
        return counts
    with event_log.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                et = ev.get("event_type", "unknown")
                counts[et] = counts.get(et, 0) + 1
            except Exception as exc:
                logger.debug("Skipping malformed event log line: %s", exc)
                continue
    return counts


def _system_health() -> dict[str, Any]:
    """Quick system health snapshot."""
    health: dict[str, Any] = {
        "relay_server": "unknown",
        "prediction_store": "unknown",
        "event_log": "unknown",
        "fpc_db": "unknown",
    }

    # Check prediction store
    try:
        from .persistence import PredictionStore
        store = PredictionStore()
        preds = store.list_all()
        health["prediction_store"] = f"ok ({len(preds)} predictions)"
        health["fpc_db"] = "ok"
    except Exception as e:
        health["prediction_store"] = f"error: {e}"
        health["fpc_db"] = f"error: {e}"

    # Check event log directory
    event_dir = Path("data/event_log")
    if event_dir.exists():
        ndjson_files = list(event_dir.glob("*.ndjson"))
        health["event_log"] = f"ok ({len(ndjson_files)} days)"
    else:
        health["event_log"] = "no event_log directory"

    return health


def _ranked_predictions() -> list[dict[str, Any]]:
    """Load and rank predictions via SignalScorer, deduplicating by topic."""
    try:
        from .signal_scorer import SignalScorer
        scorer = SignalScorer()
        ranked = scorer.rank_predictions()
    except Exception as e:
        logger.warning("SignalScorer unavailable: %s", e)
        return []

    seen: set = set()
    unique: list[dict] = []
    for pred in ranked:
        topic = pred.get("topic", "")
        if topic not in seen:
            seen.add(topic)
            unique.append(pred)
    return unique


# ── AZ Daily Brief ───────────────────────────────────────────────────────────


class AZBrief:
    """AZ_PRIME daily intelligence brief — system health + governance + strategic intel.

    Coverage:
    - System health (relay, DB, event pipeline)
    - Top ranked predictions with grades
    - Domain health across all sectors
    - Governance compliance status
    - Action items prioritized by impact score
    """

    def __init__(self) -> None:
        self.now = datetime.now()
        self.date_str = self.now.strftime("%Y-%m-%d")
        self.display_date = self.now.strftime("%A, %B %d, %Y")

    def generate(self) -> str:
        """Generate the full AZ daily brief as markdown."""
        lines: list[str] = []

        lines.append(f"# AZ PRIME Daily Brief — {self.display_date}")
        lines.append("")
        lines.append("*Classification: AZ_PRIME EYES ONLY*")
        lines.append("")

        # Section 1: System Health
        health = _system_health()
        lines.append("## 1. System Health")
        for component, status in health.items():
            icon = "✅" if "ok" in str(status) else "⚠️"
            lines.append(f"- {icon} **{component}**: {status}")
        lines.append("")

        # Section 2: Intelligence Ranking
        predictions = _ranked_predictions()
        lines.append("## 2. Intelligence Ranking")
        if predictions:
            lines.append("")
            lines.append("| # | Grade | Score | Domain | Topic |")
            lines.append("|---|-------|-------|--------|-------|")
            for i, p in enumerate(predictions[:10], 1):
                grade = p.get("grade", "?")
                score = p.get("impact_score", 0)
                domain = p.get("domain", "?")
                topic = p.get("topic", "?")[:60]
                lines.append(f"| {i} | **{grade}** | {score:.3f} | {domain} | {topic} |")
        else:
            lines.append("- No predictions available. Run FPC council session.")
        lines.append("")

        # Section 3: Domain Coverage
        lines.append("## 3. Domain Coverage")
        try:
            from .signal_scorer import SignalScorer
            scorer = SignalScorer()
            domain_health = scorer.domain_health()
            if domain_health:
                for domain, stats in sorted(domain_health.items()):
                    total = stats.get("total", 0)
                    avg_conf = stats.get("avg_confidence", 0)
                    lines.append(f"- **{domain}**: {total} predictions, avg confidence {avg_conf:.0%}")
            else:
                lines.append("- No domain data available.")
        except Exception:
            lines.append("- Domain health check unavailable.")
        lines.append("")

        # Section 4: Event Pipeline
        event_counts = _load_event_counts(self.date_str)
        lines.append("## 4. Event Pipeline")
        if event_counts:
            total_events = sum(event_counts.values())
            lines.append(f"- Total events today: **{total_events}**")
            top = sorted(event_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            for et, count in top:
                lines.append(f"  - {et}: {count}")
        else:
            lines.append("- No events captured today.")
        lines.append("")

        # Section 5: Action Items
        lines.append("## 5. Priority Actions")
        if predictions:
            s_a_items = [p for p in predictions if p.get("grade") in ("S", "A")]
            if s_a_items:
                for p in s_a_items[:3]:
                    topic = p.get("topic", "?")
                    grade = p.get("grade", "?")
                    lines.append(f"- [{grade}] **Act now**: {topic}")
            else:
                lines.append("- No S/A grade signals. Monitor B-grade items daily.")
        else:
            lines.append("- No predictions to act on.")
        lines.append("")

        lines.append("---")
        lines.append(f"*Generated {self.now.strftime('%H:%M:%S')} by NCL AZ Brief Engine*")

        return "\n".join(lines)

    def save(self) -> dict[str, Path]:
        """Generate and save the AZ brief as markdown + PDF."""
        md = self.generate()
        return _save_brief("az", md, self.now)


# ── C-Suite Daily Brief ──────────────────────────────────────────────────────


class CSuiteBrief:
    """Executive daily brief — strategic headlines, ROI focus, risk-adjusted.

    Coverage:
    - 5 strategic headlines (highest impact score)
    - Risk assessment summary
    - Opportunity spotlight
    - Market sentiment snapshot
    - Board-ready language (no technical jargon)
    """

    def __init__(self) -> None:
        self.now = datetime.now()
        self.date_str = self.now.strftime("%Y-%m-%d")
        self.display_date = self.now.strftime("%A, %B %d, %Y")

    def generate(self) -> str:
        """Generate the C-Suite executive brief as markdown."""
        lines: list[str] = []

        lines.append(f"# Executive Intelligence Brief — {self.display_date}")
        lines.append("")

        predictions = _ranked_predictions()

        # Section 1: Strategic Headlines
        lines.append("## Strategic Headlines")
        if predictions:
            for i, p in enumerate(predictions[:5], 1):
                topic = p.get("topic", "Unknown")
                grade = p.get("grade", "?")
                conf = p.get("confidence", 0)
                outcome = p.get("predicted_outcome", "")
                # Clean enum artifacts
                outcome = str(outcome).split(".")[-1] if "." in str(outcome) else str(outcome)
                if len(outcome) > 120:
                    outcome = outcome[:120] + "..."
                lines.append(f"### {i}. {topic}")
                lines.append(f"Signal strength: **{grade}** | Confidence: {conf:.0%}")
                if outcome:
                    lines.append(f"  > {outcome}")
                lines.append("")
        else:
            lines.append("No strategic signals detected. Next council session pending.")
            lines.append("")

        # Section 2: Risk Dashboard
        lines.append("## Risk Dashboard")
        if predictions:
            risk_counts: dict[str, int] = {}
            for p in predictions:
                risk = str(p.get("risk_level", "unknown")).split(".")[-1].lower()
                risk_counts[risk] = risk_counts.get(risk, 0) + 1
            for risk_level in ["critical", "high", "medium", "low"]:
                count = risk_counts.get(risk_level, 0)
                if count:
                    icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(risk_level, "⚪")
                    lines.append(f"- {icon} **{risk_level.title()}**: {count} signal(s)")
            if not risk_counts:
                lines.append("- No risk signals active.")
        else:
            lines.append("- Risk data unavailable.")
        lines.append("")

        # Section 3: Opportunity Spotlight
        lines.append("## Opportunity Spotlight")
        opportunity_domains = {"01_crypto_defi", "02_financial_markets", "06_technology"}
        opportunities = [p for p in predictions if p.get("domain") in opportunity_domains]
        if opportunities:
            best = opportunities[0]
            lines.append(f"**Top opportunity**: {best.get('topic', '?')}")
            lines.append(f"  - Grade: {best.get('grade', '?')}, Score: {best.get('impact_score', 0):.3f}")
            rec = str(best.get("recommendation", "Monitor")).split(".")[-1].lower()
            lines.append(f"  - Recommendation: {rec}")
        else:
            lines.append("No high-confidence opportunities identified today.")
        lines.append("")

        # Section 4: Bottom Line
        lines.append("## Bottom Line")
        if predictions:
            top_grades = [p.get("grade", "D") for p in predictions[:5]]
            if "S" in top_grades:
                lines.append("**Action required.** S-grade signals detected — immediate review recommended.")
            elif "A" in top_grades:
                lines.append("**High priority items.** A-grade signals warrant attention within hours.")
            elif "B" in top_grades:
                lines.append("**Steady state.** Monitor B-grade items. No immediate action needed.")
            else:
                lines.append("**Low activity.** No significant signals. Standard operations.")
        else:
            lines.append("Intelligence pipeline idle. Awaiting next data cycle.")
        lines.append("")

        lines.append("---")
        lines.append(f"*Prepared {self.now.strftime('%H:%M')} | Resonance Energy Intelligence*")

        return "\n".join(lines)

    def save(self) -> dict[str, Path]:
        """Generate and save the C-Suite brief as markdown + PDF."""
        md = self.generate()
        return _save_brief("csuite", md, self.now)
