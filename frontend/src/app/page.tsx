'use client';
import { useState, useEffect, useCallback } from 'react';
import styles from './dashboard.module.css';

// ── Types ──────────────────────────────────────────────────────────────────
interface Edital {
  id: string;
  numero_pregao: string;
  orgao: string;
  status: string;
  portal_origem: string;
  data_abertura?: string;
  licit_context?: Record<string, unknown>;
  created_at: string;
}

interface LicitItem {
  id: string;
  numero_item: string;
  descricao_original: string;
  tipo_produto?: string;
  score_compatibilidade?: number;
  status?: string;
  justificativa?: string;
  alertas?: string[];
  requisitos?: Record<string, unknown>;
}

// ── Score Badge ────────────────────────────────────────────────────────────
function ScoreBadge({ score }: { score?: number }) {
  if (score === undefined || score === null) {
    return <span className={styles.badgeGap}>GAP</span>;
  }
  if (score >= 0.90) return <span className={styles.badgeVerde}>● {(score * 100).toFixed(0)}%</span>;
  if (score >= 0.70) return <span className={styles.badgeAmbar}>● {(score * 100).toFixed(0)}%</span>;
  return <span className={styles.badgeVermelho}>● {(score * 100).toFixed(0)}%</span>;
}

// ── Status Badge ───────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    pendente_revisao_juridica: { label: 'Revisão Jurídica', cls: styles.badgeAmbar },
    pronto_para_envio:        { label: 'Pronto p/ Envio',  cls: styles.badgeVerde },
    compatibilidade_calculada: { label: 'Calculado',        cls: styles.badgeBrand },
    requisitos_extraidos:      { label: 'Extraído',         cls: styles.badgeBrand },
    texto_extraido:            { label: 'Parseado',         cls: styles.badgeBrand },
    arquivado:                 { label: 'Arquivado',        cls: styles.badgeMuted },
    novo:                      { label: 'Novo',             cls: styles.badgeMuted },
    revisao_manual_parser:     { label: 'Revisão manual',   cls: styles.badgeAmbar },
    erro_pipeline:             { label: 'Erro na análise',  cls: styles.badgeVermelho },
    erro_download:             { label: 'Erro no download', cls: styles.badgeVermelho },
  };
  const m = map[status] ?? { label: status, cls: styles.badgeMuted };
  return <span className={m.cls}>{m.label}</span>;
}

