'use client';
import { useCallback, useEffect, useMemo, useState } from 'react';
import styles from './painel.module.css';
import { API, api, postar } from '../lib/api';
import { dataBr } from '../lib/formato';

interface Arquivo { nome: string; titulo: string; docx: string | null; pdf: string | null }
interface Lote { data: string; arquivos: Arquivo[] }
interface PregaoDocs {
  id: string;
  numero_pregao: string;
  orgao: string;
  uf?: string | null;
  data_abertura?: string | null;
  documentos?: { status: string; arquivos?: Arquivo[]; avisos?: string[]; erro?: string } | null;
}

const link = (caminho: string) => `${API}/documentos/baixar?caminho=${encodeURIComponent(caminho)}`;
const dataLote = (aaaaMmDd: string) => dataBr(`${aaaaMmDd}T12:00:00`);

function Links({ arquivo }: { arquivo: Arquivo }) {
  return (
    <div className={styles.rowActions}>
      {arquivo.pdf && <a className={`${styles.btnSmall} ${styles.btnSmallPrimary}`} href={link(arquivo.pdf)} target="_blank" rel="noreferrer">PDF</a>}
      {arquivo.docx && <a className={styles.btnSmall} href={link(arquivo.docx)}>DOCX</a>}
    </div>
  );
}

