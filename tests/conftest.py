"""
Conftest central para configuração de ambiente de testes.
"""
import os
import sys
import pytest

# Garante que o backend está no PYTHONPATH para todas as fixtures
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

# Força ambiente de teste para não tocar no Supabase real por acidente
os.environ["ENVIRONMENT"] = "test"
os.environ["SUPABASE_URL"] = "http://localhost:54321"
os.environ["SUPABASE_KEY"] = "fake-key-for-testing"

@pytest.fixture
def mock_supabase_client(mocker):
    """Mocka o cliente do Supabase para testes e reseta o singleton."""
    from db.client import _client
    import db.client
    db.client._client = None  # Reseta o singleton
    return mocker.patch("db.client.create_client")
