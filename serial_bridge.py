"""
VocalGuard — Serial-to-WebSocket Bridge
Reads JSON from Arduino Uno via Serial and forwards to the VocalGuard WebSocket.

Usage:
    python serial_bridge.py              (auto-detect COM port)
    python serial_bridge.py COM3         (specify COM port)
    python serial_bridge.py /dev/ttyUSB0 (Linux)
"""

import sys
import json
import asyncio
from datetime import datetime

import serial
import serial.tools.list_ports
import websockets


# ── Configuration ────────────────────────────────────────────────────────────

WS_URL = "ws://localhost:8000/ws/monitor"
BAUD_RATE = 115200
RETRY_DELAY = 3  # seconds between reconnection attempts


def find_arduino_port():
    """Auto-detect the Arduino COM port."""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        desc = (port.description or "").lower()
        # Common Arduino identifiers
        if any(keyword in desc for keyword in ["arduino", "ch340", "cp210", "usb serial", "usb-serial"]):
            return port.device

    # If no known Arduino found, list available ports
    if ports:
        print("⚠  Could not auto-detect Arduino. Available ports:")
        for p in ports:
            print(f"   {p.device} — {p.description}")
        print(f"\n   Using first available: {ports[0].device}")
        return ports[0].device

    return None


def open_serial(port):
    """Open serial connection to Arduino."""
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1)
        print(f"✅ Serial connected: {port} @ {BAUD_RATE} baud")
        return ser
    except serial.SerialException as e:
        print(f"❌ Failed to open {port}: {e}")
        return None


async def bridge(port):
    """Main bridge loop: Serial → WebSocket."""
    ser = open_serial(port)
    if not ser:
        return

    print(f"🔗 Connecting to WebSocket: {WS_URL}")

    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                print("✅ WebSocket connected — bridging data...\n")

                while True:
                    # Read a line from Arduino Serial
                    if ser.in_waiting > 0:
                        try:
                            line = ser.readline().decode("utf-8").strip()
                        except UnicodeDecodeError:
                            continue

                        if not line:
                            continue

                        # Try to parse as JSON
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            # Not valid JSON — might be a debug message
                            print(f"   [Arduino] {line}")
                            continue

                        # Skip status messages
                        if "status" in data and "heart_rate" not in data:
                            status = data.get("status", "")
                            msg = data.get("message", "")
                            print(f"   ℹ  {status}: {msg}")
                            continue

                        # Replace Arduino millis timestamp with real ISO timestamp
                        data["timestamp"] = datetime.now().isoformat()

                        # Send to WebSocket
                        await ws.send(json.dumps(data))

                        # Read back the enriched response
                        response = json.loads(await ws.recv())
                        alert = response.get("alert_level", "normal")

                        icon = "🟢" if alert == "normal" else "🟡" if alert == "warning" else "🔴"
                        print(
                            f"  {icon} HR:{data.get('heart_rate', '--'):>3} | "
                            f"SpO2:{data.get('spo2', '--'):>3}% | "
                            f"Alert:{alert}"
                        )

                    else:
                        await asyncio.sleep(0.01)  # Small sleep to avoid busy-waiting

        except websockets.exceptions.ConnectionClosed:
            print(f"\n🔌 WebSocket disconnected — reconnecting in {RETRY_DELAY}s...")
            await asyncio.sleep(RETRY_DELAY)
        except Exception as e:
            print(f"\n❌ Error: {e} — retrying in {RETRY_DELAY}s...")
            await asyncio.sleep(RETRY_DELAY)


def main():
    print("🎤 VocalGuard Serial-to-WebSocket Bridge")
    print("=" * 45)

    # Get COM port from args or auto-detect
    if len(sys.argv) > 1:
        port = sys.argv[1]
        print(f"   Using specified port: {port}")
    else:
        port = find_arduino_port()
        if not port:
            print("❌ No serial ports found. Is the Arduino connected?")
            sys.exit(1)
        print(f"   Auto-detected port: {port}")

    print(f"   Baud rate: {BAUD_RATE}")
    print(f"   WebSocket: {WS_URL}")
    print()

    try:
        asyncio.run(bridge(port))
    except KeyboardInterrupt:
        print("\n\n🛑 Bridge stopped.")


if __name__ == "__main__":
    main()
