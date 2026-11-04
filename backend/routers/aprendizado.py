"""Rotas do aprendizado: o que o analista ensina ao motor de compatibilidade."""
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents.learning import registrar
from db.client import get_supabase_client

router = APIRouter()
log = structlog.get_logger()


class NovoConhecimento(BaseModel):
    tipo: Literal["regra_fixa", "dica_usuario", "feedback_historico"] = "regra_fixa"
    descritivo_original: str = Field(..., min_length=10, description="Trecho do descritivo que dispara a regra")
    conteudo: str = Field("", description="Motivo ou dica em texto livre")
    produto_id: UUID | None = None
    resultado: Literal["compativel", "incompativel"] | None = None
    peso: float | None = None


class Feedback(BaseModel):
    # correto=True: o sistema acertou. correto=False: errou; produto_correto diz qual atende (ou nenhum).
    correto: bool
    produto_correto_id: UUID | None = None
    motivo: str = ""


@router.get("/")
async def listar():
    client = get_supabase_client()
    linhas = (
        client.table("knowledge_items")
        .select("id,tipo,produto_id,conteudo,descritivo_original,resultado,score_final,peso,created_at")
        .order("created_at", desc=True)
        .limit(1000)
        .execute()
        .data
        or []
    )
    ids = list({linha["produto_id"] for linha in linhas if linha.get("produto_id")})
    nomes = {}
    if ids:
        nomes = {p["id"]: p["nome_comercial"] for p in client.table("products").select("id,nome_comercial").in_("id", ids).execute().data}
    for linha in linhas:
        linha["produto_nome"] = nomes.get(linha.get("produto_id"))
    return {"data": linhas, "total": len(linhas)}


@router.post("/")
async def criar(novo: NovoConhecimento):
    if novo.tipo != "dica_usuario" and not novo.resultado:
        raise HTTPException(status_code=400, detail="Informe se o produto é compatível ou incompatível.")
    if novo.tipo == "dica_usuario" and not novo.conteudo.strip():
        raise HTTPException(status_code=400, detail="Escreva a dica.")
    salvo = registrar(
        tipo=novo.tipo,
        conteudo=novo.conteudo,
        descritivo_original=novo.descritivo_original,
        produto_id=str(novo.produto_id) if novo.produto_id else None,
        resultado=novo.resultado,
        peso=novo.peso,
    )
    return {"data": salvo}


@router.post("/{conhecimento_id}/excluir")
async def excluir(conhecimento_id: UUID):
    client = get_supabase_client()
    apagado = client.table("knowledge_items").delete().eq("id", str(conhecimento_id)).execute().data
    if not apagado:
        raise HTTPException(status_code=404, detail="Item de aprendizado não encontrado.")
    log.info("aprendizado.excluido", id=str(conhecimento_id))
    return {"excluido": str(conhecimento_id)}


def registrar_feedback(item: dict, feedback: Feedback) -> list[dict]:
    """Transforma a correção do analista em uma ou duas linhas de conhecimento."""
    descritivo = item.get("descricao_original") or ""
    sugerido = item.get("produto_id")
    score = item.get("score_compatibilidade")
    motivo = feedback.motivo.strip()
    salvos = []
    if feedback.correto:
        if sugerido:
            salvos.append(registrar(tipo="feedback_historico", conteudo=motivo or "Analista confirmou o produto sugerido.",
                                    descritivo_original=descritivo, produto_id=sugerido, resultado="compativel", score_final=score))
        else:
            # Acertou ao dizer que nada atende: ensina o bloqueio geral.
            salvos.append(registrar(tipo="feedback_historico", conteudo=motivo or "Analista confirmou: nenhum produto atende.",
                                    descritivo_original=descritivo, resultado="incompativel", score_final=score))
        return salvos

    correto = str(feedback.produto_correto_id) if feedback.produto_correto_id else None
    if not correto and not sugerido:
        raise HTTPException(status_code=400, detail="Diga qual produto atende este item.")
    if not correto:
        # "Nenhum produto atende": bloqueia o catálogo inteiro para descritivos assim.
        salvos.append(registrar(tipo="feedback_historico", conteudo=motivo or "Analista: nenhum produto do catálogo atende.",
                                descritivo_original=descritivo, resultado="incompativel", score_final=score))
        return salvos
    if sugerido and sugerido != correto:
        salvos.append(registrar(tipo="feedback_historico", conteudo=motivo or "Analista reprovou o produto sugerido.",
                                descritivo_original=descritivo, produto_id=sugerido, resultado="incompativel", score_final=score))
    salvos.append(registrar(tipo="feedback_historico", conteudo=motivo or "Analista indicou este produto como compatível.",
                            descritivo_original=descritivo, produto_id=correto, resultado="compativel", score_final=score))
    return salvos
