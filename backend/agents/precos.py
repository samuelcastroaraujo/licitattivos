"""
Preço mínimo de cotação: tabela de preços com desconto (por apresentação/SKU) → preço de cada item do edital.

Regras (planilha padrão de licitação):
- Edital pede embalagem que existe na tabela → preço daquele SKU.
- Edital pede em gramas (unidade g) → preço por grama do SKU mais barato por grama.
- Edital pede embalagem que não existe → proporcional ao menor preço por grama (sinalizado).
- Sem embalagem identificável → SKU mais barato por grama, sinalizado para conferência.
Nada é inventado: produto sem SKU com preço na tabela fica sem preço.

A tabela fica em knowledge_snapshot (key "tabela_precos"), importada do .md exportado da planilha.
"""
import math
import re
import unicodedata
from typing import Any

import structlog

from db.client import get_supabase_client

log = structlog.get_logger()
CHAVE = "tabela_precos"

# slug do banco → apresentações da tabela (regex no nome normalizado do SKU). Explícito de propósito:
# preço errado em proposta é pior que preço em branco.
MAPA: dict[str, str] = {
    "pholias_just_whey_protein_isolado": r"^JUST WHEY ISOLADO\b",
    "pholias_just_whey_protein_concentrado": r"^JUST (WHEY CONCENTRADO|W CONCENT)\b(?!.*LACTOSE)",
    "pholias_just_whey_protein_hidrolisado": r"^JUST W PROT HIDROLIS",
    "pholias_whey_hi": r"^JUST WHEY HI\b",
    "pholias_just_glutamina": r"^JUST GLUTAMINA\b",
    "pholias_just_arginina": r"^JUST ARGININA\b",
    "pholias_just_maltodextrina": r"^JUST MALTODEXTRINA\b",
    "pholias_just_creatina": r"^JUST CREATINA\b",
    "pholias_just_fibra_soluvel": r"^JUST FIBRAS\b",
    "pholias_just_xilitol": r"^JUST XILITOL\b",
    "pholias_bella_fiber": r"BELLA FIBER",
    "pholias_liqthick": r"LIQTHICK",
    "pholias_veetal_active": r"VEETAL ACTIVE",
    "pholias_veetal_fiber": r"VEETAL FIBER",
    "pholias_veetal_glicontrol": r"GLICONTROL",
    "pholias_veetal_infant": r"VEETAL INFANT",
    "pholias_just_veetal_senior_50_baunilha": r"VEETAL SENIOR 50\+ +BAUNILHA",
    "pholias_just_veetal_senior_50_sem_sabor": r"VEETAL SENIOR 50\+ +SEM SABOR",
    "pholias_sorend_sem_sabor": r"^SOREND (LATA )?SEM SABOR",
    "pholias_sorend_baunilha": r"^SOREND SACHE BAUNILHA",
    "pholias_sorend_kids_baunilha": r"^SOREND KIDS BAUNILHA",
    "pholias_sorend_kids_morango": r"^SOREND KIDS MORANGO",
    "pholias_sorend_kids_sem_sabor": r"^SOREND KIDS SEM SABOR",
    "pholias_veetal_whey_bari_sem_sabor": r"VEETALWHEY BARI NEUTRO",
    "pholias_veetal_whey_bari_baunilha": r"VEETALWHEY BARI BAUNILHA",
    "pholias_veetal_whey_bari_chocolate_belga": r"VEETALWHEY BARI CHOCOLATE",
    "pholias_ai_strong_whey_doce_de_leite": r"AISTRONG WHEY",
    "pholias_kolatrix_total_abacaxi_com_hortela": r"KOLATRIX TOTAL ABACAXI",
    "pholias_kolatrix_total_baunilha": r"KOLATRIX TOTAL BAUNILHA",
    "pholias_kolatrix_total_limonada": r"KOLATRIX TOTAL LIMONADA",
    "pholias_kolatrix_total_sem_sabor": r"KOLATRIX TOTAL SEM SABOR",
    "pholias_kolatrix_total_tangerina": r"KOLATRIX TOTAL TANGERINA",
    "pholias_kolatrix_total_uva": r"KOLATRIX TOTAL UVA",
    "pholias_kolatrix_hyaluronic_abacaxi_com_hortela": r"KOLATRIX HYALURONIC ABACAXI",
    "pholias_kolatrix_hyaluronic_uva": r"KOLATRIX HYALURONIC UVA",
    "pholias_supreme_coffee": r"SUPREME COFF",
    "pholias_nati_negra": r"NATI NEGRA",
    "pholias_nati_morusil_k": r"MORUSILK",
    "pholias_omega_3": r"^OMEGA 3 OLEO PEIXE",
    "pholias_vitamina_d_gotas": r"VITAMINA D",
    "pholias_krilla": r"^KRILLA 500",
    "pholias_krilla_mega_3": r"^KRILLA MEGA",
    "pholias_4mag": r"4MAG",
    "pholias_immunoblend": r"IMMUNOBLEND",
    "pholias_tri_melatonina": r"TRI MELATONINA",
    "pholias_coq10": r"COEZIMA Q10",
}
UNIDADES_GRAMA = {"G", "GR", "GRS", "GRAMA", "GRAMAS"}
EMBALAGEM = r"(?:embalage[mn]s?|lata|pote|sache|sach[eê]s?|frasco|envelope|refil|pacote|apresenta[cç][aã]o|unidade|contendo|com)"


