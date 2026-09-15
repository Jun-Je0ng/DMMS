import time
import threading

from interfaces.camera_interface import take_photo
from config.settings import settings
from database.db import insert_bag_record


class EventManager:
    def __init__(self):
        self.settings_ = settings.get(
            "mul_settings"
        )[str(settings.get("active_mul"))]

        self.laser_timeout = self.settings_["laser_timeout"]
        self.mul_id = settings.get("active_mul")

        self.last_laser_time = None
        self.laser_waiting = False
        self.pending_timer = None

    # ========================================================
    # LASER
    # ========================================================

    def handle_laser_trigger(self):
        print("[EVENT] Laser triggered")

        self.last_laser_time = time.time()
        self.laser_waiting = True

        # Cancel an existing timer if one somehow exists
        if self.pending_timer is not None:
            self.pending_timer.cancel()

        self.pending_timer = threading.Timer(
            self.laser_timeout,
            self._laser_timeout
        )

        self.pending_timer.start()

    # ========================================================
    # BARCODE
    # ========================================================

    def handle_barcode_scan(self, barcode_value):
        print(f"Barcode scanned: {barcode_value}")

        if self.laser_waiting:
            self.pending_timer.cancel()
            self.laser_waiting = False

            self._process_bag(
                barcode=barcode_value,
                no_barcode=False
            )

        else:
            self._process_bag(
                barcode=barcode_value,
                no_barcode=False
            )


    # ========================================================
    # LASER TIMEOUT
    # ========================================================

    def _laser_timeout(self):
        print("Laser timeout — no barcode detected")

        self.laser_waiting = False

        self._process_bag(
            barcode=None,
            no_barcode=True
        )


    # ========================================================
    # PROCESS BAG
    # ========================================================

    def _process_bag(
        self,
        barcode,
        no_barcode=False
    ):
        try:

            # ------------------------------------------------
            # Take photograph
            # ------------------------------------------------

            photo_path = take_photo()

            # ------------------------------------------------
            # Determine initial status
            # ------------------------------------------------

            initial_status = (
                "needs_attention"
                if no_barcode
                else "scanned"
            )

            # ------------------------------------------------
            # Insert database record
            # ------------------------------------------------

            bag_id = insert_bag_record(
                barcode=barcode,
                mul_id=self.mul_id,
                manual_flag=False,
                photo_path=photo_path,
                initial_status=initial_status
            )

            # ------------------------------------------------
            # Check database result
            # ------------------------------------------------

            if bag_id is None:
                print(
                    "[BAG ERROR] "
                    "Bag could not be processed"
                )
                return

            # ------------------------------------------------
            # Success
            # ------------------------------------------------

            if no_barcode:
                print(
                    f"[BAG] Bag processed without barcode "
                    f"(bag_id={bag_id})"
                )
            else:
                print(
                    f"[BAG] Bag processed "
                    f"(bag_id={bag_id})"
                )

        except Exception as e:
            print(
                f"[BAG ERROR] Failed to process bag: {e}"
            )
