"""Fluxo de decisão do analista e falhas do pipeline, sem tocar no banco real."""
import asyncio
import re
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import main
from agents import agent0_ingest, orchestrator
from agents.intelligence import analisar_orgao, brl
from routers import auth, editais, pipeline

EDITAL_ID = "11111111-1111-1111-1111-111111111111"


class BancoFalso:
    """Guarda os updates feitos em cada tabela e devolve linhas fixas no select."""

    def __init__(self, linhas: dict[str, list[dict]]):
        self.linhas = linhas
        self.updates: list[tuple[str, dict]] = []

    def table(self, nome: str):
        banco = self
        consulta = MagicMock()
        for metodo in ("select", "eq", "limit", "order", "ilike", "gte", "in_", "single"):
            getattr(consulta, metodo).return_value = consulta

        def update(dados):
            banco.updates.append((nome, dados))
            return consulta

        consulta.update.side_effect = update
        consulta.execute.return_value = MagicMock(data=banco.linhas.get(nome, []))
        return consulta


def _cliente(monkeypatch, banco):
    monkeypatch.setattr(main, "get_supabase_client", lambda: MagicMock())
    monkeypatch.setattr(editais, "get_supabase_client", lambda: banco)
    monkeypatch.setattr(pipeline, "get_supabase_client", lambda: banco)
    monkeypatch.setattr(auth.settings, "api_token", "")
    monkeypatch.setattr(auth.settings, "environment", "test")
    banco.documentos_gerados = []

    async def gerar_falso(edital_id):
        banco.documentos_gerados.append(edital_id)

    monkeypatch.setattr(editais, "gerar_documentos_do_edital", gerar_falso)
    return TestClient(main.app)


def test_aprovar_grava_nota_enviada_no_corpo(monkeypatch):
    banco = BancoFalso({"editais": [{"status": "compatibilidade_calculada", "licit_context": {"score_medio": 0.9}}]})
    with _cliente(monkeypatch, banco) as c:
        r = c.post(f"/api/editais/{EDITAL_ID}/approve", json={
            "analista_nota": "Conferi a proteína na ficha.",
            "gap_correcoes": {"item:quantidade_pregao": "500"},
            "justificativas": {"item-1": "Atende com folga."},
            "proposta": [
                {"item_id": "item-1", "quantidade": 700, "preco_unitario": 89.9},
                {"item_id": "item-2", "incluir": False, "quantidade": 10, "preco_unitario": 5},
            ],
        })
    assert r.status_code == 200
    # Aprovar dispara proposta e declarações em segundo plano.
    assert banco.documentos_gerados == [EDITAL_ID]
    tabelas = [t for t, _ in banco.updates]
    assert "licit_items" in tabelas  # justificativa revisada
    final = next(d for t, d in banco.updates if t == "editais")
    assert final["status"] == "pronto_para_envio"
    assert final["licit_context"]["analista_nota"] == "Conferi a proteína na ficha."
    assert final["licit_context"]["aprovacao"]["gap_correcoes"] == {"item:quantidade_pregao": "500"}
    assert final["licit_context"]["score_medio"] == 0.9
    # Só os itens marcados para incluir vão para a proposta.
    assert [p["item_id"] for p in final["licit_context"]["aprovacao"]["proposta"]] == ["item-1"]
    assert final["licit_context"]["documentos"] == {"status": "gerando"}


def test_aprovar_sem_analise_e_bloqueado(monkeypatch):
    banco = BancoFalso({"editais": [{"status": "novo", "licit_context": {}}]})
    with _cliente(monkeypatch, banco) as c:
        r = c.post(f"/api/editais/{EDITAL_ID}/approve", json={})
    assert r.status_code == 400
    assert banco.updates == []


def test_rejeitar_guarda_motivo_e_404_sem_edital(monkeypatch):
    banco = BancoFalso({"editais": [{"licit_context": {}}]})
    with _cliente(monkeypatch, banco) as c:
        assert c.post(f"/api/editais/{EDITAL_ID}/reject", json={"motivo": "Só fórmula infantil."}).status_code == 200
    assert banco.updates[-1][1]["licit_context"]["motivo_rejeicao"] == "Só fórmula infantil."

    vazio = BancoFalso({"editais": []})
    with _cliente(monkeypatch, vazio) as c:
        assert c.post(f"/api/editais/{EDITAL_ID}/reject").status_code == 404


def test_rodar_edital_ja_em_analise_retorna_409(monkeypatch):
    banco = BancoFalso({"editais": [{"status": "em_analise"}]})
    with _cliente(monkeypatch, banco) as c:
        assert c.post(f"/api/pipeline/run/{EDITAL_ID}").status_code == 409


