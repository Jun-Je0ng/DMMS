"""
sim_runner.py — simulation runner. No hardware needed. Just:

  python sim_runner.py

Simulates the ultrasonic sensor and the barcode scanner as two INDEPENDENT
inputs, because that's what they are on the real belt — two separate
physical devices firing on their own schedules, stitched together
afterwards purely by time proximity (see Pairer in server/pipeline.py).
Decoupling them here (rather than always firing one fake "bag" that
bundles both) lets you drive every outcome the real pipeline can produce,
not just the two easy ones.

Controls (in this terminal while it is running, no Enter needed):
  t          → ultrasonic sensor fires (a bag passes the sensor)
  b          → barcode scanner reads a tag
  q          → quit  (Ctrl+C also works)

What each combination produces:
  - 't' alone, nothing paired within --pair-window (config.PAIR_WINDOW)
    seconds either side  → 'manual' (Needs Attention) — the sensor saw a
    bag but no barcode could be attached to it.
  - 'b' alone, no 't' lands within the pair window  → after the sweep
    interval, an 'unmatched_scan' bag — the scanner read a tag with
    nothing on the belt to attach it to.
  - 't' then 'b', or 'b' then 't', within the pair window  → 'matched'.
  - 'b' pressed twice before a 't' claims either of them  → 'ambiguous'
    (two candidate scans for one trigger).
  - The same simulated tag scanned again within --loop-window
    (config.LOOP_WINDOW) seconds of its last sighting  → 'duplicate'.
    (SimulatedBarcodeSource cycles through your flights list, so with N
    flights configured the same tag comes back every N scans — configure
    just 1-2 flights if you want to hit 'duplicate' quickly.)

Run this instead of run.py when you have no Arduino or scanner attached.
For the extra flags this zero-config version doesn't expose
(--pair-window, --loop-window, --flights-file, --auto-interval, ...), run
server/main.py --mode simulate directly instead.
"""

import json
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ── Local imports ─────────────────────────────────────────────────────────────
_ROOT   = Path(__file__).resolve().parent
_SERVER = _ROOT / "server"
sys.path.insert(0, str(_SERVER))

import config  # noqa: E402
from pipeline import ActivityFeed, EventLog, LiveFeed, Pairer
from sim      import SimulatedBarcodeSource

# ── Flights ───────────────────────────────────────────────────────────────────
_FLIGHTS_FILE = _ROOT / "gui" / "flights.json"


def _load_flights() -> list:
    if not _FLIGHTS_FILE.exists():
        raise FileNotFoundError(
            f"{_FLIGHTS_FILE} not found.\n"
            "Add flights via the GUI and they will be saved there automatically."
        )
    flights = json.loads(_FLIGHTS_FILE.read_text(encoding="utf-8"))
    if not isinstance(flights, list) or not flights:
        raise ValueError("gui/flights.json is empty — add at least one flight via the GUI.")
    return flights


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


class _NoCamera:
    """Stand-in for CameraCapture when there's no physical camera.
    Reports every capture as failed so the GUI shows the bag without a photo.
    """
    def capture(self, label: str = ""):
        return None


def _read_key() -> str:
    """Block for exactly one keypress and return it — no Enter needed.

    Two independent single-key controls (sensor vs. scanner) is the whole
    point of this script, so this reads raw keystrokes the same way
    hardware.SimulatedTriggerSource does for its one key, just factored out
    here since we now need it for two.
    """
    if not sys.stdin.isatty():
        # Piped input (e.g. a scripted test) — fall back to line reads.
        line = sys.stdin.readline()
        return line[:1] if line else "q"

    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getwch()
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch

    import termios
    import tty
    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch


