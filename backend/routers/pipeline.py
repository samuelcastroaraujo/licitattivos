"""
Router — Pipeline
Dispara a cadeia dos Agentes 1 → 4 sobre um edital: download do anexo,
extração de texto, extração de requisitos por item e cálculo de compatibilidade
de cada item contra o catálogo de produtos.
"""
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException

from agents.agent1_pncp import download_edital_anexo, fetch_pncp_editais, save_editais
from agents.agent2_parser import extract_text_from_pdf
from agents.agent3_requirements import extract_requirements
from agents.agent4_compatibility import match_product
from db.client import get_supabase_client
from models.edital import Edital, LicitItem
from models.product import Product

router = APIRouter()
log = structlog.get_logger()

# Mesma lista de colunas do router de products — evita puxar o vetor `embedding`
# (1536 floats por produto) para uma operação que não usa embeddings.
PRODUCT_COLUMNS = (
    "id, slug, nome_comercial, fabricante, marca, linha_clinica, categoria, ncm, "
    "registro_anvisa, tem_registro_ms, apresentacoes, descricao, indicacoes, ingredientes, "
    "alergenicos_contem, alergenicos_pode_conter, sem_gluten, sem_lactose, sem_sacarose, "
    "publico_alvo, faixa_etaria_min_anos, faixa_etaria_max_anos, nutricao_por_porcao, "
    "nutricao_por_100g, porcao_g, kcal_por_porcao, proteinas_por_porcao_g, "
    "carboidratos_por_porcao_g, gorduras_por_porcao_g, fibras_por_porcao_g, "
    "sodio_por_porcao_mg, via_oral, via_enteral, ph_solucao, solubilidade, validade_dias, "
    "validade_apos_aberto_dias, normas_regulatorias, diferenciais_tecnicos, updated_at"
)


def _load_edital(client, edital_id: UUID) -> Edital:
    result = client.table("editais").select("*").eq("id", str(edital_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Edital não encontrado")
    return Edital.model_validate(result.data[0])


async def _ensure_pdf_bytes(client, edital: Edital) -> tuple[Edital, bytes]:
    """Garante que o anexo foi baixado para o Storage (Agente 1) e retorna os bytes."""
    if not edital.anexo_local_path:
        edital = await download_edital_anexo(edital)
    if not edital.anexo_local_path:
        raise HTTPException(status_code=422, detail="Edital sem anexo disponível para download")
    pdf_bytes = client.storage.from_("editais_anexos").download(edital.anexo_local_path)
    return edital, pdf_bytes


async def _run_compatibility(client, edital_id: UUID, itens: list[LicitItem]) -> list[dict]:
    """Agente 4: cruza cada item extraído contra todo o catálogo e guarda o melhor match."""
    produtos_raw = client.table("products").select(PRODUCT_COLUMNS).execute().data or []
    produtos = [Product.model_validate(p) for p in produtos_raw]

    rows = client.table("licit_items").select("*").eq("edital_id", str(edital_id)).execute().data or []

    resultados = []
    for row in rows:
        item = LicitItem(
            numero_item=row["numero_item"],
            descricao_original=row.get("descricao_original") or "",
            tipo_produto=row.get("tipo_produto"),
            requisitos=row.get("requisitos") or {},
        )

        melhor_produto: Product | None = None
        melhor_score = None
        for produto in produtos:
            score_result = await match_product(item, produto)
            if melhor_score is None or score_result.score > melhor_score.score:
                melhor_produto, melhor_score = produto, score_result

        if melhor_produto and melhor_score:
            client.table("licit_items").update({
                "produto_id": str(melhor_produto.id),
                "score_compatibilidade": melhor_score.score,
                "compativel": melhor_score.score >= 0.70,
                "justificativa": melhor_score.justificativa_tecnica,
            }).eq("id", row["id"]).execute()

        resultados.append({
            "numero_item": row["numero_item"],
            "produto_recomendado": melhor_produto.nome_comercial if melhor_produto else None,
            "produto_id": str(melhor_produto.id) if melhor_produto else None,
            "score": melhor_score.score if melhor_score else None,
            "status": melhor_score.status if melhor_score else "sem_produto_candidato",
            "justificativa": melhor_score.justificativa_tecnica if melhor_score else None,
        })

    return resultados


@router.post("/{edital_id}/run")
async def run_pipeline(edital_id: UUID):
    """
    Roda Agente 1 → 4 sobre um edital já cadastrado:
    1. Garante o anexo baixado (Agente 1)
    2. Extrai o texto do PDF, com fallback OCR (Agente 2)
    3. Extrai os requisitos estruturados por item (Agente 3)
    4. Calcula a compatibilidade de cada item contra o catálogo (Agente 4)
    """
    client = get_supabase_client()
    edital = _load_edital(client, edital_id)

    try:
        edital, pdf_bytes = await _ensure_pdf_bytes(client, edital)
    except HTTPException:
        raise
    except Exception as e:
        log.error("pipeline.download_failed", error=str(e), edital_id=str(edital_id))
        raise HTTPException(status_code=502, detail=f"Falha ao obter anexo do edital: {e}")

    edital = await extract_text_from_pdf(edital, pdf_bytes)
    if edital.status == "revisao_manual_parser":
        return {
            "edital_id": str(edital_id),
            "status": edital.status,
            "detail": "Extração de texto insuficiente — revisão manual necessária antes de prosseguir.",
        }

    itens = await extract_requirements(edital)
    if not itens:
        return {
            "edital_id": str(edital_id),
            "status": edital.status,
            "detail": "Nenhum item extraído do edital.",
            "itens": [],
        }

    resultados = await _run_compatibility(client, edital_id, itens)

    client.table("editais").update({"status": "compatibilidade_calculada"}).eq(
        "id", str(edital_id)
    ).execute()

    return {
        "edital_id": str(edital_id),
        "status": "compatibilidade_calculada",
        "itens": resultados,
    }


@router.post("/discover")
async def discover_editais(orgao_cnpj: str):
    """Busca editais novos no PNCP para o órgão informado e persiste no Supabase (Agente 1)."""
    try:
        editais = await fetch_pncp_editais(orgao_cnpj)
        saved = await save_editais(editais)
        return {"count": len(saved), "data": [e.model_dump(mode="json") for e in saved]}
    except Exception as e:
        log.error("pipeline.discover_failed", error=str(e), orgao_cnpj=orgao_cnpj)
        raise HTTPException(status_code=502, detail=str(e))
