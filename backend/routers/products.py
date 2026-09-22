"""
Router — Products
Leitura e gestão do catálogo de produtos (fonte da verdade para o Agente 4).
Os dados são populados via scripts/import_products.py a partir de banco de dados/*.md.
"""
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query

from db.client import get_supabase_client
from models.product import ProductCreate

router = APIRouter()
log = structlog.get_logger()

# Todas as colunas de `products`, exceto `embedding` (vetor de 1536 floats —
# pesado demais para trafegar em respostas de API e não é usado pelos clientes).
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


@router.get("/")
async def list_products(
    categoria: Optional[str] = Query(None, description="Filtrar por categoria"),
    marca: Optional[str] = Query(None, description="Filtrar por marca (Pholias, Venum...)"),
    linha_clinica: Optional[str] = Query(None, description="Filtrar por linha clínica"),
    tem_registro_ms: Optional[bool] = Query(None, description="Filtrar por registro MS"),
    via_enteral: Optional[bool] = Query(None, description="Filtrar por homologação via enteral"),
    search: Optional[str] = Query(None, description="Busca por nome comercial"),
    limit: int = Query(100, le=500),
):
    """Lista produtos do catálogo com filtros opcionais."""
    try:
        client = get_supabase_client()
        query = client.table("products").select(PRODUCT_COLUMNS)

        if categoria:
            query = query.ilike("categoria", f"%{categoria}%")
        if marca:
            query = query.eq("marca", marca)
        if linha_clinica:
            query = query.ilike("linha_clinica", f"%{linha_clinica}%")
        if tem_registro_ms is not None:
            query = query.eq("tem_registro_ms", tem_registro_ms)
        if via_enteral is not None:
            query = query.eq("via_enteral", via_enteral)
        if search:
            query = query.ilike("nome_comercial", f"%{search}%")

        result = query.order("nome_comercial").limit(limit).execute()
        return {"data": result.data, "count": len(result.data)}
    except Exception as e:
        log.error("products.list_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{product_id}")
async def get_product(product_id: UUID):
    """Detalhe completo de um produto (ingredientes, nutrição, apresentações etc.)."""
    try:
        client = get_supabase_client()
        result = client.table("products").select(PRODUCT_COLUMNS).eq("id", str(product_id)).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Produto não encontrado")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        log.error("products.get_failed", error=str(e), product_id=str(product_id))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/slug/{slug}")
async def get_product_by_slug(slug: str):
    """Busca produto pelo slug — chave estável usada pelo import script e pelos agentes."""
    try:
        client = get_supabase_client()
        result = client.table("products").select(PRODUCT_COLUMNS).eq("slug", slug).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Produto não encontrado")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        log.error("products.get_by_slug_failed", error=str(e), slug=slug)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", status_code=201)
async def upsert_product(product: ProductCreate):
    """Cria ou atualiza (upsert por slug) um produto no catálogo."""
    try:
        client = get_supabase_client()
        payload = product.model_dump(mode="json")
        result = client.table("products").upsert(payload, on_conflict="slug").execute()
        log.info("products.upserted", slug=product.slug)
        return result.data[0]
    except Exception as e:
        log.error("products.upsert_failed", error=str(e), slug=product.slug)
        raise HTTPException(status_code=500, detail=str(e))
