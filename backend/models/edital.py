"""Modelos Pydantic — Edital e LicitItem."""
from uuid import UUID
from datetime import datetime, date
from typing import Any
from pydantic import BaseModel


class LicitItemRequisitos(BaseModel):
    proteina_min_g: float | None = None
    kcal_min: float | None = None
    kcal_max: float | None = None
    via_enteral_obrigatoria: bool = False
    registro_anvisa_obrigatorio: bool = False
    sem_sacarose: bool | None = None
    sem_gluten: bool | None = None
    sem_lactose: bool | None = None
    ingredientes_obrigatorios: list[str] = []
    ingredientes_proibidos: list[str] = []
    faixa_etaria: str = "qualquer"  # "infantil" | "adulto" | "idoso" | "qualquer"
    faixa_etaria_min_anos: int | None = None
    faixa_etaria_max_anos: int | None = None
    unidade_solicitada: str | None = None
    quantidade_pregao: int | None = None
    outros_requisitos_texto: list[str] = []


class LicitItem(BaseModel):
    numero_item: str
    descricao_original: str
    tipo_produto: str | None = None
    requisitos: LicitItemRequisitos = LicitItemRequisitos()
    produto_id: UUID | None = None
    score_compatibilidade: float | None = None
    compativel: bool | None = None
    alertas: list[str] = []
    justificativa: str | None = None
    preco_referencia: float | None = None
    preco_unitario: float | None = None
    status: str | None = None


class EditalBase(BaseModel):
    numero_pregao: str
    orgao: str
    uf: str | None = None
    portal_origem: str  # "comprasnet" | "bll" | "pncp" | "manual"
    url_edital: str | None = None
    data_publicacao: date | None = None
    data_abertura: datetime | None = None
    status: str = "novo"
    
    # Anexos
    anexo_url_origem: str | None = None
    anexo_local_path: str | None = None
    hash_arquivo: str | None = None


class EditalCreate(EditalBase):
    pass


class Edital(EditalBase):
    id: UUID
    created_at: datetime
    licit_context: dict[str, Any] = {}

    model_config = {"from_attributes": True}
