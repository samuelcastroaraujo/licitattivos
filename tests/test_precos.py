"""Preço mínimo de cotação a partir da tabela com desconto."""
from agents import precos as P

TABELA_MD = """# Tabela
## PHOLIAS PROFESSIONAL (5 produtos)
| Código | Produto | Valor com desconto |
|---|---|---:|
| ALPA12006 | JUST WHEY ISOLADO PT 250G | R$ 126,89 |
| ALPA12012 | JUST WHEY ISOLADO PT 1.000G | R$ 505,17 |
| ALPA10309 | JUST GLUTAMINA - 5 G SACHÊ | R$ 2,68 |
| ALPA10307 | JUST GLUTAMINA 1000G | R$ 135,63 |
| SALPA95 | SOREND SACHE BAUNILHA 30G -CX 24 UN | R$ 309,87 |
| AALPA208 | JUST WHEY CONCENTRADO COM LACTOSE 1KG (Principal) | R$ 138,55 |
| ALPA16507 | JUST WHEY CONCENTRADO - 300 G STAND UP POUCH | R$ 116,44 |
| ALPA474 | PHOLIAS NAC - 30 CAPS | Não informado |
"""
TABELA = P.ler_tabela_md(TABELA_MD)


def test_le_tabela_pesos_caixas_e_sem_preco():
    por_nome = {s["produto"]: s for s in TABELA}
    assert len(TABELA) == 8
    assert por_nome["JUST WHEY ISOLADO PT 1.000G"]["gramas"] == 1000
    assert por_nome["SOREND SACHE BAUNILHA 30G -CX 24 UN"]["gramas"] == 720  # caixa soma os sachês
    assert por_nome["PHOLIAS NAC - 30 CAPS"]["preco"] is None
    assert por_nome["JUST WHEY ISOLADO PT 250G"]["linha"] == "PHOLIAS PROFESSIONAL"


def test_embalagem_pedida_existe_usa_o_sku():
    r = P.preco_do_item("pholias_just_whey_protein_isolado", "Proteína isolada do soro. Embalagem 250g.", "UND", TABELA)
    assert r["preco_unitario"] == 126.89 and r["codigo"] == "ALPA12006"
    assert "conferir" not in r


def test_numero_de_proteina_nao_vira_embalagem():
    r = P.preco_do_item("pholias_just_whey_protein_isolado", "Com 20 g de proteína por porção. Lata 250 g", "UN", TABELA)
    assert r["preco_unitario"] == 126.89


def test_item_em_gramas_usa_menor_preco_por_grama():
    r = P.preco_do_item("pholias_just_glutamina", "Glutamina em pó", "G", TABELA)
    assert r["preco_unitario"] == round(135.63 / 1000, 4)


def test_embalagem_inexistente_e_proporcional_e_sinalizada():
    r = P.preco_do_item("pholias_just_glutamina", "Glutamina, pote 500 g", "UN", TABELA)
    assert r["preco_unitario"] == 67.82  # 500 g × R$ 0,13563/g, arredondado para cima
    assert r["conferir"] is True


def test_concentrado_com_lactose_nao_entra_no_concentrado():
    skus = [s["produto"] for s in P.skus_do_produto("pholias_just_whey_protein_concentrado", TABELA)]
    assert skus == ["JUST WHEY CONCENTRADO - 300 G STAND UP POUCH"]


def test_produto_sem_mapa_fica_sem_preco():
    assert P.preco_do_item("venum_endurance_limao", "qualquer", "UN", TABELA) is None


def test_valor_total_por_produto_e_itens_100():
    itens = [
        {"id": "a", "numero_item": "31", "produto_id": "w", "score_compatibilidade": 1.0,
         "descricao_original": "Whey isolado embalagem 250g", "requisitos": {"quantidade_pregao": 700, "unidade_solicitada": "UND"}},
        {"id": "b", "numero_item": "32", "produto_id": "g", "score_compatibilidade": 0.8,
         "descricao_original": "Glutamina sachê de 5g", "requisitos": {"quantidade_pregao": 10000, "unidade_solicitada": "UND"}},
        {"id": "c", "numero_item": "40", "produto_id": None, "requisitos": {"quantidade_pregao": 5}},
    ]
    produtos = {"w": {"slug": "pholias_just_whey_protein_isolado", "nome_comercial": "JUST WHEY PROTEIN ISOLADO"},
                "g": {"slug": "pholias_just_glutamina", "nome_comercial": "JUST GLUTAMINA"}}
    r = P.precificar(itens, produtos, TABELA)
    assert r["por_item"]["a"]["total"] == 88823.0  # 700 × 126,89
    assert r["por_item"]["b"]["total"] == 26800.0  # 10.000 × 2,68
    assert "c" not in r["por_item"]  # item sem produto compatível não tem preço
    assert [g["produto"] for g in r["por_produto"]] == ["JUST WHEY PROTEIN ISOLADO", "JUST GLUTAMINA"]
    assert r["total"] == 115623.0 and r["total_100"] == 88823.0
