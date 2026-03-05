#!/usr/bin/env bash
set -euo pipefail

echo "[NCL] Bootstrapping local folders under ~/NCL ..."
mkdir -p ~/NCL/{data,agents,missions,packs,policies,dist,audit}
mkdir -p ~/NCL/data/{event_log,derived,quarantine,indexes}
mkdir -p ~/NCL/packs/{candidate,shadow,active,archive}
mkdir -p ~/NCL/dist/{reports,exports}

echo "[NCL] Done. Canonical root: ~/NCL"

echo "[NCL] NOTE: This runtime is local-only. No cloud paths configured."
