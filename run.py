"""
run.py — hardware runner. Edit config.py for your serial port and camera, then:

  python run.py

That's it. No flags needed.
"""

import itertools
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Local imports ─────────────────────────────────────────────────────────────
_ROOT   = Path(__file__).resolve().parent
_SERVER = _ROOT / "server"
sys.path.insert(0, str(_SERVER))

import config  # noqa: E402
from hardware import CameraCapture, SerialTriggerSource
from pipeline import ActivityFeed, EventLog, LiveFeed, Pairer
from barcode  import BarcodeListener

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


def main():
    flights       = _load_flights()
    trigger_source = SerialTriggerSource(
        port=config.SERIAL_PORT,
        baud=config.SERIAL_BAUD,
        token=config.TRIGGER_TOKEN,
    )

    # No manifest to resolve a real tag against yet — cycle through flights in
    # order.  Replace the lambda with a real lookup (API, database, etc.) when
    # a flight-manifest integration is available.
    flight_cycle  = itertools.cycle(flights)
    flight_lookup = lambda _tag_id: next(flight_cycle)  # noqa: E731

    pairer   = Pairer(
        pair_window=config.PAIR_WINDOW,
        loop_window=config.LOOP_WINDOW,
        flight_lookup=flight_lookup,
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

    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    seq    = 0

    def log_unmatched_scan(ts: float, barcode: str):
        nonlocal seq
        seq += 1
        bag_id = f"scan_{run_id}_{seq}"
        print(f"Unmatched scan (no bag nearby): {barcode}")
        log.record(id=bag_id, status="unmatched_scan", tag_id=barcode)
        live.add(id=bag_id, timestamp=_iso(ts), status="unmatched_scan")

    def on_raw_scan(ts: float, barcode: str):
        activity.add("scan", ts, barcode)

    listener = BarcodeListener(pairer, on_unmatched=log_unmatched_scan, on_scan=on_raw_scan)
    listener.start()
    print("Barcode scanner subsystem started — always on, system-wide.")

    with CameraCapture(camera_index=config.CAMERA_INDEX, save_dir=str(save_dir)) as camera:
        print(f"DMMS running — serial port {config.SERIAL_PORT}. Ctrl+C to stop.")
        try:
            for event in trigger_source.events():
                trigger_ts = time.time()
                print(f"Trigger: {event.raw}")
                activity.add("trigger", trigger_ts, event.raw)

                resolution = pairer.resolve_trigger(trigger_ts)

                if resolution.tag_id:
                    print(f"  Barcode: {resolution.tag_id} ({resolution.status})")
                else:
                    print(f"  No barcode match ({resolution.status})")

                if config.PHOTO_DELAY > 0:
                    time.sleep(config.PHOTO_DELAY)
                path = camera.capture(label=event.raw)

                seq += 1
                bag_id = f"bag_{run_id}_{seq}"
                print(f"  {'Saved ' + str(path) if path else 'Capture failed'}")

                log.record(
                    id=bag_id, status=resolution.status,
                    trigger_source=event.source, trigger_raw=event.raw,
                    capture_ok=bool(path), capture_path=str(path) if path else "",
                    tag_id=resolution.tag_id or "",
                    flight_number=resolution.flight_number or "",
                    destination=resolution.destination or "",
                )
                live.add(
                    id=bag_id, timestamp=_iso(trigger_ts), status=resolution.status,
                    photo_path=str(path) if path else None,
                    flight_number=resolution.flight_number,
                    destination=resolution.destination,
                )
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            log.close()
            listener.stop()


if __name__ == "__main__":
    main()
