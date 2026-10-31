# CLAUDE.md — LicitAttivos
> Este arquivo é a memória permanente do projeto. Leia-o integralmente antes de qualque/CLEARr tarefa.
> Nunca remova seções. Atualize quando a arquitetura evoluir.

---

## O Que É Este Projeto

**LicitAttivos** é um sistema multi-agente de automação de licitações para a **Attivos Magisttrais Indústria e Comércio Ltda.** (marca **Pholias**), fabricante de suplementos de nutrição clínica hospitalar.

O sistema elimina o trabalho manual do ciclo completo de uma licitação:
1. Busca e download de editais em portais públicos
2. Análise de compatibilidade dos descritivos com o portfólio de produtos
3. Geração de proposta comercial
4. Geração de declarações, certidões e documentos exigidos pelo edital
5. Acompanhamento do pregão e criação de recursos/impugnações

**Usuário principal:** analista de licitações da Attivos Magisttrais  
**Objetivo:** o usuário foca em decisão e oportunidade — o sistema executa

12. **A Regra de Ouro da Pós-Produção (Iteração Viva):**
    - O pregoeiro vai mandar formatos de data bizarros ("fev", "abr"). O sistema vai falhar.
    - Quando o "caos da realidade" bater no Regex:
      1. Extraia o log do LangSmith.
      2. Documente o Hurdle neste arquivo (Seção `Hurdles & Fixes`).
      3. Peça para a IA refatorar a Regex/Parser.
      4. Shippe o fix em minutos.

## Hurdles & Fixes (Diário de Bordo)
- **Hurdle 1:** Supabase Singleton State Leak. *Fix:* Movido de global cache para instância via factory.
- **Hurdle 2:** Playwright bloqueando UI. *Fix:* Movido para worker serverless/async isolation.
- **Hurdle 3:** Agente 1 só buscava por CNPJ. *Fix:* `agents/agent0_ingest.py` usa a busca pública do PNCP e actors do Apify; `agents/orchestrator.py` liga os Agentes 1 a 4 sem LangGraph, por enquanto.
- **Hurdle 4:** Ficha `.md` não define registro MS nem via enteral de forma confiável. *Fix:* `scripts/seed_products.py` usa o catálogo deste arquivo. Revisar os números nutricionais carregados antes de confiar no score.
- **Inteligência histórica:** `backend/knowledge/snapshot.json` (fora do Git) vai para a tabela `knowledge_snapshot` com `scripts/import_knowledge.py`.
- **Hurdle 5:** Banco já tinha 97 produtos (61 Pholias, 36 Venum), melhores que as fichas `.md`. *Fix:* seed recusa banco com dados; pipeline usa só Pholias. Pendente: revisar `tem_registro_ms` e `via_enteral`, que divergem do catálogo.
- **Hurdle 6 (auditoria 31/10/2026):** item sem requisito numérico aprovava qualquer produto; regex de proteína copiava o valor do edital inteiro; painel mostrava dados falsos com backend offline; API sem autenticação. *Fix:* famílias de produto no Agente 4, regex só no item, painel sem dados de demonstração, token na API e senha no painel.
- **Não usar em produção ainda:** Agente 5 (declaração vazia), Agente 7 (regras simplificadas), Agente 8 (sem conexão com portal) e Agente 9 (texto simulado). Não estão ligados ao pipeline.
- **Hurdle 7:** (Aberto para próximos confrontos em produção)

## Filosofia Final
Este sistema não é um MVP; é um **Asset Digital** desenhado para assumir a linha de frente comercial da Attivos Magisttrais. A IA deve se reportar ao `USER` como um desenvolvedor Sênior de missão crítica.

---

## Regras Absolutas (Sempre Siga)

- **Nunca suprima alertas de incompatibilidade.** Um falso positivo (dizer que é compatível quando não é) resulta em desclassificação no pregão. Prefira falsos negativos com alerta claro.
- **Nunca invente dados de produto.** Todos os dados de produto vêm do banco Supabase (`products`). Se um campo estiver nulo, informe o gap — não assuma.
- **Números nutricionais são críticos.** Sempre valide thresholds (proteína mínima, minerais, vitaminas) com os valores reais do banco, nunca com estimativas do LLM.
- **Preserve a numeração de itens do edital.** O número do item é a chave de rastreabilidade em toda a cadeia (análise → proposta → declaração).
- **Documentos gerados seguem templates.** Nunca improvise formato de proposta ou declaração. Use os templates em `/templates/`.
- **Português brasileiro em toda a interface e documentos gerados.**

---

## Arquitetura: Pipeline de 9 Agentes

Cada agente tem responsabilidade única. A comunicação usa o objeto **`LicitContext`**, enriquecido em cascata.
- **Agente 7** roda em paralelo com o fluxo principal a partir do Agente 2 (análise jurídica)
- **Agente 8** é ativado manualmente pelo analista no dia do pregão (monitoramento em tempo real)

```
[Edital PDF / URL]
        │
        ▼
┌─────────────────────┐
│  Agente 1           │  Extração & Download
│  Edital Fetcher     │  → Baixa PDF, identifica órgão/pregão/anexos
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Agente 2           │  Parsing & Estruturação
│  PDF Parser         │  → Texto limpo + array de itens numerados
└────────┬────────────┘
         │
         ├──────────────────────────────────────────┐
         ▼                                          ▼
┌─────────────────────┐             ┌─────────────────────┐
│  Agente 3           │             │  Agente 7           │  [PARALELO]
│  Requirements       │             │  Impugnador         │  Análise jurídica
│  Extractor          │             │                     │  do edital
└────────┬────────────┘             └─────────────────────┘
         │
         ▼
┌─────────────────────┐
│  Agente 4           │  CORE — Motor de Compatibilidade
│  Compatibility      │  → CompatibilityResult[] com score, justificativa e alertas
│  Engine             │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Agente 5           │  Geração de Documentos
│  Document           │  → Proposta comercial, declarações, justificativa técnica
│  Generator          │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Agente 6           │  Empacotamento
│  Doc Packager       │  → ZIP organizado pronto para download e envio
└─────────────────────┘

[Dia do Pregão — Ativação Manual]
        │
        ▼
┌─────────────────────┐
│  Agente 8           │  Monitor de Pregão (tempo real)
│  Pregao Monitor     │  → Alertas e sugestões de lance em tempo real
└────────┬────────────┘
         │  (detecta necessidade de recurso)
         ▼
┌─────────────────────┐
│  Agente 9           │  Gerador de Recursos Administrativos
│  Recurso Writer     │  → Documentos jurídicos com linguagem de advogado experiente
└─────────────────────┘
```

