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
5. A ground handler refers to a GUI (this repo's `gui/`) to see the bag and its
   identification, and check whether it matches the can/truck they're loading.
6. Match → load the bag onto the assigned can. No match → manual scan/handling.

Notes from the site visit: ~180 scans is a viable target (not 100%), one MUL
loop takes ~3 minutes, and misrouted baggage down the wrong MUL is a daily
occurrence this project is meant to catch earlier.

## Architecture

- A simple backend holds events (one per bag) as they're produced by the
  sensor/camera/scanner subsystems, with flight info joined in — persisted as
  CSV (`events_with_flights.csv`) as the source of truth on disk.
- The GUI is a web page and cannot read that CSV directly, so events are
  exposed to it as JSON with the same shape — a static mock file during GUI
  development (`gui/mock-data.json`), later a small polling endpoint serving
  live data. Swapping from mock to live is just changing the fetch URL.
- `python/camera_subsystem/` holds captured bag images; `photo_path` in an
  event record is relative to that folder.

## Event shape (provisional — see gui/mock-data.json)

- `event_id`, `timestamp`, `tag_id` (decoded barcode, nullable), `flight_number`
  (nullable), `destination` (nullable), `photo_path`, `status`
- `status` is one of: `matched`, `manual` (no scan found in the verification
  window — needs a handler to identify by hand), `duplicate` (second read of a
  tag already active on the loop), `unmatched_scan`, `ambiguous`. The last two
  aren't in the mock data yet but the GUI renders placeholder UI for them.
- When `status` is `manual`, `flight_number`/`destination` are genuinely null —
  the GUI must render that as visibly "unknown," not blank or a dash.

This field list is provisional and will be tightened once the real CSV schema
from the sensor/scanner/camera subsystems is settled.

## Subsystem ownership

- Sensor — Ben
- Camera (photo capture) — Rian
- Barcode scanner — Aaron
- GUI — Bill, Jarrel, Jun (this branch: `jun`, kiosk-monitor GUI in `gui/`)

## GUI (`gui/`)

Plain HTML/CSS/JS, no build step — a kiosk-style monitor display (not
handheld). Fetches `mock-data.json` and steps through events one at a time,
showing the camera snapshot, decoded tag data, and a color-coded match verdict
so a handler can decide whether to load the bag onto their assigned can.
