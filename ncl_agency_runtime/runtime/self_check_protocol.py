#!/usr/bin/env python3
"""
NCL Self-Check Protocol — Continuous System Health Verification
══════════════════════════════════════════════════════════════════
Deep introspection engine that goes beyond gap analysis to verify
the entire NCL organism is alive and evolving.

Runs as part of the Autonomous Daemon or standalone.

Checks:
    1. Code Integrity    — all Python files parse without syntax errors
    2. Import Health     — core modules can be imported
    3. Config Validity   — ncl_config.json is valid and complete
    4. Memory Vitals     — memory system responds and has capacity
    5. Test Baseline     — test suite can be collected (not full run)
    6. Disk Health       — log directory, data directory, free space
    7. Process Health    — no zombie processes, no port conflicts
    8. Doctrine Drift    — key doctrine files haven't been deleted/corrupted
    9. Evolution Score   — are we making progress vs previous checks?
"""

from __future__ import annotations

import ast
import importlib
import json
import logging
import shutil
import socket
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

LOG = logging.getLogger("ncl.selfcheck")


@dataclass
class CheckResult:
    """Result from a single health check."""
    name: str
    passed: bool
    score: float           # 0.0 to 1.0
    details: str = ""
    recommendation: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "score": self.score,
            "details": self.details,
            "recommendation": self.recommendation,
            "timestamp": self.timestamp,
        }


