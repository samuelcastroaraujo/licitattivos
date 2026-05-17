-- Habilitar extensão pgvector se não existir
CREATE EXTENSION IF NOT EXISTS vector;

-- Tabela: products
CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT UNIQUE NOT NULL,
    nome_comercial TEXT NOT NULL,
    fabricante TEXT DEFAULT 'Attivos Magisttrais Indústria e Comércio Ltda.',
    marca TEXT DEFAULT 'Pholias',
    linha_clinica TEXT,
    categoria TEXT,
    ncm TEXT,
    registro_anvisa TEXT,
    tem_registro_ms BOOLEAN NOT NULL DEFAULT false,
    apresentacoes JSONB DEFAULT '[]'::jsonb,
    descricao TEXT,
    indicacoes TEXT[] DEFAULT '{}',
    ingredientes JSONB NOT NULL,
    alergenicos_contem TEXT[] DEFAULT '{}',
    alergenicos_pode_conter TEXT[] DEFAULT '{}',
    sem_gluten BOOLEAN NOT NULL DEFAULT false,
    sem_lactose BOOLEAN NOT NULL DEFAULT false,
    sem_sacarose BOOLEAN NOT NULL DEFAULT false,
    publico_alvo TEXT,
    faixa_etaria_min_anos INTEGER,
    faixa_etaria_max_anos INTEGER,
    nutricao_por_porcao JSONB DEFAULT '{}'::jsonb,
    nutricao_por_100g JSONB DEFAULT '{}'::jsonb,
    porcao_g NUMERIC,
    kcal_por_porcao NUMERIC,
    proteinas_por_porcao_g NUMERIC,
    carboidratos_por_porcao_g NUMERIC,
    gorduras_por_porcao_g NUMERIC,
    fibras_por_porcao_g NUMERIC,
    sodio_por_porcao_mg NUMERIC,
    via_oral BOOLEAN NOT NULL DEFAULT true,
    via_enteral BOOLEAN NOT NULL DEFAULT false,
    ph_solucao TEXT,
    solubilidade TEXT,
    validade_dias INTEGER,
    validade_apos_aberto_dias INTEGER,
    normas_regulatorias TEXT[] DEFAULT '{}',
    diferenciais_tecnicos TEXT[] DEFAULT '{}',
    embedding vector(1536),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Tabela: editais
CREATE TABLE IF NOT EXISTS editais (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    numero_pregao TEXT NOT NULL,
    orgao TEXT NOT NULL,
    uf TEXT,
    portal_origem TEXT NOT NULL,
    url_edital TEXT,
    data_publicacao DATE,
    data_abertura TIMESTAMPTZ,
    status TEXT DEFAULT 'novo',
    raw_text TEXT,
    storage_path TEXT,
    anexo_url_origem TEXT,
    anexo_local_path TEXT,
    hash_arquivo TEXT,
    licit_context JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(portal_origem, orgao, numero_pregao)
);

-- Tabela: licit_items
CREATE TABLE IF NOT EXISTS licit_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    edital_id UUID REFERENCES editais(id) ON DELETE CASCADE,
    numero_item TEXT NOT NULL,
    descricao_original TEXT,
    tipo_produto TEXT,
    requisitos JSONB DEFAULT '{}'::jsonb,
    produto_id UUID REFERENCES products(id) ON DELETE SET NULL,
    score_compatibilidade NUMERIC,
    compativel BOOLEAN,
    alertas TEXT[] DEFAULT '{}',
    justificativa TEXT,
    preco_referencia NUMERIC,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Tabela: knowledge_items
CREATE TABLE IF NOT EXISTS knowledge_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo TEXT NOT NULL,
    produto_id UUID REFERENCES products(id) ON DELETE CASCADE,
    tipo_edital TEXT,
    conteudo TEXT NOT NULL,
    descritivo_original TEXT,
    resultado TEXT,
    score_final NUMERIC,
    peso NUMERIC DEFAULT 1.0,
    validado_por TEXT DEFAULT 'analista',
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Tabela: pregao_events
CREATE TABLE IF NOT EXISTS pregao_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    edital_id UUID REFERENCES editais(id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL,
    tipo_evento TEXT NOT NULL,
    numero_item TEXT,
    conteudo_raw TEXT,
    conteudo_parsed JSONB DEFAULT '{}'::jsonb,
    alerta_gerado BOOLEAN DEFAULT false,
    resposta_sugerida TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
