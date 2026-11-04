'use client';
import { useState } from 'react';
import styles from './ValidationModal.module.css';

export interface ProdutoOpcao { id: string; nome_comercial: string }
export type EnviarFeedback = (itemId: string, correto: boolean, produtoCorretoId: string | null, motivo: string) => Promise<void>;

/** "O sistema acertou este item?" — a resposta vira aprendizado para os próximos editais. */
export function ItemFeedback({ itemId, temSugestao, produtos, onFeedback }: {
  itemId: string;
  temSugestao: boolean;
  produtos: ProdutoOpcao[];
  onFeedback: EnviarFeedback;
}) {
  const [modo, setModo] = useState<'pergunta' | 'corrigir' | 'enviado'>('pergunta');
  const [produto, setProduto] = useState('');
  const [motivo, setMotivo] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState('');

  const enviar = async (correto: boolean) => {
    setEnviando(true);
    setErro('');
    try {
      await onFeedback(itemId, correto, correto ? null : produto || null, motivo);
      setModo('enviado');
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não salvou.');
    } finally {
      setEnviando(false);
    }
  };

  if (modo === 'enviado') return <div className={styles.feedbackOk}>🎓 Aprendido. Vale para os próximos editais.</div>;

  if (modo === 'pergunta') {
    return (
      <div className={styles.feedback}>
        <span>O sistema acertou?</span>
        <button className={styles.feedbackBtn} onClick={() => enviar(true)} disabled={enviando}
          title={temSugestao ? 'O produto sugerido atende' : 'Realmente nenhum produto atende'}>✓ Acertou</button>
        <button className={styles.feedbackBtn} onClick={() => setModo('corrigir')} disabled={enviando}>✗ Errou</button>
        {erro && <span className={styles.feedbackErro}>{erro}</span>}
      </div>
    );
  }

  return (
    <div className={styles.feedbackForm}>
      <label className={styles.fieldLabel}>Qual produto atende este item?</label>
      <select className={styles.gapInput} value={produto} onChange={e => setProduto(e.target.value)} aria-label="Produto correto">
        <option value="">Nenhum produto do catálogo atende</option>
        {produtos.map(p => <option key={p.id} value={p.id}>{p.nome_comercial}</option>)}
      </select>
      <input className={styles.gapInput} placeholder="Por quê? (ex.: edital pede isolado, não concentrado)" value={motivo}
        onChange={e => setMotivo(e.target.value)} aria-label="Motivo da correção" />
      <div className={styles.feedback}>
        <button className={styles.feedbackBtn} onClick={() => enviar(false)} disabled={enviando}>{enviando ? 'Salvando...' : 'Salvar correção'}</button>
        <button className={styles.feedbackBtn} onClick={() => setModo('pergunta')} disabled={enviando}>Cancelar</button>
        {erro && <span className={styles.feedbackErro}>{erro}</span>}
      </div>
    </div>
  );
}
