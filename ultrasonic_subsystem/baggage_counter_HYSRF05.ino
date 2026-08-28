/*
  ============================================================
  Baggage Pass Counter using HY-SRF05 Ultrasonic Sensor
  Conveyor speed: 0.5 m/s
  ============================================================

  LOGIC:
    - Sensor pings continuously, measuring distance below it.
    - If distance drops below a threshold (i.e. something is
      under the sensor, blocking/shortening the echo path),
      we start a timer.
    - If that "object present" condition holds continuously for
      ~1 second (PRESENCE_TIME_MS), we flag "Baggage passed":
         -> Serial print
         -> LED turns ON
    - LED turns back OFF once the object clears (distance goes
      back above threshold) or after a max hold time as a safety
      fallback.
    - A short lockout after each confirmed bag prevents the same
      bag re-triggering the count as it finishes passing under
      the sensor.

  WIRING:
    HY-SRF05 VCC   -> Arduino 5V
    HY-SRF05 GND   -> Arduino GND
    HY-SRF05 TRIG  -> Arduino Digital Pin 3
    HY-SRF05 ECHO  -> Arduino Digital Pin 4
                       (ECHO is 5V logic - fine for 5V Arduinos.
                        If using a 3.3V board, use a voltage divider
                        or logic level shifter on ECHO.)

    LED (+ ~220ohm resistor) -> Digital Pin 8 -> GND

  MOUNTING:
    Mount sensor facing straight down above the conveyor belt.
    Measure and set EMPTY_BELT_DISTANCE_CM to the distance from
    the sensor face to the bare belt surface below it.
  ============================================================
*/

// ---------------- CONFIGURATION ----------------
const uint8_t TRIG_PIN = 3;
const uint8_t ECHO_PIN = 4;
const uint8_t LED_PIN  = 8;

// Distance (cm) from sensor to the EMPTY belt surface.
// Measure this yourself once the sensor is mounted.
const float EMPTY_BELT_DISTANCE_CM = 30.0;

// A reading at least this many cm LESS than the empty-belt
// distance is considered "object present" under the sensor.
const float DETECTION_MARGIN_CM = 5.0;

// How long the "object present" condition must hold continuously
// before it's confirmed as a baggage pass.
const unsigned long PRESENCE_TIME_MS = 1000;

// Safety cap: if something sits under the sensor way too long
// (jam, stopped belt, etc.) release the LED anyway after this,
// so it doesn't stay stuck on indefinitely. Set 0 to disable.
const unsigned long MAX_HOLD_MS = 5000;

// After a confirmed pass, ignore new detections for this long,
// so the tail end of the same bag doesn't retrigger a second count.
const unsigned long LOCKOUT_MS = 500;

// How often to ping the sensor.
const unsigned long PING_INTERVAL_MS = 50;

// ---------------- STATE ----------------
unsigned long bagCount = 0;

bool objectPresent = false;        // current raw reading state
unsigned long presentSinceMs = 0;  // when object was first seen
bool bagFlagged = false;           // has this presence already been counted?

bool ledOn = false;

unsigned long lastPingMs = 0;
unsigned long lockoutUntilMs = 0;

// ---------------- FUNCTIONS ----------------

// Returns distance in cm, or -1.0 if no echo received (timeout / out of range)
float readDistanceCM() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // 30ms timeout ~= max range ~5m, more than enough headroom
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 30000UL);

  if (duration == 0) {
    return -1.0; // no echo detected within timeout
  }

  // speed of sound ~343 m/s -> 0.0343 cm/us, round trip so /2
  float distanceCm = (duration * 0.0343) / 2.0;
  return distanceCm;
}

void setup() {
  Serial.begin(9600);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(TRIG_PIN, LOW);
  digitalWrite(LED_PIN, LOW);

  Serial.println(F("============================================"));
  Serial.println(F(" Baggage Counter - HY-SRF05 Ultrasonic"));
  Serial.print(F(" Empty belt distance: "));
  Serial.print(EMPTY_BELT_DISTANCE_CM);
  Serial.println(F(" cm"));
  Serial.print(F(" Detection threshold: < "));
  Serial.print(EMPTY_BELT_DISTANCE_CM - DETECTION_MARGIN_CM);
  Serial.println(F(" cm"));
  Serial.print(F(" Presence confirm time: "));
  Serial.print(PRESENCE_TIME_MS);
  Serial.println(F(" ms"));
  Serial.println(F(" System ready. Monitoring conveyor..."));
  Serial.println(F("============================================"));
}

void loop() {
  unsigned long now = millis();

  // --- Ping sensor at fixed interval (non-blocking) ---
  if (now - lastPingMs >= PING_INTERVAL_MS) {
    lastPingMs = now;

    float distance = readDistanceCM();
    float threshold = EMPTY_BELT_DISTANCE_CM - DETECTION_MARGIN_CM;

    // Treat "no echo" (-1.0) as "nothing detected" (object out of range / gone)
    bool rawDetect = (distance > 0 && distance < threshold);

    if (rawDetect && now >= lockoutUntilMs) {
      if (!objectPresent) {
        // just arrived
        objectPresent = true;
        presentSinceMs = now;
        bagFlagged = false;
      } else {
        // still present - check if it's been long enough to confirm
        unsigned long heldFor = now - presentSinceMs;

        if (!bagFlagged && heldFor >= PRESENCE_TIME_MS) {
          // ---- CONFIRMED: baggage passed ----
          bagFlagged = true;
          bagCount++;

          digitalWrite(LED_PIN, HIGH);
          ledOn = true;

          Serial.print(F("Baggage passed. Count = "));
          Serial.print(bagCount);
          Serial.print(F("  | held "));
          Serial.print(heldFor);
          Serial.print(F(" ms | t = "));
          Serial.print(now / 1000.0, 2);
          Serial.println(F(" s"));
        }
        else if (MAX_HOLD_MS > 0 && heldFor >= MAX_HOLD_MS && ledOn) {
          // Safety release if something sits there too long (e.g. jam)
          digitalWrite(LED_PIN, LOW);
          ledOn = false;
          Serial.println(F("Warning: object held too long - LED released (possible jam)."));
        }
      }
    }
    else {
      // Nothing detected right now (or within post-count lockout)
      if (objectPresent) {
        // object just cleared
        objectPresent = false;

        if (bagFlagged) {
          // bag finished passing - turn LED off, start lockout
          digitalWrite(LED_PIN, LOW);
          ledOn = false;
          lockoutUntilMs = now + LOCKOUT_MS;
        }
        // if it left before reaching 1s presence, it was noise/too fast -
        // nothing was flagged, nothing to undo
      }
    }
  }
}