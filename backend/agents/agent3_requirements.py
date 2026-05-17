"""
Agente 3 — Extrator de Requisitos (LLM + Regex)
Usa LLM para estruturar o texto do edital em itens e usa Regex para revalidar limiares numéricos críticos.
"""
import re
import structlog
from typing import Any
from models.edital import Edital, LicitItem

log = structlog.get_logger()

# Na vida real isso seria uma chamada para o LangChain/Claude
async def call_llm_for_extraction(raw_text: str) -> dict[str, Any]:
    """Stub para a chamada do LLM. No teste será mockado."""
    return {"itens": []}

def _revalidate_with_regex(descricao: str, raw_text: str, llm_requisitos: dict) -> None:
    """
    Regra Absoluta do Agente 3: Revalida valores numéricos com Regex.
    Se o Regex encontrar algo diferente, o Regex prevalece.
    """
    texto_busca = descricao.lower() + "\n" + raw_text.lower()
    
    # Validação de Proteína (ex: "exatos 20g de proteina" ou "mínimo 20g de proteína")
    # Busca por padrão: [numero]g de proteina
    match_proteina = re.search(r"(\d+(?:\.\d+)?)\s*g\s+de\s+prote[íi]na", texto_busca)
    if match_proteina:
        valor_regex = float(match_proteina.group(1))
        valor_llm = llm_requisitos.get("proteina_min_g")
        
        if valor_llm != valor_regex:
            log.warning("agent3.regex_override", campo="proteina_min_g", llm=valor_llm, regex=valor_regex)
            llm_requisitos["proteina_min_g"] = valor_regex

def _normalize_ingredients(ingredientes: list[str]) -> list[str]:
    """Normaliza ingredientes para facilitar busca exata futura."""
    if not ingredientes:
        return []
    # minúsculo, remove espaços extras
    return [" ".join(ing.lower().split()) for ing in ingredientes]

async def extract_requirements(edital: Edital) -> list[LicitItem]:
    """Pipeline híbrida para extração de requisitos técnicos."""
    raw_text = edital.licit_context.get("raw_text", "")
    if not raw_text:
        log.warning("agent3.no_raw_text", edital_id=str(edital.id))
        return []
        
    # Passo 1: LLM (Estruturação)
    llm_output = await call_llm_for_extraction(raw_text)
    itens_extraidos = []
    
    # Passo 2: Revalidação Regex e Ajustes
    for raw_item in llm_output.get("itens", []):
        alertas = []
        reqs = raw_item.get("requisitos", {})
        
        # Revalidação Híbrida
        _revalidate_with_regex(raw_item.get("descricao_original", ""), raw_text, reqs)
        
        # Normalização de ingredientes
        if "ingredientes_obrigatorios" in reqs:
            reqs["ingredientes_obrigatorios"] = _normalize_ingredients(reqs["ingredientes_obrigatorios"])
            
        # Regra Anti-Vibe: Detectar gap de informação
        if reqs.get("quantidade_pregao") is None:
            alertas.append("gap_de_informacao: quantidade_pregao")
            
        # Converte para modelo Pydantic
        item = LicitItem(
            numero_item=raw_item.get("numero_item", "N/A"),
            descricao_original=raw_item.get("descricao_original", ""),
            tipo_produto=raw_item.get("tipo_produto"),
            requisitos=reqs
        )
        
        # Gambiarra no Pydantic não permite adicionar atributos avulsos se extra='ignore',
        # entao vamos adicionar a nivel de dict quando salvar.
        # No modelo atual, 'alertas' não está em LicitItem (apenas na tabela licit_items).
        # Vamos adicionar no modelo LicitItem para uso in-memory e salvamento.
        if not hasattr(item, "alertas"):
            item.alertas = []
        item.alertas.extend(alertas)
        
        itens_extraidos.append(item)
        
    # Passo 3: Persistência no Supabase
    try:
        from db.client import get_supabase_client
        client = get_supabase_client()
        
        payloads = []
        for item in itens_extraidos:
            payload = {
                "edital_id": str(edital.id),
                "numero_item": item.numero_item,
                "descricao_original": item.descricao_original,
                "tipo_produto": item.tipo_produto,
                "requisitos": item.requisitos.model_dump(),
                "alertas": item.alertas
            }
            payloads.append(payload)
            
        if payloads:
            client.table("licit_items").insert(payloads).execute()
            
        edital.status = "requisitos_extraidos"
        client.table("editais").update({"status": edital.status}).eq("id", str(edital.id)).execute()
        
    except Exception as e:
        log.error("agent3.db_insert_failed", error=str(e), edital_id=str(edital.id))
        
    return itens_extraidos
