# import time
# import threading

# from interfaces.camera_interface import take_photo
# from config.settings import settings
# from database.db import insert_bag_record


# class EventManager:
#     def __init__(self):
#         self.settings_ = settings.get(
#             "mul_settings"
#         )[str(settings.get("active_mul"))]

#         self.laser_timeout = self.settings_["laser_timeout"]
#         self.mul_id = settings.get("active_mul")

#         self.last_laser_time = None
#         self.laser_waiting = False
#         self.pending_timer = None

#     # ========================================================
#     # LASER
#     # ========================================================

#     def handle_laser_trigger(self):
#         print("[EVENT] Laser triggered")

#         self.last_laser_time = time.time()
#         self.laser_waiting = True

#         # Cancel an existing timer if one somehow exists
#         if self.pending_timer is not None:
#             self.pending_timer.cancel()

#         self.pending_timer = threading.Timer(
#             self.laser_timeout,
#             self._laser_timeout
#         )

#         self.pending_timer.start()

#     # ========================================================
#     # BARCODE
#     # ========================================================

#     def handle_barcode_scan(self, barcode_value):
#         print(f"Barcode scanned: {barcode_value}")

#         if self.laser_waiting:
#             self.pending_timer.cancel()
#             self.laser_waiting = False

#             self._process_bag(
#                 barcode=barcode_value,
#                 no_barcode=False
#             )

#         else:
#             self._process_bag(
#                 barcode=barcode_value,
#                 no_barcode=False
#             )


#     # ========================================================
#     # LASER TIMEOUT
#     # ========================================================

#     def _laser_timeout(self):
#         print("Laser timeout — no barcode detected")

#         self.laser_waiting = False

#         self._process_bag(
#             barcode=None,
#             no_barcode=True
#         )


#     # ========================================================
#     # PROCESS BAG
#     # ========================================================

#     def _process_bag(
#         self,
#         barcode,
#         no_barcode=False
#     ):
#         try:

#             # ------------------------------------------------
#             # Take photograph
#             # ------------------------------------------------

#             photo_path = take_photo()

#             # ------------------------------------------------
#             # Determine initial status
#             # ------------------------------------------------

#             initial_status = (
#                 "needs_attention"
#                 if no_barcode
#                 else "scanned"
#             )

#             # ------------------------------------------------
#             # Insert database record
#             # ------------------------------------------------

#             bag_id = insert_bag_record(
#                 barcode=barcode,
#                 mul_id=self.mul_id,
#                 manual_flag=False,
#                 photo_path=photo_path,
#                 initial_status=initial_status
#             )

#             # ------------------------------------------------
#             # Check database result
#             # ------------------------------------------------

#             if bag_id is None:
#                 print(
#                     "[BAG ERROR] "
#                     "Bag could not be processed"
#                 )
#                 return

#             # ------------------------------------------------
#             # Success
#             # ------------------------------------------------

#             if no_barcode:
#                 print(
#                     f"[BAG] Bag processed without barcode "
#                     f"(bag_id={bag_id})"
#                 )
#             else:
#                 print(
#                     f"[BAG] Bag processed "
#                     f"(bag_id={bag_id})"
#                 )

#         except Exception as e:
#             print(
#                 f"[BAG ERROR] Failed to process bag: {e}"
#             )

import time
import threading

from interfaces.camera_interface import take_photo
from config.settings import settings
from database.db import (
    insert_bag_record,
    get_bag_route
)


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
        print(f"[EVENT] Barcode scanned: {barcode_value}")

        if self.laser_waiting:

            if self.pending_timer is not None:
                self.pending_timer.cancel()

            self.laser_waiting = False

        self._process_bag(
            barcode=barcode_value,
            no_barcode=False
        )

    # ========================================================
    # LASER TIMEOUT
    # ========================================================

    def _laser_timeout(self):
        print("[EVENT] Laser timeout — no barcode detected")

        self.laser_waiting = False
        self.pending_timer = None

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
            # No barcode
            # ------------------------------------------------

            if no_barcode:

                bag_id = insert_bag_record(
                    barcode=None,
                    mul_id=self.mul_id,
                    flight_id=None,
                    final_destination=None,
                    manual_flag=False,
                    photo_path=photo_path,
                    initial_status="needs_attention"
                )

                if bag_id is not None:
                    print(
                        f"[BAG] Bag processed without barcode "
                        f"(bag_id={bag_id})"
                    )

                return

            # ------------------------------------------------
            # Look up barcode route
            # ------------------------------------------------

            route = get_bag_route(barcode)

            # ------------------------------------------------
            # Barcode not found
            # ------------------------------------------------

            if route is None:

                print(
                    f"[ROUTE] No route found for barcode: "
                    f"{barcode}"
                )

                bag_id = insert_bag_record(
                    barcode=barcode,
                    mul_id=self.mul_id,
                    flight_id=None,
                    final_destination=None,
                    manual_flag=False,
                    photo_path=photo_path,
                    initial_status="needs_attention"
                )

                if bag_id is not None:
                    print(
                        f"[BAG] Unknown barcode sent to "
                        f"needs attention "
                        f"(bag_id={bag_id})"
                    )

                return

            # ------------------------------------------------
            # Route found
            # ------------------------------------------------

            route_mul_id = route["mul_id"]
            flight_id = route["flight_id"]
            final_destination = route["final_destination"]

            print(
                f"[ROUTE] {barcode} → "
                f"MUL {route_mul_id}, "
                f"flight {flight_id}"
            )

            # ------------------------------------------------
            # Barcode belongs to another MUL
            # ------------------------------------------------

            if route_mul_id != self.mul_id:

                print(
                    f"[ROUTE] Barcode {barcode} belongs to "
                    f"MUL {route_mul_id}, "
                    f"but scanner is on MUL {self.mul_id}"
                )

                bag_id = insert_bag_record(
                    barcode=barcode,
                    mul_id=self.mul_id,
                    flight_id=None,
                    final_destination=None,
                    manual_flag=False,
                    photo_path=photo_path,
                    initial_status="needs_attention"
                )

                if bag_id is not None:
                    print(
                        f"[BAG] Wrong-MUL barcode sent to "
                        f"needs attention "
                        f"(bag_id={bag_id})"
                    )

                return

            # ------------------------------------------------
            # Normal routed bag
            # ------------------------------------------------

            bag_id = insert_bag_record(
                barcode=barcode,
                mul_id=self.mul_id,
                flight_id=flight_id,
                final_destination=final_destination,
                manual_flag=False,
                photo_path=photo_path,
                initial_status="scanned"
            )

            if bag_id is not None:
                print(
                    f"[BAG] Bag processed "
                    f"(bag_id={bag_id})"
                )

        except Exception as e:

            print(
                f"[BAG ERROR] Failed to process bag: {e}"
            )
