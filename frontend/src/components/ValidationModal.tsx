'use client';
import { useState } from 'react';
import styles from './ValidationModal.module.css';

// ── Types ──────────────────────────────────────────────────────────────────
export interface LicitItem {
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

export interface Edital {
  id: string;
  numero_pregao: string;
  orgao: string;
  status: string;
  licit_context?: Record<string, unknown>;
}

interface GapField {
  itemId: string;
  campo: string;
  label: string;
  valor: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────
function parseGaps(itens: LicitItem[]): GapField[] {
  const gaps: GapField[] = [];
  for (const item of itens) {
    for (const alerta of item.alertas ?? []) {
      // Formato esperado: "gap_de_informacao: campo_nome"
      const match = alerta.match(/gap_de_informacao:\s*(.+)/i);
      if (match) {
        gaps.push({
          itemId: item.id,
          campo: match[1].trim(),
          label: match[1].trim().replace(/_/g, ' '),
          valor: '',
        });
      }
    }
  }
  return gaps;
}

function getScoreStyle(score?: number) {
  if (score === undefined || score === null) return styles.badgeGap;
  if (score >= 0.90) return styles.badgeVerde;
  if (score >= 0.70) return styles.badgeAmbar;
  return styles.badgeVermelho;
}

function formatScore(score?: number) {
  if (score === undefined || score === null) return 'GAP';
  return `${(score * 100).toFixed(0)}%`;
}

// ── Component ──────────────────────────────────────────────────────────────
interface Props {
  edital: Edital;
  itens: LicitItem[];
  isLoading?: boolean;
  onClose: () => void;
  onApprove: (
    editalId: string,
    nota: string,
    gapCorrections: Record<string, string>,
    justificativasEditadas: Record<string, string>
  ) => Promise<void>;
  onReject: (editalId: string) => Promise<void>;
}

export function ValidationModal({ edital, itens, isLoading, onClose, onApprove, onReject }: Props) {
  const [nota, setNota] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [rejecting, setRejecting] = useState(false);

  // GAP fields — cada um precisa ser preenchido para habilitar o approve
  const [gaps, setGaps] = useState<GapField[]>(() => parseGaps(itens));

  // Justificativas editáveis por item
  const [justificativas, setJustificativas] = useState<Record<string, string>>(
    () => Object.fromEntries(itens.map(i => [i.id, i.justificativa ?? '']))
  );

  const allGapsFilled = gaps.every(g => g.valor.trim().length > 0);
  const canApprove = allGapsFilled && !submitting && !rejecting;

  const handleGapChange = (idx: number, value: string) => {
    setGaps(prev => prev.map((g, i) => i === idx ? { ...g, valor: value } : g));
  };

  const handleApprove = async () => {
    setSubmitting(true);
    const gapCorrections = Object.fromEntries(
      gaps.map(g => [`${g.itemId}:${g.campo}`, g.valor])
    );
    await onApprove(edital.id, nota, gapCorrections, justificativas);
    setSubmitting(false);
  };

  const handleReject = async () => {
    setRejecting(true);
    await onReject(edital.id);
    setRejecting(false);
  };

  const impugnacoes = (edital.licit_context?.impugnacoes ?? []) as string[];

  return (
    <div className={styles.overlay} onClick={onClose} data-testid="modal-overlay">
      <div className={styles.modal} onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Modal de Validação">

        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerInfo}>
            <h2 className={styles.title}>Validação — {edital.numero_pregao}</h2>
            <p className={styles.subtitle}>{edital.orgao}</p>
          </div>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Fechar modal">✕</button>
        </div>

        {/* Body */}
        <div className={styles.body}>

          {/* Loading */}
          {isLoading && (
            <div className={styles.loadingState}>
              <div className={styles.spinner}></div>
              <span>Carregando itens...</span>
            </div>
          )}

          {/* Impugnações */}
          {impugnacoes.length > 0 && (
            <section>
              <h3 className={styles.sectionTitle}>⚖️ Minutas de Impugnação</h3>
              {impugnacoes.map((imp, i) => (
                <div key={i} className={styles.impugnacaoBox} data-testid={`impugnacao-${i}`}>{imp}</div>
              ))}
            </section>
          )}

          {/* Itens */}
          {!isLoading && itens.length > 0 && (
            <section>
              <h3 className={styles.sectionTitle}>📋 Itens do Edital ({itens.length})</h3>
              <div className={styles.itemList}>
                {itens.map(item => {
                  const itemGaps = gaps.filter(g => g.itemId === item.id);
                  return (
                    <div key={item.id} className={styles.itemCard} data-testid={`item-card-${item.id}`}>
                      <div className={styles.itemHeader}>
                        {/* Rastreabilidade: item_numero sempre visível */}
                        <span className={styles.itemNum} data-testid={`item-numero-${item.id}`}>
                          {item.numero_item}
                        </span>
                        <span className={getScoreStyle(item.score_compatibilidade)} data-testid={`score-badge-${item.id}`}>
                          {item.score_compatibilidade !== undefined ? '● ' : ''}{formatScore(item.score_compatibilidade)}
                        </span>
                      </div>

                      <p className={styles.itemDesc}>{item.descricao_original}</p>

                      {/* Justificativa editável */}
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Justificativa Técnica</label>
                        <textarea
                          className={styles.textarea}
                          value={justificativas[item.id] ?? ''}
                          onChange={e => setJustificativas(prev => ({ ...prev, [item.id]: e.target.value }))}
                          rows={2}
                          data-testid={`justificativa-input-${item.id}`}
                          aria-label={`Justificativa técnica do ${item.numero_item}`}
                        />
                      </div>

                      {/* GAP fields — Regra do Desapego: campo nulo em destaque */}
                      {itemGaps.map((gap, gi) => {
                        const globalIdx = gaps.findIndex(g => g.itemId === gap.itemId && g.campo === gap.campo);
                        const isEmpty = gap.valor.trim().length === 0;
                        return (
                          <div key={gi} className={styles.gapField} data-testid={`gap-field-${item.id}-${gap.campo}`}>
                            <div className={styles.gapLabel}>
                              <span className={styles.gapIcon}>⚠️</span>
                              <span className={styles.gapLabelText}>
                                GAP — <strong>{gap.label}</strong>
                                <span className={styles.gapRequired}> obrigatório para aprovar</span>
                              </span>
                            </div>
                            <input
                              type="text"
                              className={`${styles.gapInput} ${isEmpty ? styles.gapInputEmpty : styles.gapInputFilled}`}
                              placeholder={`Preencha: ${gap.label}`}
                              value={gap.valor}
                              onChange={e => handleGapChange(globalIdx, e.target.value)}
                              data-testid={`gap-input-${item.id}-${gap.campo}`}
                              aria-label={`Campo GAP: ${gap.label}`}
                              aria-required="true"
                            />
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Nota Analista */}
          <section>
            <h3 className={styles.sectionTitle}>📝 Nota do Analista</h3>
            <textarea
              className={styles.textarea}
              rows={3}
              placeholder="Justifique sua decisão ou anote ressalvas para o registro..."
              value={nota}
              onChange={e => setNota(e.target.value)}
              data-testid="nota-analista"
              aria-label="Nota do analista"
            />
          </section>

          {/* Bloqueio visual */}
          {gaps.length > 0 && !allGapsFilled && (
            <div className={styles.gapWarning} data-testid="gap-warning">
              ⛔ {gaps.filter(g => !g.valor.trim()).length} campo(s) com GAP pendente. Preencha para habilitar a aprovação.
            </div>
          )}
        </div>

        {/* Footer */}
        <div className={styles.footer}>
          <button
            className={styles.btnReject}
            onClick={handleReject}
            disabled={rejecting || submitting}
            data-testid="btn-rejeitar"
          >
            {rejecting ? '⟳' : '✕'} Rejeitar Edital
          </button>

          <div className={styles.footerRight}>
            <button className={styles.btnSecondary} onClick={onClose} data-testid="btn-cancelar">
              Cancelar
            </button>
            <button
              className={styles.btnApprove}
              onClick={handleApprove}
              disabled={!canApprove}
              data-testid="btn-aprovar"
              aria-disabled={!canApprove}
            >
              {submitting ? '⟳ Salvando...' : '✓ Aprovar → Envio'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
