import serial
import time

port = "COM2"  # The sending side of your virtual pair

ser = serial.Serial(port, 9600, timeout=0.1)

print("Connected to", port)
print("Press:")
print("  1 = send TRIGGER")
print("  2 = send RESTORED")
print("  3 = send fake barcode")
print("  q = quit")

while True:
    cmd = input("> ")

    if cmd == "1":
        ser.write(b"TRIGGER\n")
        print("Sent TRIGGER")

    elif cmd == "2":
        ser.write(b"RESTORED\n")
        print("Sent RESTORED")

    elif cmd == "3":
        barcode = "1234567890123"
        ser.write((barcode + "\n").encode())
        print("Sent barcode:", barcode)

    elif cmd == "q":
        break

    else:
        print("Unknown command")

ser.close()
