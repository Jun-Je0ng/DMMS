#!/bin/bash
# Launcher used by the DMMS desktop shortcut.
cd "$(dirname "$0")"
DMMS_DIR="$(pwd -P)"

# ---- Stop any DMMS that's already running ---------------------------
# Only kills run.py / web.py / app.py started from this folder, so other
# Python projects with an app.py are left alone.
for pid in $(pgrep -f 'python3? .*(run|web|app)\.py'); do
    if [ "$(readlink "/proc/$pid/cwd")" = "$DMMS_DIR" ]; then
        echo "Stopping old DMMS process $pid"
        kill "$pid" 2>/dev/null
    fi
done

# The MUL board / Needs Attention windows from a previous run.
pkill -f 'dmms-browser' 2>/dev/null

# Give them a few seconds to exit, then force anything still holding
# the port.
for _ in $(seq 10); do
    ss -ltn 'sport = :5000' | grep -q LISTEN || break
    sleep 0.5
done
fuser -k 5000/tcp >/dev/null 2>&1

python3 run.py
echo
read -p "DMMS stopped - press Enter to close this window."
