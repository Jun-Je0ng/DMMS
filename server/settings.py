"""
settings.py — merges config.py's hardcoded defaults with gui/settings.json
overrides saved from the Settings page (gui/settings.html), so changing the
camera index, serial port, or timing values from the GUI doesn't require
editing code.

gui/settings.json — written by run_gui.py's POST /api/settings — wins for
any key it contains. A missing or unreadable file, or a key it doesn't
set, falls back to config.py silently, so an installation that has never
opened the Settings page behaves exactly as it did before this existed.

Usage (run.py, sim_runner.py):
    import config
    import settings
    effective = settings.load(config)
    ...
    trigger_source = SerialTriggerSource(
        port=effective.SERIAL_PORT, baud=effective.SERIAL_BAUD,
        token=effective.TRIGGER_TOKEN,
    )
"""

import json
from pathlib import Path

# gui/settings.json key -> config.py attribute name. Both run_gui.py (which
# reads/writes the JSON) and this module need to agree on these names.
KEYS = {
    "cameraIndex":  "CAMERA_INDEX",
    "serialPort":   "SERIAL_PORT",
    "serialBaud":   "SERIAL_BAUD",
    "triggerToken": "TRIGGER_TOKEN",
    "photoDelay":   "PHOTO_DELAY",
    "pairWindow":   "PAIR_WINDOW",
    "loopWindow":   "LOOP_WINDOW",
}


def settings_path() -> Path:
    return Path(__file__).resolve().parent.parent / "gui" / "settings.json"


def _read_saved() -> dict:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


class Effective:
    """Plain attribute bag — same attribute names as config.py, with any
    gui/settings.json overrides already applied."""


def load(config_module) -> Effective:
    saved = _read_saved()
    eff = Effective()
    for json_key, attr in KEYS.items():
        value = getattr(config_module, attr, None)
        if json_key in saved and saved[json_key] not in (None, ""):
            value = saved[json_key]
        setattr(eff, attr, value)
    return eff
