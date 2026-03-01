"""
VocalGuard — WebSocket Connection Manager
Manages active WebSocket connections and provides broadcast capability.
"""

from fastapi import WebSocket


class ConnectionManager:
    """Tracks all active WebSocket clients and broadcasts data to them."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept an incoming WebSocket and add it to the pool."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket from the pool."""
        self.active_connections.remove(websocket)

    async def broadcast(self, data: dict) -> None:
        """Send a JSON payload to every connected client."""
        for connection in self.active_connections:
            await connection.send_json(data)
