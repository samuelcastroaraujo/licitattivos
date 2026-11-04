'use client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import styles from './painel.module.css';
import { ValidationModal, type LinhaProposta } from './ValidationModal';
import { API, api, postar, type Edital, type LicitItem, type Produto, type ResumoEditais } from '../lib/api';
import { brlCurto, dataBr, prazo } from '../lib/formato';

type Avisar = (msg: string, tipo: 'ok' | 'err') => void;

const STATUS: Record<string, { label: string; cls: keyof typeof styles }> = {
  novo:                      { label: 'Novo',              cls: 'badgeMuted' },
  em_analise:                { label: 'Em análise',        cls: 'badgeBrand' },
  anexo_baixado:             { label: 'Baixado',           cls: 'badgeBrand' },
  texto_extraido:            { label: 'Lido',              cls: 'badgeBrand' },
  requisitos_extraidos:      { label: 'Itens extraídos',   cls: 'badgeBrand' },
  compativel:                { label: 'Compatível · participar', cls: 'badgeVerde' },
  compatibilidade_calculada: { label: 'Analisado',         cls: 'badgeMuted' },
  pendente_revisao_juridica: { label: 'Revisão jurídica',  cls: 'badgeAmbar' },
  pronto_para_envio:         { label: 'Aprovado',          cls: 'badgeBrand' },
  revisao_manual_parser:     { label: 'Revisão manual',    cls: 'badgeAmbar' },
  erro_pipeline:             { label: 'Erro na análise',   cls: 'badgeVermelho' },
  erro_download:             { label: 'Erro no download',  cls: 'badgeVermelho' },
  arquivado:                 { label: 'Arquivado',         cls: 'badgeMuted' },
};
const ANALISAVEIS = ['novo', 'erro_pipeline', 'erro_download', 'revisao_manual_parser'];
const APROVAVEIS = ['compativel', 'compatibilidade_calculada', 'pendente_revisao_juridica'];
const EM_CURSO = ['em_analise', 'anexo_baixado', 'texto_extraido', 'requisitos_extraidos'];

function StatusBadge({ status }: { status: string }) {
  const m = STATUS[status] ?? { label: status, cls: 'badgeMuted' as const };
  return <span className={styles[m.cls]}>{EM_CURSO.includes(status) && <span className={`${styles.spinner} ${styles.spinnerSmall}`} />}{m.label}</span>;
}

function ScoreBadge({ score }: { score?: number }) {
  if (score === undefined || score === null) return <span className={styles.prazo_passado}>—</span>;
  const cls = score >= 0.9 ? 'badgeVerde' : score >= 0.7 ? 'badgeAmbar' : 'badgeVermelho';
  return <span className={styles[cls]}>● {(score * 100).toFixed(0)}%</span>;
}

