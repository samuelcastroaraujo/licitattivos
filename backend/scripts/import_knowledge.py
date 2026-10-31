"""
Envia backend/knowledge/snapshot.json para a tabela knowledge_snapshot.
Uso: uv run python scripts/import_knowledge.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.client import get_supabase_client  # noqa: E402

ARQUIVO = Path(__file__).resolve().parent.parent / "knowledge" / "snapshot.json"


def main() -> None:
    dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    get_supabase_client().table("knowledge_snapshot").upsert({"key": "historico", "data": dados}).execute()
    print("Clientes:", len(dados["clientes"]), "| Produtos:", len(dados["produtos"]))


if __name__ == "__main__":
    main()
