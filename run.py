# """
# run.py — hardware runner.

# Barcode flow:

#     Laser trigger
#         ↓
#     bag is physically present
#         ↓
#     wait for barcode
#         ↓
#     barcode → data/bag_ids.json → flight
#         ↓
#     camera
#         ↓
#     live_events.json

# Fallback:

#     barcode arrives with no laser waiting
#         ↓
#     immediate camera capture

# Run:
#     python run.py
# """

# import json
# import shutil
# import sys
# import threading
# import time
# from datetime import datetime
# from pathlib import Path

# # ── Local imports ─────────────────────────────────────────────────────────────

# _ROOT = Path(__file__).resolve().parent
# _SERVER = _ROOT / "server"
# sys.path.insert(0, str(_SERVER))

# import config  # noqa: E402
# import settings  # noqa: E402
# from hardware import CameraCapture, SerialTriggerSource  # noqa: E402
# from pipeline import ActivityFeed, EventLog, LiveFeed  # noqa: E402
# from barcode import BarcodeListener  # noqa: E402


# # ── Bag database ──────────────────────────────────────────────────────────────

# _BAG_IDS_FILE = _ROOT / "data" / "bag_ids.json"


# def _load_bag_ids() -> dict:
#     """
#     Load data/bag_ids.json.

#     Example:

#     [
#         {
#             "bagID": "12345",
#             "flight": "VA867",
#             "destination": "BNE"
#         },
#         {
#             "bagID": "12346",
#             "flight": "QF12",
#             "destination": "LAX"
#         }
#     ]
#     """

#     if not _BAG_IDS_FILE.exists():
#         raise FileNotFoundError(
#             f"{_BAG_IDS_FILE} not found.\n"
#             "Create data/bag_ids.json with bagID, flight "
#             "and optionally destination."
#         )

#     try:
#         data = json.loads(
#             _BAG_IDS_FILE.read_text(encoding="utf-8")
#         )
#     except json.JSONDecodeError as exc:
#         raise ValueError(
#             f"{_BAG_IDS_FILE} contains invalid JSON: {exc}"
#         ) from exc

#     if not isinstance(data, list):
#         raise ValueError(
#             "data/bag_ids.json must contain a JSON array."
#         )

#     lookup = {}

#     for entry in data:
#         if not isinstance(entry, dict):
#             continue

#         bag_id = str(
#             entry.get("bagID", "")
#         ).strip()

#         if not bag_id:
#             continue

#         lookup[bag_id] = {
#             "flight_number": str(
#                 entry.get("flight", "")
#             ).strip(),
#             "destination": str(
#                 entry.get("destination", "")
#             ).strip(),
#         }

#     if not lookup:
#         raise ValueError(
#             "data/bag_ids.json contains no valid bag entries."
#         )

#     return lookup


# # ── Helpers ───────────────────────────────────────────────────────────────────


# def _iso(ts: float) -> str:
#     return datetime.fromtimestamp(
#         ts
#     ).isoformat(
#         timespec="seconds"
#     )


# # ── Main ──────────────────────────────────────────────────────────────────────


# def main():

#     bag_lookup = _load_bag_ids()

#     print(
#         f"Loaded {len(bag_lookup)} bag IDs "
#         f"from {_BAG_IDS_FILE}"
#     )

#     eff = settings.load(config)

#     trigger_source = SerialTriggerSource(
#         port=eff.SERIAL_PORT,
#         baud=eff.SERIAL_BAUD,
#         token=eff.TRIGGER_TOKEN,
#     )

#     # ── Output files ──────────────────────────────────────────────────────────

#     log_path = Path(
#         "data/events_with_flights.csv"
#     )

#     if log_path.exists():
#         log_path.unlink()

#     log = EventLog(
#         str(log_path)
#     )

#     live = LiveFeed(
#         "data/live_events.json"
#     )

#     activity = ActivityFeed(
#         "data/activity.json"
#     )

#     # ── Capture directory ─────────────────────────────────────────────────────

#     save_dir = Path(
#         "data/captures"
#     )

#     if save_dir.exists():
#         shutil.rmtree(save_dir)

