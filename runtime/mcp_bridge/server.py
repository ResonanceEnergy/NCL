#!/usr/bin/env python3
"""
NCL Brain MCP Server Bridge

Exposes NCL Brain API tools to Claude Code via MCP (Model Context Protocol).
Uses FastMCP for stdio-based server implementation.

Auth: Reads STRIKE_AUTH_TOKEN from environment variable.
Backend: Calls NCL Brain API at NCL_BRAIN_URL (default: http://localhost:8800)
"""

import os
import sys
import json
import logging
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration from environment
NCL_BRAIN_URL = os.getenv("NCL_BRAIN_URL", "http://localhost:8800")
STRIKE_AUTH_TOKEN = os.getenv("STRIKE_AUTH_TOKEN", "")

if not STRIKE_AUTH_TOKEN:
    logger.warning("STRIKE_AUTH_TOKEN not set; unauthenticated requests will fail")

# Initialize FastMCP server
server = FastMCP("ncl-brain")

# HTTP client with auth
def get_headers() -> dict[str, str]:
    """Build headers with bearer token auth."""
    headers = {"Content-Type": "application/json"}
    if STRIKE_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {STRIKE_AUTH_TOKEN}"
    return headers


async def http_get(path: str) -> dict[str, Any]:
    """Make authenticated GET request to NCL Brain API."""
    url = f"{NCL_BRAIN_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=get_headers())
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"HTTP error on GET {url}: {e}")
        raise ValueError(f"NCL Brain API error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error on GET {url}: {e}")
        raise ValueError(f"Failed to reach NCL Brain: {e}")


async def http_post(path: str, data: dict[str, Any]) -> dict[str, Any]:
    """Make authenticated POST request to NCL Brain API."""
    url = f"{NCL_BRAIN_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=data, headers=get_headers())
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"HTTP error on POST {url}: {e}")
        raise ValueError(f"NCL Brain API error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error on POST {url}: {e}")
        raise ValueError(f"Failed to reach NCL Brain: {e}")


# ─────────────────────────────────────────────────────────────────
# Tool Definitions
# ─────────────────────────────────────────────────────────────────


@server.tool()
async def ncl_health() -> dict[str, Any]:
    """
    Check NCL Brain health and connectivity.

    Returns:
      status (str): 'ok' or 'error'
      uptime (float): Seconds since brain startup
      version (str): Brain API version
    """
    try:
        result = await http_get("/health")
        return result
    except ValueError as e:
        return {"status": "error", "message": str(e)}


@server.tool()
async def ncl_council_spawn(
    topic: str,
    question: str,
    council_type: str = "cloud",
) -> dict[str, Any]:
    """
    Spawn a new council (deliberation) session on a topic.

    Args:
      topic (str): Topic for council (e.g., "mandate-generation", "strategy-review")
      question (str): Specific question or prompt for council debate
      council_type (str): Type of council; "cloud" (default), "youtube", "x"

    Returns:
      session_id (str): Unique session ID
      status (str): "spawned" or "error"
      council_members (list): Participating models (Claude, Grok, Gemini, Perplexity, GPT)
      question (str): Echoed question
      deliberation_started (float): Unix timestamp of session start
    """
    payload = {
        "topic": topic,
        "question": question,
        "council_type": council_type,
    }
    return await http_post("/council/spawn", payload)


@server.tool()
async def ncl_mandate_list() -> dict[str, Any]:
    """
    List all active mandates.

    Returns:
      mandates (list): Array of active mandate objects
        - Each has: id, title, pillar, priority, created_at, status
      total (int): Total count of active mandates
    """
    return await http_get("/mandates")


@server.tool()
async def ncl_mandate_create(
    title: str,
    description: str,
    pillar: str,
    priority: str = "medium",
) -> dict[str, Any]:
    """
    Create a new mandate for downstream pillars.

    Args:
      title (str): Concise mandate title
      description (str): Full mandate description (rationale + specifics)
      pillar (str): Target pillar: "NCC", "BRS", or "AAC"
      priority (str): Priority level: "low", "medium" (default), "high", "critical"

    Returns:
      id (str): Mandate UUID
      status (str): "created" or "error"
      pillar (str): Target pillar
      created_at (float): Unix timestamp
    """
    payload = {
        "title": title,
        "description": description,
        "pillar": pillar,
        "priority": priority,
    }
    return await http_post("/mandates", payload)


@server.tool()
async def ncl_memory_query(query: str) -> dict[str, Any]:
    """
    Query institutional memory.

    Args:
      query (str): Natural language query (e.g., "What was decided about game strategy?")

    Returns:
      results (list): Matching memory entries
        - Each has: id, content, timestamp, confidence, category
      total_matches (int): Count of matching entries
    """
    payload = {"query": query}
    return await http_post("/memory/query", payload)


@server.tool()
async def ncl_feedback_submit(
    pillar: str,
    report_content: str,
    category: str = "general",
) -> dict[str, Any]:
    """
    Submit feedback report from a downstream pillar (NCC, BRS, AAC).

    Args:
      pillar (str): Source pillar: "NCC" (execution), "BRS" (revenue), or "AAC" (capital)
      report_content (str): Feedback report content (YAML or JSON accepted)
      category (str): Report category: "general" (default), "error", "opportunity", "risk"

    Returns:
      report_id (str): Unique report ID
      status (str): "received" or "error"
      processing (str): Processing stage (queued, analyzing, synthesizing)
      created_at (float): Unix timestamp
    """
    payload = {
        "pillar": pillar,
        "report_content": report_content,
        "category": category,
    }
    return await http_post("/feedback", payload)


# ─────────────────────────────────────────────────────────────────
# Server Entrypoint
# ─────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    logger.info(
        f"Starting NCL Brain MCP Server (NCL_BRAIN_URL={NCL_BRAIN_URL})"
    )
    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
