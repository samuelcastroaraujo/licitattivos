import json

import httpx
import pytest

from agents import agent3_requirements as a3


def _cliente(monkeypatch, status, corpo, capturado=None):
    def responder(pedido):
        if capturado is not None:
            capturado.update(json.loads(pedido.content), auth=pedido.headers["authorization"])
        return httpx.Response(status, json=corpo)

    original = httpx.AsyncClient
    monkeypatch.setattr(a3.httpx, "AsyncClient", lambda: original(transport=httpx.MockTransport(responder)))
    monkeypatch.setattr(a3.settings, "openrouter_api_key", "chave")


@pytest.mark.asyncio
async def test_envia_esquema_e_le_json(monkeypatch):
    enviado = {}
    _cliente(monkeypatch, 200, {"choices": [{"finish_reason": "stop", "message": {"content": '{"itens": []}'}}]}, enviado)
    assert await a3.call_llm_for_extraction("edital") == {"itens": []}
    assert enviado["response_format"]["json_schema"]["strict"] is True
    assert enviado["provider"]["require_parameters"] is True
    assert enviado["auth"] == "Bearer chave"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,corpo,mensagem", [
    (401, {}, "inválida"),
    (402, {}, "créditos"),
    (200, {"error": {"message": "falhou"}}, "falhou"),
    (200, {"choices": [{"finish_reason": "length", "message": {"content": "{"}}]}, "cortada"),
])
async def test_erros_ficam_claros(monkeypatch, status, corpo, mensagem):
    _cliente(monkeypatch, status, corpo)
    with pytest.raises(RuntimeError, match=mensagem):
        await a3.call_llm_for_extraction("edital")
