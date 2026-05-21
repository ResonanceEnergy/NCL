"""
X (Twitter) OAuth 2.0 PKCE Authentication

Handles the OAuth 2.0 Authorization Code Flow with PKCE for
accessing user-context endpoints (liked tweets, bookmarks, etc.).

Flow:
1. Generate authorization URL with PKCE challenge
2. User opens URL in browser and authorizes
3. Callback captures the authorization code
4. Exchange code for access + refresh tokens
5. Tokens stored in .env or keychain for reuse
6. Auto-refresh when access token expires

Usage via Brain API:
  POST /x/oauth/authorize → returns auth URL
  GET  /x/oauth/callback?code=...&state=... → exchanges code for tokens
  POST /x/oauth/refresh → refreshes access token
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.councils.xai.x_oauth")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
TOKEN_FILE = NCL_BASE / "data" / "x_oauth_tokens.json"

# X OAuth 2.0 config — set these in .env
def _get_client_id() -> str:
    return os.getenv("X_OAUTH_CLIENT_ID", "")

def _get_client_secret() -> str:
    return os.getenv("X_OAUTH_CLIENT_SECRET", "")

# Callback URL — must match what's registered in the X Developer Portal
REDIRECT_URI = os.getenv("X_OAUTH_REDIRECT_URI", "http://127.0.0.1:8800/x/oauth/callback")

# Scopes needed for liked tweets + user info
SCOPES = ["tweet.read", "users.read", "like.read", "bookmark.read", "offline.access"]

# PKCE state — stored in memory for the duration of the auth flow.
# NOTE: module-level global dict — only supports a single concurrent auth flow.
# If multiple users need simultaneous OAuth, refactor to per-session state (e.g. keyed by state param).
_auth_state: dict = {}


def generate_pkce_challenge() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def get_authorization_url() -> dict:
    """
    Generate the OAuth 2.0 authorization URL.

    Returns dict with 'url' and 'state' for the caller to redirect to.
    """
    global _auth_state

    client_id = _get_client_id()
    if not client_id:
        return {"error": "X_OAUTH_CLIENT_ID not set in .env"}

    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_challenge()

    # Store state for verification on callback
    _auth_state = {
        "state": state,
        "code_verifier": code_verifier,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    scope_str = " ".join(SCOPES)
    auth_url = (
        "https://twitter.com/i/oauth2/authorize"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={scope_str}"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )

    log.info(f"[X-OAuth] Authorization URL generated (state: {state[:8]}...)")
    return {
        "url": auth_url,
        "state": state,
        "scopes": SCOPES,
    }


async def exchange_code(code: str, state: str) -> dict:
    """
    Exchange authorization code for access + refresh tokens.

    Called from the OAuth callback endpoint.
    """
    import httpx

    global _auth_state

    # Verify state
    if not _auth_state or _auth_state.get("state") != state:
        log.error("[X-OAuth] State mismatch — possible CSRF attack")
        return {"error": "State mismatch"}

    client_id = _get_client_id()
    client_secret = _get_client_secret()
    code_verifier = _auth_state.get("code_verifier", "")

    if not client_id:
        return {"error": "X_OAUTH_CLIENT_ID not configured"}

    # Exchange code for tokens
    token_url = "https://api.twitter.com/2/oauth2/token"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    }

    # Use Basic auth if client_secret is set (confidential client)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    auth = None
    if client_secret:
        auth = (client_id, client_secret)
    else:
        data["client_id"] = client_id

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                token_url,
                data=data,
                headers=headers,
                auth=auth,
            )
            resp.raise_for_status()
            token_data = resp.json()

        # Save tokens
        tokens = {
            "access_token": token_data.get("access_token", ""),
            "refresh_token": token_data.get("refresh_token", ""),
            "token_type": token_data.get("token_type", "bearer"),
            "expires_in": token_data.get("expires_in", 7200),
            "scope": token_data.get("scope", ""),
            "obtained_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_tokens(tokens)

        # Set access token in environment for immediate use
        os.environ["X_USER_ACCESS_TOKEN"] = tokens["access_token"]

        log.info("[X-OAuth] Token exchange successful — access token saved")
        _auth_state = {}  # Clear auth state

        return {
            "status": "authenticated",
            "scope": tokens["scope"],
            "expires_in": tokens["expires_in"],
        }

    except httpx.HTTPStatusError as e:
        error_body = e.response.text[:200]
        log.error(f"[X-OAuth] Token exchange failed: {e.response.status_code} — {error_body}")
        return {"error": f"Token exchange failed: {e.response.status_code}", "detail": error_body}
    except Exception as e:
        log.error(f"[X-OAuth] Token exchange error: {e}", exc_info=True)
        return {"error": str(e)}


async def refresh_access_token() -> dict:
    """Refresh the access token using the stored refresh token."""
    import httpx

    tokens = _load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        return {"error": "No refresh token available — re-authenticate"}

    client_id = _get_client_id()
    client_secret = _get_client_secret()

    data = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    auth = None
    if client_secret:
        auth = (client_id, client_secret)
    else:
        data["client_id"] = client_id

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.twitter.com/2/oauth2/token",
                data=data,
                headers=headers,
                auth=auth,
            )
            resp.raise_for_status()
            token_data = resp.json()

        tokens.update({
            "access_token": token_data.get("access_token", ""),
            "refresh_token": token_data.get("refresh_token", tokens.get("refresh_token", "")),
            "expires_in": token_data.get("expires_in", 7200),
            "obtained_at": datetime.now(timezone.utc).isoformat(),
        })
        _save_tokens(tokens)
        os.environ["X_USER_ACCESS_TOKEN"] = tokens["access_token"]

        log.info("[X-OAuth] Token refreshed successfully")
        return {"status": "refreshed", "expires_in": tokens["expires_in"]}

    except httpx.HTTPStatusError as e:
        log.error(f"[X-OAuth] Token refresh failed: {e.response.status_code}")
        return {"error": f"Refresh failed: {e.response.status_code}"}
    except Exception as e:
        log.error(f"[X-OAuth] Token refresh error: {e}")
        return {"error": str(e)}


def load_access_token() -> Optional[str]:
    """Load saved access token and set in environment. Returns token or None."""
    tokens = _load_tokens()
    if tokens and tokens.get("access_token"):
        os.environ["X_USER_ACCESS_TOKEN"] = tokens["access_token"]
        return tokens["access_token"]
    return None


def _save_tokens(tokens: dict) -> None:
    """Save tokens to disk.

    # SECURITY: tokens stored unencrypted — migrate to Keychain (see keychain_get in config.py)
    """
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    # Restrict permissions
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError as e:
        log.warning(f"[X-OAuth] Failed to set token file permissions: {e}")


def _load_tokens() -> Optional[dict]:
    """Load tokens from disk."""
    if not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text())
    except Exception as e:
        log.warning(f"[X-OAuth] Failed to load tokens: {e}")
        return None


def get_auth_status() -> dict:
    """Check current OAuth authentication status."""
    tokens = _load_tokens()
    if not tokens:
        return {"authenticated": False, "reason": "No tokens saved"}

    has_access = bool(tokens.get("access_token"))
    has_refresh = bool(tokens.get("refresh_token"))
    obtained_at = tokens.get("obtained_at", "unknown")

    return {
        "authenticated": has_access,
        "has_refresh_token": has_refresh,
        "obtained_at": obtained_at,
        "scopes": tokens.get("scope", ""),
        "client_id_set": bool(_get_client_id()),
    }
