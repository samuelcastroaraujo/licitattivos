"""
Agente 8 — Monitoramento em Tempo Real (War Room)
Supervisiona o pregão, processa mensagens do chat via Playwright e dispara alertas táticos.
"""
import re
from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel
import structlog
from db.client import get_supabase_client

log = structlog.get_logger()

class CircuitBreakerOpenError(Exception):
    """Exceção levantada quando o portal excede o timeout máximo de resposta."""
    pass

class AlertLevel(str, Enum):
    VERDE = "verde"        # Informação normal
    AMBAR = "ambar"        # Atenção: lance concorrente próximo
    VERMELHO = "vermelho"  # Ação Imediata: chat citou proposta, empresa, ou erro crítico

class ChatEvent(BaseModel):
    autor: str
    texto: str
    timestamp: str

class MonitorResult(BaseModel):
    nivel: AlertLevel
    motivo: str
    lance_detectado: Optional[float] = None
    acima_do_minimo: Optional[bool] = None
    sugestao_resposta: Optional[str] = None
    enviado_automaticamente: bool = False

class WarRoomMonitor:
    def __init__(self, licit_context: Dict[str, Any], portal: str, timeout_segundos: int = 120):
        self.licit_context = licit_context
        self.portal = portal
        self.timeout_segundos = timeout_segundos
        self.circuit_breaker_aberto = False
        self.empresa_nome = licit_context.get("empresa_nome", "").lower()
        self.preco_minimo = licit_context.get("preco_minimo_autorizado", 0.0)

    async def _verificar_portal_ativo(self):
        """Simula a verificação de health/ping da página do portal (Playwright)."""
        # Em produção, usaria page.wait_for_selector ou similar
        pass

    async def verificar_conexao_com_circuit_breaker(self):
        """Impede que travamentos do portal congelem o LicitAttivos."""
        if self.circuit_breaker_aberto:
            raise CircuitBreakerOpenError("Conexão Perdida. Circuit Breaker aberto. Aguarde intervenção.")
            
        try:
            await self._verificar_portal_ativo()
        except TimeoutError:
            self.circuit_breaker_aberto = True
            log.error("agent8.circuit_breaker_tripped", portal=self.portal, timeout=self.timeout_segundos)
            raise CircuitBreakerOpenError(f"Conexão Perdida com {self.portal}. Timeout de {self.timeout_segundos}s.")

    async def _buscar_knowledge(self, pergunta: str) -> Optional[str]:
        """Busca no histórico/RAG respostas para a pergunta do pregoeiro."""
        # Em produção, usaria o stub/pgvector. Aqui é simplificado para o TDD.
        return None

    async def _gravar_evento(self, evento: ChatEvent, nivel: AlertLevel):
        """Persiste a evidência no Supabase."""
        try:
            client = get_supabase_client()
            client.table("pregao_events").insert({
                "edital_id": self.licit_context.get("edital_id"),
                "portal": self.portal,
                "autor": evento.autor,
                "texto": evento.texto,
                "timestamp": evento.timestamp,
                "alert_level": nivel.value
            }).execute()
        except Exception as e:
            log.warning("agent8.persistence_failed", error=str(e))

    async def processar_evento(self, evento: ChatEvent) -> MonitorResult:
        """Motor de regras táticas para cada mensagem ou lance que aparece no portal."""
        log.info("agent8.processing_event", autor=evento.autor)
        texto_lower = evento.texto.lower()
        
        result = MonitorResult(nivel=AlertLevel.VERDE, motivo="Mensagem padrão.")

        # 1. Alerta Vermelho: Chat direto do Pregoeiro
        if evento.autor.lower() == "pregoeiro":
            if self.empresa_nome and self.empresa_nome in texto_lower:
                result.nivel = AlertLevel.VERMELHO
                result.motivo = f"Pregoeiro citou a empresa: {self.empresa_nome}"
            elif "proposta" in texto_lower:
                result.nivel = AlertLevel.VERMELHO
                result.motivo = "Pregoeiro fez solicitação sobre proposta."
            elif "?" in texto_lower or "informe" in texto_lower or "confirme" in texto_lower:
                result.nivel = AlertLevel.VERMELHO
                result.motivo = "Pergunta técnica detectada."
                
            # Regra Absoluta: Sugestão de Resposta (Nunca Envia)
            if result.nivel == AlertLevel.VERMELHO:
                kb_resp = await self._buscar_knowledge(evento.texto)
                if kb_resp:
                    result.sugestao_resposta = kb_resp
                else:
                    result.sugestao_resposta = "Analista, favor redigir resposta. Histórico insuficiente."
                
        # 2. Inteligência de Preço: Lances de concorrentes
        lance_match = re.search(r"lance de r\$\s*([\d,\.]+)", texto_lower)
        if lance_match:
            try:
                lance_val = float(lance_match.group(1).replace(".", "").replace(",", "."))
                result.lance_detectado = lance_val
                
                if lance_val >= self.preco_minimo:
                    result.nivel = AlertLevel.AMBAR
                    result.acima_do_minimo = True
                    result.motivo = "Lance concorrente identificado. Possível cobrir."
                else:
                    result.nivel = AlertLevel.VERMELHO
                    result.acima_do_minimo = False
                    result.motivo = "Lance INVIÁVEL (não cobrir). Abaixo do mínimo autorizado."
            except ValueError:
                pass

        # 3. Persistência de Evidências (apenas eventos Ambar/Vermelho ou Pregoeiro)
        if result.nivel in [AlertLevel.AMBAR, AlertLevel.VERMELHO] or evento.autor.lower() == "pregoeiro":
            await self._gravar_evento(evento, result.nivel)

        return result
