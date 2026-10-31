from fastapi.testclient import TestClient
from unittest.mock import MagicMock

import main
from routers import auth


def _cliente(monkeypatch, ambiente, token):
    monkeypatch.setattr(main, "get_supabase_client", lambda: MagicMock())
    monkeypatch.setattr(auth.settings, "environment", ambiente)
    monkeypatch.setattr(auth.settings, "api_token", token)
    return TestClient(main.app)


def test_producao_sem_token_configurado_falha_fechada(monkeypatch):
    with _cliente(monkeypatch, "production", "") as c:
        assert c.get("/api/editais/").status_code == 401
        assert c.post("/api/pipeline/run/novos").status_code == 401


def test_token_errado_e_certo(monkeypatch):
    with _cliente(monkeypatch, "production", "segredo") as c:
        assert c.post("/api/pipeline/run/novos", headers={"X-API-Token": "errado"}).status_code == 401
        assert c.get("/api/editais/", headers={"X-API-Token": "segredo"}).status_code != 401


def test_webhook_e_id_invalido(monkeypatch):
    with _cliente(monkeypatch, "production", "segredo") as c:
        assert c.post("/api/pipeline/webhook/apify", json=[]).status_code == 401
        assert c.post("/api/pipeline/run/nao-e-uuid", headers={"X-API-Token": "segredo"}).status_code == 422
