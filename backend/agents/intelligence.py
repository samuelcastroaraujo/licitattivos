"""
Inteligência histórica: cruza o edital com vendas, preços e recebimentos passados.
Os dados ficam na tabela knowledge_snapshot; o arquivo local é só alternativa em desenvolvimento.
"""
import json
import re
from pathlib import Path

import structlog

from agents.agent0_ingest import normalizar
from db.client import get_supabase_client

log = structlog.get_logger()

ARQUIVO_LOCAL = Path(__file__).resolve().parent.parent / "knowledge" / "snapshot.json"
_cache: dict | None = None
PUBLICO_MUNICIPAL = re.compile(r"prefeitura|municipio|fundo municipal|secretaria municipal")


def carregar_snapshot(recarregar: bool = False) -> dict:
    global _cache
    if _cache is not None and not recarregar:
        return _cache
    try:
        resposta = get_supabase_client().table("knowledge_snapshot").select("data").eq("key", "historico").execute()
        if resposta.data:
            _cache = resposta.data[0]["data"]
            return _cache
    except Exception as erro:  # sem banco, tenta o arquivo local
        log.warning("intelligence.snapshot_db_falhou", error=str(erro))
    if ARQUIVO_LOCAL.exists():
        _cache = json.loads(ARQUIVO_LOCAL.read_text(encoding="utf-8"))
        return _cache
    return {"clientes": [], "produtos": [], "regras": []}


def _cliente(orgao: str, uf: str | None, snapshot: dict) -> dict | None:
    alvo = normalizar(orgao)
    candidatos = [c for c in snapshot.get("clientes", []) if not uf or not c.get("uf") or c["uf"] == uf]
    for cliente in candidatos:
        if normalizar(cliente["nome"]) == alvo:
            return cliente
    # Prefeitura e fundo municipal do mesmo município são o mesmo comprador; hospital ou fundação, não.
    if PUBLICO_MUNICIPAL.search(alvo):
        for cliente in candidatos:
            municipio = normalizar(cliente.get("municipio", ""))
            if municipio and municipio in alvo and PUBLICO_MUNICIPAL.search(normalizar(cliente["nome"])):
                return cliente
    return None


def brl(valor: float) -> str:
    """Formato brasileiro: R$ 1.234,56."""
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data_br(iso: str | None) -> str:
    partes = (iso or "").split("-")
    return "/".join(reversed(partes)) if len(partes) == 3 else (iso or "—")


def analisar_orgao(orgao: str, uf: str | None = None, snapshot: dict | None = None) -> dict:
    base = snapshot if snapshot is not None else carregar_snapshot()
    cliente = _cliente(orgao, uf, base)
    if not cliente:
        return {"cliente_existente": False, "sinais": ["Sem histórico de venda neste órgão."], "prioridade": "normal"}
    sinais = [f"Já comprou {brl(cliente['total'])} em {cliente['notas']} notas; última em {_data_br(cliente.get('ultima_compra'))}."]
    prioridade = "alta"
    vencido = cliente.get("vencido", 0)
    if vencido > 0:
        prioridade = "atencao"
        sinais.append(f"Risco de recebimento: {brl(vencido)} vencidos. Considere antes de disputar.")
    return {"cliente_existente": True, "cliente": cliente, "sinais": sinais, "prioridade": prioridade}


def historico_produto(nome_produto: str, snapshot: dict | None = None) -> list[dict]:
    base = snapshot if snapshot is not None else carregar_snapshot()
    palavras = [p for p in normalizar(nome_produto).split() if len(p) > 2 and p not in {"just", "pholias"}]
    if not palavras:
        return []
    return [p for p in base.get("produtos", []) if all(w in normalizar(p["nome"]) for w in palavras)]
