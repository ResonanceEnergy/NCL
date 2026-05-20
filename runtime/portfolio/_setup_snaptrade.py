#!/usr/bin/env python3
"""
SnapTrade User Registration & Brokerage Connection Setup
=========================================================

Two-step process:
  1. Register a user with SnapTrade (gets USER_ID and USER_SECRET)
  2. Generate a redirect URL to link a brokerage account (Wealthsimple)

Usage:
  python _setup_snaptrade.py --register          # Step 1: create user
  python _setup_snaptrade.py --connect            # Step 2: link brokerage
  python _setup_snaptrade.py --verify             # Check connection status
  python _setup_snaptrade.py --delete-user        # Remove user (cleanup)

Requires SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY in .env
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Load .env from NCL root
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)

try:
    from snaptrade_client.client import SnapTrade
except ImportError:
    print("ERROR: snaptrade-python-sdk not installed")
    print("  pip install snaptrade-python-sdk")
    sys.exit(1)


def get_client():
    client_id = os.getenv("SNAPTRADE_CLIENT_ID", "")
    consumer_key = os.getenv("SNAPTRADE_CONSUMER_KEY", "")
    if not client_id or not consumer_key:
        print("ERROR: SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY must be set in .env")
        sys.exit(1)
    return SnapTrade(consumer_key=consumer_key, client_id=client_id), client_id


def register_user():
    """Register a new SnapTrade user and print credentials."""
    snap, client_id = get_client()

    user_id = f"ncl-{uuid.uuid4().hex[:12]}"
    print(f"Registering SnapTrade user: {user_id}")

    try:
        response = snap.authentication.register_snap_trade_user(
            user_id=user_id,
        )
        print(f"\n✓ User registered successfully!")
        print(f"\nAdd these to your .env file ({_ENV_PATH}):")
        print(f"  SNAPTRADE_USER_ID={response.body['userId']}")
        print(f"  SNAPTRADE_USER_SECRET={response.body['userSecret']}")
        print(f"\nNext step: run with --connect to link your Wealthsimple account")
        return response.body
    except Exception as e:
        print(f"ERROR registering user: {e}")
        sys.exit(1)


def connect_brokerage():
    """Generate a redirect URL to link a brokerage account."""
    snap, client_id = get_client()

    user_id = os.getenv("SNAPTRADE_USER_ID", "")
    user_secret = os.getenv("SNAPTRADE_USER_SECRET", "")

    if not user_id or not user_secret:
        print("ERROR: SNAPTRADE_USER_ID and SNAPTRADE_USER_SECRET must be set in .env")
        print("  Run --register first")
        sys.exit(1)

    print(f"Generating connection link for user: {user_id}")

    try:
        response = snap.authentication.login_snap_trade_user(
            user_id=user_id,
            user_secret=user_secret,
        )
        redirect_url = response.body.get("redirectURI") or response.body.get("loginLink")
        print(f"\n✓ Open this URL in your browser to connect your brokerage:")
        print(f"\n  {redirect_url}\n")
        print(f"After connecting, run --verify to confirm.")
        return redirect_url
    except Exception as e:
        print(f"ERROR generating connection link: {e}")
        sys.exit(1)


def verify_connection():
    """Check if brokerage accounts are connected."""
    snap, client_id = get_client()

    user_id = os.getenv("SNAPTRADE_USER_ID", "")
    user_secret = os.getenv("SNAPTRADE_USER_SECRET", "")

    if not user_id or not user_secret:
        print("ERROR: SNAPTRADE_USER_ID and SNAPTRADE_USER_SECRET not set")
        sys.exit(1)

    print(f"Checking connections for user: {user_id}")

    try:
        accounts = snap.account_information.get_all_user_account_balances(
            user_id=user_id,
            user_secret=user_secret,
        )
        if accounts.body:
            print(f"\n✓ {len(accounts.body)} account(s) connected:")
            for acct in accounts.body:
                print(f"  • {json.dumps(acct, indent=2, default=str)}")
        else:
            print("\n⚠ No accounts connected yet. Run --connect to link a brokerage.")
    except Exception as e:
        print(f"ERROR verifying: {e}")
        sys.exit(1)


def delete_user():
    """Delete the SnapTrade user (cleanup)."""
    snap, client_id = get_client()

    user_id = os.getenv("SNAPTRADE_USER_ID", "")

    if not user_id:
        print("ERROR: SNAPTRADE_USER_ID not set")
        sys.exit(1)

    confirm = input(f"Delete user {user_id}? This removes all linked accounts. [y/N] ")
    if confirm.lower() != "y":
        print("Cancelled.")
        return

    try:
        snap.authentication.delete_snap_trade_user(user_id=user_id)
        print(f"✓ User {user_id} deleted. Remove SNAPTRADE_USER_ID and SNAPTRADE_USER_SECRET from .env.")
    except Exception as e:
        print(f"ERROR deleting user: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SnapTrade setup for NCL Portfolio")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--register", action="store_true", help="Register a new SnapTrade user")
    group.add_argument("--connect", action="store_true", help="Generate link to connect brokerage")
    group.add_argument("--verify", action="store_true", help="Verify connected accounts")
    group.add_argument("--delete-user", action="store_true", help="Delete SnapTrade user")

    args = parser.parse_args()

    if args.register:
        register_user()
    elif args.connect:
        connect_brokerage()
    elif args.verify:
        verify_connection()
    elif args.delete_user:
        delete_user()
