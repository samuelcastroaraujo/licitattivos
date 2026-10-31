import pytest

from agents.agent4_compatibility import match_product
from models.edital import LicitItem, LicitItemRequisitos
from models.product import Product


def produto(**extra):
    base = dict(
        id="123e4567-e89b-12d3-a456-426614174000", slug="x", nome_comercial="X",
        ingredientes={"lista": [{"nome": "Sacarose", "nome_normalizado": "sacarose", "funcao": "", "categoria": "carboidrato", "e_alergeno": False}]},
    )
    base.update(extra)
    return Product.model_validate(base)


@pytest.mark.asyncio
@pytest.mark.parametrize("requisitos", [
    {"ingredientes_proibidos": ["Sacarose"]},
    {"sem_gluten": True},
    {"sem_lactose": True},
    {"sem_sacarose": True},
    {"faixa_etaria_min_anos": 60},
])
async def test_filtros_eliminatorios_nao_aprovam(requisitos):
    item = LicitItem(numero_item="1", descricao_original="d", requisitos=LicitItemRequisitos(**requisitos))
    resultado = await match_product(item, produto(faixa_etaria_max_anos=9))
    assert resultado.status == "vermelho"


@pytest.mark.asyncio
async def test_produto_que_atende_continua_verde():
    item = LicitItem(numero_item="1", descricao_original="Módulo de glutamina", requisitos=LicitItemRequisitos(sem_gluten=True))
    assert (await match_product(item, produto(slug="pholias_just_glutamina", sem_gluten=True))).status == "verde"


@pytest.mark.asyncio
@pytest.mark.parametrize("descricao,slug,status", [
    ("Espessante alimentar instantâneo", "pholias_just_glutamina", "vermelho"),
    ("Espessante alimentar instantâneo", "pholias_liqthick", "verde"),
    ("Dieta enteral polimérica normocalórica sistema fechado", "pholias_sorend_baunilha", "vermelho"),
    ("Sonda nasoenteral para dieta", "pholias_just_whey_protein_isolado", "vermelho"),
    ("Módulo de proteína para nutrição enteral", "pholias_just_whey_protein_isolado", "verde"),
    ("Suplemento alimentar diverso", "pholias_4mag", "vermelho"),
])
async def test_item_sem_numero_nao_aprova_qualquer_produto(descricao, slug, status):
    item = LicitItem(numero_item="1", descricao_original=descricao)
    assert (await match_product(item, produto(slug=slug))).status == status


@pytest.mark.asyncio
async def test_notificado_nao_vale_como_registro_ms():
    item = LicitItem(numero_item="1", descricao_original="Módulo de glutamina", requisitos=LicitItemRequisitos(registro_anvisa_obrigatorio=True))
    assert (await match_product(item, produto(slug="pholias_just_glutamina", tem_registro_ms=True))).status == "vermelho"
    item2 = LicitItem(numero_item="1", descricao_original="Whey protein isolado", requisitos=LicitItemRequisitos(registro_anvisa_obrigatorio=True))
    assert (await match_product(item2, produto(slug="pholias_just_whey_protein_isolado", tem_registro_ms=True))).status == "verde"


@pytest.mark.asyncio
async def test_base_100g_gera_ressalva():
    item = LicitItem(numero_item="1", descricao_original="Whey com 80g de proteína por 100g", requisitos=LicitItemRequisitos(proteina_min_g=80))
    assert (await match_product(item, produto(slug="pholias_just_whey_protein_isolado", proteinas_por_porcao_g=90))).status == "amarelo"
