import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend')))

from models.edital import Edital
from agents.agent2_parser import extract_text_from_pdf

@pytest.mark.asyncio
async def test_agent2_native_extraction(mock_supabase_client):
    """Cenário A: O PDF tem camada de texto nativa legível. Pymupdf extrai com sucesso."""
    
    edital = Edital(
        id="123e4567-e89b-12d3-a456-426614174000",
        numero_pregao="00001/2026",
        orgao="Prefeitura de Teste",
        portal_origem="pncp",
        status="anexo_baixado",
        anexo_local_path="editais_anexos/uuid.pdf",
        licit_context={},
        created_at="2026-05-10T10:00:00Z"
    )
    
    mock_pdf_bytes = b"%PDF-1.4 Native PDF"
    
    # Texto fake longo o suficiente para passar na qualidade (>100 palavras)
    fake_extracted_text = "texto legivel " * 120 
    
    with patch("agents.agent2_parser.fitz.open") as mock_fitz_open, \
         patch("agents.agent2_parser.pytesseract.image_to_string") as mock_tesseract:
        
        # Mockando retorno do pymupdf
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = fake_extracted_text
        mock_doc.__iter__.return_value = [mock_page]
        mock_fitz_open.return_value.__enter__.return_value = mock_doc
        
        updated_edital = await extract_text_from_pdf(edital, mock_pdf_bytes)
        
        # O OCR NÃO deve ser chamado
        mock_tesseract.assert_not_called()
        
        # O texto bruto foi salvo no context
        assert updated_edital.licit_context.get("raw_text") == fake_extracted_text.strip()
        assert updated_edital.status == "texto_extraido"

@pytest.mark.asyncio
async def test_agent2_ocr_fallback(mock_supabase_client):
    """Cenário B: O PDF é escaneado (sem texto nativo). Agente decide fazer fallback pro OCR."""
    
    edital = Edital(
        id="123e4567-e89b-12d3-a456-426614174000",
        numero_pregao="00001/2026",
        orgao="Prefeitura de Teste",
        portal_origem="pncp",
        status="anexo_baixado",
        anexo_local_path="editais_anexos/uuid.pdf",
        licit_context={},
        created_at="2026-05-10T10:00:00Z"
    )
    
    mock_pdf_bytes = b"%PDF-1.4 Scanned PDF"
    
    fake_ocr_text = "texto extraido por ocr e que possui o tamanho minimo necessario " * 50
    
    with patch("agents.agent2_parser.fitz.open") as mock_fitz_open, \
         patch("agents.agent2_parser.pdfplumber.open") as mock_pdfplumber, \
         patch("agents.agent2_parser.pytesseract.image_to_string") as mock_tesseract:
         
        # Pymupdf retorna vazio (simulando imagem)
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "   \n  " 
        mock_doc.__iter__.return_value = [mock_page]
        mock_fitz_open.return_value.__enter__.return_value = mock_doc
        
        # Pdfplumber simula transformar página em imagem
        mock_plumber_doc = MagicMock()
        mock_plumber_page = MagicMock()
        mock_plumber_page.to_image.return_value.original = "fake_image"
        mock_plumber_doc.pages = [mock_plumber_page]
        mock_pdfplumber.return_value.__enter__.return_value = mock_plumber_doc
        
        # Ocr retorna texto
        mock_tesseract.return_value = fake_ocr_text
        
        updated_edital = await extract_text_from_pdf(edital, mock_pdf_bytes)
        
        # OCR FOI chamado
        mock_tesseract.assert_called_once()
        
        # O texto bruto foi salvo
        assert updated_edital.licit_context.get("raw_text") == fake_ocr_text.strip()
        assert updated_edital.status == "texto_extraido"

@pytest.mark.asyncio
async def test_agent2_quality_validation_failure(mock_supabase_client):
    """Desafio: Se a extração (nativa ou ocr) resultar em lixo ou texto curto, muda status."""
    
    edital = Edital(
        id="123e4567-e89b-12d3-a456-426614174000",
        numero_pregao="00001/2026",
        orgao="Prefeitura de Teste",
        portal_origem="pncp",
        status="anexo_baixado",
        anexo_local_path="editais_anexos/uuid.pdf",
        licit_context={},
        created_at="2026-05-10T10:00:00Z"
    )
    
    mock_pdf_bytes = b"%PDF-1.4 Garbage"
    
    # Texto minúsculo (< 100 palavras)
    garbage_text = "Sopa de letrinhas ilegível *#&@)(*& edital" 
    
    with patch("agents.agent2_parser.fitz.open") as mock_fitz_open, \
         patch("agents.agent2_parser.pytesseract.image_to_string") as mock_tesseract, \
         patch("agents.agent2_parser.pdfplumber.open") as mock_pdfplumber:
         
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = garbage_text
        mock_doc.__iter__.return_value = [mock_page]
        mock_fitz_open.return_value.__enter__.return_value = mock_doc
        
        # Ocr também retorna lixo (simulando falha total)
        mock_plumber_doc = MagicMock()
        mock_plumber_page = MagicMock()
        mock_plumber_doc.pages = [mock_plumber_page]
        mock_pdfplumber.return_value.__enter__.return_value = mock_plumber_doc
        mock_tesseract.return_value = garbage_text
        
        updated_edital = await extract_text_from_pdf(edital, mock_pdf_bytes)
        
        # Deve ter sido marcado para revisão manual
        assert updated_edital.status == "revisao_manual_parser"
