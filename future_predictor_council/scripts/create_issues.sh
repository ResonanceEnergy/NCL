#!/usr/bin/env bash
# create_issues.sh — Create GitHub issues from backlog/issues.yaml
# Requires: gh (GitHub CLI), yq (YAML processor)
# Usage: ./create_issues.sh [--dry-run]
set -euo pipefail

REPO="ResonanceEnergy/NCL"
ISSUES_FILE="../backlog/issues.yaml"
DRY_RUN="${1:-}"

if ! command -v gh &> /dev/null; then
    echo "ERROR: GitHub CLI (gh) not found. Install from https://cli.github.com/"
    exit 1
fi

if ! command -v yq &> /dev/null; then
    echo "ERROR: yq not found. Install: brew install yq / choco install yq"
    exit 1
fi

COUNT=$(yq '.issues | length' "$ISSUES_FILE")
echo "Found $COUNT issues in $ISSUES_FILE"

for i in $(seq 0 $(( COUNT - 1 ))); do
    TITLE=$(yq ".issues[$i].title" "$ISSUES_FILE")
    EPIC=$(yq ".issues[$i].epic" "$ISSUES_FILE")
    LABELS=$(yq ".issues[$i].labels | join(\",\")" "$ISSUES_FILE")
    ASSIGNEE=$(yq ".issues[$i].assignee" "$ISSUES_FILE")

    BODY="**Epic:** $EPIC
**Agent:** $ASSIGNEE
Generated from future_predictor_council/backlog/issues.yaml"

    if [ "$DRY_RUN" = "--dry-run" ]; then
        echo "[DRY RUN] Would create: $TITLE (labels: $LABELS)"
    else
        gh issue create \
            --repo "$REPO" \
            --title "$TITLE" \
            --body "$BODY" \
            --label "$LABELS" \
            || echo "WARNING: Failed to create issue: $TITLE"
        sleep 1  # Rate limit courtesy
    fi
done

echo "Done. Created $COUNT issues."
