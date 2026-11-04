"""Aprendizado: decisões do analista mudam a compatibilidade sem nunca liberar falha dura."""
import asyncio
from unittest.mock import MagicMock

import pytest

from agents import learning
from agents.agent4_compatibility import match_product
from models.edital import LicitItem, LicitItemRequisitos
from models.product import Ingrediente, Ingredientes, Product
from routers import aprendizado

WHEY = "22222222-2222-2222-2222-222222222222"
DESCRITIVO = "Módulo de proteína do soro do leite, 100% proteína, isento de sacarose, lata 400 g"


def _whey(**extra):
    base = dict(
        id=WHEY, slug="pholias_just_whey_protein_concentrado", nome_comercial="Just Whey Protein Concentrado",
        proteinas_por_porcao_g=20, sem_sacarose=True,
        ingredientes=Ingredientes(lista=[Ingrediente(nome="Whey", nome_normalizado="whey protein concentrado")]),
    )
    base.update(extra)
    return Product(**base)


def _item(descricao=DESCRITIVO, **reqs):
    return LicitItem(numero_item="01", descricao_original=descricao, requisitos=LicitItemRequisitos(**reqs))


def _kb(resultado, produto_id=WHEY, descritivo=DESCRITIVO, tipo="feedback_historico", conteudo="motivo do analista"):
    linha = {"id": "kb1", "tipo": tipo, "produto_id": produto_id, "resultado": resultado,
             "descritivo_original": descritivo, "conteudo": conteudo, "peso": 1.0}
    return learning.relevantes(DESCRITIVO, [linha])


def test_similaridade_ignora_acento_e_caixa():
    assert learning.similaridade("PROTEÍNA do SORO", "proteina do soro") == 1.0
    assert learning.similaridade("espessante alimentar", "dieta enteral completa") == 0.0


def test_reprovacao_do_analista_zera_o_produto():
    resultado = asyncio.run(match_product(_item(), _whey(), _kb("incompativel", conteudo="Edital pede isolado")))
    assert resultado.score == 0.0
    assert "Edital pede isolado" in resultado.justificativa_tecnica


def test_nenhum_produto_atende_bloqueia_qualquer_produto():
    resultado = asyncio.run(match_product(_item(), _whey(), _kb("incompativel", produto_id=None)))
    assert resultado.score == 0.0


def test_confirmacao_tira_duvida_mole():
    # A IA pediu um ingrediente com nome diferente do cadastro: sem aprendizado fica em 50%.
    item = _item(ingredientes_obrigatorios=["proteina do soro do leite"])
    assert asyncio.run(match_product(item, _whey(), [])).score == 0.5
    liberado = asyncio.run(match_product(item, _whey(), _kb("compativel")))
    assert liberado.score == 1.0
    assert "Aprendizado" in liberado.justificativa_tecnica


def test_confirmacao_nunca_libera_falha_dura():
    item = _item(proteina_min_g=30, ingredientes_obrigatorios=["proteina do soro do leite"])
    resultado = asyncio.run(match_product(item, _whey(), _kb("compativel")))
    assert resultado.score <= 0.10
    assert "30" in resultado.justificativa_tecnica


def test_confirmacao_em_descritivo_pouco_parecido_nao_vale():
    item = _item(ingredientes_obrigatorios=["proteina do soro do leite"])
    distante = _kb("compativel", descritivo="Módulo de proteína do soro, sachê 10 g, sabor baunilha, para idosos acamados")
    assert asyncio.run(match_product(item, _whey(), distante)).score == 0.5


@pytest.fixture
def gravados(monkeypatch):
    linhas = []
    monkeypatch.setattr(aprendizado, "registrar", lambda **k: linhas.append(k) or k)
    return linhas


def test_feedback_correto_confirma_o_sugerido(gravados):
    aprendizado.registrar_feedback({"descricao_original": DESCRITIVO, "produto_id": WHEY}, aprendizado.Feedback(correto=True))
    assert len(gravados) == 1
    assert gravados[0]["resultado"] == "compativel" and gravados[0]["produto_id"] == WHEY


def test_feedback_errado_com_outro_produto_reprova_e_libera(gravados):
    outro = "33333333-3333-3333-3333-333333333333"
    aprendizado.registrar_feedback({"descricao_original": DESCRITIVO, "produto_id": WHEY},
                                   aprendizado.Feedback(correto=False, produto_correto_id=outro, motivo="É isolado"))
    assert [(g["produto_id"], g["resultado"]) for g in gravados] == [(WHEY, "incompativel"), (outro, "compativel")]


def test_feedback_errado_sem_produto_bloqueia_o_catalogo(gravados):
    aprendizado.registrar_feedback({"descricao_original": DESCRITIVO, "produto_id": WHEY}, aprendizado.Feedback(correto=False))
    assert gravados[0].get("produto_id") is None and gravados[0]["resultado"] == "incompativel"


def test_carregar_conhecimento_sem_banco_nao_quebra():
    quebrado = MagicMock()
    quebrado.table.side_effect = RuntimeError("sem rede")
    assert learning.carregar_conhecimento(quebrado) == []
