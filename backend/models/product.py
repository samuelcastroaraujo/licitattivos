"""Modelos Pydantic — Product."""
from uuid import UUID
from typing import Any
from pydantic import BaseModel


class Ingrediente(BaseModel):
    nome: str
    nome_normalizado: str
    funcao: str | None = None
    categoria: str | None = None
    e_alergeno: bool = False
    quantidade_por_porcao_g: float | None = None


class Ingredientes(BaseModel):
    lista: list[Ingrediente]
    nota_pureza: str = ""


class Apresentacao(BaseModel):
    gramatura: str | None = None
    embalagem: str | None = None
    ean: str | None = None
    rendimento: str | None = None


class ProductBase(BaseModel):
    slug: str
    nome_comercial: str
    fabricante: str = "Attivos Magisttrais Indústria e Comércio Ltda."
    marca: str = "Pholias"
    linha_clinica: str | None = None
    categoria: str | None = None
    ncm: str | None = None
    registro_anvisa: str | None = None
    tem_registro_ms: bool = False
    apresentacoes: list[Apresentacao] = []
    descricao: str | None = None
    indicacoes: list[str] = []
    ingredientes: Ingredientes
    alergenicos_contem: list[str] = []
    alergenicos_pode_conter: list[str] = []
    sem_gluten: bool = False
    sem_lactose: bool = False
    sem_sacarose: bool = False
    publico_alvo: str | None = None
    faixa_etaria_min_anos: int | None = None
    faixa_etaria_max_anos: int | None = None
    nutricao_por_porcao: dict[str, Any] = {}
    nutricao_por_100g: dict[str, Any] = {}
    porcao_g: float | None = None
    kcal_por_porcao: float | None = None
    proteinas_por_porcao_g: float | None = None
    carboidratos_por_porcao_g: float | None = None
    gorduras_por_porcao_g: float | None = None
    fibras_por_porcao_g: float | None = None
    sodio_por_porcao_mg: float | None = None
    via_oral: bool = True
    via_enteral: bool = False
    ph_solucao: str | None = None
    solubilidade: str | None = None
    validade_dias: int | None = None
    validade_apos_aberto_dias: int | None = None
    normas_regulatorias: list[str] = []
    diferenciais_tecnicos: list[str] = []


class ProductCreate(ProductBase):
    pass


class Product(ProductBase):
    id: UUID

    model_config = {"from_attributes": True}
