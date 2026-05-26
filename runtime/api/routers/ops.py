"""/system/ops/* endpoints — Wave 14G (2026-05-25).

Consumed by the NCL Desktop menu-bar app + the future OpsView window.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from ..deps import verify_strike_token_dep

log = logging.getLogger(__name__)

router = APIRouter(tags=["ops"])


@router.get("/system/ops/snapshot")
async def ops_snapshot(_: None = Depends(verify_strike_token_dep)) -> dict:
    """Most recent ops snapshot. Empty if sampler hasn't ticked yet."""
    from ...system_monitor import get_sampler

    snap = get_sampler().latest()
    if snap is None:
        return {"status": "warming", "message": "Sampler has not produced a snapshot yet"}
    return {"status": "ok", "snapshot": snap.model_dump(mode="json")}


@router.get("/system/ops/history")
async def ops_history(
    minutes: int = Query(default=10, ge=1, le=60),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Trailing window of snapshots (every 5s)."""
    from ...system_monitor import get_sampler

    snaps = get_sampler().history(minutes=minutes)
    return {
        "status": "ok",
        "minutes": minutes,
        "count": len(snaps),
        "snapshots": [s.model_dump(mode="json") for s in snaps],
    }


@router.websocket("/system/ops/stream")
async def ops_stream(websocket: WebSocket) -> None:
    """Live snapshot stream over WebSocket. One message every ~5s.

    Auth: the desktop sends a `?token=...` query param. We verify against
    STRIKE_AUTH_TOKEN before accepting the upgrade so unauthenticated
    streams can't tail the brain.
    """
    import os

    token = websocket.query_params.get("token", "")
    expected = os.getenv("STRIKE_AUTH_TOKEN", "")
    if not expected or token != expected:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    from ...system_monitor import get_sampler

    sampler = get_sampler()
    q = sampler.subscribe()
    # Send current snapshot immediately so the client doesn't sit blank
    cur = sampler.latest()
    if cur is not None:
        try:
            await websocket.send_json(cur.model_dump(mode="json"))
        except Exception:
            pass
    try:
        while True:
            try:
                snap = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Keepalive ping so the connection survives idle periods
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                continue
            try:
                await websocket.send_json(snap.model_dump(mode="json"))
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.debug("[ops-stream] disconnect: %s", e)
    finally:
        sampler.unsubscribe(q)
