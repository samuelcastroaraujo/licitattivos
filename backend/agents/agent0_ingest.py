"""
Agente 0 — Entrada de editais.
Fontes: busca pública do PNCP (sem custo) e actors do Apify (demais portais).
Só deixa passar editais cujo objeto tem relação com nutrição clínica.
"""
import asyncio
import io
import re
import zipfile
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any

import fitz
import httpx
import structlog

from config import settings
from models.edital import EditalCreate

log = structlog.get_logger()

PNCP_BUSCA = "https://pncp.gov.br/api/consulta/v1/contratacoes/proposta"
PNCP_ARQUIVOS = "https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos"
MODALIDADE_PREGAO = 6
PAUSA_PAGINAS = 1.0
ESPERAS_PNCP = (5, 15, 30)
PALAVRAS = (
    "nutric", "nutrit", "dieta", "suplement", "formula infantil", "formulas infantis",
    "formula enteral", "enteral", "whey", "modulo de proteina", "espessante", "maltodextrina",
    "glutamina", "alimentacao especial", "fraldas e dietas",
)


def normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto or "")
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def objeto_relevante(objeto: str) -> bool:
    alvo = normalizar(objeto)
    return any(p in alvo for p in PALAVRAS)


def _para_datetime(valor: Any) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None


def _primeiro(item: dict, *chaves: str) -> Any:
    for chave in chaves:
        atual: Any = item
        for parte in chave.split("."):
            atual = atual.get(parte) if isinstance(atual, dict) else None
        if atual not in (None, ""):
            return atual
    return None


def edital_de_pncp(item: dict) -> EditalCreate:
    orgao = item.get("orgaoEntidade") or {}
    unidade = item.get("unidadeOrgao") or {}
    publicado = _para_datetime(item.get("dataPublicacaoPncp"))
    # A data que importa é o fim do envio de propostas.
    abertura = _para_datetime(item.get("dataEncerramentoProposta") or item.get("dataAberturaProposta"))
    return EditalCreate(
        numero_pregao=f"{item.get('numeroCompra', '')}/{item.get('anoCompra', '')}",
        orgao=orgao.get("razaoSocial", ""),
        uf=unidade.get("ufSigla"),
        portal_origem="pncp",
        url_edital=item.get("linkSistemaOrigem"),
        data_publicacao=publicado.date() if publicado else None,
        data_abertura=abertura,
    )


async def _url_do_edital(http: httpx.AsyncClient, item: dict) -> str | None:
    cnpj = (item.get("orgaoEntidade") or {}).get("cnpj")
    if not cnpj:
        return None
    url = PNCP_ARQUIVOS.format(cnpj=cnpj, ano=item.get("anoCompra"), seq=item.get("sequencialCompra"))
    try:
        resposta = await http.get(url, timeout=30.0)
        resposta.raise_for_status()
        arquivos = resposta.json()
    except (httpx.HTTPError, ValueError) as erro:
        log.warning("pncp.arquivos_falhou", url=url, error=str(erro))
        return None
    ativos = [a for a in arquivos if a.get("statusAtivo", True)]
    edital = next((a for a in ativos if a.get("tipoDocumentoId") == 2), ativos[0] if ativos else None)
    return edital.get("url") if edital else None


async def _get_com_espera(http: httpx.AsyncClient, params: dict[str, Any]) -> httpx.Response | None:
    """O PNCP limita o volume de consultas: espera e tenta de novo antes de desistir."""
    for espera in ESPERAS_PNCP:
        try:
            resposta = await http.get(PNCP_BUSCA, params=params, timeout=60.0)
        except httpx.TransportError as erro:
            log.warning("pncp.conexao_falhou", error=str(erro))
        else:
            if resposta.status_code not in (429, 500, 502, 503, 504):
                resposta.raise_for_status()
                return resposta
            log.warning("pncp.aguardando", status=resposta.status_code, segundos=espera)
        await asyncio.sleep(espera)
    return None


