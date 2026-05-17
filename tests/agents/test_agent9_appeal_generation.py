"""
test_agent9_appeal_generation.py — Ciclo TDD do Agente 9 (Recursos Administrativos)

Regras testadas:
1. Assert Crítico: Documento gerado DEVE citar o Art. 59, §1º da Lei 14.133/21.
2. Status correto após geração: "pronto_para_revisao"
3. Teste de Qualidade: Retorna "contexto_insuficiente" se faltar data da sessão (Anti-Vibe).
4. Formatação de persona (advogado sênior).
5. O status global fica "aguardando_assinatura_juridica".
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend')))

from models.edital import Edital
from agents.agent9_appeals import gerar_recurso_administrativo, AppealResult

# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def edital_base():
    return Edital(
        id="123e4567-e89b-12d3-a456-426614174000",
        numero_pregao="00015/2026",
        orgao="Ministério da Saúde",
        portal_origem="comprasnet",
        status="em_disputa",
        licit_context={
            "empresa_nome": "Attivos Magisttrais",
            "data_sessao": "2026-05-11",
            "motivo_desclassificacao": "Ausência de Registro MS ativo",
            "argumento_defesa": "Produto é dispensado de registro pela RDC 27/2010"
        },
        created_at="2026-05-11T10:00:00Z"
    )

# ── Testes ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent9_geracao_recurso_sucesso(edital_base):
    """
    Cenário: Desclassificação indevida por Registro MS.
    O advogado digital DEVE fundamentar a defesa na Lei 14.133/21.
    """
    # Moca a geração real do DOCX para evitar I/O no teste unitário da lógica,
    # mas validamos os dados que o agente tentou escrever.
    with patch("agents.agent9_appeals._renderizar_docx") as mock_render:
        # Moca o LLM que "escreve" a fundamentação
        with patch("agents.agent9_appeals._gerar_fundamentacao_llm") as mock_llm:
            mock_llm.return_value = "Ato contínuo, a desclassificação fere o Art. 59, §1º da Lei 14.133/21, pois o produto possui dispensa de registro..."
            
            result = await gerar_recurso_administrativo(edital_base)
            
            # Valida Output da Fundamentação (Assert Crítico)
            assert "Art. 59" in result.texto_gerado
            assert "14.133" in result.texto_gerado
            assert result.status_geracao == "pronto_para_revisao"
            
            # Valida Anti-Vibe Rule: Trava do humano
            assert edital_base.status == "aguardando_assinatura_juridica"
            
            # Verifica se tentou renderizar
            mock_render.assert_called_once()


@pytest.mark.asyncio
async def test_agent9_falta_de_contexto(edital_base):
    """
    Cenário: LicitContext NÃO possui a data da sessão.
    Anti-Vibe: O agente NÃO pode inventar datas. Deve abortar.
    """
    # Remove o campo crítico
    del edital_base.licit_context["data_sessao"]
    
    result = await gerar_recurso_administrativo(edital_base)
    
    # Assert Crítico: deve parar tudo por falta de dados
    assert result.status_geracao == "contexto_insuficiente"
    assert result.texto_gerado == ""
    assert "data_sessao" in result.motivo_falha.lower()
    
    # O status do edital não muda para aguardando assinatura, 
    # fica bloqueado no passo anterior ou requer dados.
    assert edital_base.status == "em_disputa"
