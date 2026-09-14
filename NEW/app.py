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
    
    # Initialize hardware interfaces
    laser = LaserInterface()
    barcode = BarcodeInterface()
    
    # Initialize event manager
    events = EventManager()

    print("System ready. Listening for events...")

    while True:
        try:
            # --- LASER EVENT ---
            if laser.read_laser():
                print("[LASER] TRIGGER detected")
                events.handle_laser_trigger()

            # --- BARCODE EVENT ---
            code = barcode.read_barcode()
            if code:
                print(f"[BARCODE] Read: {code}")
                events.handle_barcode_scan(code)

            # Loop speed (adjustable)
            time.sleep(0.01)  # 100 Hz polling

        except KeyboardInterrupt:
            print("Shutting down system...")
            break

        except Exception as e:
            print("[ERROR] Exception in main loop:")
            traceback.print_exc()
            time.sleep(1)  # prevent crash loops

if __name__ == "__main__":
    main()