async def buscar_pncp(ufs: list[str] | None = None, dias: int = 45, max_paginas: int = 20) -> list[EditalCreate]:
    """Pregões com proposta aberta, filtrados pelo objeto."""
    data_final = (date.today() + timedelta(days=dias)).strftime("%Y%m%d")
    encontrados: list[EditalCreate] = []
    async with httpx.AsyncClient() as http:
        for uf in ufs or [None]:
            pagina = 1
            while pagina <= max_paginas:
                params: dict[str, Any] = {
                    "dataFinal": data_final,
                    "codigoModalidadeContratacao": MODALIDADE_PREGAO,
                    "pagina": pagina,
                    "tamanhoPagina": 50,
                }
                if uf:
                    params["uf"] = uf
                resposta = await _get_com_espera(http, params)
                if resposta is None:
                    # Mantém o que já veio; a próxima rotina completa o restante.
                    log.warning("pncp.pagina_ignorada", uf=uf, pagina=pagina)
                    break
                if resposta.status_code == 204:
                    break
                corpo = resposta.json()
                for item in corpo.get("data", []):
                    if not objeto_relevante(item.get("objetoCompra", "")):
                        continue
                    edital = edital_de_pncp(item)
                    edital.anexo_url_origem = await _url_do_edital(http, item)
                    encontrados.append(edital)
                if not corpo.get("paginasRestantes"):
                    break
                pagina += 1
                await asyncio.sleep(PAUSA_PAGINAS)
    log.info("pncp.busca_concluida", total=len(encontrados))
    return encontrados


def edital_de_apify(item: dict) -> EditalCreate | None:
    """Aceita nomes de campo diferentes, porque cada actor devolve o seu formato."""
    orgao = _primeiro(item, "orgao", "orgaoNome", "orgaoEntidade.razaoSocial", "buyer", "agency", "entity")
    numero = _primeiro(item, "numero_pregao", "numeroPregao", "numero", "numeroCompra", "number", "id")
    if not orgao or not numero:
        return None
    objeto = str(_primeiro(item, "objeto", "objetoCompra", "object", "description", "title", "titulo") or "")
    if objeto and not objeto_relevante(objeto):
        return None
    publicado = _para_datetime(_primeiro(item, "data_publicacao", "dataPublicacao", "dataPublicacaoPncp", "publishedAt"))
    abertura = _para_datetime(_primeiro(item, "data_abertura", "dataAbertura", "dataEncerramentoProposta", "openingDate", "deadline"))
    return EditalCreate(
        numero_pregao=str(numero),
        orgao=str(orgao),
        uf=_primeiro(item, "uf", "unidadeOrgao.ufSigla", "state"),
        portal_origem=str(_primeiro(item, "portal", "portal_origem", "source") or "apify"),
        url_edital=_primeiro(item, "url", "url_edital", "link", "linkSistemaOrigem"),
        anexo_url_origem=_primeiro(item, "anexo_url", "pdfUrl", "pdf", "editalUrl", "fileUrl", "attachmentUrl"),
        data_publicacao=publicado.date() if publicado else None,
        data_abertura=abertura,
    )


def editais_de_apify(itens: list[dict]) -> list[EditalCreate]:
    editais = [edital_de_apify(item) for item in itens]
    validos = [e for e in editais if e]
    log.info("apify.normalizado", recebidos=len(itens), aproveitados=len(validos))
    return validos


CONLICITACAO_BASE = "https://consultaonline.conlicitacao.com.br"
CONLICITACAO_TERMOS = ("DIETA ENTERAL", "SUPLEMENTO ALIMENTAR", "FORMULA INFANTIL", "MODULO DE PROTEINA", "ESPESSANTE")


def edital_de_conlicitacao(lance: dict) -> EditalCreate | None:
    orgao = (lance.get("public_body") or {}).get("nome")
    numero = lance.get("edital") or lance.get("processo") or lance.get("bidding_id") or lance.get("id")
    if not orgao or not numero:
        return None
    prazo = _para_datetime(lance.get("datahora_prazo") or lance.get("datahora_documento") or lance.get("datahora_abertura"))
    if prazo is None and lance.get("data_validade"):
        prazo = _para_datetime(f"{lance['data_validade']}T00:00:00-03:00")
    criado = _para_datetime(lance.get("created"))
    arquivos = lance.get("edicts") or []
    caminho = arquivos[0].get("url") if arquivos else None
    if caminho and caminho.startswith("/"):
        caminho = CONLICITACAO_BASE + caminho
    return EditalCreate(
        numero_pregao=f"{numero} #{lance.get('id')}",
        orgao=str(orgao),
        uf=lance.get("orgao_estado"),
        portal_origem="conlicitacao",
        url_edital=lance.get("edital_site") or None,
        anexo_url_origem=caminho,
        data_publicacao=criado.date() if criado else None,
        data_abertura=prazo,
    )


def lances_do_dataset(itens: list[dict]) -> tuple[list[dict], int]:
    """Abre a resposta da task HTTP. Sessão vencida não traz a lista de editais."""
    lances: list[dict] = []
    paginas = 0
    for item in itens:
        corpo = item.get("data")
        if not isinstance(corpo, dict) or "biddings" not in corpo:
            raise RuntimeError("Sessão da ConLicitação vencida ou resposta inesperada. Renove o cookie na task do Apify.")
        lances.extend(corpo["biddings"])
        paginas = max(paginas, int(corpo.get("total_pages") or 0))
    return lances, paginas