---

## Stack Tecnológica

| Camada | Tecnologia |
|--------|------------|
| Backend | Python 3.12 + FastAPI |
| Orquestração de Agentes | LangGraph |
| LLM Principal | OpenRouter, modelo em `LLM_MODEL` (padrão DeepSeek V4.1 Flash) |
| Banco de Dados | Supabase — PostgreSQL + pgvector |
| Embeddings | `text-embedding-3-small` (OpenAI) |
| Parser PDF nativo | `pdfplumber` + `pymupdf` + `pdfminer.six` |
| OCR (PDFs escaneados) | `pytesseract` + Tesseract (PT-BR) |
| Geração de documentos | `python-docx` (Word) + `WeasyPrint` (PDF) + `openpyxl` (Excel) |
| Frontend | Next.js (App Router) + shadcn/ui |
| Observabilidade | LangSmith (traces de agentes) + Sentry (erros em produção) |
| Hospedagem | Railway |

---

## Banco de Dados: Supabase

### Tabela `products`

Schema completo e definitivo. Toda análise de compatibilidade parte desta tabela.

```sql
id                        UUID PRIMARY KEY
slug                      TEXT UNIQUE                 -- ex: "just-whey-protein-isolado"
nome_comercial            TEXT NOT NULL
fabricante                TEXT DEFAULT 'Attivos Magisttrais Indústria e Comércio Ltda.'
marca                     TEXT DEFAULT 'Pholias'
linha_clinica             TEXT                        -- ex: "Nutrição Clínica Pediátrica"
categoria                 TEXT                        -- ex: "Módulo de Proteína Isolada"
ncm                       TEXT
registro_anvisa           TEXT                        -- nº do registro ou "Dispensado RDC 240/2018"
tem_registro_ms           BOOLEAN NOT NULL DEFAULT false
apresentacoes             JSONB                       -- [{gramatura, embalagem, ean, rendimento}]
descricao                 TEXT
indicacoes                TEXT[]                      -- indicações clínicas em array
ingredientes              JSONB NOT NULL              -- ver estrutura abaixo (campo central)
alergenicos_contem        TEXT[]                      -- ex: ["LEITE", "LACTOSE"]
alergenicos_pode_conter   TEXT[]                      -- ex: ["OVO", "SOJA"]
sem_gluten                BOOLEAN NOT NULL DEFAULT false
sem_lactose               BOOLEAN NOT NULL DEFAULT false
sem_sacarose              BOOLEAN NOT NULL DEFAULT false
publico_alvo              TEXT                        -- ex: "Adultos ≥19 anos", "Crianças 4-9 anos"
faixa_etaria_min_anos     INTEGER
faixa_etaria_max_anos     INTEGER
nutricao_por_porcao       JSONB                       -- tabela nutricional completa por porção
nutricao_por_100g         JSONB                       -- tabela nutricional por 100g
porcao_g                  NUMERIC
kcal_por_porcao           NUMERIC
proteinas_por_porcao_g    NUMERIC
carboidratos_por_porcao_g NUMERIC
gorduras_por_porcao_g     NUMERIC
fibras_por_porcao_g       NUMERIC
sodio_por_porcao_mg       NUMERIC
via_oral                  BOOLEAN NOT NULL DEFAULT true
via_enteral               BOOLEAN NOT NULL DEFAULT false  -- apto para sonda
ph_solucao                TEXT
solubilidade              TEXT
validade_dias             INTEGER
validade_apos_aberto_dias INTEGER
normas_regulatorias       TEXT[]                      -- RDCs aplicáveis
diferenciais_tecnicos     TEXT[]                      -- argumentos de defesa técnica (seção 11)
embedding                 vector(1536)                -- pgvector para RAG semântico
updated_at                TIMESTAMPTZ DEFAULT now()
```

### Estrutura JSONB de `ingredientes` (campo central do Agente 4)

```json
{
  "lista": [
    {
      "nome": "Proteína Concentrada do Soro do Leite",
      "nome_normalizado": "whey protein concentrado",
      "funcao": "Fonte Proteica de Alto Valor Biológico",
      "categoria": "proteina",
      "e_alergeno": true,
      "quantidade_por_porcao_g": null
    },
    {
      "nome": "L-Arginina",
      "nome_normalizado": "arginina",
      "funcao": "Aminoácido precursor de NO (Cicatrização)",
      "categoria": "aminoacido",
      "e_alergeno": false,
      "quantidade_por_porcao_g": 0.618
    }
  ],
  "nota_pureza": "Produto monocomponente. Não contém açúcares, corantes ou aromatizantes."
}
```

**Por que `nome_normalizado`?** O edital pode escrever "Arginina", "L-Arginina", "arginina livre". O campo normalizado permite busca exata. O Agente 4 usa busca exata primeiro, embedding como fallback.

**Categorias válidas para `ingredientes.lista[].categoria`:**
`proteina` | `aminoacido` | `carboidrato` | `lipideo` | `fibra` | `vitamina` | `mineral` | `enzima` | `edulcorante` | `espessante` | `flavorizante` | `antiumectante`

### Catálogo de Produtos (16 produtos ativos)

| Produto | Linha | `tem_registro_ms` | `via_enteral` | `publico_alvo` |
|---------|-------|:-----------------:|:-------------:|----------------|
| Just Whey Protein Isolado | Proteína | `true` (MS 6.7055.0029) | `true` | Adulto |
| Just Whey Protein Concentrado | Proteína | `true` (MS 6.7055.0028) | `true` | Adulto |
| Just Whey Protein Hidrolisado | Proteína | `false` | `false` | Adulto |
| Just Arginina | Módulo AA | `false` | `false` | Adulto |
| Just Creatina | Módulo AA | `false` | `false` | Adulto |
| Just Glutamina | Módulo AA | `false` | `false` | Adulto |
| Just Maltodextrina | Energia | `false` | `false` | Adulto |
| Just Fibras Solúveis | Fibra | `false` | `false` | Adulto |
| Sorend | Cicatrização | `false` (Dispensado) | `true` | Adulto ≥19 |
| Sorend Kids | Cicatrização Pediátrica | `false` (Dispensado) | `false` | Criança |
| Veetal Infant | Nutrição Pediátrica | `false` (Dispensado) | `false` | 4–9 anos |
| Veetal Senior 50+ | Nutrição Idosos | `false` | `false` | ≥50 anos |
| Veetal Fiber | Fibra Clínica | `false` | `false` | Adulto |
| Just Veetal Active | Performance | `false` | `false` | Adulto |
| Veetal Gli Control | Controle Glicêmico | `false` (Dispensado) | `false` | Adulto diabético |
| Bella Fiber | Fibra Feminino | `false` | `false` | Adulto feminino |

