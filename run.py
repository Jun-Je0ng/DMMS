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

import config    # noqa: E402
import settings  # noqa: E402
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
    flights  = _load_flights()
    eff      = settings.load(config)   # config.py defaults + gui/settings.json overrides
    trigger_source = SerialTriggerSource(
        port=eff.SERIAL_PORT,
        baud=eff.SERIAL_BAUD,
        token=eff.TRIGGER_TOKEN,
    )

    # No manifest to resolve a real tag against yet — cycle through flights in
    # order.  Replace the lambda with a real lookup (API, database, etc.) when
    # a flight-manifest integration is available.
    flight_cycle  = itertools.cycle(flights)
    flight_lookup = lambda _tag_id: next(flight_cycle)  # noqa: E731

    pairer   = Pairer(
        pair_window=eff.PAIR_WINDOW,
        loop_window=eff.LOOP_WINDOW,
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

    # Camera opens BEFORE the barcode listener starts (rather than the other
    # way around) for two reasons: a bad camera index fails loudly here at
    # startup instead of during the first bag of the shift, and it means
    # on_unmatched_scan below (a closure over `camera`) always has a real,
    # already-open camera to call — no risk of a scan's fallback-capture
    # timer firing before `camera` exists.
    with CameraCapture(camera_index=eff.CAMERA_INDEX, save_dir=str(save_dir)) as camera:

        def on_late_match(bag_id: str, resolution):
            # A scan showed up within PAIR_WINDOW seconds of a trigger that
            # had already been logged as 'manual' (the sensor-then-barcode
            # ordering — see Pairer.on_late_match). Upgrade the board entry
            # in place rather than leaving it stuck in Needs Attention.
            print(f"  Late match: {bag_id} paired with {resolution.tag_id} after the fact "
                  f"({resolution.status}) — updating the board")
            live.update(
                bag_id, status=resolution.status,
                flight_number=resolution.flight_number,
                destination=resolution.destination,
            )
            log.record(
                id=bag_id, status=resolution.status,
                tag_id=resolution.tag_id or "",
                flight_number=resolution.flight_number or "",
                destination=resolution.destination or "",
                trigger_source="late-match",
            )

        pairer.on_late_match = on_late_match

        def on_unmatched_scan(ts: float, barcode: str):
            nonlocal seq
            seq += 1
            bag_id = f"scan_{run_id}_{seq}"
            # The sensor never claimed this scan within PAIR_WINDOW seconds —
            # most likely it failed to trigger for this bag. Fall back to
            # taking a photo right now so the bag still gets a picture on
            # the board, then route it to its CAN using the barcode's flight
            # info. Because this only fires PAIR_WINDOW seconds after the
            # scan, two barcode scans closer together than that will overlap
            # here — space scans further apart than PAIR_WINDOW (Settings
            # page → Timing) if you're relying on this path routinely.
            flight        = flight_lookup(barcode)
            flight_number = flight.get("flight_number")
            destination   = flight.get("destination")
            path = camera.capture(label=barcode)
            print(f"Unmatched scan (no bag nearby): {barcode} "
                  f"({flight_number or '?'}) — "
                  f"{'photo captured' if path else 'capture failed'}")
            log.record(
                id=bag_id, status="unmatched_scan", tag_id=barcode,
                trigger_source="barcode-fallback", trigger_raw=barcode,
                capture_ok=bool(path), capture_path=str(path) if path else "",
                flight_number=flight_number or "", destination=destination or "",
            )
            live.add(
                id=bag_id, timestamp=_iso(ts), status="unmatched_scan",
                photo_path=str(path) if path else None,
                flight_number=flight_number, destination=destination,
            )

        def on_raw_scan(ts: float, barcode: str):
            activity.add("scan", ts, barcode)

        listener = BarcodeListener(pairer, on_unmatched=on_unmatched_scan, on_scan=on_raw_scan)
        listener.start()
        print("Barcode scanner subsystem started — always on, system-wide.")

        print(f"DMMS running — serial port {eff.SERIAL_PORT}, camera index {eff.CAMERA_INDEX}. Ctrl+C to stop.")
        try:
            for event in trigger_source.events():
                trigger_ts = time.time()
                print(f"Trigger: {event.raw}")
                activity.add("trigger", trigger_ts, event.raw)

                seq += 1
                bag_id = f"bag_{run_id}_{seq}"

                # bag_id opts this trigger into a late-match second chance —
                # see on_late_match above and Pairer.resolve_trigger's
                # docstring. Usual real-world ordering is sensor-then-scan,
                # so this call very often can't see the matching scan yet
                # and will say 'manual' here; on_late_match fixes it up a
                # moment later if a scan does show up in time.
                resolution = pairer.resolve_trigger(trigger_ts, bag_id=bag_id)

                if resolution.tag_id:
                    print(f"  Barcode: {resolution.tag_id} ({resolution.status})")
                else:
                    print(f"  No barcode match yet ({resolution.status} for now)")

                if eff.PHOTO_DELAY > 0:
                    time.sleep(eff.PHOTO_DELAY)
                path = camera.capture(label=event.raw)

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
