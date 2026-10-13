#!/bin/bash
# Launcher used by the DMMS desktop shortcut. run.py stops any DMMS
# that's already running before it starts.
cd "$(dirname "$0")"
python3 run.py
echo
read -p "DMMS stopped - press Enter to close this window."
