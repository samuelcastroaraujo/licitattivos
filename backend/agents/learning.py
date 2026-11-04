"""
Aprendizado: decisões do analista viram conhecimento (tabela knowledge_items) que o Agente 4 consulta.

Tipos:
- feedback_historico: o analista corrigiu ou confirmou um item analisado.
- regra_fixa: regra criada à mão ("descritivo assim → produto X é/não é compatível"). Peso maior.
- dica_usuario: orientação em texto livre; aparece na análise, não mexe no score.

Busca por semelhança de palavras do descritivo (sem custo de IA). A coluna `embedding`
fica livre para busca semântica no futuro.
"""
import re
import unicodedata
from typing import Any

import structlog

from db.client import get_supabase_client

log = structlog.get_logger()

TIPOS = ("feedback_historico", "regra_fixa", "dica_usuario")
# Bloquear é seguro: basta parecer. Liberar exige descritivo quase igual.
SIMILARIDADE_BLOQUEIO = 0.55
SIMILARIDADE_LIBERACAO = 0.75
SIMILARIDADE_DICA = 0.45
PARADAS = {
    "com", "sem", "para", "por", "uma", "dos", "das", "nos", "nas", "que", "como", "ser", "sua", "seu",
    "pelo", "pela", "este", "esta", "item", "unidade", "embalagem", "deve", "devera", "conter", "contendo",
    "apresentar", "produto", "marca", "referencia", "similar", "equivalente", "ate", "mais", "menos",
}


def _tokens(texto: str) -> set[str]:
    limpo = unicodedata.normalize("NFD", texto or "")
    limpo = "".join(c for c in limpo if unicodedata.category(c) != "Mn").lower()
    return {t for t in re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", limpo) if (len(t) > 2 or t.isdigit()) and t not in PARADAS}


def similaridade(a: str, b: str) -> float:
    """Sobreposição de palavras (Jaccard). 1.0 = mesmas palavras."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def carregar_conhecimento(client=None) -> list[dict[str, Any]]:
    """Todo o conhecimento cabe na memória: centenas de linhas, lidas uma vez por análise."""
    client = client or get_supabase_client()
    try:
        return (
            client.table("knowledge_items")
            .select("id,tipo,produto_id,tipo_edital,conteudo,descritivo_original,resultado,score_final,peso,created_at")
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
            .data
            or []
        )
    except Exception as erro:
        # Sem aprendizado a análise continua, só mais conservadora.
        log.warning("aprendizado.carregar_falhou", error=str(erro))
        return []


def relevantes(descricao: str, conhecimento: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Conhecimento parecido com o descritivo, do mais parecido (e mais pesado) para o menos."""
    achados = []
    for kb in conhecimento:
        base = kb.get("descritivo_original") or ""
        if not base:
            continue
        sim = similaridade(descricao, base)
        if sim >= SIMILARIDADE_DICA:
            achados.append({**kb, "similaridade": round(sim, 3)})
    return sorted(achados, key=lambda k: (k["similaridade"] * float(k.get("peso") or 1.0)), reverse=True)


def registrar(
    *,
    tipo: str,
    conteudo: str,
    descritivo_original: str | None = None,
    produto_id: str | None = None,
    resultado: str | None = None,
    score_final: float | None = None,
    tipo_edital: str | None = None,
    peso: float | None = None,
    client=None,
) -> dict[str, Any]:
    if tipo not in TIPOS:
        raise ValueError(f"Tipo inválido: {tipo}.")
    if resultado not in (None, "compativel", "incompativel"):
        raise ValueError("Resultado deve ser 'compativel' ou 'incompativel'.")
    linha = {
        "tipo": tipo,
        "conteudo": conteudo.strip() or "(sem observação)",
        "descritivo_original": (descritivo_original or "").strip() or None,
        "produto_id": produto_id,
        "resultado": resultado,
        "score_final": score_final,
        "tipo_edital": tipo_edital,
        "peso": peso if peso is not None else (2.0 if tipo == "regra_fixa" else 1.0),
        "validado_por": "analista",
    }
    client = client or get_supabase_client()
    salvo = client.table("knowledge_items").insert(linha).execute().data[0]
    log.info("aprendizado.registrado", tipo=tipo, resultado=resultado, produto_id=produto_id)
    return salvo
