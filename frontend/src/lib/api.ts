// Tudo passa pelo servidor do painel, que guarda o token da API.
export const API = '/api/backend';

export class ErroApi extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export async function api<T>(caminho: string, init?: RequestInit): Promise<T> {
  let resposta: Response;
  try {
    resposta = await fetch(`${API}/${caminho.replace(/^\//, '')}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
      cache: 'no-store',
    });
  } catch {
    throw new ErroApi('Sem conexão com o painel.', 0);
  }
  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    const detalhe = corpo?.detail;
    const texto = typeof detalhe === 'string' ? detalhe : resposta.status === 503 ? 'Backend offline.' : `Erro ${resposta.status}.`;
    throw new ErroApi(texto, resposta.status);
  }
  return corpo as T;
}

export const postar = <T,>(caminho: string, corpo?: unknown) =>
  api<T>(caminho, { method: 'POST', body: corpo === undefined ? undefined : JSON.stringify(corpo) });

// ── Tipos compartilhados ──────────────────────────────────────────────────
export interface Edital {
  id: string;
  numero_pregao: string;
  orgao: string;
  uf?: string | null;
  status: string;
  portal_origem: string;
  url_edital?: string | null;
  data_abertura?: string | null;
  licit_context?: Record<string, unknown>;
  created_at: string;
}

export interface LicitItem {
  id: string;
  numero_item: string;
  descricao_original: string;
  tipo_produto?: string;
  score_compatibilidade?: number;
  compativel?: boolean | null;
  produto_nome?: string | null;
  status?: string;
  justificativa?: string;
  alertas?: string[];
  preco_referencia?: number | null;
  requisitos?: Record<string, unknown>;
}

export interface ResumoEditais {
  total: number;
  abertos: number;
  abrem_7_dias: number;
  por_status: Record<string, number>;
  por_uf: Record<string, number>;
}

export interface Produto {
  id: string;
  slug: string;
  nome_comercial: string;
  marca?: string | null;
  categoria?: string | null;
  linha_clinica?: string | null;
  registro_anvisa?: string | null;
  tem_registro_ms: boolean;
  via_enteral?: boolean;
  publico_alvo?: string | null;
  porcao_g?: number | null;
  kcal_por_porcao?: number | null;
  proteinas_por_porcao_g?: number | null;
  sem_gluten?: boolean;
  sem_lactose?: boolean;
  sem_sacarose?: boolean;
}
