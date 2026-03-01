"""
VoxGuard — Sensor Simulator
Sends fake biometric data to the WebSocket endpoint for testing
the dashboard without actual Arduino hardware.
"""

import asyncio
import json
import random
import math
from datetime import datetime

import websockets


WS_URL = "ws://localhost:8000/ws/monitor"

# Simulation parameters
BASE_HR = 75
BASE_SPO2 = 98
BASE_PITCH = 440
BASE_VOLUME = 70
INTERVAL_SEC = 0.5  # send data every 500ms

time_counter = 0


def generate_vitals():
    """Generate realistic-looking vitals with occasional anomalies."""
    global time_counter
    time_counter += 1

    # Simulate a gradual performance arc (strain builds over time)
    performance_progress = min(time_counter / 120, 1.0)  # peaks at ~60 seconds

    # Heart rate: gradually increases during performance
    hr = random.randint(72, 78)

    # SpO2: stays mostly stable, occasional dips
    spo2 = int(BASE_SPO2 - 2 * performance_progress + random.gauss(0, 1))
    spo2 = max(85, min(100, spo2))

    # Pitch: varies with singing
    pitch = BASE_PITCH + 200 * math.sin(time_counter * 0.1) + random.gauss(0, 30)
    pitch = max(80, pitch)

    # Volume: fluctuates
    volume = BASE_VOLUME + 15 * math.sin(time_counter * 0.15) + random.gauss(0, 5)
    volume = max(0, min(100, volume))

    # Voice stress: builds up, with some variation
    stress = 0.2 + 0.5 * performance_progress + 0.15 * math.sin(time_counter * 0.2) + random.gauss(0, 0.05)
    stress = max(0, min(1.0, stress))

    # ── Simulate a critical event after ~50 seconds ──
    if 100 <= time_counter <= 110:
        hr = random.randint(72, 78)  # Kept normal as requested
        spo2 = random.randint(86, 91)
        stress = round(random.uniform(0.85, 0.99), 2)
        print(f"  🚨 SIMULATING CRITICAL EVENT (packet {time_counter})")

    return {
        "heart_rate": hr,
        "spo2": spo2,
        "voice_stress_level": round(stress, 3),
        "pitch": round(pitch, 1),
        "volume": round(volume, 1),
        "timestamp": datetime.now().isoformat(),
    }


async def run_simulator():
    print("🎤 VoxGuard Sensor Simulator")
    print(f"   Connecting to {WS_URL}...")

    async with websockets.connect(WS_URL) as ws:
        print("   ✅ Connected! Sending data every 500ms...")
        print("   ⏱  Critical event will trigger at ~50 seconds")
        print("   Press Ctrl+C to stop.\n")

        while True:
            vitals = generate_vitals()
            await ws.send(json.dumps(vitals))

            # Read back the enriched response
            response = json.loads(await ws.recv())
            alert = response.get("alert_level", "normal")

            icon = "🟢" if alert == "normal" else "🟡" if alert == "warning" else "🔴"
            print(
                f"  {icon} HR:{vitals['heart_rate']:>3} | "
                f"SpO2:{vitals['spo2']:>3}% | "
                f"Strain:{vitals['voice_stress_level']:.2f} | "
                f"Pitch:{vitals['pitch']:>6.1f}Hz | "
                f"Vol:{vitals['volume']:>4.1f}dB | "
                f"Alert:{alert}"
            )

            await asyncio.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    try:
        asyncio.run(run_simulator())
    except KeyboardInterrupt:
        print("\n\n🛑 Simulator stopped.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("   Make sure the server is running: uvicorn main:app --port 8000")
