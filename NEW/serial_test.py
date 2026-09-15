# import serial
# import time
# import msvcrt

# port = "COM2"

# ser = serial.Serial(port, 9600, timeout=0.1)

# print("Connected to", port)
# print("Press:")
# print("  1 = send TRIGGER")
# print("  2 = send RESTORED")
# print("  3 = send fake barcode")
# print("  q = quit")


# def send_hid(text):
#     for ch in text:
#         msvcrt.putwch(ch)
#         time.sleep(0.01)  # simulate scanner speed
#     msvcrt.putwch('\r')  # simulate Enter key

# while True:
#     cmd = input("> ")

#     if cmd == "1":
#         ser.write(b"TRIGGER\n")
#         print("Sent TRIGGER")

#     elif cmd == "2":
#         ser.write(b"RESTORED\n")
#         print("Sent RESTORED")

#     elif cmd == "3":
#         barcode = "1234567890123"
#         send_hid(barcode)
#         print("Sent HID barcode:", barcode)

#     elif cmd == "q":
#         break

#     else:
#         print("Unknown command")

# ser.close()


import serial
import tkinter as tk
from tkinter import messagebox


PORT = "COM2"
BAUDRATE = 9600


class HardwareTestPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("DMMS Hardware Test")
        self.root.geometry("400x300")

        try:
            self.ser = serial.Serial(
                PORT,
                BAUDRATE,
                timeout=0.1
            )
        except serial.SerialException as e:
            messagebox.showerror(
                "Serial Error",
                f"Could not open {PORT}:\n\n{e}"
            )
            root.destroy()
            return

        # ----------------------------------------------------
        # Title
        # ----------------------------------------------------

        tk.Label(
            root,
            text="DMMS Hardware Test",
            font=("Arial", 18, "bold")
        ).pack(pady=(20, 5))

        tk.Label(
            root,
            text=f"Serial: {PORT} @ {BAUDRATE}",
            font=("Arial", 10)
        ).pack(pady=(0, 20))

        # ----------------------------------------------------
        # Laser buttons
        # ----------------------------------------------------

        tk.Button(
            root,
            text="LASER TRIGGER",
            command=self.send_trigger,
            bg="#ff4444",
            fg="white",
            font=("Arial", 13, "bold"),
            width=25,
            height=2
        ).pack(pady=5)

        tk.Button(
            root,
            text="LASER RESTORED",
            command=self.send_restored,
            bg="#44aa44",
            fg="white",
            font=("Arial", 13, "bold"),
            width=25,
            height=2
        ).pack(pady=5)

        # ----------------------------------------------------
        # Barcode button
        # ----------------------------------------------------

        tk.Button(
            root,
            text="SEND TEST BARCODE",
            command=self.send_barcode,
            bg="#4488cc",
            fg="white",
            font=("Arial", 13, "bold"),
            width=25,
            height=2
        ).pack(pady=5)

        # ----------------------------------------------------
        # Status
        # ----------------------------------------------------

        self.status = tk.Label(
            root,
            text="Ready",
            font=("Arial", 10)
        )

        self.status.pack(pady=15)

        root.protocol(
            "WM_DELETE_WINDOW",
            self.close
        )

    # ========================================================
    # LASER
    # ========================================================

    def send_trigger(self):
        self.ser.write(b"TRIGGER\n")

        self.status.config(
            text="Sent: TRIGGER"
        )

        print("[TEST] Sent TRIGGER")

    def send_restored(self):
        self.ser.write(b"RESTORED\n")

        self.status.config(
            text="Sent: RESTORED"
        )

        print("[TEST] Sent RESTORED")

    # ========================================================
    # BARCODE
    # ========================================================

    def send_barcode(self):
        barcode = "1234567890123"

        # NOTE:
        # This uses Windows keyboard simulation.
        # It is kept only as a convenient barcode test.

        import msvcrt
        import time

        for char in barcode:
            msvcrt.putwch(char)
            time.sleep(0.01)

        msvcrt.putwch("\r")

        self.status.config(
            text=f"Sent barcode: {barcode}"
        )

        print(
            f"[TEST] Sent HID barcode: {barcode}"
        )

    # ========================================================
    # CLOSE
    # ========================================================

    def close(self):
        try:
            if self.ser.is_open:
                self.ser.close()
        finally:
            self.root.destroy()


root = tk.Tk()

panel = HardwareTestPanel(root)

root.mainloop()