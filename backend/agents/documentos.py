"""
Documentos do pregão no papel timbrado da empresa.

- Proposta comercial: cópia do modelo real (templates/privado/proposta_modelo.docx) com órgão, data
  e tabela de itens trocados. O timbrado é imagem no cabeçalho, então fica idêntico.
- Declarações: mesmo arquivo como base (cabeçalho/rodapé), corpo trocado pelo texto padronizado.
- PDF: convertido pelo Word quando ele existe na máquina (Windows). Sem Word, fica só o DOCX.
- Tudo vai para o bucket "documentos" do Supabase:
    documentos/pregoes/{edital_id}/...      gerados na aprovação
    documentos/estoque/{AAAA-MM-DD}/...     estoque renovado a cada 30 dias
"""
import asyncio
import copy
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.table import _Row
from docx.text.paragraph import Paragraph

from db.client import get_supabase_client

log = structlog.get_logger()

PASTA_PRIVADA = Path(__file__).resolve().parent.parent / "templates" / "privado"
MODELO = PASTA_PRIVADA / "proposta_modelo.docx"
EMPRESA = PASTA_PRIVADA / "empresa.json"
BUCKET = "documentos"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]
DIAS_ESTOQUE = 30
_word = threading.Lock()


# ── Dados básicos ──────────────────────────────────────────────────────────

def garantir_modelos() -> None:
    """
    Modelo da proposta e dados da empresa não vão para o Git (CPF, RG, banco).
    No servidor, vêm da pasta privada config/ do bucket "documentos" na primeira vez que forem usados.
    """
    faltando = [arquivo for arquivo in (MODELO, EMPRESA) if not arquivo.exists()]
    if not faltando:
        return
    armazem = get_supabase_client().storage.from_(BUCKET)
    PASTA_PRIVADA.mkdir(parents=True, exist_ok=True)
    for arquivo in faltando:
        try:
            arquivo.write_bytes(armazem.download(f"config/{arquivo.name}"))
            log.info("documentos.modelo_baixado", arquivo=arquivo.name)
        except Exception as erro:
            log.error("documentos.modelo_ausente", arquivo=arquivo.name, error=str(erro)[:200])


def empresa() -> dict[str, Any]:
    garantir_modelos()
    if not EMPRESA.exists():
        raise RuntimeError("Falta backend/templates/privado/empresa.json com os dados da empresa.")
    return json.loads(EMPRESA.read_text(encoding="utf-8"))


def data_extenso(quando: date, cidade: str) -> str:
    return f"{cidade}, {quando.day} de {MESES[quando.month - 1]} de {quando.year}."


