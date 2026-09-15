import threading
from pynput import keyboard


class BarcodeInterface:
    def __init__(self):
        print("[BARCODE] HID keyboard mode enabled")

        self.buffer = []
        self._last_barcode = None
        self._lock = threading.Lock()

        self.listener = keyboard.Listener(
            on_press=self._on_press
        )

        self.listener.start()

    def _on_press(self, key):
        with self._lock:
            if key == keyboard.Key.enter:
                barcode = "".join(self.buffer).strip()
                self.buffer = []

                if barcode:
                    self._last_barcode = barcode

                return

            if key == keyboard.Key.backspace:
                if self.buffer:
                    self.buffer.pop()
                return

            char = getattr(key, "char", None)

            if char and char.isprintable():
                self.buffer.append(char)

    def read_barcode(self):
        with self._lock:
            barcode = self._last_barcode
            self._last_barcode = None

        return barcode

    def stop(self):
        print("[BARCODE] Stopping keyboard listener...")

        if self.listener is not None:
            self.listener.stop()
            self.listener.join(timeout=2)
            self.listener = None

        print("[BARCODE] Keyboard listener stopped.")
