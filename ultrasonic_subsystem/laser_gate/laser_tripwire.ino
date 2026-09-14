/*
  Laser Tripwire
  --------------
  - Laser diode connected to pin 13 (always on, forms the beam)
  - Light-dependent resistor (LDR) / photoresistor module output on A0
  - Alarm LED on pin 8 lights up (and a message prints to Serial)
    when the beam is broken (light level drops below threshold)

  Wiring:
    Laser module   -> VCC/GND + signal pin to D13 (or just power it
                      from 5V/GND if it's an always-on laser module,
                      and use D13 only if you want to switch it via code)
    LDR module     -> VCC, GND, and OUT (digital or analog) -> A0
    Alarm LED      -> Anode through ~220ohm resistor -> D8, cathode -> GND

  Adjust THRESHOLD based on your sensor's readings (use Serial Monitor
  to see live values and calibrate).
*/

const int laserPin  = 13;   // Laser output pin
const int sensorPin = A0;   // Light sensor input pin
const int ledPin    = 8;    // Alarm LED (detection indicator)

int threshold = 500;        // Trip threshold - CALIBRATE THIS (0-1023)
int sensorValue = 0;

void setup() {
  pinMode(laserPin, OUTPUT);
  pinMode(ledPin, OUTPUT);
  pinMode(sensorPin, INPUT);

  digitalWrite(laserPin, HIGH); // Turn laser ON and leave it on
  digitalWrite(ledPin, LOW);

  Serial.begin(9600);
  Serial.println("Laser Tripwire Initialized...");
  Serial.println("Calibrating... keep the beam clear.");
  delay(2000);

  // Optional auto-calibration: take a baseline reading with the beam
  // uninterrupted, then set threshold a bit below it.
  long total = 0;
  for (int i = 0; i < 20; i++) {
    total += analogRead(sensorPin);
    delay(50);
  }
  int baseline = total / 20;
  threshold = baseline * 0.7; // trip if reading falls below 70% of baseline

  Serial.print("Baseline light level: ");
  Serial.println(baseline);
  Serial.print("Trip threshold set to: ");
  Serial.println(threshold);
  Serial.println("Tripwire armed.");
}

void loop() {
  sensorValue = analogRead(sensorPin);

  if (sensorValue < threshold) {
    // Beam broken - trigger alarm
    digitalWrite(ledPin, HIGH);
    Serial.print("!!! BEAM BROKEN !!!  Sensor value: ");
    Serial.println(sensorValue);
  } else {
    // Beam intact - all clear
    digitalWrite(ledPin, LOW);
  }

  // Uncomment to constantly monitor raw sensor values for calibration:
  // Serial.println(sensorValue);

  delay(50); // small delay for stability
}
