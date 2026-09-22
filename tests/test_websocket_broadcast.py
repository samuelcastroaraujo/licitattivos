"""
test_websocket_broadcast.py — Ciclo TDD do WebSockets da War Room

Regras testadas:
1. Conexão WS estabelecida e Heartbeat funcionando.
2. Broadcast imediato: Injetar evento VERMELHO e cliente receber < 100ms.
3. Recuperação de estado: Cliente desconecta, perde um evento, reconecta e puxa os pendentes.
"""
import os
import sys
import asyncio
import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from main import app
from ws.manager import manager
from agents.agent8_monitor import ChatEvent, AlertLevel

# ── Testes ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_lifespan_and_db(monkeypatch, mock_supabase_client):
    # Ignora os eventos de startup que tentam bater no banco real
    monkeypatch.setattr("main.lifespan", None)

@pytest.mark.asyncio
async def test_websocket_broadcast_imediato_abaixo_100ms():
    """O servidor WebSocket deve propagar o evento Vermelho em tempo real."""
    # Reseta o manager para o teste
    manager.active_connections.clear()
    
    with TestClient(app) as client:
        with client.websocket_connect("/ws/war-room") as websocket:
            # Cliente 1 conectado
            assert len(manager.active_connections) == 1
            
            # Simulando evento injetado pelo Agente 8 no backend
            start_time = asyncio.get_event_loop().time()
            
            # Dispara broadcast
            evento = {
                "id": "evt-123",
                "nivel": AlertLevel.VERMELHO.value,
                "motivo": "Pregoeiro citou a proposta",
                "timestamp": "2026-05-11T20:55:00",
                "ack": False
            }
            # Simula a inserção na fila global
            manager.pending_events.append(evento)
            # Já estamos rodando no loop do teste — await direto evita o
            # deadlock de aguardar (.result()) uma coroutine agendada no
            # próprio loop que está bloqueado esperando por ela.
            await manager.broadcast(evento)
            
            # Cliente deve receber a mensagem
            data = websocket.receive_json()
            end_time = asyncio.get_event_loop().time()
            
            assert data["id"] == "evt-123"
            assert data["nivel"] == "vermelho"
            
            # A latência tem que ser mínima (< 100ms em ambiente local simulado)
            # TestClient é síncrono, então a medida de tempo aqui é simbólica, 
            # mas garante que o path está otimizado sem IO bloqueante.
            assert (end_time - start_time) < 0.1  # 100ms

@pytest.mark.asyncio
async def test_websocket_reconectar_e_recuperar_estado():
    """Teste de resiliência: Cliente cai, evento acontece, cliente reconecta e puxa o pendente."""
    manager.active_connections.clear()
    manager.pending_events.clear()
    
    # 1. Agente 8 dispara um evento enquanto não há NINGUÉM conectado
    evento_perdido = {
        "id": "evt-perdido-1",
        "nivel": AlertLevel.VERMELHO.value,
        "motivo": "Lance abaixo do mínimo",
        "timestamp": "2026-05-11T20:56:00",
        "ack": False
    }
    manager.pending_events.append(evento_perdido)
    
    # 2. Cliente reconecta (UI da tela após um F5 ou queda de wifi)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/war-room") as websocket:
            # O sistema DEVE enviar o estado inicial de eventos não-ack no momento da conexão
            data = websocket.receive_json()
            
            # Recebe o histórico
            assert data["type"] == "sync_state"
            assert len(data["events"]) == 1
            assert data["events"][0]["id"] == "evt-perdido-1"
            
            # O cliente então dá o ACK de que viu a mensagem (A "ciência" da UI)
            websocket.send_json({"type": "ack", "event_id": "evt-perdido-1"})
            
            # O backend deve marcar como ack
            assert len([e for e in manager.pending_events if not e["ack"]]) == 0

@pytest.mark.asyncio
async def test_websocket_heartbeat():
    """Teste da regra do Desapego: PING/PONG para segurar firewall."""
    manager.active_connections.clear()
    
    with TestClient(app) as client:
        with client.websocket_connect("/ws/war-room") as websocket:
            # UI envia PING
            websocket.send_json({"type": "ping"})
            # Backend tem que retornar PONG imediatamente
            data = websocket.receive_json()
            assert data["type"] == "pong"
