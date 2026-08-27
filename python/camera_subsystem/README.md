# camera_subsystem

Placeholder for Rian's camera capture code (RGB snapshot taken at the moment
the laser/ultrasonic sensor detects baggage entering the MUL).

Once wired up, this folder will hold the captured bag images. The `photo_path`
field in event records (see `events_with_flights.csv` and `gui/mock-data.json`)
is a path relative to this folder, e.g. `photo_path: "2026-08-27/bag_0042.jpg"`
resolves to `python/camera_subsystem/2026-08-27/bag_0042.jpg`.

Nothing here yet — this is a scaffold so the GUI and backend can agree on the
path convention before the capture code lands.