def brl(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def nome_arquivo(texto: str) -> str:
    limpo = unicodedata.normalize("NFD", texto)
    limpo = "".join(c for c in limpo if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "_", limpo).strip("_").lower()[:80]


# ── Declarações padronizadas ───────────────────────────────────────────────
# {ref} = "no âmbito do Pregão nº X, promovido por Y" (pregão) ou texto genérico (estoque).
# "busca": como o edital costuma pedir; serve para marcar a declaração como exigida.

DECLARACOES: list[dict[str, str]] = [
    {
        "id": "habilitacao",
        "titulo": "DECLARAÇÃO DE CUMPRIMENTO DOS REQUISITOS DE HABILITAÇÃO",
        "busca": r"requisitos de habilitacao|cumpre (plenamente )?os requisitos|art\.? 63,? i\b",
        "texto": "{razao}, inscrita no CNPJ sob o nº {cnpj}, com sede em {endereco}, {cidade}/{uf}, por intermédio de sua representante legal, {responsavel}, {cargo}, portadora do RG nº {rg} e do CPF nº {cpf}, DECLARA, {ref}, que cumpre plenamente os requisitos de habilitação exigidos, nos termos do art. 63, inciso I, da Lei nº 14.133/2021, e que as informações e os documentos apresentados são verdadeiros, ciente das sanções previstas em lei.",
    },
    {
        "id": "fato_impeditivo",
        "titulo": "DECLARAÇÃO DE INEXISTÊNCIA DE FATO IMPEDITIVO",
        "busca": r"fato (superveniente|impeditivo)|inexistencia de fatos",
        "texto": "{razao}, inscrita no CNPJ sob o nº {cnpj}, por sua representante legal, DECLARA, {ref}, que até a presente data inexistem fatos impeditivos à sua habilitação e participação, e que está ciente da obrigatoriedade de comunicar a ocorrência de fatos supervenientes.",
    },
    {
        "id": "menor",
        "titulo": "DECLARAÇÃO DE NÃO EMPREGO DE MENOR",
        "busca": r"menor(es)? de (dezoito|18)|trabalho noturno,? perigoso|xxxiii do art\.? 7",
        "texto": "{razao}, inscrita no CNPJ sob o nº {cnpj}, por sua representante legal, DECLARA, {ref}, para fins do disposto no inciso VI do art. 68 da Lei nº 14.133/2021, que não emprega menor de 18 (dezoito) anos em trabalho noturno, perigoso ou insalubre e não emprega menor de 16 (dezesseis) anos, salvo na condição de aprendiz, a partir de 14 (quatorze) anos, conforme o inciso XXXIII do art. 7º da Constituição Federal.",
    },
    {
        "id": "proposta_independente",
        "titulo": "DECLARAÇÃO DE ELABORAÇÃO INDEPENDENTE DE PROPOSTA",
        "busca": r"elaboracao independente|proposta independente",
        "texto": "{razao}, inscrita no CNPJ sob o nº {cnpj}, por sua representante legal, DECLARA, {ref}, que a proposta apresentada foi elaborada de maneira independente, que seu conteúdo não foi, no todo ou em parte, informado, discutido ou recebido de qualquer outro participante ou potencial participante, e que não tentou, por qualquer meio, influir na decisão de outros participantes quanto a participar ou não do certame.",
    },
    {
        "id": "me_epp",
        "titulo": "DECLARAÇÃO DE ENQUADRAMENTO COMO MICROEMPRESA",
        "busca": r"microempresa|empresa de pequeno porte|me/epp|lei complementar n?.? ?123",
        "texto": "{razao}, inscrita no CNPJ sob o nº {cnpj}, por sua representante legal, DECLARA, {ref}, sob as penas da lei, que está enquadrada como {porte}, nos termos do art. 3º da Lei Complementar nº 123/2006, que não se enquadra em nenhuma das vedações do § 4º do mesmo artigo e que cumpre os requisitos legais para usufruir do tratamento diferenciado previsto nos arts. 42 a 49 da referida Lei e no art. 4º da Lei nº 14.133/2021.",
    },
    {
        "id": "reserva_cargos",
        "titulo": "DECLARAÇÃO DE RESERVA DE CARGOS PARA PESSOA COM DEFICIÊNCIA E REABILITADO",
        "busca": r"pessoa com deficiencia|reabilitado|reserva de cargos|art\.? 93 da lei n?.? ?8\.?213",
        "texto": "{razao}, inscrita no CNPJ sob o nº {cnpj}, por sua representante legal, DECLARA, {ref}, que cumpre as exigências de reserva de cargos para pessoa com deficiência e para reabilitado da Previdência Social previstas em lei e em outras normas específicas, nos termos do art. 63, inciso IV, da Lei nº 14.133/2021, quando aplicáveis ao seu quadro de empregados.",
    },
    {
        "id": "custos",
        "titulo": "DECLARAÇÃO DE QUE A PROPOSTA COMPREENDE A INTEGRALIDADE DOS CUSTOS",
        "busca": r"integralidade dos custos|custos (diretos|para atendimento)|art\.? 63,? ?§ ?1",
        "texto": "{razao}, inscrita no CNPJ sob o nº {cnpj}, por sua representante legal, DECLARA, {ref}, nos termos do § 1º do art. 63 da Lei nº 14.133/2021, que sua proposta econômica compreende a integralidade dos custos para atendimento dos direitos trabalhistas assegurados na Constituição Federal, nas leis trabalhistas, nas normas infralegais, nas convenções coletivas de trabalho e nos termos de ajustamento de conduta vigentes na data de entrega da proposta, bem como todos os tributos, fretes e demais despesas incidentes sobre o fornecimento.",
    },
    {
        "id": "trabalho_degradante",
        "titulo": "DECLARAÇÃO DE NÃO UTILIZAÇÃO DE TRABALHO DEGRADANTE OU FORÇADO",
        "busca": r"degradante|trabalho forcado|analog[ao] a de escravo",
        "texto": "{razao}, inscrita no CNPJ sob o nº {cnpj}, por sua representante legal, DECLARA, {ref}, que não possui, em sua cadeia produtiva, empregados executando trabalho degradante ou forçado, observando o disposto nos incisos III e IV do art. 1º e no inciso III do art. 5º da Constituição Federal.",
    },
    {
        "id": "nepotismo",
        "titulo": "DECLARAÇÃO DE INEXISTÊNCIA DE VÍNCULO COM AGENTES PÚBLICOS",
        "busca": r"nepotismo|parentesco|vinculo (de natureza )?(tecnica|comercial|economica|familiar)|art\.? 14,? (inciso )?iv",
        "texto": "{razao}, inscrita no CNPJ sob o nº {cnpj}, por sua representante legal, DECLARA, {ref}, que não possui, em seu quadro societário ou de empregados, dirigente ou agente público do órgão ou entidade contratante, nem pessoa que mantenha com eles vínculo de natureza técnica, comercial, econômica, financeira, trabalhista ou civil, ou que seja cônjuge, companheiro ou parente em linha reta, colateral ou por afinidade, até o terceiro grau, nos termos do art. 14, inciso IV, da Lei nº 14.133/2021.",
    },
    {
        "id": "idoneidade",
        "titulo": "DECLARAÇÃO DE IDONEIDADE",
        "busca": r"inidone|idoneidade|impedid[ao] de licitar",
        "texto": "{razao}, inscrita no CNPJ sob o nº {cnpj}, por sua representante legal, DECLARA, {ref}, que não foi declarada inidônea para licitar ou contratar com a Administração Pública, nem está impedida ou suspensa de licitar ou contratar, nos termos do art. 156 da Lei nº 14.133/2021, e que não incorre nas vedações do art. 14 da mesma Lei.",
    },
    {
        "id": "ciencia_edital",
        "titulo": "DECLARAÇÃO DE CIÊNCIA E CONCORDÂNCIA COM O EDITAL",
        "busca": r"ciencia|concord(a|ancia) com (as condicoes|os termos)|conhece e aceita",
        "texto": "{razao}, inscrita no CNPJ sob o nº {cnpj}, por sua representante legal, DECLARA, {ref}, que tomou conhecimento de todas as informações e condições do instrumento convocatório e de seus anexos, que concorda integralmente com elas e que está apta a cumprir todas as obrigações decorrentes da contratação.",
    },
    {
        "id": "produto_validade",
        "titulo": "DECLARAÇÃO DE COMPROMISSO DE ENTREGA E VALIDADE DOS PRODUTOS",
        "busca": r"validade (minima|nao inferior|de no minimo)|prazo de validade|produtos? nov[oa]s?",
        "texto": "{razao}, inscrita no CNPJ sob o nº {cnpj}, por sua representante legal, DECLARA, {ref}, que os produtos ofertados serão entregues novos, sem uso, em embalagens originais e invioladas, rotulados conforme a legislação sanitária vigente, com prazo de validade compatível com o exigido no instrumento convocatório, e que substituirá, às suas expensas, qualquer produto em desacordo com as especificações.",
    },
]


def _sem_acento(texto: str) -> str:
    limpo = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in limpo if unicodedata.category(c) != "Mn").lower()


