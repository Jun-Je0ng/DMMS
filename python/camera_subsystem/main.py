import argparse
import csv
import itertools
import shutil
import time
from pathlib import Path

from camera_capture import CameraCapture
from event_log import EventLog
from trigger_source import SerialTriggerSource, SimulatedTriggerSource

FLIGHTS_FILE = Path(__file__).parent / "flights.csv"


def load_flight_cycle():
    with open(FLIGHTS_FILE, newline="") as f:
        flights = list(csv.DictReader(f))
    if not flights:
        raise ValueError(f"{FLIGHTS_FILE} has no rows")
    return itertools.cycle(flights)


def build_trigger_source(args):
    if args.mode == "simulate":
        interval = None if args.auto_interval is None else tuple(args.auto_interval)
        return SimulatedTriggerSource(interval=interval)
    return SerialTriggerSource(port=args.port, baud=args.baud)


def main():
    parser = argparse.ArgumentParser(description="Camera subsystem: photo capture on sensor trigger.")
    parser.add_argument(
        "--mode",
        choices=["simulate", "serial"],
        default="simulate",
        help="simulate: no hardware needed. serial: read triggers from the Arduino.",
    )
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Serial port for the Arduino (serial mode).")
    parser.add_argument("--baud", type=int, default=9600)
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
    args = parser.parse_args()

    trigger_source = build_trigger_source(args)
    flight_cycle = load_flight_cycle()

    log_path = Path(args.log_file)
    if log_path.exists():
        log_path.unlink()
    log = EventLog(args.log_file)

    save_dir_path = Path(args.save_dir)
    if save_dir_path.exists():
        shutil.rmtree(save_dir_path)

    with CameraCapture(camera_index=args.camera_index, save_dir=args.save_dir) as camera:
        print(f"Camera subsystem running in {args.mode} mode. Ctrl+C to stop.")
        try:
            for event in trigger_source.events():
                print(f"Trigger from {event.source}: {event.raw}")
                if args.delay > 0:
                    time.sleep(args.delay)
                path = camera.capture(label=event.raw)
                if path:
                    flight = next(flight_cycle)
                    print(f"Saved {path} for {flight['flight_number']}")
                    log.record(
                        event.source, event.raw, True, str(path),
                        flight["flight_number"], flight["destination"],
                    )
                else:
                    print("Capture failed")
                    log.record(event.source, event.raw, False)
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            log.close()


if __name__ == "__main__":
    main()
