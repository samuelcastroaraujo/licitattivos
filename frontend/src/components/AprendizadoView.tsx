'use client';
import { useCallback, useEffect, useMemo, useState } from 'react';
import styles from './painel.module.css';
import { api, postar, type Produto } from '../lib/api';
import { dataBr } from '../lib/formato';

interface Conhecimento {
  id: string;
  tipo: 'feedback_historico' | 'regra_fixa' | 'dica_usuario';
  produto_id?: string | null;
  produto_nome?: string | null;
  conteudo: string;
  descritivo_original?: string | null;
  resultado?: 'compativel' | 'incompativel' | null;
  created_at: string;
}

const TIPO: Record<Conhecimento['tipo'], string> = {
  feedback_historico: 'Correção em item',
  regra_fixa: 'Regra fixa',
  dica_usuario: 'Dica',
};

export function AprendizadoView({ avisar }: { avisar: (m: string, t: 'ok' | 'err') => void }) {
  const [lista, setLista] = useState<Conhecimento[]>([]);
  const [produtos, setProdutos] = useState<Produto[]>([]);
  const [carregado, setCarregado] = useState(false);
  const [busca, setBusca] = useState('');
  const [form, setForm] = useState({ tipo: 'regra_fixa' as Conhecimento['tipo'], descritivo: '', produto: '', resultado: 'incompativel', conteudo: '' });
  const [salvando, setSalvando] = useState(false);

  const carregar = useCallback(async () => {
    try {
      const [k, p] = await Promise.all([
        api<{ data: Conhecimento[] }>('aprendizado'),
        api<{ data: Produto[] }>('products'),
      ]);
      setLista(k.data ?? []);
      setProdutos((p.data ?? []).filter(x => (x.marca ?? '').toUpperCase() === 'PHOLIAS'));
    } catch (e) {
      avisar(e instanceof Error ? e.message : 'Falha ao carregar o aprendizado.', 'err');
    } finally {
      setCarregado(true);
    }
  }, [avisar]);

  useEffect(() => {
    const t = setTimeout(carregar, 0);
    return () => clearTimeout(t);
  }, [carregar]);

  const salvar = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setSalvando(true);
    try {
      await postar('aprendizado', {
        tipo: form.tipo,
        descritivo_original: form.descritivo,
        conteudo: form.conteudo,
        produto_id: form.tipo === 'dica_usuario' ? null : form.produto || null,
        resultado: form.tipo === 'dica_usuario' ? null : form.resultado,
      });
      avisar('Aprendizado salvo. Use "Reaplicar aprendizado" nos editais já analisados.', 'ok');
      setForm(f => ({ ...f, descritivo: '', conteudo: '' }));
      carregar();
    } catch (e) {
      avisar(e instanceof Error ? e.message : 'Não salvou.', 'err');
    } finally {
      setSalvando(false);
    }
  };

  const excluir = async (k: Conhecimento) => {
    try {
      await postar(`aprendizado/${k.id}/excluir`);
      setLista(l => l.filter(x => x.id !== k.id));
      avisar('Removido.', 'ok');
    } catch (e) {
      avisar(e instanceof Error ? e.message : 'Não removeu.', 'err');
    }
  };

  const filtrada = useMemo(() => {
    const alvo = busca.toLowerCase();
    return lista.filter(k => !alvo || `${k.descritivo_original} ${k.conteudo} ${k.produto_nome}`.toLowerCase().includes(alvo));
  }, [lista, busca]);

  const conta = (f: (k: Conhecimento) => boolean) => lista.filter(f).length;

  return (
    <>
      <header className={styles.topbar}>
        <div>
          <h1 className={styles.pageTitle}>Aprendizado</h1>
          <p className={styles.pageSub}>O que você ensina aqui vale para os próximos editais com descritivo parecido</p>
        </div>
      </header>

      <div className={styles.kpis}>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Total</span><b className={styles.kpiValor}>{lista.length}</b><span className={styles.kpiSub}>no Supabase</span></div>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Liberações</span><b className={styles.kpiValor}>{conta(k => k.resultado === 'compativel')}</b><span className={styles.kpiSub}>produto confirmado</span></div>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Bloqueios</span><b className={styles.kpiValor}>{conta(k => k.resultado === 'incompativel')}</b><span className={styles.kpiSub}>produto reprovado</span></div>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Dicas</span><b className={styles.kpiValor}>{conta(k => k.tipo === 'dica_usuario')}</b><span className={styles.kpiSub}>aparecem na justificativa</span></div>
      </div>

      <div className={styles.aviso}>
        Como funciona: <b>bloqueio</b> zera o produto em descritivo parecido (basta ~55% das palavras em comum). <b>Liberação</b> só tira dúvidas de leitura (família, ingrediente com outro nome) em descritivo quase igual (~75%) e nunca passa por cima de falha dura: proteína abaixo, registro MS, via enteral, glúten, lactose, faixa etária.
      </div>

      <div className={styles.grid2}>
        <form className={styles.panel} onSubmit={salvar}>
          <div className={styles.panelTitle}>Ensinar uma regra</div>
          <div style={{ display: 'grid', gap: 10 }}>
            <select className={styles.select} style={{ width: '100%' }} value={form.tipo} onChange={e => setForm({ ...form, tipo: e.target.value as Conhecimento['tipo'] })} aria-label="Tipo">
              <option value="regra_fixa">Regra fixa (peso dobrado)</option>
              <option value="dica_usuario">Dica (só orienta, não muda score)</option>
            </select>
            <textarea className={styles.input} rows={4} required minLength={10} value={form.descritivo}
              onChange={e => setForm({ ...form, descritivo: e.target.value })}
              placeholder="Cole aqui um descritivo típico (ex.: Módulo de proteína isolada do soro do leite, lata 400 g...)" aria-label="Descritivo" />
            {form.tipo !== 'dica_usuario' && (
              <div className={styles.filters}>
                <select className={styles.select} style={{ flex: '2 1 200px' }} value={form.produto} onChange={e => setForm({ ...form, produto: e.target.value })} aria-label="Produto">
                  <option value="">{form.resultado === 'incompativel' ? 'Nenhum produto atende' : 'Escolha o produto'}</option>
                  {produtos.map(p => <option key={p.id} value={p.id}>{p.nome_comercial}</option>)}
                </select>
                <select className={styles.select} style={{ flex: '1 1 140px' }} value={form.resultado} onChange={e => setForm({ ...form, resultado: e.target.value })} aria-label="Resultado">
                  <option value="incompativel">Incompatível</option>
                  <option value="compativel">Compatível</option>
                </select>
              </div>
            )}
            <input className={styles.input} value={form.conteudo} onChange={e => setForm({ ...form, conteudo: e.target.value })}
              placeholder={form.tipo === 'dica_usuario' ? 'A dica (ex.: este órgão aceita sachê)' : 'Motivo (ex.: exige isolado, não concentrado)'} aria-label="Motivo" />
            <button className={styles.btnPrimary} disabled={salvando || (form.tipo !== 'dica_usuario' && form.resultado === 'compativel' && !form.produto)}>
              {salvando ? 'Salvando...' : 'Salvar aprendizado'}
            </button>
          </div>
        </form>

        <div className={styles.panel}>
          <div className={styles.panelTitle}>Como o sistema aprende sozinho</div>
          <ul className={styles.lista}>
            <li>No modal de validação, cada item tem <b>“O sistema acertou?”</b>. Sua resposta vira uma linha aqui.</li>
            <li>“Errou” + produto certo: reprova o sugerido e libera o correto para descritivos parecidos.</li>
            <li>“Errou” + “nenhum atende”: bloqueia o catálogo inteiro para esse tipo de descritivo.</li>
            <li>Depois de ensinar, clique em <b>🎓 Reaplicar aprendizado</b> no edital: recalcula na hora, sem gastar IA.</li>
          </ul>
        </div>
      </div>

      <div className={styles.filters}>
        <div className={styles.searchWrap}>
          <span className={styles.searchIcon}>🔍</span>
          <input className={styles.input} placeholder="Buscar no aprendizado..." value={busca} onChange={e => setBusca(e.target.value)} aria-label="Buscar no aprendizado" />
        </div>
      </div>

      <div className={styles.tableWrap}>
        {!carregado ? (
          <div className={styles.emptyState}><div className={styles.spinner} /><p>Carregando...</p></div>
        ) : filtrada.length === 0 ? (
          <div className={styles.emptyState}><p className={styles.emptyIcon}>🎓</p><p>Nada aprendido ainda. Valide um edital e responda “O sistema acertou?” nos itens.</p></div>
        ) : (
          <table className={styles.table}>
            <thead><tr><th>Descritivo</th><th>Decisão</th><th>Tipo</th><th>Data</th><th></th></tr></thead>
            <tbody>
              {filtrada.map(k => (
                <tr key={k.id}>
                  <td className={styles.cardTitle} data-label="">
                    <span className={styles.orgao}>{(k.descritivo_original ?? '').slice(0, 140)}{(k.descritivo_original ?? '').length > 140 ? '…' : ''}</span>
                    <span className={styles.sub}>{k.conteudo}</span>
                  </td>
                  <td data-label="Decisão">
                    {k.resultado === 'compativel' && <span className={styles.badgeVerde}>✓ {k.produto_nome ?? 'produto'}</span>}
                    {k.resultado === 'incompativel' && <span className={styles.badgeVermelho}>✗ {k.produto_nome ?? 'nenhum produto'}</span>}
                    {!k.resultado && <span className={styles.badgeMuted}>dica</span>}
                  </td>
                  <td data-label="Tipo">{TIPO[k.tipo] ?? k.tipo}</td>
                  <td data-label="Data">{dataBr(k.created_at)}</td>
                  <td className={styles.cardActions} data-label="">
                    <div className={styles.rowActions}><button className={styles.btnSmall} onClick={() => excluir(k)}>Remover</button></div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
