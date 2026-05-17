import os
import sys
import pytest
import respx
import httpx
from datetime import datetime

# Adiciona backend ao PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend')))

from agents.agent1_pncp import fetch_pncp_editais

@pytest.mark.asyncio
@respx.mock
async def test_fetch_pncp_editais_success():
    """Teste para garantir que o Agente 1 busca editais do PNCP e retorna no formato correto."""
    
    # Mock da API do PNCP
    mock_url = "https://pncp.gov.br/api/pncp/v1/orgaos/12345/compras"
    respx.get(mock_url).mock(return_value=httpx.Response(200, json={
        "data": [
            {
                "numeroCompra": "00001/2026",
                "orgaoEntidade": {"razaoSocial": "Prefeitura de Teste"},
                "unidadeOrçamentaria": {"ufCnpj": "SP"},
                "linkSistemaOrigem": "https://pncp.gov.br/app/editais/123",
                "dataPublicacaoPncp": "2026-05-10T10:00:00Z",
                "dataAberturaProposta": "2026-05-20T10:00:00Z"
            }
        ]
    }))

    # Executa a função do agente
    editais = await fetch_pncp_editais(orgao_cnpj="12345")

    # Asserts
    assert len(editais) == 1
    assert editais[0].numero_pregao == "00001/2026"
    assert editais[0].orgao == "Prefeitura de Teste"
    assert editais[0].uf == "SP"
    assert editais[0].portal_origem == "pncp"
    assert editais[0].url_edital == "https://pncp.gov.br/app/editais/123"
    assert editais[0].status == "novo"
