"""Rotas para buscar editais e rodar a análise."""
import hmac

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel

from agents.agent0_ingest import editais_de_apify
from agents.orchestrator import executar_com_seguranca, reaplicar_aprendizado, ingerir_apify, ingerir_conlicitacao, ingerir_pncp, processar_novos, salvar_novos
from config import settings
from db.client import get_supabase_client
from routers.auth import exigir_token

router = APIRouter()
protegido = [Depends(exigir_token)]


class BuscaPncp(BaseModel):
    ufs: list[str] | None = None
    dias: int = 45
    processar: bool = False


class BuscaApify(BaseModel):
    actor_input: dict = {}
    processar: bool = False


@router.post("/ingest/pncp", dependencies=protegido)
async def buscar_no_pncp(busca: BuscaPncp, tarefas: BackgroundTasks):
    salvos = await ingerir_pncp(busca.ufs, busca.dias)
    if busca.processar:
        tarefas.add_task(processar_novos)
    return {"salvos": len(salvos)}


@router.post("/ingest/conlicitacao", dependencies=protegido)
async def buscar_na_conlicitacao(tarefas: BackgroundTasks, dias: int = 60, processar: bool = False):
    try:
        salvos = await ingerir_conlicitacao(dias)
    except RuntimeError as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from erro
    if processar:
        tarefas.add_task(processar_novos)
    return {"salvos": len(salvos)}


@router.post("/ingest/apify", dependencies=protegido)
async def buscar_no_apify(busca: BuscaApify, tarefas: BackgroundTasks):
    try:
        salvos = await ingerir_apify(busca.actor_input)
    except RuntimeError as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from erro
    if busca.processar:
        tarefas.add_task(processar_novos)
    return {"salvos": len(salvos)}


@router.post("/webhook/apify")
async def webhook_apify(itens: list[dict], tarefas: BackgroundTasks, x_webhook_secret: str = Header(default="")):
    """Recebe os itens do Apify. Sem segredo configurado, a rota fica desligada."""
    segredo = settings.apify_webhook_secret
    if not segredo or not hmac.compare_digest(x_webhook_secret, segredo):
        raise HTTPException(status_code=401, detail="Segredo inválido.")
    salvos = await salvar_novos(editais_de_apify(itens))
    tarefas.add_task(processar_novos)
    return {"salvos": len(salvos)}


@router.post("/run/novos", dependencies=protegido)
async def rodar_novos(tarefas: BackgroundTasks, limite: int = 20):
    tarefas.add_task(processar_novos, limite)
    return {"status": "iniciado", "limite": limite}


@router.post("/run/{edital_id}", dependencies=protegido)
async def rodar_edital(edital_id: UUID, tarefas: BackgroundTasks):
    linhas = get_supabase_client().table("editais").select("status").eq("id", str(edital_id)).limit(1).execute().data
    if not linhas:
        raise HTTPException(status_code=404, detail="Edital não encontrado.")
    if linhas[0]["status"] == "em_analise":
        raise HTTPException(status_code=409, detail="Este edital já está em análise.")
    tarefas.add_task(executar_com_seguranca, str(edital_id))
    return {"status": "iniciado", "edital_id": str(edital_id)}


@router.post("/reaplicar/{edital_id}", dependencies=protegido)
async def reaplicar(edital_id: UUID):
    """Recalcula a compatibilidade com o aprendizado atual. Rápido e sem custo de IA."""
    try:
        resultado = await reaplicar_aprendizado(str(edital_id))
    except ValueError as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from erro
    return {"status": resultado["status"], "itens": len(resultado["itens"])}
