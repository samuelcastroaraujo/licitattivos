-- Índices HNSW para busca por similaridade de cosseno nos vetores de embedding.
-- HNSW (em vez de IVFFLAT) porque não exige calibrar um número de "lists" ao
-- tamanho da tabela — o catálogo hoje tem ~150 produtos, pouco para IVFFLAT
-- treinar bem, e o HNSW mantém boa recall desde o primeiro vetor, escalando à
-- medida que o catálogo e o knowledge_items crescem.
-- `vector_cosine_ops` casa com o uso de similaridade de cosseno descrito no
-- CLAUDE.md (Agente 4, threshold cosine >= 0.82).
CREATE INDEX IF NOT EXISTS products_embedding_hnsw_idx
    ON products USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS knowledge_items_embedding_hnsw_idx
    ON knowledge_items USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
