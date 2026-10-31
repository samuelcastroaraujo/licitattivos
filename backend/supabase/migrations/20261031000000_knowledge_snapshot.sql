-- Histórico comercial consolidado (vendas, preços, recebimentos e regras).
CREATE TABLE IF NOT EXISTS knowledge_snapshot (
    key TEXT PRIMARY KEY,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Dados comerciais: acesso só pela service role do backend.
ALTER TABLE knowledge_snapshot ENABLE ROW LEVEL SECURITY;

INSERT INTO storage.buckets (id, name, public)
VALUES ('editais_anexos', 'editais_anexos', false)
ON CONFLICT (id) DO NOTHING;
