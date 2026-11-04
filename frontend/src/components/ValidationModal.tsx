'use client';
import { useState } from 'react';
import { createPortal } from 'react-dom';
import styles from './ValidationModal.module.css';
import { ItemFeedback, type EnviarFeedback, type ProdutoOpcao } from './ItemFeedback';

// ── Types ──────────────────────────────────────────────────────────────────
export interface LicitItem {
  id: string;
  numero_item: string;
  descricao_original: string;
  tipo_produto?: string;
  score_compatibilidade?: number;
  compativel?: boolean | null;
  produto_nome?: string | null;
  preco_referencia?: number | null;
  status?: string;
  justificativa?: string;
  alertas?: string[];
  requisitos?: Record<string, unknown>;
}

export interface Edital {
  id: string;
  numero_pregao: string;
  orgao: string;
  uf?: string | null;
  status: string;
  data_abertura?: string | null;
  url_edital?: string | null;
  licit_context?: Record<string, unknown>;
}

export interface LinhaProposta {
  item_id: string;
  incluir: boolean;
  quantidade: number;
  preco_unitario: number;
}

interface ArquivoGerado { nome: string; titulo: string; docx: string; pdf: string | null }
interface PrecoItem { preco_unitario?: number; sku?: string; codigo?: string; criterio?: string; total?: number | null; conferir?: boolean; sem_preco?: boolean; motivo?: string }
interface Precificacao {
  por_item?: Record<string, PrecoItem>;
  por_produto?: { produto: string; itens: string[]; quantidade: number; total: number; itens_100: number }[];
  total?: number;
  total_100?: number;
  tabela?: string;
}
interface Documentos { status: 'gerando' | 'pronto' | 'erro'; arquivos?: ArquivoGerado[]; avisos?: string[]; erro?: string; gerado_em?: string }

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
        gaps.push({ itemId: item.id, campo: match[1].trim(), label: match[1].trim().replace(/_/g, ' '), valor: '' });
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

const brl = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const dataHora = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' }) : '—';
const quantidadeDo = (item: LicitItem) => {
  const q = Number(item.requisitos?.quantidade_pregao);
  return Number.isFinite(q) && q > 0 ? q : 0;
};

// Resumo do edital: campo → rótulo, na ordem em que o analista lê.
const FATOS: [string, string][] = [
  ['numero_pregao', 'Pregão'],
  ['numero_processo', 'Processo'],
  ['modalidade', 'Modalidade'],
  ['data_sessao', 'Sessão pública'],
  ['plataforma', 'Plataforma'],
  ['criterio_julgamento', 'Critério de julgamento'],
  ['modo_disputa', 'Modo de disputa'],
  ['participacao_me_epp', 'Participação ME/EPP'],
  ['valor_estimado_total', 'Valor estimado'],
  ['prazo_entrega', 'Prazo de entrega'],
  ['local_entrega', 'Local de entrega'],
  ['validade_proposta_dias', 'Validade da proposta'],
  ['prazo_pagamento', 'Pagamento'],
  ['vigencia', 'Vigência'],
  ['exige_amostra', 'Amostra'],
  ['prazo_impugnacao', 'Impugnação até'],
  ['contato', 'Contato'],
];
const LISTAS: [string, string, boolean][] = [
  ['pontos_atencao', '⚠️ Pontos de atenção', true],
  ['exigencias_produto', 'Exigências sobre o produto', false],
  ['documentos_habilitacao', 'Documentos de habilitação', false],
  ['declaracoes_exigidas', 'Declarações exigidas', false],
];

