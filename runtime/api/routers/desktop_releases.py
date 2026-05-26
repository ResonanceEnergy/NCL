"""Wave 14G Phase 7 — serves Sparkle appcast + .dmg downloads.

The make_release.sh script writes to ~/dev/NCL/data/desktop_releases/.
This router exposes two endpoints — both unauthenticated since Sparkle
runs before the user has any credentials:
  GET /desktop/appcast.xml          → appcast feed
  GET /desktop/dl/{filename}        → DMG download (whitelisted to *.dmg)
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

router = APIRouter(prefix="/desktop", tags=["desktop"])

# Base dir matches what make_release.sh writes to. Override via env if you
# relocate the release artifacts.
_BASE = Path(os.environ.get(
    "NCL_DESKTOP_RELEASES",
    str(Path.home() / "dev" / "NCL" / "data" / "desktop_releases"),
))


@router.get("/appcast.xml")
async def appcast() -> Response:
    path = _BASE / "appcast.xml"
    if not path.exists():
        # Serve a minimal empty feed so Sparkle's first run doesn't error;
        # logs the absence so we know to publish a release.
        empty = (
            '<?xml version="1.0" standalone="yes"?>\n'
            '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" '
            'version="2.0"><channel><title>NCL Desktop</title>'
            '<description>No releases yet — run scripts/make_release.sh</description>'
            '</channel></rss>'
        )
        return Response(content=empty, media_type="application/rss+xml")
    return FileResponse(str(path), media_type="application/rss+xml")


@router.get("/dl/{filename}")
async def dl(filename: str):
    # Whitelist: only files matching NCLDesktop-*.dmg are downloadable.
    if not (filename.startswith("NCLDesktop-") and filename.endswith(".dmg")):
        raise HTTPException(status_code=403, detail="forbidden filename")
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    path = _BASE / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        str(path),
        media_type="application/octet-stream",
        filename=filename,
    )
