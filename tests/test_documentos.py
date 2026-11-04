"""Proposta e declarações saem do modelo real, com dados do pregão e da empresa."""
import io
from datetime import date

import pytest
from docx import Document

from agents import documentos as D

pytestmark = pytest.mark.skipif(not D.MODELO.exists(), reason="modelo privado da proposta não está nesta máquina")

EDITAL = {"orgao": "Prefeitura Municipal de São José de Mipibu", "numero_pregao": "PE/34/2026 #19476075"}
ITENS = [
    {"numero_item": "31", "descricao": "Módulo de proteína isolada do soro do leite", "produto": "Just Whey Protein Isolado",
     "registro_anvisa": "6.7055.0029", "quantidade": 700, "preco_unitario": 89.9},
    {"numero_item": "23", "descricao": "Módulo de fibras solúveis", "produto": "Just Fibras",
     "registro_anvisa": None, "quantidade": 120, "preco_unitario": 45.5},
]


def _texto(conteudo: bytes) -> str:
    doc = Document(io.BytesIO(conteudo))
    partes = [p.text for p in doc.paragraphs]
    for tabela in doc.tables:
        for linha in tabela.rows:
            partes.append(" | ".join(c.text for c in linha.cells))
    return "\n".join(partes)


def test_proposta_troca_orgao_data_itens_e_total():
    texto = _texto(D.gerar_proposta(EDITAL, ITENS, date(2026, 11, 3), {"numero_processo": "6.303/2026", "validade_proposta_dias": 180}))
    assert "PIRENOPOLIS" not in texto and "SOREND" not in texto  # nada do pregão do modelo sobra
    assert "PREFEITURA MUNICIPAL DE SÃO JOSÉ DE MIPIBU – PREGÃO PE/34/2026 – PROCESSO 6.303/2026" in texto
    assert "#19476075" not in texto
    assert "Anápolis, 3 de novembro de 2026." in texto
    assert "180 dias corridos" in texto  # edital pediu validade maior que a padrão
    assert "JUST WHEY PROTEIN ISOLADO" in texto and "R$ 62.930,00" in texto
    assert "R$ 5.460,00" in texto and "R$ 68.390,00" in texto  # total
    assert "(preencher)" in texto  # registro ausente não é inventado
    assert "NUTROPOLIS COMERCIO" in texto  # dados da empresa do modelo continuam


def test_proposta_de_outro_ramo_com_fabricante_objeto_e_sem_anvisa():
    itens = [{"numero_item": "1", "descricao": "Colchão hospitalar D33, 188x88x14 cm", "produto": "ULTRAFLEX D33",
              "fabricante": "Gilson Colchões", "mostrar_anvisa": False, "quantidade": 50, "preco_unitario": 389.9}]
    texto = _texto(D.gerar_proposta({"orgao": "Hospital Municipal de Goiânia", "numero_pregao": "12/2026"}, itens,
                                    date(2026, 11, 4), objeto="Colchões Hospitalares", cidade="Goiânia"))
    assert "Goiânia, 4 de novembro de 2026." in texto
    assert "aquisição de Colchões Hospitalares" in texto and "Nutrição Especializada" not in texto
    assert "GILSON COLCHÕES" in texto and "ATTIVOS" not in texto
    assert "ANVISA" not in texto
    assert "R$ 19.495,00" in texto


def test_proposta_sem_itens_nao_sai():
    with pytest.raises(ValueError):
        D.gerar_proposta(EDITAL, [])


def test_declaracao_do_pregao_e_do_estoque():
    do_pregao = _texto(D.gerar_declaracao("menor", EDITAL, date(2026, 11, 3)))
    assert "DECLARAÇÃO DE NÃO EMPREGO DE MENOR" in do_pregao
    assert "Pregão nº PE/34/2026, promovido por Prefeitura Municipal de São José de Mipibu" in do_pregao
    assert "31.258.727/0001-05" in do_pregao and "Fernanda Mirabelli Cassino de Luna" in do_pregao
    assert "PROPOSTA COMERCIAL" not in do_pregao  # corpo do modelo foi trocado
    estoque = _texto(D.gerar_declaracao("habilitacao", None, date(2026, 11, 3)))
    assert "procedimentos licitatórios" in estoque and "Pregão nº" not in estoque


def test_todas_as_declaracoes_padrao_montam():
    for decl in D.DECLARACOES:
        assert decl["titulo"] in _texto(D.gerar_declaracao(decl["id"], EDITAL))


def test_detecta_declaracoes_exigidas_e_as_sem_modelo():
    ids, sem_modelo = D.declaracoes_exigidas(
        "Declaração de que não emprega menor de 18 anos em trabalho noturno. Declaração de microempresa.",
        ["Declaração de visita técnica", "Declaração de idoneidade"],
    )
    assert {"menor", "me_epp", "idoneidade"} <= set(ids)
    assert sem_modelo == ["Declaração de visita técnica"]


def test_download_so_aceita_pastas_de_documentos():
    for caminho in ("../.env", "pregoes/../../segredo", "outra/pasta.pdf"):
        with pytest.raises(ValueError):
            D.baixar(caminho)