#     save_dir.mkdir(
#         parents=True,
#         exist_ok=True,
#     )

#     run_id = datetime.now().strftime(
#         "%Y%m%d%H%M%S"
#     )

#     seq = 0

#     # ── Pairing state ─────────────────────────────────────────────────────────

#     # When a laser trigger fires, this contains the bag event
#     # currently waiting for a barcode.
#     pending_trigger = None

#     # Protects pending_trigger because barcode.py calls its
#     # callback from another thread.
#     pairing_lock = threading.Lock()

#     # ── Camera ─────────────────────────────────────────────────────────────────

#     with CameraCapture(
#         camera_index=eff.CAMERA_INDEX,
#         save_dir=str(save_dir),
#     ) as camera:

#         # ── Barcode handler ──────────────────────────────────────────────────

#         def on_barcode_scan(
#             ts: float,
#             barcode: str,
#         ):
#             """
#             Handle a barcode scan.

#             Case 1:
#                 A laser trigger is waiting.
#                 → attach barcode to that trigger.
#                 → laser path takes the photo.

#             Case 2:
#                 No laser trigger is waiting.
#                 → barcode acts as fallback.
#                 → take photo immediately.
#             """

#             nonlocal seq
#             nonlocal pending_trigger

#             barcode = str(
#                 barcode
#             ).strip()

#             if not barcode:
#                 return

#             print(
#                 f"Barcode scanned: {barcode}"
#             )

#             activity.add(
#                 "scan",
#                 ts,
#                 barcode,
#             )

#             # ── Look up bag ──────────────────────────────────────────────────

#             bag = bag_lookup.get(
#                 barcode
#             )

#             if bag is None:

#                 print(
#                     f"  UNKNOWN BAG ID: {barcode}"
#                 )

#                 activity.add(
#                     "scan_unknown",
#                     ts,
#                     barcode,
#                 )

#                 return

#             flight_number = bag.get(
#                 "flight_number",
#                 "",
#             )

#             destination = bag.get(
#                 "destination",
#                 "",
#             )

#             print(
#                 f"  Bag {barcode} → "
#                 f"{flight_number or '?'}"
#                 f"{' → ' + destination if destination else ''}"
#             )

#             # ── Try to pair with laser ──────────────────────────────────────

#             with pairing_lock:

#                 trigger = pending_trigger

#                 if trigger is not None:

#                     # Claim the waiting laser event.
#                     pending_trigger = None

#             if trigger is not None:

#                 # Barcode belongs to the laser-triggered bag.
#                 trigger["barcode"] = barcode
#                 trigger["flight_number"] = flight_number
#                 trigger["destination"] = destination
#                 trigger["barcode_ts"] = ts
#                 trigger["event"].set()

#                 print(
#                     f"  Paired with laser trigger "
#                     f"{trigger['bag_event_id']}"
#                 )

#                 return

#             # ── No laser waiting → barcode fallback ─────────────────────────

#             seq += 1

#             bag_event_id = (
#                 f"bag_{run_id}_{seq}"
#             )

#             bag_event_id = bag.get("bagID")

#             print(
#                 f"  No laser waiting — "
#                 f"barcode fallback capture"
#             )

#             path = camera.capture(
#                 label=barcode
#             )

#             print(
#                 f"  "
#                 f"{'Saved ' + str(path) if path else 'Capture failed'}"
#             )

#             log.record(
#                 id=bag_event_id,
#                 status="matched",
#                 trigger_source="barcode",
#                 trigger_raw=barcode,
#                 capture_ok=bool(path),
#                 capture_path=str(path)
#                 if path
#                 else "",
#                 tag_id=barcode,
#                 flight_number=flight_number,
#                 destination=destination,
#             )

#             live.add(
#                 id=bag_event_id,
#                 timestamp=_iso(ts),
#                 status="matched",
#                 photo_path=path.as_posix()
#                 if path
#                 else None,
#                 flight_number=flight_number,
#                 destination=destination,
#             )

#             print(
#                 f"  Added to board: "
#                 f"#{barcode}"
#             )

#         # ── Barcode listener ──────────────────────────────────────────────────

