#!/bin/bash
# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

# Launch the PufferDrive interactive demo (Reflex app). See README.md for setup.
#
# Environment variables (all optional):
#   DRIVE_BINARIES_DATA_ROOT  map binaries root, containing training/ validation/ testing/
#                             (default: resources/drive/binaries — the symlink created below)
#   DRIVE_CONFIG_DIR          directory scanned for demo profile *.ini (default: config)
#   DRIVE_SCENARIOS_DIR       directory for saved scenario JSON (default: scenarios)
#   HOST_IP                   host the browser reaches the backend on (default: localhost)
#   VIRTUAL_ENV               an already-activated venv is used as-is, else <repo>/.venv

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$DEMO_DIR")"

# Scan for conflicting Reflex instances before starting
PORTS=(3000 8000)
all_pids=()

for port in "${PORTS[@]}"; do
    mapfile -t pids < <(lsof -ti TCP:"$port" -sTCP:LISTEN 2>/dev/null)
    all_pids+=("${pids[@]}")
done
mapfile -t reflex_pids < <(pgrep -f "reflex run" 2>/dev/null)
all_pids+=("${reflex_pids[@]}")
unique_pids=($(printf '%s\n' "${all_pids[@]}" | sort -un))

if [[ ${#unique_pids[@]} -gt 0 ]]; then
    echo "Conflicting Reflex instances found:"
    for pid in "${unique_pids[@]}"; do
        args=$(ps -p "$pid" -o args= 2>/dev/null)
        echo "  PID $pid  $args"
    done
    echo ""
    read -r -p "Kill them and continue? [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]] || exit 1
    kill "${unique_pids[@]}" 2>/dev/null
    # Give them a moment to exit, then force-kill any survivors.
    sleep 2
    for pid in "${unique_pids[@]}"; do
        kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
    done
    echo "Killed: ${unique_pids[*]}"
    echo ""
fi

cd "$REPO_DIR" || exit 1

# Use the venv the caller already activated, otherwise the repo's own .venv.
if [[ -z "$VIRTUAL_ENV" && -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

# Build the C extension the demo imports (pufferlib.ocean.drive). Cheap when up to date.
python setup.py build_ext --inplace --force || exit 1

cd "$DEMO_DIR" || exit 1

# Relative resource paths in the demo inis (resources/drive/...) resolve from this
# directory, so link the repo's resources/ in. Relative link — works on any checkout.
[[ -e resources ]] || ln -sfn ../pufferlib/resources resources

# Map binaries usually live outside the repo. Point the viewer at them by exporting
# DRIVE_BINARIES_DATA_ROOT=/path/to/binaries before running this script.
echo "Map binaries: ${DRIVE_BINARIES_DATA_ROOT:-resources/drive/binaries (default)}"

# HOST_IP=localhost  → access via SSH tunnel (default, works from any network)
# HOST_IP=<lan-ip>   → access directly on the LAN
export HOST_IP=${HOST_IP:-localhost}
echo "Accessible at http://$HOST_IP:3000"

# The header "Reset" button restarts the whole app (fresh Python process) without
# recompiling the C extension, which was already built once above. It touches this
# sentinel and SIGINTs reflex; we watch for the sentinel and relaunch when we see it.
export PD_RESTART_SENTINEL="$DEMO_DIR/.pd_restart"
rm -f "$PD_RESTART_SENTINEL"

while true; do
    echo "Launching app"
    reflex run --backend-host 0.0.0.0
    if [[ -f "$PD_RESTART_SENTINEL" ]]; then
        rm -f "$PD_RESTART_SENTINEL"
        echo ""
        echo "↻ Restart requested — relaunching (skipping C build)…"
        # Free the ports in case reflex left a lingering child behind.
        for port in "${PORTS[@]}"; do
            mapfile -t leftover < <(lsof -ti TCP:"$port" -sTCP:LISTEN 2>/dev/null)
            [[ ${#leftover[@]} -gt 0 ]] && kill -9 "${leftover[@]}" 2>/dev/null
        done
        echo ""
        continue
    fi
    break
done