### Tabela `editais`

```sql
id                UUID PRIMARY KEY
numero_pregao     TEXT
orgao             TEXT
uf                TEXT
portal_origem     TEXT    -- "comprasnet" | "bll" | "pncp" | "manual"
url_edital        TEXT
data_publicacao   DATE
data_abertura     TIMESTAMPTZ
status            TEXT    -- "novo" | "analisando" | "compativel" | "incompativel" | "proposta_gerada" | "em_pregao" | "vencido" | "perdido"
raw_text          TEXT
storage_path      TEXT    -- caminho no Supabase Storage
licit_context     JSONB   -- objeto LicitContext completo
created_at        TIMESTAMPTZ DEFAULT now()
```

### Tabela `licit_items`

```sql
id                   UUID PRIMARY KEY
edital_id            UUID REFERENCES editais(id)
numero_item          TEXT NOT NULL
descricao_original   TEXT
tipo_produto         TEXT
requisitos           JSONB   -- estrutura LicitItem.requisitos (ver Agente 3)
produto_id           UUID REFERENCES products(id)  -- produto vinculado após análise
score_compatibilidade NUMERIC  -- 0.0 a 1.0
compativel           BOOLEAN
alertas              TEXT[]
justificativa        TEXT
preco_referencia     NUMERIC
created_at           TIMESTAMPTZ DEFAULT now()
```

### Tabela `knowledge_items`

Base de conhecimento acumulado. Alimentada automaticamente pelo feedback do analista e por dicas inseridas manualmente. Usada pelo Agente 4 como orientação antes de calcular o score.

```sql
id                   UUID PRIMARY KEY
tipo                 TEXT NOT NULL   -- "feedback_historico" | "dica_usuario" | "regra_fixa"
produto_id           UUID REFERENCES products(id)   -- produto relacionado (pode ser null)
tipo_edital          TEXT            -- ex: "cicatrizacao", "controle_glicemico", "proteina_hospitalar"
conteudo             TEXT NOT NULL   -- descrição do conhecimento em linguagem natural
descritivo_original  TEXT            -- texto do item do edital que gerou esse conhecimento
resultado            TEXT            -- "compativel" | "incompativel" | "compativel_com_ressalvas"
score_final          NUMERIC         -- score que o analista validou como correto
peso                 NUMERIC DEFAULT 1.0   -- dicas manuais podem ter peso maior (ex: 2.0)
validado_por         TEXT DEFAULT 'analista'
embedding            vector(1536)    -- para busca semântica no Agente 4
created_at           TIMESTAMPTZ DEFAULT now()
```

**Regras de uso:**
- O Agente 4 busca os **5 mais similares** por pgvector, ordenando por `similaridade * peso * recência`
- Itens com `tipo = "regra_fixa"` têm prioridade máxima (ex: regras de negócio definidas pelo analista)
- O analista gerencia os `knowledge_items` através de painel na interface (visualizar, editar, excluir, adicionar dica)
- Meta: ~100 itens por tipo de produto para cobertura sólida de cenários

---

## Agente 3 — Extrator de Requisitos

O prompt do Agente 3 deve extrair do texto do edital o seguinte schema por item:

```typescript
interface LicitItem {
  numero_item: string;
  descricao_original: string;
  tipo_produto: string;
  requisitos: {
    proteina_min_g?: number;
    kcal_min?: number;
    kcal_max?: number;
    via_enteral_obrigatoria: boolean;
    registro_anvisa_obrigatorio: boolean;
    sem_sacarose?: boolean;
    sem_gluten?: boolean;
    sem_lactose?: boolean;
    ingredientes_obrigatorios: string[];   // em lowercase normalizado
    ingredientes_proibidos: string[];      // em lowercase normalizado
    faixa_etaria: "infantil" | "adulto" | "idoso" | "qualquer";
    faixa_etaria_min_anos?: number;
    faixa_etaria_max_anos?: number;
    unidade_solicitada: string;
    quantidade_pregao: number;
    outros_requisitos_texto: string[];    // requisitos que não couberam nos campos acima
  };
}
```

**Validação obrigatória pós-LLM:** Valores numéricos (`proteina_min_g`, `kcal_min`, `quantidade_pregao`) devem ser revalidados com regex no texto original. Se o LLM divergir do texto, o texto original prevalece.

---

## Agente 4 — Motor de Compatibilidade

### Pré-processamento: Orientação por Histórico (executado antes das camadas)

Antes de calcular qualquer score, o Agente 4 consulta a tabela `knowledge_items` para orientar a análise com base em decisões anteriores semelhantes.

```
PRÉ-PROCESSAMENTO — Busca de Conhecimento Histórico:
  ├── Vetoriza o descritivo do item atual (embedding)
  ├── Busca os 5 knowledge_items mais similares via pgvector
  │   (filtra por produto_id ou tipo_edital quando disponível)
  ├── Ordena por: similaridade semântica + recência (últimas decisões têm mais peso)
  └── Injeta como orientação no contexto do Agente:
      "Compatibilidades recentes com descritivos similares indicam: [contexto]"
      → Não substitui o score — orienta o raciocínio do LLM nas camadas seguintes
```

### Lógica em 5 Camadas

```
CAMADA 1 — Filtros Eliminatórios (hard filters — qualquer falha = score 0):
  ├── registro_anvisa_obrigatorio = true  →  products.tem_registro_ms = true
  ├── via_enteral_obrigatoria = true      →  products.via_enteral = true
  ├── sem_gluten = true                   →  products.sem_gluten = true
  ├── faixa_etaria vs faixa_etaria_min/max_anos do produto
  └── ingrediente_proibido ∈ ingredientes.lista[].nome_normalizado  →  eliminatório

CAMADA 2 — Score por Ingredientes (peso 40%):
  └── Para cada ingrediente_obrigatorio:
      ├── busca exata em ingredientes.lista[].nome_normalizado
      ├── busca semântica via pgvector (threshold cosine ≥ 0.82)
      └── score += (encontrados / total_obrigatorios)

CAMADA 3 — Score Nutricional (peso 35%):
  ├── proteina_min_g ≤ products.proteinas_por_porcao_g
  ├── kcal dentro do range solicitado
  └── demais thresholds nutricionais do edital

CAMADA 4 — Score de Apresentação (peso 15%):
  ├── unidade_solicitada disponível em products.apresentacoes[]
  └── gramatura compatível

CAMADA 5 — Score Regulatório / Diferenciais (peso 10%):
  ├── tem_registro_ms = true  →  +0.05 bonus
  └── diferenciais_tecnicos relevantes ao tipo do edital  →  bonus semântico
```