async def buscar_conlicitacao(termos: tuple[str, ...] = CONLICITACAO_TERMOS, dias: int = 60, max_paginas: int = 10) -> list[EditalCreate]:
    """Roda a task do Apify, que guarda o cookie da sessão, para cada termo e página."""
    if not settings.apify_token or not settings.apify_task_id:
        raise RuntimeError("Configure APIFY_TOKEN e APIFY_TASK_ID.")
    base = f"https://api.apify.com/v2/actor-tasks/{settings.apify_task_id}"
    cabecalho = {"Authorization": f"Bearer {settings.apify_token}"}
    hoje = date.today()
    editais: list[EditalCreate] = []
    async with httpx.AsyncClient(headers=cabecalho) as http:
        resposta = await http.get(f"{base}/input", timeout=60.0)
        resposta.raise_for_status()
        entrada = resposta.json()
        for termo in termos:
            pagina, total = 1, 1
            while pagina <= min(total, max_paginas):
                entrada["params"] = {
                    **entrada.get("params", {}),
                    "objeto": termo,
                    "page": str(pagina),
                    "data_validade[from]": f"{hoje.isoformat()}T00:00:00.0000-03:00",
                    "data_validade[to]": f"{(hoje + timedelta(days=dias)).isoformat()}T23:59:59.0000-03:00",
                }
                resposta = await http.post(f"{base}/run-sync-get-dataset-items", params={"timeout": 120}, json=entrada, timeout=180.0)
                resposta.raise_for_status()
                lances, total = lances_do_dataset(resposta.json())
                editais.extend(e for e in map(edital_de_conlicitacao, lances) if e)
                pagina += 1
    log.info("conlicitacao.busca_concluida", total=len(editais))
    return sem_duplicados(editais)


def pdf_do_arquivo(conteudo: bytes) -> bytes:
    """A ConLicitação entrega ZIP com arquivo_1.pdf, arquivo_2.pdf... sem dizer qual é o edital.
    Junta todos os PDFs para nenhum item ou anexo ficar de fora da análise."""
    if not conteudo.startswith(b"PK"):
        return conteudo
    juntos = fitz.open()
    with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
        nomes = sorted(
            (a for a in pacote.infolist() if a.filename.lower().endswith(".pdf")),
            key=lambda a: [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", a.filename.lower())],
        )
        for arquivo in nomes:
            try:
                with fitz.open(stream=pacote.read(arquivo), filetype="pdf") as pdf:
                    juntos.insert_pdf(pdf)
            except (fitz.FileDataError, RuntimeError) as erro:
                log.warning("zip.pdf_ignorado", arquivo=arquivo.filename, error=str(erro))
    if juntos.page_count == 0:
        raise ValueError("ZIP sem PDF legível.")
    return juntos.tobytes()


async def cookie_conlicitacao() -> str:
    """O cookie fica só na task do Apify, para haver um único lugar de renovação."""
    if not settings.apify_token or not settings.apify_task_id:
        raise RuntimeError("Configure APIFY_TOKEN e APIFY_TASK_ID.")
    async with httpx.AsyncClient() as http:
        resposta = await http.get(
            f"https://api.apify.com/v2/actor-tasks/{settings.apify_task_id}/input",
            headers={"Authorization": f"Bearer {settings.apify_token}"},
            timeout=60.0,
        )
        resposta.raise_for_status()
        return resposta.json().get("headers", {}).get("cookie", "")


async def buscar_apify(actor_input: dict | None = None) -> list[EditalCreate]:
    """Roda o actor configurado e devolve os editais do dataset."""
    if not settings.apify_token or not settings.apify_actor_id:
        raise RuntimeError("Configure APIFY_TOKEN e APIFY_ACTOR_ID.")
    actor = settings.apify_actor_id.replace("/", "~")
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
    async with httpx.AsyncClient() as http:
        resposta = await http.post(
            url,
            json=actor_input or {},
            headers={"Authorization": f"Bearer {settings.apify_token}"},
            timeout=300.0,
        )
        resposta.raise_for_status()
        return editais_de_apify(resposta.json())


def sem_duplicados(editais: list[EditalCreate]) -> list[EditalCreate]:
    """O upsert em lote falha se a mesma chave aparece duas vezes."""
    unicos: dict[tuple[str, str, str], EditalCreate] = {}
    for edital in editais:
        unicos[(edital.portal_origem, edital.orgao, edital.numero_pregao)] = edital
    return list(unicos.values())