def declaracoes_exigidas(raw_text: str, pedidas: list[str] | None = None) -> tuple[list[str], list[str]]:
    """IDs das declarações padrão pedidas no edital e as pedidas que não têm modelo padrão."""
    texto = _sem_acento(raw_text)
    ids = [d["id"] for d in DECLARACOES if re.search(d["busca"], texto)]
    sem_modelo = []
    for pedida in pedidas or []:
        alvo = _sem_acento(pedida)
        achou = next((d["id"] for d in DECLARACOES if re.search(d["busca"], alvo) or _sem_acento(d["titulo"])[13:40] in alvo), None)
        if achou:
            if achou not in ids:
                ids.append(achou)
        else:
            sem_modelo.append(pedida)
    return ids, sem_modelo


# ── Montagem dos DOCX ──────────────────────────────────────────────────────

def _texto(paragrafo: Paragraph, texto: str) -> None:
    """Troca o texto mantendo a formatação do trecho principal (o de mais texto, não a quebra de linha)."""
    runs = paragrafo.runs
    if not runs:
        paragrafo.add_run(texto)
        return
    base = max(runs, key=lambda r: len(r.text.strip()))
    base.text = texto
    for run in runs:
        if run is not base:
            run._r.getparent().remove(run._r)


def _linhas_na_celula(celula, linhas: list[str]) -> None:
    paragrafos = celula.paragraphs
    base = paragrafos[0]
    for extra in paragrafos[1:]:
        extra._p.getparent().remove(extra._p)
    _texto(base, linhas[0] if linhas else "")
    anterior = base._p
    for linha in linhas[1:]:
        novo = copy.deepcopy(base._p)
        anterior.addnext(novo)
        _texto(Paragraph(novo, base._parent), linha)
        anterior = novo


