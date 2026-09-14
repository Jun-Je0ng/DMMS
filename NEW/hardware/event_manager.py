import time
import threading
from interfaces.camera_interface import take_photo
from config.settings import settings
from database.db import insert_bag_record

class EventManager:
    def __init__(self):
        self.laser_timeout = settings.get("laser_timeout")
        self.mul_id = settings.get("mul_id")

        self.last_laser_time = None
        self.laser_waiting = False
        self.pending_timer = None

    def handle_laser_trigger(self):
        print("Laser triggered")
        self.last_laser_time = time.time()
        self.laser_waiting = True

        self.pending_timer = threading.Timer(self.laser_timeout, self._laser_timeout)
        self.pending_timer.start()

    def handle_barcode_scan(self, barcode_value):
        print(f"Barcode scanned: {barcode_value}")

        if self.laser_waiting:
            self.pending_timer.cancel()
            self.laser_waiting = False
            self._process_bag(barcode_value, manual=False)
        else:
            self._process_bag(barcode_value, manual=False)

    def _laser_timeout(self):
        print("Laser timeout — no barcode detected")
        self.laser_waiting = False
        self._process_bag(None, manual=True)

    def _process_bag(self, barcode_value, manual):
        photo_path = take_photo()

        insert_bag_record(
            bag_short_id=barcode_value,
            mul_id=self.mul_id,
            manual_flag=manual,
            photo_path=photo_path
        )

        print("Bag processed")