#         listener = BarcodeListener(
#             on_scan=on_barcode_scan,
#         )

#         listener.start()

#         print(
#             "Barcode scanner subsystem started — "
#             "always on, system-wide."
#         )

#         print(
#             "Laser + barcode pairing enabled."
#         )

#         print(
#             f"  Laser waits up to "
#             f"{eff.PAIR_WINDOW}s for barcode."
#         )

#         print(
#             "  Barcode without laser → "
#             "immediate fallback capture."
#         )

#         print(
#             f"DMMS running — serial port "
#             f"{eff.SERIAL_PORT}, "
#             f"camera index {eff.CAMERA_INDEX}. "
#             f"Ctrl+C to stop."
#         )

#         # ── Sensor trigger loop ──────────────────────────────────────────────

#         try:

#             for event in trigger_source.events():

#                 trigger_ts = time.time()

#                 print(
#                     f"Trigger: {event.raw}"
#                 )

#                 activity.add(
#                     "trigger",
#                     trigger_ts,
#                     event.raw,
#                 )

#                 seq += 1

#                 bag_event_id = (
#                     f"bag_{run_id}_{seq}"
#                 )

#                 # Event used by barcode callback
#                 # to wake this trigger.
#                 barcode_event = threading.Event()

#                 trigger_info = {
#                     "bag_event_id": bag_event_id,
#                     "event": barcode_event,
#                     "barcode": None,
#                     "flight_number": "",
#                     "destination": "",
#                     "barcode_ts": None,
#                 }

#                 # ── Become the active laser trigger ─────────────────────────

#                 with pairing_lock:

#                     # If another trigger was somehow still waiting,
#                     # the previous one gets finalized as manual below.
#                     previous = pending_trigger

#                     pending_trigger = trigger_info

#                 if previous is not None:

#                     print(
#                         "  Warning: previous laser trigger "
#                         "was still waiting."
#                     )

#                 # ── Wait for barcode ────────────────────────────────────────

#                 got_barcode = barcode_event.wait(
#                     timeout=eff.PAIR_WINDOW
#                 )

#                 # ── Take ownership of trigger state ─────────────────────────

#                 with pairing_lock:

#                     if pending_trigger is trigger_info:

#                         pending_trigger = None

#                 # ── Barcode arrived ─────────────────────────────────────────

#                 if got_barcode:

#                     barcode = trigger_info["barcode"]
#                     flight_number = trigger_info[
#                         "flight_number"
#                     ]
#                     destination = trigger_info[
#                         "destination"
#                     ]

#                     status = "matched"

#                     print(
#                         f"  Barcode: {barcode} "
#                         f"({flight_number or '?'})"
#                     )

#                     capture_label = barcode

#                 # ── No barcode ──────────────────────────────────────────────

#                 else:

#                     barcode = ""
#                     flight_number = ""
#                     destination = ""

#                     status = "manual"

#                     print(
#                         f"  No barcode within "
#                         f"{eff.PAIR_WINDOW}s "
#                         f"(manual)"
#                     )

#                     capture_label = event.raw

#                 # ── Optional camera delay ───────────────────────────────────

#                 if eff.PHOTO_DELAY > 0:

#                     time.sleep(
#                         eff.PHOTO_DELAY
#                     )

#                 # ── Capture exactly once ────────────────────────────────────

#                 path = camera.capture(
#                     label=capture_label
#                 )

#                 print(
#                     f"  "
#                     f"{'Saved ' + str(path) if path else 'Capture failed'}"
#                 )

#                 # ── Log ─────────────────────────────────────────────────────

#                 log.record(
#                     id=bag_event_id,
#                     status=status,
#                     trigger_source=event.source,
#                     trigger_raw=event.raw,
#                     capture_ok=bool(path),
#                     capture_path=str(path)
#                     if path
#                     else "",
#                     tag_id=barcode,
#                     flight_number=flight_number,
#                     destination=destination,
#                 )

#                 # ── Live board ──────────────────────────────────────────────

