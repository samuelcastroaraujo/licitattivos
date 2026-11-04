"""
Orquestrador: entrada do edital → download → texto → requisitos → compatibilidade → inteligência.
Termina em 'compatibilidade_calculada', e a decisão continua humana.
"""
from datetime import datetime, timezone

import structlog

from agents.agent0_ingest import anexo_pelo_pncp, buscar_apify, buscar_conlicitacao, buscar_pncp, sem_duplicados
from agents.agent1_pncp import download_edital_anexo, save_editais
from agents.agent2_parser import extract_text_from_file
from agents.agent3_requirements import extract_requirements
from agents.agent4_compatibility import match_product
from agents.intelligence import analisar_orgao, historico_produto
from db.client import get_supabase_client
from agents.learning import carregar_conhecimento, relevantes
from agents.precos import precificar_edital
from agents.resumo_edital import resumir_texto
from models.edital import Edital, EditalCreate, LicitItem
from models.product import Product

log = structlog.get_logger()
SCORE_COMPATIVEL = 0.70
# Um item 100% compatível já basta para valer a pena disputar o edital.
SCORE_TOTAL = 0.999


def resultado_do_edital(analise: list[dict]) -> tuple[str, list[str]]:
    """Status final e itens 100%: com pelo menos um, o edital fica apto a participar."""
    cem = [a["numero_item"] for a in analise if (a.get("score") or 0) >= SCORE_TOTAL]
    return ("compativel" if cem else "compatibilidade_calculada"), cem
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


