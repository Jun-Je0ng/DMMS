import argparse
import csv
import itertools
import random
import shutil
import time
from datetime import datetime
from pathlib import Path

from activity_feed import ActivityFeed
from barcode_listener import BarcodeListener
from camera_capture import CameraCapture
from event_log import EventLog
from live_feed import LiveFeed
from pairing import Pairer
from simulated_barcode import SimulatedBarcodeSource
from trigger_source import SerialTriggerSource, SimulatedTriggerSource

FLIGHTS_FILE = Path(__file__).parent / "flights.csv"


def load_flights() -> list:
    with open(FLIGHTS_FILE, newline="") as f:
        flights = list(csv.DictReader(f))
    if not flights:
        raise ValueError(f"{FLIGHTS_FILE} has no rows")
    return flights


def build_trigger_source(args):
    if args.mode == "simulate":
        return SimulatedTriggerSource(interval=tuple(args.auto_interval))
    return SerialTriggerSource(port=args.port, baud=args.baud, token=args.trigger_token)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def wait_for_scan_since(pairer: Pairer, trigger_ts: float, timeout: float, poll_interval: float = 0.1, settle: float = 0.2):
    """
    Blocks until a scan at/after trigger_ts shows up in the pairer (then
    waits a brief settle period to catch a near-simultaneous second one, for
    ambiguous detection) or `timeout` elapses either way. This is what makes
    the barcode scanner "start scanning" from the sensor's point of view:
    only scans from trigger_ts onward count for this bag, and this call
    doesn't return until it knows one way or the other.
    """
    deadline = trigger_ts + timeout
    found = False
    while time.time() < deadline:
        if pairer.candidates_since(trigger_ts):
            found = True
            break
        time.sleep(poll_interval)
    if found and settle > 0:
        time.sleep(settle)
    return pairer.take_since(trigger_ts)


