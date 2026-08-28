import argparse
import csv
import itertools
import random
import shutil
import time
from datetime import datetime
from pathlib import Path

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
        interval = None if args.auto_interval is None else tuple(args.auto_interval)
        return SimulatedTriggerSource(interval=interval)
    return SerialTriggerSource(port=args.port, baud=args.baud, token=args.trigger_token)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def main():
    parser = argparse.ArgumentParser(
        description="DMMS integration: ultrasonic sensor + barcode scanner + camera -> events for the GUI."
    )
    parser.add_argument(
        "--mode",
        choices=["simulate", "serial"],
        default="simulate",
        help="simulate: no Arduino needed. serial: read triggers from the Arduino.",
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
        default=None,
        metavar=("MIN", "MAX"),
        help="Simulate mode: fire automatically at a random interval in seconds instead of waiting for Enter.",
    )
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait after a trigger before taking the photo, to allow for belt travel from sensor to camera.",
    )
    parser.add_argument("--save-dir", default="captures")
    parser.add_argument("--log-file", default="events_with_flights.csv")
    parser.add_argument(
        "--live-file",
        default="live_events.json",
        help="JSON file written after every event, in the shape gui/app.js polls for.",
    )
    parser.add_argument(
        "--barcode-mode",
        choices=["simulate", "scanner", "off"],
        default="simulate",
        help="simulate: no scanner needed, generates a fake tag like 'KR712-MEL' per trigger. "
        "scanner: run the real barcode_subsystem scanner (needs the physical scanner attached). "
        "off: no barcode subsystem at all -- every bag needs a manual check.",
    )
    parser.add_argument(
        "--pair-window",
        type=float,
        default=4.0,
        help="Seconds a scan and a trigger can be apart and still be considered the same bag.",
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

    seq = 0

    def log_unmatched_scan(ts: float, barcode: str):
        nonlocal seq
        seq += 1
        bag_id = f"scan_{seq}"
        print(f"Unmatched scan (no bag nearby): {barcode}")
        log.record(id=bag_id, status="unmatched_scan", tag_id=barcode)
        live.add(id=bag_id, timestamp=iso(ts), status="unmatched_scan")

    listener = None
    if args.barcode_mode == "scanner":
        listener = BarcodeListener(pairer, on_unmatched=log_unmatched_scan)
        listener.start()
        print("Barcode scanner subsystem started.")
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

                if sim_barcode is not None:
                    tag = sim_barcode.next_tag()
                    # A little jitter so it isn't suspiciously exact, well
                    # inside pair_window so it still reliably matches.
                    scan_ts = trigger_ts + random.uniform(-0.5, 0.5)
                    pairer.submit_scan(ts=scan_ts, barcode=tag)
                    print(f"  Barcode: {tag}")

                if args.delay > 0:
                    time.sleep(args.delay)
                path = camera.capture(label=event.raw)

                # Resolved after the capture delay (not immediately at the
                # trigger) so a scan that arrives during that window has
                # already reached the pairer -- resolve_trigger still uses
                # trigger_ts as the reference point, just called a little
                # later to give pending scans more of a chance to show up.
                resolution = pairer.resolve_trigger(trigger_ts)

                seq += 1
                bag_id = f"bag_{seq}"

                if path:
                    print(f"Saved {path} ({resolution.status}, tag={resolution.tag_id})")
                else:
                    print(f"Capture failed ({resolution.status}, tag={resolution.tag_id})")

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
