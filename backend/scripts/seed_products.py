"""
Carrega as 16 fichas de 'banco de dados/' na tabela products.
Valor que não é encontrado fica vazio: o Agente 4 trata como lacuna, nunca como aprovação.

Uso: uv run python scripts/seed_products.py          (só mostra)
     uv run python scripts/seed_products.py --gravar (grava no Supabase)
"""
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
PASTA = Path(__file__).resolve().parents[2] / "banco de dados"

# Catálogo oficial do CLAUDE.md. Só estes têm registro MS ou via enteral:
# na dúvida, o produto fica de fora para não gerar falso positivo.
COM_REGISTRO_MS = {"just_whey_protein_isolado", "just_whey_protein_concentrado"}
VIA_ENTERAL = {"just_whey_protein_isolado", "just_whey_protein_concentrado", "sorend"}


def _norm(texto: str) -> str:
    limpo = unicodedata.normalize("NFD", texto)
    limpo = "".join(c for c in limpo if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", limpo.replace("*", "")).strip().lower()


def _campo(texto: str, rotulo: str) -> str | None:
    achado = re.search(rf"\*\*{rotulo}[^*]*:\*\*\s*(.+)", texto, re.I)
    return achado.group(1).strip() if achado else None


def _ingredientes(texto: str) -> list[dict]:
    secao = re.search(r"^## \d+\.\s*Ingredientes.*?(?=^## |\Z)", texto, re.M | re.S | re.I)
    if not secao:
        return []
    lista = []
    vistos = set()
    for linha in secao.group(0).splitlines():
        partes = [p.strip() for p in linha.strip().strip("|").split("|")]
        if not linha.strip().startswith("|") or len(partes) < 2:
            continue
        if set(partes[0]) <= {"-", " ", ":"} or _norm(partes[0]) == "ingrediente":
            continue
        nome = partes[0].replace("*", "").strip()
        if _norm(nome) in vistos:
            continue
        vistos.add(_norm(nome))
        lista.append({
            "nome": nome,
            "nome_normalizado": _norm(nome),
            "funcao": partes[1].replace("*", "").strip(),
            "categoria": "ingrediente",
            "e_alergeno": any(a in _norm(nome) for a in ("leite", "soja", "ovo", "gluten", "trigo")),
        })
    return lista


def _nutriente(texto: str, *nomes: str) -> float | None:
    secao = re.search(r"^## \d+\.\s*Informa.*?Nutricionais.*?(?=^## |\Z)", texto, re.M | re.S | re.I)
    if not secao:
        return None
    for linha in secao.group(0).splitlines():
        partes = [p.strip() for p in linha.strip().strip("|").split("|")]
        if len(partes) >= 2 and any(n in _norm(partes[0]) for n in nomes):
            valor = re.search(r"\d+(?:[.,]\d+)?", partes[1])
            if valor:
                return float(valor.group(0).replace(",", "."))
    return None


def montar(arquivo: Path) -> dict:
    texto = arquivo.read_text(encoding="utf-8")
    titulo = re.search(r"^# (.+)", texto, re.M)
    alvo = _norm(texto)
    sem = lambda *termos: any(t in alvo for t in termos)
    return {
        "slug": arquivo.stem,
        "nome_comercial": titulo.group(1).strip() if titulo else arquivo.stem,
        "linha_clinica": _campo(texto, "Linha"),
        "categoria": _campo(texto, "Categoria"),
        "ncm": _campo(texto, "Classifica"),
        "registro_anvisa": _campo(texto, "Registro"),
        "tem_registro_ms": arquivo.stem in COM_REGISTRO_MS,
        "descricao": texto[:4000],
        "ingredientes": {"lista": _ingredientes(texto), "nota_pureza": ""},
        "sem_gluten": sem("nao contem gluten", "sem gluten", "isento de gluten"),
        "sem_lactose": sem("zero lactose", "sem lactose", "isento de lactose"),
        "sem_sacarose": sem("sem sacarose", "zero acucar", "sem adicao de acucar", "isento de sacarose"),
        "via_oral": True,
        "via_enteral": arquivo.stem in VIA_ENTERAL,
        "kcal_por_porcao": _nutriente(texto, "valor energetico", "energia", "kcal"),
        "proteinas_por_porcao_g": _nutriente(texto, "proteina"),
        "carboidratos_por_porcao_g": _nutriente(texto, "carboidrato"),
        "gorduras_por_porcao_g": _nutriente(texto, "gorduras totais"),
        "fibras_por_porcao_g": _nutriente(texto, "fibra"),
        "sodio_por_porcao_mg": _nutriente(texto, "sodio"),
    }


def main() -> None:
    produtos = [montar(a) for a in sorted(PASTA.glob("*.md"))]
    for p in produtos:
        print(p["slug"], "| ing", len(p["ingredientes"]["lista"]), "| kcal", p["kcal_por_porcao"],
              "| prot", p["proteinas_por_porcao_g"], "| MS", p["tem_registro_ms"], "| enteral", p["via_enteral"])
    if "--gravar" in sys.argv:
        from db.client import get_supabase_client
        existentes = get_supabase_client().table("products").select("id", count="exact").limit(1).execute().count
        if existentes:
            print(f"Cancelado: o banco já tem {existentes} produtos, mais confiáveis que estas fichas.")
            return
        get_supabase_client().table("products").upsert(produtos, on_conflict="slug").execute()
        print("Gravados:", len(produtos))


if __name__ == "__main__":
    main()
