import serial
from config.settings import settings

mul_id = settings.get("active_mul")
mul_cfg = settings.get("mul_settings")[str(mul_id)]

laser_port = mul_cfg["laser_serial_port"]
barcode_port = mul_cfg["barcode_serial_port"]
camera_index = mul_cfg["camera_device_index"]
resolution = mul_cfg["camera_resolution"]
laser_timeout = mul_cfg["laser_timeout"]

class BarcodeInterface:
    def __init__(self):
        # port = settings.get("barcode_serial_port")
        port = barcode_port
        self.ser = serial.Serial(port, 9600, timeout=0.1)

    def read_barcode(self):
        line = self.ser.readline().decode(errors="ignore").strip()
        if line:
            return line  # raw barcode string
        return None
