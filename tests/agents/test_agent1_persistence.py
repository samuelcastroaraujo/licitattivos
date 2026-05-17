import os
import sys
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

# Adiciona backend ao PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend')))

from models.edital import EditalCreate
from agents.agent1_pncp import save_editais

@pytest.mark.asyncio
async def test_save_editais_persistence(mock_supabase_client):
    """Garante que a função de salvamento insere os metadados no Supabase (idempotente)."""
    
    # Setup do mock do Supabase
    mock_supabase = MagicMock()
    mock_supabase_client.return_value = mock_supabase
    
    # Simula resposta do supabase.table("editais").upsert().execute()
    mock_execute = MagicMock()
    mock_execute.data = [{
        "id": "123e4567-e89b-12d3-a456-426614174000", 
        "numero_pregao": "00001/2026", 
        "orgao": "Prefeitura de Teste",
        "portal_origem": "pncp",
        "status": "novo",
        "created_at": datetime.now(timezone.utc).isoformat()
    }]
    
    mock_upsert = MagicMock()
    mock_upsert.execute.return_value = mock_execute
    
    mock_table = MagicMock()
    mock_table.upsert.return_value = mock_upsert
    mock_supabase.table.return_value = mock_table

    # Dado um edital recém-criado
    edital_create = EditalCreate(
        numero_pregao="00001/2026",
        orgao="Prefeitura de Teste",
        uf="SP",
        portal_origem="pncp",
        url_edital="https://pncp.gov.br/app/editais/123",
        status="novo",
        data_publicacao=datetime.now(timezone.utc).date()
    )

    # Quando salvamos no banco
    saved_editais = await save_editais([edital_create])

    # Então o supabase deve ter sido chamado corretamente
    mock_supabase.table.assert_called_with("editais")
    mock_table.upsert.assert_called_once()
    
    # Verifica o payload enviado pro upsert
    upsert_args = mock_table.upsert.call_args[0][0]
    assert len(upsert_args) == 1
    assert upsert_args[0]["numero_pregao"] == "00001/2026"
    assert upsert_args[0]["orgao"] == "Prefeitura de Teste"
    
    # Verifica se o id foi populado com a resposta do banco
    assert len(saved_editais) == 1
    assert str(saved_editais[0].id) == "123e4567-e89b-12d3-a456-426614174000"
