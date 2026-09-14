from interfaces.camera_interface import preview_camera, take_photo

def main():
    print("Starting camera preview...")
    preview_camera()

    print("Taking a test photo...")
    path = take_photo()
    print(f"Photo saved to: {path}")

if __name__ == "__main__":
    main()
