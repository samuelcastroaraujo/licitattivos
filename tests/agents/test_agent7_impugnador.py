import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend')))

from models.edital import Edital
from agents.agent7_impugnador import analyze_edital_juridico, ImpugnacaoResult

@pytest.fixture
def base_edital():
    return Edital(
        id="123e4567-e89b-12d3-a456-426614174000",
        numero_pregao="00001/2026",
        orgao="Prefeitura de Teste",
        portal_origem="pncp",
        status="requisitos_extraidos",
        licit_context={"raw_text": ""},
        created_at="2026-05-10T10:00:00Z"
    )

@pytest.mark.asyncio
async def test_agent7_cenario_a_legal(base_edital, mock_supabase_client):
    """Cenário A (Legal): Cita 'Marca X ou similar'. Gera apenas Pedido de Esclarecimento."""
    base_edital.licit_context["raw_text"] = "O produto deve ser da marca Nestlé ou similar."
    
    with patch("agents.agent7_impugnador.check_equivalent_product") as mock_check:
        mock_check.return_value = True # Temos produto
        
        result = await analyze_edital_juridico(base_edital)
        
        assert isinstance(result, ImpugnacaoResult)
        assert len(result.impugnacoes) == 0
        assert len(result.esclarecimentos) == 1
        assert "ou similar" in result.esclarecimentos[0].lower()
        
        assert base_edital.status == "pendente_revisao_juridica"

@pytest.mark.asyncio
async def test_agent7_cenario_b_vicio_claro(base_edital, mock_supabase_client):
    """Cenário B (Vício Claro): Exige marca específica sem 'ou similar'. Gera Impugnação (Lei 14.133/21)."""
    base_edital.licit_context["raw_text"] = "O produto deve ser exclusivamente Just Whey Concentrado."
    
    with patch("agents.agent7_impugnador.check_equivalent_product") as mock_check:
        mock_check.return_value = True # Temos equivalente para oferecer, precisamos impugnar
        
        result = await analyze_edital_juridico(base_edital)
        
        assert len(result.impugnacoes) == 1
        assert "Vício de Direcionamento" in result.impugnacoes[0]
        assert "14.133" in result.impugnacoes[0]
        assert base_edital.status == "pendente_revisao_juridica"

@pytest.mark.asyncio
async def test_agent7_cenario_c_especificidade_excessiva(base_edital, mock_supabase_client):
    """Cenário C (Especificidade Excessiva): Exige exatos 87.3g de proteína por 100g. Detecta direcionamento implícito."""
    base_edital.licit_context["raw_text"] = "O suplemento deve conter exatos 87.3g de proteína por 100g, sem variação."
    
    with patch("agents.agent7_impugnador.check_equivalent_product") as mock_check:
        mock_check.return_value = True
        
        result = await analyze_edital_juridico(base_edital)
        
        assert len(result.alertas_juridicos) >= 1
        assert any("87.3" in alerta for alerta in result.alertas_juridicos)
        assert any("direcionamento implícito" in alerta.lower() or "especificidade" in alerta.lower() for alerta in result.alertas_juridicos)
        assert base_edital.status == "pendente_revisao_juridica"

@pytest.mark.asyncio
async def test_agent7_sem_equivalente(base_edital, mock_supabase_client):
    """Regra de Ouro: Se não temos equivalente, o Agente 7 age de forma diferente (ex: apenas alerta)."""
    base_edital.licit_context["raw_text"] = "Exclusivamente marca XPTO."
    
    with patch("agents.agent7_impugnador.check_equivalent_product") as mock_check:
        mock_check.return_value = False # NÃO temos produto para disputar
        
        result = await analyze_edital_juridico(base_edital)
        
        # Pode decidir não impugnar gastando tempo jurídico atoa se não temos como fornecer
        assert len(result.impugnacoes) == 0
        assert len(result.alertas_juridicos) >= 1
        assert "não possui" in result.alertas_juridicos[0].lower()
