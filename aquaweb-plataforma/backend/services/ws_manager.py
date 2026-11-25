"""Gestor de conexiones WebSocket en tiempo real (/ws/live) para AquaWeb IoT."""

from __future__ import annotations

import asyncio
from typing import Any
from fastapi import WebSocket


class LiveWebSocketManager:
    """Administra clientes WebSocket conectados y difunde eventos en tiempo real."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    def broadcast_threadsafe(self, message: dict[str, Any]) -> None:
        if self._loop is None or not self._connections:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self._loop)
        except RuntimeError:
            pass


ws_manager = LiveWebSocketManager()
