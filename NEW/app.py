import time
import traceback

from interfaces.laser_interface import LaserInterface
from interfaces.barcode_interface import BarcodeInterface
from hardware.event_manager import EventManager
from config.settings import settings


mul_id = settings.get("active_mul")
mul_cfg = settings.get("mul_settings")[str(mul_id)]

laser_port = mul_cfg["laser_serial_port"]
barcode_port = mul_cfg["barcode_serial_port"]
camera_index = mul_cfg["camera_device_index"]
resolution = mul_cfg["camera_resolution"]
laser_timeout = mul_cfg["laser_timeout"]


def main():
    print("Starting hardware interface system...")

    laser = None
    barcode = None
    events = None

    try:
        # Initialize hardware interfaces
        laser = LaserInterface()
        barcode = BarcodeInterface()

        # Initialize event manager
        events = EventManager()

        print("System ready. Listening for events...")

        while True:
            # --- LASER EVENT ---
            if laser.read_laser():
                print("[LASER] TRIGGER detected")
                events.handle_laser_trigger()

            # --- BARCODE EVENT ---
            code = barcode.read_barcode()

            if code:
                print(f"[BARCODE] Read: {code}")
                events.handle_barcode_scan(code)

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nShutting down system...")

    except Exception:
        print("[ERROR] Exception in main loop:")
        traceback.print_exc()

    finally:
        print("[SHUTDOWN] Stopping barcode listener...")

        if barcode is not None:
            try:
                barcode.stop()
            except Exception:
                traceback.print_exc()

        print("[SHUTDOWN] Stopping laser...")

        if laser is not None:
            try:
                laser.stop()
            except AttributeError:
                pass
            except Exception:
                traceback.print_exc()

        print("[SHUTDOWN] System stopped.")


if __name__ == "__main__":
    main()