export function EditaisView({ avisar }: { avisar: Avisar }) {
  const [editais, setEditais] = useState<Edital[]>([]);
  const [resumo, setResumo] = useState<ResumoEditais | null>(null);
  // Carregando = a lista na tela ainda não é da consulta atual.
  const [carregadoPara, setCarregadoPara] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [busca, setBusca] = useState('');
  const [orgao, setOrgao] = useState('');
  const [status, setStatus] = useState('');
  const [uf, setUf] = useState('');
  const [abertos, setAbertos] = useState(true);
  const [buscando, setBuscando] = useState<'' | 'conlicitacao' | 'pncp'>('');

  const [selecionado, setSelecionado] = useState<Edital | null>(null);
  const [itens, setItens] = useState<LicitItem[]>([]);
  const [carregandoItens, setCarregandoItens] = useState(false);
  const pedidoAtual = useRef(0);
  const [produtos, setProdutos] = useState<Produto[]>([]);

  // Espera o usuário parar de digitar antes de consultar.
  useEffect(() => {
    const t = setTimeout(() => setOrgao(busca.trim()), 400);
    return () => clearTimeout(t);
  }, [busca]);

  const consulta = useMemo(() => {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (orgao) params.set('orgao', orgao);
    if (uf) params.set('uf', uf);
    if (abertos) params.set('abertos', 'true');
    return params.toString();
  }, [status, orgao, uf, abertos]);
  const carregando = carregadoPara !== consulta;

  const carregar = useCallback(async (silencioso = false) => {
    const pedido = ++pedidoAtual.current;
    const params = consulta;
    if (!silencioso) setCarregadoPara(null);
    try {
      const [lista, res] = await Promise.all([
        api<{ data: Edital[] }>(`editais?${params}`),
        api<ResumoEditais>('editais/resumo'),
      ]);
      if (pedido !== pedidoAtual.current) return;
      setEditais(lista.data ?? []);
      setResumo(res);
      setOffline(false);
    } catch (erro) {
      if (pedido !== pedidoAtual.current) return;
      // Nunca mostrar dado fictício em tela de decisão.
      setEditais([]);
      setOffline(true);
      if (!silencioso) avisar(erro instanceof Error ? erro.message : 'Falha ao carregar.', 'err');
    } finally {
      if (pedido === pedidoAtual.current) setCarregadoPara(params);
    }
  }, [consulta, avisar]);

  // Primeira carga e troca de filtro: dispara a consulta sem setState síncrono no efeito.
  useEffect(() => {
    const t = setTimeout(() => carregar(true), 0);
    return () => clearTimeout(t);
  }, [carregar]);

  // Enquanto houver análise rodando, atualiza sozinho.
  const rodando = editais.some(e => EM_CURSO.includes(e.status)
    || (e.licit_context?.documentos as { status?: string } | undefined)?.status === 'gerando');
  useEffect(() => {
    if (!rodando) return;
    const t = setInterval(() => carregar(true), 8000);
    return () => clearInterval(t);
  }, [rodando, carregar]);

  const buscarEditais = async (fonte: 'conlicitacao' | 'pncp') => {
    setBuscando(fonte);
    avisar(fonte === 'pncp' ? 'Buscando no PNCP. Pode levar alguns minutos...' : 'Buscando na ConLicitação...', 'ok');
    try {
      const r = await postar<{ salvos: number }>(fonte === 'pncp' ? 'pipeline/ingest/pncp' : 'pipeline/ingest/conlicitacao', fonte === 'pncp' ? {} : undefined);
      avisar(`${r.salvos} editais encontrados ou atualizados.`, 'ok');
      carregar();
    } catch (erro) {
      avisar(erro instanceof Error ? erro.message : 'Falha na busca.', 'err');
    } finally {
      setBuscando('');
    }
  };

  // A análise usa IA paga: só roda para o edital escolhido.
  const analisar = async (edital: Edital) => {
    try {
      await postar(`pipeline/run/${edital.id}`);
      setEditais(prev => prev.map(e => e.id === edital.id ? { ...e, status: 'em_analise' } : e));
      avisar('Análise iniciada. A lista atualiza sozinha.', 'ok');
    } catch (erro) {
      avisar(erro instanceof Error ? erro.message : 'Não foi possível iniciar a análise.', 'err');
    }
  };

  const abrir = async (edital: Edital) => {
    if (produtos.length === 0) {
      // Lista para o analista corrigir o produto de um item (só Pholias entra na análise).
      api<{ data: Produto[] }>('products')
        .then(r => setProdutos((r.data ?? []).filter(p => (p.marca ?? '').toUpperCase() === 'PHOLIAS')))
        .catch(() => undefined);
    }
    setSelecionado(edital);
    setItens([]);
    setCarregandoItens(true);
    try {
      const r = await api<{ edital: Edital; itens: LicitItem[] }>(`editais/${edital.id}`);
      let detalhe = r.edital;
      if (!detalhe.licit_context?.precificacao && (r.itens ?? []).some(i => i.produto_nome)) {
        // Edital analisado antes da tabela de preços: calcula agora (sem IA, leva 1 ou 2 segundos).
        try {
          const precificacao = await postar<Record<string, unknown>>(`editais/${edital.id}/precificar`);
          detalhe = { ...detalhe, licit_context: { ...(detalhe.licit_context ?? {}), precificacao } };
        } catch {
          /* segue sem preço; o relatório mostra os itens normalmente */
        }
      }
      setSelecionado(detalhe);
      setItens(r.itens ?? []);
    } catch (erro) {
      avisar(erro instanceof Error ? erro.message : 'Não foi possível carregar os itens.', 'err');
    } finally {
      setCarregandoItens(false);
    }
  };

  // Atualiza o relatório aberto sem piscar (usado enquanto os documentos são gerados).
  const recarregarAberto = useCallback(async (id: string) => {
    try {
      const r = await api<{ edital: Edital; itens: LicitItem[] }>(`editais/${id}`);
      setSelecionado(atual => (atual && atual.id === id ? r.edital : atual));
    } catch {
      /* mantém o que está na tela */
    }
  }, []);

  const docsGerando = (selecionado?.licit_context?.documentos as { status?: string } | undefined)?.status === 'gerando';
  useEffect(() => {
    if (!selecionado || !docsGerando) return;
    const id = selecionado.id;
    const t = setInterval(() => recarregarAberto(id), 4000);
    return () => clearInterval(t);
  }, [selecionado, docsGerando, recarregarAberto]);

  const aprovar = async (id: string, nota: string, gaps: Record<string, string>, justificativas: Record<string, string>, proposta?: LinhaProposta[]) => {
    try {
      // Só manda a justificativa que o analista de fato mudou.
      const mudadas = Object.fromEntries(Object.entries(justificativas).filter(([itemId, texto]) =>
        texto !== (itens.find(i => i.id === itemId)?.justificativa ?? '')));
      await postar(`editais/${id}/approve`, { analista_nota: nota, gap_correcoes: gaps, justificativas: mudadas, proposta: proposta ?? [] });
      avisar('Edital aprovado. Gerando proposta e declarações...', 'ok');
      // O relatório continua aberto e mostra os documentos quando ficarem prontos.
      await recarregarAberto(id);
      carregar(true);
    } catch (erro) {
      avisar(erro instanceof Error ? erro.message : 'Erro ao aprovar.', 'err');
    }
  };

  const gerarResumo = async () => {
    if (!selecionado) return;
    try {
      await postar(`editais/${selecionado.id}/resumo`);
      await recarregarAberto(selecionado.id);
      avisar('Resumo do edital gerado.', 'ok');
    } catch (erro) {
      avisar(erro instanceof Error ? erro.message : 'Falha ao gerar o resumo.', 'err');
    }
  };

  const regerarDocumentos = async (proposta: LinhaProposta[]) => {
    if (!selecionado) return;
    try {
      await postar(`editais/${selecionado.id}/documentos`, { proposta });
      await recarregarAberto(selecionado.id);
    } catch (erro) {
      avisar(erro instanceof Error ? erro.message : 'Falha ao gerar documentos.', 'err');
    }
  };

  const rejeitar = async (id: string, motivo?: string) => {
    try {
      await postar(`editais/${id}/reject`, { motivo });
      avisar('Edital arquivado.', 'ok');
      setSelecionado(null);
      carregar();
    } catch (erro) {
      avisar(erro instanceof Error ? erro.message : 'Erro ao arquivar.', 'err');
    }
  };

  const enviarFeedback = async (itemId: string, correto: boolean, produtoCorretoId: string | null, motivo: string) => {
    if (!selecionado) return;
    await postar(`editais/${selecionado.id}/itens/${itemId}/feedback`, { correto, produto_correto_id: produtoCorretoId, motivo });
  };

  const reaplicar = async () => {
    if (!selecionado) return;
    try {
      const r = await postar<{ status: string; itens: number }>(`pipeline/reaplicar/${selecionado.id}`);
      avisar(r.status === 'compativel' ? 'Recalculado: edital compatível para participar!' : `Recalculado com o aprendizado (${r.itens} itens).`, 'ok');
      await abrir(selecionado);
      carregar(true);
    } catch (erro) {
      avisar(erro instanceof Error ? erro.message : 'Falha ao recalcular.', 'err');
    }
  };

  const reabrir = async (edital: Edital) => {
    try {
      await postar(`editais/${edital.id}/reabrir`);
      avisar('Edital reaberto.', 'ok');
      carregar();
    } catch (erro) {
      avisar(erro instanceof Error ? erro.message : 'Erro ao reabrir.', 'err');
    }
  };

  const ufs = useMemo(() => Object.keys(resumo?.por_uf ?? {}).filter(u => u !== '—').sort(), [resumo]);
  const porStatus = resumo?.por_status ?? {};
  const analisados = (porStatus.compatibilidade_calculada ?? 0) + (porStatus.pendente_revisao_juridica ?? 0);
  const compativeis = porStatus.compativel ?? 0;
  const kpis: { label: string; valor: number; sub: string; filtro?: string }[] = [
    { label: 'Abertos', valor: resumo?.abertos ?? 0, sub: `de ${resumo?.total ?? 0} na base` },
    { label: 'Abrem em 7 dias', valor: resumo?.abrem_7_dias ?? 0, sub: 'prioridade de análise' },
    { label: 'Compatíveis', valor: compativeis, sub: 'têm item 100%: participar', filtro: 'compativel' },
    { label: 'Analisados', valor: analisados, sub: 'sem item 100%', filtro: 'compatibilidade_calculada,pendente_revisao_juridica' },
    { label: 'Aprovados', valor: porStatus.pronto_para_envio ?? 0, sub: 'prontos para envio', filtro: 'pronto_para_envio' },
    { label: 'Com erro', valor: (porStatus.erro_pipeline ?? 0) + (porStatus.erro_download ?? 0) + (porStatus.revisao_manual_parser ?? 0), sub: 'precisam de atenção', filtro: 'erro_pipeline,erro_download,revisao_manual_parser' },
  ];

  return (
    <>
      <header className={styles.topbar}>
        <div>
          <h1 className={styles.pageTitle}>Editais</h1>
          <p className={styles.pageSub}>Busca, análise de compatibilidade e decisão do analista</p>
        </div>
        <div className={styles.acoes}>
          <button className={styles.btn} onClick={() => buscarEditais('pncp')} disabled={!!buscando}>
            {buscando === 'pncp' ? <span className={`${styles.spinner} ${styles.spinnerSmall}`} /> : '🏛️'} Buscar no PNCP
          </button>
          <button className={styles.btnPrimary} onClick={() => buscarEditais('conlicitacao')} disabled={!!buscando}>
            {buscando === 'conlicitacao' ? <span className={`${styles.spinner} ${styles.spinnerSmall}`} /> : '🔎'} Buscar na ConLicitação
          </button>
        </div>
      </header>

      {offline && <div className={`${styles.aviso} ${styles.avisoErro}`}>Backend fora do ar. Confira se o servidor da API está rodando na porta 8000.</div>}

      <div className={styles.kpis}>
        {kpis.map(k => k.filtro ? (
          <button key={k.label} className={`${styles.kpi} ${status === k.filtro ? styles.kpiAtivo : ''}`}
            onClick={() => { setStatus(status === k.filtro ? '' : k.filtro!); setAbertos(false); }}>
            <span className={styles.kpiLabel}>{k.label} ›</span>
            <b className={styles.kpiValor}>{k.valor}</b>
            <span className={styles.kpiSub}>{k.sub}</span>
          </button>
        ) : (
          <div key={k.label} className={styles.kpi}>
            <span className={styles.kpiLabel}>{k.label}</span>
            <b className={styles.kpiValor}>{k.valor}</b>
            <span className={styles.kpiSub}>{k.sub}</span>
          </div>
        ))}
      </div>

      <div className={styles.filters}>
        <div className={styles.searchWrap}>
          <span className={styles.searchIcon}>🔍</span>
          <input className={styles.input} placeholder="Filtrar por órgão..." value={busca} onChange={e => setBusca(e.target.value)} aria-label="Filtrar por órgão" />
        </div>
        <select className={styles.select} value={status} onChange={e => setStatus(e.target.value)} aria-label="Status">
          <option value="">Todos os status</option>
          <option value="erro_pipeline,erro_download,revisao_manual_parser">Com erro (todos)</option>
          {Object.entries(STATUS).map(([v, m]) => <option key={v} value={v}>{m.label}</option>)}
        </select>
        <select className={styles.select} value={uf} onChange={e => setUf(e.target.value)} aria-label="UF">
          <option value="">Todas as UFs</option>
          {ufs.map(u => <option key={u} value={u}>{u} ({resumo?.por_uf[u]})</option>)}
        </select>
        <label className={styles.toggle}>
          <input type="checkbox" checked={abertos} onChange={e => setAbertos(e.target.checked)} /> Só abertos
        </label>
        <button className={styles.btnGhost} onClick={() => carregar()} title="Atualizar">⟳ Atualizar</button>
      </div>

      <div className={styles.tableWrap}>
        {carregando ? (
          <div className={styles.emptyState}><div className={styles.spinner} /><p>Carregando editais...</p></div>
        ) : editais.length === 0 ? (
          <div className={styles.emptyState}>
            <p className={styles.emptyIcon}>📭</p>
            <p>{offline ? 'Sem conexão com o backend.' : 'Nenhum edital com esses filtros.'}</p>
          </div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Órgão / Pregão</th>
                <th>UF</th>
                <th>Abertura</th>
                <th>Status</th>
                <th>Score</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {editais.map(e => {
                const p = prazo(e.data_abertura);
                const ctx = e.licit_context ?? {};
                const erro = ctx.erro_pipeline as string | undefined;
                const emCurso = EM_CURSO.includes(e.status);
                const temAnalise = typeof ctx.score_medio === 'number' || APROVAVEIS.includes(e.status) || e.status === 'pronto_para_envio';
                return (
                  <tr key={e.id}>
                    <td className={styles.cardTitle} data-label="">
                      <span className={styles.orgao}>{e.orgao}</span>
                      <span className={styles.sub}>
                        <span className={styles.mono}>{e.numero_pregao}</span> · <span className={styles.portal}>{e.portal_origem.toUpperCase()}</span>
                        {e.url_edital && <> · <a className={styles.link} href={e.url_edital} target="_blank" rel="noreferrer">abrir ↗</a></>}
                      </span>
                      {erro && ['erro_pipeline', 'erro_download', 'revisao_manual_parser'].includes(e.status) && <span className={styles.erroTexto}>{erro}</span>}
                    </td>
                    <td data-label="UF">{e.uf ?? '—'}</td>
                    <td data-label="Abertura">
                      <span className={styles.prazo}>{dataBr(e.data_abertura)}</span>
                      <span className={`${styles.sub} ${styles[`prazo_${p.tom}`]}`}>{p.texto}</span>
                    </td>
                    <td data-label="Status">
                      <StatusBadge status={e.status} />
                      {Array.isArray(ctx.itens_100) && ctx.itens_100.length > 0 && (
                        <span className={styles.sub}>Item{ctx.itens_100.length > 1 ? 's' : ''} 100%: {(ctx.itens_100 as string[]).join(', ')}</span>
                      )}
                    </td>
                    <td data-label="Score">
                      <ScoreBadge score={ctx.score_medio as number | undefined} />
                      {typeof (ctx.precificacao as { total?: number } | undefined)?.total === 'number' && (ctx.precificacao as { total: number }).total > 0 && (
                        <span className={styles.sub} title="Soma dos itens compatíveis pelo preço mínimo da tabela">
                          {brlCurto((ctx.precificacao as { total: number }).total)} mín.
                        </span>
                      )}
                    </td>
                    <td className={styles.cardActions} data-label="">
                      <div className={styles.rowActions}>
                        {ANALISAVEIS.includes(e.status) && (
                          <button className={styles.btnSmall} onClick={() => analisar(e)}>
                            {e.status === 'novo' ? 'Analisar' : 'Tentar de novo'}
                          </button>
                        )}
                        {e.status === 'arquivado' && <button className={styles.btnSmall} onClick={() => reabrir(e)}>Reabrir</button>}
                        {!emCurso && (temAnalise || e.status !== 'novo') && (
                          <button className={`${styles.btnSmall} ${APROVAVEIS.includes(e.status) ? styles.btnSmallPrimary : ''}`} onClick={() => abrir(e)}>
                            {APROVAVEIS.includes(e.status) ? 'Validar →' : 'Ver'}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      <div className={styles.tableFooter}>
        <span>{editais.length} edita{editais.length === 1 ? 'l' : 'is'} na lista{editais.length >= 500 ? ' (limite de 500)' : ''}</span>
        {rodando && <span>⟳ Atualizando a cada 8 s enquanto há análise rodando</span>}
      </div>

      {selecionado && (
        <ValidationModal
          key={`${selecionado.id}-${carregandoItens ? 'c' : 'ok'}`}
          edital={selecionado}
          itens={itens}
          isLoading={carregandoItens}
          onClose={() => setSelecionado(null)}
          onApprove={aprovar}
          onReject={rejeitar}
          podeAprovar={APROVAVEIS.includes(selecionado.status)}
          produtos={produtos}
          onFeedback={enviarFeedback}
          onReaplicar={reaplicar}
          onGerarResumo={gerarResumo}
          onRegerarDocumentos={selecionado.status === 'pronto_para_envio' ? regerarDocumentos : undefined}
          linkDocumento={caminho => `${API}/documentos/baixar?caminho=${encodeURIComponent(caminho)}`}
          statusLabel={STATUS[selecionado.status]?.label}
          avisoBloqueio={selecionado.status === 'pronto_para_envio'
            ? 'Este edital já foi aprovado.'
            : `Status atual: ${STATUS[selecionado.status]?.label ?? selecionado.status}. Só dá para aprovar depois da análise.`}
        />
      )}
    </>
  );
}
