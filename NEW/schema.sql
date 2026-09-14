PRAGMA foreign_keys = ON;

-- ============================
-- FLIGHTS TABLE
-- ============================
CREATE TABLE flights (
    flight_id INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_number TEXT NOT NULL,
    departure_time TEXT,
    destination TEXT,
    gate_number TEXT
);

-- ============================
-- MUL TABLE
-- ============================
CREATE TABLE mul (
    mul_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mul_name TEXT NOT NULL
);

-- ============================
-- CANS TABLE
-- ============================
CREATE TABLE cans (
    can_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mul_id INTEGER NOT NULL,
    flight_id INTEGER NOT NULL,

    FOREIGN KEY (mul_id) REFERENCES mul(mul_id) ON DELETE CASCADE,
    FOREIGN KEY (flight_id) REFERENCES flights(flight_id) ON DELETE SET NULL
);

-- ============================
-- BAGS TABLE
-- ============================
CREATE TABLE bags (
    bag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    bag_short_id INTEGER NOT NULL,
    final_destination TEXT,
    flight_id INTEGER NOT NULL,
    mul_id INTEGER NOT NULL,

    FOREIGN KEY (flight_id) REFERENCES flights(flight_id) ON DELETE SET NULL,
    FOREIGN KEY (mul_id) REFERENCES mul(mul_id) ON DELETE CASCADE,

    -- bag_short_id must be unique per MUL
    UNIQUE (mul_id, bag_short_id)
);

-- ============================
-- USERS TABLE
-- ============================
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    user_type TEXT CHECK(user_type IN ('admin', 'worker')) NOT NULL
);
