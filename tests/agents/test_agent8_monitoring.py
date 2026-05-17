"""
test_agent8_monitoring.py — Ciclo TDD do Agente 8 (War Room de Pregão)

Regras testadas:
1. Alerta Vermelho: captura menção à empresa/proposta no chat
2. Inteligência de Preço: detecção de lance concorrente abaixo do mínimo
3. Sugestão de Resposta: base de resposta para pergunta técnica
4. Circuit Breaker: parar retries após 120s e emitir alerta
5. Persistência: eventos gravados na tabela pregao_events
"""
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend')))

from agents.agent8_monitor import (
    WarRoomMonitor,
    ChatEvent,
    AlertLevel,
    CircuitBreakerOpenError,
)

# ── Fixtures ───────────────────────────────────────────────────────────────
LICIT_CONTEXT = {
    "empresa_nome": "Attivos Magisttrais",
    "preco_minimo_autorizado": 45.00,      # Planilha do Agente 5
    "preco_unitario_proposta": 52.00,
    "edital_id": "edital-001",
    "itens": []
}

@pytest.fixture
def monitor():
    """Cria o monitor sem conexão real ao portal."""
    return WarRoomMonitor(
        licit_context=LICIT_CONTEXT,
        portal="comprasnet",
        timeout_segundos=120
    )


# ── Testes ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent8_alerta_vermelho_mencao_empresa(monitor, mock_supabase_client):
    """Cenário A: pregoeiro cita 'Attivos' no chat → alerta VERMELHO imediato."""
    mensagem_chat = ChatEvent(
        autor="Pregoeiro",
        texto="Attivos Magisttrais, por favor confirme a procedência do seu produto.",
        timestamp="2026-05-11T20:00:00"
    )

    with patch.object(monitor, '_gravar_evento') as mock_gravar:
        resultado = await monitor.processar_evento(mensagem_chat)

    assert resultado.nivel == AlertLevel.VERMELHO
    assert "attivos" in resultado.motivo.lower()
    mock_gravar.assert_called_once()


@pytest.mark.asyncio
async def test_agent8_alerta_vermelho_mencao_proposta(monitor, mock_supabase_client):
    """Cenário A2: pregoeiro cita 'proposta' → alerta VERMELHO imediato."""
    evento = ChatEvent(
        autor="Pregoeiro",
        texto="Solicito que a proposta seja readequada no prazo de 30 minutos.",
        timestamp="2026-05-11T20:01:00"
    )

    resultado = await monitor.processar_evento(evento)

    assert resultado.nivel == AlertLevel.VERMELHO
    assert resultado.sugestao_resposta is not None


@pytest.mark.asyncio
async def test_agent8_inteligencia_preco_lance_concorrente(monitor, mock_supabase_client):
    """Cenário B: Lance concorrente abaixo da proposta da Attivos → alerta Âmbar."""
    evento = ChatEvent(
        autor="Concorrente_01",
        texto="Lance de R$ 48,50 para o Item 02.",
        timestamp="2026-05-11T20:05:00"
    )

    resultado = await monitor.processar_evento(evento)

    assert resultado.nivel == AlertLevel.AMBAR
    assert resultado.lance_detectado == 48.50
    assert resultado.acima_do_minimo is True   # 48.50 > 45.00 → ainda lucrativo se cobrir


@pytest.mark.asyncio
async def test_agent8_lance_abaixo_do_minimo_nao_cobrir(monitor, mock_supabase_client):
    """Cenário B2: lance concorrente ABAIXO do preço mínimo → alerta VERMELHO (não cobrir)."""
    evento = ChatEvent(
        autor="Concorrente_01",
        texto="Lance de R$ 40,00 para o Item 02.",
        timestamp="2026-05-11T20:06:00"
    )

    resultado = await monitor.processar_evento(evento)

    assert resultado.nivel == AlertLevel.VERMELHO
    assert resultado.lance_detectado == 40.00
    assert resultado.acima_do_minimo is False
    assert "não cobrir" in resultado.motivo.lower()


@pytest.mark.asyncio
async def test_agent8_sugestao_resposta_pergunta_tecnica(monitor, mock_supabase_client):
    """Cenário C: pregoeiro faz pergunta técnica → Agente busca knowledge e sugere resposta."""
    evento = ChatEvent(
        autor="Pregoeiro",
        texto="O produto possui registro na ANVISA?",
        timestamp="2026-05-11T20:10:00"
    )

    with patch.object(monitor, '_buscar_knowledge') as mock_kb:
        mock_kb.return_value = "O produto é enquadrado como Dispensado de Registro conforme RDC 27/2010."

        resultado = await monitor.processar_evento(evento)

    assert resultado.sugestao_resposta is not None
    assert "ANVISA" in resultado.sugestao_resposta or "Dispensado" in resultado.sugestao_resposta
    # Regra Absoluta: Agente 8 NUNCA envia a resposta — apenas sugere
    assert resultado.enviado_automaticamente is False


@pytest.mark.asyncio
async def test_agent8_circuit_breaker_abre_apos_timeout(monitor):
    """Circuit Breaker: portal para de responder → para retries e dispara alerta."""
    # Simula falhas consecutivas suficientes para abrir o circuit breaker
    with patch.object(monitor, '_verificar_portal_ativo', side_effect=TimeoutError("portal timeout")):
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await monitor.verificar_conexao_com_circuit_breaker()

    assert "Conexão Perdida" in str(exc_info.value)
    assert monitor.circuit_breaker_aberto is True


@pytest.mark.asyncio
async def test_agent8_evento_nao_relevante_nao_gera_alerta(monitor, mock_supabase_client):
    """Mensagem irrelevante (concorrente falando de outro item) → sem alerta."""
    evento = ChatEvent(
        autor="Outro_Fornecedor",
        texto="Boa tarde a todos.",
        timestamp="2026-05-11T20:15:00"
    )

    resultado = await monitor.processar_evento(evento)

    assert resultado.nivel == AlertLevel.VERDE   # Sem alerta — tudo tranquilo
    assert resultado.sugestao_resposta is None


@pytest.mark.asyncio
async def test_agent8_persistencia_evento_supabase(monitor, mock_supabase_client):
    """Eventos relevantes são gravados na tabela pregao_events."""
    evento = ChatEvent(
        autor="Pregoeiro",
        texto="Attivos, confirme o valor unitário.",
        timestamp="2026-05-11T20:20:00"
    )

    mock_supabase = MagicMock()
    mock_supabase_client.return_value = mock_supabase
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "ev-001"}])

    with patch('agents.agent8_monitor.get_supabase_client', return_value=mock_supabase):
        await monitor.processar_evento(evento)

    mock_supabase.table.assert_any_call("pregao_events")
    mock_supabase.table.return_value.insert.assert_called()
