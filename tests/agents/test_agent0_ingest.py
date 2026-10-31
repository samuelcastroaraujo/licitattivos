import io
import zipfile
import fitz
import pytest
from agents.agent0_ingest import edital_de_conlicitacao, lances_do_dataset, pdf_do_arquivo
from agents.agent0_ingest import edital_de_apify, edital_de_pncp, objeto_relevante, sem_duplicados
from agents.intelligence import analisar_orgao, historico_produto

SNAPSHOT = {
    "clientes": [
        {"nome": "PREFEITURA MUNICIPAL DE MARILIA", "municipio": "Marília", "uf": "SP", "total": 100.0, "notas": 2, "ultima_compra": "2026-08-10", "vencido": 50.0},
        {"nome": "FUNDO MUNICIPAL DE SAUDE", "municipio": "Anápolis", "uf": "GO", "total": 80.0, "notas": 1, "ultima_compra": "2026-04-28", "vencido": 0},
    ],
    "produtos": [{"nome": "JUST VEETAL SENIOR 800G", "preco_medio": 63.9}, {"nome": "SOREND 25G", "preco_medio": 26.4}],
}


def test_filtra_objeto_ignorando_acentos():
    assert objeto_relevante("Aquisição de FÓRMULAS ENTERAIS e suplementos")
    assert objeto_relevante("Registro de preços de dietas")
    assert not objeto_relevante("Aquisição de pneus e material de limpeza")


def test_converte_pncp_usando_fim_das_propostas():
    edital = edital_de_pncp({
        "numeroCompra": "90021", "anoCompra": 2026,
        "orgaoEntidade": {"razaoSocial": "MUNICIPIO DE ANAPOLIS"},
        "unidadeOrgao": {"ufSigla": "GO"},
        "dataPublicacaoPncp": "2026-04-10T07:09:04",
        "dataAberturaProposta": "2026-10-23T08:00:00",
        "dataEncerramentoProposta": "2026-11-10T09:00:00",
    })
    assert edital.numero_pregao == "90021/2026"
    assert edital.uf == "GO"
    assert edital.data_abertura.day == 10


def test_apify_aceita_campos_diferentes_e_descarta_o_resto():
    bom = edital_de_apify({"buyer": "Hospital X", "number": "12", "description": "dieta enteral", "pdfUrl": "http://x/a.pdf"})
    assert bom.orgao == "Hospital X" and bom.anexo_url_origem == "http://x/a.pdf"
    assert edital_de_apify({"buyer": "Hospital X", "number": "12", "description": "cimento"}) is None
    assert edital_de_apify({"number": "12"}) is None


def test_sem_duplicados_para_o_upsert():
    a = edital_de_apify({"buyer": "H", "number": "1", "description": "dieta"})
    b = edital_de_apify({"buyer": "H", "number": "1", "description": "dieta"})
    assert len(sem_duplicados([a, b])) == 1


def test_inteligencia_alerta_cliente_com_vencido():
    r = analisar_orgao("Prefeitura Municipal de Marília", "SP", SNAPSHOT)
    assert r["cliente_existente"] and r["prioridade"] == "atencao"


def test_inteligencia_nome_generico_exige_municipio():
    assert analisar_orgao("Fundo Municipal de Saúde de Anápolis", "GO", SNAPSHOT)["cliente_existente"]
    assert not analisar_orgao("Fundo Municipal de Saúde de Goiânia", "GO", SNAPSHOT)["cliente_existente"]


def test_historico_de_preco_por_produto():
    assert historico_produto("Veetal Senior 50+", {"produtos": [{"nome": "JUST VEETAL SENIOR 50+ 800G"}]})
    assert historico_produto("Bella Fiber", SNAPSHOT) == []


def test_conlicitacao_converte_edital():
    edital = edital_de_conlicitacao({
        "id": 7, "edital": "PE/153/2026", "orgao_estado": "MG",
        "public_body": {"nome": "Prefeitura X"}, "datahora_prazo": "2026-11-05T12:30:00.000-03:00",
        "edicts": [{"url": "/boletim_web/edital.zip"}],
    })
    assert edital.numero_pregao == "PE/153/2026 #7" and edital.portal_origem == "conlicitacao"
    assert edital.anexo_url_origem.startswith("https://consultaonline.conlicitacao.com.br/")
    assert edital.data_abertura.day == 5


def test_sessao_vencida_avisa():
    with pytest.raises(RuntimeError, match="Sessão"):
        lances_do_dataset([{"data": {"error": "login"}, "status": 401}])


def _pdf(texto):
    documento = fitz.open()
    documento.new_page().insert_text((50, 50), texto)
    return documento.tobytes()


def test_junta_todos_os_pdfs_do_zip_em_ordem():
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as pacote:
        pacote.writestr("arquivo_10.pdf", _pdf("dez"))
        pacote.writestr("arquivo_2.pdf", _pdf("dois"))
        pacote.writestr("planilha.xlsx", "y")
    junto = fitz.open(stream=pdf_do_arquivo(memoria.getvalue()), filetype="pdf")
    assert [pagina.get_text().strip() for pagina in junto] == ["dois", "dez"]
    assert pdf_do_arquivo(b"%PDF-1") == b"%PDF-1"


def test_hospital_do_mesmo_municipio_nao_herda_historico():
    assert not analisar_orgao("Santa Casa de Marília", "SP", SNAPSHOT)["cliente_existente"]
