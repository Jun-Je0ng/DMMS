# DMMS GUI — Current State Reference

> For AI sessions picking up this project. Read this before touching any GUI file.
> Last updated: September 2026 — added the two mobile bag-confirmation prototypes
> (`mobile_swipe.html` / `mobile_keypad.html`) and the `/api/loaded` sync endpoint.

---

## What This Is

**DMMS** (Departure Make-Up Line Management System) is a kiosk GUI for baggage routing at an airport's Make-Up Line (MUL). A bag arrives on a belt, an ultrasonic sensor fires, a barcode scanner reads the tag, a camera captures the bag, and the GUI shows which physical "can" (container) the bag belongs in based on its flight.

The GUI is **pure HTML/CSS/JS** — no framework, no build step. It is served by `run_gui.py` (a Python `http.server` subclass) from the repo root, which also exposes REST endpoints for persisting data (flights, cans, and — since the mobile pages were added — loaded confirmations).

Two mobile-first pages let roving staff confirm bags loaded from a phone on the same LAN, as two competing UX prototypes to A/B with real people (see "Mobile Confirmation Pages" below).

---

## Repository Layout (post-refactor)

```
DMMS/
├── config.py           Hardware settings (serial port, camera index, etc.) — edit once
├── run.py              Hardware runner  →  python run.py
├── sim_runner.py       Simulation runner → python sim_runner.py  (no hardware needed)
├── run_gui.py          GUI web server   →  python run_gui.py  (serves gui/ on :8080)
│
├── server/             Python backend (6 modules, flat)
│   ├── main.py         Full CLI entry point (power-user, all flags)
│   ├── hardware.py     TriggerSource (serial/simulated), CameraCapture
│   ├── pipeline.py     Pairer, EventLog, LiveFeed, ActivityFeed
│   ├── barcode.py      BurstDetector, ScanReader, BarcodeListener (+ subprocess entry)
│   ├── sim.py          SimulatedBarcodeSource
│   └── diagnostics.py  Engineer dashboard (cv2 window polling data/activity.json)
│
├── data/               Runtime output — written by Python, read by GUI
│   ├── live_events.json    → gui/app.js (and the mobile pages) poll this every 1.5 s
│   ├── loaded.json         → GET/POST via /api/loaded* — bags confirmed loaded from a phone
│   ├── activity.json       → server/diagnostics.py polls this
│   ├── events_with_flights.csv  → audit log, one row per bag
│   ├── captures/           → bag photos saved here by CameraCapture
│   └── mock_events.json    → static fixture for offline testing (not auto-loaded)
│
├── gui/                Front-end (served at http://127.0.0.1:8080/gui/)
│   ├── index.html          Main board  (operator kiosk view)
│   ├── attention.html      Needs-Attention tray (secondary window)
│   ├── cans.html           Can & Flight management page
│   ├── mobile_swipe.html   Mobile prototype A — flight number → swipe deck → tick/cross
│   ├── mobile_keypad.html  Mobile prototype B — numeric keypad → bag tag → confirm
│   ├── mobile-common.js    Shared fetch/mark/unmark/formatting helpers for both mobile pages
│   ├── mobile.css          Shared phone-first styles for both mobile pages
│   ├── mobile-qr.js         Main board's "Mobile Access" QR popup (index.html only)
│   ├── vendor/
│   │   ├── qrcode.js         Vendored offline QR encoder (MIT, see QRCODE-LICENSE.txt)
│   │   └── QRCODE-LICENSE.txt
│   ├── app.js               All board logic (routing, polling, rendering, mobile-sync)
│   ├── config.js            Display config (uiScale — user editable, no restart needed)
│   ├── style.css            Full design system (CSS custom properties, dark theme)
│   ├── flights.json         Persisted flight list (source of truth)
│   ├── cans.json             Persisted can list
│   └── resources/
│       ├── airlines/   Airline logos — {IATA_CODE}.png  (e.g. QF.png, NZ.png)
│       └── *.png       Brand logo and other assets
│
├── tests/              Unit tests (pytest)
│   ├── test_pipeline.py   Pairer tests
│   ├── test_feeds.py      ActivityFeed tests
│   └── test_barcode.py    BurstDetector + SimulatedBarcodeSource tests
│
└── hardware/           Arduino sketch(es)
    └── ultrasonic.ino  HYSRF05 ultrasonic sensor, prints "Baggage passed" on detect
```

