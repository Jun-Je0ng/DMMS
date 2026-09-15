import cv2
import time

from config.settings import settings


mul_id = settings.get("active_mul")
mul_cfg = settings.get("mul_settings")[str(mul_id)]

camera_index = mul_cfg["camera_device_index"]
resolution = mul_cfg["camera_resolution"]


def take_photo():
    cap = cv2.VideoCapture(camera_index)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])

    time.sleep(0.2)

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError(
            f"Failed to capture image from camera {camera_index}"
        )

    filename = (
        f"static/bag_photos/{int(time.time())}.jpg"
    )

    success = cv2.imwrite(filename, frame)

    if not success:
        raise RuntimeError(
            f"Failed to save photo: {filename}"
        )

    return filename


def preview_camera():
    cap = cv2.VideoCapture(camera_index)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])

    print("Press 'q' to quit preview")

    while True:
        ret, frame = cap.read()

        if not ret:
            print("Camera read failed")
            break

        cv2.imshow("Camera Preview", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
