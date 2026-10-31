"""Rotas de produtos e da inteligência histórica."""
from fastapi import APIRouter

from agents.intelligence import analisar_orgao, carregar_snapshot, historico_produto
from db.client import get_supabase_client

router = APIRouter()


@router.get("/")
async def listar_produtos():
    resposta = get_supabase_client().table("products").select("id,slug,nome_comercial,categoria,tem_registro_ms").order("nome_comercial").execute()
    return {"data": resposta.data}


@router.get("/inteligencia/orgao")
async def inteligencia_orgao(nome: str, uf: str | None = None):
    return analisar_orgao(nome, uf)


@router.get("/inteligencia/produto")
async def inteligencia_produto(nome: str):
    return {"data": historico_produto(nome)}


@router.get("/inteligencia/resumo")
async def inteligencia_resumo():
    base = carregar_snapshot()
    return {"resumo": base.get("resumo", {}), "regras": base.get("regras", [])}
