"""Vision board image generation — Wave 14F (2026-05-25).

Takes a Vision (title + narrative + pillars) and generates a 1024x1024
"vision board" image via OpenAI's gpt-image-1 (default) or DALL-E 3.

Why OpenAI gpt-image-1: native HD, predictable PNG output, ~$0.04 per
1024x1024 hi-detail vs DALL-E 3's $0.04 standard. Either works.

Output: data/life_plan/vision-boards/{vision_id}-{timestamp}.png
Endpoint: POST /life/vision/board/generate
Serves: GET /life/vision/board/latest -> base64 + filename
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Vision


log = logging.getLogger("ncl.life_plan.vision_board")

_MODEL = os.getenv("NCL_VISION_BOARD_MODEL", "gpt-image-1")
_SIZE = os.getenv("NCL_VISION_BOARD_SIZE", "1024x1024")
_QUALITY = os.getenv("NCL_VISION_BOARD_QUALITY", "high")
_BUDGET = float(
    os.getenv("NCL_VISION_BOARD_BUDGET", "0.10")
)  # ~$0.04 per gen, 0.10 leaves headroom
_TIMEOUT = float(os.getenv("NCL_VISION_BOARD_TIMEOUT", "120.0"))


def _board_dir() -> Path:
    base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    d = base / "data" / "life_plan" / "vision-boards"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _build_prompt(vision: Vision) -> str:
    """Build the image-generation prompt from the Vision content."""
    pillars_text = ", ".join(vision.pillars) if vision.pillars else "balanced life"
    narrative_excerpt = (vision.narrative or "")[:600].replace("\n", " ")
    return (
        f'A vision board collage representing the life vision: "{vision.title}". '
        f"Pillars: {pillars_text}. "
        f"Style: warm, aspirational, photographic montage with soft natural lighting, "
        f"no text or words on the image. "
        f"Horizon: {vision.horizon_years} years. "
        f"Context: {narrative_excerpt}. "
        f"Mood: focused, optimistic, grounded. Use symbolic imagery — open horizons, "
        f"a person walking toward sunlight, geometric clarity, layered depth."
    )


async def generate_vision_board(vision: Vision) -> dict:
    """Hit OpenAI Images API. Returns dict with status + path or error.

    Result shape:
      {
        "status": "ok" | "no_key" | "budget" | "api_error",
        "path": str | None,         # local file path
        "filename": str | None,      # leaf name for client download
        "model": str,
        "size": str,
        "cost_usd": float,
        "error": str | None,
        "prompt_used": str,
      }
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return {
            "status": "no_key",
            "path": None,
            "filename": None,
            "error": "OPENAI_API_KEY not set",
        }

    # Budget gate
    try:
        from ..cost_tracker import check_budget

        if not await check_budget("openai", _BUDGET):
            return {
                "status": "budget",
                "path": None,
                "filename": None,
                "error": f"openai budget too low (need {_BUDGET})",
            }
    except Exception:
        pass

    prompt = _build_prompt(vision)

    import httpx

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "prompt": prompt,
                    "size": _SIZE,
                    "quality": _QUALITY,
                    "n": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300] if e.response is not None else ""
        log.warning(
            "[VISION-BOARD] HTTP %s: %s", e.response.status_code if e.response else "?", body
        )
        return {
            "status": "api_error",
            "path": None,
            "filename": None,
            "error": f"HTTP {e.response.status_code if e.response else '?'}: {body}",
        }
    except Exception as e:
        log.warning("[VISION-BOARD] api call failed: %s", e)
        return {"status": "api_error", "path": None, "filename": None, "error": str(e)}

    # Extract b64 image. OpenAI returns either b64_json or url depending on settings.
    img_b64: Optional[str] = None
    img_url: Optional[str] = None
    if isinstance(data.get("data"), list) and data["data"]:
        d0 = data["data"][0]
        img_b64 = d0.get("b64_json")
        img_url = d0.get("url")

    img_bytes: Optional[bytes] = None
    if img_b64:
        img_bytes = base64.b64decode(img_b64)
    elif img_url:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c2:
                imgr = await c2.get(img_url)
                imgr.raise_for_status()
                img_bytes = imgr.content
        except Exception as e:
            log.warning("[VISION-BOARD] url download failed: %s", e)
            return {
                "status": "api_error",
                "path": None,
                "filename": None,
                "error": f"url download: {e}",
            }

    if not img_bytes:
        return {
            "status": "api_error",
            "path": None,
            "filename": None,
            "error": "no image bytes returned",
        }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{vision.vision_id}-{ts}.png"
    out_path = _board_dir() / filename
    out_path.write_bytes(img_bytes)

    # Track cost (rough: $0.04 per 1024x1024 high-quality gpt-image-1)
    cost_usd = 0.04 if _QUALITY == "high" else 0.02
    try:
        from ..cost_tracker import record_cost

        await record_cost(
            "openai",
            cost_usd,
            "vision_board",
            f"vision board {vision.vision_id} -> {filename}",
            model="gpt-image-1",
            quality=_QUALITY,
        )
    except Exception:
        pass

    log.info("[VISION-BOARD] generated %s (%d bytes)", filename, len(img_bytes))
    return {
        "status": "ok",
        "path": str(out_path),
        "filename": filename,
        "model": _MODEL,
        "size": _SIZE,
        "cost_usd": cost_usd,
        "error": None,
        "prompt_used": prompt,
    }


def latest_board_for_vision(vision_id: str) -> Optional[Path]:
    """Return the most recent board file for a given vision_id, or None."""
    matches = sorted(
        _board_dir().glob(f"{vision_id}-*.png"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return matches[0] if matches else None


def list_boards(vision_id: Optional[str] = None) -> list[dict]:
    """List all generated boards (newest first)."""
    pattern = f"{vision_id}-*.png" if vision_id else "*.png"
    out = []
    for p in sorted(_board_dir().glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
        out.append(
            {
                "filename": p.name,
                "size_bytes": p.stat().st_size,
                "modified_at": datetime.fromtimestamp(
                    p.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    return out
