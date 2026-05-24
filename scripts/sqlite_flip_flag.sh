#!/usr/bin/env bash
#
# sqlite_flip_flag.sh — recipe printer for promoting a SQLite double-write
# from write-only mirror to read-from-SQLite.
#
# W8-A7 (2026-05-24): This script DOES NOT mutate .env, kickstart the
# Brain, or touch the DB. It (a) runs the burn-in verifier to confirm
# zero divergence between the JSONL/JSON source and the SQLite mirror,
# then (b) prints the exact lines NATRIX must execute to flip the flag.
#
# NATRIX runs the printed commands. Hands-off-config doctrine: the
# script is a safety check + a recipe, not a self-driving deploy tool.
#
# Usage:
#     scripts/sqlite_flip_flag.sh --table cost_ledger
#     scripts/sqlite_flip_flag.sh --table mandates
#     scripts/sqlite_flip_flag.sh --table units_index
#
# Exit codes:
#   0 — verifier matched, recipe printed
#   1 — verifier reported divergence (recipe NOT printed)
#   2 — bad args or environment problem

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTHON="${PYTHON:-/opt/homebrew/bin/python3}"
VERIFIER="$SCRIPT_DIR/sqlite_burn_in_verify.py"

# ── Args ─────────────────────────────────────────────────────────────

TABLE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --table)
            TABLE="${2:-}"
            shift 2
            ;;
        --help|-h)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *)
            echo "ERROR: unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

if [[ -z "$TABLE" ]]; then
    echo "ERROR: --table is required (cost_ledger | mandates | units_index)" >&2
    exit 2
fi

case "$TABLE" in
    cost_ledger)
        FLAG_WRITE_VAR="NCL_COST_LEDGER_SQLITE"
        FLAG_READ_VAR="NCL_COST_LEDGER_READ"
        ;;
    mandates)
        FLAG_WRITE_VAR="NCL_MANDATES_SQLITE"
        FLAG_READ_VAR="NCL_MANDATES_READ"
        ;;
    units_index)
        FLAG_WRITE_VAR="NCL_UNITS_INDEX_SQLITE"
        FLAG_READ_VAR="NCL_UNITS_INDEX_READ"
        ;;
    *)
        echo "ERROR: unknown table $TABLE (allowed: cost_ledger, mandates, units_index)" >&2
        exit 2
        ;;
esac

# ── Sanity checks ────────────────────────────────────────────────────

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: python at $PYTHON not executable" >&2
    exit 2
fi

if [[ ! -f "$VERIFIER" ]]; then
    echo "ERROR: verifier not found at $VERIFIER" >&2
    exit 2
fi

# Sanity: ensure the write-side flag is currently ON in .env, otherwise
# the SQLite mirror cannot be expected to match the JSONL source.
if [[ -f "$REPO_ROOT/.env" ]]; then
    if ! grep -E "^${FLAG_WRITE_VAR}=true" "$REPO_ROOT/.env" >/dev/null 2>&1; then
        echo "WARN: ${FLAG_WRITE_VAR}=true is NOT currently set in .env." >&2
        echo "      Burn-in window has not started — the SQLite mirror is stale." >&2
        echo "      Add ${FLAG_WRITE_VAR}=true to .env first, kickstart the Brain," >&2
        echo "      let it run for a 1-2 week burn-in, then re-run this script." >&2
        echo "" >&2
    fi
else
    echo "WARN: $REPO_ROOT/.env not found — cannot pre-check write-side flag" >&2
fi

# ── Step 1: verify ────────────────────────────────────────────────────

echo "==> Verifying JSONL ↔ SQLite parity for table '$TABLE'..."
cd "$REPO_ROOT"
if ! "$PYTHON" "$VERIFIER" --table "$TABLE"; then
    echo "" >&2
    echo "ABORT: verifier reported divergence between JSONL and SQLite." >&2
    echo "       Do NOT flip the read flag until parity is restored." >&2
    echo "       Investigate divergence above, fix root cause, re-run." >&2
    exit 1
fi

# ── Step 2: recipe ────────────────────────────────────────────────────

cat <<EOF

==> Verification PASSED.

Recipe for NATRIX to flip the read flag (run these manually):

    echo '${FLAG_READ_VAR}=true' >> ~/dev/NCL/.env
    launchctl kickstart -k gui/\$(id -u)/com.resonanceenergy.ncl-brain

After kickstart, tail the brain logs and watch for:
    [SQLITE]   Store initialized at .../data/persistence/ncl.db
    [${TABLE}] read path: SQLite (flag flipped)

Rollback (if any consumer misbehaves):
    sed -i.bak '/^${FLAG_READ_VAR}=true/d' ~/dev/NCL/.env
    launchctl kickstart -k gui/\$(id -u)/com.resonanceenergy.ncl-brain

Note: ${FLAG_WRITE_VAR}=true should stay set during and after the flip.
The double-write is the safety net during the read-side soak.

EOF

exit 0
