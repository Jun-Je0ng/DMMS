import json
import os
import sys

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")

# ------------------------------------------------------------------
# Operating-system profiles
# ------------------------------------------------------------------
# Serial port names and camera indices differ between machines
# (COM5 on a Windows laptop, /dev/ttyUSB0 on a Raspberry Pi), so each MUL
# keeps one set of hardware values per profile under "os_hardware".
# "os_profile" in settings.json picks which one is live:
#   "auto"    -> windows on Windows, linux everywhere else (default)
#   "windows" -> force the Windows values
#   "linux"   -> force the Raspberry Pi / Linux values
OS_PROFILES = {
    "windows": "Windows (laptop)",
    "linux": "Raspberry Pi / Linux",
}

# Keys that live inside each profile's block.
OS_HARDWARE_KEYS = (
    "laser_serial_port",
    "barcode_serial_port",
    "camera_device_index",
)


def detect_os_profile():
    return "windows" if sys.platform.startswith("win") else "linux"


class Settings:
    def __init__(self):
        self._load()

    def _load(self):
        with open(SETTINGS_PATH, "r") as f:
            self.data = json.load(f)

    def reload(self):
        """Re-read settings.json (picks up changes saved by web.py)."""
        self._load()

    def save(self):
        with open(SETTINGS_PATH, "w") as f:
            json.dump(self.data, f, indent=4)

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value
        self.save()

    # --------------------------------------------------------------
    # OS profile helpers
    # --------------------------------------------------------------

    def os_choice(self):
        """What is stored: "auto", "windows" or "linux"."""
        choice = self.data.get("os_profile", "auto")
        return choice if choice in OS_PROFILES else "auto"

    def active_os_profile(self):
        """The profile actually in use ("windows" or "linux")."""
        choice = self.os_choice()
        return detect_os_profile() if choice == "auto" else choice

    def set_os_choice(self, choice):
        if choice != "auto" and choice not in OS_PROFILES:
            raise ValueError(f"Unknown OS profile: {choice}")
        self.data["os_profile"] = choice
        self.save()

    def mul_cfg(self, mul_id=None):
        """
        Config for a MUL with the active OS profile's hardware values
        merged over the shared ones (resolution, laser timeout...).
        Returns a copy; use set_mul_hardware() to change anything.
        Old-style files with the hardware keys at the top level of the
        MUL still work as a fallback.
        """
        if mul_id is None:
            mul_id = self.data.get("active_mul")

        base = self.data["mul_settings"][str(mul_id)]
        cfg = {k: v for k, v in base.items() if k != "os_hardware"}
        cfg.update(base.get("os_hardware", {}).get(self.active_os_profile(), {}))
        return cfg

    def set_mul_hardware(self, mul_id, **values):
        """Write OS-specific hardware values into the active profile."""
        block = self.data["mul_settings"][str(mul_id)].setdefault(
            "os_hardware", {}
        ).setdefault(self.active_os_profile(), {})

        for key, value in values.items():
            if key not in OS_HARDWARE_KEYS:
                raise KeyError(f"{key} is not an OS-specific setting")
            block[key] = value


settings = Settings()