async def _pontuar_itens(client, edital: Edital, itens, produtos: list[Product], conhecimento: list[dict] | None = None) -> list[dict]:
    salvos = client.table("licit_items").select("id,numero_item").eq("edital_id", str(edital.id)).execute().data
    # O mesmo número de item pode repetir em lotes diferentes.
    ids: dict[str, list[str]] = {}
    for linha in salvos:
        ids.setdefault(linha["numero_item"], []).append(linha["id"])
    resultado = []
    for item in itens:
        # Aprendizado: o que o analista já decidiu em descritivos parecidos (busca uma vez por item).
        parecidos = relevantes(item.descricao_original, conhecimento or [])
        dicas = [k["conteudo"] for k in parecidos if k.get("tipo") == "dica_usuario"][:3]
        melhor, melhor_produto = None, None
        for produto in produtos:
            nota = await match_product(item, produto, parecidos)
            if melhor is None or nota.score > melhor.score:
                melhor, melhor_produto = nota, produto
        if melhor is None or melhor_produto is None:
            continue
        compativel = melhor.score >= SCORE_COMPATIVEL
        justificativa = melhor.justificativa_tecnica + "".join(f" Dica do analista: {d}" for d in dicas)
        fila = ids.get(item.numero_item) or []
        if fila:
            client.table("licit_items").update({
                # Sem compatibilidade, nenhum produto é sugerido.
                "produto_id": str(melhor_produto.id) if compativel else None,
                "score_compatibilidade": melhor.score,
                "compativel": compativel,
                "justificativa": justificativa,
            }).eq("id", fila.pop(0)).execute()
        resultado.append({
            "numero_item": item.numero_item,
            "produto": melhor_produto.nome_comercial if compativel else None,
            "score": melhor.score,
            "status": melhor.status,
            "aprendizado": "Aprendizado:" in melhor.justificativa_tecnica,
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
    # Erro de tentativa anterior não pode aparecer como se fosse desta.
    (edital.licit_context or {}).pop("erro_pipeline", None)
    # O painel mostra que a análise está rodando e não deixa disparar de novo.
    client.table("editais").update({"status": "em_analise"}).eq("id", edital_id).execute()

    if not edital.anexo_url_origem and not edital.anexo_local_path:
        # ConLicitação às vezes não traz o arquivo, mas aponta para a página do PNCP.
        edital.anexo_url_origem = await anexo_pelo_pncp(edital.url_edital)
        if edital.anexo_url_origem:
            client.table("editais").update({"anexo_url_origem": edital.anexo_url_origem}).eq("id", edital_id).execute()
    if not edital.anexo_local_path:
        edital = await download_edital_anexo(edital)
    if not edital.anexo_local_path:
        _marcar(client, edital, "revisao_manual_parser", "Edital sem PDF disponível.")
        return {"edital_id": edital_id, "status": edital.status}

    caminho = edital.anexo_local_path
    arquivo = client.storage.from_("editais_anexos").download(caminho)
    edital = await extract_text_from_file(edital, arquivo)
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

    try:
        # Resumo do edital para o relatório; se a IA falhar aqui, a análise segue.
        edital.licit_context["resumo"] = await resumir_texto(edital.licit_context.get("raw_text", ""))
    except Exception as erro:
        log.warning("pipeline.resumo_falhou", edital_id=edital_id, error=str(erro))
        edital.licit_context["erro_resumo"] = str(erro)[:300]
    await _finalizar_analise(client, edital, itens)
    return {"edital_id": edital_id, "status": edital.status, "itens": edital.licit_context.get("itens_analisados", [])}


async def _finalizar_analise(client, edital: Edital, itens: list[LicitItem]) -> list[dict]:
    """Compatibilidade + aprendizado + inteligência. Não chama IA: dá para repetir de graça."""
    produtos = carregar_produtos(client)
    conhecimento = carregar_conhecimento(client)
    analise = await _pontuar_itens(client, edital, itens, produtos, conhecimento)
    edital.licit_context = {
        **(edital.licit_context or {}),
        "score_medio": round(sum(a["score"] for a in analise) / len(analise), 2) if analise else None,
        "inteligencia": analisar_orgao(edital.orgao, edital.uf),
        "itens_analisados": analise,
    }
    status_final, itens_100 = resultado_do_edital(analise)
    edital.licit_context["itens_100"] = itens_100
    edital.licit_context["apto_participar"] = bool(itens_100)
    edital.licit_context["conhecimento_usado"] = len(conhecimento)
    try:
        # Valor mínimo de cotação por item e por produto (tabela de preços com desconto).
        edital.licit_context["precificacao"] = precificar_edital(client, str(edital.id))
    except Exception as erro:
        log.warning("pipeline.precificacao_falhou", edital_id=str(edital.id), error=str(erro))
    _marcar(client, edital, status_final)
    log.info("pipeline.concluido", edital_id=str(edital.id), itens=len(analise), conhecimento=len(conhecimento))
    return analise


async def reaplicar_aprendizado(edital_id: str) -> dict:
    """Recalcula a compatibilidade com os itens já extraídos e o aprendizado atual, sem IA."""
    client = get_supabase_client()
    linha = client.table("editais").select("*").eq("id", edital_id).single().execute().data
    edital = Edital.model_validate(linha)
    linhas = client.table("licit_items").select("*").eq("edital_id", edital_id).order("created_at").execute().data or []
    if not linhas:
        raise ValueError("Este edital ainda não tem itens extraídos. Rode a análise primeiro.")
    itens = [
        LicitItem(numero_item=r["numero_item"], descricao_original=r.get("descricao_original") or "",
                  tipo_produto=r.get("tipo_produto"), requisitos=r.get("requisitos") or {},
                  preco_referencia=r.get("preco_referencia"))
        for r in linhas
    ]
    edital.licit_context.pop("erro_pipeline", None)
    analise = await _finalizar_analise(client, edital, itens)
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
    return [await executar_com_seguranca(linha["id"]) for linha in novos]


EM_CURSO = ("em_analise", "anexo_baixado", "texto_extraido", "requisitos_extraidos")


def destravar_analises_interrompidas() -> int:
    """Análise roda dentro do servidor: se ele reiniciou no meio, o edital ficaria preso para sempre."""
    client = get_supabase_client()
    try:
        presos = client.table("editais").select("id,licit_context").in_("status", list(EM_CURSO)).execute().data
        for linha in presos:
            contexto = {**(linha.get("licit_context") or {}), "erro_pipeline": "Análise interrompida: o servidor reiniciou. Rode de novo."}
            client.table("editais").update({"status": "erro_pipeline", "licit_context": contexto}).eq("id", linha["id"]).execute()
        if presos:
            log.warning("pipeline.destravados", total=len(presos))
        return len(presos)
    except Exception as erro:
        log.error("pipeline.destravar_falhou", error=str(erro))
        return 0


async def executar_com_seguranca(edital_id: str) -> dict:
    """Roda o pipeline sem deixar o edital preso em 'em_analise' se algo quebrar."""
    try:
        return await executar_pipeline(edital_id)
    except Exception as erro:
        motivo = str(erro) or erro.__class__.__name__
        log.error("pipeline.falhou", edital_id=edital_id, error=motivo)
        client = get_supabase_client()
        try:
            atual = client.table("editais").select("licit_context").eq("id", edital_id).limit(1).execute().data
            contexto = {**((atual[0].get("licit_context") if atual else None) or {}), "erro_pipeline": motivo[:500]}
            contexto.pop("raw_text", None)
            client.table("editais").update({"status": "erro_pipeline", "licit_context": contexto}).eq("id", edital_id).execute()
        except Exception as erro_banco:
            log.error("pipeline.falhou_ao_marcar", edital_id=edital_id, error=str(erro_banco))
        return {"edital_id": edital_id, "status": "erro_pipeline", "erro": motivo}
