"""
Agente 4 — Motor de Compatibilidade (As 5 Camadas)
"""
import re
import unicodedata

import structlog
from pydantic import BaseModel
from models.edital import LicitItem
from models.product import Product
from agents.learning import SIMILARIDADE_BLOQUEIO, SIMILARIDADE_LIBERACAO

log = structlog.get_logger()

# Regra aprendida nas extensões de cotação: material e medicamento nunca são produto nosso.
NAO_E_PRODUTO = re.compile(
    r"\b(soro fisiologico|soro glicosado|soro ringer|reidrat\w*|sonda|equipo|seringa|fixador|bomba de infusao"
    r"|hemodialise|albumina humana|injetavel|ampola|leite uht|creme de leite|iogurte|biscoito|cafe soluvel)s?\b"
)
# Família pedida no item → produtos da família. A primeira que casar vence, do mais específico ao mais geral.
FAMILIAS: tuple[tuple[str, str, str], ...] = (
    ("espessante", r"espessa", r"liqthick"),
    ("glutamina", r"glutamin", r"glutamina"),
    ("creatina", r"creatin", r"creatina"),
    ("carboidrato", r"maltodextrin|modulo de carboidrato", r"maltodextrina"),
    ("fibras", r"modulo de fibra|fibras? soluve|mix de fibra|prebiotic", r"fibra|fiber"),
    ("módulo de proteína", r"modulo de proteina|modulo proteico|whey|proteina (isolada|concentrada|hidrolisada|do soro)", r"whey"),
    ("cicatrização", r"cicatriz|lesao por pressao|lesoes por pressao|escara", r"sorend"),
    ("arginina", r"arginin", r"arginina|sorend"),
    ("controle glicêmico", r"diabet|glicemi", r"glicontrol"),
    ("idoso", r"idoso|senior|sarcopeni", r"senior"),
    ("pediátrico", r"pediatric|crianca", r"kids|infant"),
    ("lactente", r"lactente|primeiro semestre|formula infantil", r"(?!)"),
    ("fórmula enteral completa", r"(dieta|formula).{0,60}(enteral|polimeric|sistema fechado|normocalor|hipercalor)", r"(?!)"),
)
# Catálogo oficial do CLAUDE.md. O cadastro do banco ainda diverge e não basta para aprovar.
REGISTRO_MS_CONFIRMADO = re.compile(r"just[-_]whey[-_]protein[-_](isolado|concentrado)$")
ENTERAL_CONFIRMADO = re.compile(r"just[-_]whey[-_]protein[-_](isolado|concentrado)$|sorend($|[-_](baunilha|sem))")


def _sem_acento(texto: str) -> str:
    limpo = unicodedata.normalize("NFD", texto or "")
    return " ".join("".join(c for c in limpo if unicodedata.category(c) != "Mn").lower().split())


def _avaliar_familia(descricao: str, produto: Product) -> tuple[float, str | None]:
    """Sem isto, item sem requisito numérico aprovava qualquer produto do catálogo."""
    texto = _sem_acento(descricao)
    if NAO_E_PRODUTO.search(texto):
        return 0.0, "Incompatível: item é material ou medicamento, não produto do catálogo."
    alvo = _sem_acento(f"{produto.slug} {produto.nome_comercial}")
    for nome, pedido, oferta in FAMILIAS:
        if re.search(pedido, texto):
            if re.search(oferta, alvo):
                return 1.0, None
            return 0.10, f"Incompatível: item pede {nome}; produto é de outra família."
    return 0.50, "Sem correspondência segura entre o item e o produto: decisão do analista."


class ScoreResult(BaseModel):
    score: float
    status: str
    justificativa_tecnica: str

async def get_knowledge_items(query: str) -> list[dict]:
    """Fora do pipeline não há conhecimento carregado; o orquestrador passa a lista pronta."""
    return []

def _normalize_string(s: str) -> str:
    if not s:
        return ""
    return " ".join(s.lower().split())