### Score Final
- **≥ 0.90** — Compatível, recomendado
- **0.70 – 0.89** — Compatível com ressalvas (listar alertas)
- **0.50 – 0.69** — Compatibilidade parcial (decisão do analista)
- **< 0.50** — Incompatível

O analista pode **ajustar os pesos** de cada camada pela interface (persistidos em `configuracoes_usuario`).

### Feedback Loop — Como o Sistema Aprende

Após cada análise validada pelo analista, o resultado é salvo como novo `knowledge_item`. Isso garante que a cada edital analisado o sistema fica mais preciso para descritivos similares.

```
Análise concluída
      ↓
Analista valida ou corrige o resultado na interface
      ↓
Sistema salva knowledge_item:
  - tipo: "feedback_historico"
  - descritivo_original do item do edital
  - produto vinculado + score + decisão final do analista
  - embedding do descritivo (para busca futura)
      ↓
Próximo edital com descritivo similar → Agente 4 encontra esse item
e usa como orientação antes de calcular o score
```

---

## Agente 7 — Impugnador (Fluxo Paralelo)

**Responsabilidade:** Análise jurídica do edital em paralelo ao fluxo de compatibilidade. Roda a partir do texto parseado pelo Agente 2, independente dos Agentes 3–6.

- **Input:** Texto completo do edital + Termo de Referência parseados
- **Output:** `ImpugnacaoResult` com três seções: impugnações, esclarecimentos e alertas jurídicos

### Classificação de Menção de Marca (lógica central)

O agente detecta e classifica cada ocorrência de marca/produto por item antes de decidir a ação:

| Tipo detectado no descritivo | Interpretação jurídica | Ação do Agente 7 |
|---|---|---|
| **"Marca X ou similar"** / **"referência"** | Legal — é apenas referência técnica. Qualquer equivalente pode participar. | Gera **pedido de esclarecimento** confirmando que o produto da Attivos é aceito como similar |
| **"Marcas recomendadas: [lista]"** | Legal — lista é orientativa, não excludente | Gera **pedido de esclarecimento** pedindo confirmação que produtos não listados são aceitos se tecnicamente equivalentes |
| **"Marcas aceitas: [lista]"** | Potencial vício — se nosso produto é equivalente e não está na lista | Gera **pedido de esclarecimento** primeiro. Se a resposta excluir produtos equivalentes, gera **minuta de impugnação** |
| **"Marcas cadastradas: [lista]"** | Depende do processo de cadastro — se aberto e razoável, é legal | Gera pedido de esclarecimento sobre **como incluir nova marca no cadastro** e prazo |
| **Marca específica sem alternativa** (sem "ou similar") | Vício claro de direcionamento (Art. 15 e 40, Lei 14.133/21) | **Impugnação direta** — gera minuta completa |
| **Processo judicial como justificativa** | Exceção legal — pode fechar para marca. MAS: verifica se o **item específico** (não só o edital) cita marca | Se o item específico cita marca + há processo: **registra como alerta monitorado**. Sem processo: **impugnação direta** |
| **Valores nutricionais específicos que só um produto atende** | Potencial vício técnico por especificidade excessiva | Gera **pedido de esclarecimento** com justificativa técnica explicando que nosso produto atende ou que o critério é restritivo sem motivo |

### Detecção de Descritivos com Especificidade Excessiva

Além de mencionar marcas, o agente detecta padrões de direcionamento implícito:
- Valores nutricionais com precisão suspeita (ex: exige exatamente 87g/100g — valor único de um produto)
- Código EAN ou número de registro ANVISA de produto específico
- Características físicas únicas (tipo de embalagem, cor, dimensões) que eliminam concorrentes legítimos
- Combinação de múltiplos critérios que, individualmente são razoáveis, mas em conjunto só um produto atende

### Estrutura do Output (`ImpugnacaoResult`)

```json
{
  "impugnacoes": [
    {
      "numero_item": "05",
      "tipo_vicio": "marca_especifica_sem_alternativa",
      "descricao_vicio": "Item 05 cita \"Fresubin\" sem permitir produto similar",
      "fundamento_legal": "Art. 40 §1º e Art. 15 da Lei 14.133/2021",
      "minuta_impugnacao": "[texto completo da impugnação gerado por template]"
    }
  ],
  "esclarecimentos": [
    {
      "numero_item": "12",
      "tipo": "marca_recomendada",
      "pergunta": "O órgão aceitará produto tecnicamente equivalente ao citado como referência, desde que atenda todos os requisitos do descritivo?",
      "contexto": "Nosso produto Just Whey Protein Concentrado possui registro MS e via enteral homologada"
    },
    {
      "numero_item": "08",
      "tipo": "ambiguidade_descritivo",
      "pergunta": "O descritivo exige embalagem tipo pote ou sachê também será aceito?"
    }
  ],
  "alertas_juridicos": [
    {
      "numero_item": "03",
      "tipo": "excecao_processo_judicial",
      "descricao": "Edital menciona processo judicial nº XXXX como justificativa. Item 03 cita marca 'Y'. Monitorar resposta do pregoeiro."
    }
  ]
}
```

### Documentos Gerados pelo Agente 7

| # | Documento | Formato | Template |
|---|-----------|---------|----------|
| 01 | Impugnação ao Edital | `.docx` + `.pdf` | `impugnacao.jinja2` |
| 02 | Pedidos de Esclarecimento ao Pregoeiro | `.docx` | `esclarecimento.jinja2` |
| 03 | Relatório de Alertas Jurídicos | `.pdf` | `alertas_juridicos.jinja2` |

Os documentos do Agente 7 são incluídos no ZIP do Agente 6 na pasta `juridico/`:
```
pregao_.../
├── [...documentos de proposta...]
└── juridico/
    ├── impugnacao_item_05.docx
    ├── esclarecimentos_ao_pregoeiro.docx
    └── relatorio_alertas_juridicos.pdf
```

### Regra Crítica do Agente 7

O agente **nunca impugna automaticamente sem alerta ao analista.** Todo item classificado como vício exige validação do analista antes de gerar o documento final — a minuta é gerada, mas o envio é sempre uma decisão humana.

---

## Agente 8 — Monitor de Pregão (Tempo Real)

