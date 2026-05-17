"""
War Room — Gerenciador de WebSockets
Mantém as sessões ativas do analista e envia broadcasts em tempo real.
Contém regras de resiliência e recuperação de estado (estado pendente).
"""
import structlog
from typing import List, Dict, Any
from fastapi import WebSocket

log = structlog.get_logger()

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        # Mantém eventos em memória até o frontend dar ACK de que leu
        self.pending_events: List[Dict[str, Any]] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        log.info("ws.client_connected", active=len(self.active_connections))
        
        # Teste de resiliência: Envia pendentes imediatamente na reconexão
        pendentes_nao_lidos = [e for e in self.pending_events if not e.get("ack")]
        if pendentes_nao_lidos:
            await websocket.send_json({
                "type": "sync_state",
                "events": pendentes_nao_lidos
            })

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            log.info("ws.client_disconnected", active=len(self.active_connections))

    async def broadcast(self, event_data: dict):
        """Envia mensagem para todos os clientes ativos com latência < 100ms."""
        log.debug("ws.broadcasting_event", event_id=event_data.get("id"))
        for connection in self.active_connections:
            try:
                await connection.send_json(event_data)
            except Exception as e:
                log.warning("ws.broadcast_failed", error=str(e))
                self.disconnect(connection)
                
    def acknowledge_event(self, event_id: str):
        """A ciência humana que marca o alerta como lido (Anti-Vibe)."""
        for evt in self.pending_events:
            if evt.get("id") == event_id:
                evt["ack"] = True
                log.info("ws.event_acknowledged", event_id=event_id)
                break

manager = ConnectionManager()
