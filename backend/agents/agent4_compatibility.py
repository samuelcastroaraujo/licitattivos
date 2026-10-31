"""
Agente 4 — Motor de Compatibilidade (As 5 Camadas)
"""
import re
import unicodedata

import structlog
from pydantic import BaseModel
from models.edital import LicitItem
from models.product import Product

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
    """Regras fixas aprendidas com a revisão humana (ainda sem busca vetorial)."""
    return []

def _normalize_string(s: str) -> str:
    if not s:
        return ""
    return " ".join(s.lower().split())

async def match_product(item: LicitItem, product: Product) -> ScoreResult:
    justificativas = []
    score = 1.0
    status = "compatível"
    
    # Camada 0: Orientação por Histórico
    kb_items = await get_knowledge_items(f"{item.descricao_original} {product.nome_comercial}")
    for kb in kb_items:
        if kb.get("regra_fixa"):
            log.warning("agent4.layer0_history_override", product=product.slug)
            if kb.get("decisao") == "reprovado":
                return ScoreResult(
                    score=0.0,
                    status="incompatível",
                    justificativa_tecnica=kb.get("motivo", "Reprovado por regra histórica.")
                )
            # Se for aprovado direto, poderia forçar score 1.0

    reqs = item.requisitos

    nota_familia, motivo_familia = _avaliar_familia(item.descricao_original, product)
    score = min(score, nota_familia)
    if motivo_familia:
        justificativas.append(motivo_familia)
    if re.search(r"(por|/|em)\s*100\s*(g|ml)", _sem_acento(item.descricao_original)) and (reqs.proteina_min_g or reqs.kcal_min):
        score = min(score, 0.85)
        justificativas.append("Ressalva: valor do edital por 100 g/ml; o cadastro é por porção. Conferir a conversão.")

    # Filtros eliminatórios: qualquer falha impede a recomendação.
    ingredientes_produto = {_normalize_string(i.nome_normalizado) for i in product.ingredientes.lista}
    for proibido in reqs.ingredientes_proibidos:
        if _normalize_string(proibido) in ingredientes_produto:
            score = 0.0
            justificativas.append(f"Eliminatório: contém ingrediente proibido ({proibido}).")
    restricoes = (
        (reqs.sem_gluten, product.sem_gluten, "sem glúten"),
        (reqs.sem_lactose, product.sem_lactose, "sem lactose"),
        (reqs.sem_sacarose, product.sem_sacarose, "sem sacarose"),
    )
    for exigido, atende, nome in restricoes:
        if exigido and not atende:
            score = min(score, 0.10)
            justificativas.append(f"Incompatível ou sem comprovação: edital exige {nome}.")
    if reqs.faixa_etaria_min_anos is not None and product.faixa_etaria_max_anos is not None \
            and product.faixa_etaria_max_anos < reqs.faixa_etaria_min_anos:
        score = 0.0
        justificativas.append("Eliminatório: faixa etária do produto fora da exigida.")
    if reqs.faixa_etaria_max_anos is not None and product.faixa_etaria_min_anos is not None \
            and product.faixa_etaria_min_anos > reqs.faixa_etaria_max_anos:
        score = 0.0
        justificativas.append("Eliminatório: faixa etária do produto fora da exigida.")

    # Camada 1: Thresholds Matemáticos e Gaps
    # Proteína
    if reqs.proteina_min_g is not None:
        if product.proteinas_por_porcao_g is None:
            score = min(score, 0.40) # Trava o score, gap de info
            justificativas.append("GAP de informação: produto não possui valor de proteína cadastrado.")
        elif product.proteinas_por_porcao_g < reqs.proteina_min_g:
            score = min(score, 0.10)
            justificativas.append(f"Incompatível: Edital pede {reqs.proteina_min_g}g de proteína, produto tem {product.proteinas_por_porcao_g}g.")
            
    # Kcal
    if reqs.kcal_min is not None:
        if product.kcal_por_porcao is None:
            score = min(score, 0.40)
            justificativas.append("GAP de informação: produto não possui kcal cadastrada.")
        elif product.kcal_por_porcao < reqs.kcal_min:
            score = min(score, 0.10)
            justificativas.append(f"Incompatível: Edital pede {reqs.kcal_min} kcal, produto tem {product.kcal_por_porcao}.")

    # Camada 2: Ingredientes (Busca Exata normalizada)
    if reqs.ingredientes_obrigatorios:
        # Pega a lista de ingredientes do produto
        prod_ings = [_normalize_string(ing.nome_normalizado) for ing in product.ingredientes.lista]
        for req_ing in reqs.ingredientes_obrigatorios:
            if _normalize_string(req_ing) not in prod_ings:
                score = min(score, 0.50)
                justificativas.append(f"Ingrediente obrigatório faltante: {req_ing}.")

    # Camada 3: Regulatório. Exigência expressa é eliminatória.
    if reqs.registro_anvisa_obrigatorio and not (product.tem_registro_ms and REGISTRO_MS_CONFIRMADO.search(product.slug)):
        score = min(score, 0.10)
        justificativas.append("Incompatível: edital exige Registro MS e o registro do produto não está confirmado no catálogo. Avaliar esclarecimento ou impugnação.")

    # Camada 4: Clínico (Via Enteral)
    if reqs.via_enteral_obrigatoria and not (product.via_enteral and ENTERAL_CONFIRMADO.search(product.slug)):
        score = min(score, 0.10)
        justificativas.append("Incompatível: via enteral não confirmada para o produto.")

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
