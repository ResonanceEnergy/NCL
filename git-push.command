#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
git status --short
echo ""
read -p "Push current branch to origin? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
exec git push origin HEAD
