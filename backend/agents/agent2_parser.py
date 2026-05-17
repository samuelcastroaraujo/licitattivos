"""
Agente 2 — Parser Sensorial
Extrai texto de PDFs usando pymupdf (nativo) com fallback para pytesseract (OCR local).
"""
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
        with pdfplumber.open(pdf_bytes) as pdf:
            for page in pdf.pages:
                # Converte página para imagem (resolução padrão do pdfplumber é boa para OCR)
                img = page.to_image(resolution=300).original
                text += pytesseract.image_to_string(img, lang="por") + "\n"
    except Exception as e:
        log.warning("parser.ocr_extraction_failed", error=str(e))
    return _clean_text(text)

async def extract_text_from_pdf(edital: Edital, pdf_bytes: bytes) -> Edital:
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
