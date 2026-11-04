"""
Router — Editais
Endpoints para listagem, filtro, detalhamento e aprovação pelo analista.
"""
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query
from pydantic import BaseModel, Field

from agents.documentos import gerar_documentos_do_edital
from agents.precos import precificar_edital
from agents.resumo_edital import resumir_edital

from db.client import get_supabase_client
from routers.aprendizado import Feedback, registrar_feedback

router = APIRouter()
log = structlog.get_logger()
# raw_text tem megabytes; a lista não precisa dele.
COLUNAS_LISTA = "id,numero_pregao,orgao,uf,portal_origem,url_edital,data_publicacao,data_abertura,status,licit_context,created_at"
APROVAVEIS = ("compativel", "pendente_revisao_juridica", "compatibilidade_calculada")


class ItemProposta(BaseModel):
    item_id: str
    incluir: bool = True
    quantidade: float = Field(..., gt=0)
    preco_unitario: float = Field(..., gt=0)


class Aprovacao(BaseModel):
    analista_nota: str | None = None
    # Itens ofertados na proposta comercial, com preço e quantidade decididos pelo analista.
    proposta: list[ItemProposta] = []
    # "item_id:campo" → valor informado pelo analista
    gap_correcoes: dict[str, str] = {}
    # item_id → justificativa revisada
    justificativas: dict[str, str] = {}


class Rejeicao(BaseModel):
    motivo: str | None = None


def _contexto_leve(contexto: dict | None) -> dict:
    """A lista não leva o texto bruto nem a análise item a item."""
    contexto = dict(contexto or {})
    for chave in ("raw_text", "itens_analisados"):
        contexto.pop(chave, None)
    return contexto


def _buscar(client, edital_id: UUID, colunas: str) -> dict:
    linhas = client.table("editais").select(colunas).eq("id", str(edital_id)).limit(1).execute().data
    if not linhas:
        raise HTTPException(status_code=404, detail="Edital não encontrado.")
    return linhas[0]


@router.get("/")
async def list_editais(
    status: Optional[str] = Query(None, description="Filtrar por status do edital"),
    orgao: Optional[str] = Query(None, description="Filtrar por órgão"),
    uf: Optional[str] = Query(None, description="Filtrar por UF"),
    abertos: bool = Query(False, description="Só editais com abertura a partir de agora"),
):
    """Lista editais com filtros opcionais. Ordem: abertura mais próxima primeiro."""
    try:
        client = get_supabase_client()
        query = client.table("editais").select(COLUNAS_LISTA)
        if status:
            # Aceita vários status separados por vírgula.
            varios = [s.strip() for s in status.split(",") if s.strip()]
            query = query.in_("status", varios) if len(varios) > 1 else query.eq("status", varios[0])
        if orgao:
            query = query.ilike("orgao", f"%{orgao}%")
        if uf:
            query = query.eq("uf", uf.upper())
        if abertos:
            query = query.gte("data_abertura", datetime.now(timezone.utc).isoformat())
        result = query.order("data_abertura", nullsfirst=False).limit(500).execute()
        dados = [{**linha, "licit_context": _contexto_leve(linha.get("licit_context"))} for linha in result.data]
        return {"data": dados, "count": len(dados)}
    except Exception as e:
        log.error("editais.list_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Erro interno. Veja os logs.")


@router.get("/resumo")
async def resumo_editais():
    """Contagens para os indicadores do painel."""
    try:
        client = get_supabase_client()
        linhas = client.table("editais").select("status,uf,data_abertura").limit(5000).execute().data
        agora = datetime.now(timezone.utc).isoformat()
        semana = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + 7 * 86400, timezone.utc).isoformat()
        abertos = [e for e in linhas if (e.get("data_abertura") or "") >= agora]
        return {
            "total": len(linhas),
            "abertos": len(abertos),
            "abrem_7_dias": sum(1 for e in abertos if e["data_abertura"] <= semana),
            "por_status": dict(Counter(e["status"] for e in linhas)),
            "por_uf": dict(Counter(e.get("uf") or "—" for e in abertos).most_common()),
        }
    except Exception as e:
        log.error("editais.resumo_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Erro interno. Veja os logs.")


