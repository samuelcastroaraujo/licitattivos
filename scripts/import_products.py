#!/usr/bin/env python
"""
scripts/import_products.py — Importa os .md de `banco de dados/` para a tabela
`products` do Supabase, com embedding do conteúdo completo para busca semântica
(pgvector) usada pelo Agente 4.

Cada arquivo .md é um dossiê técnico semi-estruturado (identificação, apresentações,
descrição, ingredientes, informações nutricionais, alergênicos, regulatório, preços).
O formato varia bastante entre arquivos (produtos das linhas Pholias e Venum têm
seções e nomenclatura ligeiramente diferentes), então o parser é best-effort:
extrai o que consegue com confiança e deixa `None`/vazio quando não há como ter
certeza — nunca inventa um valor (Regra de Ouro do CLAUDE.md).

Uso:
    uv run python scripts/import_products.py --dry-run          # só parseia e resume, não toca em nada
    uv run python scripts/import_products.py                    # upsert por slug (não apaga nada)
    uv run python scripts/import_products.py --wipe              # APAGA todos os produtos existentes antes de importar
    uv run python scripts/import_products.py --only just_whey    # roda para arquivos cujo slug contém o filtro
    uv run python scripts/import_products.py --no-embed          # pula a geração de embeddings (mais rápido para testar parsing)

Variáveis de ambiente exigidas (via .env na raiz do backend/ ou do repo):
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY   (necessária para upsert/delete — a anon key não passa pela RLS)
    OPENAI_API_KEY              (necessária para embeddings, a menos que --no-embed)
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_MD_DIR = REPO_ROOT / "banco de dados"
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))  # reaproveita os modelos Pydantic do backend

from dotenv import load_dotenv  # noqa: E402

# `config.Settings` resolve `.env` relativo ao diretório de trabalho atual; como este
# script pode ser chamado tanto da raiz do repo quanto de dentro de backend/, carrega
# explicitamente as duas localizações possíveis antes de qualquer import de `config`.
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(REPO_ROOT / ".env")

from models.product import Apresentacao, Ingrediente, Ingredientes, ProductCreate  # noqa: E402

EMBEDDING_MODEL = "text-embedding-3-small"  # 1536 dimensões — igual à coluna `embedding vector(1536)`
MAX_EMBEDDING_CHARS = 28000  # ~7k tokens, com folga sob o limite de 8191 tokens do modelo

# ── Utilidades de texto ──────────────────────────────────────────────────────

BOLD_RE = re.compile(r"\*\*(.*?)\*\*")
BULLET_FIELD_RE = re.compile(r"^\s*[-*]\s*\*\*([^:*]+):\*\*\s*(.+)$", re.MULTILINE)
SECTION_RE = re.compile(r"^##\s+(\d+)\.\s*(.*?)\s*$", re.MULTILINE)


def _strip_md(text: str) -> str:
    text = BOLD_RE.sub(r"\1", text)
    return text.strip(" \t*-••")


def _normalize_label(label: str) -> str:
    label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", label.lower())


def _to_float(raw: str) -> float | None:
    if not raw:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", raw)
    if not m:
        return None
    return float(m.group(0).replace(".", "").replace(",", ".")) if "," in m.group(0) else float(m.group(0))


def split_sections(text: str) -> dict[str, str]:
    """Divide o markdown em seções de nível `## N. Título`, indexadas pelo número."""
    matches = list(SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[m.group(1)] = text[start:end].strip()
    return sections


def parse_md_tables(body: str) -> list[list[dict[str, str]]]:
    """Extrai todas as tabelas markdown (`| a | b |`) de um trecho de texto."""
    lines = body.split("\n")
    tables: list[list[dict[str, str]]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        is_header = line.strip().startswith("|")
        is_separator = i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1] or "")
        if is_header and is_separator:
            headers = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows: list[dict[str, str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if len(cells) == len(headers):
                    rows.append(dict(zip(headers, cells)))
                i += 1
            tables.append(rows)
        else:
            i += 1
    return tables


def _find_col(headers: list[str], *keywords: str) -> str | None:
    for h in headers:
        norm = _normalize_label(h)
        if any(kw in norm for kw in keywords):
            return h
    return None


# ── Classificação heurística de ingredientes ────────────────────────────────

_CATEGORIA_KEYWORDS: list[tuple[str, str]] = [
    ("proteina", "proteina"),
    ("whey", "proteina"),
    ("caseina", "proteina"),
    ("colageno", "proteina"),
    ("arginina", "aminoacido"),
    ("glutamina", "aminoacido"),
    ("creatina", "aminoacido"),
    ("bcaa", "aminoacido"),
    ("aminoacido", "aminoacido"),
    ("maltodextrina", "carboidrato"),
    ("dextrose", "carboidrato"),
    ("frutose", "carboidrato"),
    ("goma guar", "fibra"),
    ("fibra", "fibra"),
    ("inulina", "fibra"),
    ("psyllium", "fibra"),
    ("oleo", "lipideo"),
    ("lecitina", "lipideo"),
    ("triglic", "lipideo"),
    ("gordura", "lipideo"),
    ("vitamina", "vitamina"),
    ("cobalamina", "vitamina"),
    ("acido folico", "vitamina"),
    ("calcio", "mineral"),
    ("potassio", "mineral"),
    ("sodio", "mineral"),
    ("ferro", "mineral"),
    ("magnesio", "mineral"),
    ("zinco", "mineral"),
    ("cloreto de potassio", "mineral"),
    ("enzima", "enzima"),
    ("estevia", "edulcorante"),
    ("esteviol", "edulcorante"),
    ("taumatina", "edulcorante"),
    ("sucralose", "edulcorante"),
    ("edulcorante", "edulcorante"),
    ("espessante", "espessante"),
    ("gelificante", "espessante"),
    ("aroma", "flavorizante"),
    ("flavorizante", "flavorizante"),
    ("dioxido de silicio", "antiumectante"),
    ("antiumectante", "antiumectante"),
]

_ALERGENO_KEYWORDS = ("leite", "soja", "ovo", "trigo", "gluten", "crustaceo", "amendoim", "castanha", "peixe")


def _classify_categoria(nome_normalizado: str) -> str:
    for kw, categoria in _CATEGORIA_KEYWORDS:
        if kw in nome_normalizado:
            return categoria
    return "outros"


def _is_alergeno(nome_normalizado: str) -> bool:
    return any(kw in nome_normalizado for kw in _ALERGENO_KEYWORDS)


# ── Parsing por seção ────────────────────────────────────────────────────────


def parse_identificacao(body: str) -> dict[str, str]:
    campos: dict[str, str] = {}
    for label, value in BULLET_FIELD_RE.findall(body):
        campos[_normalize_label(label)] = _strip_md(value)
    return campos


def parse_apresentacoes(body: str) -> list[Apresentacao]:
    apresentacoes: list[Apresentacao] = []
    for table in parse_md_tables(body):
        if not table:
            continue
        headers = list(table[0].keys())
        col_variante = _find_col(headers, "variante", "sabor")
        col_peso = _find_col(headers, "peso", "gramatura", "formato")
        col_embalagem = _find_col(headers, "embalagem")
        col_rendimento = _find_col(headers, "rendimento")
        col_obs = _find_col(headers, "observa", "ean")

        if col_peso or col_variante:
            # Tabela "larga" com uma linha por variante comercial.
            for row in table:
                peso = row.get(col_peso, "") if col_peso else ""
                variante = row.get(col_variante, "") if col_variante else ""
                gramatura = " — ".join(p for p in (variante, peso) if p) or peso or variante
                if not gramatura:
                    continue
                obs = row.get(col_obs, "") if col_obs else ""
                ean_match = re.search(r"EAN:\s*([\w./-]+(?:\s[\w./-]+)*)", obs)
                ean = ean_match.group(1).strip() if ean_match else None
                if ean and ean.lower().startswith("sem"):
                    ean = None
                apresentacoes.append(Apresentacao(
                    gramatura=gramatura,
                    embalagem=row.get(col_embalagem, "") if col_embalagem else "",
                    ean=ean,
                    rendimento=(row.get(col_rendimento) or None) if col_rendimento else None,
                ))
            continue

        # Tabela chave-valor "Parâmetro | Detalhes" (formato usado por vários dossiês).
        col_param = _find_col(headers, "parametro", "campo", "item")
        col_valor = _find_col(headers, "detalhe", "valor", "descricao")
        if not (col_param and col_valor):
            continue
        kv = {_normalize_label(row[col_param]): row[col_valor] for row in table if row.get(col_param)}
        formato_key = next((k for k in kv if "apresenta" in k or "formato" in k), None)
        if not formato_key:
            continue
        raw = _strip_md(kv[formato_key])
        ean_key = next((k for k in kv if "ean" in k or "codigodebarras" in k), None)
        ean_val = None
        if ean_key:
            ean_raw = _strip_md(kv[ean_key])
            if ean_raw and "n/a" not in ean_raw.lower() and "sem ean" not in ean_raw.lower():
                ean_val = ean_raw
        rendimento_key = next((k for k in kv if "rendimento" in k or "doses" in k), None)
        embalagem_match = re.search(
            r"(pote|frasco|sach[eê]|bl[íi]ster|bisnaga|tubo|caixa|display)[^-]*", raw, re.IGNORECASE
        )
        apresentacoes.append(Apresentacao(
            gramatura=raw,
            embalagem=embalagem_match.group(0).strip() if embalagem_match else "",
            ean=ean_val,
            rendimento=_strip_md(kv[rendimento_key]) if rendimento_key else None,
        ))
    return apresentacoes


def parse_descricao_e_indicacoes(body: str) -> tuple[str, list[str]]:
    marker = re.search(r"\*\*Aplica[çc][õo]es e Indica[çc][õo]es:?\*\*", body)
    if marker:
        descricao_raw = body[: marker.start()]
        resto = body[marker.end():]
    else:
        descricao_raw = body
        resto = ""

    class_marker = re.search(r"\*\*Classifica[çc][ãa]o Nutricional", descricao_raw)
    if class_marker:
        descricao_raw = descricao_raw[: class_marker.start()]

    descricao = "\n".join(
        line.strip() for line in descricao_raw.split("\n") if line.strip()
    ).strip()

    indicacoes = []
    for line in resto.split("\n"):
        line = line.strip()
        if line.startswith(("•", "-", "*")):
            item = _strip_md(line.lstrip("•-* \t"))
            if item:
                indicacoes.append(item)
        elif line and not line.startswith("#"):
            break  # fim da lista de indicações

    return descricao, indicacoes


def parse_ingredientes(body: str) -> Ingredientes:
    lista: list[Ingrediente] = []
    seen: set[str] = set()
    for table in parse_md_tables(body):
        if not table:
            continue
        headers = list(table[0].keys())
        col_nome = _find_col(headers, "ingrediente")
        col_funcao = _find_col(headers, "funcao", "fisiologica")
        if not col_nome:
            continue
        for row in table:
            nome_raw = row.get(col_nome, "")
            nome = _strip_md(nome_raw)
            if not nome:
                continue
            nome_normalizado = " ".join(nome.lower().split())
            if nome_normalizado in seen:
                continue
            seen.add(nome_normalizado)
            funcao = _strip_md(row.get(col_funcao, "")) if col_funcao else ""
            lista.append(Ingrediente(
                nome=nome,
                nome_normalizado=nome_normalizado,
                funcao=funcao,
                categoria=_classify_categoria(nome_normalizado),
                e_alergeno=_is_alergeno(nome_normalizado),
                quantidade_por_porcao_g=None,  # não declarado por ingrediente nestes dossiês
            ))

    nota_pureza = ""
    quote_match = re.search(r"^>\s*(.+)$", body, re.MULTILINE)
    if quote_match:
        nota_pureza = _strip_md(quote_match.group(1))

    return Ingredientes(lista=lista, nota_pureza=nota_pureza)


NUTRIENTE_SCALAR_MAP: list[tuple[str, str]] = [
    (r"valor energ", "kcal_por_porcao"),
    (r"prote[íi]nas?\b", "proteinas_por_porcao_g"),
    (r"carboidratos?\b", "carboidratos_por_porcao_g"),
    (r"gorduras? totais?", "gorduras_por_porcao_g"),
    (r"fibras? aliment", "fibras_por_porcao_g"),
    (r"s[óo]dio", "sodio_por_porcao_mg"),
]


def parse_nutricao(body: str) -> tuple[dict[str, Any], dict[str, Any], float | None, dict[str, float | None]]:
    """
    Retorna (nutricao_por_porcao, nutricao_por_100g, porcao_g, escalares).
    Os dicts JSONB guardam a tabela completa tal como está no documento (fiel à fonte).
    Os campos escalares só são preenchidos quando há uma única coluna de "quantidade
    por porção" inequívoca — evita atribuir o valor errado em tabelas multi-coluna
    (ex.: produtos com doses diferentes por consistência/sabor).
    """
    tables = parse_md_tables(body)
    nutricao_por_porcao: dict[str, Any] = {}
    nutricao_por_100g: dict[str, Any] = {}
    escalares: dict[str, float | None] = {k: None for _, k in NUTRIENTE_SCALAR_MAP}

    porcao_g = None
    porcao_match = re.search(r"Por[çc][ãa]o:?\*{0,2}\s*([\d.,]+)\s*g", body, re.IGNORECASE)
    if porcao_match:
        porcao_g = _to_float(porcao_match.group(1))

    for table in tables:
        if not table:
            continue
        headers = list(table[0].keys())
        col_nutriente = headers[0]
        col_100g = _find_col(headers, "100g", "100ml")
        col_porcao = _find_col(headers, "porcao", "porção".lower())
        if col_porcao is None:
            # fallback: única coluna de valor além do nutriente (tabela simples de 2-3 colunas)
            candidatas = [h for h in headers[1:] if h != col_100g]
            col_porcao = candidatas[0] if len(candidatas) == 1 else None

        for row in table:
            nome_nutriente = row.get(col_nutriente, "")
            if not nome_nutriente:
                continue
            nome_limpo = _strip_md(nome_nutriente)
            valores_extra = {h: row[h] for h in headers[1:] if h not in (col_porcao, col_100g)}
            if col_porcao and not valores_extra:
                nutricao_por_porcao[nome_limpo] = row.get(col_porcao)
            else:
                # Mais de uma coluna de valor (ex.: doses/consistências diferentes) —
                # guarda a linha completa tal como está na fonte, sem escolher uma coluna arbitrária.
                bag = dict(valores_extra)
                if col_porcao:
                    bag[col_porcao] = row.get(col_porcao)
                nutricao_por_porcao[nome_limpo] = bag
            if col_100g:
                nutricao_por_100g[nome_limpo] = row.get(col_100g)

            if col_porcao and not valores_extra and porcao_g is not None:
                nome_norm = _strip_md(nome_nutriente).lower()
                for pattern, campo in NUTRIENTE_SCALAR_MAP:
                    if re.search(pattern, nome_norm) and escalares[campo] is None:
                        escalares[campo] = _to_float(row.get(col_porcao, ""))

    return nutricao_por_porcao, nutricao_por_100g, porcao_g, escalares


def parse_alergenicos(body: str) -> dict[str, Any]:
    def extract(verb_pattern: str) -> list[str]:
        results: list[str] = []
        for m in re.finditer(
            verb_pattern + r"\s+([A-ZÇÃÕÁÉÍÓÚÂÊÔ][A-ZÇÃÕÁÉÍÓÚÂÊÔ\s,]*?)(?:\.|,\s*de acordo|;)", body
        ):
            for part in re.split(r",| E ", m.group(1)):
                part = part.strip(" .")
                if part and part not in results:
                    results.append(part)
        return results

    return {
        "alergenicos_contem": extract(r"(?<!N[ÃA]O )CONT[ÉE]M"),
        "alergenicos_pode_conter": extract(r"PODE CONTER"),
        "sem_gluten": bool(re.search(r"N[ÃA]O CONT[ÉE]M GL[ÚU]TEN", body, re.IGNORECASE)),
        "sem_lactose": bool(re.search(r"N[ÃA]O CONT[ÉE]M LACTOSE", body, re.IGNORECASE)),
        "sem_sacarose": bool(re.search(r"(N[ÃA]O CONT[ÉE]M|ISENTO DE|SEM)\s+SACAROSE", body, re.IGNORECASE)),
    }


def parse_normas_regulatorias(full_text: str) -> list[str]:
    normas = []
    for m in re.finditer(r"(RDC|IN|Lei)\s*n?[º°o]?\s*[\d]+(?:\.[\d]+)*\s*/\s*\d{2,4}", full_text):
        norm = re.sub(r"\s+", " ", m.group(0)).strip()
        if norm not in normas:
            normas.append(norm)
    return normas


def parse_diferenciais(body: str) -> list[str]:
    itens = []
    for m in re.finditer(r"^\s*\d+\.\s*(.+)$", body, re.MULTILINE):
        itens.append(_strip_md(m.group(1)))
    return itens


def determine_via_enteral(identificacao: dict[str, str]) -> bool:
    """
    Só considera `via_enteral=True` quando a própria Categoria do produto (Seção 1)
    declara explicitamente uso para nutrição enteral — a frase padrão da Seção 8
    ("Via Oral e Via Enteral quando aplicável") se repete em quase todos os
    dossiês e não é um sinal confiável por produto.
    """
    categoria = identificacao.get("categoria", "") or identificacao.get("categoriaclassificacao", "")
    return "enteral" in categoria.lower()


def determine_registro_ms(registro_texto: str) -> bool:
    """
    Conservador por padrão: só marca True com um número de registro MS explícito.
    "Notificado"/"Dispensado" (o padrão da maioria destes dossiês) resulta em False —
    coerente com a distinção do CLAUDE.md entre produtos com Registro MS e produtos
    dispensados de registro pela RDC 240/2018.
    """
    if not registro_texto:
        return False
    if re.search(r"dispensad", registro_texto, re.IGNORECASE):
        return False
    return bool(re.search(r"registro\s*(?:sanit[áa]rio\s*)?(?:no\s*)?MS\s*n?[º°o]?\s*[\d.\-]+", registro_texto, re.IGNORECASE))


# ── Produto completo ─────────────────────────────────────────────────────────


@dataclass
class ParsedProduct:
    slug: str
    product: ProductCreate
    full_text: str
    warnings: list[str] = field(default_factory=list)


def parse_product_file(path: Path) -> ParsedProduct:
    text = path.read_text(encoding="utf-8")
    slug = path.stem
    warnings: list[str] = []

    title_match = re.search(r"^#\s+(.+?)\s*\.?\s*$", text, re.MULTILINE)
    nome_comercial = title_match.group(1).strip() if title_match else slug.replace("_", " ").title()
    if not title_match:
        warnings.append("Título (H1) não encontrado — usando slug como nome comercial.")

    sections = split_sections(text)

    identificacao = parse_identificacao(sections.get("1", ""))
    fabricante = identificacao.get("fabricante") or "Attivos Magisttrais Indústria e Comércio Ltda."
    marca = identificacao.get("marca") or "Pholias"
    linha_clinica = identificacao.get("linha")
    categoria = identificacao.get("categoria") or identificacao.get("categoriaclassificacao")
    ncm = identificacao.get("classificacaofiscalncm") or identificacao.get("ncm") or identificacao.get("codigofiscalncm")
    registro_texto = identificacao.get("registromapaanvisa") or identificacao.get("registroanvisa")

    if "2" not in sections:
        warnings.append("Seção 2 (Apresentações) não encontrada.")
    apresentacoes = parse_apresentacoes(sections.get("2", ""))
    if not apresentacoes:
        warnings.append("Nenhuma apresentação comercial extraída.")

    if "3" not in sections:
        warnings.append("Seção 3 (Descrição) não encontrada.")
    descricao, indicacoes = parse_descricao_e_indicacoes(sections.get("3", ""))

    if "4" not in sections:
        warnings.append("Seção 4 (Ingredientes) não encontrada.")
    ingredientes = parse_ingredientes(sections.get("4", ""))
    if not ingredientes.lista:
        warnings.append("Nenhum ingrediente extraído — verificar manualmente.")

    nutricao_porcao, nutricao_100g, porcao_g, escalares = parse_nutricao(sections.get("5", ""))
    if not nutricao_porcao:
        warnings.append("Tabela nutricional não extraída.")

    alergenicos = parse_alergenicos(sections.get("6", ""))
    normas_regulatorias = parse_normas_regulatorias(text)
    diferenciais_tecnicos = parse_diferenciais(sections.get("11", ""))

    via_enteral = determine_via_enteral(identificacao)
    tem_registro_ms = determine_registro_ms(registro_texto or "")

    product = ProductCreate(
        slug=slug,
        nome_comercial=nome_comercial,
        fabricante=fabricante,
        marca=marca,
        linha_clinica=linha_clinica,
        categoria=categoria,
        ncm=ncm,
        registro_anvisa=registro_texto,
        tem_registro_ms=tem_registro_ms,
        apresentacoes=apresentacoes,
        descricao=descricao or None,
        indicacoes=indicacoes,
        ingredientes=ingredientes,
        alergenicos_contem=alergenicos["alergenicos_contem"],
        alergenicos_pode_conter=alergenicos["alergenicos_pode_conter"],
        sem_gluten=alergenicos["sem_gluten"],
        sem_lactose=alergenicos["sem_lactose"],
        sem_sacarose=alergenicos["sem_sacarose"],
        nutricao_por_porcao=nutricao_porcao,
        nutricao_por_100g=nutricao_100g,
        porcao_g=porcao_g,
        kcal_por_porcao=escalares["kcal_por_porcao"],
        proteinas_por_porcao_g=escalares["proteinas_por_porcao_g"],
        carboidratos_por_porcao_g=escalares["carboidratos_por_porcao_g"],
        gorduras_por_porcao_g=escalares["gorduras_por_porcao_g"],
        fibras_por_porcao_g=escalares["fibras_por_porcao_g"],
        sodio_por_porcao_mg=escalares["sodio_por_porcao_mg"],
        via_enteral=via_enteral,
        normas_regulatorias=normas_regulatorias,
        diferenciais_tecnicos=diferenciais_tecnicos,
    )

    if not tem_registro_ms and not (registro_texto and re.search(r"dispensad", registro_texto, re.IGNORECASE)):
        warnings.append(
            "tem_registro_ms=False por padrão conservador — texto de registro não bateu com "
            "nenhum padrão reconhecido; revisar manualmente: "
            f"{registro_texto!r}"
        )

    return ParsedProduct(slug=slug, product=product, full_text=text, warnings=warnings)


# ── Embeddings e persistência ───────────────────────────────────────────────


def compute_embeddings(texts: list[str]) -> list[list[float]]:
    from langchain_openai import OpenAIEmbeddings

    embedder = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    truncated = [t[:MAX_EMBEDDING_CHARS] for t in texts]
    return embedder.embed_documents(truncated)


def get_admin_client():
    from config import settings
    from supabase import create_client

    key = settings.supabase_service_role_key or settings.supabase_key
    if not settings.supabase_service_role_key:
        print(
            "AVISO: SUPABASE_SERVICE_ROLE_KEY não definido — usando SUPABASE_KEY. "
            "Se for a chave anônima, o upsert pode falhar por causa do RLS.",
            file=sys.stderr,
        )
    return create_client(settings.supabase_url, key)


def wipe_products(client) -> int:
    existing = client.table("products").select("id").execute().data or []
    if not existing:
        return 0
    client.table("products").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    return len(existing)


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Só parseia e resume — não chama OpenAI nem Supabase.")
    parser.add_argument("--wipe", action="store_true", help="APAGA todos os produtos existentes antes de importar.")
    parser.add_argument("--only", default=None, help="Só processa arquivos cujo slug contém este texto.")
    parser.add_argument("--no-embed", action="store_true", help="Pula a geração de embeddings.")
    parser.add_argument("--limit", type=int, default=None, help="Limita a N arquivos (para testes).")
    args = parser.parse_args()

    if not PRODUCTS_MD_DIR.is_dir():
        print(f"ERRO: diretório não encontrado: {PRODUCTS_MD_DIR}", file=sys.stderr)
        sys.exit(1)

    files = sorted(PRODUCTS_MD_DIR.glob("*.md"))
    if args.only:
        files = [f for f in files if args.only.lower() in f.stem.lower()]
    if args.limit:
        files = files[: args.limit]

    if not files:
        print("Nenhum arquivo .md encontrado para processar.")
        return

    print(f"Encontrados {len(files)} arquivos .md em '{PRODUCTS_MD_DIR}'.\n")

    parsed: list[ParsedProduct] = []
    for path in files:
        try:
            parsed.append(parse_product_file(path))
        except Exception as e:
            print(f"  [ERRO] {path.name}: falha ao parsear — {e}", file=sys.stderr)

    total_warnings = sum(len(p.warnings) for p in parsed)
    print(f"Parseados com sucesso: {len(parsed)}/{len(files)}  |  avisos: {total_warnings}\n")
    for p in parsed:
        if p.warnings:
            print(f"  {p.slug}:")
            for w in p.warnings:
                print(f"    - {w}")

    slugs = [p.slug for p in parsed]
    duplicated = {s for s in slugs if slugs.count(s) > 1}
    if duplicated:
        print(f"\nAVISO: slugs duplicados entre arquivos (sobrescrevem uns aos outros): {duplicated}")

    if args.dry_run:
        print("\n--dry-run: nada foi enviado ao Supabase nem à OpenAI.")
        return

    embeddings: list[list[float] | None] = [None] * len(parsed)
    if not args.no_embed:
        print(f"\nGerando embeddings ({EMBEDDING_MODEL}) para {len(parsed)} produtos...")
        embeddings = compute_embeddings([p.full_text for p in parsed])
    else:
        print("\n--no-embed: coluna `embedding` ficará NULL para os produtos importados.")

    client = get_admin_client()

    if args.wipe:
        print("\n--wipe: apagando todos os produtos existentes em `products`...")
        removed = wipe_products(client)
        print(f"  {removed} produto(s) removido(s).")

    print(f"\nEnviando {len(parsed)} produtos ao Supabase (upsert por slug)...")
    payload = []
    for p, emb in zip(parsed, embeddings):
        data = p.product.model_dump(mode="json")
        if emb is not None:
            data["embedding"] = emb
        payload.append(data)

    BATCH_SIZE = 25
    sent = 0
    for i in range(0, len(payload), BATCH_SIZE):
        batch = payload[i:i + BATCH_SIZE]
        client.table("products").upsert(batch, on_conflict="slug").execute()
        sent += len(batch)
        print(f"  {sent}/{len(payload)} enviados...")

    print(f"\nConcluído: {sent} produtos importados/atualizados em `products`.")


if __name__ == "__main__":
    main()