def _achar(doc, comeco: str) -> Paragraph:
    for p in doc.paragraphs:
        if p.text.strip().startswith(comeco):
            return p
    raise RuntimeError(f"Modelo da proposta mudou: não achei o parágrafo '{comeco}'.")


def _salvar(doc) -> bytes:
    saida = io.BytesIO()
    doc.save(saida)
    return saida.getvalue()


def gerar_proposta(edital: dict, itens: list[dict], quando: date | None = None, resumo: dict | None = None,
                   objeto: str | None = None, cidade: str | None = None) -> bytes:
    """
    itens: [{numero_item, descricao, produto, registro_anvisa, quantidade, preco_unitario}].
    Opcionais por item (proposta avulsa, outro ramo): "fabricante" e "mostrar_anvisa" (False tira a linha ANVISA).
    """
    if not itens:
        raise ValueError("Nenhum item para ofertar na proposta.")
    # No servidor o modelo não vem no deploy: busca no Supabase antes de checar.
    garantir_modelos()
    if not MODELO.exists():
        raise RuntimeError("Falta o modelo backend/templates/privado/proposta_modelo.docx.")
    dados = empresa()
    quando = quando or date.today()
    doc = Document(str(MODELO))

    _texto(_achar(doc, "Anápolis,"), data_extenso(quando, cidade or dados["cidade"]))
    if objeto:
        frase = _achar(doc, "Apresentamos a nossa proposta")
        _texto(frase, frase.text.replace("Nutrição Especializada", objeto.strip()))
    processo = (resumo or {}).get("numero_processo")
    numero = (edital.get("numero_pregao") or "").split(" #")[0].strip()
    cabecalho = edital["orgao"].upper() + (f" – PREGÃO {numero}" if numero else "")
    if processo:
        cabecalho += f" – PROCESSO {processo}"
    _texto(_achar(doc, "FUNDO MUNICIPAL"), "\n" + cabecalho)
    validade = int((resumo or {}).get("validade_proposta_dias") or 0)
    if validade > int(dados.get("validade_proposta_dias", 120)):
        # Edital pede validade maior que a padrão: a proposta acompanha o edital.
        corpo = _achar(doc, "Nos preços indicados")
        _texto(corpo, corpo.text.replace("120 dias corridos", f"{validade} dias corridos"))

    tabela = doc.tables[0]
    modelo_linha = tabela.rows[1]
    total = 0.0
    for item in itens:
        tr = copy.deepcopy(modelo_linha._tr)
        modelo_linha._tr.addprevious(tr)
        linha = _Row(tr, tabela)
        quantidade = float(item["quantidade"])
        unitario = float(item["preco_unitario"])
        subtotal = round(quantidade * unitario, 2)
        total += subtotal
        registro = item.get("registro_anvisa") or "(preencher)"
        marca = [item["produto"].upper()]
        if item.get("mostrar_anvisa", True):
            marca += ["", "ANVISA:", str(registro)]
        valores = [
            [str(item["numero_item"])],
            [item["descricao"].upper()],
            [(item.get("fabricante") or dados.get("fabricante_proposta", "ATTIVOS MAGISTRAIS - PHOLIAS")).upper()],
            marca,
            [f"{quantidade:g}".replace(".", ",")],
            [brl(unitario)],
            [brl(subtotal)],
        ]
        for celula, linhas in zip(linha.cells, valores):
            _linhas_na_celula(celula, linhas)
    modelo_linha._tr.getparent().remove(modelo_linha._tr)

    rodape = tabela.rows[-1].cells
    _linhas_na_celula(rodape[-2], ["TOTAL"])
    _linhas_na_celula(rodape[-1], [brl(total)])
    for celula in rodape[-2:]:
        celula.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for run in celula.paragraphs[0].runs:
            run.bold = True
    return _salvar(doc)