#                 live.add(
#                     id=bag_event_id,
#                     timestamp=_iso(trigger_ts),
#                     status=status,
#                     photo_path=path.as_posix()
#                     if path
#                     else None,
#                     flight_number=flight_number,
#                     destination=destination,
#                 )

#         except KeyboardInterrupt:

#             print(
#                 "\nStopped."
#             )

#         finally:

#             listener.stop()
#             log.close()


# if __name__ == "__main__":
#     main()


"""
run.py — hardware runner.

Barcode flow:

    Laser trigger
        ↓
    bag is physically present
        ↓
    wait for barcode
        ↓
    barcode → data/bag_ids.json → flight
        ↓
    camera
        ↓
    live_events.json

Fallback:

    barcode arrives with no laser waiting
        ↓
    immediate camera capture

Important:
    The real bag ID from data/bag_ids.json is used as the event ID.
    No generated bag IDs are used once a barcode is known.

Run:
    python run.py
"""

import json
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ── Local imports ─────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent
_SERVER = _ROOT / "server"
sys.path.insert(0, str(_SERVER))

import config  # noqa: E402
import settings  # noqa: E402
from hardware import CameraCapture, SerialTriggerSource  # noqa: E402
from pipeline import ActivityFeed, EventLog, LiveFeed  # noqa: E402
from barcode import BarcodeListener  # noqa: E402


# ── Bag database ──────────────────────────────────────────────────────────────

_BAG_IDS_FILE = _ROOT / "data" / "bag_ids.json"


def _load_bag_ids() -> dict:
    """
    Load data/bag_ids.json.

    Example:

    [
        {
            "bagID": "12345",
            "flight": "VA867",
            "destination": "BNE"
        },
        {
            "bagID": "12346",
            "flight": "QF12",
            "destination": "LAX"
        }
    ]

    Returns:

    {
        "12345": {
            "bag_id": "12345",
            "flight_number": "VA867",
            "destination": "BNE"
        }
    }
    """

    if not _BAG_IDS_FILE.exists():
        raise FileNotFoundError(
            f"{_BAG_IDS_FILE} not found.\n"
            "Create data/bag_ids.json with bagID, flight "
            "and optionally destination."
        )

    try:
        data = json.loads(
            _BAG_IDS_FILE.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{_BAG_IDS_FILE} contains invalid JSON: {exc}"
        ) from exc

    if not isinstance(data, list):
        raise ValueError(
            "data/bag_ids.json must contain a JSON array."
        )

    lookup = {}

    for entry in data:
        if not isinstance(entry, dict):
            continue

        bag_id = str(
            entry.get("bagID", "")
        ).strip()

        if not bag_id:
            continue

        lookup[bag_id] = {
            "bag_id": bag_id,
            "flight_number": str(
                entry.get("flight", "")
            ).strip(),
            "destination": str(
                entry.get("destination", "")
            ).strip(),
        }

    if not lookup:
        raise ValueError(
            "data/bag_ids.json contains no valid bag entries."
        )

    return lookup


# ── Helpers ───────────────────────────────────────────────────────────────────


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(
        ts
    ).isoformat(
        timespec="seconds"
    )


# ── Main ──────────────────────────────────────────────────────────────────────


