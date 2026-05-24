#!/usr/bin/env python3
"""
NARTIX Health Dashboard — Monitor all ecosystem services from one command.

Checks HTTP health endpoints for relay, NCL brain, Paperclip, and Ollama.
Outputs a color-coded status table or machine-readable JSON.

Generated via NARTIX MWP Pipeline:
  Pump: PUMP-CODING-TEST-001
  Council: Hierarchical Delegation (immediate)
  Execution: Claude → Copilot (Opus 4.6) hybrid loop

Usage:
    python3 nartix_health.py          # Rich table output
    python3 nartix_health.py --json   # Machine-readable JSON
    python3 nartix_health.py --watch  # Continuous monitoring (5s refresh)
"""

from __future__ import annotations

import asyncio
import json
import ssl
import sys
import time
from dataclasses import asdict, dataclass
from typing import Optional


try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table

    HAS_RICH = True
except ImportError:
    HAS_RICH = False


# --- Service Configuration ---


@dataclass
class ServiceConfig:
    """Definition of a NARTIX service to monitor."""

    name: str
    url: str
    status_key: str = "status"
    expected_value: str = "ok"
    description: str = ""


SERVICES: list[ServiceConfig] = [
    ServiceConfig(
        name="Relay",
        url="https://192.168.1.72:8787/health",
        status_key="status",
        expected_value="ok",
        description="FirstStrike iPhone → NCL pipeline",
    ),
    ServiceConfig(
        name="NCL Brain",
        url="http://localhost:8800/health",
        status_key="status",
        expected_value="ok",
        description="NCL Brain cortex API",
    ),
    ServiceConfig(
        name="AAC WAR Room",
        url="http://localhost:8080/health",
        status_key="status",
        expected_value="healthy",
        description="Capital growth engine + scenario war room",
    ),
    ServiceConfig(
        name="Paperclip",
        url="http://localhost:3100/api/health",
        status_key="status",
        expected_value="ok",
        description="Agent control plane",
    ),
    ServiceConfig(
        name="Ollama",
        url="http://localhost:11434/api/tags",
        status_key="_any",
        expected_value="_any",
        description="Local LLM inference",
    ),
]


# --- Health Check ---


@dataclass
class HealthResult:
    """Result of a single service health check."""

    name: str
    url: str
    status: str  # UP, DOWN, DEGRADED
    response_time_ms: float
    detail: Optional[str] = None
    error: Optional[str] = None

    @property
    def is_healthy(self) -> bool:
        return self.status == "UP"


async def check_service(service: ServiceConfig, timeout: float = 5.0) -> HealthResult:
    """
    Check a single service's health endpoint.
    Returns HealthResult with status, timing, and any error details.
    """
    start = time.monotonic()

    # Skip TLS verification for self-signed certs (relay uses self-signed)
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            verify=ssl_context,
            follow_redirects=True,
        ) as client:
            resp = await client.get(service.url)
            elapsed = (time.monotonic() - start) * 1000

            if resp.status_code == 200:
                # Try to parse JSON and check status key
                try:
                    data = resp.json()
                    if service.status_key == "_any":
                        # Any 200 response is good (e.g., Ollama /api/tags)
                        return HealthResult(
                            name=service.name,
                            url=service.url,
                            status="UP",
                            response_time_ms=round(elapsed, 1),
                            detail=f"{len(data.get('models', []))} models"
                            if isinstance(data, dict) and "models" in data
                            else "OK",
                        )

                    actual = data.get(service.status_key, "unknown")

                    # AAC WAR Room — surface P&L, ROI, doctrine state
                    detail_str = str(actual)
                    if isinstance(data, dict) and "pnl" in data:
                        pnl = data.get("pnl", 0)
                        roi = data.get("roi", 0)
                        doctrine = data.get("doctrine_state", "unknown")
                        pnl_sign = "+" if pnl >= 0 else ""
                        detail_str = f"P&L:{pnl_sign}{pnl:.0f} ROI:{roi:.1%} [{doctrine}]"

                    if actual == service.expected_value:
                        return HealthResult(
                            name=service.name,
                            url=service.url,
                            status="UP",
                            response_time_ms=round(elapsed, 1),
                            detail=detail_str,
                        )
                    else:
                        return HealthResult(
                            name=service.name,
                            url=service.url,
                            status="DEGRADED",
                            response_time_ms=round(elapsed, 1),
                            detail=detail_str,
                        )
                except (json.JSONDecodeError, AttributeError):
                    return HealthResult(
                        name=service.name,
                        url=service.url,
                        status="UP",
                        response_time_ms=round(elapsed, 1),
                        detail="non-JSON 200",
                    )
            else:
                elapsed = (time.monotonic() - start) * 1000
                return HealthResult(
                    name=service.name,
                    url=service.url,
                    status="DEGRADED",
                    response_time_ms=round(elapsed, 1),
                    error=f"HTTP {resp.status_code}",
                )

    except httpx.ConnectError:
        elapsed = (time.monotonic() - start) * 1000
        return HealthResult(
            name=service.name,
            url=service.url,
            status="DOWN",
            response_time_ms=round(elapsed, 1),
            error="Connection refused",
        )
    except httpx.ConnectTimeout:
        elapsed = (time.monotonic() - start) * 1000
        return HealthResult(
            name=service.name,
            url=service.url,
            status="DOWN",
            response_time_ms=round(elapsed, 1),
            error=f"Timeout ({timeout}s)",
        )
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return HealthResult(
            name=service.name,
            url=service.url,
            status="DOWN",
            response_time_ms=round(elapsed, 1),
            error=str(e)[:80],
        )


