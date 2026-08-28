# DMMS

Baggage-identification system for a Qantas airport MUL (Make-Up Line) conveyor.
Goal: reduce misrouted baggage and speed up loading baggage into cans/trucks by
scanning tags and camera-matching bags as they enter the line.

## Workflow (from site visit)

1. Baggage enters the MUL. A laser/ultrasonic sensor detects it and triggers the loop.
2. An RGB camera snapshot is taken at the moment of detection.
3. A fixed barcode scanner reads the tag on the bag (may fail to read).
4. Snapshot + decoded tag data (flight number, terminal, etc.) — or snapshot
   alone if the barcode couldn't be read — is published as an event.
5. Sensor detection + barcode scan + camera photo are all backend logic (not
   shown in the GUI as separate panels) that resolve to one event: a bag,
   its photo, and — once the barcode subsystem is merged in — which can it
   belongs to.
6. The GUI (this repo's `gui/`) is a routing board: as each bag's photo
   arrives, it's placed into the quadrant for its assigned can. A ground
   handler glances at a quadrant to see what's waiting for that can, and
   double-clicks a photo once they've physically loaded that bag, clearing it.
7. A bag with no confident can match (no scan, a duplicate read, an unpaired
   scan, more than one possible match) goes to a separate "Needs Attention"
   tray instead of a guessed quadrant — that's the manual-scan path from the
   original site-visit workflow, just surfaced as a holding area rather than
   a yes/no prompt.

Notes from the site visit: ~180 scans is a viable target (not 100%), one MUL
loop takes ~3 minutes, and misrouted baggage down the wrong MUL is a daily
occurrence this project is meant to catch earlier.

## Architecture

Three subsystems, each built independently with no wiring between them, plus
`python/camera_subsystem/main.py` as the integration point that ties them
together:

- `ultrasonic_subsystem/baggage_counter_HYSRF05.ino` (Ben) — Arduino sketch.
  Over serial at 9600 baud it prints a line containing `"Baggage passed"`
  each time a bag is confirmed under the sensor (see the sketch's own header
  comment for wiring/mounting). `main.py --mode serial --port ... --baud ...
  --trigger-token "Baggage passed"` reads this.
- `barcode_subsystem/scanner_capture.py` (Aaron) — always-on, no trigger, no
  relationship to the sensor. Keeps a hidden field focused so a USB
  keyboard-wedge barcode scanner's reads land there, and prints
  `SCAN,<timestamp>,<barcode>` per scan. `main.py` runs this as a subprocess
  (`python/camera_subsystem/barcode_listener.py`) and reads its stdout.
- `python/camera_subsystem/` (Rian) — sensor-trigger listener + camera
  capture. A trigger fires (simulated, or the real Arduino), a photo is
  taken after `--delay` seconds (belt travel time from sensor to camera).
- **Pairing** (`python/camera_subsystem/pairing.py`, `Pairer`) is the piece
  that turns "a photo was taken at time T" and "a barcode was read at time S"
  — two independent timelines — into one bag identity, using proximity in
  time as the only signal: a scan within `--pair-window` seconds of a
  trigger is `matched`; none found is `manual`; more than one candidate is
  `ambiguous`; the same tag re-matched within `--loop-window` seconds
  (roughly one MUL loop, ~3 min per the site visit) is `duplicate`; a scan
  that ages out with no trigger ever near it becomes a standalone
  `unmatched_scan` event. Pure logic, no I/O — see `test_pairing.py`. Flight
  info on a fresh match comes from `Pairer`'s `flight_lookup(tag_id)`
  callback: in `--barcode-mode simulate` the fake tag already encodes its
  flight (`simulated_barcode.py`, see `test_simulated_barcode.py`); in
  `--barcode-mode scanner` it's still round-robin from `flights.csv`, since
  no real tag→flight manifest exists yet to look a real scanned tag up
  against.
- Hardware connection (which serial port, which camera index) is a **backend
  CLI concern**, handled by `main.py`'s arguments — not something the browser
  GUI selects or connects to directly.
- `main.py` writes every event to `events_with_flights.csv` (via
  `event_log.py`, gitignored — regenerated fresh each run) and, in the same
  shape the GUI expects, to `live_events.json` (via `live_feed.py`, atomic
  write so a poll never sees a half-written file, also gitignored).
- The GUI is a web page and cannot read the CSV directly. `gui/app.js` has
  two modes selected by URL: `gui/` is demo mode (steps through the static
  `mock_events.json` fixture, then generates random bags once it runs out);
  `gui/?live=1` polls `live_events.json` every 1.5s and shows new bags as
  they arrive, no Play/Next needed.
- `python/camera_subsystem/captures/` (created at runtime, gitignored) holds
  captured bag images; `photo_path` in an event record is relative to
  `python/camera_subsystem/`.
- Run the GUI with `python3 run_gui.py` from the repo root (serves the whole
  repo so it can reach `python/camera_subsystem/`). Run the integrated
  backend with `python3 main.py` from inside `python/camera_subsystem/` (see
  `--help` for every flag). Defaults match "barcode scanner is real, Arduino
  isn't wired up yet": `--mode simulate` (sensor — with no `--auto-interval`,
  pressing Enter stands in for the sensor firing) and `--barcode-mode
  scanner` (spawns the real `barcode_subsystem/scanner_capture.py`
  subprocess) are the defaults, so `python3 main.py` with no flags is enough
  once the real scanner is attached and a real tag is in front of it. Swap
  to `--mode serial --port ...` once the real Arduino is wired up (needs
  `pyserial` installed — not there by default; see `requirements.txt`).
  `--barcode-mode simulate` generates a fake tag like `KR712-MEL` per
  trigger via `simulated_barcode.py`, for testing with no scanner attached
  at all; `--barcode-mode off` skips barcode identification entirely (every
  bag needs a manual check). Note the camera
  step still uses a real `cv2.VideoCapture` regardless of these flags — with
  no `--camera-index` override it's whatever's at index 0, e.g. a laptop's
  built-in webcam, not a placeholder.

