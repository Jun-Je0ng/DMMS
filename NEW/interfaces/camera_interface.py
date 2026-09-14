import cv2
from config.settings import settings
import time


mul_id = settings.get("active_mul")
mul_cfg = settings.get("mul_settings")[str(mul_id)]

laser_port = mul_cfg["laser_serial_port"]
barcode_port = mul_cfg["barcode_serial_port"]
camera_index = mul_cfg["camera_device_index"]
resolution = mul_cfg["camera_resolution"]
laser_timeout = mul_cfg["laser_timeout"]

def take_photo():
    # cam_index = settings.get("camera_device_index")
    cam_index = camera_index
    # resolution = settings.get("camera_resolution")
    resolution = resolution

    cap = cv2.VideoCapture(cam_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])

    time.sleep(0.2)  # allow camera to adjust

    ret, frame = cap.read()
    cap.release()

    filename = f"static/bag_photos/{int(time.time())}.jpg"
    cv2.imwrite(filename, frame)

    return filename


def preview_camera():
    # cam_index = settings.get("camera_device_index")
    cam_index = camera_index
    # resolution = settings.get("camera_resolution")
    resolution = resolution

    cap = cv2.VideoCapture(cam_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])

    print("Press 'q' to quit preview")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Camera read failed")
            break

        cv2.imshow("Camera Preview", frame)

        # Quit preview
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
