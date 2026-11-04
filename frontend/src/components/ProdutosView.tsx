'use client';
import { useCallback, useEffect, useMemo, useState } from 'react';
import styles from './painel.module.css';
import { api, postar, type Produto } from '../lib/api';
import { dataBr } from '../lib/formato';

interface Sku { codigo: string; produto: string; preco: number | null; gramas: number | null }
interface PrecoProduto { produto_id: string; skus: Sku[]; menor_por_grama: number | null; sku_mais_barato: string | null }
interface TabelaPrecos { fonte?: string; atualizado_em?: string; total: number; sem_preco: number; produtos: PrecoProduto[] }

const num = (v?: number | null, un = '') => (v === null || v === undefined ? '—' : `${v.toLocaleString('pt-BR')}${un}`);

export function ProdutosView({ avisar }: { avisar: (m: string, t: 'ok' | 'err') => void }) {
  const [produtos, setProdutos] = useState<Produto[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [busca, setBusca] = useState('');
  const [soPholias, setSoPholias] = useState(true);
  const [tabela, setTabela] = useState<TabelaPrecos | null>(null);
  const [importando, setImportando] = useState(false);

  const carregarPrecos = useCallback(() => {
    api<TabelaPrecos>('products/precos').then(setTabela).catch(() => setTabela(null));
  }, []);

  useEffect(() => {
    api<{ data: Produto[] }>('products')
      .then(r => setProdutos(r.data ?? []))
      .catch(e => avisar(e instanceof Error ? e.message : 'Falha ao carregar produtos.', 'err'))
      .finally(() => setCarregando(false));
    carregarPrecos();
  }, [avisar, carregarPrecos]);

  const precoDe = useMemo(() => Object.fromEntries((tabela?.produtos ?? []).map(p => [p.produto_id, p])), [tabela]);

  const importar = async (arquivo: File | undefined) => {
    if (!arquivo) return;
    setImportando(true);
    try {
      const r = await postar<{ total: number; sem_preco: number }>('products/precos/importar', { markdown: await arquivo.text(), fonte: arquivo.name });
      avisar(`Tabela importada: ${r.total} apresentações (${r.sem_preco} sem preço). Reaplique o aprendizado nos editais para recalcular.`, 'ok');
      carregarPrecos();
    } catch (e) {
      avisar(e instanceof Error ? e.message : 'Falha ao importar a tabela.', 'err');
    } finally {
      setImportando(false);
    }
  };

  const lista = useMemo(() => {
    const alvo = busca.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
    return produtos
      .filter(p => !soPholias || (p.marca ?? '').toUpperCase() === 'PHOLIAS')
      .filter(p => !alvo || `${p.nome_comercial} ${p.categoria ?? ''} ${p.linha_clinica ?? ''}`.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').includes(alvo));
  }, [produtos, busca, soPholias]);

  const pholias = produtos.filter(p => (p.marca ?? '').toUpperCase() === 'PHOLIAS');

  return (
    <>
      <header className={styles.topbar}>
        <div>
          <h1 className={styles.pageTitle}>Produtos</h1>
          <p className={styles.pageSub}>Catálogo que o motor de compatibilidade usa. Só Pholias entra na análise de edital.</p>
        </div>
        <div className={styles.acoes}>
          <label className={styles.btnPrimary} style={{ cursor: importando ? 'wait' : 'pointer' }}>
            {importando ? 'Importando...' : '💲 Importar tabela de preços (.md)'}
            <input type="file" accept=".md,text/markdown,text/plain" hidden disabled={importando}
              onChange={e => { importar(e.target.files?.[0]); e.target.value = ''; }} />
          </label>
        </div>
      </header>

      {tabela && (
        <div className={styles.aviso} style={{ background: 'var(--brand-glow)', borderColor: 'rgba(59,130,246,.35)', color: '#BFDBFE' }}>
          Tabela de preços em uso: <b>{tabela.fonte ?? '—'}</b>{tabela.atualizado_em ? ` · importada em ${dataBr(tabela.atualizado_em)}` : ''} · {tabela.total} apresentações ({tabela.sem_preco} sem preço).
          O preço mínimo de cada item de edital sai daqui.
        </div>
      )}

      <div className={styles.kpis}>
        <div className={styles.kpi}><span className={styles.kpiLabel}>No banco</span><b className={styles.kpiValor}>{produtos.length}</b></div>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Pholias</span><b className={styles.kpiValor}>{pholias.length}</b><span className={styles.kpiSub}>usados na análise</span></div>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Com registro MS</span><b className={styles.kpiValor}>{pholias.filter(p => p.tem_registro_ms).length}</b></div>
        <div className={styles.kpi}><span className={styles.kpiLabel}>Via enteral</span><b className={styles.kpiValor}>{pholias.filter(p => p.via_enteral).length}</b></div>
      </div>

      <div className={styles.aviso}>
        O cadastro de registro MS e via enteral ainda diverge do catálogo oficial (Hurdle 5). Por segurança, o motor só aceita registro MS dos dois Just Whey e via enteral dos Just Whey e do Sorend, mesmo que o banco diga outra coisa.
      </div>

      <div className={styles.filters}>
        <div className={styles.searchWrap}>
          <span className={styles.searchIcon}>🔍</span>
          <input className={styles.input} placeholder="Buscar produto, categoria ou linha..." value={busca} onChange={e => setBusca(e.target.value)} aria-label="Buscar produto" />
        </div>
        <label className={styles.toggle}><input type="checkbox" checked={soPholias} onChange={e => setSoPholias(e.target.checked)} /> Só Pholias</label>
      </div>

      <div className={styles.tableWrap}>
        {carregando ? (
          <div className={styles.emptyState}><div className={styles.spinner} /><p>Carregando produtos...</p></div>
        ) : lista.length === 0 ? (
          <div className={styles.emptyState}><p className={styles.emptyIcon}>📦</p><p>Nenhum produto encontrado.</p></div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Produto</th>
                <th className={styles.hideMd}>Público</th>
                <th className={styles.num}>Porção</th>
                <th className={styles.num}>Proteína</th>
                <th className={styles.num}>Kcal</th>
                <th className={styles.num}>Menor R$/g</th>
                <th>Selos</th>
              </tr>
            </thead>
            <tbody>
              {lista.map(p => (
                <tr key={p.id}>
                  <td className={styles.cardTitle} data-label="">
                    <span className={styles.orgao}>{p.nome_comercial}</span>
                    <span className={styles.sub}>{[p.marca, p.categoria].filter(Boolean).join(' · ')}</span>
                  </td>
                  <td className={styles.hideMd} data-label="Público">{p.publico_alvo ?? '—'}</td>
                  <td className={styles.num} data-label="Porção">{num(p.porcao_g, ' g')}</td>
                  <td className={styles.num} data-label="Proteína">{num(p.proteinas_por_porcao_g, ' g')}</td>
                  <td className={styles.num} data-label="Kcal">{num(p.kcal_por_porcao)}</td>
                  <td className={styles.num} data-label="Menor R$/g" title={precoDe[p.id]?.sku_mais_barato ?? 'Sem preço na tabela'}>
                    {precoDe[p.id]?.menor_por_grama
                      ? <>R$ {precoDe[p.id]!.menor_por_grama!.toLocaleString('pt-BR', { minimumFractionDigits: 4 })}<span className={styles.sub}>{precoDe[p.id]!.skus.length} apresentações</span></>
                      : <span className={styles.prazo_passado}>sem preço</span>}
                  </td>
                  <td data-label="Selos">
                    <div className={styles.chips}>
                      {p.tem_registro_ms && <span className={`${styles.chip} ${styles.chipOk}`}>Registro MS</span>}
                      {p.via_enteral && <span className={`${styles.chip} ${styles.chipOk}`}>Enteral</span>}
                      {p.sem_gluten && <span className={styles.chip}>Sem glúten</span>}
                      {p.sem_lactose && <span className={styles.chip}>Sem lactose</span>}
                      {p.sem_sacarose && <span className={styles.chip}>Sem sacarose</span>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className={styles.tableFooter}><span>{lista.length} produto{lista.length === 1 ? '' : 's'}</span></div>
    </>
  );
}