def main():

    bag_lookup = _load_bag_ids()

    print(
        f"Loaded {len(bag_lookup)} bag IDs "
        f"from {_BAG_IDS_FILE}"
    )

    eff = settings.load(config)

    trigger_source = SerialTriggerSource(
        port=eff.SERIAL_PORT,
        baud=eff.SERIAL_BAUD,
        token=eff.TRIGGER_TOKEN,
    )

    # ── Output files ──────────────────────────────────────────────────────────

    log_path = Path(
        "data/events_with_flights.csv"
    )

    if log_path.exists():
        log_path.unlink()

    log = EventLog(
        str(log_path)
    )

    live = LiveFeed(
        "data/live_events.json"
    )

    activity = ActivityFeed(
        "data/activity.json"
    )

    # ── Capture directory ─────────────────────────────────────────────────────

    save_dir = Path(
        "data/captures"
    )

    if save_dir.exists():
        shutil.rmtree(save_dir)

    save_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_id = datetime.now().strftime(
        "%Y%m%d%H%M%S"
    )

    # Only used for temporary laser-trigger bookkeeping.
    # It is NOT used as the final bag ID.
    trigger_seq = 0

    # ── Pairing state ─────────────────────────────────────────────────────────

    pending_trigger = None

    pairing_lock = threading.Lock()

    # ── Camera ─────────────────────────────────────────────────────────────────

    with CameraCapture(
        camera_index=eff.CAMERA_INDEX,
        save_dir=str(save_dir),
    ) as camera:

        # ── Barcode handler ──────────────────────────────────────────────────

        def on_barcode_scan(
            ts: float,
            barcode: str,
        ):
            """
            Handle a barcode scan.

            Case 1:
                Laser trigger is waiting.
                → attach barcode to that trigger.
                → laser path captures the photo.

            Case 2:
                No laser trigger is waiting.
                → barcode is a fallback.
                → capture immediately.

            The barcode itself is the real bag ID.
            """

            nonlocal pending_trigger

            barcode = str(
                barcode
            ).strip()

            if not barcode:
                return

            print(
                f"Barcode scanned: {barcode}"
            )

            activity.add(
                "scan",
                ts,
                barcode,
            )

            # ── Look up bag ──────────────────────────────────────────────────

            bag = bag_lookup.get(
                barcode
            )

            if bag is None:

                print(
                    f"  UNKNOWN BAG ID: {barcode}"
                )

                activity.add(
                    "scan_unknown",
                    ts,
                    barcode,
                )

                return

            # IMPORTANT:
            # This is the canonical ID used everywhere else.
            bag_id = bag["bag_id"]

            flight_number = bag.get(
                "flight_number",
                "",
            )

            destination = bag.get(
                "destination",
                "",
            )

            print(
                f"  Bag {bag_id} → "
                f"{flight_number or '?'}"
                f"{' → ' + destination if destination else ''}"
            )

            # ── Try to pair with laser ──────────────────────────────────────

            with pairing_lock:

                trigger = pending_trigger

                if trigger is not None:

                    pending_trigger = None

            if trigger is not None:

                # The barcode is now the REAL event ID.
                trigger["bag_id"] = bag_id
                trigger["barcode"] = barcode
                trigger["flight_number"] = flight_number
                trigger["destination"] = destination
                trigger["barcode_ts"] = ts

                trigger["event"].set()

                print(
                    f"  Paired with laser trigger "
                    f"{trigger['temporary_id']}"
                )

                print(
                    f"  Real bag ID: {bag_id}"
                )

                return

            # ── No laser waiting → barcode fallback ─────────────────────────

            print(
                "  No laser waiting — "
                "barcode fallback capture"
            )

            path = camera.capture(
                label=bag_id
            )

            print(
                f"  "
                f"{'Saved ' + str(path) if path else 'Capture failed'}"
            )

            # IMPORTANT:
            # Use the actual bag ID as the event ID.
            log.record(
                id=bag_id,
                status="matched",
                trigger_source="barcode",
                trigger_raw=barcode,
                capture_ok=bool(path),
                capture_path=str(path)
                if path
                else "",
                tag_id=barcode,
                flight_number=flight_number,
                destination=destination,
            )

            live.add(
                id=bag_id,
                timestamp=_iso(ts),
                status="matched",
                photo_path=path.as_posix()
                if path
                else None,
                flight_number=flight_number,
                destination=destination,
            )

            print(
                f"  Added to board: #{bag_id}"
            )

        # ── Barcode listener ──────────────────────────────────────────────────

        listener = BarcodeListener(
            on_scan=on_barcode_scan,
        )

        listener.start()

        print(
            "Barcode scanner subsystem started — "
            "always on, system-wide."
        )

        print(
            "Laser + barcode pairing enabled."
        )

        print(
            f"  Laser waits up to "
            f"{eff.PAIR_WINDOW}s for barcode."
        )

        print(
            "  Barcode without laser → "
            "immediate fallback capture."
        )

        print(
            f"DMMS running — serial port "
            f"{eff.SERIAL_PORT}, "
            f"camera index {eff.CAMERA_INDEX}. "
            f"Ctrl+C to stop."
        )

        # ── Sensor trigger loop ──────────────────────────────────────────────

        try:

            for event in trigger_source.events():

                trigger_ts = time.time()

                print(
                    f"Trigger: {event.raw}"
                )

                activity.add(
                    "trigger",
                    trigger_ts,
                    event.raw,
                )

                # Temporary ID only for the period where we do not
                # yet know the bag ID.
                trigger_seq += 1

                temporary_id = (
                    f"trigger_{run_id}_{trigger_seq}"
                )

                barcode_event = threading.Event()

                trigger_info = {
                    "temporary_id": temporary_id,
                    "event": barcode_event,

                    # These become populated when barcode arrives.
                    "bag_id": None,
                    "barcode": None,
                    "flight_number": "",
                    "destination": "",
                    "barcode_ts": None,
                }

                # ── Become the active laser trigger ─────────────────────────

                with pairing_lock:

                    previous = pending_trigger

                    pending_trigger = trigger_info

                if previous is not None:

                    print(
                        "  Warning: previous laser trigger "
                        "was still waiting."
                    )

                # ── Wait for barcode ────────────────────────────────────────

                got_barcode = barcode_event.wait(
                    timeout=eff.PAIR_WINDOW
                )

                # ── Take ownership of trigger state ─────────────────────────

                with pairing_lock:

                    if pending_trigger is trigger_info:

                        pending_trigger = None

                # ── Barcode arrived ─────────────────────────────────────────

                if got_barcode:

                    bag_id = trigger_info["bag_id"]

                    barcode = trigger_info["barcode"]

                    flight_number = (
                        trigger_info["flight_number"]
                    )

                    destination = (
                        trigger_info["destination"]
                    )

                    status = "matched"

                    print(
                        f"  Barcode: {barcode} "
                        f"({flight_number or '?'})"
                    )

                    print(
                        f"  Using bag ID: {bag_id}"
                    )

                    capture_label = bag_id

                # ── No barcode ──────────────────────────────────────────────

                else:

                    barcode = ""
                    bag_id = ""

                    flight_number = ""
                    destination = ""

                    status = "manual"

                    print(
                        f"  No barcode within "
                        f"{eff.PAIR_WINDOW}s "
                        f"(manual)"
                    )

                    # There is no real bag ID yet.
                    # The temporary trigger ID is ONLY used for
                    # this unresolved/manual event.
                    capture_label = event.raw

                # ── Optional camera delay ───────────────────────────────────

                if eff.PHOTO_DELAY > 0:

                    time.sleep(
                        eff.PHOTO_DELAY
                    )

                # ── Capture exactly once ────────────────────────────────────

                path = camera.capture(
                    label=capture_label
                )

                print(
                    f"  "
                    f"{'Saved ' + str(path) if path else 'Capture failed'}"
                )

                # ── Determine final event ID ────────────────────────────────

                if bag_id:

                    # Barcode was received.
                    # This is the canonical ID.
                    final_event_id = bag_id

                else:

                    # No barcode was received.
                    # There is no way to know the real bag ID yet.
                    # Keep a temporary/manual ID so the physical trigger
                    # is still visible on the board.
                    final_event_id = temporary_id

                # ── Log ─────────────────────────────────────────────────────

                log.record(
                    id=final_event_id,
                    status=status,
                    trigger_source=event.source,
                    trigger_raw=event.raw,
                    capture_ok=bool(path),
                    capture_path=str(path)
                    if path
                    else "",
                    tag_id=barcode,
                    flight_number=flight_number,
                    destination=destination,
                )

                # ── Live board ──────────────────────────────────────────────

                live.add(
                    id=final_event_id,
                    timestamp=_iso(trigger_ts),
                    status=status,
                    photo_path=path.as_posix()
                    if path
                    else None,
                    flight_number=flight_number,
                    destination=destination,
                )

                print(
                    f"  Added to board: "
                    f"#{final_event_id}"
                )

        except KeyboardInterrupt:

            print(
                "\nStopped."
            )

        finally:

            listener.stop()
            log.close()


if __name__ == "__main__":
    main()