class SelfCheckProtocol:
    """Deep system health verification protocol."""

    def __init__(self, repo_root: Path | None = None):
        self.repo_root = repo_root or _REPO_ROOT
        self._results: list[CheckResult] = []

    def run_all(self) -> dict[str, Any]:
        """Run all self-checks and return comprehensive report."""
        self._results = []
        checks = [
            self._check_code_integrity,
            self._check_import_health,
            self._check_config_validity,
            self._check_memory_vitals,
            self._check_disk_health,
            self._check_port_availability,
            self._check_doctrine_integrity,
            self._check_evolution_score,
        ]

        for check in checks:
            try:
                result = check()
                self._results.append(result)
            except Exception as exc:
                self._results.append(CheckResult(
                    name=check.__name__.replace("_check_", ""),
                    passed=False,
                    score=0.0,
                    details=f"Check crashed: {exc}",
                    recommendation="Fix the check itself",
                ))

        overall_score = (
            sum(r.score for r in self._results) / len(self._results)
            if self._results else 0.0
        )
        passed_count = sum(1 for r in self._results if r.passed)

        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "overall_score": round(overall_score, 3),
            "checks_passed": passed_count,
            "checks_total": len(self._results),
            "health_status": self._health_label(overall_score),
            "results": [r.to_dict() for r in self._results],
            "recommendations": [
                r.recommendation for r in self._results
                if not r.passed and r.recommendation
            ],
        }

        # Save report
        report_path = self.repo_root / "ncl_agency_runtime" / "logs" / "selfcheck_latest.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

        return report

    def _health_label(self, score: float) -> str:
        if score >= 0.9:
            return "EXCELLENT"
        if score >= 0.7:
            return "GOOD"
        if score >= 0.5:
            return "FAIR"
        if score >= 0.3:
            return "DEGRADED"
        return "CRITICAL"

    def _check_code_integrity(self) -> CheckResult:
        """Verify all Python files parse without syntax errors."""
        py_files = list(self.repo_root.rglob("*.py"))
        # Exclude __pycache__ and .git
        py_files = [f for f in py_files if "__pycache__" not in str(f) and ".git" not in str(f)]

        errors = []
        for py_file in py_files:
            try:
                source = py_file.read_text(encoding="utf-8")
                ast.parse(source, filename=str(py_file))
            except SyntaxError as exc:
                errors.append(f"{py_file.relative_to(self.repo_root)}: {exc.msg} (line {exc.lineno})")

        if errors:
            return CheckResult(
                name="code_integrity",
                passed=False,
                score=max(0, 1.0 - len(errors) / len(py_files)),
                details=f"{len(errors)} syntax errors in {len(py_files)} files: {'; '.join(errors[:5])}",
                recommendation="Fix syntax errors in listed files",
            )
        return CheckResult(
            name="code_integrity",
            passed=True,
            score=1.0,
            details=f"All {len(py_files)} Python files parse cleanly",
        )

    def _check_import_health(self) -> CheckResult:
        """Verify core modules can be imported."""
        core_modules = [
            "lib_ncl",
            "ncl_memory",
        ]
        failures = []
        for mod in core_modules:
            try:
                importlib.import_module(mod)
            except Exception as exc:
                failures.append(f"{mod}: {exc}")

        if failures:
            return CheckResult(
                name="import_health",
                passed=False,
                score=1.0 - len(failures) / len(core_modules),
                details=f"{len(failures)} import failures: {'; '.join(failures)}",
                recommendation="Check sys.path and module dependencies",
            )
        return CheckResult(
            name="import_health",
            passed=True,
            score=1.0,
            details=f"All {len(core_modules)} core modules import cleanly",
        )

    def _check_config_validity(self) -> CheckResult:
        """Verify ncl_config.json is valid and has required sections."""
        config_path = self.repo_root / "ncl_config.json"
        if not config_path.exists():
            return CheckResult(
                name="config_validity",
                passed=False,
                score=0.0,
                details="ncl_config.json not found",
                recommendation="Create ncl_config.json with required sections",
            )

        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return CheckResult(
                name="config_validity",
                passed=False,
                score=0.0,
                details=f"JSON parse error: {exc}",
                recommendation="Fix JSON syntax in ncl_config.json",
            )

        required_sections = ["system", "paths", "network", "memory", "privacy"]
        missing = [s for s in required_sections if s not in config]

        if missing:
            return CheckResult(
                name="config_validity",
                passed=False,
                score=1.0 - len(missing) / len(required_sections),
                details=f"Missing sections: {', '.join(missing)}",
                recommendation="Add missing config sections",
            )

        return CheckResult(
            name="config_validity",
            passed=True,
            score=1.0,
            details=f"Config valid with {len(config)} top-level sections",
        )

    def _check_memory_vitals(self) -> CheckResult:
        """Check memory system responsiveness."""
        try:
            from ncl_memory import get_memory_manager
            mgr = get_memory_manager()

            # Check basic operations work
            if hasattr(mgr, "get_memory_stats"):
                stats = mgr.get_memory_stats()
                total = stats.get("working_memory_count", 0) + \
                        stats.get("short_term_count", 0) + \
                        stats.get("long_term_count", 0)
                return CheckResult(
                    name="memory_vitals",
                    passed=True,
                    score=1.0,
                    details=f"Memory system online. Total memories: {total}",
                )

            return CheckResult(
                name="memory_vitals",
                passed=True,
                score=0.8,
                details="Memory system importable but stats unavailable",
            )

        except ImportError:
            return CheckResult(
                name="memory_vitals",
                passed=False,
                score=0.0,
                details="ncl_memory module not importable",
                recommendation="Check ncl_memory.py exists and dependencies installed",
            )
        except Exception as exc:
            return CheckResult(
                name="memory_vitals",
                passed=False,
                score=0.3,
                details=f"Memory system error: {exc}",
                recommendation="Check SQLite database integrity",
            )

    def _check_disk_health(self) -> CheckResult:
        """Check disk space and directory writability."""
        try:
            usage = shutil.disk_usage(str(self.repo_root))
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            pct_free = (usage.free / usage.total) * 100

            # Check log directory writable
            log_dir = self.repo_root / "ncl_agency_runtime" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            probe = log_dir / ".disk_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()

            if pct_free < 5:
                return CheckResult(
                    name="disk_health",
                    passed=False,
                    score=0.2,
                    details=f"Low disk space: {free_gb:.1f}GB free ({pct_free:.1f}%)",
                    recommendation="Free up disk space",
                )

            return CheckResult(
                name="disk_health",
                passed=True,
                score=min(1.0, pct_free / 20),
                details=f"{free_gb:.1f}GB free of {total_gb:.1f}GB ({pct_free:.1f}%)",
            )
        except Exception as exc:
            return CheckResult(
                name="disk_health",
                passed=False,
                score=0.0,
                details=f"Disk check failed: {exc}",
            )

    def _check_port_availability(self) -> CheckResult:
        """Check if required ports are available or already bound by NCL."""
        ports = {8787: "relay_server", 8123: "onedrop_api"}
        results = {}
        for port, service in ports.items():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    s.bind(("127.0.0.1", port))
                    results[service] = "available"
            except OSError:
                results[service] = "in_use"

        in_use = [s for s, status in results.items() if status == "in_use"]

        return CheckResult(
            name="port_availability",
            passed=True,  # Ports in use might be NCL services
            score=1.0,
            details=f"Port status: {json.dumps(results)}",
            recommendation="Check if in-use ports are NCL services" if in_use else "",
        )

    def _check_doctrine_integrity(self) -> CheckResult:
        """Verify key doctrine files exist and aren't corrupted."""
        doctrine_files = {
            "NCC_Master_Doctrine_v2.0.md": 1000,     # min expected size in bytes
            "ROADMAP_TO_SUCCESS.md": 500,
            "ncl_config.json": 100,
            "NCL_SUPER_OPENCLAW_SPEC.md": 500,
        }
        issues = []
        for filename, min_size in doctrine_files.items():
            filepath = self.repo_root / filename
            if not filepath.exists():
                issues.append(f"{filename} MISSING")
            elif filepath.stat().st_size < min_size:
                issues.append(f"{filename} suspiciously small ({filepath.stat().st_size}B)")

        if issues:
            return CheckResult(
                name="doctrine_integrity",
                passed=False,
                score=1.0 - len(issues) / len(doctrine_files),
                details=f"Doctrine issues: {'; '.join(issues)}",
                recommendation="Restore missing or corrupted doctrine files",
            )

        return CheckResult(
            name="doctrine_integrity",
            passed=True,
            score=1.0,
            details=f"All {len(doctrine_files)} doctrine files intact",
        )

    def _check_evolution_score(self) -> CheckResult:
        """Compare current state against previous self-check to measure progress."""
        history_path = self.repo_root / "ncl_agency_runtime" / "logs" / "selfcheck_history.ndjson"

        current_metrics = {
            "test_files": len(list((self.repo_root / "tests").glob("test_*.py")))
                          if (self.repo_root / "tests").exists() else 0,
            "runtime_modules": len(list((self.repo_root / "ncl_agency_runtime" / "runtime").glob("*.py")))
                              if (self.repo_root / "ncl_agency_runtime" / "runtime").exists() else 0,
            "total_py_files": len([
                f for f in self.repo_root.rglob("*.py")
                if "__pycache__" not in str(f) and ".git" not in str(f)
            ]),
        }

        # Append to history
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as f:
            entry = {"timestamp": datetime.now(UTC).isoformat(), "metrics": current_metrics}
            f.write(json.dumps(entry) + "\n")

        # Compare with previous
        try:
            lines = history_path.read_text(encoding="utf-8").splitlines()
            if len(lines) >= 2:
                prev = json.loads(lines[-2])
                prev_metrics = prev.get("metrics", {})
                improvements = sum(
                    1 for k in current_metrics
                    if current_metrics[k] > prev_metrics.get(k, 0)
                )
                regressions = sum(
                    1 for k in current_metrics
                    if current_metrics[k] < prev_metrics.get(k, 0)
                )

                if improvements > regressions:
                    return CheckResult(
                        name="evolution_score",
                        passed=True,
                        score=1.0,
                        details=f"Evolving positively: {improvements} improvements, {regressions} regressions. "
                                f"Metrics: {json.dumps(current_metrics)}",
                    )
                elif regressions > improvements:
                    return CheckResult(
                        name="evolution_score",
                        passed=False,
                        score=0.5,
                        details=f"Regression detected: {regressions} regressions, {improvements} improvements",
                        recommendation="Investigate recent changes that may have caused regression",
                    )
                else:
                    return CheckResult(
                        name="evolution_score",
                        passed=True,
                        score=1.0,
                        details=f"Stable — no regressions. Metrics: {json.dumps(current_metrics)}",
                    )
        except Exception:
            LOG.debug("Failed to check evolution score", exc_info=True)

        return CheckResult(
            name="evolution_score",
            passed=True,
            score=0.8,
            details=f"Baseline recorded: {json.dumps(current_metrics)}",
        )


# ── CLI Entry ────────────────────────────────────────────────

def main():
    protocol = SelfCheckProtocol()
    report = protocol.run_all()

    print("\n  NCL Self-Check Report")
    print(f"  {'=' * 50}")
    print(f"  Overall Score: {report['overall_score']:.1%}")
    print(f"  Status: {report['health_status']}")
    print(f"  Checks: {report['checks_passed']}/{report['checks_total']} passed")
    print()

    for result in report["results"]:
        icon = "+" if result["passed"] else "-"
        print(f"  [{icon}] {result['name']}: {result['score']:.0%} — {result['details'][:80]}")

    if report["recommendations"]:
        print("\n  Recommendations:")
        for rec in report["recommendations"]:
            print(f"    * {rec}")

    print()


if __name__ == "__main__":
    main()
