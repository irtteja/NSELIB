#!/usr/bin/env bash
# Sync the nselib package into equity-research-agent's vendor directory.
# Assumes both repos are siblings: ../equity-research-agent/
# Run directly or via the NSELIB post-commit hook.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO_ROOT/nselib"

# Discover the vendor target — sibling repo by default, overridable via env.
VENDOR="${VENDOR_PATH:-$REPO_ROOT/../equity-research-agent/vendor/nselib}"

if [ ! -d "$VENDOR" ]; then
    echo "[sync_vendor] target not found: $VENDOR — skipping" >&2
    exit 0
fi

# Sync .py and .json files; skip __pycache__ and .pyc
rsync -a --delete \
    --include="*.py" \
    --include="*.json" \
    --include="modules/" \
    --exclude="__pycache__/" \
    --exclude="*.pyc" \
    --filter="- __pycache__/" \
    "$SRC/" "$VENDOR/"

echo "[sync_vendor] synced nselib → $VENDOR"
