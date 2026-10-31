"""Proteção da API: o backend usa a chave total do banco, então nenhuma rota de dados fica aberta."""
import hmac

from fastapi import Header, HTTPException

from config import settings


def token_valido(recebido: str) -> bool:
    if not settings.api_token:
        # Sem token só o desenvolvimento local funciona; produção falha fechada.
        return settings.environment != "production"
    return hmac.compare_digest(recebido, settings.api_token)


async def exigir_token(x_api_token: str = Header(default="")) -> None:
    if not token_valido(x_api_token):
        raise HTTPException(status_code=401, detail="Não autorizado.")
