import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend')))

from models.product import Product, Ingredientes
from models.edital import LicitItem, LicitItemRequisitos
from agents.agent4_compatibility import match_product, ScoreResult

@pytest.mark.asyncio
async def test_agent4_critical_failure_math_threshold():
    """Cenário de Falha Crítica: Edital pede 20g proteína, produto tem 0g. Score <= 0.10."""
    
    item = LicitItem(
        numero_item="01",
        descricao_original="Suplemento hiperproteico 20g",
        tipo_produto="suplemento",
        requisitos=LicitItemRequisitos(
            proteina_min_g=20.0
        )
    )
    
    product = Product(
        id="11111111-1111-1111-1111-111111111111",
        slug="just-glutamina",
        nome_comercial="Just Glutamina",
        proteinas_por_porcao_g=0.0,  # Zero proteína
        ingredientes=Ingredientes(lista=[])
    )
    
    # Mock knowledge DB para não interferir
    with patch("agents.agent4_compatibility.get_knowledge_items") as mock_kb:
        mock_kb.return_value = []  # Sem histórico
        
        result = await match_product(item, product)
        
        assert isinstance(result, ScoreResult)
        assert result.score <= 0.10
        assert result.status in ["incompatível", "vermelho"]
        assert "proteína" in result.justificativa_tecnica.lower()

@pytest.mark.asyncio
async def test_agent4_ressalva_regulatory():
    """Regra do CLAUDE.md: Registro MS exigido é eliminatório para produto sem registro confirmado. Alerta."""
    
    item = LicitItem(
        numero_item="02",
        descricao_original="Suplemento alimentar com registro MS obrigatório",
        requisitos=LicitItemRequisitos(
            registro_anvisa_obrigatorio=True
        )
    )
    
    product = Product(
        id="22222222-2222-2222-2222-222222222222",
        slug="sorend",
        nome_comercial="Sorend",
        tem_registro_ms=False,  # Dispensado
        proteinas_por_porcao_g=None,  # Não aplicável neste teste
        ingredientes=Ingredientes(lista=[])
    )
    
    with patch("agents.agent4_compatibility.get_knowledge_items") as mock_kb:
        mock_kb.return_value = []
        
        result = await match_product(item, product)
        
        assert result.score <= 0.10
        assert result.status == "vermelho"
        assert "registro" in result.justificativa_tecnica.lower()

@pytest.mark.asyncio
async def test_agent4_layer0_history_override():
    """A Regra Absoluta: Histórico tem prioridade. Se tem regra_fixa reprovando, trava em 0."""
    
    item = LicitItem(
        numero_item="03",
        descricao_original="Módulo de Glutamina",
        requisitos=LicitItemRequisitos()
    )
    
    product = Product(
        id="11111111-1111-1111-1111-111111111111",
        slug="just-glutamina",
        nome_comercial="Just Glutamina",
        ingredientes=Ingredientes(lista=[])
    )
    
    with patch("agents.agent4_compatibility.get_knowledge_items") as mock_kb:
        # Retorna uma regra histórica reprovando sumariamente
        mock_kb.return_value = [{"regra_fixa": True, "decisao": "reprovado", "motivo": "Edital exige probiótico associado"}]
        
        result = await match_product(item, product)
        
        assert result.score == 0.0
        assert "Edital exige probiótico associado" in result.justificativa_tecnica
        assert result.status in ["incompatível", "vermelho"]

@pytest.mark.asyncio
async def test_agent4_anti_vibe_null_protection():
    """Anti-vibe: Se banco tem nulo no campo exigido, trava o score e não chuta médio."""
    
    item = LicitItem(
        numero_item="04",
        descricao_original="Edital pede 300 kcal",
        requisitos=LicitItemRequisitos(
            kcal_min=300.0
        )
    )
    
    product = Product(
        id="33333333-3333-3333-3333-333333333333",
        slug="novo-produto",
        nome_comercial="Produto Cego",
        kcal_por_porcao=None,  # Produto sem cadastro completo
        ingredientes=Ingredientes(lista=[])
    )
    
    with patch("agents.agent4_compatibility.get_knowledge_items") as mock_kb:
        mock_kb.return_value = []
        
        result = await match_product(item, product)
        
        # Como o banco não tem a informação, não podemos aprovar nem reprovar sumariamente sem gap alert
        # O user disse: "travar o score e reportar o gap"
        assert result.score < 0.50  # Trava abaixo do limite de aprovação
        assert "gap" in result.justificativa_tecnica.lower()
