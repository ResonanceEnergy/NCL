#!/usr/bin/env python3
"""
Feedback Synthesis Engine

Reads recent reports from all pillars (NCC, BRS, AAC) and orchestrates
synthesis via NCL Brain council. Outputs integrated synthesis to synthesis/

Usage:
  python synthesizer.py                             # Run synthesis pass
  python synthesizer.py --debug                     # Verbose output
  python synthesizer.py --dry-run                   # Show what would be synthesized
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import yaml
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
FEEDBACK_DIR = SENDER_DIR.parent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

if not STRIKE_AUTH_TOKEN:
    logger.warning("STRIKE_AUTH_TOKEN not set; authentication may fail")


# ─────────────────────────────────────────────────────────────────
# Report Loading
# ─────────────────────────────────────────────────────────────────


def load_report(file_path: Path) -> Optional[dict]:
    """Load YAML report file."""
    try:
        with open(file_path) as f:
            data = yaml.safe_load(f)
            if isinstance(data, dict):
                data["_source_file"] = file_path.name
                return data
    except Exception as e:
        logger.warning(f"Failed to load {file_path.name}: {e}")
    return None


def collect_recent_reports(days: int = 7) -> dict[str, list[dict]]:
    """
    Collect recent reports from all pillar directories.

    Args:
      days: Only include reports modified within last N days

    Returns:
      {"NCC": [...], "BRS": [...], "AAC": [...]}
    """
    reports = {"NCC": [], "BRS": [], "AAC": []}
    cutoff = datetime.now().timestamp() - (days * 86400)

    for pillar, folder in [
        ("NCC", FEEDBACK_DIR / "ncc-reports"),
        ("BRS", FEEDBACK_DIR / "brs-reports"),
        ("AAC", FEEDBACK_DIR / "aac-reports"),
    ]:
        if not folder.exists():
            continue

        for report_file in folder.glob("*.yaml"):
            # Filter by recency
            if report_file.stat().st_mtime < cutoff:
                continue

            report_data = load_report(report_file)
            if report_data:
                reports[pillar].append(report_data)

    return reports


# ─────────────────────────────────────────────────────────────────
# HTTP Client
# ─────────────────────────────────────────────────────────────────


def get_headers() -> dict[str, str]:
    """Build headers with bearer token."""
    headers = {"Content-Type": "application/json"}
    if STRIKE_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {STRIKE_AUTH_TOKEN}"
    return headers


async def call_ncl_council(topic: str, question: str) -> Optional[dict]:
    """
    Call NCL council to synthesize feedback.

    Args:
      topic: Council topic (e.g., "feedback-synthesis")
      question: Synthesis question/prompt

    Returns:
      Council response or None on failure
    """
    url = f"{NCL_BRAIN_URL}/council/spawn"
    payload = {
        "topic": topic,
        "question": question,
        "council_type": "cloud",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=get_headers())
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Council call failed: {e}")
        return None


async def submit_synthesis(synthesis_data: dict) -> bool:
    """
    POST completed synthesis to NCL Brain.

    Args:
      synthesis_data: Synthesis output dict

    Returns:
      Success flag
    """
    url = f"{NCL_BRAIN_URL}/feedback/synthesis"
    payload = {
        "synthesis": synthesis_data,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=get_headers())
            response.raise_for_status()
            logger.info("Synthesis posted to NCL Brain")
            return True
    except Exception as e:
        logger.error(f"Failed to post synthesis: {e}")
        return False


# ─────────────────────────────────────────────────────────────────
# Synthesis Logic
# ─────────────────────────────────────────────────────────────────


def build_synthesis_prompt(reports: dict[str, list[dict]]) -> str:
    """
    Build synthesis question for council.

    Args:
      reports: {pillar: [report_dicts]}

    Returns:
      Council prompt
    """
    summary = []

    if reports["NCC"]:
        summary.append(f"NCC has {len(reports['NCC'])} execution report(s)")
    if reports["BRS"]:
        summary.append(f"BRS has {len(reports['BRS'])} revenue report(s)")
    if reports["AAC"]:
        summary.append(f"AAC has {len(reports['AAC'])} capital report(s)")

    prompt = (
        "Synthesize feedback across execution (NCC), revenue (BRS), and capital (AAC) pillars. "
        "Identify: (1) patterns and convergences, (2) risks or blockers, (3) opportunities for mandate adjustment.\n\n"
        + " | ".join(summary)
    )

    return prompt


async def run_synthesis(reports: dict[str, list[dict]], dry_run: bool = False) -> Optional[dict]:
    """
    Run full synthesis pipeline.

    Returns:
      Synthesis output dict or None on failure
    """
    total_reports = sum(len(r) for r in reports.values())

    if total_reports == 0:
        logger.info("No recent reports found; skipping synthesis")
        return None

    logger.info(
        f"Running synthesis: {len(reports['NCC'])} NCC, "
        f"{len(reports['BRS'])} BRS, {len(reports['AAC'])} AAC"
    )

    if dry_run:
        logger.info("[DRY RUN] Would call council for synthesis")
        return {
            "timestamp": datetime.now().isoformat(),
            "pillar_summary": {
                "ncc_reports": len(reports["NCC"]),
                "brs_reports": len(reports["BRS"]),
                "aac_reports": len(reports["AAC"]),
            },
            "status": "dry_run",
        }

    # Build synthesis prompt
    prompt = build_synthesis_prompt(reports)

    # Call council
    council_response = await call_ncl_council(
        topic="feedback-synthesis",
        question=prompt,
    )

    if not council_response:
        logger.error("Council call failed; aborting synthesis")
        return None

    # Build synthesis output
    synthesis_output = {
        "timestamp": datetime.now().isoformat(),
        "council_session_id": council_response.get("session_id"),
        "topic": "feedback-synthesis",
        "pillar_summary": {
            "ncc_reports": len(reports["NCC"]),
            "brs_reports": len(reports["BRS"]),
            "aac_reports": len(reports["AAC"]),
        },
        "council_question": prompt,
        "council_response": council_response,
        "status": "synthesized",
    }

    return synthesis_output


async def save_synthesis(synthesis: dict) -> bool:
    """
    Save synthesis output to synthesis/ folder.

    Args:
      synthesis: Synthesis dict

    Returns:
      Success flag
    """
    synthesis_dir = FEEDBACK_DIR / "synthesis"
    synthesis_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = synthesis_dir / f"synthesis_{timestamp}.json"

    try:
        with open(output_file, "w") as f:
            json.dump(synthesis, f, indent=2, default=str)
        logger.info(f"Saved synthesis to {output_file.name}")
        return True
    except Exception as e:
        logger.error(f"Failed to save synthesis: {e}")
        return False


# ─────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────


async def main(args) -> int:
    """Main synthesis orchestrator."""
    # Collect reports
    reports = collect_recent_reports(days=7)
    total = sum(len(r) for r in reports.values())

    if args.debug:
        logger.setLevel(logging.DEBUG)

    if total == 0:
        logger.info("No recent reports found")
        return 0

    logger.info(
        f"Collected {total} reports: "
        f"{len(reports['NCC'])} NCC, "
        f"{len(reports['BRS'])} BRS, "
        f"{len(reports['AAC'])} AAC"
    )

    # Run synthesis
    synthesis = await run_synthesis(reports, dry_run=args.dry_run)

    if not synthesis:
        return 1

    # Save synthesis
    if not await save_synthesis(synthesis):
        return 1

    # Post to NCL Brain (unless dry-run)
    if not args.dry_run:
        if not await submit_synthesis(synthesis):
            logger.warning("Synthesis saved locally but failed to post to NCL Brain")

    logger.info("Synthesis complete")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Feedback Synthesis Engine — Orchestrate multi-pillar feedback synthesis"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be synthesized without calling council",
    )
    parser.add_argument(
        "--brain-url",
        default=NCL_BRAIN_URL,
        help=f"NCL Brain URL (default: {NCL_BRAIN_URL})",
    )

    args = parser.parse_args()

    if args.brain_url != NCL_BRAIN_URL:
        globals()["NCL_BRAIN_URL"] = args.brain_url

    sys.exit(asyncio.run(main(args)))
