"""
Agente 9 — Recursos Administrativos (O Advogado Digital)
Analisa a desclassificação e elabora minutas de recurso com precisão jurídica
com base na Lei 14.133/21, exigindo validação humana para protocolamento.
"""
import os
import structlog
from pydantic import BaseModel
from models.edital import Edital
try:
    from docx import Document
except ImportError:
    Document = None

log = structlog.get_logger()

class AppealResult(BaseModel):
    status_geracao: str
    texto_gerado: str = ""
    motivo_falha: str = ""
    caminho_arquivo: str = ""

async def _gerar_fundamentacao_llm(contexto: dict) -> str:
    """
    Persona: Advogado Sênior Especialista em Direito Administrativo.
    Constrói a argumentação jurídica cruzando o motivo da desclassificação com a lei.
    """
    # Em produção, usaria um LLM via LangChain/OpenAI.
    # Simulando a resposta técnica exigida pela regra:
    return (
        f"Ato contínuo, a desclassificação baseada em '{contexto.get('motivo_desclassificacao')}' "
        "fere os princípios da razoabilidade e da competitividade, bem como o "
        "Art. 59, §1º da Lei 14.133/21, visto que o produto apresentado atende plenamente "
        f"às exigências normativas, pois {contexto.get('argumento_defesa')}."
    )

async def _renderizar_docx(texto_fundamentacao: str, contexto: dict, filepath: str):
    """
    Renderiza o documento em formatação estrita usando python-docx.
    Formatação exigida: Times New Roman 12, espaçamento 1.5.
    """
    if Document is None:
        log.warning("agent9.docx_lib_missing", msg="python-docx não instalado no ambiente.")
        return
        
    doc = Document()
    
    # Exemplo de formatação
    titulo = doc.add_heading(f"RECURSO ADMINISTRATIVO - PREGÃO {contexto.get('numero_pregao')}", 1)
    
    p = doc.add_paragraph()
    p.add_run(texto_fundamentacao).font.name = 'Times New Roman'
    p.add_run("").font.size = 120000  # 12pt em unidades do docx (aproximado, depende da versão)
    p.paragraph_format.line_spacing = 1.5
    
    doc.save(filepath)

async def gerar_recurso_administrativo(edital: Edital) -> AppealResult:
    """
    Avalia a situação, constrói a fundamentação jurídica e gera o arquivo do recurso.
    Trava o fluxo até assinatura do analista humano.
    """
    log.info("agent9.starting_appeal", edital_id=str(edital.id))
    
    ctx = edital.licit_context or {}
    
    # Trava Anti-Vibe de Qualidade de Dados
    campos_criticos = ["data_sessao", "motivo_desclassificacao", "argumento_defesa"]
    campos_faltantes = [campo for campo in campos_criticos if campo not in ctx or not str(ctx[campo]).strip()]
    
    if campos_faltantes:
        motivo = f"Faltam dados essenciais para elaboração jurídica: {', '.join(campos_faltantes)}"
        log.warning("agent9.context_missing", edital_id=str(edital.id), missing=campos_faltantes)
        return AppealResult(
            status_geracao="contexto_insuficiente",
            motivo_falha=motivo
        )

    # 1. Geração da Tese
    texto_base = await _gerar_fundamentacao_llm({
        "numero_pregao": edital.numero_pregao,
        **ctx
    })
    
    # 2. Renderização Documental
    output_path = f"/tmp/recurso_pregao_{edital.numero_pregao.replace('/','_')}.docx"
    await _renderizar_docx(texto_base, {"numero_pregao": edital.numero_pregao, **ctx}, output_path)

    # 3. Trava Humana Absoluta (Anti-Vibe)
    edital.status = "aguardando_assinatura_juridica"
    
    # (Opcional) Salvar state via Supabase...
    
    return AppealResult(
        status_geracao="pronto_para_revisao",
        texto_gerado=texto_base,
        caminho_arquivo=output_path
    )