def main():
    parser = argparse.ArgumentParser(
        description="DMMS integration: ultrasonic sensor + barcode scanner + camera -> events for the GUI."
    )
    parser.add_argument(
        "--mode",
        choices=["simulate", "serial"],
        required=True,
        help="Required, no default, on purpose: simulate stands in for the sensor and runs on its own "
        "(no Arduino needed) -- it should never turn on just because you forgot to pick a mode. "
        "serial: read real triggers from the Arduino.",
    )
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Serial port for the Arduino (serial mode).")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument(
        "--trigger-token",
        default="Baggage passed",
        help="Substring the Arduino sketch prints on a confirmed detection "
        "(see ultrasonic_subsystem/baggage_counter_HYSRF05.ino's Serial.print lines).",
    )
    parser.add_argument(
        "--auto-interval",
        type=float,
        nargs=2,
        default=[4.0, 10.0],
        metavar=("MIN", "MAX"),
        help="Simulate mode: fire on its own at a random interval in this range (seconds), no keypress needed. "
        "Default 4-10s.",
    )
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait after resolving the barcode before taking the photo, to allow for belt travel "
        "from the scanner to the camera.",
    )
    parser.add_argument("--save-dir", default="captures")
    parser.add_argument("--log-file", default="events_with_flights.csv")
    parser.add_argument(
        "--live-file",
        default="live_events.json",
        help="JSON file written after every event, in the shape gui/app.js polls for.",
    )
    parser.add_argument(
        "--activity-file",
        default="activity.json",
        help="Rolling raw sensor/scanner log for diagnostics_view.py -- separate from --live-file, "
        "which only holds resolved (paired) bags.",
    )
    parser.add_argument(
        "--barcode-mode",
        choices=["simulate", "scanner", "off"],
        default="scanner",
        help="scanner: run the real barcode_subsystem scanner (needs the physical scanner attached). "
        "simulate: no scanner needed, generates a fake tag like 'KR712-MEL' per trigger, for testing "
        "without hardware. "
        "off: no barcode subsystem at all -- every bag needs a manual check.",
    )
    parser.add_argument(
        "--pair-window",
        type=float,
        default=4.0,
        help="Seconds to wait for a barcode scan after a trigger before giving up on this bag (manual).",
    )
    parser.add_argument(
        "--loop-window",
        type=float,
        default=200.0,
        help="Seconds a tag stays 'active' for duplicate detection -- roughly one MUL loop (~3 min per the site visit).",
    )
    args = parser.parse_args()

    trigger_source = build_trigger_source(args)
    flights = load_flights()

    log_path = Path(args.log_file)
    if log_path.exists():
        log_path.unlink()
    log = EventLog(args.log_file)

    live = LiveFeed(args.live_file)
    activity = ActivityFeed(args.activity_file)

    save_dir_path = Path(args.save_dir)
    if save_dir_path.exists():
        shutil.rmtree(save_dir_path)

    sim_barcode = SimulatedBarcodeSource(flights) if args.barcode_mode == "simulate" else None
    if sim_barcode is not None:
        flight_lookup = sim_barcode.lookup
    else:
        # No manifest exists yet to look a real tag up against, so this is a
        # placeholder: whichever flight is next in rotation, regardless of
        # which tag actually got scanned.
        flight_cycle = itertools.cycle(flights)
        flight_lookup = lambda _tag_id: next(flight_cycle)  # noqa: E731

    pairer = Pairer(pair_window=args.pair_window, loop_window=args.loop_window, flight_lookup=flight_lookup)

    # Prefixes every id with a per-run stamp so restarting main.py never
    # reissues an id like "bag_1" that the GUI already saw and dismissed in
    # an earlier run -- the browser's dismissed-tile memory is keyed by id
    # and has no other way to know a "new" bag_1 is actually a different bag.
    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    seq = 0

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
        print("Barcode scanner subsystem started -- waiting for the sensor to activate it per bag.")
    elif args.barcode_mode == "simulate":
        print("Barcode scanner simulated -- generating a fake tag per trigger, no hardware needed.")
    else:
        print("Running without the barcode scanner -- every bag will need a manual check.")

    with CameraCapture(camera_index=args.camera_index, save_dir=args.save_dir) as camera:
        print(f"Camera subsystem running in {args.mode} mode. Ctrl+C to stop.")
        try:
            for event in trigger_source.events():
                trigger_ts = time.time()
                print(f"Trigger from {event.source}: {event.raw}")
                activity.add("trigger", trigger_ts, event.raw)

                # Sequential, per the real workflow: sensor fires, THEN the
                # scanner is what we listen to (only scans from trigger_ts
                # onward count for this bag), THEN the photo is taken after
                # --delay seconds of belt travel from scanner to camera.
                if sim_barcode is not None:
                    tag = sim_barcode.next_tag()
                    scan_ts = trigger_ts + random.uniform(-0.3, 0.3)
                    pairer.submit_scan(ts=scan_ts, barcode=tag)
                    activity.add("scan", scan_ts, tag)
                    resolution = pairer.resolve_trigger(trigger_ts)
                elif args.barcode_mode == "scanner":
                    candidates, expired = wait_for_scan_since(pairer, trigger_ts, timeout=args.pair_window)
                    for ts, barcode in expired:
                        log_unmatched_scan(ts, barcode)
                    resolution = pairer.resolve_candidates(trigger_ts, candidates)
                else:
                    resolution = pairer.resolve_trigger(trigger_ts)  # "off": nothing's ever submitted -> manual

                if resolution.tag_id:
                    print(f"  Barcode: {resolution.tag_id} ({resolution.status})")
                else:
                    print(f"  No barcode match ({resolution.status})")

                if args.delay > 0:
                    time.sleep(args.delay)
                path = camera.capture(label=event.raw)

                seq += 1
                bag_id = f"bag_{run_id}_{seq}"

                if path:
                    print(f"  Saved {path}")
                else:
                    print("  Capture failed")

                log.record(
                    id=bag_id,
                    status=resolution.status,
                    trigger_source=event.source,
                    trigger_raw=event.raw,
                    capture_ok=bool(path),
                    capture_path=str(path) if path else "",
                    tag_id=resolution.tag_id or "",
                    flight_number=resolution.flight_number or "",
                    destination=resolution.destination or "",
                )
                live.add(
                    id=bag_id,
                    timestamp=iso(trigger_ts),
                    status=resolution.status,
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
