'use client';
import { useEffect, useState } from 'react';
import styles from './painel.module.css';
import { api } from '../lib/api';
import { brl, brlCurto, dataBr, mesBr } from '../lib/formato';

interface Resumo {
  resumo: {
    faturado?: number; a_receber?: number; notas?: number; media_12m?: number;
    top1?: number; top5?: number; periodo?: string[]; por_mes?: Record<string, number>;
  };
  regras: string[];
}
interface Cliente { nome: string; uf?: string; municipio?: string; total: number; notas: number; vencido?: number; em_aberto?: number; ultima_compra?: string }
interface AnaliseOrgao { cliente_existente: boolean; sinais: string[]; prioridade: string; cliente?: Cliente }

export function InteligenciaView({ avisar }: { avisar: (m: string, t: 'ok' | 'err') => void }) {
  const [dados, setDados] = useState<Resumo | null>(null);
  const [clientes, setClientes] = useState<Cliente[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [orgao, setOrgao] = useState('');
  const [uf, setUf] = useState('');
  const [analise, setAnalise] = useState<AnaliseOrgao | null>(null);

  useEffect(() => {
    Promise.all([
      api<Resumo>('products/inteligencia/resumo'),
      api<{ data: Cliente[] }>('products/inteligencia/clientes?limite=15'),
    ])
      .then(([r, c]) => { setDados(r); setClientes(c.data ?? []); })
      .catch(e => avisar(e instanceof Error ? e.message : 'Falha ao carregar a inteligência.', 'err'))
      .finally(() => setCarregando(false));
  }, [avisar]);

  const consultar = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!orgao.trim()) return;
    try {
      const p = new URLSearchParams({ nome: orgao.trim() });
      if (uf.trim()) p.set('uf', uf.trim().toUpperCase());
      setAnalise(await api<AnaliseOrgao>(`products/inteligencia/orgao?${p}`));
    } catch (e) {
      avisar(e instanceof Error ? e.message : 'Falha na consulta.', 'err');
    }
  };

  if (carregando) return <div className={styles.emptyState}><div className={styles.spinner} /><p>Carregando histórico...</p></div>;
  const r = dados?.resumo ?? {};
  const meses = Object.entries(r.por_mes ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const maxMes = Math.max(1, ...meses.map(([, v]) => v));
  const maxCli = Math.max(1, ...clientes.map(c => c.total));

  return (
    <>
      <header className={styles.topbar}>
        <div>
          <h1 className={styles.pageTitle}>Inteligência</h1>
          <p className={styles.pageSub}>
            Histórico de vendas e recebimentos{r.periodo?.length === 2 ? ` de ${dataBr(r.periodo[0] + 'T12:00')} a ${dataBr(r.periodo[1] + 'T12:00')}` : ''}
          </p>
        </div>
      </header>

      <div className={styles.kpis}>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Faturado</span><b className={styles.kpiValor}>{brlCurto(r.faturado ?? 0)}</b><span className={styles.kpiSub}>{r.notas ?? 0} notas</span></div>
        <div className={styles.kpi}><span className={styles.kpiLabel}>A receber</span><b className={styles.kpiValor}>{brlCurto(r.a_receber ?? 0)}</b></div>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Média 12 meses</span><b className={styles.kpiValor}>{brlCurto(r.media_12m ?? 0)}</b><span className={styles.kpiSub}>por mês</span></div>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Concentração</span><b className={styles.kpiValor}>{(r.top5 ?? 0).toLocaleString('pt-BR')}%</b><span className={styles.kpiSub}>nos 5 maiores (maior: {(r.top1 ?? 0).toLocaleString('pt-BR')}%)</span></div>
      </div>

      <div className={styles.panel}>
        <div className={styles.panelTitle}>Faturamento por mês</div>
        <div className={styles.chart} role="img" aria-label="Faturamento mensal">
          {meses.map(([m, v], i) => (
            <div key={m} className={styles.chartCol} title={`${mesBr(m)}: ${brl(v)}`}>
              <div className={styles.chartBar} style={{ height: `${(v / maxMes) * 100}%` }} />
              {/* Com 24 meses, rótulo a cada trimestre para não embolar. */}
              <span className={styles.chartLabel}>{(meses.length - 1 - i) % 3 === 0 ? mesBr(m) : ' '}</span>
            </div>
          ))}
        </div>
      </div>

      <div className={styles.grid2}>
        <div className={styles.panel}>
          <div className={styles.panelTitle}>Maiores compradores</div>
          {clientes.map((c, i) => {
            // Nome genérico ("Fundo Municipal de Saúde") só faz sentido com o município.
            const local = [c.municipio && !c.nome.toLowerCase().includes(c.municipio.toLowerCase()) ? c.municipio : '', c.uf].filter(Boolean).join('/');
            return (
            <div key={`${c.nome}-${c.municipio}-${c.uf}-${i}`} className={styles.hbar} title={`${c.nome}${local ? ` (${local})` : ''}: ${brl(c.total)} em ${c.notas} notas`}>
              <span>{c.nome}{local ? ` · ${local}` : ''}</span>
              <div className={styles.hbarTrack}><div className={`${styles.hbarFill} ${(c.vencido ?? 0) > 0 ? styles.hbarFillAlerta : ''}`} style={{ width: `${(c.total / maxCli) * 100}%` }} /></div>
              <b>{brlCurto(c.total)}</b>
            </div>
            );
          })}
          <p className={styles.kpiSub} style={{ marginTop: 8 }}>Barra âmbar: cliente com valor vencido.</p>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelTitle}>Consultar órgão antes de disputar</div>
          <form onSubmit={consultar} className={styles.filters}>
            <input className={styles.input} style={{ flex: '1 1 200px' }} placeholder="Ex.: Prefeitura Municipal de Marília" value={orgao} onChange={e => setOrgao(e.target.value)} aria-label="Órgão" />
            <input className={styles.input} style={{ width: 70 }} placeholder="UF" maxLength={2} value={uf} onChange={e => setUf(e.target.value)} aria-label="UF" />
            <button className={styles.btnPrimary}>Consultar</button>
          </form>
          {analise && (
            <ul className={styles.lista} style={{ marginTop: 12 }}>
              {analise.sinais.map((s, i) => <li key={i} style={analise.prioridade === 'atencao' && i > 0 ? { borderLeftColor: 'var(--amber)' } : undefined}>{s}</li>)}
            </ul>
          )}

          <div className={styles.panelTitle} style={{ marginTop: 20 }}>Regras aprendidas</div>
          <ul className={styles.lista}>
            {(dados?.regras ?? []).map((regra, i) => <li key={i}>{regra}</li>)}
          </ul>
        </div>
      </div>
    </>
  );
}