**Responsabilidade:** Monitoramento ativo da sessão do pregão eletrônico no dia da disputa. Ativado manualmente pelo analista. Opera em tempo real sobre o chat do portal (Comprasnet, BLL, PNCP) via Playwright.

- **Input:** Sessão autenticada no portal + `LicitContext` do edital (contexto completo da análise anterior)
- **Output:** Alertas em tempo real no dashboard + documentos pós-pregão (recursos, atas, relatórios)

### Eventos Monitorados e Ações

| Evento detectado no chat | Prioridade | Ação do Agente 8 |
|---|:---:|---|
| **Pregoeiro abre item para lances** | 🔴 Alta | Notifica analista + exibe preço mínimo aceitável (da planilha de autorização) |
| **Pregoeiro faz pergunta no chat** | 🔴 Alta | Exibe a pergunta em destaque + sugere resposta com base no `LicitContext` |
| **Concorrente dá lance menor que o nosso** | 🔴 Alta | Alerta com diferença de valor + indica se ainda está acima do preço mínimo autorizado |
| **Item suspenso ou reclassificado** | 🔴 Alta | Alerta imediato + orienta se cabe recurso |
| **Prazo de envio de proposta expirando** | 🔶 Média | Alerta com tempo restante |
| **Pregoeiro solicita documentos complementares** | 🔶 Média | Lista os documentos solicitados e indica quais já estão no ZIP |
| **Concorrente desclassificado** | 🔷 Baixa | Registra + analisa se muda a postura de lance |
| **Sessão encerrada / vencedor declarado** | 🔷 Baixa | Registra resultado e aciona geração de relatório pós-pregão |

### Suporte a Recursos (Pós-Pregão)

Após o encerramento do pregão, o Agente 8 analisa os eventos registrados e identifica situações que justificam recurso administrativo:

```
Situações que geram minuta de recurso automática:

├── Desclassificação indevida
│   └── Sistema foi desclassificado por motivo que o LicitContext indica não proceder
│       Ex: exigência de documento não prevista no edital
├── Julgamento irregular do vencedor
│   └── Vencedor declarado com proposta que não atende descritivo técnico
│       Agente cruza descritivo vencedor com banco de produtos (se disponível)
├── Preço excessivamente abaixo do mercado (preço inexequível)
│   └── Lance vencedor abaixo de 70% do preço de referência do edital
└── Irregularidade no procedimento
    └── Pregoeiro descumpriu fase (ex: não abriu prazo para recursos)
```

### Estrutura da Tabela `pregao_events` (Supabase)

```sql
id              UUID PRIMARY KEY
edital_id       UUID REFERENCES editais(id)
timestamp       TIMESTAMPTZ
tipo_evento     TEXT   -- "lance" | "mensagem_pregoeiro" | "desclassificacao" | "encerramento" | ...
numero_item     TEXT
conteudo_raw    TEXT   -- texto exato do chat
conteudo_parsed JSONB  -- extração estruturada do evento
alerta_gerado   BOOLEAN
resposta_sugerida TEXT -- sugestão de resposta ao pregoeiro (quando aplicável)
created_at      TIMESTAMPTZ DEFAULT now()
```

### Documentos Gerados pelo Agente 8

| # | Documento | Quando | Template |
|---|-----------|--------|----------|
| 01 | Relatório do Pregão | Após encerramento da sessão | `relatorio_pregao.jinja2` |
| 02 | Ata de Análise | Registro interno para autorização gerencial | `ata_analise.jinja2` |

Quando o Agente 8 detecta necessidade de recurso, aciona o **Agente 9** com o contexto completo dos eventos registrados.

### Regra Crítica do Agente 8

O agente opera em **modo de assistência** — nunca envia lances, mensagens ou documentos automaticamente. Toda ação no portal é executada pelo analista. O agente sugere, alerta e prepara; o analista decide e age.

**Prazo de recurso é fatídico:** o sistema alerta o analista sobre o prazo de interposição com 24h de antecedência e no momento exato da abertura do prazo pelo pregoeiro.

---

## Agente 9 — Gerador de Recursos Administrativos

**Responsabilidade:** Geração de documentos jurídicos de alta qualidade para interposição de recursos administrativos em licitações. O output deve ser indistinguível de um documento redigido por advogado experiente em direito administrativo e licitações públicas.

- **Input:** `RecursoContext` — eventos do Agente 8 + `LicitContext` completo + tipo de recurso + fundamentos identificados
- **Output:** Documentos jurídicos prontos em `.docx` e `.pdf`, com linguagem formal, fundamentação legal sólida e argumentação técnica

### Persona do Agente 9

O prompt deste agente instrui o LLM a operar com a seguinte persona:

```
Você é um advogado especialista em Direito Administrativo e licitações públicas
com 15 anos de experiência, com sólido conhecimento em:
- Lei 14.133/2021 (Nova Lei de Licitações)
- Lei 8.666/1993 (quando ainda aplicável)
- Jurisprudência do TCU (Acórdãos relevantes)
- Jurisprudência do CGU e Tribunais de Contas estaduais
- RDC, Pregão Eletrônico (Lei 10.520/2002)

Seu estilo de escrita:
- Formal, técnico e assertivo — sem rodeios
- Parágrafos densos com fundamentação encadeada
- Citações de dispositivos legais integradas ao texto (não só em rodapé)
- Vocabulário jurídico preciso: "ora recorrente", "v. Acórdão", "data venia"
- Argumentação progressiva: do geral ao específico
- Nunca use linguagem de IA: sem bullet points no corpo do recurso,
  sem frases genéricas, sem repetição de estruturas
```

### Tipos de Documentos e Estrutura

#### 1. Intenção de Recurso (prazo imediato — durante o pregão)
```
Estrutura:
1. Identificação (Recorrente, Pregão, Órgão, Item)
2. Manifestação de intenção e reserva de prazo
3. Síntese do motivo (1 parágrafo — suficiente para abertura do prazo)
```

#### 2. Recurso Administrativo (prazo: geralmente 3 dias úteis)
```
Estrutura obrigatória:
1. PREÂMBULO — Identificação completa das partes e do processo
2. DOS FATOS — Narrativa cronológica e objetiva dos eventos do pregão
3. DO DIREITO
   3.1 Dos dispositivos legais aplicáveis
   3.2 Da jurisprudência do TCU (citar Acórdãos pertinentes)
   3.3 Da fundamentação técnica (cruzar com dados do LicitContext)
4. DO PEDIDO — Pedido claro, subsidiário quando cabível
5. DOCUMENTOS ANEXOS — Lista dos documentos que instruem o recurso
```