## Event shape (python/camera_subsystem/mock_events.json and live_events.json)

- `id`, `timestamp`, `status`, `flight_number` (nullable), `destination`
  (nullable), `photo_path` (nullable)
- `status` is one of: `matched`, `manual` (no scan found in the verification
  window — needs a handler to identify by hand), `duplicate` (second read of
  a tag already active on the loop), `unmatched_scan` (a scan with no bag
  ever near it), `ambiguous` (more than one possible match). All five are
  produced by `Pairer` now; the GUI renders each with its own styling.
- When `status` is `manual`, `flight_number`/`destination` are genuinely null —
  the GUI must render that as visibly "unknown," not blank or a dash.
- There is **no can/tag field yet** in this shape — no tag→can manifest
  exists. `gui/app.js`'s `canIndexFor()` checks for an explicit `can` field
  first and only falls back to a hash of the bag id (demo-only, to exercise
  the 4-quadrant layout) when it's missing — wiring in the real field later
  is then automatic. `tag_id` (the decoded barcode) is in the CSV but not
  yet threaded into the JSON shape or the GUI.

## Subsystem ownership

- Sensor (Arduino hardware/sketch) — Ben (`ultrasonic_subsystem/`)
- Barcode scanner — Aaron (`barcode_subsystem/`)
- Sensor-trigger + camera-capture + integration (pairing, event log, live
  feed) — Rian (`python/camera_subsystem/`)
- GUI — Bill, Jarrel, Jun (this branch: `jun`, kiosk-monitor GUI in `gui/`)

## GUI (`gui/`)

Plain HTML/CSS/JS, no build step — a kiosk-style monitor display (not
handheld). Four can quadrants (each a fixed categorical color, per the
dataviz skill's palette rules) accumulate bag photos as they're routed in,
using a balanced fill-grid per quadrant (1 bag fills the whole space, 2 split
it evenly, 4 make a 2x2 — same approach a video-call grid uses) rather than
small scrolling thumbnails. A "Needs Attention" tray below holds bags without
a confident can match. Double-click a tile to clear it once loaded.

Demo mode (`gui/`) starts idle and only advances on Play/Next, then runs
forever once started (generates random bags after the mock fixture ends) —
it never auto-plays on page load, so it can't be mistaken for a live feed.
Live mode (`gui/?live=1`) has no demo controls; it polls and shows real bags
as `main.py` produces them.
