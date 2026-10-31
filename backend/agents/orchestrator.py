"""
Orquestrador: entrada do edital → download → texto → requisitos → compatibilidade → inteligência.
Termina em 'compatibilidade_calculada', e a decisão continua humana.
"""
from datetime import datetime, timezone

import structlog

from agents.agent0_ingest import buscar_apify, buscar_conlicitacao, buscar_pncp, pdf_do_arquivo, sem_duplicados
from agents.agent1_pncp import download_edital_anexo, save_editais
from agents.agent2_parser import extract_text_from_pdf
from agents.agent3_requirements import extract_requirements
from agents.agent4_compatibility import match_product
from agents.intelligence import analisar_orgao, historico_produto
from db.client import get_supabase_client
from models.edital import Edital, EditalCreate
from models.product import Product

log = structlog.get_logger()
SCORE_COMPATIVEL = 0.70
MARCA_LICITACAO = "PHOLIAS"


async def salvar_novos(editais: list[EditalCreate]) -> list[Edital]:
    return await save_editais(sem_duplicados(editais))


async def ingerir_pncp(ufs: list[str] | None = None, dias: int = 45) -> list[Edital]:
    return await salvar_novos(await buscar_pncp(ufs=ufs, dias=dias))


async def ingerir_conlicitacao(dias: int = 60) -> list[Edital]:
    return await salvar_novos(await buscar_conlicitacao(dias=dias))


async def ingerir_apify(actor_input: dict | None = None) -> list[Edital]:
    return await salvar_novos(await buscar_apify(actor_input))


def _marcar(client, edital: Edital, status: str, motivo: str | None = None) -> None:
    contexto = dict(edital.licit_context or {})
    contexto.pop("raw_text", None)
    if motivo:
        contexto["erro_pipeline"] = motivo
    client.table("editais").update({"status": status, "licit_context": contexto}).eq("id", str(edital.id)).execute()
    edital.status = status


async def _pontuar_itens(client, edital: Edital, itens, produtos: list[Product]) -> list[dict]:
    salvos = client.table("licit_items").select("id,numero_item").eq("edital_id", str(edital.id)).execute().data
    # O mesmo número de item pode repetir em lotes diferentes.
    ids: dict[str, list[str]] = {}
    for linha in salvos:
        ids.setdefault(linha["numero_item"], []).append(linha["id"])
    resultado = []
    for item in itens:
        melhor, melhor_produto = None, None
        for produto in produtos:
            nota = await match_product(item, produto)
            if melhor is None or nota.score > melhor.score:
                melhor, melhor_produto = nota, produto
        if melhor is None or melhor_produto is None:
            continue
        compativel = melhor.score >= SCORE_COMPATIVEL
        fila = ids.get(item.numero_item) or []
        if fila:
            client.table("licit_items").update({
                # Sem compatibilidade, nenhum produto é sugerido.
                "produto_id": str(melhor_produto.id) if compativel else None,
                "score_compatibilidade": melhor.score,
                "compativel": compativel,
                "justificativa": melhor.justificativa_tecnica,
            }).eq("id", fila.pop(0)).execute()
        resultado.append({
            "numero_item": item.numero_item,
            "produto": melhor_produto.nome_comercial if compativel else None,
            "score": melhor.score,
            "status": melhor.status,
            "historico_precos": historico_produto(melhor_produto.nome_comercial) if compativel else [],
        })
    return resultado


def carregar_produtos(client) -> list[Product]:
    """Só Pholias entra em licitação de nutrição clínica; o banco também guarda a linha esportiva Venum."""
    linhas = client.table("products").select("*").execute().data
    produtos = []
    for linha in linhas:
        if (linha.get("marca") or "").upper() != MARCA_LICITACAO:
            continue
        try:
            produtos.append(Product.model_validate(linha))
        except ValueError as erro:
            log.warning("produto.invalido", slug=linha.get("slug"), error=str(erro))
    return produtos


async def executar_pipeline(edital_id: str) -> dict:
    client = get_supabase_client()
    linha = client.table("editais").select("*").eq("id", edital_id).single().execute().data
    edital = Edital.model_validate(linha)

    if not edital.anexo_local_path:
        edital = await download_edital_anexo(edital)
    if not edital.anexo_local_path:
        _marcar(client, edital, "revisao_manual_parser", "Edital sem PDF disponível.")
        return {"edital_id": edital_id, "status": edital.status}

    caminho = edital.anexo_local_path
    pdf = client.storage.from_("editais_anexos").download(caminho)
    edital = await extract_text_from_pdf(edital, pdf_do_arquivo(pdf))
    # O texto já está no banco. Manter os arquivos estouraria o armazenamento grátis em cerca de 100 editais.
    client.storage.from_("editais_anexos").remove([caminho])
    client.table("editais").update({"anexo_local_path": None}).eq("id", edital_id).execute()
    edital.anexo_local_path = None
    if edital.status != "texto_extraido":
        return {"edital_id": edital_id, "status": edital.status}

    # Evita itens duplicados quando o edital é reprocessado.
    client.table("licit_items").delete().eq("edital_id", edital_id).execute()
    itens = await extract_requirements(edital)
    if not itens:
        _marcar(client, edital, "revisao_manual_parser", "Nenhum item extraído do edital.")
        return {"edital_id": edital_id, "status": edital.status}

    produtos = carregar_produtos(client)
    analise = await _pontuar_itens(client, edital, itens, produtos)
    edital.licit_context = {
        **(edital.licit_context or {}),
        "score_medio": round(sum(a["score"] for a in analise) / len(analise), 2) if analise else None,
        "inteligencia": analisar_orgao(edital.orgao, edital.uf),
        "itens_analisados": analise,
    }
    _marcar(client, edital, "compatibilidade_calculada")
    log.info("pipeline.concluido", edital_id=edital_id, itens=len(analise))
    return {"edital_id": edital_id, "status": edital.status, "itens": analise}


async def processar_novos(limite: int = 20) -> list[dict]:
    """Processa os editais ainda não analisados. Um erro não derruba os demais."""
    client = get_supabase_client()
    # Limite por rodada controla o custo; edital com prazo vencido não vale a análise.
    agora = datetime.now(timezone.utc).isoformat()
    novos = (
        client.table("editais").select("id").eq("status", "novo").gte("data_abertura", agora)
        .order("data_abertura").limit(limite).execute().data
    )
    resultados = []
    for linha in novos:
        try:
            resultados.append(await executar_pipeline(linha["id"]))
        except Exception as erro:
            log.error("pipeline.falhou", edital_id=linha["id"], error=str(erro))
            client.table("editais").update({"status": "erro_pipeline"}).eq("id", linha["id"]).execute()
            resultados.append({"edital_id": linha["id"], "status": "erro_pipeline", "erro": str(erro)})
    return resultados