#### 3. Contrarrazões (quando outro licitante recorreu contra a Attivos)
```
Estrutura:
1. PREÂMBULO
2. DA TEMPESTIVIDADE DAS CONTRARRAZÕES
3. DOS FATOS (versão da Attivos)
4. DO DIREITO (rebater ponto a ponto os argumentos do recorrente)
5. DO PEDIDO (manutenção da decisão recorrida)
```

### Fundamentos Jurídicos por Tipo de Recurso

O agente seleciona automaticamente os fundamentos com base no `tipo_recurso`:

| Tipo de Recurso | Fundamentos Primários | Acórdãos TCU de Referência |
|---|---|---|
| Desclassificação indevida | Art. 59, §1º Lei 14.133/21 | Acórdão 2.072/2011-TCU-Plenário |
| Descritivo direcionado | Art. 40, §1º Lei 14.133/21 | Acórdão 1.190/2020-TCU-Plenário |
| Preço inexequível (vencedor) | Art. 59, §4º Lei 14.133/21 | Acórdão 1.793/2011-TCU-Plenário |
| Exigência documental ilegal | Art. 67 Lei 14.133/21 | Acórdão 2.859/2018-TCU-Plenário |
| Habilitação irregular do vencedor | Art. 62 Lei 14.133/21 | Acórdão 3.243/2016-TCU-Plenário |

### Pipeline Interno do Agente 9

```
RecursoContext recebido
        │
        ▼
[Seleção do tipo de recurso e fundamentos jurídicos]
        │
        ▼
[Geração do rascunho pelo LLM com persona de advogado]
        │
        ▼
[Pós-processamento: verificação de coerência jurídica]
  ├── Todos os artigos citados existem na lei referenciada?
  ├── Acórdãos TCU citados são pertinentes ao caso?
  └── O pedido é juridicamente possível?
        │
        ▼
[Humanização: variação de estrutura frasal]
  └── Evita padrões repetitivos que denunciam geração por IA
        │
        ▼
[Analista revisa e aprova — NUNCA protocolo automático]
        │
        ▼
[Geração do .docx e .pdf finais com formatação ABNT/Advocacia]
```

### Padrão de Formatação dos Documentos

- **Fonte:** Times New Roman 12pt (corpo) / Arial 12pt (alternativo)
- **Espaçamento:** 1,5 linhas no corpo; simples nas citações recuadas
- **Margens:** ABNT (superior/esquerda 3cm, inferior/direita 2cm)
- **Citações longas (>3 linhas):** recuadas 4cm, fonte 10pt
- **Negrito:** apenas em títulos de seção e no pedido final
- **Sem bullet points no corpo jurídico** — argumentação em parágrafos

### Documentos no ZIP Final

```
pregao_.../
└── pos_pregao/
    ├── relatorio_pregao.pdf              (Agente 8)
    ├── intencao_recurso.docx             (Agente 9)
    ├── intencao_recurso.pdf
    ├── recurso_administrativo.docx       (Agente 9)
    ├── recurso_administrativo.pdf
    └── contrarrazoes.docx                (Agente 9 — se aplicável)
```

### Regra Crítica do Agente 9

**O documento nunca é protocolado automaticamente.** O analista lê, revisa e aprova antes de qualquer envio. O sistema oferece o documento — o advogado (analista) assina com sua responsabilidade técnica.

**Qualidade não é negociável:** se o Agente 9 não conseguir gerar fundamentação jurídica sólida por falta de contexto suficiente, deve retornar `status: "contexto_insuficiente"` com lista dos dados faltantes — nunca gerar recurso com argumentação fraca.

## Agente 5 — Documentos Gerados

### Por edital validado, o sistema gera:

| # | Documento | Formato | Template |
|---|-----------|---------|----------|
| 01 | Proposta Comercial | `.xlsx` + `.pdf` | `proposta_comercial.jinja2` |
| 02 | Declaração de Compatibilidade Técnica | `.docx` | `declaracao_compatibilidade.jinja2` |
| 03 | Justificativa Técnica (item a item) | `.pdf` | `justificativa_tecnica.jinja2` |
| 04 | Declarações padrão (exigidas pelo edital) | `.docx` | dinâmico por tipo |
| 05 | Checklist de documentos a juntar | `.pdf` | `checklist.jinja2` |
| 06 | Planilha de autorização gerencial | `.xlsx` | `autorizacao_gerencial.jinja2` |

**Declarações padrão que o sistema identifica e gera automaticamente:**
- Declaração de inexistência de fato impeditivo
- Declaração de não emprego de menor
- Declaração de elaboração independente de proposta
- Declaração de cumprimento de requisitos de habilitação
- Declarações específicas mencionadas no Termo de Referência

### Estrutura do ZIP Final

```
pregao_[orgao]_[numero]_[YYYYMMDD]/
├── 01_proposta_comercial.xlsx
├── 02_proposta_comercial.pdf
├── 03_declaracao_compatibilidade.docx
├── 04_justificativa_tecnica.pdf
├── 05_checklist_documentos.pdf
├── 06_autorizacao_gerencial.xlsx
├── declaracoes/
│   ├── decl_inexistencia_fato_impeditivo.docx
│   ├── decl_nao_emprego_menor.docx
│   └── [outras declarações identificadas no edital]
└── fichas_tecnicas/
    └── [ficha técnica PDF de cada produto ofertado]
```

---

## Portais de Licitação Integrados

| Portal | Método de Acesso | Endpoint/Estratégia |
|--------|-----------------|---------------------|
| **PNCP** (Portal Nacional) | API REST pública | `https://pncp.gov.br/api/pncp/v1/` |
| **Comprasnet** | Playwright headless (requer login GOV.BR) | Sessão autenticada do usuário |
| **BLL** | API (com credenciais) | `https://bll.org.br/api/` |
| **Portais municipais** | Upload manual de PDF | Agente 2 processa normalmente |

---

## Fluxo de Trabalho do Usuário (UX)

### Fase 1 — Prospecção e Análise (Agentes 1 → 4 + 7)

