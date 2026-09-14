# config.py — hardware settings for THIS installation.
# Edit here once; both run.py and sim_runner.py read from this file.
#
# These are just the DEFAULTS. The Settings page (open gui/settings.html,
# or the "Settings" button on the main board) writes overrides to
# gui/settings.json, which wins over whatever's below without editing this
# file — see server/settings.py. Editing here still works fine if you'd
# rather not use the GUI; it's only ever the fallback when settings.json
# has nothing to say about a given value.
# ─────────────────────────────────────────────────────────────────────────────

# Serial port the Arduino is connected to.
# Windows:  "COM3", "COM4", …
# Linux:    "/dev/ttyUSB0", "/dev/ttyACM0", …
# macOS:    "/dev/cu.usbserial-…"
SERIAL_PORT   = "COM3"
SERIAL_BAUD   = 9600

# String the Arduino sketch prints each time the ultrasonic sensor fires.
# Must match the Serial.print() call in hardware/baggage_counter_HYSRF05.ino.
TRIGGER_TOKEN = "Baggage passed"

# Camera device index (0 = first/only webcam, 1 = second, …).
# Unsure which index is which camera? Open the Settings page and use
# "Detect Cameras" — it probes each index and shows a live preview so you
# can tell them apart, then saves your pick without editing this file.
CAMERA_INDEX  = 0

# Seconds to wait after the sensor trigger before taking the photo.
# Covers belt travel time between the sensor and the camera.
PHOTO_DELAY   = 0.5

# Pairing window: a scan and a trigger must be within this many seconds of
# each other to be considered the same bag.
PAIR_WINDOW   = 4.0

# Loop window: how long a tag stays "active" for duplicate detection.
# Roughly one MUL loop (~3 minutes per the site visit notes).
LOOP_WINDOW   = 200.0
