"""
Agente 5 — Fbrica de Documentos
Carrega templates e gera os artefatos PDF/DOCX (Proposta, Justificativa, etc.)
"""
import os
import structlog
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from docx import Document

from models.edital import Edital

log = structlog.get_logger()

class MissingDocumentDataError(Exception):
    """Exceo lanada quando falta um dado obrigatrio para renderizar o template."""
    pass

REQUIRED_FIELDS = [
    "empresa_nome",
    "empresa_cnpj",
    "data_validade_proposta",
    "prazo_entrega_dias",
    "condicoes_pagamento"
]

def _validate_context(context: dict):
    """Regra Anti-Vibe: Valida se todos os campos requeridos existem e no so nulos."""
    for field in REQUIRED_FIELDS:
        if context.get(field) is None:
            log.error("agent5.missing_data", field=field)
            raise MissingDocumentDataError(f"Dado obrigatrio ausente no contexto: {field}")

async def generate_documents(edital: Edital, output_dir: str):
    """Gera documentos baseados nos itens aprovados/com ressalvas."""
    log.info("agent5.starting_generation", edital_id=str(edital.id))
    
    context = edital.licit_context or {}
    _validate_context(context)
    
    # Prepara itens filtrados
    raw_itens = context.get("itens", [])
    valid_itens = []
    
    for r_item in raw_itens:
        status = r_item.get("status")
        if status in ["verde", "amarelo"]:
            # Prepara variveis computadas para o template (ex: valor_total = qtd * unitario)
            reqs = r_item.get("requisitos", {})
            qtd = reqs.get("quantidade_pregao") or 0
            unitario = r_item.get("preco_unitario") or 0.0
            r_item["quantidade_pregao"] = qtd
            r_item["preco_unitario"] = unitario
            valid_itens.append(r_item)
            
    context["itens"] = valid_itens
    
    # Carrega Templates
    template_dir = os.path.join(os.path.dirname(__file__), "../templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    
    # Gera Proposta Comercial
    template_proposta = env.get_template("proposta_comercial.html")
    html_proposta = template_proposta.render(**context)
    proposta_path = os.path.join(output_dir, "proposta_comercial.pdf")
    HTML(string=html_proposta).write_pdf(proposta_path)
    
    # Gera Justificativa Tcnica
    template_justificativa = env.get_template("justificativa_tecnica.html")
    html_justificativa = template_justificativa.render(**context)
    justificativa_path = os.path.join(output_dir, "justificativa_tecnica.pdf")
    HTML(string=html_justificativa).write_pdf(justificativa_path)
    
    # Gera Word genrico via docx (apenas para provar que a biblioteca pode ser chamada/mockada)
    doc = Document()
    doc.add_heading('Declarao de Compatibilidade', 0)
    doc_path = os.path.join(output_dir, "declaracao_compatibilidade.docx")
    doc.save(doc_path)
    
    log.info("agent5.documents_generated", output_dir=output_dir)