@router.get("/{edital_id}")
async def get_edital(edital_id: UUID):
    """Detalhes completos de um edital com seus itens e scores."""
    try:
        client = get_supabase_client()
        edital = _buscar(client, edital_id, COLUNAS_LISTA)
        edital["licit_context"] = {
            k: v for k, v in (edital.get("licit_context") or {}).items() if k != "raw_text"
        }
        itens = client.table("licit_items").select("*").eq("edital_id", str(edital_id)).execute().data or []
        nomes = {}
        ids_produto = {i["produto_id"] for i in itens if i.get("produto_id")}
        if ids_produto:
            produtos = client.table("products").select("id,nome_comercial").in_("id", list(ids_produto)).execute().data
            nomes = {p["id"]: p["nome_comercial"] for p in produtos}
        for item in itens:
            item["produto_nome"] = nomes.get(item.get("produto_id"))
        itens.sort(key=lambda i: [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", str(i.get("numero_item", "")))])
        return {"edital": edital, "itens": itens}
    except HTTPException:
        raise
    except Exception as e:
        log.error("editais.get_failed", error=str(e), edital_id=str(edital_id))
        raise HTTPException(status_code=500, detail="Erro interno. Veja os logs.")


@router.post("/{edital_id}/approve")
async def approve_edital(
    edital_id: UUID,
    tarefas: BackgroundTasks,
    aprovacao: Aprovacao | None = Body(default=None),
    analista_nota: Optional[str] = Query(None, description="Compatibilidade: nota pela query"),
):
    """
    Trava Anti-Vibe: O analista aprova explicitamente.
    Muda status de compatibilidade_calculada/pendente_revisao_juridica → pronto_para_envio.
    """
    dados = aprovacao or Aprovacao()
    nota = (dados.analista_nota or analista_nota or "").strip() or None
    try:
        client = get_supabase_client()
        edital = _buscar(client, edital_id, "status,licit_context")
        current_status = edital["status"]
        if current_status not in APROVAVEIS:
            raise HTTPException(
                status_code=400,
                detail=f"Edital com status '{current_status}' não pode ser aprovado. Rode a análise antes.",
            )

        # Justificativa revisada vale para o item; a original fica no histórico do contexto.
        for item_id, texto in dados.justificativas.items():
            client.table("licit_items").update({"justificativa": texto}).eq("id", item_id).eq(
                "edital_id", str(edital_id)
            ).execute()

        contexto = {**(edital.get("licit_context") or {})}
        contexto["aprovacao"] = {
            "em": datetime.now(timezone.utc).isoformat(),
            "nota": nota,
            "gap_correcoes": dados.gap_correcoes,
            "proposta": [p.model_dump() for p in dados.proposta if p.incluir],
        }
        contexto["documentos"] = {"status": "gerando"}
        if nota:
            contexto["analista_nota"] = nota
        client.table("editais").update({"status": "pronto_para_envio", "licit_context": contexto}).eq(
            "id", str(edital_id)
        ).execute()
        log.info("edital.approved_by_analyst", edital_id=str(edital_id))
        # Proposta e declarações saem depois da aprovação, em segundo plano.
        tarefas.add_task(gerar_documentos_do_edital, str(edital_id))
        return {"status": "pronto_para_envio", "edital_id": str(edital_id)}
    except HTTPException:
        raise
    except Exception as e:
        log.error("editais.approve_failed", error=str(e), edital_id=str(edital_id))
        raise HTTPException(status_code=500, detail="Erro interno. Veja os logs.")


@router.post("/{edital_id}/reject")
async def reject_edital(
    edital_id: UUID,
    rejeicao: Rejeicao | None = Body(default=None),
    motivo: Optional[str] = Query(None),
):
    """O analista rejeita o edital e ele é arquivado."""
    texto = ((rejeicao.motivo if rejeicao else None) or motivo or "").strip() or None
    try:
        client = get_supabase_client()
        atual = _buscar(client, edital_id, "licit_context")
        contexto = {**(atual.get("licit_context") or {}), "motivo_rejeicao": texto}
        client.table("editais").update({"status": "arquivado", "licit_context": contexto}).eq(
            "id", str(edital_id)
        ).execute()
        log.info("edital.rejected_by_analyst", edital_id=str(edital_id), motivo=texto)
        return {"status": "arquivado", "edital_id": str(edital_id)}
    except HTTPException:
        raise
    except Exception as e:
        log.error("editais.reject_failed", error=str(e), edital_id=str(edital_id))
        raise HTTPException(status_code=500, detail="Erro interno. Veja os logs.")


@router.post("/{edital_id}/reabrir")
async def reabrir_edital(edital_id: UUID):
    """Desfaz arquivamento ou aprovação: volta para revisão do analista."""
    try:
        client = get_supabase_client()
        atual = _buscar(client, edital_id, "status,licit_context")
        contexto = atual.get("licit_context") or {}
        if contexto.get("itens_analisados"):
            novo = "compativel" if contexto.get("apto_participar") else "compatibilidade_calculada"
        else:
            novo = "novo"
        client.table("editais").update({"status": novo}).eq("id", str(edital_id)).execute()
        return {"status": novo, "edital_id": str(edital_id)}
    except HTTPException:
        raise
    except Exception as e:
        log.error("editais.reabrir_failed", error=str(e), edital_id=str(edital_id))
        raise HTTPException(status_code=500, detail="Erro interno. Veja os logs.")


@router.post("/{edital_id}/itens/{item_id}/feedback")
async def feedback_item(edital_id: UUID, item_id: UUID, feedback: Feedback):
    """O analista diz se o sistema acertou o item. Vira aprendizado para os próximos editais."""
    client = get_supabase_client()
    linhas = (
        client.table("licit_items").select("id,descricao_original,produto_id,score_compatibilidade")
        .eq("id", str(item_id)).eq("edital_id", str(edital_id)).limit(1).execute().data
    )
    if not linhas:
        raise HTTPException(status_code=404, detail="Item não encontrado neste edital.")
    salvos = registrar_feedback(linhas[0], feedback)
    return {"registrados": len(salvos)}


@router.post("/{edital_id}/resumo")
async def gerar_resumo(edital_id: UUID):
    """Resumo do edital por IA a partir do texto já salvo (para editais analisados antes do resumo existir)."""
    try:
        return {"resumo": await resumir_edital(str(edital_id))}
    except ValueError as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from erro
    except RuntimeError as erro:
        raise HTTPException(status_code=502, detail=str(erro)) from erro


class Regerar(BaseModel):
    # Opcional: preços/quantidades novos para a proposta (ex.: edital aprovado antes de existir proposta).
    proposta: list[ItemProposta] | None = None


@router.post("/{edital_id}/documentos")
async def regerar_documentos(edital_id: UUID, tarefas: BackgroundTasks, dados: Regerar | None = Body(default=None)):
    """Gera de novo proposta e declarações (ex.: preço corrigido, modelo ou dados da empresa trocados)."""
    client = get_supabase_client()
    edital = _buscar(client, edital_id, "status,licit_context")
    if edital["status"] != "pronto_para_envio":
        raise HTTPException(status_code=400, detail="Documentos só saem depois da aprovação.")
    contexto = {**(edital.get("licit_context") or {}), "documentos": {"status": "gerando"}}
    if dados and dados.proposta is not None:
        aprovacao = {**(contexto.get("aprovacao") or {})}
        aprovacao["proposta"] = [p.model_dump() for p in dados.proposta if p.incluir]
        contexto["aprovacao"] = aprovacao
    client.table("editais").update({"licit_context": contexto}).eq("id", str(edital_id)).execute()
    tarefas.add_task(gerar_documentos_do_edital, str(edital_id))
    return {"status": "gerando"}


@router.post("/{edital_id}/precificar")
async def precificar(edital_id: UUID):
    """Recalcula preço mínimo por item e valor total por produto com a tabela atual."""
    client = get_supabase_client()
    edital = _buscar(client, edital_id, "licit_context")
    resultado = precificar_edital(client, str(edital_id))
    contexto = {**(edital.get("licit_context") or {}), "precificacao": resultado}
    client.table("editais").update({"licit_context": contexto}).eq("id", str(edital_id)).execute()
    return resultado