def normalizar(texto: str) -> str:
    limpo = unicodedata.normalize("NFD", texto or "")
    limpo = "".join(c for c in limpo if unicodedata.category(c) != "Mn").upper()
    limpo = re.sub(r"\bS/\s*SABOR", "SEM SABOR", limpo)
    return re.sub(r"\s+", " ", limpo).strip()


def _numero(texto: str) -> float:
    """'1.000' → 1000; '6,7' → 6.7."""
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", texto):
        return float(texto.replace(".", ""))
    return float(texto.replace(",", "."))


def gramas_do_sku(nome: str) -> float | None:
    """Peso total da apresentação. Caixa com N sachês soma tudo."""
    alvo = normalizar(nome)
    peso = re.search(r"(\d{1,3}(?:\.\d{3})+|\d+(?:,\d+)?)\s*(KG|G)\b", alvo)
    if not peso:
        return None
    gramas = _numero(peso.group(1)) * (1000 if peso.group(2) == "KG" else 1)
    caixa = re.search(r"CX\s*(?:C/\s*)?(\d+)\s*UN", alvo)
    return gramas * int(caixa.group(1)) if caixa else gramas


def ler_tabela_md(texto: str) -> list[dict[str, Any]]:
    """Linhas '| Código | Produto | R$ 12,34 |' do .md exportado da planilha; 'Não informado' fica sem preço."""
    linhas = []
    linha_atual = ""
    for bruta in texto.splitlines():
        cabecalho = re.match(r"^##\s+(.+?)\s*(\(|$)", bruta)
        if cabecalho:
            linha_atual = cabecalho.group(1).strip()
            continue
        partes = [p.strip() for p in bruta.strip().strip("|").split("|")]
        if len(partes) != 3 or partes[0] in ("Código", "---") or set(partes[0]) <= {"-"}:
            continue
        codigo, produto, valor = partes
        preco = re.search(r"R\$\s*([\d.]+,\d{2})", valor)
        linhas.append({
            "codigo": codigo,
            "produto": produto,
            "linha": linha_atual,
            "preco": float(preco.group(1).replace(".", "").replace(",", ".")) if preco else None,
            "gramas": gramas_do_sku(produto),
        })
    return linhas


def salvar_tabela(itens: list[dict], fonte: str) -> dict:
    dados = {"fonte": fonte, "itens": itens, "total": len(itens), "sem_preco": sum(1 for i in itens if i["preco"] is None)}
    get_supabase_client().table("knowledge_snapshot").upsert({"key": CHAVE, "data": dados}).execute()
    log.info("precos.tabela_importada", fonte=fonte, total=len(itens))
    return dados


def carregar_tabela(client=None) -> dict:
    client = client or get_supabase_client()
    try:
        linhas = client.table("knowledge_snapshot").select("data,updated_at").eq("key", CHAVE).limit(1).execute().data
    except Exception as erro:
        log.warning("precos.tabela_indisponivel", error=str(erro))
        return {"itens": []}
    if not linhas:
        return {"itens": []}
    return {**linhas[0]["data"], "atualizado_em": linhas[0].get("updated_at")}


def skus_do_produto(slug: str, tabela: list[dict]) -> list[dict]:
    padrao = MAPA.get(slug)
    if not padrao:
        return []
    return [s for s in tabela if s.get("preco") and re.search(padrao, normalizar(s["produto"]))]


def _embalagens_pedidas(descricao: str) -> list[float]:
    """Pesos de embalagem citados no item ('lata 400 g', 'embalagem 250g'); ignora '20 g de proteína'."""
    texto = normalizar(descricao).lower()
    pedidas = []
    for achado in re.finditer(rf"{EMBALAGEM}[^0-9.;]{{0,25}}?(\d{{1,3}}(?:\.\d{{3}})+|\d+(?:,\d+)?)\s*(kg|g)\b", texto):
        pedidas.append(_numero(achado.group(1)) * (1000 if achado.group(2) == "kg" else 1))
    if not pedidas:
        # "...Embalagem: 250g" com a palavra depois do número também vale.
        for achado in re.finditer(r"(\d{1,3}(?:\.\d{3})+|\d+(?:,\d+)?)\s*(kg|g)\b(?!\s*(de|da|do|por)\b)", texto):
            depois = texto[achado.end(): achado.end() + 25]
            if re.search(r"(embalagem|lata|pote|sache|frasco)", depois):
                pedidas.append(_numero(achado.group(1)) * (1000 if achado.group(2) == "kg" else 1))
    return pedidas


