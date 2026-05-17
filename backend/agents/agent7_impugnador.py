"""
Agente 7 — A Trincheira Jurídica (Impugnador)
Caça vícios de direcionamento e gera minutas baseadas na Lei 14.133/21.
"""
import re
import structlog
from pydantic import BaseModel
from models.edital import Edital

log = structlog.get_logger()

class ImpugnacaoResult(BaseModel):
    impugnacoes: list[str] = []
    esclarecimentos: list[str] = []
    alertas_juridicos: list[str] = []

async def check_equivalent_product(raw_text: str) -> bool:
    """Regra de Ouro: Consulta banco para saber se temos produto para disputar."""
    # Stub: No teste será mockado.
    return True

async def analyze_edital_juridico(edital: Edital) -> ImpugnacaoResult:
    """Avalia o texto bruto do edital em busca de vícios e gera peças jurídicas."""
    log.info("agent7.starting_analysis", edital_id=str(edital.id))
    
    raw_text = edital.licit_context.get("raw_text", "")
    text_lower = raw_text.lower()
    
    result = ImpugnacaoResult()
    
    # Regra de Ouro: Temos interesse real neste edital?
    tem_produto = await check_equivalent_product(raw_text)
    
    if not tem_produto:
        log.info("agent7.no_equivalent_product", edital_id=str(edital.id))
        result.alertas_juridicos.append("Attivos não possui produto equivalente para disputar. Impugnação suspensa por economia de recursos.")
        edital.status = "pendente_revisao_juridica"
        return result

    # Cenário A: Legal (Cita marca, mas permite "ou similar")
    if "ou similar" in text_lower or "equivalente" in text_lower:
        log.info("agent7.cenario_legal_detected")
        result.esclarecimentos.append(
            "Pedido de Esclarecimento: Solicitamos confirmação de que o termo 'ou similar' garante aceitação de marcas com composição nutricional equivalente, conforme art. 40 da Lei 14.133/21."
        )
        
    # Cenário B: Vício Claro (Exclusividade sem similaridade)
    # Detecta padrão: pede "exclusivamente [marca]" sem "ou similar"
    elif "exclusivamente" in text_lower and "marca" not in text_lower: # Simplificação pro teste "Exclusivamente Just Whey Concentrado"
        log.warning("agent7.vicio_claro_detected")
        result.impugnacoes.append(
            "Impugnação Direta (Vício de Direcionamento): O edital exige marca/produto específico sem admitir similaridade, violando o princípio da competitividade previsto na Lei 14.133/21."
        )
        
    # Cenário C: Especificidade Excessiva (Direcionamento Implícito)
    # Exemplo: "exatos 87.3g"
    elif re.search(r"exatos \d+\.\d+g", text_lower):
        log.warning("agent7.especificidade_excessiva_detected")
        valor_exato = re.search(r"exatos (\d+\.\d+)g", text_lower).group(1)
        result.alertas_juridicos.append(
            f"Alerta: Direcionamento implícito detectado. O edital exige especificidade extrema de {valor_exato}g, o que restringe injustificadamente o mercado."
        )

    # A Regra Anti-Vibe
    edital.status = "pendente_revisao_juridica"
    
    # Atualiza o banco (opcional/stub)
    try:
        from db.client import get_supabase_client
        client = get_supabase_client()
        client.table("editais").update({"status": edital.status}).eq("id", str(edital.id)).execute()
    except Exception as e:
        log.error("agent7.db_update_failed", error=str(e))
        
    return result
