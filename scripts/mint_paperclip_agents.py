#!/usr/bin/env python3
"""
Mint all NARTIX agents in Paperclip.

Reads the canonical agent list from paperclip.config.json (doctrine)
plus extras from nartix-company.json, then registers each one via
the Paperclip API.

Usage:
    python scripts/mint_paperclip_agents.py [--dry-run]

Requires:
    - Paperclip running at PAPERCLIP_URL (default: http://localhost:3100)
    - PAPERCLIP_COMPANY_ID set in .env
"""

import asyncio
import json
import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Load .env
env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

from runtime.paperclip_adapter.client import PaperclipClient

# ── Canonical agent definitions (union of both manifests) ────────────────

AGENTS = [
    {
        "name": "Claude-Chair",
        "role": "council_moderator",
        "adapter": "claude_local",
        "pillar": "NCL",
        "description": "Permanent council chair. Moderates debate, synthesizes outputs, runs Claude-to-Copilot hybrid coding loop.",
    },
    {
        "name": "Researcher",
        "role": "investigate_factcheck",
        "adapter": "perplexity",
        "pillar": "NCL",
        "description": "UNI research cortex. Investigates claims, verifies facts, finds primary sources with confidence scores.",
    },
    {
        "name": "TrendsAnalyst",
        "role": "youtube_news_trends",
        "adapter": "gemini",
        "pillar": "NCL",
        "description": "Monitors YouTube, Google Trends, and News for signals. Flags anomalies and emerging patterns.",
    },
    {
        "name": "IntelScanner",
        "role": "intelligence_scanning",
        "adapter": "grok",
        "pillar": "NCL",
        "description": "Awarebot-FPC intelligence scanner. Monitors X, Reddit, Polymarket. Scores importance, detects convergence.",
    },
    {
        "name": "FirstStrike",
        "role": "mobile_intelligence",
        "adapter": "grok",
        "pillar": "NCL",
        "description": "Mobile cognition entry point. Receives and pre-processes pump prompts from iPhone.",
    },
    {
        "name": "Engineer",
        "role": "execution_support",
        "adapter": "claude_local",
        "pillar": "NCC",
        "description": "NCC execution engineer. Deploys services, manages infrastructure, runs health checks.",
    },
    {
        "name": "WarRoomAnalyst",
        "role": "scenario_analysis",
        "adapter": "claude_local",
        "pillar": "AAC",
        "description": "AAC War Room scenarios. Evaluates geopolitical events, calculates Kelly criterion position sizing.",
    },
    {
        "name": "RevenueAgent",
        "role": "revenue_operations",
        "adapter": "claude_local",
        "pillar": "BRS",
        "description": "BRS revenue operations. Tracks DIGITAL-LABOUR leads, manages NERVE scoring, generates proposals.",
    },
    {
        "name": "YouTubeCouncil",
        "role": "youtube_intelligence",
        "adapter": "claude_local",
        "pillar": "NCL",
        "description": "YouTube Intelligence Council analyst. Scrapes channels, transcribes audio, analyzes for actionable intelligence.",
    },
    {
        "name": "XCouncil",
        "role": "x_intelligence",
        "adapter": "claude_local",
        "pillar": "NCL",
        "description": "X (Twitter) Intelligence Council analyst. Full intelligence sweeps across tracked accounts and trending topics.",
    },
    {
        "name": "LocalThinker",
        "role": "fast_reasoning",
        "adapter": "ollama_fast",
        "pillar": "NCL",
        "description": "Quick-turnaround reasoning and code review via local Ollama. Low-latency, no cloud API needed.",
    },
]


async def mint_agents(dry_run: bool = False):
    """Register all NARTIX agents in Paperclip."""

    client = PaperclipClient()

    print(f"Paperclip URL: {client.base_url}")
    print(f"Company ID:    {client.company_id}")
    print(f"Agents to mint: {len(AGENTS)}")
    print()

    if not client.company_id:
        print("ERROR: No PAPERCLIP_COMPANY_ID set. Run register_company first or set in .env")
        return

    # Health check
    healthy = await client.health_check()
    if not healthy:
        print(f"WARNING: Paperclip health check failed at {client.base_url}")
        if not dry_run:
            print("Aborting. Fix Paperclip connectivity first.")
            await client.close()
            return
    else:
        print(f"Paperclip healthy at {client.base_url}")

    # Check existing agents
    try:
        existing = await client.list_agents()
        existing_names = {a.get("name", "") for a in existing}
        print(f"Existing agents: {len(existing)} ({', '.join(existing_names) or 'none'})")
    except Exception as e:
        print(f"Could not list existing agents: {e}")
        existing_names = set()

    print()

    # Mint each agent
    minted = 0
    skipped = 0
    failed = 0

    for agent in AGENTS:
        name = agent["name"]

        if name in existing_names:
            print(f"  SKIP  {name:20s} (already exists)")
            skipped += 1
            continue

        if dry_run:
            print(f"  DRY   {name:20s} role={agent['role']:25s} pillar={agent['pillar']}")
            minted += 1
            continue

        try:
            agent_id = await client.register_agent(
                name=name,
                description=agent["description"],
                role=agent["role"],
            )
            print(f"  MINT  {name:20s} → {agent_id}")
            minted += 1
        except Exception as e:
            print(f"  FAIL  {name:20s} → {e}")
            failed += 1

    print()
    print(f"Results: {minted} minted, {skipped} skipped, {failed} failed")

    await client.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== DRY RUN MODE ===\n")
    asyncio.run(mint_agents(dry_run=dry_run))