function valorFato(chave: string, valor: unknown): string | null {
  if (valor === null || valor === undefined || valor === '') return null;
  if (chave === 'valor_estimado_total' && typeof valor === 'number') return brl(valor);
  if (chave === 'validade_proposta_dias') return `${valor} dias`;
  if (typeof valor === 'boolean') return valor ? 'Sim' : 'Não';
  return String(valor);
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
    justificativasEditadas: Record<string, string>,
    proposta?: LinhaProposta[]
  ) => Promise<void>;
  onReject: (editalId: string, motivo?: string) => Promise<void>;
  /** Falso quando o status não permite aprovar (ex.: análise ainda não rodou). */
  podeAprovar?: boolean;
  avisoBloqueio?: string;
  /** Aprendizado: com estes dois, cada item ganha "O sistema acertou?". */
  produtos?: ProdutoOpcao[];
  onFeedback?: EnviarFeedback;
  onReaplicar?: () => Promise<void>;
  /** Resumo do edital por IA, para editais analisados antes do resumo existir. */
  onGerarResumo?: () => Promise<void>;
  onRegerarDocumentos?: (proposta: LinhaProposta[]) => Promise<void>;
  /** Monta o link de download de um arquivo gerado. */
  linkDocumento?: (caminho: string) => string;
  statusLabel?: string;
}