```
1. Dashboard exibe editais novos encontrados automaticamente pelos portais
   (PNCP, Comprasnet, BLL — varredura automática via APScheduler)

2. Analista filtra por UF, órgão, tipo de produto e data de abertura

3. Analista seleciona edital para análise
        ↓
   Sistema roda pipeline automático: Agente 1 → 2 → 3 → 4
   EM PARALELO: Agente 7 (Impugnador) analisa vícios jurídicos
        ↓
4. Dashboard exibe:
   ├── Tabela de itens com score de compatibilidade (cores: verde/âmbar/vermelho)
   ├── Produto recomendado por item com justificativa
   ├── Alertas de incompatibilidade ou gaps
   ├── Conhecimentos históricos usados na orientação (do knowledge_items)
   └── Alertas jurídicos do Agente 7 (impugnações, esclarecimentos)

5. Analista pode:
   ├── Ajustar score manualmente (override) com justificativa
   ├── Aprovar ou rejeitar produto sugerido por item
   ├── Adicionar dica ao knowledge_items para futuras análises
   ├── Validar impugnação gerada pelo Agente 7
   └── Enviar pedido de esclarecimento ao pregoeiro (gerado pelo Agente 7)
```

### Fase 2 — Geração de Documentos (Agentes 5 → 6)

```
6. Analista aprova a análise e preenche preços
        ↓
   Sistema roda Agente 5 (Document Generator)
        ↓
7. Dashboard exibe preview dos documentos gerados:
   ├── Proposta comercial
   ├── Declarações exigidas
   ├── Justificativa técnica
   ├── Planilha de autorização gerencial
   └── Documentos jurídicos do Agente 7 (se aplicável)

8. Analista revisa e solicita ajustes se necessário

9. Analista confirma → Agente 6 gera ZIP completo para download
```

### Fase 3 — Dia do Pregão (Agente 8)

```
10. Analista ativa o monitoramento para o edital selecionado
         ↓
    Agente 8 conecta na sessão do portal via Playwright
         ↓
11. Dashboard exibe em tempo real:
    ├── Chat do pregoeiro com destaque para perguntas
    ├── Lances dos concorrentes vs. nosso preço mínimo autorizado
    ├── Sugestões de resposta ao pregoeiro (geradas com base no LicitContext)
    ├── Alertas de prazo (envio de proposta, abertura de fase)
    └── Notificação se item é suspenso ou desclassificado

12. Analista age no portal manualmente (lances, respostas, envios)
    Agente 8 apenas sugere e alerta — nunca age sozinho

13. Sessão encerrada → Agente 8 gera relatório do pregão + ata
```

### Fase 4 — Pós-Pregão e Recursos (Agente 9)

```
14. Se houver necessidade de recurso:
    ├── Agente 8 identifica situação (desclassificação, vício, preço inexequível)
    ├── Analista confirma a interposição de recurso
    └── Agente 9 gera:
        ├── Intenção de Recurso (imediato)
        ├── Recurso Administrativo (dentro do prazo legal)
        └── Contrarrazões (se outro licitante recorreu contra nós)

15. Analista revisa o documento jurídico gerado
    └── Qualidade jurídica: linguagem de advogado, fundamentação legal, acórdãos TCU

16. Analista protocola o recurso no portal (ação manual)

17. Resultado final registrado no sistema:
    ├── Status do edital atualizado (vencido / perdido / recurso em análise)
    ├── Knowledge_item gerado automaticamente com o feedback da análise
    └── Histórico completo disponível para futuras referências
```

---

## Convenções de Código

- **Testes antes de implementar:** Escreva o teste unitário do caso de uso principal antes de escrever a implementação (TDD).
- **Tipagem estrita:** Python com `mypy` habilitado. TypeScript no frontend com `strict: true`.
- **Validação com Pydantic v2:** Todo dado que entra no pipeline (especialmente saída de LLM) é validado com Pydantic antes de prosseguir.
- **Logs estruturados:** Use `structlog` no backend. Cada execução de pipeline gera um trace completo vinculado ao `edital_id`.
- **Variáveis de ambiente:** Nunca hardcode de chaves. Usar `.env` local e Railway secrets em produção.
- **Nunca commitar dados reais de licitação** no repositório (ficam apenas no Supabase).

---

## Estrutura de Diretórios do Projeto

```
licitattivos/
├── backend/
│   ├── agents/
│   │   ├── agent1_fetcher.py
│   │   ├── agent2_parser.py
│   │   ├── agent3_requirements.py
│   │   ├── agent4_compatibility.py
│   │   ├── agent5_documents.py
│   │   └── agent6_packager.py
│   ├── models/
│   │   ├── product.py          # Pydantic models
│   │   ├── licit_item.py
│   │   └── licit_context.py
│   ├── db/
│   │   └── supabase_client.py
│   ├── templates/              # Jinja2 templates de documentos
│   └── main.py                 # FastAPI app
├── frontend/
│   └── [Next.js App Router]
├── scripts/
│   └── import_products.py      # Importa os .md do banco de dados → Supabase
├── banco de dados/             # Arquivos .md dos produtos (fonte da verdade)
│   ├── just_whey_protein_concentrado.md
│   ├── just_whey_protein_isolado.md
│   └── [...14 outros produtos]
└── CLAUDE.md                   # Este arquivo
```

---

## Contexto de Negócio (Leia Para Entender o Domínio)

- **Licitação pública:** processo pelo qual órgãos públicos (hospitais, prefeituras, secretarias de saúde) compram produtos via pregão eletrônico. O menor preço compatível com o descritivo técnico vence.
- **Descritivo técnico:** texto do edital que especifica o produto desejado (composição, nutrição, registro, embalagem). A compatibilidade é analisada contra esse texto.
- **Registro MS:** Produto com Registro no Ministério da Saúde (obrigatório quando exigido). Dois produtos da Attivos têm: Just Whey Isolado e Just Whey Concentrado. Os demais são "dispensados de registro" (RDC 240/2018) — o que não é negativo, mas limita participação em editais que exigem explicitamente Registro MS.
- **Via enteral:** administração por sonda gástrica/nasoentérica. Editais hospitalares de UTI frequentemente exigem que o produto seja homologado para essa via.
- **Pregão eletrônico:** fase de disputa de preços em tempo real (chat). O sistema deve suportar monitoramento e geração de recursos nessa fase.
- **Impugnação:** recurso formal contestando o edital antes da abertura. Usada quando o descritivo é fechado para um concorrente específico (direcionado). O sistema gera minuta de impugnação.

---

## Ferramentas e Ambiente de Desenvolvimento Recomendados

