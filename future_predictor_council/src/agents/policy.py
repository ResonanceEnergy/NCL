"""Policy Engine — enforces ReleasePolicy.yaml and steering.json gates.

Provides a unified interface for:
  - Release channel management (alpha → beta → stable)
  - Cost cap enforcement
  - Rollback trigger evaluation
  - Approval workflow management
  - Security scan gates
"""

from __future__ import annotations

import json
import logging
import pathlib
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class Channel(StrEnum):
    ALPHA = "alpha"
    BETA = "beta"
    STABLE = "stable"


class PolicyVerdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    GATE = "gate"  # needs human approval


@dataclass
class PolicyResult:
    verdict: PolicyVerdict
    channel: Channel | None = None
    checks: list[str] = field(default_factory=list)
    reason: str = ""
    requires_human: bool = False


@dataclass
class DeployState:
    """Tracks current deployment state per channel."""

    channel: Channel
    version: str = ""
    deployed_at: float = 0.0
    soak_start: float = 0.0
    soak_hours: float = 0.0
    traffic_pct: int = 0
    health_ok: bool = True
    action_failures: int = 0
    p95_latency_ms: float = 0.0


class PolicyEngine:
    """Unified policy enforcement for the autonomous agent framework."""

    def __init__(
        self,
        steering_path: str | pathlib.Path | None = None,
        policy_path: str | pathlib.Path | None = None,
    ) -> None:
        self.steering: dict[str, Any] = {}
        self.release_policy: dict[str, Any] = {}
        self.deploy_states: dict[str, DeployState] = {}
        self._spend_log: list[dict[str, Any]] = []
        self._total_spend_usd: float = 0.0

        base = pathlib.Path(__file__).resolve().parents[2]
        self._load_steering(steering_path or base / "config" / "steering.json")
        self._load_release_policy(policy_path or base / "ops" / "ReleasePolicy.yaml")

    def _load_steering(self, path: str | pathlib.Path) -> None:
        p = pathlib.Path(path)
        if p.exists():
            self.steering = json.loads(p.read_text())

    def _load_release_policy(self, path: str | pathlib.Path) -> None:
        p = pathlib.Path(path)
        if not p.exists():
            return
        try:
            import yaml
            self.release_policy = yaml.safe_load(p.read_text()) or {}
        except ImportError:
            self.release_policy = {"_raw": p.read_text()}

    # ── Cost Governance ─────────────────────────────────────────
    def check_budget(self, cost_usd: float) -> PolicyResult:
        """Check if spending cost_usd would exceed weekly budget."""
        cap = self.steering.get("budget_weekly_usd", 50.0)
        remaining = cap - self._total_spend_usd

        if cost_usd > remaining:
            return PolicyResult(
                verdict=PolicyVerdict.DENY,
                checks=[f"Budget: ${self._total_spend_usd:.2f} spent of ${cap:.2f}"],
                reason=f"Would exceed budget by ${cost_usd - remaining:.2f}",
            )

        return PolicyResult(
            verdict=PolicyVerdict.ALLOW,
            checks=[f"Budget OK: ${remaining:.2f} remaining after ${cost_usd:.2f}"],
        )

    def record_spend(self, usd: float, source: str = "") -> None:
        self._total_spend_usd += usd
        self._spend_log.append({"usd": usd, "source": source, "ts": time.time(), "total": self._total_spend_usd})

    def spend_summary(self) -> dict[str, Any]:
        cap = self.steering.get("budget_weekly_usd", 50.0)
        return {
            "total_usd": round(self._total_spend_usd, 2),
            "cap_usd": cap,
            "remaining_usd": round(cap - self._total_spend_usd, 2),
            "pct_used": round(self._total_spend_usd / cap * 100, 1) if cap > 0 else 0,
            "transactions": len(self._spend_log),
        }

    # ── GPU / Burst Cost Checks ─────────────────────────────────
    def check_burst(self, hourly_cost: float, duration_min: float) -> PolicyResult:
        """Validate a burst request against GPU and budget caps."""
        checks: list[str] = []
        gpu_cap = self.steering.get("gpu_max_hourly", 1.20)
        daily_cap = self.steering.get("gpu_max_daily_min", 60)
        total_cost = hourly_cost * (duration_min / 60.0)

        if hourly_cost > gpu_cap:
            return PolicyResult(
                verdict=PolicyVerdict.DENY,
                checks=[f"Hourly ${hourly_cost:.2f} > cap ${gpu_cap:.2f}"],
                reason="GPU hourly rate exceeds cap",
            )
        checks.append(f"Hourly OK: ${hourly_cost:.2f} <= ${gpu_cap:.2f}")

        if duration_min > daily_cap:
            return PolicyResult(
                verdict=PolicyVerdict.DENY,
                checks=[*checks, f"Duration {duration_min}min > cap {daily_cap}min"],
                reason="Burst duration exceeds daily cap",
            )
        checks.append(f"Duration OK: {duration_min}min <= {daily_cap}min")

        budget_result = self.check_budget(total_cost)
        if budget_result.verdict == PolicyVerdict.DENY:
            return PolicyResult(
                verdict=PolicyVerdict.DENY,
                checks=checks + budget_result.checks,
                reason=budget_result.reason,
            )
        checks.extend(budget_result.checks)

        return PolicyResult(verdict=PolicyVerdict.ALLOW, checks=checks)

    # ── Release Channel Management ──────────────────────────────
    def check_deploy(self, version: str, target_channel: str = "alpha") -> PolicyResult:
        """Check if deploying a version to a channel is allowed."""
        channels = self.release_policy.get("channels", {})
        channel_config = channels.get(target_channel)
        checks: list[str] = []

        if not channel_config:
            return PolicyResult(verdict=PolicyVerdict.DENY, reason=f"Unknown channel: {target_channel}")

        # Check soak requirements of current channel before promoting
        if target_channel == "beta":
            alpha_state = self.deploy_states.get("alpha")
            if alpha_state:
                soak_required = channels.get("alpha", {}).get("soak_hours", 0)
                elapsed = (time.time() - alpha_state.soak_start) / 3600 if alpha_state.soak_start else 0
                if elapsed < soak_required:
                    checks.append(f"Soak: {elapsed:.1f}h of {soak_required}h completed")
                    return PolicyResult(
                        verdict=PolicyVerdict.DENY,
                        checks=checks,
                        reason=f"Alpha soak not complete ({elapsed:.1f}h < {soak_required}h)",
                    )
            checks.append("Alpha soak complete")

        elif target_channel == "stable":
            beta_state = self.deploy_states.get("beta")
            if beta_state:
                soak_required = channels.get("beta", {}).get("soak_hours", 24)
                elapsed = (time.time() - beta_state.soak_start) / 3600 if beta_state.soak_start else 0
                if elapsed < soak_required:
                    return PolicyResult(
                        verdict=PolicyVerdict.DENY,
                        checks=[f"Soak: {elapsed:.1f}h of {soak_required}h"],
                        reason=f"Beta soak not complete ({elapsed:.1f}h < {soak_required}h)",
                    )
            checks.append("Beta soak complete")

        # Check if auto-promote is allowed
        auto_promote = channel_config.get("auto_promote", False)
        if not auto_promote:
            checks.append(f"Channel {target_channel} requires manual approval")
            return PolicyResult(
                verdict=PolicyVerdict.GATE,
                channel=Channel(target_channel),
                checks=checks,
                requires_human=True,
            )

        checks.append(f"Deploy to {target_channel} approved")
        return PolicyResult(verdict=PolicyVerdict.ALLOW, channel=Channel(target_channel), checks=checks)

    def record_deploy(self, version: str, channel: str) -> None:
        """Record a deployment to a channel."""
        now = time.time()
        self.deploy_states[channel] = DeployState(
            channel=Channel(channel),
            version=version,
            deployed_at=now,
            soak_start=now,
        )

    # ── Rollback Triggers ───────────────────────────────────────
    def check_rollback(self, channel: str, p95_ms: float = 0.0, failures: int = 0) -> PolicyResult:
        """Check if rollback thresholds are breached."""
        triggers = self.release_policy.get("rollback_triggers", {})
        checks: list[str] = []
        should_rollback = False

        p95_limit = triggers.get("p95_latency_ms")
        if p95_limit and p95_ms > p95_limit:
            checks.append(f"BREACH: p95 {p95_ms}ms > {p95_limit}ms")
            should_rollback = True
        elif p95_limit:
            checks.append(f"p95 OK: {p95_ms}ms <= {p95_limit}ms")

        failure_limit = triggers.get("action_failures")
        if failure_limit and failures > failure_limit:
            checks.append(f"BREACH: {failures} failures > {failure_limit}")
            should_rollback = True
        elif failure_limit:
            checks.append(f"Failures OK: {failures} <= {failure_limit}")

        mase_limit = triggers.get("mase_regression")
        if mase_limit:
            checks.append(f"MASE regression cap: {mase_limit}")

        if should_rollback:
            return PolicyResult(
                verdict=PolicyVerdict.DENY,
                channel=Channel(channel) if channel in Channel.__members__.values() else None,
                checks=checks,
                reason="Rollback triggered — thresholds breached",
            )

        return PolicyResult(verdict=PolicyVerdict.ALLOW, checks=checks)

    # ── Security Gates ──────────────────────────────────────────
    def check_security(self, sbom_present: bool = False, vuln_scan_clean: bool = False) -> PolicyResult:
        """Enforce security scan gates before deploy."""
        gates = self.release_policy.get("security", {})
        checks: list[str] = []

        if gates.get("sbom", {}).get("required", False) and not sbom_present:
            checks.append("FAIL: SBOM required but not present")
            return PolicyResult(verdict=PolicyVerdict.DENY, checks=checks, reason="Missing SBOM")
        checks.append("SBOM: present" if sbom_present else "SBOM: not required")

        if gates.get("vuln_scan", {}).get("required", False) and not vuln_scan_clean:
            checks.append("FAIL: Vuln scan required but not clean")
            return PolicyResult(verdict=PolicyVerdict.DENY, checks=checks, reason="Vulnerability scan failures")
        checks.append("Vuln scan: clean" if vuln_scan_clean else "Vuln scan: not required")

        return PolicyResult(verdict=PolicyVerdict.ALLOW, checks=checks)
