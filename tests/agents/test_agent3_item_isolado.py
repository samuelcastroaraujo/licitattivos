from agents.agent3_requirements import _revalidate_with_regex


def test_valor_de_outro_item_do_edital_nao_contamina():
    requisitos = {"proteina_min_g": None}
    _revalidate_with_regex("Espessante alimentar", "Item 1: suplemento com 20g de proteína", requisitos)
    assert requisitos["proteina_min_g"] is None


def test_decimal_com_virgula():
    requisitos = {"proteina_min_g": 9}
    _revalidate_with_regex("Whey com 12,5 g de proteína", "", requisitos)
    assert requisitos["proteina_min_g"] == 12.5
