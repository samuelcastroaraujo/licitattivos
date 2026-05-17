import os
import sys
import pytest
from fastapi.testclient import TestClient

# Adiciona backend ao PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from main import app

client = TestClient(app)

def test_health_check_returns_200():
    """Confirma que a API base está de pé e as configurações carregaram."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "licitattivos-backend"
