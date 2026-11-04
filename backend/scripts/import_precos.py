"""Importa a tabela de preços com desconto (.md exportado da planilha) para o Supabase.

Uso: uv run python scripts/import_precos.py "caminho/Produtos_valores_com_desconto_DD-MM-AAAA.md"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.precos import ler_tabela_md, salvar_tabela  # noqa: E402

if __name__ == "__main__":
    arquivo = Path(sys.argv[1])
    itens = ler_tabela_md(arquivo.read_text(encoding="utf-8"))
    dados = salvar_tabela(itens, arquivo.name)
    print(f"{dados['total']} SKUs importados ({dados['sem_preco']} sem preço) de {arquivo.name}")