### Assistente de IA Principal: Antigravity (Google DeepMind)
- **Antigravity** é o assistente de IA utilizado em todo o desenvolvimento deste projeto.
- Este arquivo `CLAUDE.md` funciona como o contexto permanente carregado antes de cada sessão — a IA lê o arquivo inteiro e já sabe o estado atual do projeto, as decisões tomadas e as regras a seguir, sem necessidade de reexplicar.
- **Fluxo de trabalho:** abrir o `CLAUDE.md` no editor → iniciar sessão no Antigravity com o arquivo como contexto → executar a tarefa do dia.
- **VS Code** como editor de código. O `CLAUDE.md` fica aberto em aba permanente durante o desenvolvimento.

### Gerenciamento de Ambiente Python
- **`uv`** (astral-sh/uv) — substitui `pip` + `venv` + `pip-tools`. Instalação de dependências 10–100x mais rápida. Comandos: `uv init`, `uv add fastapi`, `uv run python`. **Use em vez de pip.**
- **`pyenv-win`** — gerencia múltiplas versões do Python no Windows sem conflito.

### Banco de Dados e Visualização
- **Supabase Studio** (já embutido no Supabase) — interface visual para editar tabelas, testar queries SQL e visualizar embeddings. Acesse via `supabase.com/dashboard`.
- **TablePlus** — cliente de banco leve para Windows. Conecta no PostgreSQL do Supabase com a connection string. Ideal para inspecionar dados durante desenvolvimento.
- **Qdrant (alternativa ao pgvector)** — se o volume de buscas semânticas crescer muito, migrar para Qdrant dedicado. Por ora, pgvector no Supabase é suficiente.

### Testes e Qualidade
- **`pytest`** — framework de testes padrão. Estrutura: `tests/agents/test_agent4.py` com casos reais de editais.
- **`pytest-asyncio`** — necessário pois FastAPI e LangGraph são assíncronos.
- **`respx`** — mock de chamadas HTTP (para testar Agente 1 sem fazer requests reais nos portais).
- **`mypy`** — verificação de tipos estáticos. Rode antes de commitar: `uv run mypy backend/`.

### Observabilidade e Debug de Agentes
- **LangSmith** (smith.langchain.com) — ferramenta oficial do LangChain/LangGraph para rastrear execuções de agentes. Visualiza cada nó do grafo, os prompts enviados, as respostas do LLM e o tempo de cada etapa. **Essencial para debugar o Agente 3 e 4.**
  - Configuração: `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` no `.env`
- **Sentry** — monitoramento de erros em produção no Railway. Integra com FastAPI em 2 linhas.

### Desenvolvimento Frontend (Next.js) — Design System

**Identidade Visual:**
- **Fundo base:** `#0F1117` (quase preto, evita cansaço visual em sessões longas)
- **Superfícies / Cards:** `#1C1E26`
- **Bordas sutis:** `#2A2D3A`
- **Cor primária (ações, links, botões):** `#6366F1` (índigo vibrante)
- **Status Compatível:** `#22C55E` (verde)
- **Status Ressalvas:** `#F59E0B` (âmbar)
- **Status Incompatível:** `#EF4444` (vermelho)
- **Status Aprendizado / Knowledge:** `#A78BFA` (roxo claro — diferencia do fluxo principal)
- **Texto primário:** `#F1F5F9` | **Texto secundário:** `#94A3B8`
- **Tipografia:** `Inter` (Google Fonts) — legibilidade máxima em tabelas densas

**Componentes (shadcn/ui customizado):**
- Badge de score colorido por faixa (≥ 0.90 verde, 0.70–0.89 âmbar, < 0.50 vermelho)
- Tabela de editais com filtros por status, UF, órgão e data
- Painel de `knowledge_items` (gerenciar dicas e histórico de feedback)
- Modal de validação do analista (aprovar/corrigir resultado do Agente 4)
- Progress bar do pipeline (Agente 1 → 6) em tempo real

**Bibliotecas:**
- **TanStack Table** — tabelas com filtros, ordenação e paginação
- **Zustand** — estado global do `LicitContext` ativo
- **React PDF (`@react-pdf/renderer`)** — preview dos documentos gerados no browser antes do download

### Automação e Pipeline CI/CD
- **GitHub Actions** — automatiza: testes a cada PR + deploy no Railway ao fazer merge na `main`. Template básico em `.github/workflows/deploy.yml`.
- **Railway CLI** — deploy via terminal: `railway up`. Variáveis de ambiente gerenciadas pelo painel do Railway.

### Manipulação de PDF
- **`pdfplumber`** — extração de tabelas e texto com coordenadas. Melhor para PDFs nativos (gerados por Word/LibreOffice).
- **`pymupdf` (fitz)** — mais rápido que pdfplumber para extração simples de texto. Use como primeiro passo, pdfplumber como segundo se precisar de tabelas.
- **`pytesseract` + Tesseract OCR** — para PDFs escaneados (imagem). Instalar Tesseract no Railway via `apt-get` no Dockerfile. Treinar com dicionário de português.
- **`camelot-py`** — especializado em extração de tabelas complexas de PDF. Útil quando os itens do edital estão em tabela com bordas.

### Geração de Documentos
- **`python-docx`** — geração de `.docx` com estilos, tabelas e formatação. Templates `.docx` base ficam em `/templates/`.
- **`openpyxl`** — geração de `.xlsx` para proposta comercial e planilha de autorização gerencial.
- **`WeasyPrint`** — converte HTML/CSS → PDF. Alternativa mais flexível ao `reportlab` para layouts complexos. Útil para justificativa técnica com formatação rica.

### Monitoramento de Portais de Licitação
- **`playwright`** (Microsoft) — automação de browser para portais que requerem JavaScript (Comprasnet). Use `playwright install chromium`.
- **`apscheduler`** — agendamento de tarefas em Python. Configura varredura automática dos portais a cada X horas sem precisar de Celery.

### Gestão do Projeto
- **Linear** (linear.app) — gestão de tarefas técnicas (issues, sprints). Alternativa mais moderna ao Jira, grátis para times pequenos.
- **Notion** — documentação de processo do setor de licitações (não técnica). Integra com o Linear via automação.

---

### Ordem de Instalação Recomendada (Início Imediato)

```bash
# 1. Instalar uv (gerenciador Python moderno)
pip install uv

# 2. Iniciar projeto backend
uv init backend
cd backend
uv add fastapi uvicorn pdfplumber pymupdf python-docx openpyxl \
       langchain langgraph langchain-anthropic langchain-openai \
       supabase pydantic structlog python-dotenv pytest pytest-asyncio

# 3. Instalar Playwright para scraping
uv add playwright
uv run playwright install chromium

# 4. Frontend
npx create-next-app@latest frontend --typescript --app --tailwind
cd frontend
npx shadcn-ui@latest init
npm install @tanstack/react-table zustand
```
