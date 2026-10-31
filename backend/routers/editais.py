"""
Router — Editais
Endpoints para listagem, filtro, detalhamento e aprovação pelo analista.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from uuid import UUID
from db.client import get_supabase_client
import structlog

router = APIRouter()
log = structlog.get_logger()
# raw_text tem megabytes; a lista não precisa dele.
COLUNAS_LISTA = "id,numero_pregao,orgao,uf,portal_origem,url_edital,data_publicacao,data_abertura,status,licit_context,created_at"


@router.get("/")
async def list_editais(
    status: Optional[str] = Query(None, description="Filtrar por status do edital"),
    orgao: Optional[str] = Query(None, description="Filtrar por órgão"),
):
    """Lista editais com filtros opcionais por status e órgão."""
    try:
        client = get_supabase_client()
        query = client.table("editais").select(COLUNAS_LISTA)

        if status:
            query = query.eq("status", status)
        if orgao:
            query = query.ilike("orgao", f"%{orgao}%")

        result = query.order("data_abertura").limit(500).execute()
        return {"data": result.data, "count": len(result.data)}
    except Exception as e:
        log.error("editais.list_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Erro interno. Veja os logs.")


@router.get("/{edital_id}")
async def get_edital(edital_id: UUID):
    """Detalhes completos de um edital com seus itens e scores."""
    try:
        client = get_supabase_client()
        edital = client.table("editais").select("*").eq("id", str(edital_id)).single().execute()
        if not edital.data:
            raise HTTPException(status_code=404, detail="Edital não encontrado")

        itens = client.table("licit_items").select("*").eq("edital_id", str(edital_id)).execute()

        return {
            "edital": edital.data,
            "itens": itens.data or [],
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("editais.get_failed", error=str(e), edital_id=str(edital_id))
        raise HTTPException(status_code=500, detail="Erro interno. Veja os logs.")


@router.post("/{edital_id}/approve")
async def approve_edital(edital_id: UUID, analista_nota: Optional[str] = None):
    """
    Trava Anti-Vibe: O analista aprova explicitamente.
    Muda status de pendente_revisao_juridica → pronto_para_envio.
    """
    try:
        client = get_supabase_client()
        edital = client.table("editais").select("status,licit_context").eq("id", str(edital_id)).single().execute()

        if not edital.data:
            raise HTTPException(status_code=404, detail="Edital não encontrado")

        current_status = edital.data["status"]
        if current_status not in ["pendente_revisao_juridica", "compatibilidade_calculada"]:
            raise HTTPException(
                status_code=400,
                detail=f"Edital com status '{current_status}' não pode ser aprovado diretamente."
            )

        update_payload = {"status": "pronto_para_envio"}
        if analista_nota:
            update_payload["licit_context"] = {
                **(edital.data.get("licit_context") or {}),
                "analista_nota": analista_nota
            }

        client.table("editais").update(update_payload).eq("id", str(edital_id)).execute()
        log.info("edital.approved_by_analyst", edital_id=str(edital_id))
        return {"status": "pronto_para_envio", "edital_id": str(edital_id)}
    except HTTPException:
        raise
    except Exception as e:
        log.error("editais.approve_failed", error=str(e), edital_id=str(edital_id))
        raise HTTPException(status_code=500, detail="Erro interno. Veja os logs.")


@router.post("/{edital_id}/reject")
async def reject_edital(edital_id: UUID, motivo: Optional[str] = None):
    """O analista rejeita o edital e ele é arquivado."""
    try:
        client = get_supabase_client()
        atual = client.table("editais").select("licit_context").eq("id", str(edital_id)).single().execute()
        contexto = {**((atual.data or {}).get("licit_context") or {}), "motivo_rejeicao": motivo}
        client.table("editais").update({"status": "arquivado", "licit_context": contexto}).eq("id", str(edital_id)).execute()
        log.info("edital.rejected_by_analyst", edital_id=str(edital_id), motivo=motivo)
        return {"status": "arquivado", "edital_id": str(edital_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Erro interno. Veja os logs.")