def test_falha_no_pipeline_marca_erro_com_motivo(monkeypatch):
    banco = BancoFalso({"editais": [{"licit_context": {"raw_text": "x" * 10}}]})
    monkeypatch.setattr(orchestrator, "get_supabase_client", lambda: banco)

    async def quebra(_):
        raise RuntimeError("Sem créditos na OpenRouter.")

    monkeypatch.setattr(orchestrator, "executar_pipeline", quebra)
    resultado = asyncio.run(orchestrator.executar_com_seguranca(EDITAL_ID))
    assert resultado["status"] == "erro_pipeline"
    final = banco.updates[-1][1]
    assert final["status"] == "erro_pipeline"
    assert final["licit_context"]["erro_pipeline"] == "Sem créditos na OpenRouter."
    assert "raw_text" not in final["licit_context"]


def test_analise_interrompida_por_reinicio_vira_erro(monkeypatch):
    banco = BancoFalso({"editais": [{"id": EDITAL_ID, "licit_context": {"score_medio": None}}]})
    monkeypatch.setattr(orchestrator, "get_supabase_client", lambda: banco)
    assert orchestrator.destravar_analises_interrompidas() == 1
    final = banco.updates[-1][1]
    assert final["status"] == "erro_pipeline"
    assert "reiniciou" in final["licit_context"]["erro_pipeline"]


def test_link_da_pagina_do_pncp_vira_consulta_de_arquivos(monkeypatch):
    pedidos = []

    async def falso(http, item):
        pedidos.append(item)
        return "https://pncp.gov.br/arquivo.pdf"

    monkeypatch.setattr(agent0_ingest, "_url_do_edital", falso)
    url = asyncio.run(agent0_ingest.anexo_pelo_pncp("https://pncp.gov.br/app/editais/08365850000103/2026/137"))
    assert url == "https://pncp.gov.br/arquivo.pdf"
    assert pedidos[0] == {"orgaoEntidade": {"cnpj": "08365850000103"}, "anoCompra": "2026", "sequencialCompra": "137"}
    assert asyncio.run(agent0_ingest.anexo_pelo_pncp("https://outro.site/edital")) is None


def test_valores_em_formato_brasileiro():
    assert brl(542538) == "R$ 542.538,00"
    base = {"clientes": [{"nome": "PREFEITURA MUNICIPAL DE MARÍLIA", "uf": "SP", "total": 542538.0, "notas": 13,
                          "ultima_compra": "2026-08-10", "vencido": 98718.4}]}
    sinais = " ".join(analisar_orgao("Prefeitura Municipal de Marília", "SP", base)["sinais"])
    assert "R$ 542.538,00" in sinais and "10/08/2026" in sinais and "R$ 98.718,40" in sinais
    assert not re.search(r"\d,\d{3}\.\d{2}", sinais)


def _docx(paragrafos: list[str]) -> bytes:
    import io
    import zipfile
    corpo = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragrafos)
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{corpo}</w:body></w:document>")
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        z.writestr("word/document.xml", xml)
    return memoria.getvalue()


def test_edital_em_docx_e_zip_com_docx_viram_texto(monkeypatch):
    import io
    import zipfile
    from agents import agent2_parser
    from models.edital import Edital

    monkeypatch.setattr(agent2_parser, "get_supabase_client", lambda: MagicMock())
    item = "Item 1 suplemento alimentar com 20 g de proteína por porção " * 20
    arquivo = _docx(["EDITAL PREGÃO 34/2026", item])
    assert agent2_parser.eh_docx(arquivo)

    def novo():
        return Edital(id=EDITAL_ID, numero_pregao="34/2026", orgao="Prefeitura", portal_origem="pncp",
                      created_at="2026-11-01T00:00:00+00:00")

    lido = asyncio.run(agent2_parser.extract_text_from_file(novo(), arquivo))
    assert lido.status == "texto_extraido"
    assert "20 g de proteína" in lido.licit_context["raw_text"]

    pacote = io.BytesIO()
    with zipfile.ZipFile(pacote, "w") as z:
        z.writestr("arquivo_1.docx", arquivo)
    lido_zip = asyncio.run(agent2_parser.extract_text_from_file(novo(), pacote.getvalue()))
    assert lido_zip.status == "texto_extraido"

    import pytest
    with pytest.raises(ValueError):
        asyncio.run(agent2_parser.extract_text_from_file(novo(), b"isto nao e pdf"))


def test_um_item_100_por_cento_torna_o_edital_compativel():
    analise = [
        {"numero_item": "01", "score": 0.5},
        {"numero_item": "07", "score": 1.0},
        {"numero_item": "09", "score": 0.85},
    ]
    assert orchestrator.resultado_do_edital(analise) == ("compativel", ["07"])
    assert orchestrator.resultado_do_edital([{"numero_item": "01", "score": 0.95}]) == ("compatibilidade_calculada", [])
    assert orchestrator.resultado_do_edital([]) == ("compatibilidade_calculada", [])


def test_edital_compativel_pode_ser_aprovado(monkeypatch):
    banco = BancoFalso({"editais": [{"status": "compativel", "licit_context": {"apto_participar": True}}]})
    with _cliente(monkeypatch, banco) as c:
        assert c.post(f"/api/editais/{EDITAL_ID}/approve", json={}).status_code == 200
