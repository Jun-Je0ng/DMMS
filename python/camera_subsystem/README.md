# camera_subsystem

Rian's sensor-trigger + camera-capture subsystem: on each trigger it takes a
photo, assigns a flight from `flights.csv` (round-robin — this is a stand-in
until barcode-based identification is merged in), and appends a row to
`events_with_flights.csv`.

```
python3 main.py --mode simulate            # press Enter to simulate each bag
python3 main.py --mode simulate --auto-interval 1 3   # fires on its own
python3 main.py --mode serial --port /dev/ttyUSB0 --baud 9600   # real Arduino
```

`mock_events.json` is a static fixture in the GUI's target shape —
`{ id, timestamp, status, flight_number, destination, photo_path }` — used by
`gui/` while `events_with_flights.csv` isn't being actively populated. There's
no `tag_id`/barcode field yet; that's Aaron's barcode-scanner subsystem, not
merged in here.