def preco_do_item(slug: str, descricao: str, unidade: str | None, tabela: list[dict]) -> dict | None:
    """Preço unitário mínimo para o item, com o SKU e o critério usados. None = produto sem preço."""
    skus = [s for s in skus_do_produto(slug, tabela) if s.get("gramas")]
    if not skus:
        com_preco = skus_do_produto(slug, tabela)
        if len(com_preco) == 1:
            sku = com_preco[0]
            return {"preco_unitario": sku["preco"], "sku": sku["produto"], "codigo": sku["codigo"], "criterio": "único SKU do produto"}
        return None
    mais_barato = min(skus, key=lambda s: s["preco"] / s["gramas"])
    por_grama = mais_barato["preco"] / mais_barato["gramas"]
    if normalizar(unidade or "") in UNIDADES_GRAMA:
        return {"preco_unitario": round(por_grama, 4), "sku": mais_barato["produto"], "codigo": mais_barato["codigo"],
                "criterio": "preço por grama (item pedido em gramas)", "por_grama": round(por_grama, 4)}
    pedidas = _embalagens_pedidas(descricao)
    for gramas in pedidas:
        exatos = [s for s in skus if abs(s["gramas"] - gramas) < 0.5]
        if exatos:
            sku = min(exatos, key=lambda s: s["preco"])
            return {"preco_unitario": sku["preco"], "sku": sku["produto"], "codigo": sku["codigo"],
                    "criterio": f"embalagem de {gramas:g} g pedida no edital", "por_grama": round(sku["preco"] / sku["gramas"], 4)}
    if pedidas:
        gramas = pedidas[0]
        return {"preco_unitario": math.ceil(por_grama * gramas * 100) / 100, "sku": mais_barato["produto"], "codigo": mais_barato["codigo"],
                "criterio": f"proporcional: embalagem de {gramas:g} g não existe na tabela; usado o preço por grama do SKU mais barato",
                "por_grama": round(por_grama, 4), "conferir": True}
    return {"preco_unitario": mais_barato["preco"], "sku": mais_barato["produto"], "codigo": mais_barato["codigo"],
            "criterio": "embalagem não identificada no edital; usado o SKU mais barato por grama", "por_grama": round(por_grama, 4), "conferir": True}


def precificar(itens: list[dict], produtos: dict[str, dict], tabela: list[dict]) -> dict:
    """
    itens: licit_items (com produto_id, quantidade em requisitos). produtos: id → {slug, nome_comercial}.
    Devolve preço por item e o valor total de cada produto (quantidade × preço mínimo).
    """
    por_item: dict[str, dict] = {}
    por_produto: dict[str, dict] = {}
    for item in itens:
        produto = produtos.get(item.get("produto_id") or "")
        if not produto:
            continue
        requisitos = item.get("requisitos") or {}
        preco = preco_do_item(produto["slug"], item.get("descricao_original") or "", requisitos.get("unidade_solicitada"), tabela)
        quantidade = requisitos.get("quantidade_pregao") or 0
        if not preco:
            por_item[item["id"]] = {"sem_preco": True, "motivo": "Produto sem preço na tabela de descontos."}
            continue
        total = round(preco["preco_unitario"] * quantidade, 2) if quantidade else None
        por_item[item["id"]] = {**preco, "quantidade": quantidade, "total": total}
        grupo = por_produto.setdefault(produto["nome_comercial"], {"produto": produto["nome_comercial"], "itens": [], "quantidade": 0, "total": 0.0, "itens_100": 0})
        grupo["itens"].append(item["numero_item"])
        grupo["quantidade"] += quantidade
        grupo["total"] = round(grupo["total"] + (total or 0), 2)
        if (item.get("score_compatibilidade") or 0) >= 0.999:
            grupo["itens_100"] += 1
    produtos_ordenados = sorted(por_produto.values(), key=lambda g: g["total"], reverse=True)
    return {
        "por_item": por_item,
        "por_produto": produtos_ordenados,
        "total": round(sum(g["total"] for g in produtos_ordenados), 2),
        "total_100": round(sum(por_item[i["id"]].get("total") or 0 for i in itens
                               if i["id"] in por_item and (i.get("score_compatibilidade") or 0) >= 0.999), 2),
    }


def precificar_edital(client, edital_id: str) -> dict:
    """Recalcula com a tabela atual. Só itens compatíveis (com produto sugerido) entram."""
    itens = client.table("licit_items").select("id,numero_item,descricao_original,produto_id,requisitos,score_compatibilidade") \
        .eq("edital_id", edital_id).execute().data or []
    ids = list({i["produto_id"] for i in itens if i.get("produto_id")})
    produtos = {}
    if ids:
        produtos = {p["id"]: p for p in client.table("products").select("id,slug,nome_comercial").in_("id", ids).execute().data}
    tabela = carregar_tabela(client)
    resultado = precificar(itens, produtos, tabela.get("itens") or [])
    resultado["tabela"] = tabela.get("fonte")
    return resultado
