"""Rotas de produtos e da inteligência histórica."""
from fastapi import APIRouter

from fastapi import HTTPException
from pydantic import BaseModel

from agents.intelligence import analisar_orgao, carregar_snapshot, historico_produto
from agents.precos import MAPA, carregar_tabela, ler_tabela_md, salvar_tabela, skus_do_produto
from db.client import get_supabase_client

router = APIRouter()
COLUNAS = (
    "id,slug,nome_comercial,marca,categoria,linha_clinica,registro_anvisa,tem_registro_ms,via_enteral,"
    "publico_alvo,porcao_g,kcal_por_porcao,proteinas_por_porcao_g,sem_gluten,sem_lactose,sem_sacarose"
)


@router.get("/")
async def listar_produtos():
    resposta = get_supabase_client().table("products").select(COLUNAS).order("nome_comercial").execute()
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


@router.get("/inteligencia/clientes")
async def inteligencia_clientes(limite: int = 50):
    """Maiores compradores do histórico, com o que está vencido."""
    clientes = carregar_snapshot().get("clientes", [])
    ordenados = sorted(clientes, key=lambda c: c.get("total") or 0, reverse=True)
    return {"data": ordenados[: max(1, min(limite, 500))], "total": len(clientes)}



class NovaTabela(BaseModel):
    markdown: str
    fonte: str = "tabela importada pelo painel"


@router.get("/precos")
async def tabela_precos():
    """Tabela de preços com desconto e o que cada produto do catálogo usa dela."""
    tabela = carregar_tabela()
    itens = tabela.get("itens") or []
    produtos = get_supabase_client().table("products").select("id,slug,nome_comercial").execute().data
    por_produto = []
    for p in produtos:
        skus = skus_do_produto(p["slug"], itens)
        if skus or p["slug"] in MAPA:
            com_gramas = [s for s in skus if s.get("gramas")]
            barato = min(com_gramas, key=lambda s: s["preco"] / s["gramas"]) if com_gramas else None
            por_produto.append({
                "produto_id": p["id"], "produto": p["nome_comercial"], "skus": skus,
                "menor_por_grama": round(barato["preco"] / barato["gramas"], 4) if barato else None,
                "sku_mais_barato": barato["produto"] if barato else None,
            })
    return {"fonte": tabela.get("fonte"), "atualizado_em": tabela.get("atualizado_em"), "total": len(itens),
            "sem_preco": tabela.get("sem_preco", 0), "produtos": sorted(por_produto, key=lambda x: x["produto"])}


@router.post("/precos/importar")
async def importar_precos(nova: NovaTabela):
    """Troca a tabela pelo .md novo (mesmo formato do exportado da planilha)."""
    itens = ler_tabela_md(nova.markdown)
    if len(itens) < 5:
        raise HTTPException(status_code=400, detail="Não achei a tabela no arquivo. Use o .md exportado da planilha de preços.")
    dados = salvar_tabela(itens, nova.fonte)
    return {"total": dados["total"], "sem_preco": dados["sem_preco"], "fonte": nova.fonte}