---

## How to Run

```bash
# Start the GUI server (always needed)
python run_gui.py          # serves http://127.0.0.1:8080/gui/

# Then, in a second terminal, start one of:
python run.py              # real hardware (Arduino + scanner + camera)
python sim_runner.py       # simulation (key-press per bag, no hardware)
```

**`config.py`** is the only file a new installation needs to edit — set `SERIAL_PORT` and `CAMERA_INDEX` to match the hardware.

`run_gui.py` binds `0.0.0.0:8080` (not just `127.0.0.1`) so phones on the same LAN can reach `mobile_swipe.html` / `mobile_keypad.html` — it prints the LAN IP and the two mobile URLs on startup. If a phone can't connect, check Windows Firewall is allowing inbound on port 8080.

`sim_runner.py` simulates the ultrasonic sensor and the barcode scanner as **two independent keys**, not one combined "send a bag" action — because that's what they are on the real belt, two separate devices firing on their own schedule that `Pairer` (in `server/pipeline.py`) stitches together afterwards purely by how close their timestamps are:

- **`t`** — ultrasonic sensor fires (a bag passes the sensor)
- **`b`** — barcode scanner reads a tag (cycles through `gui/flights.json`)
- **`q`** / **Ctrl+C** — stop

No Enter needed — both are single-key, and can be pressed in either order, close together or far apart, to reach every status the real pipeline can produce: `t` alone → `manual`; `b` alone with no `t` nearby → `unmatched_scan` (after a ~1s background sweep, mirroring `BarcodeListener`'s sweep in real hardware mode); `t`+`b` within `config.PAIR_WINDOW` seconds (either order) → `matched`; two `b`s before a `t` claims either → `ambiguous`; the same simulated tag scanned again within `config.LOOP_WINDOW` seconds of its last sighting → `duplicate`. Configure only 1-2 flights in `gui/flights.json` if you want `duplicate` to come up quickly, since `SimulatedBarcodeSource` cycles the tag every `len(flights)` scans.

This is deliberately the zero-flags quick-start version — for `--pair-window`, `--loop-window`, `--flights-file`, `--auto-interval` and the rest, run `server/main.py --mode simulate` directly instead.

---

## GUI Pages

### `gui/index.html` — Main Board
The primary kiosk screen. Operators watch this.

- **Header**: brand logo, 4 stat tiles (Scanned / In a Can / Needs Attention / Loaded), live clock.
- **Board** (`#quadrants`): one `<section class="quadrant">` per can, injected by `app.js`. Tiles appear inside quadrants as bags arrive.
- **Footer**: Auto-clear toggle (30 s default), Auto-scroll toggle, **Manage Cans** button (opens `cans.html`), **Needs Attention** button (opens `attention.html`), **Reset Board** button.
- **Dead markup** (leftover, harmless): `#mode-banner` (MOCK DATA banner) and `#btn-prev/play/next` demo controls are in the HTML but hidden — they will never show because `IS_LIVE = true` in `app.js`.

Loads: `config.js`, then `app.js`.

### `gui/attention.html` — Needs Attention Tray
A secondary window (opened via footer button) that shows only bags that couldn't be routed: `manual`, `duplicate`, `unmatched_scan`, `ambiguous`. Same `app.js` / `style.css` — the logic detects it has no `#quadrants` element and switches to tray mode.

### `gui/cans.html` — Can & Flight Management
Operator configuration page (opened in a new tab from the main board's "Manage Cans" button).

**Left panel — Active Cans**: list of current cans, each with a flight dropdown and a label text input. Changes save immediately.

**Right panel — two tabs**:
- **Add Can tab**: flight dropdown (optional) + label → "Add Can" button.
- **Flights tab**: lists current flights; form to add a new one (flight number, destination code, departure time).

**Persistence** (dual-write, both always attempted):
1. `localStorage` at key `dmms:cans` / `dmms:flights` — instant, in-browser.
2. `POST /api/cans` → `gui/cans.json` and `POST /api/flights` → `gui/flights.json` — survives browser clears, works across machines on the same LAN.

On load, the file takes priority over localStorage if it has data. Both `cans.html` and `app.js` fetch from the file API at boot and fall back to localStorage.

---

## Mobile Confirmation Pages (two competing prototypes)

Two phone-first pages let roving staff confirm a bag was physically loaded, without touching the kiosk. They're built as **two different interaction models on purpose** — the idea was to run them past real ramp staff and see which one people actually find faster/less error-prone, not to pick a "winner" in code.

Both pages:
- are served from the same origin as the kiosk (`http://<pc-ip>:8080/gui/mobile_swipe.html` / `mobile_keypad.html`) — a phone on the same LAN just browses there;
- poll `data/live_events.json` directly (same shape as the kiosk board) and `GET /api/loaded` for what's already confirmed;
- write confirmations via `POST /api/loaded/mark` / `POST /api/loaded/unmark` — **not** localStorage, because a phone is a different browser/origin than the kiosk, so localStorage can't be shared between them;
- share `gui/mobile-common.js` (fetch/format/mark/unmark helpers, bag "tag" numbering) and `gui/mobile.css` (big-touch-target dark-theme layout, safe-area padding for notches).
- link to each other ("Switch to Swipe/Keypad Confirm") so a tester can flip between the two without retyping a flight/URL.

The kiosk board (`index.html`) has a single **📱 Mobile Access** footer button that pops up a QR code for each page (see next section) — phones should scan rather than type a URL, since it changes network to network.

### Mobile Access QR popup (`gui/mobile-qr.js`, kiosk board only)

The kiosk's LAN address is different on every network it's plugged into, so instead of a URL painted on the wall, the **📱 Mobile Access** button calls `GET /api/server-info` (added to `run_gui.py`) to ask the server what address it's *actually* bound to right now, builds `http://<lan_ip>:8080/gui/mobile_swipe.html` and `.../mobile_keypad.html`, and renders each as a QR code on a `<canvas>` for a phone camera to scan straight in. Each QR card also has an "Open on this device" link (relative path) for testing from the kiosk PC itself without a phone.

QR rendering uses `gui/vendor/qrcode.js` — the classic Kazuhiko Arase "QRCode for JavaScript" (MIT), re-bundled from the copy vendored inside npm's own `qrcode-terminal` package into a single browser-loadable file exposing `window.qrcode`. This was a deliberate choice: the kiosk may have no internet access on site, and `qrcode()` (via a CDN) was not an option, so the encoder is vendored directly in the repo — see `gui/vendor/QRCODE-LICENSE.txt` for attribution. If you ever need to regenerate it, the algorithm files are pure JS with no external deps; do not swap in a differently-shaped API without updating `mobile-qr.js`'s `drawQr()`, which expects `new window.qrcode(typeNumber, level)` with `.addData()`, `.make()`, `.getModuleCount()`, `.isDark(row, col)`.

`run_gui.py`'s `GET /api/server-info` returns `{"lan_ip": "192.168.x.x" | null, "port": 8080}`. The IP is detected once (via a UDP "connect" to 8.8.8.8 that never actually sends anything — just makes the OS report which interface it would use) and cached for the life of the process. `run_gui.py` also binds `0.0.0.0` instead of `127.0.0.1` now, and prints the same LAN URLs to the console on startup, so phones can reach it at all.

### Bag "tag" numbers

Since a full bag ID (`bag_20260908135715_1`) is unwieldy to type on a phone keypad, every bag also gets a short **tag** number — just its 1-based position in the `live_events.json` feed (`event._tag`, stamped client-side, never sent by the Python backend). The exact same scheme is computed independently in `app.js` (`stampTags`) and `mobile-common.js` (`dmmsStampTags`) — **if you ever change one, change the other**, or tag numbers on the kiosk board and the phone stop matching. The kiosk board shows the tag as a small `#N` badge in the top-left corner of every tile (`.tile-tag` in `style.css`) so staff can read it off the screen to type into the keypad page.

### `gui/mobile_swipe.html` — Prototype A: flight number → swipe deck

1. **Entry screen**: type/tap a flight number (chips show flights currently seen in the feed).
2. **Deck screen**: one bag at a time (`status: "matched"`, that flight, not yet loaded, oldest first). Swiping left/right (touch or mouse drag) or the on-screen `←`/`→` arrows **only moves focus** between bags — it never confirms anything, so a stray swipe can't accidentally mark a bag loaded. Confirming is always the explicit ✓ button (`POST /api/loaded/mark`, source `"swipe"`); the ✗ button just skips to the next bag without marking it.
3. **Loaded tray**: a swipe-up drawer (drag the handle, or tap it) lists everything confirmed loaded for this flight, each with an **Undo** button (`POST /api/loaded/unmark`) that puts the bag straight back into the pending deck — the reversibility the swipe interaction needed.

### `gui/mobile_keypad.html` — Prototype B: keypad → bag lookup → confirm

1. **Keypad screen**: a big numeric pad; type the bag's `#tag` (read off the kiosk tile) and press **Go**.
2. Looks the bag up fresh (refetches `live_events.json` + `/api/loaded` on every lookup, not from a stale poll) by `_tag`. Not found → a dedicated error screen with **Try Again**.
3. **Confirm screen**: shows the bag's photo, flight, id and "Confirm loaded?" with big Yes/No buttons. If that tag was already confirmed (by either mobile page or the kiosk double-click), it instead shows *when* and lets the user **Undo — Not Loaded** right there, so mistakes are self-correcting without needing the swipe page's tray.

### `run_gui.py` — `/api/loaded*` endpoints

| Method | Path | Body | Effect |
|---|---|---|---|
| `GET`  | `/api/loaded` | — | Returns `data/loaded.json` (array), `[]` if missing |
| `POST` | `/api/loaded/mark` | `{id, flight_number, tag, source}` | Upserts a record with `loaded_at` (server time); `source` is `"board"` \| `"swipe"` \| `"keypad"` |
| `POST` | `/api/loaded/unmark` | `{id}` | Removes that record |

Unlike `/api/cans` and `/api/flights` (whole-file overwrite — fine for a single admin editing at a time), `/api/loaded` uses **read-modify-write per bag** so two phones tapping at once can't clobber each other. `run_gui.py`'s `http.server` handles one request at a time (no threading), so this is safe without extra locking. `_write_loaded()` writes to a temp file and `os.replace()`s it, so a crash mid-write can't corrupt `data/loaded.json`.

`app.js` also polls `/api/loaded` on the same 1.5 s interval as `live_events.json` (`pollServerLoaded`) and folds any new record into the board's own `state.loaded` / `state.dismissed` sets — so a bag confirmed from a phone disappears from the kiosk board too. Conversely, when an operator double-clicks a tile and picks "Mark as Loaded" on the kiosk itself, `app.js` now also calls `POST /api/loaded/mark` (`source: "board"`) so the phones see it as already loaded.

---

## `gui/app.js` — Core Logic

### Key Constants (top of file)
```js
const IS_LIVE        = true;                    // always live — no demo/mock toggle
const DATA_URL       = "../data/live_events.json"; // polled every 1.5 s
const IMAGE_BASE_URL = "../data/";              // prepended to photo_path from events
const LIVE_POLL_MS   = 1500;
const CAROUSEL_THRESHOLD = 4;                  // >4 tiles per can → horizontal carousel
```

### Event Shape (from `data/live_events.json`)
```json
{
  "id":            "bag_20260904123456_1",
  "timestamp":     "2026-09-04T12:34:56",
  "status":        "matched",
  "flight_number": "QF298",
  "destination":   "SYD",
  "photo_path":    "captures/bag_20260904_123456_789012_bag_1.jpg"
}
```
`status` values: `matched` | `manual` | `duplicate` | `unmatched_scan` | `ambiguous`

`manual` and anything without a `flight_number` go to the Needs Attention tray.

### Can Routing (`canIndexFor(event)`)
1. If **no can has a flight assigned** → hash-based round-robin across all cans (demo fallback).
2. If event has a `flight_number` → find the can whose `flight` field matches (case-insensitive). If none matches, fall back to the first can with an empty flight (catch-all).
3. If event has no `flight_number` → go straight to the catch-all can. If no catch-all exists, returns -1 → bag goes to Needs Attention.

### Airline Logo Auto-Matching
```js
function airlineLogoUrl(flightNumber) {
  // "QF298" → "resources/airlines/QF.png"
  // "NZ499" → "resources/airlines/NZ.png"
}
```
Drop `{IATA_CODE}.png` in `gui/resources/airlines/` — no config needed. `onerror` hides the image gracefully if the file is missing.

### State Object
```js
const state = {
  cans:            [...],   // from localStorage / API
  events:          [...],   // raw from live_events.json
  flights:         [...],   // from localStorage / API
  dismissed:       Set,     // IDs dismissed by operator (persisted)
  loaded:          Set,     // IDs marked "Loaded" (persisted)
  liveResetOffset: 0,       // skip events older than this index on Reset Board
};
```

### localStorage Keys
| Key | Contents |
|-----|----------|
| `dmms:cans` | Array of can objects `{id, label, flight}` |
| `dmms:flights` | Array `{flight_number, destination, departure_time}` |
| `dmms:dismissed` | Array of dismissed bag IDs |
| `dmms:loaded` | Array of "Loaded" bag IDs |
| `dmms:settings` | `{timeoutEnabled, timeoutSecs, autoScrollEnabled}` |
| `dmms:liveResetOffset` | Int — index in live_events.json to start from after Reset |

### Cross-Tab Sync
`window.addEventListener("storage", ...)` in `app.js` and `attention.html` — when `cans.html` writes to localStorage, the board re-renders immediately without a page reload.

---

## `gui/style.css` — Design System

Dark theme only (`data-theme="dark"` on `<html>`). Key CSS custom properties:

```css
--page-plane     /* #0d0d0d — outermost background */
--surface-1      /* panels, cards */
--surface-2      /* inputs, inner elements */
--border         /* subtle separators */
--border-strong  /* input borders */
--accent         /* #2461c8 — blue, primary interactive */
--good           /* green — "Loaded" / success states */
--critical       /* red — remove / destructive */
--text-primary
--text-secondary
--text-muted
--ui-scale       /* set from config.js uiScale, applied via calc() throughout */
--radius-sm/md/lg
--mono           /* monospace font stack */
```

Per-can accent colour is passed via `--cat` on each `.quadrant` element.

---

## `gui/config.js` — User-Editable Display Config

```js
window.DMMS_CONFIG = {
  uiScale: 1.0,   // 1.0 = laptop, 1.5 = 30"+ screen, 2.0 = 4K TV
};
```

`app.js` reads this at load and sets `--ui-scale` on `:root`. No restart needed — just reload the browser.

---

## Data Persistence — Flights & Cans

Both are **dual-persisted**: localStorage (instant, per-browser) and a JSON file (durable, cross-browser/machine).

| Data | localStorage key | File | API endpoint |
|------|-----------------|------|-------------|
| Flights | `dmms:flights` | `gui/flights.json` | `GET/POST /api/flights` |
| Cans | `dmms:cans` | `gui/cans.json` | `GET/POST /api/cans` |
| Loaded (mobile sync) | `dmms:loaded` (kiosk board only, secondary) | `data/loaded.json` | `GET /api/loaded`, `POST /api/loaded/mark`, `POST /api/loaded/unmark` |

`run_gui.py` serves the GUI at `:8080` and handles these two endpoints. The file is the **source of truth** — on page load the file wins if it has data.

`gui/flights.json` is also read by `run.py` and `sim_runner.py` to load the flight list for barcode lookup. It is the **single source of truth for flights** — the old `python/camera_subsystem/flights.csv` no longer exists.

---

## Known Stubs / Things to Clean Up

- **`#mode-banner`** (MOCK DATA banner) and **`#btn-prev/play/next`** (demo playback controls) are still in `index.html` and `attention.html` HTML markup. They are never shown because `IS_LIVE = true` always. Safe to remove from the HTML if desired.
- **`data/mock_events.json`** — static fixture, not auto-loaded. Useful for manual testing: copy it to `data/live_events.json` while no Python runner is active to preview the board with sample data.
- **`config.js` comment** says "stored in localStorage". Update it to mention `gui/flights.json` and `gui/cans.json` as the real persistence layer.
- **`run_gui.py`** still at repo root alongside new `run.py`. Eventually consolidate into one launcher or rename for clarity.

---

## What the GUI Does NOT Do Yet (Planned)

- **Operator tablet/phone interface** — ~~discussed but not built~~ now built as two competing prototypes, `gui/mobile_swipe.html` and `gui/mobile_keypad.html` (see "Mobile Confirmation Pages" above). Still untested with real ramp staff — that's the point of having two.
- **A winner picked between the two mobile prototypes** — both stay in the repo until someone runs the usability test; don't delete either without checking with the user first.
- **Real flight-manifest lookup** — currently `run.py` cycles through flights in order when a real scanner is used (no manifest API). The lambda in `run.py` is the placeholder to replace.
- **Photo display** — `photo_path` is stored in events but the tile currently shows a camera icon placeholder when no image loads. Real photos from `data/captures/` should display when `run.py` is used with a real camera.
