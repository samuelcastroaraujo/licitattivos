import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend')))

# Mocking Weasyprint BEFORE importing agent5 to avoid GTK3 missing library errors on Windows
mock_weasyprint = MagicMock()
sys.modules['weasyprint'] = mock_weasyprint

from models.edital import Edital, LicitItem, LicitItemRequisitos
from agents.agent5_generator import generate_documents, MissingDocumentDataError

@pytest.fixture
def dummy_edital():
    item1 = LicitItem(
        numero_item="Item 04",
        descricao_original="Suplemento Aprovado",
        tipo_produto="suplemento",
        requisitos=LicitItemRequisitos(quantidade_pregao=100),
        status="verde",
        preco_unitario=50.0,
        produto_id="11111111-1111-1111-1111-111111111111",
        justificativa="Aprovado sem ressalvas.",
        compativel=True
    )
    
    item2 = LicitItem(
        numero_item="Item 05",
        descricao_original="Suplemento com Ressalva",
        tipo_produto="suplemento",
        requisitos=LicitItemRequisitos(quantidade_pregao=200),
        status="amarelo",
        preco_unitario=150.0,
        produto_id="22222222-2222-2222-2222-222222222222",
        justificativa="Requer recurso administrativo para justificar a RDC.",
        compativel=True
    )
    
    edital = Edital(
        id="123e4567-e89b-12d3-a456-426614174000",
        numero_pregao="00001/2026",
        orgao="Prefeitura de Teste",
        portal_origem="pncp",
        status="compatibilidade_calculada",
        licit_context={
            "itens": [item1.model_dump(), item2.model_dump()],
            # Campos do template
            "empresa_nome": "Attivos Magisttrais Indústria e Comércio Ltda.",
            "empresa_cnpj": "00.000.000/0001-00",
            "data_validade_proposta": "10/06/2026",
            "prazo_entrega_dias": 10,
            "condicoes_pagamento": "30 dias"
        },
        created_at="2026-05-10T10:00:00Z"
    )
    return edital

@pytest.mark.asyncio
async def test_agent5_document_generation_success(dummy_edital, tmp_path):
    """Verifica se os documentos são gerados corretamente e preservam a matemática e o texto."""
    
    output_dir = tmp_path / "docs"
    output_dir.mkdir()
    
    # Mocking weasyprint to just intercept the HTML string instead of rendering real PDF
    with patch("agents.agent5_generator.HTML") as mock_html, \
         patch("agents.agent5_generator.Document") as mock_doc:
        
        # Faz com que HTML().write_pdf() não faça nada
        mock_html_instance = MagicMock()
        mock_html.return_value = mock_html_instance
        
        # Roda o gerador
        await generate_documents(dummy_edital, str(output_dir))
        
        # Verifica se weasyprint foi chamado para a Proposta e Justificativa
        assert mock_html.call_count >= 2
        
        # Pega a string HTML passada para o WeasyPrint para a Justificativa/Proposta
        html_calls = mock_html.call_args_list
        html_strings = [call.kwargs.get("string", "") for call in html_calls]
        combined_html = " ".join(html_strings)
        
        # ASSERT: A Matemática (100 * 50 = 5000, 200 * 150 = 30000)
        assert "5000" in combined_html or "5.000" in combined_html
        assert "30000" in combined_html or "30.000" in combined_html
        
        # ASSERT CRÍTICO: Justificativa exata
        assert "Requer recurso administrativo para justificar a RDC" in combined_html
        
        # ASSERT Cabeçalho
        assert "Attivos Magisttrais" in combined_html
        assert "00.000.000/0001-00" in combined_html
        
        # ASSERT Preservação do Item 
        assert "Item 04" in combined_html
        assert "Item 05" in combined_html

@pytest.mark.asyncio
async def test_agent5_anti_vibe_missing_data(dummy_edital, tmp_path):
    """Anti-vibe: Se falta dado obrigatório no contexto, levanta MissingDocumentDataError."""
    
    # Sabota o contexto removendo um dado crítico que o template exige
    dummy_edital.licit_context["data_validade_proposta"] = None
    
    output_dir = tmp_path / "docs"
    output_dir.mkdir()
    
    with pytest.raises(MissingDocumentDataError) as exc_info:
        await generate_documents(dummy_edital, str(output_dir))
        
    assert "data_validade_proposta" in str(exc_info.value)
