"""Personal dashboard — single-screen command center for FPC analysis.

Renders rich terminal output combining predictions, alerts, scoring,
signal freshness, domain health, and evolution status into a unified view.

CLI commands::

    fpc dashboard             — Full command center overview
    fpc alerts                — View/manage active alerts
    fpc alerts --ack <id>     — Acknowledge an alert
    fpc alerts --ack-all      — Acknowledge all alerts
    fpc rank                  — Ranked prediction leaderboard
    fpc rank --all            — Include resolved predictions
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ── ANSI colors for terminal output ──────────────────────────────────────────

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_GREEN = "\033[92m"
_CYAN = "\033[96m"
_MAGENTA = "\033[95m"
_WHITE = "\033[97m"

GRADE_COLORS = {
    "S": _RED + _BOLD,
    "A": _YELLOW + _BOLD,
    "B": _GREEN,
    "C": _CYAN,
    "D": _DIM,
}

LEVEL_COLORS = {
    "CRITICAL": _RED + _BOLD,
    "HIGH": _YELLOW + _BOLD,
    "MEDIUM": _CYAN,
    "LOW": _DIM,
}

LEVEL_ICONS = {
    "CRITICAL": "!!!",
    "HIGH": " !! ",
    "MEDIUM": "  ! ",
    "LOW": "  . ",
}


def _color(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}"


def _header(title: str) -> str:
    line = "=" * 70
    return f"\n{_BOLD}{_CYAN}{line}\n  {title}\n{line}{_RESET}"


def _section(title: str) -> str:
    return f"\n{_BOLD}{_WHITE}--- {title} ---{_RESET}"


# ── Dashboard renderer ───────────────────────────────────────────────────────

class Dashboard:
    """Aggregate system state into terminal output."""

    def render_full(self) -> str:
        """Render the complete command center view."""
        lines = [_header("FPC COMMAND CENTER")]
        lines.append(f"  {_DIM}{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{_RESET}")

        # 1. Alert summary
        lines.append(self._render_alert_summary())

        # 2. Active predictions ranked
        lines.append(self._render_ranked_predictions(limit=10))

        # 3. Domain health
        lines.append(self._render_domain_health())

        # 4. Signal freshness
        lines.append(self._render_signal_freshness())

        # 5. Evolution status
        lines.append(self._render_evolution_status())

        # 6. Flywheel status
        lines.append(self._render_flywheel())

        lines.append(f"\n{_DIM}Commands: fpc alerts | fpc rank | fpc evolve | fpc scrape --status{_RESET}\n")
        return "\n".join(lines)

    def render_alerts(self, level: str | None = None) -> str:
        """Render detailed alert view."""
        from .alerting import AlertEngine
        engine = AlertEngine()
        active = engine.get_active_alerts(level)

        lines = [_header("ACTIVE ALERTS")]
        summary = engine.summary()
        crit = summary["CRITICAL"]
        high = summary["HIGH"]
        med = summary["MEDIUM"]
        low = summary["LOW"]
        lines.append(
            f"  {_color('CRITICAL: ' + str(crit), LEVEL_COLORS['CRITICAL'])} | "
            f"{_color('HIGH: ' + str(high), LEVEL_COLORS['HIGH'])} | "
            f"{_color('MEDIUM: ' + str(med), LEVEL_COLORS['MEDIUM'])} | "
            f"{_color('LOW: ' + str(low), LEVEL_COLORS['LOW'])}"
        )

        if not active:
            lines.append(f"\n  {_GREEN}No active alerts.{_RESET}")
            return "\n".join(lines)

        for a in active:
            lv = a.get("level", "LOW")
            icon = LEVEL_ICONS.get(lv, "  . ")
            color = LEVEL_COLORS.get(lv, "")
            icon_str = "[" + icon + "]"
            title = a.get("title", "Unknown")
            lines.append(f"\n  {_color(icon_str, color)} {_BOLD}{title}{_RESET}")
            lines.append(f"       {a.get('detail', '')}")
            lines.append(f"       {_DIM}ID: {a.get('id', '')} | {a.get('created_at', '')}{_RESET}")

        lines.append(f"\n  {_DIM}Acknowledge: fpc alerts --ack <alert_id>{_RESET}")
        lines.append(f"  {_DIM}Acknowledge all: fpc alerts --ack-all{_RESET}\n")
        return "\n".join(lines)

    def render_ranked(self, include_resolved: bool = False, limit: int = 25) -> str:
        """Render the full ranked prediction leaderboard."""
        from .signal_scorer import SignalScorer
        scorer = SignalScorer()
        predictions = scorer.rank_predictions(include_resolved=include_resolved)

        lines = [_header("PREDICTION LEADERBOARD")]
        if not predictions:
            lines.append(f"\n  {_DIM}No predictions tracked yet.{_RESET}")
            return "\n".join(lines)

        lines.append(
            f"\n  {'#':>3}  {'GRADE':^5}  {'SCORE':>6}  {'CONF':>5}  {'RISK':>8}  "
            f"{'DOMAIN':<22}  TOPIC"
        )
        lines.append(f"  {'---':>3}  {'-----':^5}  {'------':>6}  {'-----':>5}  {'--------':>8}  "
                     f"{'----------------------':<22}  {'-----'}")

        for i, p in enumerate(predictions[:limit], 1):
            grade = p.get("grade", "D")
            gc = GRADE_COLORS.get(grade, "")
            risk_str = str(p.get("risk_level", "?"))[:8]
            domain_str = p.get("domain", "?")[:22]
            topic_str = str(p.get("topic", "?"))[:40]

            grade_label = "  " + grade + "  "
            lines.append(
                f"  {i:>3}  {_color(grade_label, gc)}  "
                f"{p.get('impact_score', 0):>6.3f}  "
                f"{float(p.get('confidence', 0)):>5.0%}  "
                f"{risk_str:>8}  "
                f"{domain_str:<22}  {topic_str}"
            )

            if p.get("resolved"):
                acc = p.get("accuracy_score")
                acc_str = f"{acc:.0%}" if acc is not None else "N/A"
                lines.append(f"       {_DIM}Resolved: accuracy={acc_str}, "
                             f"outcome={p.get('actual_outcome', 'N/A')}{_RESET}")

        if len(predictions) > limit:
            lines.append(f"\n  {_DIM}... and {len(predictions) - limit} more. "
                         f"Use --all to include resolved.{_RESET}")

        lines.append("")
        return "\n".join(lines)

    # ── Section renderers ────────────────────────────────────────────────────

    def _render_alert_summary(self) -> str:
        from .alerting import AlertEngine
        engine = AlertEngine()
        s = engine.summary()

        if s["total_active"] == 0:
            return f"{_section('ALERTS')}\n  {_GREEN}All clear — no active alerts{_RESET}"

        parts = []
        if s["CRITICAL"]:
            parts.append(_color(f"{s['CRITICAL']} CRITICAL", LEVEL_COLORS["CRITICAL"]))
        if s["HIGH"]:
            parts.append(_color(f"{s['HIGH']} HIGH", LEVEL_COLORS["HIGH"]))
        if s["MEDIUM"]:
            parts.append(_color(f"{s['MEDIUM']} MEDIUM", LEVEL_COLORS["MEDIUM"]))
        if s["LOW"]:
            parts.append(_color(f"{s['LOW']} LOW", LEVEL_COLORS["LOW"]))

        return f"{_section('ALERTS')}\n  {' | '.join(parts)}  — run: fpc alerts"

    def _render_ranked_predictions(self, limit: int = 10) -> str:
        from .signal_scorer import SignalScorer
        scorer = SignalScorer()
        predictions = scorer.rank_predictions()

        lines = [_section("TOP PREDICTIONS (by impact score)")]
        if not predictions:
            lines.append(f"  {_DIM}No active predictions.{_RESET}")
            return "\n".join(lines)

        for i, p in enumerate(predictions[:limit], 1):
            grade = p.get("grade", "D")
            gc = GRADE_COLORS.get(grade, "")
            topic = str(p.get("topic", "?"))[:45]
            lines.append(
                f"  {i:>2}. {_color(f'[{grade}]', gc)} "
                f"{p.get('impact_score', 0):.3f}  "
                f"{float(p.get('confidence', 0)):.0%} conf  "
                f"{p.get('risk_level', '')!s:<8}  "
                f"{topic}"
            )

        if len(predictions) > limit:
            lines.append(f"  {_DIM}... {len(predictions) - limit} more — run: fpc rank{_RESET}")

        return "\n".join(lines)

    def _render_domain_health(self) -> str:
        from .signal_scorer import SignalScorer
        scorer = SignalScorer()
        health = scorer.domain_health()

        lines = [_section("DOMAIN HEALTH")]
        if not health:
            lines.append(f"  {_DIM}No domain data yet.{_RESET}")
            return "\n".join(lines)

        for domain, stats in sorted(health.items()):
            acc = stats.get("avg_accuracy")
            acc_str = f"{acc:.0%}" if acc is not None else "---"
            conf_str = f"{stats.get('avg_confidence', 0):.0%}"
            total = stats.get("total", 0)
            resolved = stats.get("resolved", 0)

            # Color-code accuracy
            if acc is not None and acc < 0.4:
                acc_disp = _color(acc_str, _RED)
            elif acc is not None and acc >= 0.7:
                acc_disp = _color(acc_str, _GREEN)
            else:
                acc_disp = acc_str

            lines.append(
                f"  {domain:<25} acc={acc_disp:>5}  "
                f"conf={conf_str:>4}  "
                f"predictions={total} ({resolved} resolved)"
            )

        return "\n".join(lines)

    def _render_signal_freshness(self) -> str:
        cache_dir = Path("data/signal_cache")
        lines = [_section("SIGNAL FRESHNESS")]

        if not cache_dir.exists():
            lines.append(f"  {_DIM}No signal cache found. Run: fpc scrape{_RESET}")
            return "\n".join(lines)

        for tier in ["tier_1_daily", "tier_2_weekly", "tier_3_monthly", "tier_4_quarterly"]:
            files = sorted(cache_dir.glob(f"{tier}_*.json"))
            if not files:
                lines.append(f"  {tier:<22} {_color('NEVER', _RED)}")
                continue

            latest = files[-1]
            try:
                ts_str = latest.stem.replace(f"{tier}_", "")
                last_dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
                age = datetime.now() - last_dt
                age_str = f"{age.days}d {age.seconds // 3600}h ago"

                data = json.loads(latest.read_text(encoding="utf-8"))
                count = data.get("signal_count", "?")

                if age.days > 7:
                    age_disp = _color(age_str, _RED)
                elif age.days > 1:
                    age_disp = _color(age_str, _YELLOW)
                else:
                    age_disp = _color(age_str, _GREEN)

                lines.append(f"  {tier:<22} {age_disp:<30} ({count} signals)")
            except (ValueError, json.JSONDecodeError, OSError):
                lines.append(f"  {tier:<22} {_DIM}parse error{_RESET}")

        return "\n".join(lines)

    def _render_evolution_status(self) -> str:
        lines = [_section("EVOLUTION ENGINE")]
        tasks_file = Path("state/evolution/tasks.json")

        if not tasks_file.exists():
            lines.append(f"  {_DIM}No evolution tasks. Run: fpc evolve{_RESET}")
            return "\n".join(lines)

        try:
            tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            lines.append(f"  {_DIM}Could not read evolution tasks.{_RESET}")
            return "\n".join(lines)

        queued = [t for t in tasks if t.get("status") == "queued"]
        completed = [t for t in tasks if t.get("status") == "completed"]
        in_progress = [t for t in tasks if t.get("status") == "in-progress"]

        lines.append(
            f"  Queued: {len(queued)}  |  In-Progress: {len(in_progress)}  |  "
            f"Completed: {len(completed)}  |  Total: {len(tasks)}"
        )

        # Show top 3 queued tasks
        top = sorted(queued, key=lambda t: t.get("priority", 100))[:3]
        for t in top:
            lines.append(
                f"    [{t.get('priority', '?'):>3}] {t.get('category', '?')}: "
                f"{t.get('title', 'Unknown')}"
            )

        # Latest evolution report
        evo_reports = sorted(Path("state/evolution").glob("report_*.json"))
        if evo_reports:
            latest = evo_reports[-1]
            try:
                report = json.loads(latest.read_text(encoding="utf-8"))
                acc = report.get("accuracy", 0)
                acc_color = _RED if acc < 0.4 else (_GREEN if acc >= 0.7 else _YELLOW)
                lines.append(
                    f"\n  Last analysis: accuracy={_color(f'{acc:.0%}', acc_color)}, "
                    f"strengths={len(report.get('strengths', []))}, "
                    f"weaknesses={len(report.get('weaknesses', []))}"
                )
            except (json.JSONDecodeError, OSError):
                pass

        return "\n".join(lines)

    def _render_flywheel(self) -> str:
        feed_file = Path("state/flywheel_feed.json")
        lines = [_section("SYSTEM STATUS")]

        if not feed_file.exists():
            lines.append(f"  {_DIM}No flywheel data.{_RESET}")
            return "\n".join(lines)

        try:
            feed = json.loads(feed_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            lines.append(f"  {_DIM}Could not read flywheel feed.{_RESET}")
            return "\n".join(lines)

        stage = feed.get("stage", "unknown")
        detail = feed.get("detail", "")
        ts = feed.get("timestamp", "")

        stage_colors = {"idle": _GREEN, "council": _CYAN, "backtest": _YELLOW,
                        "thinking": _MAGENTA, "scraping": _YELLOW, "ingestion": _CYAN}
        sc = stage_colors.get(stage, _WHITE)

        lines.append(f"  Stage: {_color(stage, sc)}  |  {detail}  |  {_DIM}{ts}{_RESET}")

        # Prediction count
        pred_file = Path("state/predictions.json")
        if pred_file.exists():
            try:
                preds = json.loads(pred_file.read_text(encoding="utf-8"))
                total = len(preds)
                unresolved = len([p for p in preds if not p.get("resolved")])
                lines.append(f"  Predictions: {total} total, {unresolved} active")
            except (json.JSONDecodeError, OSError):
                pass

        return "\n".join(lines)
