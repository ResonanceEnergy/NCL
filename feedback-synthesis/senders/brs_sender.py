#!/usr/bin/env python3
"""
BRS Feedback Sender

Reads BRS economic reports from brs-reports/ and POSTs them to the NCL Brain.
Validates reports against schema before submission.

Usage:
  python brs_sender.py <report_file.yaml>          # Send specific report
  python brs_sender.py --watch                      # Watch for new reports (continuous mode)
  python brs_sender.py --list                       # List pending reports
"""

import os
import sys
import argparse
import asyncio
import logging
from pathlib import Path
from typing import Optional

import yaml
import httpx
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────

# Load .env from NCL/ directory
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

NCL_BRAIN_URL = os.getenv("NCL_BRAIN_URL", "http://localhost:8800")
STRIKE_AUTH_TOKEN = os.getenv("STRIKE_AUTH_TOKEN", "")
SENDER_DIR = Path(__file__).parent
REPORTS_DIR = SENDER_DIR.parent / "brs-reports"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

if not STRIKE_AUTH_TOKEN:
    logger.warning("STRIKE_AUTH_TOKEN not set; authentication may fail")

# ─────────────────────────────────────────────────────────────────
# Schema Validation
# ─────────────────────────────────────────────────────────────────

REQUIRED_FIELDS = {
    "title": str,
    "timestamp": (int, float, str),
    "revenue_total": (int, float),
    "metrics": dict,
}

VALID_CATEGORIES = {"general", "error", "opportunity", "risk"}


def validate_report(data: dict) -> tuple[bool, Optional[str]]:
    """
    Validate BRS report structure.

    Returns:
      (is_valid, error_message)
    """
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            return False, f"Missing required field: {field}"
        if not isinstance(data[field], expected_type):
            return False, (
                f"Field '{field}' has wrong type; "
                f"expected {expected_type}, got {type(data[field])}"
            )

    if not isinstance(data.get("metrics"), dict):
        return False, "metrics must be a dict"

    return True, None


# ─────────────────────────────────────────────────────────────────
# HTTP Client
# ─────────────────────────────────────────────────────────────────


def get_headers() -> dict[str, str]:
    """Build headers with bearer token."""
    headers = {"Content-Type": "application/json"}
    if STRIKE_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {STRIKE_AUTH_TOKEN}"
    return headers


async def submit_report(report_data: dict, source_file: Path) -> bool:
    """
    Submit BRS report to NCL Brain.

    Args:
      report_data: Validated report dict
      source_file: Source file path (for logging)

    Returns:
      Success flag
    """
    url = f"{NCL_BRAIN_URL}/feedback"
    category = report_data.get("category", "general")

    payload = {
        "pillar": "BRS",
        "report_content": yaml.dump(report_data),
        "category": category,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=get_headers())
            response.raise_for_status()

            result = response.json()
            logger.info(
                f"✓ Submitted {source_file.name} (report_id={result.get('report_id')})"
            )
            return True

    except httpx.HTTPError as e:
        logger.error(f"HTTP error submitting {source_file.name}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error submitting {source_file.name}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────
# File Operations
# ─────────────────────────────────────────────────────────────────


def load_report(file_path: Path) -> Optional[dict]:
    """Load and parse YAML report file."""
    try:
        with open(file_path) as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                logger.error(f"Report {file_path.name} is not a YAML dict")
                return None
            return data
    except Exception as e:
        logger.error(f"Failed to load {file_path.name}: {e}")
        return None


def list_pending_reports() -> list[Path]:
    """List unprocessed BRS reports."""
    if not REPORTS_DIR.exists():
        logger.error(f"Reports directory not found: {REPORTS_DIR}")
        return []

    reports = sorted(REPORTS_DIR.glob("*.yaml"))
    return reports


# ─────────────────────────────────────────────────────────────────
# CLI Interface
# ─────────────────────────────────────────────────────────────────


async def send_single_report(file_path: str) -> int:
    """Send a single report file."""
    report_path = Path(file_path).resolve()

    if not report_path.exists():
        logger.error(f"File not found: {report_path}")
        return 1

    logger.info(f"Loading report: {report_path.name}")
    report_data = load_report(report_path)

    if not report_data:
        return 1

    is_valid, error = validate_report(report_data)
    if not is_valid:
        logger.error(f"Validation failed: {error}")
        return 1

    logger.info(f"Report validation passed. Submitting...")
    success = await submit_report(report_data, report_path)

    return 0 if success else 1


async def send_all_reports() -> int:
    """Send all pending reports."""
    reports = list_pending_reports()

    if not reports:
        logger.info("No pending reports found.")
        return 0

    logger.info(f"Found {len(reports)} pending reports.")
    success_count = 0

    for report_path in reports:
        report_data = load_report(report_path)
        if not report_data:
            continue

        is_valid, error = validate_report(report_data)
        if not is_valid:
            logger.warning(f"{report_path.name}: {error}")
            continue

        success = await submit_report(report_data, report_path)
        if success:
            success_count += 1

    logger.info(f"Submitted {success_count}/{len(reports)} reports.")
    return 0 if success_count == len(reports) else 1


def list_reports() -> int:
    """List pending reports."""
    reports = list_pending_reports()

    if not reports:
        print("No pending reports.")
        return 0

    print(f"\nPending BRS Reports ({len(reports)}):")
    for i, report_path in enumerate(reports, 1):
        stat = report_path.stat()
        size_kb = stat.st_size / 1024
        print(f"  {i}. {report_path.name:40} ({size_kb:.1f} KB)")

    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="BRS Feedback Sender — Submit economic reports to NCL Brain"
    )
    parser.add_argument(
        "report_file",
        nargs="?",
        help="Report YAML file to send (or omit for --list/--all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Send all pending reports from brs-reports/",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List pending reports without sending",
    )
    parser.add_argument(
        "--brain-url",
        default=NCL_BRAIN_URL,
        help=f"NCL Brain URL (default: {NCL_BRAIN_URL})",
    )

    args = parser.parse_args()

    # Override URL if provided
    if args.brain_url != NCL_BRAIN_URL:
        globals()["NCL_BRAIN_URL"] = args.brain_url

    # Dispatch
    if args.list:
        return list_reports()

    if args.all or not args.report_file:
        return asyncio.run(send_all_reports())

    return asyncio.run(send_single_report(args.report_file))


if __name__ == "__main__":
    sys.exit(main())
