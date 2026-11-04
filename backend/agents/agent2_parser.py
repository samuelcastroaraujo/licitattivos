"""
Agente 2 — Parser Sensorial
Extrai texto de PDFs usando pymupdf (nativo) com fallback para pytesseract (OCR local).
"""
import io
import re
import zipfile
from xml.etree import ElementTree

import structlog
import fitz  # pymupdf
import pdfplumber
import pytesseract
from models.edital import Edital
from db.client import get_supabase_client

log = structlog.get_logger()

MIN_WORDS = 100

def _clean_text(text: str) -> str:
    """Limpa o texto extraído removendo espaços duplicados."""
    if not text:
        return ""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)

def _extract_native(pdf_bytes: bytes) -> str:
    """Extrai texto nativo do PDF usando pymupdf."""
    text = ""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                text += page.get_text("text") + "\n"
    except Exception as e:
        log.warning("parser.native_extraction_failed", error=str(e))
    return _clean_text(text)

def _extract_ocr(pdf_bytes: bytes) -> str:
    """Fallback: Extrai texto do PDF convertendo para imagem e usando tesseract."""
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                # Converte página para imagem (resolução padrão do pdfplumber é boa para OCR)
                img = page.to_image(resolution=300).original
                text += pytesseract.image_to_string(img, lang="por") + "\n"
    except Exception as e:
        log.warning("parser.ocr_extraction_failed", error=str(e))
    return _clean_text(text)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def eh_docx(conteudo: bytes) -> bool:
    if not conteudo.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
            return "word/document.xml" in pacote.namelist()
    except zipfile.BadZipFile:
        return False


def texto_docx(conteudo: bytes) -> str:
    """Texto de um .docx, parágrafo por parágrafo. Célula de tabela vira linha própria."""
    with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
        raiz = ElementTree.fromstring(pacote.read("word/document.xml"))
    linhas = []
    for paragrafo in raiz.iter(f"{W}p"):
        partes = []
        for no in paragrafo.iter():
            if no.tag == f"{W}t" and no.text:
                partes.append(no.text)
            elif no.tag == f"{W}tab":
                partes.append("\t")
        linhas.append("".join(partes))
    return _clean_text("\n".join(linhas))


def _docx_dentro_do_zip(conteudo: bytes) -> str:
    """ConLicitação e PNCP às vezes mandam ZIP com edital ou TR em Word."""
    if not conteudo.startswith(b"PK") or eh_docx(conteudo):
        return ""
    textos = []
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
            nomes = sorted(n for n in pacote.namelist() if n.lower().endswith(".docx"))
            for nome in nomes:
                try:
                    textos.append(texto_docx(pacote.read(nome)))
                except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as erro:
                    log.warning("parser.docx_ignorado", arquivo=nome, error=str(erro))
    except zipfile.BadZipFile:
        return ""
    return "\n".join(t for t in textos if t)


async def extract_text_from_file(edital: Edital, conteudo: bytes) -> Edital:
    """Entrada única do parser: PDF, DOCX ou ZIP com PDFs e/ou DOCX."""
    from agents.agent0_ingest import pdf_do_arquivo

    if eh_docx(conteudo):
        log.info("parser.docx", edital_id=str(edital.id))
        return await _concluir(edital, texto_docx(conteudo))
    extra = _docx_dentro_do_zip(conteudo)
    try:
        pdf = pdf_do_arquivo(conteudo)
    except ValueError:
        if extra:
            return await _concluir(edital, extra)
        raise ValueError("Arquivo do edital sem PDF ou DOCX legível.")
    if not pdf.startswith(b"%PDF") and not re.match(rb"\s*%PDF", pdf[:1024]):
        raise ValueError("Formato do arquivo do edital não reconhecido (esperado PDF ou DOCX).")
    return await extract_text_from_pdf(edital, pdf, extra)


async def extract_text_from_pdf(edital: Edital, pdf_bytes: bytes, texto_extra: str = "") -> Edital:
    """Tenta extrair texto nativo. Se insuficiente, aciona OCR. Valida qualidade no fim."""
    log.info("parser.starting_extraction", edital_id=str(edital.id))
    
    # Tentativa 1: Nativo (Rápido)
    raw_text = _extract_native(pdf_bytes)
    word_count = len(raw_text.split())
    
    if word_count < MIN_WORDS:
        log.info("parser.native_insufficient", words=word_count, edital_id=str(edital.id))
        
        # Tentativa 2: OCR Fallback (Lento)
        ocr_text = _extract_ocr(pdf_bytes)
        ocr_word_count = len(ocr_text.split())
        
        if ocr_word_count > word_count:
            raw_text = ocr_text
            word_count = ocr_word_count
            log.info("parser.ocr_used", words=word_count, edital_id=str(edital.id))

    if texto_extra:
        raw_text = f"{raw_text}\n{texto_extra}".strip()
    return await _concluir(edital, raw_text)


async def _concluir(edital: Edital, raw_text: str) -> Edital:
    """Valida a quantidade de texto e grava no banco."""
    word_count = len(raw_text.split())
    # Validação de Qualidade
    if word_count < MIN_WORDS:
        log.warning("parser.quality_validation_failed", words=word_count, edital_id=str(edital.id))
        edital.status = "revisao_manual_parser"
    else:
        edital.status = "texto_extraido"
        
    # Injeta no contexto
    if not edital.licit_context:
        edital.licit_context = {}
    edital.licit_context["raw_text"] = raw_text

    # Salva no banco (apenas se tivermos um DB Client disponível no teste/ambiente)
    try:
        client = get_supabase_client()
        client.table("editais").update({
            "status": edital.status,
            "licit_context": edital.licit_context,
            "raw_text": raw_text # Também salva na coluna principal conforme schema
        }).eq("id", str(edital.id)).execute()
    except Exception as e:
        log.error("parser.db_update_failed", error=str(e), edital_id=str(edital.id))
        
    return edital
