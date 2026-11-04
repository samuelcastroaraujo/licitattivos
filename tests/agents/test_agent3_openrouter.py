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


# ── Gemini ────────────────────────────────────────────────────────────────

def _gemini(monkeypatch, respostas, enviados):
    """respostas: lista de (status, corpo), uma por chamada, na ordem."""
    fila = list(respostas)

    def responder(pedido):
        enviados.append((str(pedido.url), json.loads(pedido.content), pedido.headers.get("x-goog-api-key")))
        status, corpo = fila.pop(0)
        return httpx.Response(status, json=corpo)

    original = httpx.AsyncClient
    monkeypatch.setattr(a3.httpx, "AsyncClient", lambda: original(transport=httpx.MockTransport(responder)))
    monkeypatch.setattr(a3.settings, "llm_provider", "gemini")
    monkeypatch.setattr(a3.settings, "gemini_api_key", "chave-g")
    monkeypatch.setattr(a3.settings, "gemini_model", "modelo-a,modelo-b")
    monkeypatch.setattr(a3, "GEMINI_ESPERAS", (0,))


@pytest.mark.asyncio
async def test_gemini_espera_e_tenta_outra_volta_quando_todos_estao_cheios(monkeypatch):
    enviados, esperas = [], []
    cheio = (503, {"error": {"message": "high demand"}})
    _gemini(monkeypatch, [cheio, cheio, (200, _ok('{"itens": []}'))], enviados)
    monkeypatch.setattr(a3, "GEMINI_ESPERAS", (0, 15))

    async def dormir(segundos):
        esperas.append(segundos)

    monkeypatch.setattr(a3.asyncio, "sleep", dormir)
    assert await a3.call_llm_for_extraction("edital") == {"itens": []}
    assert esperas == [15]
    assert "modelo-a" in enviados[2][0]


def _ok(texto):
    partes = [{"text": "pensando", "thought": True}, {"text": texto}]
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": partes}}]}


@pytest.mark.asyncio
async def test_gemini_envia_esquema_e_ignora_raciocinio(monkeypatch):
    enviados = []
    _gemini(monkeypatch, [(200, _ok('{"itens": []}'))], enviados)
    assert await a3.call_llm_for_extraction("edital") == {"itens": []}
    url, corpo, chave = enviados[0]
    assert "modelo-a:generateContent" in url
    assert chave == "chave-g"
    assert corpo["generationConfig"]["responseJsonSchema"] == a3._ESQUEMA_ITENS
    assert corpo["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.asyncio
async def test_gemini_sobrecarregado_passa_para_o_proximo_modelo(monkeypatch):
    enviados = []
    _gemini(monkeypatch, [(503, {"error": {"message": "high demand"}}), (200, _ok('{"itens": [1]}'))], enviados)
    assert await a3.call_llm_for_extraction("edital") == {"itens": [1]}
    assert "modelo-b" in enviados[1][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("respostas,mensagem", [
    ([(400, {"error": {"message": "API key not valid"}})], "inválida"),
    ([(503, {"error": {"message": "x"}}), (429, {"error": {"message": "quota"}})], "sobrecarregado"),
    ([(200, {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]})], "cortada"),
])
async def test_gemini_erros_ficam_claros(monkeypatch, respostas, mensagem):
    _gemini(monkeypatch, respostas, [])
    with pytest.raises(RuntimeError, match=mensagem):
        await a3.call_llm_for_extraction("edital")