def _documento_timbrado():
    """O modelo da proposta sem o corpo: sobra a página com cabeçalho e rodapé do timbrado."""
    doc = Document(str(MODELO))
    estilos = {
        "titulo": copy.deepcopy(_achar(doc, "PROPOSTA COMERCIAL")._p),
        "data": copy.deepcopy(_achar(doc, "Anápolis,")._p),
        "orgao": copy.deepcopy(_achar(doc, "FUNDO MUNICIPAL")._p),
        "corpo": copy.deepcopy(_achar(doc, "A proponente declara")._p),
    }
    corpo = doc.element.body
    for filho in list(corpo):
        if filho.tag != qn("w:sectPr"):
            corpo.remove(filho)
    return doc, estilos


def _par(doc, estilos: dict, tipo: str, texto: str, alinhamento=None) -> Paragraph:
    elemento = copy.deepcopy(estilos[tipo])
    doc.element.body.insert(len(doc.element.body) - 1, elemento)  # antes do sectPr
    paragrafo = Paragraph(elemento, doc._body)
    _texto(paragrafo, texto)
    if alinhamento is not None:
        paragrafo.alignment = alinhamento
    return paragrafo


def gerar_declaracao(decl_id: str, edital: dict | None = None, quando: date | None = None) -> bytes:
    decl = next((d for d in DECLARACOES if d["id"] == decl_id), None)
    if not decl:
        raise ValueError(f"Declaração desconhecida: {decl_id}.")
    garantir_modelos()
    if not MODELO.exists():
        raise RuntimeError("Falta o modelo backend/templates/privado/proposta_modelo.docx.")
    dados = empresa()
    quando = quando or date.today()
    if edital:
        numero = edital["numero_pregao"].split(" #")[0]
        ref = f"para fins de participação no Pregão nº {numero}, promovido por {edital['orgao']}"
        destino = f"\nAo(À) Pregoeiro(a) – {edital['orgao'].upper()} – PREGÃO {numero}"
    else:
        ref = "para fins de participação em procedimentos licitatórios e contratações com a Administração Pública"
        destino = "\nAo(À) Agente de Contratação / Pregoeiro(a)"
    texto = decl["texto"].format(
        razao=dados["razao_social"], cnpj=dados["cnpj"], endereco=dados["endereco"], cidade=dados["cidade"],
        uf=dados["uf"], responsavel=dados["responsavel"], cargo=dados["cargo"], rg=dados["rg"], cpf=dados["cpf"],
        porte=dados.get("porte", "Microempresa (ME)"), ref=ref,
    )
    doc, estilos = _documento_timbrado()
    _par(doc, estilos, "titulo", decl["titulo"])
    _par(doc, estilos, "orgao", destino)
    _par(doc, estilos, "corpo", texto).paragraph_format.space_before = Pt(12)
    _par(doc, estilos, "corpo", "Por ser expressão da verdade, firma a presente.").paragraph_format.space_before = Pt(10)
    _par(doc, estilos, "data", data_extenso(quando, dados["cidade"])).paragraph_format.space_before = Pt(18)
    _par(doc, estilos, "corpo", "\n\n_______________________________________________", WD_ALIGN_PARAGRAPH.CENTER).paragraph_format.space_before = Pt(24)
    _par(doc, estilos, "corpo", f"{dados['responsavel']}\n{dados['cargo']} – CPF {dados['cpf']}\n{dados['razao_social']}\nCNPJ {dados['cnpj']}",
         WD_ALIGN_PARAGRAPH.CENTER)
    return _salvar(doc)


# ── PDF pelo Word ──────────────────────────────────────────────────────────

