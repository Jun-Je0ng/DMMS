PRAGMA foreign_keys = ON;

-- ============================================================
-- DROP EXISTING TABLES
-- ============================================================

DROP TABLE IF EXISTS bag_events;
DROP TABLE IF EXISTS bag_status;
DROP TABLE IF EXISTS bags;
DROP TABLE IF EXISTS cans;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS mul;
DROP TABLE IF EXISTS flights;


-- ============================================================
-- FLIGHTS
-- ============================================================

CREATE TABLE flights (
    flight_id INTEGER PRIMARY KEY AUTOINCREMENT,

    flight_number TEXT NOT NULL,

    departure_time TEXT,

    destination TEXT,

    gate_number TEXT
);


-- ============================================================
-- MUL
-- ============================================================

CREATE TABLE mul (
    mul_id INTEGER PRIMARY KEY AUTOINCREMENT,

    mul_name TEXT NOT NULL
);


-- ============================================================
-- CANS
-- ============================================================

CREATE TABLE cans (
    can_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- NULL means this CAN is not currently assigned to any MUL
    -- ("inactive" on the CAN assignment page).
    mul_id INTEGER,

    flight_id INTEGER,

    FOREIGN KEY (mul_id)
        REFERENCES mul(mul_id)
        ON DELETE SET NULL,

    FOREIGN KEY (flight_id)
        REFERENCES flights(flight_id)
        ON DELETE SET NULL
);


-- ============================================================
-- BAGS
-- ============================================================

CREATE TABLE bags (
    bag_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Actual barcode from the physical scanner.
    -- Can be NULL when a bag has no readable barcode.
    barcode TEXT,

    -- Small human/operator-facing number.
    -- Unique only within a MUL.
    short_id INTEGER NOT NULL,

    final_destination TEXT,

    flight_id INTEGER,

    mul_id INTEGER NOT NULL,

    photo_path TEXT,

    scanned_at INTEGER NOT NULL
        DEFAULT (strftime('%s', 'now')),

    FOREIGN KEY (flight_id)
        REFERENCES flights(flight_id)
        ON DELETE SET NULL,

    FOREIGN KEY (mul_id)
        REFERENCES mul(mul_id)
        ON DELETE CASCADE,

    UNIQUE (mul_id, short_id),

    -- A physical barcode should identify only one bag.
    -- NULL values are allowed for bags without barcodes.
    UNIQUE (barcode)
);


-- ============================================================
-- BAG STATUS
-- ============================================================

CREATE TABLE bag_status (
    bag_id INTEGER PRIMARY KEY,

    status TEXT NOT NULL
        CHECK (
            status IN (
                'scanned',
                'assigned',
                'in_can',
                'loaded',
                'needs_attention',
                'resolved',
                'rejected'
            )
        ),

    loaded_by INTEGER,

    loaded_at INTEGER,

    can_id INTEGER,

    FOREIGN KEY (bag_id)
        REFERENCES bags(bag_id)
        ON DELETE CASCADE,

    FOREIGN KEY (loaded_by)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    FOREIGN KEY (can_id)
        REFERENCES cans(can_id)
        ON DELETE SET NULL
);


-- ============================================================
-- BAG EVENTS
-- ============================================================

CREATE TABLE bag_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,

    bag_id INTEGER NOT NULL,

    event_type TEXT NOT NULL,

    user_id INTEGER,

    timestamp INTEGER NOT NULL
        DEFAULT (strftime('%s', 'now')),

    details TEXT,

    FOREIGN KEY (bag_id)
        REFERENCES bags(bag_id)
        ON DELETE CASCADE,

    FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE SET NULL
);


-- ============================================================
-- USERS
-- ============================================================

CREATE TABLE users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,

    user_name TEXT NOT NULL,

    user_type TEXT NOT NULL
        CHECK (
            user_type IN (
                'admin',
                'worker'
            )
        )
);

CREATE TABLE bag_routes (
    barcode TEXT PRIMARY KEY,

    flight_id INTEGER,

    mul_id INTEGER NOT NULL,

    final_destination TEXT,

    FOREIGN KEY (flight_id)
        REFERENCES flights(flight_id)
        ON DELETE SET NULL,

    FOREIGN KEY (mul_id)
        REFERENCES mul(mul_id)
        ON DELETE CASCADE
);


-- ============================================================
-- INITIAL TEST DATA
-- ============================================================

INSERT INTO mul (
    mul_id,
    mul_name
)
VALUES (
    1,
    'MUL 1'
);


INSERT INTO users (
    user_id,
    user_name,
    user_type
)
VALUES (
    1,
    'Test Worker',
    'worker'
);


-- ============================================================
-- TEST FLIGHT
-- ============================================================

INSERT INTO flights (
    flight_number,
    departure_time,
    destination,
    gate_number
)
VALUES (
    'TEST001',
    '2026-09-15 12:00',
    'Melbourne',
    'A1'
);


-- ============================================================
-- TEST CAN
-- ============================================================

INSERT INTO cans (
    mul_id,
    flight_id
)
VALUES (
    1,
    1
);