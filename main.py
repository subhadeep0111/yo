"""
VocalGuard — Main Application
FastAPI backend with real-time WebSocket monitoring, AI safety thresholds,
Gemini Flash 2.5 alert verification, and SQLite session persistence.

Goal: ≤ 100 ms latency so the singer gets warned before collapse.
"""

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, func

from models import async_session, SessionLog, init_db
from manager import ConnectionManager


# ── Pydantic Schemas ─────────────────────────────────────────────────────────


class VitalsPacket(BaseModel):
    """Incoming JSON from the Arduino / MAX30102 sensor + mic."""
    heart_rate: int
    spo2: int
    voice_stress_level: float
    pitch: float = 0.0          # Hz — computed from mic on the frontend
    volume: float = 0.0         # dB — computed from mic on the frontend
    timestamp: str


class AlertResult(BaseModel):
    """Result of the safety-threshold evaluation."""
    alert_level: str          # "normal" | "warning" | "critical"
    alert_message: Optional[str] = None


class VerifyAlertRequest(BaseModel):
    """Payload sent to Gemini for alert verification."""
    heart_rate: int
    spo2: int
    voice_stress_level: float
    alert_level: str
    alert_message: str


# ── AI Guard — Safety Threshold Logic ────────────────────────────────────────


def evaluate_vitals(packet: VitalsPacket) -> AlertResult:
    """
    Evaluate a single data packet against clinical safety thresholds.

    Priority order (highest → lowest):
      1. SpO2 critical  (< 90 %)
      2. Heart-rate critical  (> 180 BPM)
      3. SpO2 warning  (< 94 %)
      4. Heart-rate warning  (> 160 BPM)
      5. Normal
    """
    # ── Critical checks ──
    if packet.spo2 < 90:
        return AlertResult(
            alert_level="critical",
            alert_message="⚠️ CRITICAL: SpO2 dangerously low ({spo2}%). Stop immediately!".format(
                spo2=packet.spo2
            ),
        )
    if packet.heart_rate > 180:
        return AlertResult(
            alert_level="critical",
            alert_message="⚠️ CRITICAL: Heart rate dangerously high ({hr} BPM). Stop immediately!".format(
                hr=packet.heart_rate
            ),
        )

    # ── Warning checks ──
    if packet.spo2 < 94:
        return AlertResult(
            alert_level="warning",
            alert_message="⚠ WARNING: SpO2 below safe level ({spo2}%). Consider resting.".format(
                spo2=packet.spo2
            ),
        )
    if packet.heart_rate > 160:
        return AlertResult(
            alert_level="warning",
            alert_message="⚠ WARNING: Heart rate elevated ({hr} BPM). Monitor closely.".format(
                hr=packet.heart_rate
            ),
        )

    return AlertResult(alert_level="normal")


# ── Gemini AI Alert Verification ─────────────────────────────────────────────


async def verify_alert_with_gemini(data: VerifyAlertRequest) -> dict:
    """
    Send vitals to Gemini Flash 2.5 to verify if the alert is genuine
    or a possible sensor glitch.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {
            "verdict": "unavailable",
            "explanation": "Gemini API key not configured. Set GEMINI_API_KEY environment variable.",
        }

    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        prompt = f"""You are a medical safety AI for a live singer monitoring system called VocalGuard.
Analyze these real-time biometric readings and determine if the alert is genuine or a sensor glitch.

CURRENT READINGS:
- Heart Rate: {data.heart_rate} BPM
- SpO2 (Blood Oxygen): {data.spo2}%
- Vocal Strain Index: {data.voice_stress_level}

ALERT TRIGGERED: {data.alert_level.upper()}
ALERT MESSAGE: {data.alert_message}

Based on the correlation between these three data points, respond with EXACTLY this JSON format:
{{
  "verdict": "genuine" or "likely_false" or "uncertain",
  "risk_level": "high" or "medium" or "low",
  "explanation": "Brief 1-2 sentence explanation of your analysis",
  "recommendation": "What the singer/crew should do right now"
}}

Consider:
- If heart rate AND SpO2 are both abnormal, the alert is likely genuine.
- If only one metric is off and vocal strain is low, it could be a sensor glitch.
- High vocal strain combined with abnormal vitals is a strong indicator of genuine distress.
- A single abnormal reading with others normal may indicate a sensor issue.