def _converter_libreoffice(arquivos: dict[str, bytes]) -> dict[str, bytes]:
    """Servidor Linux (Railway): LibreOffice sem tela converte todos de uma vez."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        log.warning("documentos.sem_conversor_pdf")
        return {}
    with _word, tempfile.TemporaryDirectory() as pasta:
        caminhos = []
        for nome, conteudo in arquivos.items():
            caminho = Path(pasta, f"{nome}.docx")
            caminho.write_bytes(conteudo)
            caminhos.append(str(caminho))
        try:
            subprocess.run([soffice, "--headless", "--norestore", f"-env:UserInstallation=file://{pasta}/perfil",
                            "--convert-to", "pdf", "--outdir", pasta, *caminhos],
                           check=True, capture_output=True, timeout=600)
        except (subprocess.SubprocessError, OSError) as erro:
            log.warning("documentos.pdf_falhou", error=str(erro)[:300])
            return {}
        return {nome: Path(pasta, f"{nome}.pdf").read_bytes() for nome in arquivos if Path(pasta, f"{nome}.pdf").exists()}


def converter_para_pdf(arquivos: dict[str, bytes]) -> dict[str, bytes]:
    """Converte vários DOCX de uma vez: Word no Windows, LibreOffice no servidor."""
    if not arquivos:
        return {}
    if os.name != "nt":
        return _converter_libreoffice(arquivos)
    with _word, tempfile.TemporaryDirectory() as pasta:
        for nome, conteudo in arquivos.items():
            Path(pasta, f"{nome}.docx").write_bytes(conteudo)
        script = (
            "$ErrorActionPreference='Stop';$w=New-Object -ComObject Word.Application;$w.Visible=$false;"
            f"Get-ChildItem -LiteralPath '{pasta}' -Filter *.docx | ForEach-Object {{"
            "$d=$w.Documents.Open($_.FullName,$false,$true);"
            "$d.SaveAs2([IO.Path]::ChangeExtension($_.FullName,'pdf'),17);$d.Close($false)};$w.Quit()"
        )
        try:
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           check=True, capture_output=True, timeout=600)
        except (subprocess.SubprocessError, OSError) as erro:
            log.warning("documentos.pdf_falhou", error=str(erro)[:300])
            return {}
        return {nome: Path(pasta, f"{nome}.pdf").read_bytes() for nome in arquivos if Path(pasta, f"{nome}.pdf").exists()}


# ── Armazenamento ──────────────────────────────────────────────────────────

def _enviar(client, caminho: str, conteudo: bytes, tipo: str) -> None:
    client.storage.from_(BUCKET).upload(caminho, conteudo, {"content-type": tipo, "upsert": "true"})


def _publicar(client, pasta: str, docx: dict[str, bytes], titulos: dict[str, str]) -> list[dict]:
    pdfs = converter_para_pdf(docx)
    arquivos = []
    for nome, conteudo in docx.items():
        _enviar(client, f"{pasta}/{nome}.docx", conteudo, DOCX)
        registro = {"nome": nome, "titulo": titulos.get(nome, nome), "docx": f"{pasta}/{nome}.docx", "pdf": None}
        if nome in pdfs:
            _enviar(client, f"{pasta}/{nome}.pdf", pdfs[nome], "application/pdf")
            registro["pdf"] = f"{pasta}/{nome}.pdf"
        arquivos.append(registro)
    return arquivos


def publicar_modelos() -> list[str]:
    """Sobe o modelo da proposta e os dados da empresa para a pasta privada (usado antes do deploy)."""
    client = get_supabase_client()
    enviados = []
    for arquivo, tipo in ((MODELO, DOCX), (EMPRESA, "application/json")):
        if arquivo.exists():
            _enviar(client, f"config/{arquivo.name}", arquivo.read_bytes(), tipo)
            enviados.append(arquivo.name)
    return enviados


def baixar(caminho: str) -> bytes:
    if not caminho.startswith(("pregoes/", "estoque/", "avulsas/")) or ".." in caminho:
        raise ValueError("Caminho inválido.")
    return get_supabase_client().storage.from_(BUCKET).download(caminho)


# ── Fluxos ─────────────────────────────────────────────────────────────────

def itens_da_proposta(client, edital_id: str, escolhas: list[dict]) -> list[dict]:
    """Junta o que o analista escolheu na aprovação (preço/quantidade) com item e produto do banco."""
    linhas = client.table("licit_items").select("id,numero_item,descricao_original,produto_id,requisitos").eq("edital_id", edital_id).execute().data
    por_id = {linha["id"]: linha for linha in linhas}
    produtos_ids = list({linha["produto_id"] for linha in linhas if linha.get("produto_id")})
    produtos = {}
    if produtos_ids:
        produtos = {p["id"]: p for p in client.table("products").select("id,nome_comercial,registro_anvisa").in_("id", produtos_ids).execute().data}
    from agents.precos import precificar_edital
    try:
        skus = (precificar_edital(client, edital_id) or {}).get("por_item", {})
    except Exception:
        skus = {}
    itens = []
    for escolha in escolhas:
        linha = por_id.get(escolha.get("item_id"))
        if not linha or not linha.get("produto_id") or not escolha.get("incluir", True):
            continue
        produto = produtos.get(linha["produto_id"], {})
        itens.append({
            "numero_item": linha["numero_item"],
            "descricao": linha.get("descricao_original") or "",
            # Na proposta vai a apresentação real (ex.: JUST WHEY ISOLADO PT 250G), como no modelo.
            "produto": (skus.get(linha["id"]) or {}).get("sku") or produto.get("nome_comercial", ""),
            "registro_anvisa": produto.get("registro_anvisa"),
            "quantidade": escolha["quantidade"],
            "preco_unitario": escolha["preco_unitario"],
        })
    return sorted(itens, key=lambda i: [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", str(i["numero_item"]))])


async def gerar_documentos_do_edital(edital_id: str) -> dict:
    """Roda depois da aprovação: proposta + declarações do pregão. Resultado fica no licit_context."""
    client = get_supabase_client()
    linha = client.table("editais").select("id,numero_pregao,orgao,uf,licit_context,raw_text").eq("id", edital_id).single().execute().data
    contexto = linha.get("licit_context") or {}
    resumo = contexto.get("resumo") or {}
    quando = date.today()
    pasta = f"pregoes/{edital_id}"

    def montar() -> dict:
        docx: dict[str, bytes] = {}
        titulos: dict[str, str] = {}
        avisos: list[str] = []
        escolhas = (contexto.get("aprovacao") or {}).get("proposta") or []
        itens = itens_da_proposta(client, edital_id, escolhas)
        if itens:
            docx["01_proposta_comercial"] = gerar_proposta(linha, itens, quando, resumo)
            titulos["01_proposta_comercial"] = "Proposta comercial"
        else:
            avisos.append("Proposta não gerada: nenhum item com produto, preço e quantidade na aprovação.")
        ids, sem_modelo = declaracoes_exigidas(linha.get("raw_text") or "", resumo.get("declaracoes_exigidas"))
        # O núcleo da Lei 14.133 vai sempre; o resto, quando o edital pede.
        nucleo = ["habilitacao", "fato_impeditivo", "menor", "proposta_independente", "me_epp", "reserva_cargos", "custos"]
        for i, decl_id in enumerate(dict.fromkeys(nucleo + ids), start=2):
            decl = next(d for d in DECLARACOES if d["id"] == decl_id)
            nome = f"{i:02d}_declaracao_{decl_id}"
            docx[nome] = gerar_declaracao(decl_id, linha, quando)
            titulos[nome] = decl["titulo"]
        if sem_modelo:
            avisos.append("Declarações pedidas no edital sem modelo padrão (fazer à mão): " + "; ".join(sem_modelo))
        arquivos = _publicar(client, pasta, docx, titulos)
        if arquivos and not any(a["pdf"] for a in arquivos):
            avisos.append("PDF não gerado (Word indisponível neste servidor). Os DOCX estão prontos.")
        return {"arquivos": arquivos, "avisos": avisos}

    contexto["documentos"] = {"status": "gerando", "inicio": datetime.now(timezone.utc).isoformat()}
    client.table("editais").update({"licit_context": contexto}).eq("id", edital_id).execute()
    try:
        resultado = await asyncio.to_thread(montar)
        contexto["documentos"] = {"status": "pronto", "gerado_em": datetime.now(timezone.utc).isoformat(), **resultado}
        log.info("documentos.pregao_gerados", edital_id=edital_id, arquivos=len(resultado["arquivos"]))
    except Exception as erro:
        log.error("documentos.pregao_falhou", edital_id=edital_id, error=str(erro))
        contexto["documentos"] = {"status": "erro", "erro": str(erro)[:400]}
    client.table("editais").update({"licit_context": contexto}).eq("id", edital_id).execute()
    return contexto["documentos"]


def listar_estoque() -> list[dict]:
    """Lotes do estoque, do mais novo para o mais antigo, com os arquivos de cada um."""
    armazem = get_supabase_client().storage.from_(BUCKET)
    lotes = []
    for pasta in armazem.list("estoque", {"limit": 1000}) or []:
        nome = pasta.get("name", "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", nome):
            continue
        arquivos = [f["name"] for f in armazem.list(f"estoque/{nome}", {"limit": 1000}) or [] if f.get("name")]
        bases = sorted({a.rsplit(".", 1)[0] for a in arquivos})
        lotes.append({
            "data": nome,
            "arquivos": [
                {
                    "nome": base,
                    "titulo": next((d["titulo"] for d in DECLARACOES if base.endswith(d["id"])), base),
                    "docx": f"estoque/{nome}/{base}.docx" if f"{base}.docx" in arquivos else None,
                    "pdf": f"estoque/{nome}/{base}.pdf" if f"{base}.pdf" in arquivos else None,
                }
                for base in bases
            ],
        })
    return sorted(lotes, key=lambda lote: lote["data"], reverse=True)


async def gerar_estoque(forcar: bool = False) -> dict:
    """Lote de todas as declarações padrão, sem pregão, renovado a cada 30 dias."""
    hoje = date.today()
    lotes = await asyncio.to_thread(listar_estoque)
    if lotes and not forcar:
        ultimo = date.fromisoformat(lotes[0]["data"])
        if (hoje - ultimo).days < DIAS_ESTOQUE:
            return {"gerado": False, "ultimo": lotes[0]["data"], "proximo_em_dias": DIAS_ESTOQUE - (hoje - ultimo).days}

    def montar() -> list[dict]:
        docx = {f"{i:02d}_{d['id']}": gerar_declaracao(d["id"], None, hoje) for i, d in enumerate(DECLARACOES, start=1)}
        titulos = {f"{i:02d}_{d['id']}": d["titulo"] for i, d in enumerate(DECLARACOES, start=1)}
        return _publicar(get_supabase_client(), f"estoque/{hoje.isoformat()}", docx, titulos)

    arquivos = await asyncio.to_thread(montar)
    log.info("documentos.estoque_gerado", data=hoje.isoformat(), arquivos=len(arquivos))
    return {"gerado": True, "data": hoje.isoformat(), "arquivos": len(arquivos)}


# ── Proposta avulsa (qualquer ramo, digitada no painel) ────────────────────

def gerar_proposta_avulsa(dados: dict) -> dict:
    """
    dados: {orgao, pregao, processo?, objeto?, cidade?, data? (AAAA-MM-DD), validade_dias?,
            itens: [{item, descricao, fabricante?, marca, registro?, quantidade, valor_unitario}]}.
    Gera DOCX (e PDF quando há Word), guarda em avulsas/ com os dados para consulta depois.
    """
    quando = date.fromisoformat(dados["data"]) if dados.get("data") else date.today()
    itens = [{
        "numero_item": i["item"],
        "descricao": i["descricao"],
        "produto": i["marca"],
        "fabricante": i.get("fabricante"),
        "registro_anvisa": i.get("registro"),
        "mostrar_anvisa": bool((i.get("registro") or "").strip()),
        "quantidade": i["quantidade"],
        "preco_unitario": i["valor_unitario"],
    } for i in dados["itens"]]
    resumo = {"numero_processo": dados.get("processo"), "validade_proposta_dias": dados.get("validade_dias")}
    conteudo = gerar_proposta({"orgao": dados["orgao"], "numero_pregao": dados.get("pregao") or ""}, itens, quando, resumo,
                              objeto=dados.get("objeto"), cidade=dados.get("cidade"))
    carimbo = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d_%H%M%S")
    pasta = f"avulsas/{carimbo}_{nome_arquivo(dados['orgao'])[:40]}"
    client = get_supabase_client()
    arquivos = _publicar(client, pasta, {"proposta_comercial": conteudo}, {"proposta_comercial": "Proposta comercial"})
    total = round(sum(float(i["quantidade"]) * float(i["valor_unitario"]) for i in dados["itens"]), 2)
    registro = {"pasta": pasta, "criado_em": datetime.now(timezone.utc).isoformat(), "total": total, "dados": dados, "arquivo": arquivos[0]}
    _enviar(client, f"{pasta}/dados.json", json.dumps(registro, ensure_ascii=False).encode("utf-8"), "application/json")
    log.info("documentos.proposta_avulsa", pasta=pasta, itens=len(itens), total=total)
    return registro


def listar_avulsas(limite: int = 100) -> list[dict]:
    armazem = get_supabase_client().storage.from_(BUCKET)
    pastas = sorted((p["name"] for p in armazem.list("avulsas", {"limit": 1000}) or [] if p.get("name")), reverse=True)[:limite]
    registros = []
    for pasta in pastas:
        try:
            registros.append(json.loads(armazem.download(f"avulsas/{pasta}/dados.json")))
        except Exception as erro:
            log.warning("documentos.avulsa_sem_dados", pasta=pasta, error=str(erro)[:120])
    return registros
