import os
import sys
import pytest
import respx
import httpx
from unittest.mock import MagicMock
import hashlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend')))

from models.edital import Edital
from agents.agent1_pncp import download_edital_anexo

@pytest.mark.asyncio
@respx.mock
async def test_download_anexo_success(mock_supabase_client):
    """Garante que o PDF é baixado, armazenado no bucket correto e o hash é gerado."""
    
    # Mock de um edital existente
    edital = Edital(
        id="123e4567-e89b-12d3-a456-426614174000",
        numero_pregao="00001/2026",
        orgao="Prefeitura de Teste",
        portal_origem="pncp",
        url_edital="https://pncp.gov.br/app/editais/123",
        anexo_url_origem="https://pncp.gov.br/api/pncp/v1/orgaos/123/arquivos/1",
        status="novo",
        created_at="2026-05-10T10:00:00Z"
    )

    # Mock do HTTP Download (PDF Fake)
    fake_pdf_bytes = b"%PDF-1.4 Fake PDF Content"
    expected_hash = hashlib.sha256(fake_pdf_bytes).hexdigest()
    respx.get(edital.anexo_url_origem).mock(return_value=httpx.Response(200, content=fake_pdf_bytes))

    # Mock do Supabase Storage e DB
    mock_supabase = MagicMock()
    mock_supabase_client.return_value = mock_supabase
    
    # Supabase upload success
    mock_supabase.storage.from_.return_value.upload.return_value = {"Key": f"editais_anexos/{edital.id}.pdf"}
    
    # Executa a função
    updated_edital = await download_edital_anexo(edital)

    # Asserts - O arquivo "pousou"?
    mock_supabase.storage.from_.assert_called_with("editais_anexos")
    mock_supabase.storage.from_().upload.assert_called_once()
    
    # Asserts - O banco foi atualizado?
    mock_supabase.table.assert_called_with("editais")
    mock_supabase.table().update.assert_called_once()
    
    update_payload = mock_supabase.table().update.call_args[0][0]
    assert update_payload["anexo_local_path"] is not None
    assert update_payload["hash_arquivo"] == expected_hash
    assert updated_edital.hash_arquivo == expected_hash

@pytest.mark.asyncio
@respx.mock
async def test_download_anexo_retry_and_failure(mock_supabase_client):
    """Garante o retry (3x) e a atualização para erro_download se todas falharem."""
    
    edital = Edital(
        id="123e4567-e89b-12d3-a456-426614174000",
        numero_pregao="00001/2026",
        orgao="Prefeitura de Teste",
        portal_origem="pncp",
        url_edital="https://pncp.gov.br/app/editais/123",
        anexo_url_origem="https://pncp.gov.br/api/pncp/v1/orgaos/123/arquivos/1",
        status="novo",
        created_at="2026-05-10T10:00:00Z"
    )

    # Simula 3 falhas seguidas (500 Internal Server Error)
    route = respx.get(edital.anexo_url_origem).mock(return_value=httpx.Response(500))

    mock_supabase = MagicMock()
    mock_supabase_client.return_value = mock_supabase

    # Executa a função
    updated_edital = await download_edital_anexo(edital)

    # Asserts
    assert route.call_count == 3  # Tenta 3 vezes
    mock_supabase.storage.from_().upload.assert_not_called()  # Não faz upload se falhou
    
    # O banco deve registrar erro
    mock_supabase.table.assert_called_with("editais")
    update_payload = mock_supabase.table().update.call_args[0][0]
    assert update_payload["status"] == "erro_download"
    assert updated_edital.status == "erro_download"
