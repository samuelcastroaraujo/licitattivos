export const brl = (valor: number) =>
  valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

export const brlCurto = (valor: number) => {
  if (Math.abs(valor) >= 1_000_000) return `R$ ${(valor / 1_000_000).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} mi`;
  if (Math.abs(valor) >= 1_000) return `R$ ${(valor / 1_000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mil`;
  return brl(valor);
};

export const dataBr = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' }) : '—';

export const horaBr = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo' }) : '';

/** "hoje", "amanhã", "em 5 dias", "encerrado" — conta dias de calendário em Brasília. */
export function prazo(iso?: string | null): { texto: string; tom: 'urgente' | 'perto' | 'normal' | 'passado' } {
  if (!iso) return { texto: 'sem data', tom: 'normal' };
  const dia = (d: Date) => d.toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' });
  const alvo = new Date(iso);
  if (alvo.getTime() < Date.now()) return { texto: 'encerrado', tom: 'passado' };
  const dias = Math.round((Date.parse(dia(alvo)) - Date.parse(dia(new Date()))) / 86_400_000);
  if (dias <= 0) return { texto: `hoje ${horaBr(iso)}`, tom: 'urgente' };
  if (dias === 1) return { texto: `amanhã ${horaBr(iso)}`, tom: 'urgente' };
  return { texto: `em ${dias} dias`, tom: dias <= 7 ? 'perto' : 'normal' };
}

export const mesBr = (aaaaMm: string) => {
  const [a, m] = aaaaMm.split('-');
  const nomes = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  return `${nomes[Number(m) - 1]}/${a.slice(2)}`;
};
