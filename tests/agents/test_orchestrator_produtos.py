from unittest.mock import MagicMock

from agents.agent0_ingest import edital_de_conlicitacao
from agents.orchestrator import carregar_produtos


def _linha(slug, marca, apresentacoes):
    return {"id": "123e4567-e89b-12d3-a456-426614174000", "slug": slug, "nome_comercial": slug, "marca": marca,
            "ingredientes": {"lista": []}, "apresentacoes": apresentacoes}


def test_so_pholias_e_apresentacao_incompleta_nao_derruba():
    cliente = MagicMock()
    cliente.table.return_value.select.return_value.execute.return_value.data = [
        _linha("a", "PHOLIAS", [{"ean": "1"}]),
        _linha("b", "VENUM", []),
        _linha("c", "PHOLIAS", "invalido"),
    ]
    assert [p.slug for p in carregar_produtos(cliente)] == ["a"]


def test_reingestao_nao_reenvia_status():
    edital = edital_de_conlicitacao({"id": 1, "edital": "PE/1", "public_body": {"nome": "X"}})
    assert "status" not in edital.model_dump(exclude_unset=True)
