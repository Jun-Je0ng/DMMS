"""
main.py — DMMS integration entry point.

Wires together the trigger source, barcode subsystem, camera, and all
the pipeline feeds (event log, live JSON, activity log).

Run (from repo root):
  python server/main.py --mode simulate           # keyboard-driven, no hardware
  python server/main.py --mode simulate --auto-interval 3 8   # stress test
  python server/main.py --mode serial --port /dev/ttyUSB0     # real Arduino
"""

import argparse
import itertools
import json
import random
import shutil
import time
from datetime import datetime
from pathlib import Path

from hardware  import CameraCapture, SerialTriggerSource, SimulatedTriggerSource
from pipeline  import ActivityFeed, EventLog, LiveFeed, Pairer
from barcode   import BarcodeListener
from sim       import SimulatedBarcodeSource

# gui/flights.json is the single source of truth for flights.
# Resolve from this file's location so `python server/main.py` works from
# any cwd, but also honour a custom --flights-file when given.
_DEFAULT_FLIGHTS = Path(__file__).resolve().parent.parent / "gui" / "flights.json"


def load_flights(path: Path) -> list:
    if not path.exists():
        raise FileNotFoundError(
            f"Flights file not found: {path}\n"
            "Add flights via the GUI (cans.html / flights tab) and they will be saved there automatically."
        )
    flights = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(flights, list) or not flights:
        raise ValueError(f"{path} is empty or not a JSON array.")
    return flights


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def main():
    parser = argparse.ArgumentParser(
        description="DMMS: ultrasonic sensor + barcode scanner + camera → events for the GUI."
    )

    # ── Trigger mode ────────────────────────────────────────────────────────
    parser.add_argument(
        "--mode",
        choices=["simulate", "serial"],
        required=True,
        help=(
            "simulate: stand-in for the sensor, runs without an Arduino — "
            "press Enter per bag, or use --auto-interval for stress tests. "
            "serial: read real triggers from the Arduino over serial."
        ),
    )
    parser.add_argument("--port",  default="/dev/ttyUSB0",
                        help="Serial port for the Arduino (serial mode).")
    parser.add_argument("--baud",  type=int, default=9600)
    parser.add_argument("--trigger-token", default="Baggage passed",
                        help="Substring the Arduino sketch prints on detection.")
    parser.add_argument(
        "--auto-interval", type=float, nargs=2, default=None,
        metavar=("MIN", "MAX"),
        help="Simulate mode: fire automatically at a random interval in [MIN, MAX] seconds "
             "(default: wait for Enter per bag).",
    )

    # ── Barcode ─────────────────────────────────────────────────────────────
    parser.add_argument(
        "--barcode-mode",
        choices=["simulate", "scanner", "off"],
        default="scanner",
        help=(
            "scanner: use the real USB keyboard-wedge scanner. "
            "simulate: generate a fake tag per trigger (no scanner needed). "
            "off: no barcode at all — every bag goes to manual."
        ),
    )
    parser.add_argument("--pair-window", type=float, default=4.0,
                        help="Seconds a scan and trigger may differ and still be paired.")
    parser.add_argument("--loop-window", type=float, default=200.0,
                        help="Seconds a tag stays active for duplicate detection (~one MUL loop).")

    # ── Camera ──────────────────────────────────────────────────────────────
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument(
        "--delay", type=float, default=0.5,
        help="Seconds to wait after barcode resolution before shooting the photo.",
    )

    # ── Output paths ────────────────────────────────────────────────────────
    parser.add_argument("--flights-file", default=str(_DEFAULT_FLIGHTS),
                        help="Path to gui/flights.json (the GUI's saved flights list).")
    parser.add_argument("--save-dir",     default="data/captures")
    parser.add_argument("--log-file",     default="data/events_with_flights.csv")
    parser.add_argument("--live-file",    default="data/live_events.json",
                        help="JSON polled by gui/app.js for the live board.")
    parser.add_argument("--activity-file", default="data/activity.json",
                        help="Rolling raw-event log for server/diagnostics.py.")

    args = parser.parse_args()

    # ── Build subsystems ────────────────────────────────────────────────────
    interval = None if args.auto_interval is None else tuple(args.auto_interval)
    if args.mode == "simulate":
        trigger_source = SimulatedTriggerSource(interval=interval)
    else:
        trigger_source = SerialTriggerSource(
            port=args.port, baud=args.baud, token=args.trigger_token,
        )

    flights = load_flights(Path(args.flights_file))

    if args.barcode_mode == "simulate":
        sim_barcode    = SimulatedBarcodeSource(flights)
        flight_lookup  = sim_barcode.lookup
    else:
        sim_barcode   = None
        # No manifest to resolve a real tag against — cycle through flights in
        # order.  Replace this with a real lookup (API, CSV, etc.) when a
        # flight-manifest integration is available.
        flight_cycle  = itertools.cycle(flights)
        flight_lookup = lambda _tag_id: next(flight_cycle)  # noqa: E731

    pairer   = Pairer(pair_window=args.pair_window, loop_window=args.loop_window,
                      flight_lookup=flight_lookup)

    log_path = Path(args.log_file)
    if log_path.exists():
        log_path.unlink()
    log      = EventLog(args.log_file)
    live     = LiveFeed(args.live_file)
    activity = ActivityFeed(args.activity_file)

    save_dir_path = Path(args.save_dir)
    if save_dir_path.exists():
        shutil.rmtree(save_dir_path)

    # Prefix every id with a per-run stamp so restarting never reissues an
    # id the GUI already saw ("bag_1" in run A ≠ "bag_1" in run B).
    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    seq    = 0

    def log_unmatched_scan(ts: float, barcode: str):
        nonlocal seq
        seq += 1
        bag_id = f"scan_{run_id}_{seq}"
        print(f"Unmatched scan (no bag nearby): {barcode}")
        log.record(id=bag_id, status="unmatched_scan", tag_id=barcode)
        live.add(id=bag_id, timestamp=iso(ts), status="unmatched_scan")

    def on_raw_scan(ts: float, barcode: str):
        activity.add("scan", ts, barcode)

    listener = None
    if args.barcode_mode == "scanner":
        listener = BarcodeListener(pairer, on_unmatched=log_unmatched_scan, on_scan=on_raw_scan)
        listener.start()
        print(
            "Barcode scanner subsystem started — always on, system-wide. "
            "Scan a tag within --pair-window seconds of a trigger to pair it."
        )
    elif args.barcode_mode == "simulate":
        print("Barcode mode: simulated — generating a fake tag per trigger.")
    else:
        print("Barcode mode: off — every bag will need a manual check.")

    # ── Main loop ────────────────────────────────────────────────────────────
    with CameraCapture(camera_index=args.camera_index, save_dir=args.save_dir) as camera:
        print(f"DMMS running in {args.mode} mode. Ctrl+C to stop.")
        try:
            for event in trigger_source.events():
                trigger_ts = time.time()
                print(f"Trigger from {event.source}: {event.raw}")
                activity.add("trigger", trigger_ts, event.raw)

                if sim_barcode is not None and event.barcode:
                    tag      = sim_barcode.next_tag()
                    scan_ts  = trigger_ts + random.uniform(-0.3, 0.3)
                    pairer.submit_scan(ts=scan_ts, barcode=tag)
                    activity.add("scan", scan_ts, tag)

                resolution = pairer.resolve_trigger(trigger_ts)

                if resolution.tag_id:
                    print(f"  Barcode: {resolution.tag_id} ({resolution.status})")
                else:
                    print(f"  No barcode match ({resolution.status})")

                if args.delay > 0:
                    time.sleep(args.delay)
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
                    id=bag_id, timestamp=iso(trigger_ts), status=resolution.status,
                    photo_path=str(path) if path else None,
                    flight_number=resolution.flight_number,
                    destination=resolution.destination,
                )

        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            log.close()
            if listener:
                listener.stop()


if __name__ == "__main__":
    main()