async def check_all_services() -> list[HealthResult]:
    """Check all configured services in parallel."""
    tasks = [check_service(svc) for svc in SERVICES]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Convert any unexpected exceptions to HealthResult with error detail
    cleaned = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            cleaned.append(
                HealthResult(
                    name=SERVICES[i].name,
                    url=SERVICES[i].url,
                    status="DOWN",
                    response_time_ms=0,
                    error=f"Check failed: {r}",
                )
            )
        else:
            cleaned.append(r)
    return cleaned


# --- Output Formatters ---


def print_table(results: list[HealthResult]) -> None:
    """Print results as a rich color-coded table."""
    if HAS_RICH:
        _print_rich_table(results)
    else:
        _print_plain_table(results)


def _print_rich_table(results: list[HealthResult]) -> None:
    """Rich library table output."""
    console = Console()

    table = Table(
        title="NARTIX Health Dashboard",
        title_style="bold cyan",
        border_style="dim",
        show_lines=True,
    )
    table.add_column("Service", style="bold", min_width=12)
    table.add_column("Status", justify="center", min_width=10)
    table.add_column("Response", justify="right", min_width=10)
    table.add_column("Detail", min_width=20)
    table.add_column("URL", style="dim", min_width=15)

    for r in results:
        status_style = {
            "UP": "[bold green]UP[/bold green]",
            "DOWN": "[bold red]DOWN[/bold red]",
            "DEGRADED": "[bold yellow]DEGRADED[/bold yellow]",
        }.get(r.status, r.status)

        time_color = (
            "green"
            if r.response_time_ms < 100
            else ("yellow" if r.response_time_ms < 1000 else "red")
        )
        time_str = f"[{time_color}]{r.response_time_ms:.0f}ms[/{time_color}]"

        detail = r.detail or r.error or ""

        table.add_row(r.name, status_style, time_str, detail, r.url)

    console.print()
    console.print(table)

    # Summary line
    up = sum(1 for r in results if r.status == "UP")
    total = len(results)
    color = "green" if up == total else ("yellow" if up > 0 else "red")
    console.print(f"\n  [{color}]{up}/{total} services healthy[/{color}]", highlight=False)
    console.print()


def _print_plain_table(results: list[HealthResult]) -> None:
    """Fallback plain-text table when rich is not installed."""
    print("\n  NARTIX Health Dashboard")
    print("  " + "=" * 70)
    print(f"  {'Service':<14} {'Status':<10} {'Time':>8}  {'Detail'}")
    print("  " + "-" * 70)

    for r in results:
        icon = {"UP": "+", "DOWN": "X", "DEGRADED": "~"}.get(r.status, "?")
        detail = r.detail or r.error or ""
        print(f"  [{icon}] {r.name:<12} {r.status:<10} {r.response_time_ms:>6.0f}ms  {detail}")

    print("  " + "=" * 70)
    up = sum(1 for r in results if r.status == "UP")
    print(f"  {up}/{len(results)} services healthy\n")


def print_json(results: list[HealthResult]) -> None:
    """Print results as JSON array."""
    output = [asdict(r) for r in results]
    print(json.dumps(output, indent=2))


# --- CLI ---


def main() -> None:
    """CLI entry point for nartix-health."""
    args = sys.argv[1:]

    json_mode = "--json" in args
    watch_mode = "--watch" in args

    if watch_mode and HAS_RICH:
        _run_watch_mode()
    else:
        results = asyncio.run(check_all_services())

        if json_mode:
            print_json(results)
        else:
            print_table(results)

        # Exit code: 0 if all healthy, 1 if any down
        sys.exit(0 if all(r.is_healthy for r in results) else 1)


def _run_watch_mode() -> None:
    """Continuous monitoring with live-updating table."""
    console = Console()
    console.print("[bold cyan]NARTIX Health Watch[/bold cyan] — Ctrl+C to stop\n")

    try:
        while True:
            results = asyncio.run(check_all_services())
            # Clear and reprint
            console.clear()
            console.print("[bold cyan]NARTIX Health Watch[/bold cyan] — Ctrl+C to stop\n")
            print_table(results)
            time.sleep(5)
    except KeyboardInterrupt:
        console.print("\n[dim]Watch stopped.[/dim]")


if __name__ == "__main__":
    main()
