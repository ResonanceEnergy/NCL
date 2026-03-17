"""Report generator — structured Markdown + JSON forecast reports."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate council session reports in JSON and Markdown."""

    def __init__(self, output_dir: str = "reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, session_data: dict[str, Any]) -> dict[str, str]:
        """Create JSON + Markdown reports from a council session result.

        Returns dict with ``json_path`` and ``md_path`` keys.
        """
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        topic_slug = session_data.get("topic", "unknown").lower().replace(" ", "_")[:30]
        base = f"council_{topic_slug}_{ts}"

        json_path = self.output_dir / f"{base}.json"
        md_path = self.output_dir / f"{base}.md"

        # ── JSON ──
        json_path.write_text(json.dumps(session_data, indent=2, default=str), encoding="utf-8")

        # ── Markdown ──
        md_lines = [
            f"# Council Report — {session_data.get('topic', 'N/A')}",
            "",
            f"**Session:** {session_data.get('session_id', 'N/A')}  ",
            f"**Horizon:** {session_data.get('horizon', 'N/A')}  ",
            f"**Timestamp:** {session_data.get('timestamp', 'N/A')}  ",
            "",
            "## Council Members",
            "",
        ]
        for name in session_data.get("council_members", []):
            md_lines.append(f"- {name}")

        md_lines += ["", "## Predictions", ""]
        for pred in session_data.get("predictions", []):
            md_lines.append(f"### {pred.get('council_member', 'Unknown')}")
            md_lines.append(f"- **Outcome:** {pred.get('predicted_outcome', 'N/A')}")
            md_lines.append(f"- **Confidence:** {pred.get('confidence', 0):.0%}")
            md_lines.append(f"- **Risk:** {pred.get('risk_level', 'N/A')}")
            evidence = pred.get("evidence", [])
            if evidence:
                md_lines.append(f"- **Evidence:** {', '.join(str(e) for e in evidence)}")
            md_lines.append("")

        consensus = session_data.get("consensus")
        if consensus:
            md_lines += [
                "## Consensus",
                f"- **Reached:** {consensus.get('consensus_reached', False)}",
                f"- **Avg Confidence:** {consensus.get('average_confidence', 0):.0%}",
                f"- **Outcome:** {consensus.get('consensus_outcome', 'N/A')}",
                "",
            ]

        md_path.write_text("\n".join(md_lines), encoding="utf-8")
        logger.info("Reports saved: %s, %s", json_path, md_path)
        return {"json_path": str(json_path), "md_path": str(md_path)}

    def generate_backtest_report(self, backtest_df, topic: str = "backtest") -> dict[str, str]:
        """Generate a report from a backtest DataFrame."""
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        base = f"backtest_{topic}_{ts}"

        csv_path = self.output_dir / f"{base}.csv"
        md_path = self.output_dir / f"{base}.md"

        backtest_df.to_csv(csv_path, index=False)

        md_lines = [
            f"# Backtest Report — {topic}",
            f"**Timestamp:** {ts}",
            "",
            "## Results",
            "",
            backtest_df.to_markdown(index=False),
            "",
        ]
        md_path.write_text("\n".join(md_lines), encoding="utf-8")
        logger.info("Backtest report saved: %s", md_path)
        return {"csv_path": str(csv_path), "md_path": str(md_path)}
