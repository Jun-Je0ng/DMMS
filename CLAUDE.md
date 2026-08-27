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

- `python/camera_subsystem/` (Rian) is the sensor + camera subsystem: a
  trigger source (simulated, or a real Arduino over serial via `--mode serial
  --port ... --baud ...`) fires, a photo is captured, a flight is currently
  assigned round-robin from `flights.csv` (a stand-in until barcode-based
  identification is merged in), and a row is appended to
  `events_with_flights.csv` — the source of truth on disk.
- Hardware connection (which serial port, which camera index) is a **backend
  CLI concern**, handled by `main.py`'s arguments — not something the browser
  GUI selects or connects to directly.
- The GUI is a web page and cannot read that CSV directly, so events are
  exposed to it as JSON with the same shape — currently the static
  `python/camera_subsystem/mock_events.json` fixture, later a small polling
  endpoint serving live data off the CSV. Swapping from mock to live is just
  changing `DATA_URL` in `gui/app.js`.
- `python/camera_subsystem/captures/` (created at runtime, not committed)
  holds captured bag images; `photo_path` in an event record is relative to
  `python/camera_subsystem/`.
- Run both together with `python3 run_gui.py` from the repo root — it serves
  the whole repo (so the GUI can reach `python/camera_subsystem/`) and opens
  the browser to `gui/`.

## Event shape (confirmed via python/camera_subsystem/mock_events.json)

- `id` (the sensor trigger's own id, e.g. `"bag_1"` — not a barcode), `timestamp`,
  `status`, `flight_number` (nullable), `destination` (nullable), `photo_path`
- `status` is one of: `matched`, `manual` (no scan found in the verification
  window — needs a handler to identify by hand), `duplicate` (second read of a
  tag already active on the loop), `unmatched_scan`, `ambiguous`. The last two
  aren't in the mock data yet but the GUI renders placeholder UI for them.
- When `status` is `manual`, `flight_number`/`destination` are genuinely null —
  the GUI must render that as visibly "unknown," not blank or a dash.
- There is **no can/tag field yet** — that's Aaron's barcode subsystem and
  hasn't been merged into this event shape. `gui/app.js`'s `canIndexFor()`
  checks for an explicit `can` field first and only falls back to a hash of
  the bag id (demo-only, to exercise the 4-quadrant layout) when it's
  missing — wiring in the real field later is then automatic.

## Subsystem ownership

- Sensor (Arduino hardware/sketch) — Ben
- Sensor-trigger + camera-capture pipeline (consumes Ben's Arduino over
  serial) — Rian (`python/camera_subsystem/`)
- Barcode scanner — Aaron
- GUI — Bill, Jarrel, Jun (this branch: `jun`, kiosk-monitor GUI in `gui/`)

## GUI (`gui/`)

Plain HTML/CSS/JS, no build step — a kiosk-style monitor display (not
handheld), not a live sensor/barcode/camera readout. Four can quadrants (each
a fixed categorical color, per the dataviz skill's palette rules) accumulate
bag photos as they're routed in; a "Needs Attention" tray below holds bags
without a confident can match. Double-click a tile to clear it once loaded.
Starts idle on load and only advances on Play/Next — it never auto-plays on
its own, so it can't be mistaken for a live feed.
