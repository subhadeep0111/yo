/*
 * VocalGuard — MAX30102 Sensor Reader
 * Arduino Uno + MAX30102 (SpO2 & Heart Rate)
 * 
 * Wiring:
 *   MAX30102 VIN  → Arduino 3.3V
 *   MAX30102 GND  → Arduino GND
 *   MAX30102 SDA  → Arduino A4
 *   MAX30102 SCL  → Arduino A5
 * 
 * Outputs JSON over Serial at 115200 baud:
 *   {"heart_rate":75,"spo2":98,"voice_stress_level":0.0,"timestamp":"millis"}
 * 
 * Required Library: SparkFun MAX3010x Pulse and Proximity Sensor Library
 *   Install via: Arduino IDE → Sketch → Include Library → Manage Libraries
 *   Search: "SparkFun MAX3010x" and install it.
 */

#include <Wire.h>
#include "MAX30105.h"           // SparkFun MAX3010x library (works for MAX30102)
#include "heartRate.h"          // Heart rate calculation algorithm

MAX30105 particleSensor;

// ── Heart Rate Detection ──
const byte RATE_SIZE = 4;       // Moving average window
byte rates[RATE_SIZE];
byte rateSpot = 0;
long lastBeat = 0;
float beatsPerMinute = 0;
int beatAvg = 0;

// ── SpO2 Variables ──
long irValue = 0;
long redValue = 0;
int spo2 = 0;

// ── Timing ──
unsigned long lastSendTime = 0;
const unsigned long SEND_INTERVAL = 500;  // Send data every 500ms

void setup() {
    Serial.begin(115200);
    Serial.println("{\"status\":\"initializing\"}");

    // Initialize MAX30102
    if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
        Serial.println("{\"error\":\"MAX30102 not found. Check wiring.\"}");
        while (1);  // Halt if sensor not found
    }

    // Configure sensor
    particleSensor.setup();                     // Default settings
    particleSensor.setPulseAmplitudeRed(0x0A);  // Low red LED for proximity detection
    particleSensor.setPulseAmplitudeGreen(0);   // Turn off green LED
    
    // For SpO2 reading, configure both LEDs
    particleSensor.enableDIETEMPRDY();          // Enable die temperature reading

    Serial.println("{\"status\":\"ready\"}");
}

void loop() {
    // Read sensor values
    irValue = particleSensor.getIR();
    redValue = particleSensor.getRed();

    // ── Heart Rate Detection ──
    if (checkForBeat(irValue) == true) {
        long delta = millis() - lastBeat;
        lastBeat = millis();

        beatsPerMinute = 60 / (delta / 1000.0);

        // Only accept reasonable heart rates
        if (beatsPerMinute > 20 && beatsPerMinute < 255) {
            rates[rateSpot++ % RATE_SIZE] = (byte)beatsPerMinute;

            // Calculate average
            beatAvg = 0;
            for (byte x = 0; x < RATE_SIZE; x++) {
                beatAvg += rates[x];
            }
            beatAvg /= RATE_SIZE;
        }
    }

    // ── SpO2 Estimation ──
    // Simplified SpO2 calculation from IR and Red LED ratio
    if (irValue > 50000) {  // Finger is detected
        float ratio = (float)redValue / (float)irValue;
        // Linear approximation of SpO2 (simplified)
        spo2 = constrain((int)(104 - 17 * ratio), 0, 100);
    } else {
        spo2 = 0;  // No finger detected
    }

    // ── Send JSON every SEND_INTERVAL ms ──
    if (millis() - lastSendTime >= SEND_INTERVAL) {
        lastSendTime = millis();

        // Only send valid data (finger must be on sensor)
        if (irValue > 50000) {
            Serial.print("{\"heart_rate\":");
            Serial.print(beatAvg);
            Serial.print(",\"spo2\":");
            Serial.print(spo2);
            Serial.print(",\"voice_stress_level\":0.0");  // Calculated by frontend mic
            Serial.print(",\"pitch\":0.0");                // Calculated by frontend mic
            Serial.print(",\"volume\":0.0");               // Calculated by frontend mic
            Serial.print(",\"timestamp\":\"");
            Serial.print(millis());
            Serial.println("\"}");
        } else {
            // No finger — send status message
            Serial.println("{\"status\":\"no_finger\",\"message\":\"Place finger on sensor\"}");
        }
    }
}