Respond ONLY with the JSON, no other text."""

        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-04-17",
            contents=prompt,
        )

        import json
        # Parse the response text as JSON
        response_text = response.text.strip()
        # Remove markdown code fences if present
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            response_text = response_text.rsplit("```", 1)[0].strip()

        result = json.loads(response_text)
        return result

    except Exception as e:
        return {
            "verdict": "error",
            "explanation": f"Gemini verification failed: {str(e)}",
        }


# ── Application Lifecycle ────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database on startup."""
    await init_db()
    print("✅ VocalGuard DB initialised — ready to protect.")
    yield


app = FastAPI(
    title="VocalGuard API",
    description="Real-time safety monitoring backend for singers.",
    version="2.0.0",
    lifespan=lifespan,
)

# Allow any frontend origin during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()


# ── REST Endpoints ───────────────────────────────────────────────────────────


@app.get("/api/health")
async def healthcheck():
    """Simple health-check endpoint."""
    return {"status": "ok", "service": "VocalGuard", "version": "2.0.0"}


@app.get("/api/sessions")
async def get_sessions(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """
    Return paginated session logs for post-performance review.
    Most recent entries first.
    """
    async with async_session() as session:
        # Total count
        count_result = await session.execute(select(func.count(SessionLog.id)))
        total = count_result.scalar()

        # Paginated rows
        result = await session.execute(
            select(SessionLog)
            .order_by(SessionLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = result.scalars().all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "data": [
            {
                "id": r.id,
                "heart_rate": r.heart_rate,
                "spo2": r.spo2,
                "voice_stress_level": r.voice_stress_level,
                "pitch": r.pitch,
                "volume": r.volume,
                "alert_level": r.alert_level,
                "alert_message": r.alert_message,
                "timestamp": r.timestamp,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@app.post("/api/verify-alert")
async def verify_alert(data: VerifyAlertRequest):
    """
    Send vitals to Gemini Flash 2.5 for AI-powered alert verification.
    Determines if the alert is genuine or a potential sensor glitch.
    """
    result = await verify_alert_with_gemini(data)
    return result


# ── WebSocket Endpoint ───────────────────────────────────────────────────────


@app.websocket("/ws/monitor")
async def websocket_monitor(websocket: WebSocket):
    """
    Real-time monitoring endpoint.

    Flow:
    1. Arduino sends a JSON vitals packet.
    2. Guard system evaluates safety thresholds (< 0.1 ms).
    3. Enriched payload is persisted to SQLite.
    4. Enriched payload is broadcast to all connected dashboard clients.
    """
    await manager.connect(websocket)
    print(f"🔗  Client connected — {len(manager.active_connections)} active")

    try:
        while True:
            # 1️⃣  Receive raw vitals from sensor / simulator
            raw = await websocket.receive_json()
            packet = VitalsPacket(**raw)

            # 2️⃣  Evaluate safety thresholds
            alert = evaluate_vitals(packet)

            # 3️⃣  Build enriched response
            response = {
                "heart_rate": packet.heart_rate,
                "spo2": packet.spo2,
                "voice_stress_level": packet.voice_stress_level,
                "pitch": packet.pitch,
                "volume": packet.volume,
                "timestamp": packet.timestamp,
                "alert_level": alert.alert_level,
                "alert_message": alert.alert_message,
            }

            # 4️⃣  Persist to database
            async with async_session() as session:
                log_entry = SessionLog(
                    heart_rate=packet.heart_rate,
                    spo2=packet.spo2,
                    voice_stress_level=packet.voice_stress_level,
                    pitch=packet.pitch,
                    volume=packet.volume,
                    alert_level=alert.alert_level,
                    alert_message=alert.alert_message,
                    timestamp=packet.timestamp,
                )
                session.add(log_entry)
                await session.commit()

            # 5️⃣  Broadcast to all dashboard clients
            await manager.broadcast(response)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print(f"🔌  Client disconnected — {len(manager.active_connections)} active")


# ── Serve Frontend ───────────────────────────────────────────────────────────

# Serve the dashboard at root
@app.get("/")
async def serve_dashboard():
    """Serve the frontend dashboard."""
    return FileResponse("frontend/index.html")


# Mount static files (CSS, JS)
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")


# ── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
