"""Rotas de documentos: estoque de declarações e download de arquivos gerados."""
import asyncio
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from agents import documentos
from db.client import get_supabase_client

router = APIRouter()
TIPOS = {"pdf": "application/pdf", "docx": documentos.DOCX}


@router.get("/estoque")
async def estoque():
    lotes = await asyncio.to_thread(documentos.listar_estoque)
    return {"lotes": lotes, "dias_renovacao": documentos.DIAS_ESTOQUE}


@router.post("/estoque")
async def gerar_estoque(forcar: bool = True):
    """Gera um lote novo agora (o automático roda sozinho a cada 30 dias)."""
    try:
        return await documentos.gerar_estoque(forcar=forcar)
    except RuntimeError as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from erro


@router.get("/pregoes")
async def pregoes_com_documentos():
    """Editais aprovados e o estado dos documentos de cada um."""
    linhas = (
        get_supabase_client().table("editais").select("id,numero_pregao,orgao,uf,data_abertura,licit_context")
        .eq("status", "pronto_para_envio").order("data_abertura", desc=True).limit(500).execute().data or []
    )
    return {"data": [
        {k: v for k, v in linha.items() if k != "licit_context"} | {"documentos": (linha.get("licit_context") or {}).get("documentos")}
        for linha in linhas
    ]}


@router.get("/baixar")
async def baixar(caminho: str = Query(..., description="Caminho no bucket, ex.: estoque/2026-11-03/01_habilitacao.pdf")):
    try:
        conteudo = await asyncio.to_thread(documentos.baixar, caminho)
    except ValueError as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from erro
    except Exception as erro:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.") from erro
    extensao = caminho.rsplit(".", 1)[-1].lower()
    nome = caminho.rsplit("/", 1)[-1]
    # PDF abre no navegador; DOCX baixa.
    modo = "inline" if extensao == "pdf" else "attachment"
    return Response(
        content=conteudo,
        media_type=TIPOS.get(extensao, "application/octet-stream"),
        headers={"Content-Disposition": f"{modo}; filename*=UTF-8''{quote(nome)}"},
    )


class ItemAvulso(BaseModel):
    item: str = Field(..., min_length=1)
    descricao: str = Field(..., min_length=2)
    fabricante: str | None = None
    marca: str = Field(..., min_length=1)
    registro: str | None = None
    quantidade: float = Field(..., gt=0)
    valor_unitario: float = Field(..., gt=0)


class PropostaAvulsa(BaseModel):
    orgao: str = Field(..., min_length=3)
    pregao: str | None = None
    processo: str | None = None
    objeto: str | None = None
    cidade: str | None = None
    data: str | None = None
    validade_dias: int | None = None
    itens: list[ItemAvulso] = Field(..., min_length=1)


@router.post("/proposta-avulsa")
async def proposta_avulsa(proposta: PropostaAvulsa):
    """Proposta de qualquer ramo no papel timbrado, só com as informações principais."""
    try:
        return await asyncio.to_thread(documentos.gerar_proposta_avulsa, proposta.model_dump())
    except (RuntimeError, ValueError) as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from erro


@router.get("/avulsas")
async def avulsas():
    return {"data": await asyncio.to_thread(documentos.listar_avulsas)}