def main():
    flights     = _load_flights()
    sim_barcode = SimulatedBarcodeSource(flights)
    camera      = _NoCamera()

    pairer = Pairer(
        pair_window=config.PAIR_WINDOW,
        loop_window=config.LOOP_WINDOW,
        flight_lookup=sim_barcode.lookup,
    )

    log_path = Path("data/events_with_flights.csv")
    if log_path.exists():
        log_path.unlink()
    log      = EventLog(str(log_path))
    live     = LiveFeed("data/live_events.json")
    activity = ActivityFeed("data/activity.json")

    save_dir = Path("data/captures")
    if save_dir.exists():
        shutil.rmtree(save_dir)

    run_id   = datetime.now().strftime("%Y%m%d%H%M%S")
    seq      = 0
    seq_lock = threading.Lock()

    def next_bag_id(prefix: str) -> str:
        nonlocal seq
        with seq_lock:
            seq += 1
            return f"{prefix}_{run_id}_{seq}"

    # ── Action 1: ultrasonic/sensor trigger ────────────────────────────────
    def do_trigger():
        trigger_ts = time.time()
        activity.add("trigger", trigger_ts, "sim-sensor")

        resolution = pairer.resolve_trigger(trigger_ts)
        path       = camera.capture(label="sim")
        bag_id     = next_bag_id("bag")

        if resolution.tag_id:
            print(f"  [sensor]  {bag_id}: {resolution.status} "
                  f"— paired with {resolution.tag_id} ({resolution.flight_number or '?'})")
        else:
            print(f"  [sensor]  {bag_id}: {resolution.status} — no scan paired with it")

        log.record(
            id=bag_id, status=resolution.status,
            trigger_source="simulated", trigger_raw="sim-sensor",
            capture_ok=False, capture_path="",
            tag_id=resolution.tag_id or "",
            flight_number=resolution.flight_number or "",
            destination=resolution.destination or "",
        )
        live.add(
            id=bag_id, timestamp=_iso(trigger_ts), status=resolution.status,
            photo_path=None,
            flight_number=resolution.flight_number,
            destination=resolution.destination,
        )

    # ── Action 2: barcode scanner read ─────────────────────────────────────
    def do_scan():
        scan_ts = time.time()
        tag     = sim_barcode.next_tag()
        pairer.submit_scan(ts=scan_ts, barcode=tag)
        activity.add("scan", scan_ts, tag)
        print(f"  [scanner] read {tag} — waiting up to {config.PAIR_WINDOW:g}s "
              f"for a sensor trigger to pair with")

    # ── Background sweep: scans that never got claimed by a trigger ───────
    # Mirrors BarcodeListener._sweep_loop in server/barcode.py (the real
    # hardware path) — without this, a lone 'b' press with no matching 't'
    # would sit in Pairer.pending_scans forever instead of surfacing as an
    # 'unmatched_scan' bag on the board.
    def log_unmatched_scan(ts: float, barcode: str):
        bag_id = next_bag_id("scan")
        print(f"  [sweep]   {bag_id}: unmatched_scan — {barcode} was never claimed by a trigger")
        log.record(id=bag_id, status="unmatched_scan", tag_id=barcode)
        live.add(id=bag_id, timestamp=_iso(ts), status="unmatched_scan")

    stop_event = threading.Event()

    def sweep_loop():
        while not stop_event.wait(1.0):
            for ts, barcode in pairer.sweep_unmatched(now=time.time()):
                log_unmatched_scan(ts, barcode)

    threading.Thread(target=sweep_loop, daemon=True).start()

    print("Simulation running.")
    print(f"  t = sensor trigger   b = barcode scan   q = quit"
          f"   (pair window {config.PAIR_WINDOW:g}s, loop window {config.LOOP_WINDOW:g}s)\n")

    try:
        while True:
            key = _read_key().lower()
            if key in ("t", "\r", "\n"):
                do_trigger()
            elif key == "b":
                do_scan()
            elif key in ("q", "\x03"):
                break
            # anything else is ignored — no prompt spam on stray keys
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopped.")
        stop_event.set()
        log.close()


if __name__ == "__main__":
    main()
