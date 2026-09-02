# DMMS

Baggage-identification system for a Qantas airport MUL (Make-Up Line)
conveyor. Scans tags and camera-matches bags as they enter the line, routing
each one to its can on a kiosk display. See `CLAUDE.md` for full
architecture/workflow docs.

```
python3 run_gui.py     # serves the GUI at http://127.0.0.1:8080/gui/
```

## New on this branch (`jarrel`)

GUI (`gui/`):

- **Needs Attention is now its own window** (`gui/attention.html`) instead of
  a cramped strip under the board — opens automatically when the board loads
  (falls back to a flagged manual button if the browser's popup blocker eats
  the auto-open; allow pop-ups for `127.0.0.1` once to fix that for good).
  The two windows poll independently but stay in sync — clearing a tile in
  one updates the other's stats within a poll tick.
- **Fixed tile flicker**: tiles are now cached by bag id and reused across
  polls instead of being torn down and rebuilt every 1.5s, which was
  resetting each `<img>` to "unloaded" and flashing back to the fallback
  camera icon — most visible on Needs Attention bags since those sit the
  longest before a handler clears them.
- **Click a tile to zoom** the photo into its own separate popup window
  (single click; double-click still clears the tile).
- **Flight number + destination now shown on every tile**, in both the Can
  quadrants and Needs Attention — the data was already in every event, it
  just wasn't rendered before.

Backend (`python/camera_subsystem/`):

- **`--mode simulate` gets a second key**: Enter still fires a normal
  (barcoded) bag; `u` fires immediately too but skips pairing a barcode to
  it, landing it straight in Needs Attention (`manual`) — lets you demo/test
  that path on demand instead of waiting on the random status weighting.