def _mesmo_produto(kb: dict, product: Product) -> bool:
    return str(kb.get("produto_id") or "") == str(product.id)


def _aprendizado(conhecimento: list[dict], product: Product) -> tuple[dict | None, dict | None]:
    """(bloqueio, liberação) vindos do analista para este produto em descritivo parecido."""
    bloqueio = liberacao = None
    for kb in conhecimento:
        # Sem "similaridade", o item já chegou filtrado para este descritivo (formato antigo de regra).
        sim = kb.get("similaridade", 1.0)
        if kb.get("tipo") == "dica_usuario":
            continue
        reprovado = kb.get("resultado") == "incompativel" or kb.get("decisao") == "reprovado"
        # Sem produto no bloqueio = "nenhum produto do catálogo atende".
        if reprovado and sim >= SIMILARIDADE_BLOQUEIO and (not kb.get("produto_id") or _mesmo_produto(kb, product)):
            bloqueio = bloqueio or kb
        if kb.get("resultado") == "compativel" and sim >= SIMILARIDADE_LIBERACAO and _mesmo_produto(kb, product):
            liberacao = liberacao or kb
    return bloqueio, liberacao


async def match_product(item: LicitItem, product: Product, conhecimento: list[dict] | None = None) -> ScoreResult:
    """
    Duas réguas: `duro` (falhas que nenhum aprendizado desfaz) e `mole` (dúvidas de leitura:
    família incerta, ingrediente que a IA não achou no cadastro). Confirmação do analista em
    descritivo quase igual tira só a régua mole. Reprovação do analista zera o produto.
    """
    duras: list[str] = []
    moles: list[str] = []
    duro = 1.0
    mole = 1.0

    # Camada 0: Orientação por Histórico
    kb_items = conhecimento if conhecimento is not None else await get_knowledge_items(
        f"{item.descricao_original} {product.nome_comercial}"
    )
    bloqueio, liberacao = _aprendizado(kb_items, product)
    if bloqueio:
        log.info("agent4.aprendizado_bloqueou", product=product.slug, kb=bloqueio.get("id"))
        motivo = bloqueio.get("conteudo") or bloqueio.get("motivo") or "sem observação"
        parecido = round((bloqueio.get("similaridade") or 1) * 100)
        return ScoreResult(
            score=0.0,
            status="vermelho",
            justificativa_tecnica=f"Aprendizado: o analista marcou como incompatível em descritivo semelhante "
            f"({parecido}% parecido). Motivo: {motivo}",
        )

    reqs = item.requisitos
    texto = _sem_acento(item.descricao_original)

    if NAO_E_PRODUTO.search(texto):
        duro = 0.0
        duras.append("Incompatível: item é material ou medicamento, não produto do catálogo.")
    else:
        nota_familia, motivo_familia = _avaliar_familia(item.descricao_original, product)
        mole = min(mole, nota_familia)
        if motivo_familia:
            moles.append(motivo_familia)
    if re.search(r"(por|/|em)\s*100\s*(g|ml)", texto) and (reqs.proteina_min_g or reqs.kcal_min):
        duro = min(duro, 0.85)
        duras.append("Ressalva: valor do edital por 100 g/ml; o cadastro é por porção. Conferir a conversão.")

    # Filtros eliminatórios: qualquer falha impede a recomendação.
    ingredientes_produto = {_normalize_string(i.nome_normalizado) for i in product.ingredientes.lista}
    for proibido in reqs.ingredientes_proibidos:
        if _normalize_string(proibido) in ingredientes_produto:
            duro = 0.0
            duras.append(f"Eliminatório: contém ingrediente proibido ({proibido}).")
    restricoes = (
        (reqs.sem_gluten, product.sem_gluten, "sem glúten"),
        (reqs.sem_lactose, product.sem_lactose, "sem lactose"),
        (reqs.sem_sacarose, product.sem_sacarose, "sem sacarose"),
    )
    for exigido, atende, nome in restricoes:
        if exigido and not atende:
            duro = min(duro, 0.10)
            duras.append(f"Incompatível ou sem comprovação: edital exige {nome}.")
    if reqs.faixa_etaria_min_anos is not None and product.faixa_etaria_max_anos is not None \
            and product.faixa_etaria_max_anos < reqs.faixa_etaria_min_anos:
        duro = 0.0
        duras.append("Eliminatório: faixa etária do produto fora da exigida.")
    if reqs.faixa_etaria_max_anos is not None and product.faixa_etaria_min_anos is not None \
            and product.faixa_etaria_min_anos > reqs.faixa_etaria_max_anos:
        duro = 0.0
        duras.append("Eliminatório: faixa etária do produto fora da exigida.")

    # Camada 1: Thresholds Matemáticos e Gaps
    if reqs.proteina_min_g is not None:
        if product.proteinas_por_porcao_g is None:
            duro = min(duro, 0.40)  # Trava o score, gap de info
            duras.append("GAP de informação: produto não possui valor de proteína cadastrado.")
        elif product.proteinas_por_porcao_g < reqs.proteina_min_g:
            duro = min(duro, 0.10)
            duras.append(f"Incompatível: Edital pede {reqs.proteina_min_g}g de proteína, produto tem {product.proteinas_por_porcao_g}g.")
    if reqs.kcal_min is not None:
        if product.kcal_por_porcao is None:
            duro = min(duro, 0.40)
            duras.append("GAP de informação: produto não possui kcal cadastrada.")
        elif product.kcal_por_porcao < reqs.kcal_min:
            duro = min(duro, 0.10)
            duras.append(f"Incompatível: Edital pede {reqs.kcal_min} kcal, produto tem {product.kcal_por_porcao}.")

    # Camada 2: Ingredientes (Busca Exata normalizada)
    if reqs.ingredientes_obrigatorios:
        prod_ings = [_normalize_string(ing.nome_normalizado) for ing in product.ingredientes.lista]
        for req_ing in reqs.ingredientes_obrigatorios:
            if _normalize_string(req_ing) not in prod_ings:
                mole = min(mole, 0.50)
                moles.append(f"Ingrediente obrigatório faltante: {req_ing}.")

    # Camada 3: Regulatório. Exigência expressa é eliminatória.
    if reqs.registro_anvisa_obrigatorio and not (product.tem_registro_ms and REGISTRO_MS_CONFIRMADO.search(product.slug)):
        duro = min(duro, 0.10)
        duras.append("Incompatível: edital exige Registro MS e o registro do produto não está confirmado no catálogo. Avaliar esclarecimento ou impugnação.")

    # Camada 4: Clínico (Via Enteral)
    if reqs.via_enteral_obrigatoria and not (product.via_enteral and ENTERAL_CONFIRMADO.search(product.slug)):
        duro = min(duro, 0.10)
        duras.append("Incompatível: via enteral não confirmada para o produto.")

    if liberacao and moles:
        # A confirmação do analista resolve só as dúvidas de leitura; falha dura continua valendo.
        log.info("agent4.aprendizado_liberou", product=product.slug, kb=liberacao.get("id"))
        parecido = round((liberacao.get("similaridade") or 1) * 100)
        moles = [f"Aprendizado: o analista confirmou este produto em descritivo semelhante ({parecido}% parecido)."]
        mole = 1.0

    score = min(duro, mole)
    justificativas = duras + moles

    # Definição do status baseado no score (Traffic Light)
    if score >= 0.90:
        status = "verde"
    elif score >= 0.70:
        status = "amarelo"
    else:
        status = "vermelho"

    final_justification = " ".join(justificativas) if justificativas else "Aprovado sem ressalvas."

    return ScoreResult(
        score=score,
        status=status,
        justificativa_tecnica=final_justification
    )
