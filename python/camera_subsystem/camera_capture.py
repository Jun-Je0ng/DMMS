from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2


class CameraCapture:
    def __init__(self, camera_index: int = 0, save_dir: str = "captures"):
        self.camera_index = camera_index
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self._cap = None

    def open(self):
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open camera index {self.camera_index}")

        # Request the camera's maximum resolution. Many USB webcams only
        # reach their highest resolutions in a compressed format (MJPG) --
        # raw/YUYV is often capped much lower by USB bandwidth -- so set MJPG
        # first, then ask for an intentionally oversized frame size; V4L2
        # clamps both to whatever the camera actually supports.
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 99999)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 99999)
        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"Camera opened at {actual_w}x{actual_h}")

    def close(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def capture(self, label: str = "") -> Optional[Path]:
        """Grab one frame and save it. Returns the saved path, or None on failure."""
        if self._cap is None:
            raise RuntimeError("Camera not open, call open() first")
        # Discard one buffered frame so the saved photo reflects the current moment.
        self._cap.read()
        ok, frame = self._cap.read()
        if not ok:
            return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        suffix = f"_{label}" if label else ""
        path = self.save_dir / f"bag_{stamp}{suffix}.jpg"
        cv2.imwrite(str(path), frame)
        return path