// ── Modal de Validação ─────────────────────────────────────────────────────
function ValidationModal({
  edital, itens, onClose, onApprove, onReject
}: {
  edital: Edital;
  itens: LicitItem[];
  onClose: () => void;
  onApprove: (id: string, nota: string) => void;
  onReject: (id: string) => void;
}) {
  const [nota, setNota] = useState('');
  const [loading, setLoading] = useState(false);

  const handleApprove = async () => {
    setLoading(true);
    await onApprove(edital.id, nota);
    setLoading(false);
  };

  const hasGap = itens.some(i =>
    i.alertas?.some(a => a.toLowerCase().includes('gap'))
  );
  const canApprove = !hasGap || nota.trim().length > 10;

  const ctx = edital.licit_context ?? {};

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className={styles.modalHeader}>
          <div>
            <div className={styles.modalTitle}>Validação — {edital.numero_pregao}</div>
            <div className={styles.modalSub}>{edital.orgao}</div>
          </div>
          <StatusBadge status={edital.status} />
          <button className={styles.closeBtn} onClick={onClose}>✕</button>
        </div>

        <div className={styles.modalBody}>
          {/* Impugnações */}
          {Array.isArray(ctx.impugnacoes) && (ctx.impugnacoes as string[]).length > 0 && (
            <section className={styles.section}>
              <h3 className={styles.sectionTitle}>⚖️ Minutas de Impugnação</h3>
              {(ctx.impugnacoes as string[]).map((imp, i) => (
                <div key={i} className={styles.alertBox}>{imp}</div>
              ))}
            </section>
          )}

          {/* Itens */}
          <section className={styles.section}>
            <h3 className={styles.sectionTitle}>📋 Itens ({itens.length})</h3>
            <div className={styles.itemGrid}>
              {itens.map(item => {
                const gapAlertas = item.alertas?.filter(a => a.toLowerCase().includes('gap')) ?? [];
                return (
                  <div key={item.id} className={styles.itemCard}>
                    <div className={styles.itemHeader}>
                      <span className={styles.itemNum}>{item.numero_item}</span>
                      <ScoreBadge score={item.score_compatibilidade} />
                    </div>
                    <p className={styles.itemDesc}>{item.descricao_original}</p>
                    {item.justificativa && (
                      <p className={styles.itemJust}>{item.justificativa}</p>
                    )}
                    {gapAlertas.map((g, gi) => (
                      <div key={gi} className={styles.gapAlert}>
                        <span className={styles.gapIcon}>⚠️</span>
                        <span>{g}</span>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          </section>

          {/* Nota */}
          <section className={styles.section}>
            <h3 className={styles.sectionTitle}>
              Nota do Analista{hasGap && <span className={styles.required}> * obrigatório (GAP detectado)</span>}
            </h3>
            <textarea
              className={`${styles.textarea} ${hasGap && !canApprove ? styles.textareaError : ''}`}
              rows={3}
              placeholder="Justifique a decisão ou anote ressalvas..."
              value={nota}
              onChange={e => setNota(e.target.value)}
            />
          </section>
        </div>

        {/* Footer */}
        <div className={styles.modalFooter}>
          <button className={styles.btnReject} onClick={() => onReject(edital.id)}>
            ✕ Rejeitar Edital
          </button>
          <div className={styles.footerRight}>
            <button className={styles.btnSecondary} onClick={onClose}>Cancelar</button>
            <button
              className={styles.btnApprove}
              onClick={handleApprove}
              disabled={!canApprove || loading}
            >
              {loading ? '⟳ Salvando...' : '✓ Aprovar → Envio'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

import { useWarRoom } from '../hooks/useWarRoom';

// ── Main Dashboard ─────────────────────────────────────────────────────────
// Passa pelo servidor do painel, que guarda o token da API.
const API = '/api/backend';
const WS_API = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws/war-room';

const STATUS_OPTIONS = [
  { value: '', label: 'Todos os status' },
  { value: 'pendente_revisao_juridica', label: 'Revisão Jurídica' },
  { value: 'compatibilidade_calculada', label: 'Compatibilidade Calculada' },
  { value: 'pronto_para_envio', label: 'Pronto p/ Envio' },
  { value: 'novo', label: 'Novos' },
  { value: 'revisao_manual_parser', label: 'Revisão manual' },
  { value: 'erro_pipeline', label: 'Erro na análise' },
  { value: 'arquivado', label: 'Arquivados' },
];

export default function Dashboard() {
  const [editais, setEditais] = useState<Edital[]>([]);
  const [filterStatus, setFilterStatus] = useState('');
  const [filterOrgao, setFilterOrgao] = useState('');
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Edital | null>(null);
  const [selectedItens, setSelectedItens] = useState<LicitItem[]>([]);
  const [loadingModal, setLoadingModal] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: 'ok' | 'err' } | null>(null);

  // War Room (WebSocket)
  const { connected: wsConnected, events: warRoomEvents, acknowledge } = useWarRoom(WS_API);
  
  // Alertas ativos
  const activeAlerts = warRoomEvents.filter(e => !e.ack);

  const showToast = (msg: string, type: 'ok' | 'err') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const fetchEditais = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterStatus) params.set('status', filterStatus);
      if (filterOrgao) params.set('orgao', filterOrgao);
      const res = await fetch(`${API}/editais/?${params}`);
      if (!res.ok) throw new Error('API offline');
      const json = await res.json();
      setEditais(json.data ?? []);
    } catch {
      // Nunca mostrar dado fictício em tela de decisão.
      showToast('Não foi possível carregar os editais. Backend offline?', 'err');
      setEditais([]);
    } finally {
      setLoading(false);
    }
  }, [filterStatus, filterOrgao]);

  useEffect(() => { fetchEditais(); }, [fetchEditais]);

  const buscarEditais = async () => {
    showToast('Buscando editais na ConLicitação...', 'ok');
    try {
      const res = await fetch(`${API}/pipeline/ingest/conlicitacao`, { method: 'POST' });
      if (!res.ok) {
        const erro = await res.json().catch(() => null);
        throw new Error(erro?.detail ?? 'Falha na busca.');
      }
      const json = await res.json();
      showToast(`${json.salvos} editais atualizados.`, 'ok');
      fetchEditais();
    } catch (erro) {
      showToast(erro instanceof Error ? erro.message : 'Falha na busca.', 'err');
    }
  };

  // A análise usa IA paga: só roda para o edital escolhido.
  const analisar = async (edital: Edital) => {
    const res = await fetch(`${API}/pipeline/run/${edital.id}`, { method: 'POST' }).catch(() => null);
    showToast(res?.ok ? 'Análise iniciada. Atualize em alguns minutos.' : 'Não foi possível iniciar a análise.', res?.ok ? 'ok' : 'err');
  };

  const openModal = async (edital: Edital) => {
    setSelected(edital);
    setLoadingModal(true);
    try {
      const res = await fetch(`${API}/editais/${edital.id}`);
      if (res.ok) {
        const json = await res.json();
        setSelectedItens(json.itens ?? []);
      } else {
        setSelectedItens([]);
        showToast('Não foi possível carregar os itens.', 'err');
      }
    } catch {
      setSelectedItens([]);
      showToast('Não foi possível carregar os itens.', 'err');
    } finally {
      setLoadingModal(false);
    }
  };

  const handleApprove = async (id: string, nota: string) => {
    try {
      const res = await fetch(`${API}/editais/${id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analista_nota: nota }),
      });
      if (res.ok) {
        showToast('Edital aprovado → Pronto para envio!', 'ok');
        setSelected(null);
        fetchEditais();
      } else throw new Error();
    } catch {
      showToast('Erro ao aprovar. Verifique a conexão.', 'err');
    }
  };

  const handleReject = async (id: string) => {
    try {
      await fetch(`${API}/editais/${id}/reject`, { method: 'POST' });
      showToast('Edital arquivado.', 'ok');
      setSelected(null);
      fetchEditais();
    } catch {
      showToast('Erro ao rejeitar.', 'err');
    }
  };

  const pendentes = editais.filter(e => e.status === 'pendente_revisao_juridica').length;

  return (
    <div className={styles.root}>
      {/* Sidebar */}
      <aside className={styles.sidebar}>
        <div className={styles.logo}>
          <div className={styles.logoIcon}>LA</div>
          <div>
            <div className={styles.logoName}>LicitAttivos</div>
            <div className={styles.logoSub}>Attivos Magisttrais</div>
          </div>
        </div>
        <nav className={styles.nav}>
          <a href="#" className={`${styles.navItem} ${styles.navActive}`}>
            <span>📋</span> Editais
          </a>
          <a href="#" className={styles.navItem}><span>📦</span> Produtos</a>
          <a href="#" className={styles.navItem}><span>⚖️</span> Jurídico</a>
          <a href="#" className={styles.navItem}><span>📊</span> Relatórios</a>
          <a href="#" className={styles.navItem}><span>⚙️</span> Configurações</a>
        </nav>
        <div className={styles.sidebarFooter}>
          <div className={styles.agentStatus}>
            <span className={`${styles.agentDot} ${wsConnected ? styles.dotGreen : styles.dotRed}`}></span>
            {wsConnected ? 'War Room Conectada' : 'War Room Offline'}
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className={styles.main}>
        {/* War Room Banner (Anti-Vibe UI) */}
        {activeAlerts.length > 0 && (
          <div className={styles.warRoomBanner}>
            <div className={styles.warRoomHeader}>
              <span className={styles.warRoomIcon}>🚨</span>
              <h3>Alerta de Combate — Atenção Requerida</h3>
            </div>
            <div className={styles.warRoomGrid}>
              {activeAlerts.map(evt => (
                <div key={evt.id} className={`${styles.warRoomCard} ${evt.nivel === 'vermelho' ? styles.cardRedPulse : styles.cardAmbar}`}>
                  <div className={styles.evtTime}>{new Date(evt.timestamp).toLocaleTimeString()}</div>
                  <div className={styles.evtMotivo}>{evt.motivo}</div>
                  {evt.sugestao_resposta && (
                    <div className={styles.evtSugestao}>
                      <strong>Sugestão do Agente 8:</strong> {evt.sugestao_resposta}
                    </div>
                  )}
                  <button className={styles.btnAck} onClick={() => acknowledge(evt.id)}>
                    ✓ Ciente
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Topbar */}
        <header className={styles.topbar}>
          <div>
            <h1 className={styles.pageTitle}>Dashboard de Decisão</h1>
            <button type="button" className={styles.btnRefresh} onClick={buscarEditais}>Buscar editais</button>
            <p className={styles.pageSub}>Validação pelo analista · Gatilho humano de envio</p>
          </div>
          {pendentes > 0 && (
            <div className={styles.alertPill}>
              <span className={styles.alertDot}></span>
              {pendentes} edital{pendentes > 1 ? 'is' : ''} aguardando revisão
            </div>
          )}
        </header>

        {/* Filters */}
        <div className={styles.filters}>
          <div className={styles.searchWrap}>
            <span className={styles.searchIcon}>🔍</span>
            <input
              id="filter-orgao"
              className={styles.searchInput}
              placeholder="Filtrar por órgão..."
              value={filterOrgao}
              onChange={e => setFilterOrgao(e.target.value)}
            />
          </div>
          <select
            id="filter-status"
            className={styles.select}
            value={filterStatus}
            onChange={e => setFilterStatus(e.target.value)}
          >
            {STATUS_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button className={styles.btnRefresh} onClick={fetchEditais}>⟳ Atualizar</button>
        </div>

        {/* Table */}
        <div className={styles.tableWrap}>
          {loading ? (
            <div className={styles.emptyState}>
              <div className={styles.spinner}></div>
              <p>Carregando editais...</p>
            </div>
          ) : editais.length === 0 ? (
            <div className={styles.emptyState}>
              <p className={styles.emptyIcon}>📭</p>
              <p>Nenhum edital encontrado com os filtros atuais.</p>
            </div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Pregão</th>
                  <th>Órgão</th>
                  <th>Portal</th>
                  <th>Status</th>
                  <th>Score Médio</th>
                  <th>Abertura</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {editais.map((e, idx) => {
                  const score = (e.licit_context?.score_medio as number | undefined);
                  const isRedPulse = activeAlerts.some(a => a.nivel === 'vermelho' && a.id.includes(e.id));
                  return (
                    <tr key={e.id} className={`${styles.tableRow} ${isRedPulse ? styles.rowRedPulse : ''}`} style={{ animationDelay: `${idx * 40}ms` }}>
                      <td><span className={styles.monoText}>{e.numero_pregao}</span></td>
                      <td className={styles.orgaoCell}>{e.orgao}</td>
                      <td><span className={styles.portalBadge}>{e.portal_origem.toUpperCase()}</span></td>
                      <td><StatusBadge status={e.status} /></td>
                      <td><ScoreBadge score={score} /></td>
                      <td className={styles.dateCell}>
                        {e.data_abertura ? new Date(e.data_abertura).toLocaleDateString('pt-BR') : '—'}
                      </td>
                      <td>
                        {['novo', 'erro_pipeline', 'erro_download'].includes(e.status) && (
                          <button className={styles.btnRefresh} onClick={() => analisar(e)}>Analisar</button>
                        )}
                        <button
                          id={`btn-validar-${e.id}`}
                          className={styles.btnValidar}
                          onClick={() => openModal(e)}
                        >
                          Validar →
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        <div className={styles.tableFooter}>
          <span>{editais.length} edital{editais.length !== 1 ? 'is' : ''} listado{editais.length !== 1 ? 's' : ''}</span>
        </div>
      </main>

      {/* Modal */}
      {selected && (
        <ValidationModal
          edital={selected}
          itens={loadingModal ? [] : selectedItens}
          onClose={() => setSelected(null)}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      )}

      {/* Toast */}
      {toast && (
        <div className={`${styles.toast} ${toast.type === 'ok' ? styles.toastOk : styles.toastErr}`}>
          {toast.type === 'ok' ? '✓' : '✕'} {toast.msg}
        </div>
      )}
    </div>
  );
}

// ── Demo Data (API offline) ────────────────────────────────────────────────
