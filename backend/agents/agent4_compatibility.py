"""
Agente 4 — Motor de Compatibilidade (As 5 Camadas)
"""
import structlog
from pydantic import BaseModel
from models.edital import LicitItem
from models.product import Product

log = structlog.get_logger()

class ScoreResult(BaseModel):
    score: float
    status: str
    justificativa_tecnica: str

async def get_knowledge_items(query: str) -> list[dict]:
    """Stub para consulta ao pgvector da tabela knowledge_items."""
    return []

def _normalize_string(s: str) -> str:
    if not s:
        return ""
    return " ".join(s.lower().split())

async def match_product(item: LicitItem, product: Product) -> ScoreResult:
    justificativas = []
    score = 1.0
    status = "compatível"
    
    # Camada 0: Orientação por Histórico
    kb_items = await get_knowledge_items(f"{item.descricao_original} {product.nome_comercial}")
    for kb in kb_items:
        if kb.get("regra_fixa"):
            log.warning("agent4.layer0_history_override", product=product.slug)
            if kb.get("decisao") == "reprovado":
                return ScoreResult(
                    score=0.0,
                    status="incompatível",
                    justificativa_tecnica=kb.get("motivo", "Reprovado por regra histórica.")
                )
            # Se for aprovado direto, poderia forçar score 1.0

    reqs = item.requisitos
    
    # Camada 1: Thresholds Matemáticos e Gaps
    # Proteína
    if reqs.proteina_min_g is not None:
        if product.proteinas_por_porcao_g is None:
            score = min(score, 0.40) # Trava o score, gap de info
            justificativas.append("GAP de informação: produto não possui valor de proteína cadastrado.")
        elif product.proteinas_por_porcao_g < reqs.proteina_min_g:
            score = min(score, 0.10)
            justificativas.append(f"Incompatível: Edital pede {reqs.proteina_min_g}g de proteína, produto tem {product.proteinas_por_porcao_g}g.")
            
    # Kcal
    if reqs.kcal_min is not None:
        if product.kcal_por_porcao is None:
            score = min(score, 0.40)
            justificativas.append("GAP de informação: produto não possui kcal cadastrada.")
        elif product.kcal_por_porcao < reqs.kcal_min:
            score = min(score, 0.10)
            justificativas.append(f"Incompatível: Edital pede {reqs.kcal_min} kcal, produto tem {product.kcal_por_porcao}.")

    # Camada 2: Ingredientes (Busca Exata normalizada)
    if reqs.ingredientes_obrigatorios:
        # Pega a lista de ingredientes do produto
        prod_ings = [_normalize_string(ing.nome_normalizado) for ing in product.ingredientes.lista]
        for req_ing in reqs.ingredientes_obrigatorios:
            if _normalize_string(req_ing) not in prod_ings:
                score = min(score, 0.50)
                justificativas.append(f"Ingrediente obrigatório faltante: {req_ing}.")

    # Camada 3: Regulatório (Registro MS)
    if reqs.registro_anvisa_obrigatorio:
        if not product.tem_registro_ms:
            # Produto Dispensado vs Edital exigindo MS
            score = min(score, 0.85) # Ressalva (0.70 a 0.89)
            justificativas.append("Ressalva (Regulatório): Edital exige Registro MS, mas o produto é enquadrado como Dispensado de Registro. Requer recurso administrativo para justificar a RDC.")

    # Camada 4: Clínico (Via Enteral)
    if reqs.via_enteral_obrigatoria:
        if not product.via_enteral:
            score = min(score, 0.10)
            justificativas.append("Incompatível: Produto não é homologado para via enteral.")

    # Definição do status baseado no score (Traffic Light)
    if score >= 0.90:
        status = "verde"
    elif score >= 0.70:
        status = "amarelo"
    else:
        status = "vermelho"
        
    final_justification = " ".join(justificativas) if justificativas else "Aprovado sem ressalvas."

    return ScoreResult(
        score=score,
        status=status,
        justificativa_tecnica=final_justification
    )
