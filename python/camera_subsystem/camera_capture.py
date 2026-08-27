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