export function ValidationModal({
  edital, itens, isLoading, onClose, onApprove, onReject, podeAprovar = true, avisoBloqueio,
  produtos, onFeedback, onReaplicar, onGerarResumo, onRegerarDocumentos, linkDocumento, statusLabel,
}: Props) {
  const [reaplicando, setReaplicando] = useState(false);
  const [resumindo, setResumindo] = useState(false);
  const [nota, setNota] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [rejecting, setRejecting] = useState(false);

  // GAP fields — cada um precisa ser preenchido para habilitar o approve
  const [gaps, setGaps] = useState<GapField[]>(() => parseGaps(itens));

  // Justificativas editáveis por item
  const [justificativas, setJustificativas] = useState<Record<string, string>>(
    () => Object.fromEntries(itens.map(i => [i.id, i.justificativa ?? '']))
  );

  // Preço mínimo de cotação (tabela com desconto) por item e valor total por produto.
  const precificacao = edital.licit_context?.precificacao as Precificacao | undefined;
  const precoDo = (itemId: string) => precificacao?.por_item?.[itemId];

  // Primeira proposta: itens com produto sugerido, quantidade do edital e preço mínimo da tabela.
  const [proposta, setProposta] = useState<Record<string, { incluir: boolean; quantidade: string; preco: string }>>(
    () => Object.fromEntries(itens.filter(i => i.produto_nome).map(i => {
      const minimo = precoDo(i.id)?.preco_unitario;
      return [i.id, {
        incluir: true,
        quantidade: quantidadeDo(i) ? String(quantidadeDo(i)) : '',
        preco: minimo ? String(minimo) : i.preco_referencia ? String(i.preco_referencia) : '',
      }];
    }))
  );

  const linhasProposta: LinhaProposta[] = Object.entries(proposta).map(([item_id, p]) => ({
    item_id,
    incluir: p.incluir,
    quantidade: Number(p.quantidade.replace(',', '.')),
    preco_unitario: Number(p.preco.replace(',', '.')),
  }));
  const propostaIncompleta = linhasProposta.some(l => l.incluir && !(l.quantidade > 0 && l.preco_unitario > 0));
  const totalProposta = linhasProposta.filter(l => l.incluir && l.quantidade > 0 && l.preco_unitario > 0)
    .reduce((soma, l) => soma + l.quantidade * l.preco_unitario, 0);

  const allGapsFilled = gaps.every(g => g.valor.trim().length > 0);
  const canApprove = podeAprovar && !isLoading && allGapsFilled && !propostaIncompleta && !submitting && !rejecting;

  const handleGapChange = (idx: number, value: string) => {
    setGaps(prev => prev.map((g, i) => i === idx ? { ...g, valor: value } : g));
  };

  const handleApprove = async () => {
    setSubmitting(true);
    const gapCorrections = Object.fromEntries(gaps.map(g => [`${g.itemId}:${g.campo}`, g.valor]));
    await onApprove(edital.id, nota, gapCorrections, justificativas, linhasProposta.filter(l => l.incluir));
    setSubmitting(false);
  };

  const handleReject = async () => {
    setRejecting(true);
    const motivo = nota.trim();
    await (motivo ? onReject(edital.id, motivo) : onReject(edital.id));
    setRejecting(false);
  };

  const imprimir = () => {
    document.body.classList.add('imprimindo-relatorio');
    window.print();
    document.body.classList.remove('imprimindo-relatorio');
  };

  const ctx = edital.licit_context ?? {};
  const impugnacoes = (ctx.impugnacoes ?? []) as string[];
  const erro = ctx.erro_pipeline as string | undefined;
  const inteligencia = ctx.inteligencia as { sinais?: string[]; prioridade?: string } | undefined;
  const resumo = ctx.resumo as Record<string, unknown> | undefined;
  const documentos = ctx.documentos as Documentos | undefined;
  const compativeis = itens.filter(i => i.compativel).length;
  const itens100 = itens.filter(i => (i.score_compatibilidade ?? 0) >= 0.999);
  const scoreMedio = ctx.score_medio as number | undefined;
  const numero = edital.numero_pregao.split(' #')[0];

  const conteudo = (
    <div className={styles.overlay} onClick={onClose} data-testid="modal-overlay">
      <div className={styles.modal} onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Modal de Validação">

        {/* Barra do visualizador */}
        <div className={`${styles.toolbar} ${styles.noPrint}`}>
          <div className={styles.toolbarInfo}>
            <span className={styles.toolbarIcon}>📄</span>
            <span className={styles.toolbarTitle}>Validação — {edital.numero_pregao}</span>
          </div>
          <div className={styles.toolbarActions}>
            <button className={styles.toolBtn} onClick={imprimir} title="Imprimir ou salvar como PDF">🖨 Imprimir / PDF</button>
            <button className={styles.closeBtn} onClick={onClose} aria-label="Fechar modal">✕</button>
          </div>
        </div>

        {/* Folha */}
        <div className={styles.canvas}>
          <article className={styles.paper}>
            <header className={styles.docHeader}>
              <div className={styles.kicker}>LicitAttivos · Relatório de análise de edital</div>
              <h2 className={styles.title}>{edital.orgao}</h2>
              <p className={styles.subtitle}>
                Pregão {numero}{edital.uf ? ` · ${edital.uf}` : ''}{edital.data_abertura ? ` · Abertura ${dataHora(edital.data_abertura)}` : ''}
              </p>
              <div className={styles.docMeta}>
                <span>Status: <b>{statusLabel ?? edital.status}</b></span>
                <span>Emitido em {new Date().toLocaleDateString('pt-BR')}</span>
                {edital.url_edital && <a className={`${styles.link} ${styles.noPrint}`} href={edital.url_edital} target="_blank" rel="noreferrer">Abrir edital no portal ↗</a>}
              </div>
            </header>

            {isLoading && (
              <div className={styles.loadingState}><div className={styles.spinner}></div><span>Carregando itens...</span></div>
            )}

            {itens100.length > 0 && (
              <div className={styles.apto} data-testid="apto-participar">
                ✅ <strong>Apto a participar.</strong> {itens100.length === 1 ? 'Item' : 'Itens'} 100% compatíve{itens100.length === 1 ? 'l' : 'is'}:{' '}
                {itens100.map(i => `${i.numero_item}${i.produto_nome ? ` (${i.produto_nome})` : ''}`).join(', ')}
              </div>
            )}
            {erro && <div className={styles.gapWarning}>⚠️ Última análise: {erro}</div>}

            {/* 1. Resumo do edital */}
            <section className={styles.docSection}>
              <h3 className={styles.sectionTitle}>1. Resumo do edital</h3>
              {resumo ? (
                <>
                  {resumo.objeto ? <p className={styles.objeto}><b>Objeto:</b> {String(resumo.objeto)}</p> : null}
                  <dl className={styles.fatos}>
                    {FATOS.map(([chave, rotulo]) => {
                      const valor = valorFato(chave, resumo[chave]);
                      return valor ? (<div key={chave}><dt>{rotulo}</dt><dd>{valor}</dd></div>) : null;
                    })}
                    {typeof resumo.registro_de_precos === 'boolean' && (
                      <div><dt>Registro de preços</dt><dd>{resumo.registro_de_precos ? 'Sim (SRP)' : 'Não'}</dd></div>
                    )}
                  </dl>
                  {LISTAS.map(([chave, rotulo, destaque]) => {
                    const lista = (resumo[chave] as string[] | undefined) ?? [];
                    return lista.length > 0 ? (
                      <div key={chave} className={destaque ? styles.blocoAtencao : styles.bloco}>
                        <h4>{rotulo}</h4>
                        <ul>{lista.map((linha, i) => <li key={i}>{linha}</li>)}</ul>
                      </div>
                    ) : null;
                  })}
                </>
              ) : (
                <div className={styles.vazio}>
                  Resumo ainda não gerado para este edital.
                  {onGerarResumo && (
                    <button className={`${styles.toolBtnLight} ${styles.noPrint}`} disabled={resumindo}
                      onClick={async () => { setResumindo(true); await onGerarResumo(); setResumindo(false); }}>
                      {resumindo ? '⟳ Lendo o edital...' : '✨ Gerar resumo com IA'}
                    </button>
                  )}
                </div>
              )}
            </section>

            {/* 2. Resultado */}
            <section className={styles.docSection}>
              <h3 className={styles.sectionTitle}>2. Resultado da análise</h3>
              <div className={styles.numeros}>
                <div><b>{itens.length}</b><span>itens no edital</span></div>
                <div><b>{compativeis}</b><span>compatíveis (≥ 70%)</span></div>
                <div><b>{itens100.length}</b><span>100% compatíveis</span></div>
                <div><b>{scoreMedio !== undefined && scoreMedio !== null ? `${Math.round(scoreMedio * 100)}%` : '—'}</b><span>score médio</span></div>
              </div>
              {inteligencia?.sinais && inteligencia.sinais.length > 0 && (
                <ul className={styles.sinais}>
                  {inteligencia.sinais.map((s, i) => <li key={i} data-prioridade={inteligencia.prioridade}>{s}</li>)}
                </ul>
              )}

              {precificacao?.por_produto && precificacao.por_produto.length > 0 && (
                <div data-testid="valor-por-produto">
                  <h4 className={styles.subTitulo}>Valor total por produto (preço mínimo de cotação)</h4>
                  <table className={styles.tabelaValores}>
                    <thead><tr><th>Produto</th><th>Itens</th><th className={styles.num}>Quantidade</th><th className={styles.num}>Valor mínimo</th></tr></thead>
                    <tbody>
                      {precificacao.por_produto.map(g => (
                        <tr key={g.produto}>
                          <td>{g.produto}{g.itens_100 > 0 && <span className={styles.selo100}>100%</span>}</td>
                          <td>{g.itens.join(', ')}</td>
                          <td className={styles.num}>{g.quantidade.toLocaleString('pt-BR')}</td>
                          <td className={styles.num}>{brl(g.total)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr><td colSpan={3}>Total dos itens compatíveis</td><td className={styles.num}>{brl(precificacao.total ?? 0)}</td></tr>
                      <tr><td colSpan={3}>Só itens 100% compatíveis</td><td className={styles.num}>{brl(precificacao.total_100 ?? 0)}</td></tr>
                    </tfoot>
                  </table>
                  {precificacao.tabela && <p className={styles.fonte}>Tabela de preços: {precificacao.tabela}</p>}
                </div>
              )}
            </section>

            {impugnacoes.length > 0 && (
              <section className={styles.docSection}>
                <h3 className={styles.sectionTitle}>⚖️ Minutas de Impugnação</h3>
                {impugnacoes.map((imp, i) => (
                  <div key={i} className={styles.impugnacaoBox} data-testid={`impugnacao-${i}`}>{imp}</div>
                ))}
              </section>
            )}

            {/* 3. Itens */}
            <section className={styles.docSection}>
              <h3 className={styles.sectionTitle}>3. Itens do edital ({itens.length})</h3>
              {!isLoading && itens.length === 0 && !erro && (
                <p className={styles.vazio}>Nenhum item analisado ainda. Rode a análise para ver a compatibilidade.</p>
              )}
              <div className={styles.itemList}>
                {itens.map(item => {
                  const itemGaps = gaps.filter(g => g.itemId === item.id);
                  const linha = proposta[item.id];
                  const qtd = quantidadeDo(item);
                  const unidade = item.requisitos?.unidade_solicitada as string | undefined;
                  return (
                    <div key={item.id} className={`${styles.itemCard} ${(item.score_compatibilidade ?? 0) >= 0.999 ? styles.itemCem : ''}`} data-testid={`item-card-${item.id}`}>
                      <div className={styles.itemHeader}>
                        {/* Rastreabilidade: item_numero sempre visível */}
                        <span className={styles.itemNum} data-testid={`item-numero-${item.id}`}>{item.numero_item}</span>
                        <span className={getScoreStyle(item.score_compatibilidade)} data-testid={`score-badge-${item.id}`}>
                          {item.score_compatibilidade !== undefined ? '● ' : ''}{formatScore(item.score_compatibilidade)}
                        </span>
                      </div>

                      <p className={styles.itemDesc}>{item.descricao_original}</p>
                      <div className={styles.itemMeta}>
                        <span>Produto sugerido: {item.produto_nome ? <strong>{item.produto_nome}</strong> : <em className={styles.semProduto}>sem produto compatível</em>}</span>
                        {qtd > 0 && <span>Quantidade: <strong>{qtd.toLocaleString('pt-BR')}{unidade ? ` ${unidade}` : ''}</strong></span>}
                        {item.preco_referencia ? <span>Preço de referência: <strong>{brl(item.preco_referencia)}</strong></span> : null}
                      </div>
                      {(() => {
                        const preco = precoDo(item.id);
                        if (!preco) return null;
                        if (preco.sem_preco) return <div className={styles.precoAviso}>💲 {preco.motivo}</div>;
                        const acimaDaReferencia = !!item.preco_referencia && (preco.preco_unitario ?? 0) > item.preco_referencia;
                        return (
                          <div className={`${styles.precoLinha} ${preco.conferir || acimaDaReferencia ? styles.precoConferir : ''}`}>
                            💲 Preço mínimo: <strong>{brl(preco.preco_unitario ?? 0)}</strong>
                            {preco.sku && <> · {preco.sku}{preco.codigo ? ` (${preco.codigo})` : ''}</>}
                            {preco.total ? <> · Total mínimo: <strong>{brl(preco.total)}</strong></> : null}
                            <span className={styles.precoCriterio}>{preco.criterio}</span>
                            {acimaDaReferencia && <span className={styles.precoCriterio}>⚠️ Mínimo acima do preço de referência do edital: risco de desclassificação.</span>}
                          </div>
                        );
                      })()}

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

                      {onFeedback && produtos && (
                        <div className={styles.noPrint}>
                          <ItemFeedback itemId={item.id} temSugestao={!!item.produto_nome} produtos={produtos} onFeedback={onFeedback} />
                        </div>
                      )}

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

                      {/* Proposta: preço e quantidade decididos pelo analista */}
                      {linha && (podeAprovar || onRegerarDocumentos) && (
                        <div className={`${styles.propostaLinha} ${styles.noPrint}`} data-testid={`proposta-${item.id}`}>
                          <label className={styles.incluir}>
                            <input type="checkbox" checked={linha.incluir}
                              onChange={e => setProposta(p => ({ ...p, [item.id]: { ...linha, incluir: e.target.checked } }))} />
                            Ofertar na proposta
                          </label>
                          {linha.incluir && (
                            <>
                              <label>Qtd.
                                <input inputMode="decimal" value={linha.quantidade} aria-label={`Quantidade do ${item.numero_item}`}
                                  onChange={e => setProposta(p => ({ ...p, [item.id]: { ...linha, quantidade: e.target.value } }))} />
                              </label>
                              <label>Preço unit. (R$)
                                <input inputMode="decimal" value={linha.preco} aria-label={`Preço unitário do ${item.numero_item}`}
                                  onChange={e => setProposta(p => ({ ...p, [item.id]: { ...linha, preco: e.target.value } }))} />
                              </label>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>

            {/* 4. Documentos gerados */}
            {documentos && (
              <section className={styles.docSection}>
                <h3 className={styles.sectionTitle}>4. Documentos gerados</h3>
                {documentos.status === 'gerando' && (
                  <div className={styles.loadingState}><div className={styles.spinner}></div><span>Gerando proposta e declarações...</span></div>
                )}
                {documentos.status === 'erro' && <div className={styles.gapWarning}>Falha ao gerar: {documentos.erro}</div>}
                {documentos.status === 'pronto' && (
                  <ul className={styles.docsLista}>
                    {(documentos.arquivos ?? []).map(a => (
                      <li key={a.nome}>
                        <span>{a.titulo}</span>
                        <span className={styles.noPrint}>
                          {a.pdf && linkDocumento && <a className={styles.link} href={linkDocumento(a.pdf)} target="_blank" rel="noreferrer">PDF</a>}
                          {linkDocumento && <a className={styles.link} href={linkDocumento(a.docx)}>DOCX</a>}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {(documentos.avisos ?? []).map((aviso, i) => <div key={i} className={styles.gapWarning}>{aviso}</div>)}
              </section>
            )}
            {onRegerarDocumentos && documentos?.status !== 'gerando' && (
              <div className={styles.noPrint}>
                <button className={styles.toolBtnLight} disabled={propostaIncompleta}
                  onClick={() => onRegerarDocumentos(linhasProposta.filter(l => l.incluir))}>
                  {documentos ? '↻ Gerar documentos de novo com os preços acima' : '📄 Gerar proposta e declarações com os preços acima'}
                </button>
                {Object.keys(proposta).length > 0 && <p className={styles.totalProposta}>Total da proposta: <b>{brl(totalProposta)}</b></p>}
              </div>
            )}

            {/* Decisão */}
            <section className={`${styles.docSection} ${styles.noPrint}`}>
              <h3 className={styles.sectionTitle}>📝 Nota do Analista</h3>
              <textarea
                className={styles.textarea}
                rows={3}
                placeholder="Justifique sua decisão ou anote ressalvas. Ao rejeitar, este texto vira o motivo."
                value={nota}
                onChange={e => setNota(e.target.value)}
                data-testid="nota-analista"
                aria-label="Nota do analista"
              />
              {podeAprovar && Object.keys(proposta).length > 0 && (
                <p className={styles.totalProposta}>
                  Total da proposta: <b>{brl(totalProposta)}</b> · Ao aprovar, o sistema gera a proposta no papel timbrado e as declarações do pregão.
                </p>
              )}
              {propostaIncompleta && <div className={styles.gapWarning}>Preencha quantidade e preço de todos os itens marcados para ofertar.</div>}
              {!podeAprovar && avisoBloqueio && <div className={styles.gapWarning}>{avisoBloqueio}</div>}
              {/* Bloqueio visual */}
              {gaps.length > 0 && !allGapsFilled && (
                <div className={styles.gapWarning} data-testid="gap-warning">
                  ⛔ {gaps.filter(g => !g.valor.trim()).length} campo(s) com GAP pendente. Preencha para habilitar a aprovação.
                </div>
              )}
            </section>
          </article>
        </div>

        {/* Ações */}
        <div className={`${styles.footer} ${styles.noPrint}`}>
          <button className={styles.btnReject} onClick={handleReject} disabled={rejecting || submitting} data-testid="btn-rejeitar">
            {rejecting ? '⟳' : '✕'} Rejeitar Edital
          </button>
          <div className={styles.footerRight}>
            {onReaplicar && itens.length > 0 && (
              <button className={styles.btnSecondary} disabled={reaplicando}
                title="Recalcula os scores com o que você ensinou. Não usa IA."
                onClick={async () => { setReaplicando(true); await onReaplicar(); setReaplicando(false); }}>
                {reaplicando ? '⟳ Recalculando...' : '🎓 Reaplicar aprendizado'}
              </button>
            )}
            <button className={styles.btnSecondary} onClick={onClose} data-testid="btn-cancelar">Cancelar</button>
            <button className={styles.btnApprove} onClick={handleApprove} disabled={!canApprove} data-testid="btn-aprovar" aria-disabled={!canApprove}>
              {submitting ? '⟳ Salvando...' : '✓ Aprovar e gerar documentos'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  // Portal no <body>: o relatório imprime sozinho, sem o painel atrás.
  if (typeof document === 'undefined') return conteudo;
  return createPortal(<div className="relatorio-portal">{conteudo}</div>, document.body);
}
