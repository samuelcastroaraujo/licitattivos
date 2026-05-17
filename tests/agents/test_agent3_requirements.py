import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend')))

from models.edital import Edital
from agents.agent3_requirements import extract_requirements

@pytest.mark.asyncio
async def test_agent3_successful_extraction(mock_supabase_client):
    """Garante extração de metadados críticos como item_numero e obrigatoriedade MS."""
    
    edital = Edital(
        id="123e4567-e89b-12d3-a456-426614174000",
        numero_pregao="00001/2026",
        orgao="Prefeitura de Teste",
        portal_origem="pncp",
        status="texto_extraido",
        licit_context={
            "raw_text": "Item 01: Suplemento hiperproteico, mínimo 20g de proteína por porção. Exclusivo para via enteral. É obrigatório apresentar registro no MS."
        },
        created_at="2026-05-10T10:00:00Z"
    )

    mock_llm_response = {
        "itens": [
            {
                "numero_item": "01",
                "descricao_original": "Suplemento hiperproteico...",
                "tipo_produto": "suplemento",
                "requisitos": {
                    "proteina_min_g": 20.0,
                    "registro_anvisa_obrigatorio": True,
                    "via_enteral_obrigatoria": True
                }
            }
        ]
    }

    with patch("agents.agent3_requirements.call_llm_for_extraction") as mock_llm:
        mock_llm.return_value = mock_llm_response
        
        mock_supabase = MagicMock()
        mock_supabase_client.return_value = mock_supabase
        
        # Simula resposta do DB para inserção
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "uuid-item-1"}])
        
        itens = await extract_requirements(edital)
        
        assert len(itens) == 1
        assert itens[0].numero_item == "01"
        assert itens[0].requisitos.registro_anvisa_obrigatorio is True
        assert itens[0].requisitos.proteina_min_g == 20.0
        
        # Verifica se o banco foi chamado
        mock_supabase.table.assert_any_call("licit_items")
        mock_supabase.table().insert.assert_called_once()

@pytest.mark.asyncio
async def test_agent3_regex_validation_overrides_llm_hallucination(mock_supabase_client):
    """Falha Crítica: LLM alucina valor numérico (25g). Regex deve detectar (20g) e sobrepor."""
    
    edital = Edital(
        id="123e4567-e89b-12d3-a456-426614174000",
        numero_pregao="00001/2026",
        orgao="Prefeitura de Teste",
        portal_origem="pncp",
        status="texto_extraido",
        licit_context={
            "raw_text": "Item 02: Módulo proteico contendo exatos 20g de proteina na porção de 30g."
        },
        created_at="2026-05-10T10:00:00Z"
    )

    # O mock do LLM finge que extraiu 25g (ALUCINAÇÃO)
    mock_llm_response = {
        "itens": [
            {
                "numero_item": "02",
                "descricao_original": "Módulo proteico contendo exatos 20g de proteina...",
                "tipo_produto": "modulo_proteina",
                "requisitos": {
                    "proteina_min_g": 25.0  # Alucinação
                }
            }
        ]
    }

    with patch("agents.agent3_requirements.call_llm_for_extraction") as mock_llm:
        mock_llm.return_value = mock_llm_response
        
        mock_supabase = MagicMock()
        mock_supabase_client.return_value = mock_supabase
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "uuid-item-2"}])
        
        itens = await extract_requirements(edital)
        
        assert len(itens) == 1
        # O Regex deve ter rodado e sobreposto os 25g com os 20g reais do texto
        assert itens[0].requisitos.proteina_min_g == 20.0
        
        # Deve ter adicionado um alerta de gap se faltou dado de quantidade (Anti-Vibe rule)
        assert any("gap_de_informacao" in alerta for alerta in itens[0].alertas)

@pytest.mark.asyncio
async def test_agent3_missing_critical_data_creates_alert(mock_supabase_client):
    """Agente não deve chutar se falta dado (ex: qtd do pregão). Deve gerar alerta."""
    
    edital = Edital(
        id="123e4567-e89b-12d3-a456-426614174000",
        numero_pregao="00001/2026",
        orgao="Prefeitura de Teste",
        portal_origem="pncp",
        status="texto_extraido",
        licit_context={
            "raw_text": "Item 03: Fórmula Pediátrica. Quantidade não especificada."
        },
        created_at="2026-05-10T10:00:00Z"
    )

    mock_llm_response = {
        "itens": [
            {
                "numero_item": "03",
                "descricao_original": "Fórmula Pediátrica",
                "tipo_produto": "nutricao_pediatrica",
                "requisitos": {
                    "quantidade_pregao": None # O LLM honesto marcou nulo
                }
            }
        ]
    }

    with patch("agents.agent3_requirements.call_llm_for_extraction") as mock_llm:
        mock_llm.return_value = mock_llm_response
        
        mock_supabase = MagicMock()
        mock_supabase_client.return_value = mock_supabase
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "uuid-item-3"}])
        
        itens = await extract_requirements(edital)
        
        assert itens[0].requisitos.quantidade_pregao is None
        assert "gap_de_informacao: quantidade_pregao" in itens[0].alertas
