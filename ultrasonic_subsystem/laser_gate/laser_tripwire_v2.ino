/*
  Laser Tripwire — debounced edge-triggered output
  -------------------------------------------------
  Only sends ONE serial message per beam-break event (falling edge of the
  light level), plus one "RESTORED" message when the beam comes back.
  A COOLDOWN_MS guard prevents rapid re-triggers from noise or a slow-
  moving object hovering in the beam.

  Wiring:
    Laser module   -> VCC/GND (always on), or D13 if you want code control
    LDR module     -> VCC, GND, OUT -> A0
    Alarm LED      -> Anode through ~220 Ω -> D8, cathode -> GND

  Serial protocol (9600 baud):
    "TRIGGER"    — beam just broken  (one line per event)
    "RESTORED"   — beam just restored
    Calibration lines at startup (ignored by the host)
*/

const int laserPin  = 13;
const int sensorPin = A0;
const int ledPin    = 8;

// ── Tunable constants ──────────────────────────────────────────────────────
// How long (ms) to ignore further triggers after one fires.
// Raise this if a slow-moving bag produces multiple events.
const unsigned long COOLDOWN_MS = 2000;

// Fraction of the baseline to use as the trip threshold (0.0–1.0).
// Lower = more sensitive, higher = less sensitive.
const float THRESHOLD_FACTOR = 0.70;
// ──────────────────────────────────────────────────────────────────────────

int threshold = 500;

// Debounce state
bool beamBroken       = false;   // current stable state
unsigned long lastTriggerMs = 0; // time of last TRIGGER sent

void setup() {
  pinMode(laserPin, OUTPUT);
  pinMode(ledPin,   OUTPUT);
  pinMode(sensorPin, INPUT);

  digitalWrite(laserPin, HIGH); // laser on
  digitalWrite(ledPin,   LOW);

  Serial.begin(9600);
  Serial.println("Laser Tripwire Initializing...");
  Serial.println("Calibrating — keep the beam clear for 1 second.");
  delay(1000);

  // Auto-calibrate: average 20 readings with beam unbroken.
  long total = 0;
  for (int i = 0; i < 20; i++) {
    total += analogRead(sensorPin);
    delay(50);
  }
  int baseline = total / 20;
  threshold = (int)(baseline * THRESHOLD_FACTOR);

  Serial.print("Baseline: ");
  Serial.print(baseline);
  Serial.print("  Threshold: ");
  Serial.println(threshold);
  Serial.println("READY");
}

void loop() {
  int raw = analogRead(sensorPin);
  bool nowBroken = (raw < threshold);
  unsigned long now = millis();

  if (nowBroken && !beamBroken) {
    // Falling edge: beam just broke
    if (now - lastTriggerMs >= COOLDOWN_MS) {
      beamBroken   = true;
      lastTriggerMs = now;
      digitalWrite(ledPin, HIGH);
      Serial.println("TRIGGER");
    }
  } else if (!nowBroken && beamBroken) {
    // Rising edge: beam restored
    beamBroken = false;
    digitalWrite(ledPin, LOW);
    Serial.println("RESTORED");
  }

  // Uncomment to stream raw values for calibration:
  // Serial.println(raw);

  delay(20); // ~50 Hz sampling — fast enough for a bag on a belt
}
