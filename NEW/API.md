# DMMS test-data API

JSON API under `/api/v1` (code: `api.py`, registered in `web.py`).
Use it instead of `seed.py`. The server runs on port 5000.

## One call: build a whole scenario

```bash
curl -X POST localhost:5000/api/v1/setup -H "Content-Type: application/json" -d '{
  "mul_id": 1,
  "flights": [
    {"flight_number": "QF401", "destination": "Perth",
     "departure_time": "2026-10-30 14:00", "gate_number": "A1",
     "cans": 1, "bags": 10},
    {"flight_number": "QF402", "destination": "Cairns", "bags": 5}
  ]
}'
```

Creates the flights (reuses a flight with the same number), a CAN per flight
in that MUL, and `bags` barcodes per flight (`B-QF401-01` ... `B-QF401-10`,
override with `barcode_prefix`). Each call adds more CANs, so use `"cans": 0`
when re-running for an existing flight.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/flights` | POST takes one object or a list |
| GET/PATCH/DELETE | `/flights/<id>` | |
| GET/POST | `/cans` | `{"mul_id":1,"flight_number":"QF401","count":2}`; omit `mul_id` for an inactive CAN; `GET ?mul_id=` |
| PATCH/DELETE | `/cans/<id>` | change `mul_id` / `flight_id` / `flight_number` |
| GET/POST | `/muls` | `{"mul_name":"MUL 2"}` |
| GET/POST | `/users` | `{"user_name":"Sam","user_type":"worker"}` |
| GET/POST | `/bag-routes` | the barcode lookups the scanner uses; list via `"barcodes":[...]` or `"prefix"+"count"` |
| DELETE | `/bag-routes/<barcode>` | |
| GET/POST | `/bags` | POST simulates a scan (see below); `GET ?mul_id=&status=` |
| DELETE | `/bags/<id>` | |

### Creating a bag directly

```bash
# uses the bag_route for flight / MUL / destination
curl -X POST localhost:5000/api/v1/bags -H "Content-Type: application/json" \
     -d '{"barcode": "B-QF401-01"}'

# no barcode -> lands in Needs Attention
curl -X POST localhost:5000/api/v1/bags -H "Content-Type: application/json" -d '{"mul_id": 1}'

# force a status / CAN
curl -X POST localhost:5000/api/v1/bags -H "Content-Type: application/json" \
     -d '{"barcode":"X1","flight_number":"QF401","status":"in_can","can_id":3}'
```

Errors return `{"error": "..."}` with 400 (bad input), 404 (unknown
flight/MUL/CAN) or 409 (duplicate barcode / constraint).

There is no authentication, and the server listens on 0.0.0.0, so anyone on
the network can call this. Fine for a demo LAN; add a token check before
exposing it anywhere else.

## Tag registration (demo day)

`/admin/register` (Admin dashboard -> "Register Bag Tags"): pick a flight,
scan tags, each one is attached to that flight. Backed by
`POST /api/v1/register-scan {"barcode","flight_id","mul_id"}`.

While the page is open it sends a heartbeat to `/api/v1/register-mode`, and
`interfaces/barcode_interface.py` ignores keystrokes so registration scans
don't create live bags. Close the page (or wait 10s) to go back to normal.
The hardware listener now accepts `B-...` codes *and* any 8+ character
letters/digits/hyphens token containing a digit (e.g. 10-digit airline tags).