export function DocumentosView({ avisar }: { avisar: (m: string, t: 'ok' | 'err') => void }) {
  const [lotes, setLotes] = useState<Lote[]>([]);
  const [dias, setDias] = useState(30);
  const [pregoes, setPregoes] = useState<PregaoDocs[]>([]);
  const [loteAberto, setLoteAberto] = useState<string | null>(null);
  const [carregado, setCarregado] = useState(false);
  const [gerando, setGerando] = useState(false);
  const [busca, setBusca] = useState('');
  const [agora] = useState(() => Date.now());

  const carregar = useCallback(async () => {
    try {
      const [e, p] = await Promise.all([
        api<{ lotes: Lote[]; dias_renovacao: number }>('documentos/estoque'),
        api<{ data: PregaoDocs[] }>('documentos/pregoes'),
      ]);
      setLotes(e.lotes ?? []);
      setDias(e.dias_renovacao ?? 30);
      setPregoes(p.data ?? []);
    } catch (erro) {
      avisar(erro instanceof Error ? erro.message : 'Falha ao carregar documentos.', 'err');
    } finally {
      setCarregado(true);
    }
  }, [avisar]);

  useEffect(() => {
    const t = setTimeout(carregar, 0);
    return () => clearTimeout(t);
  }, [carregar]);

  const gerarLote = async () => {
    setGerando(true);
    avisar('Gerando o lote de declarações (DOCX e PDF). Leva cerca de 1 minuto...', 'ok');
    try {
      await postar('documentos/estoque?forcar=true');
      avisar('Lote novo no estoque.', 'ok');
      await carregar();
    } catch (erro) {
      avisar(erro instanceof Error ? erro.message : 'Falha ao gerar o lote.', 'err');
    } finally {
      setGerando(false);
    }
  };

  const ultimo = lotes[0];
  const idadeUltimo = ultimo ? Math.floor((agora - Date.parse(`${ultimo.data}T12:00:00`)) / 86_400_000) : null;
  const aberto = lotes.find(l => l.data === (loteAberto ?? ultimo?.data));
  const pregoesFiltrados = useMemo(() => {
    const alvo = busca.toLowerCase();
    return pregoes.filter(p => !alvo || `${p.orgao} ${p.numero_pregao}`.toLowerCase().includes(alvo));
  }, [pregoes, busca]);

  return (
    <>
      <header className={styles.topbar}>
        <div>
          <h1 className={styles.pageTitle}>Documentos</h1>
          <p className={styles.pageSub}>Estoque de declarações renovado a cada {dias} dias e os documentos de cada pregão aprovado</p>
        </div>
        <div className={styles.acoes}>
          <button className={styles.btnPrimary} onClick={gerarLote} disabled={gerando}>
            {gerando ? <span className={`${styles.spinner} ${styles.spinnerSmall}`} /> : '📄'} Gerar lote agora
          </button>
        </div>
      </header>

      <div className={styles.kpis}>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Último lote</span><b className={styles.kpiValor}>{ultimo ? dataLote(ultimo.data) : '—'}</b>
          <span className={styles.kpiSub}>{idadeUltimo !== null ? `há ${idadeUltimo} dia${idadeUltimo === 1 ? '' : 's'}` : 'nenhum ainda'}</span></div>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Próxima renovação</span><b className={styles.kpiValor}>{idadeUltimo !== null ? `${Math.max(0, dias - idadeUltimo)} dias` : 'hoje'}</b>
          <span className={styles.kpiSub}>automática</span></div>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Lotes guardados</span><b className={styles.kpiValor}>{lotes.length}</b></div>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Pregões com documentos</span><b className={styles.kpiValor}>{pregoes.filter(p => p.documentos?.status === 'pronto').length}</b></div>
      </div>

      <div className={styles.panel}>
        <div className={styles.filters} style={{ justifyContent: 'space-between', marginBottom: 10 }}>
          <div className={styles.panelTitle} style={{ margin: 0 }}>Estoque de declarações</div>
          {lotes.length > 1 && (
            <select className={styles.select} value={aberto?.data ?? ''} onChange={e => setLoteAberto(e.target.value)} aria-label="Lote">
              {lotes.map(l => <option key={l.data} value={l.data}>Lote de {dataLote(l.data)}</option>)}
            </select>
          )}
        </div>
        {!carregado ? (
          <div className={styles.emptyState}><div className={styles.spinner} /></div>
        ) : !aberto ? (
          <div className={styles.emptyState}><p className={styles.emptyIcon}>🗂️</p><p>Nenhum lote ainda. O primeiro sai sozinho quando o servidor liga, ou clique em “Gerar lote agora”.</p></div>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr><th>Declaração</th><th>Emitida em</th><th></th></tr></thead>
              <tbody>
                {aberto.arquivos.map(a => (
                  <tr key={a.nome}>
                    <td className={styles.cardTitle} data-label=""><span className={styles.orgao}>{a.titulo}</span></td>
                    <td data-label="Emitida em">{dataLote(aberto.data)}</td>
                    <td className={styles.cardActions} data-label=""><Links arquivo={a} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className={styles.filters}>
        <div className={styles.searchWrap}>
          <span className={styles.searchIcon}>🔍</span>
          <input className={styles.input} placeholder="Buscar pregão aprovado por órgão ou número..." value={busca} onChange={e => setBusca(e.target.value)} aria-label="Buscar pregão" />
        </div>
      </div>

      {carregado && pregoesFiltrados.length === 0 ? (
        <div className={styles.tableWrap}><div className={styles.emptyState}><p className={styles.emptyIcon}>📭</p><p>Nenhum pregão aprovado ainda. Aprove um edital compatível para gerar proposta e declarações.</p></div></div>
      ) : (
        pregoesFiltrados.map(p => (
          <div key={p.id} className={styles.panel}>
            <div className={styles.panelTitle} style={{ marginBottom: 2 }}>{p.orgao}</div>
            <p className={styles.sub} style={{ marginBottom: 10 }}>Pregão {p.numero_pregao.split(' #')[0]}{p.uf ? ` · ${p.uf}` : ''}{p.data_abertura ? ` · abertura ${dataBr(p.data_abertura)}` : ''}</p>
            {p.documentos?.status === 'gerando' && <p className={styles.sub}>⟳ Gerando documentos...</p>}
            {p.documentos?.status === 'erro' && <div className={`${styles.aviso} ${styles.avisoErro}`}>{p.documentos.erro}</div>}
            {!p.documentos && <p className={styles.sub}>Documentos ainda não gerados. Abra o edital e use “Gerar documentos de novo”.</p>}
            {(p.documentos?.arquivos ?? []).length > 0 && (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <tbody>
                    {(p.documentos?.arquivos ?? []).map(a => (
                      <tr key={a.nome}>
                        <td className={styles.cardTitle} data-label=""><span className={styles.orgao}>{a.titulo}</span></td>
                        <td className={styles.cardActions} data-label=""><Links arquivo={a} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {(p.documentos?.avisos ?? []).map((aviso, i) => <div key={i} className={styles.aviso} style={{ marginTop: 8 }}>{aviso}</div>)}
          </div>
        ))
      )}
    </>
  );
}
