'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import styles from './painel.module.css';
import { API, api, postar } from '../lib/api';
import { brl, dataBr } from '../lib/formato';

interface ItemForm { item: string; descricao: string; fabricante: string; marca: string; registro: string; quantidade: string; valor_unitario: string }
interface Form { orgao: string; pregao: string; processo: string; objeto: string; cidade: string; data: string; validade_dias: string; itens: ItemForm[] }
interface Gerada {
  pasta: string;
  criado_em: string;
  total: number;
  dados: Omit<Form, 'itens' | 'validade_dias'> & { validade_dias?: number | null; itens: (Omit<ItemForm, 'quantidade' | 'valor_unitario'> & { quantidade: number; valor_unitario: number })[] };
  arquivo: { docx: string; pdf: string | null };
}

const RASCUNHO = 'licitattivos.proposta-avulsa';
const hoje = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' });
const itemVazio = (n: number): ItemForm => ({ item: String(n), descricao: '', fabricante: '', marca: '', registro: '', quantidade: '', valor_unitario: '' });
const formVazio = (): Form => ({ orgao: '', pregao: '', processo: '', objeto: '', cidade: 'Anápolis', data: hoje(), validade_dias: '', itens: [itemVazio(1)] });
const numero = (v: string) => Number(v.replace(/\./g, '').replace(',', '.'));
const link = (caminho: string) => `${API}/documentos/baixar?caminho=${encodeURIComponent(caminho)}`;

function lerRascunho(): Form {
  try {
    const salvo = localStorage.getItem(RASCUNHO);
    if (salvo) return { ...formVazio(), ...JSON.parse(salvo) };
  } catch {
    /* sem armazenamento: começa em branco */
  }
  return formVazio();
}

export function PropostaAvulsaView({ avisar }: { avisar: (m: string, t: 'ok' | 'err') => void }) {
  const [form, setForm] = useState<Form>(formVazio);
  const [gerando, setGerando] = useState(false);
  const [ultima, setUltima] = useState<Gerada | null>(null);
  const [historico, setHistorico] = useState<Gerada[]>([]);
  // Só grava o rascunho depois de ler o salvo; senão o formulário vazio apagaria o rascunho.
  const rascunhoLido = useRef(false);

  const carregarHistorico = useCallback(() => {
    api<{ data: Gerada[] }>('documentos/avulsas').then(r => setHistorico(r.data ?? [])).catch(() => undefined);
  }, []);

  useEffect(() => {
    // Rascunho guardado só neste navegador, para não perder o que foi digitado.
    const t = setTimeout(() => { setForm(lerRascunho()); rascunhoLido.current = true; carregarHistorico(); }, 0);
    return () => clearTimeout(t);
  }, [carregarHistorico]);

  useEffect(() => {
    if (!rascunhoLido.current) return;
    try { localStorage.setItem(RASCUNHO, JSON.stringify(form)); } catch { /* ignora */ }
  }, [form]);

  const mudar = (campo: keyof Omit<Form, 'itens'>, valor: string) => setForm(f => ({ ...f, [campo]: valor }));
  const mudarItem = (i: number, campo: keyof ItemForm, valor: string) =>
    setForm(f => ({ ...f, itens: f.itens.map((it, k) => (k === i ? { ...it, [campo]: valor } : it)) }));
  const adicionar = () => setForm(f => {
    const anterior = f.itens[f.itens.length - 1];
    // Fabricante e marca repetem do item anterior: em proposta de um ramo só, quase sempre são iguais.
    return { ...f, itens: [...f.itens, { ...itemVazio(f.itens.length + 1), fabricante: anterior?.fabricante ?? '', marca: anterior?.marca ?? '' }] };
  });
  const remover = (i: number) => setForm(f => ({ ...f, itens: f.itens.length > 1 ? f.itens.filter((_, k) => k !== i) : f.itens }));

  const subtotal = (it: ItemForm) => {
    const q = numero(it.quantidade), v = numero(it.valor_unitario);
    return q > 0 && v > 0 ? q * v : 0;
  };
  const total = form.itens.reduce((s, it) => s + subtotal(it), 0);
  const faltando = !form.orgao.trim() || form.itens.some(it => !it.descricao.trim() || !it.marca.trim() || !(subtotal(it) > 0));

  const gerar = async () => {
    setGerando(true);
    // A aba do PDF abre no clique; se abrisse depois da espera, o navegador bloquearia como pop-up.
    const janela = window.open('', '_blank');
    janela?.document.write('<p style="font-family:sans-serif;padding:24px">Gerando a proposta no papel timbrado...</p>');
    try {
      const r = await postar<Gerada>('documentos/proposta-avulsa', {
        orgao: form.orgao.trim(),
        pregao: form.pregao.trim() || null,
        processo: form.processo.trim() || null,
        objeto: form.objeto.trim() || null,
        cidade: form.cidade.trim() || null,
        data: form.data || null,
        validade_dias: form.validade_dias ? Number(form.validade_dias) : null,
        itens: form.itens.map(it => ({
          item: it.item.trim(), descricao: it.descricao.trim(), fabricante: it.fabricante.trim() || null,
          marca: it.marca.trim(), registro: it.registro.trim() || null,
          quantidade: numero(it.quantidade), valor_unitario: numero(it.valor_unitario),
        })),
      });
      setUltima(r);
      avisar('Proposta gerada no papel timbrado.', 'ok');
      if (janela && r.arquivo.pdf) janela.location.href = link(r.arquivo.pdf);
      else janela?.close();
      carregarHistorico();
    } catch (e) {
      janela?.close();
      avisar(e instanceof Error ? e.message : 'Falha ao gerar a proposta.', 'err');
    } finally {
      setGerando(false);
    }
  };

  const usarComoBase = (g: Gerada) => {
    const d = g.dados;
    setForm({
      orgao: d.orgao ?? '', pregao: d.pregao ?? '', processo: d.processo ?? '', objeto: d.objeto ?? '',
      cidade: d.cidade ?? 'Anápolis', data: hoje(), validade_dias: d.validade_dias ? String(d.validade_dias) : '',
      itens: d.itens.map(i => ({
        item: i.item, descricao: i.descricao, fabricante: i.fabricante ?? '', marca: i.marca, registro: i.registro ?? '',
        quantidade: String(i.quantidade).replace('.', ','), valor_unitario: String(i.valor_unitario).replace('.', ','),
      })),
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
    avisar('Dados carregados. Ajuste e gere de novo.', 'ok');
  };

  const campo = (rotulo: string, chave: keyof Omit<Form, 'itens'>, extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label style={{ display: 'grid', gap: 4, fontSize: 12.5, color: 'var(--text-secondary)', flex: extra.style ? undefined : '1 1 200px' }}>
      {rotulo}
      <input className={styles.input} value={form[chave]} onChange={e => mudar(chave, e.target.value)} {...extra} />
    </label>
  );

  return (
    <>
      <header className={styles.topbar}>
        <div>
          <h1 className={styles.pageTitle}>Gerador de proposta</h1>
          <p className={styles.pageSub}>Proposta de qualquer ramo no papel timbrado, só com as informações principais</p>
        </div>
        <div className={styles.acoes}>
          <button className={styles.btnGhost} onClick={() => setForm(formVazio())}>Limpar</button>
          <button className={styles.btnPrimary} onClick={gerar} disabled={gerando || faltando}>
            {gerando ? <span className={`${styles.spinner} ${styles.spinnerSmall}`} /> : '📄'} Gerar proposta (PDF)
          </button>
        </div>
      </header>

      <div className={styles.panel}>
        <div className={styles.panelTitle}>Dados do pregão</div>
        <div className={styles.filters}>
          {campo('Órgão *', 'orgao', { placeholder: 'Ex.: Fundo Municipal de Saúde de Pirenópolis' })}
          {campo('Pregão', 'pregao', { placeholder: 'Ex.: 024/2026' })}
          {campo('Processo', 'processo', { placeholder: 'Ex.: 5576/2026' })}
        </div>
        <div className={styles.filters} style={{ marginTop: 10 }}>
          {campo('Objeto (completa "Apresentamos a nossa proposta para aquisição de ...")', 'objeto', { placeholder: 'Ex.: Colchões Hospitalares' })}
          {campo('Cidade', 'cidade', { style: { width: 160 } })}
          {campo('Data', 'data', { type: 'date', style: { width: 170, colorScheme: 'dark' } })}
          {campo('Validade (dias)', 'validade_dias', { inputMode: 'numeric', placeholder: '120', style: { width: 120 } })}
        </div>
      </div>

      <div className={styles.panel}>
        <div className={styles.panelTitle}>Itens</div>
        <div style={{ display: 'grid', gap: 12 }}>
          {form.itens.map((it, i) => (
            <div key={i} className={styles.itemAvulso}>
              <div className={styles.filters}>
                <label className={styles.campoAvulso} style={{ width: 80, flex: 'none' }}>Item
                  <input className={styles.input} value={it.item} onChange={e => mudarItem(i, 'item', e.target.value)} /></label>
                <label className={styles.campoAvulso} style={{ flex: '3 1 320px' }}>Descritivo *
                  <textarea className={styles.input} rows={2} value={it.descricao} onChange={e => mudarItem(i, 'descricao', e.target.value)}
                    placeholder="Copie o descritivo do edital" /></label>
              </div>
              <div className={styles.filters} style={{ marginTop: 8 }}>
                <label className={styles.campoAvulso}>Fabricante
                  <input className={styles.input} value={it.fabricante} onChange={e => mudarItem(i, 'fabricante', e.target.value)} placeholder="Ex.: Gilson Colchões" /></label>
                <label className={styles.campoAvulso}>Marca / modelo *
                  <input className={styles.input} value={it.marca} onChange={e => mudarItem(i, 'marca', e.target.value)} placeholder="Ex.: ULTRAFLEX D33" /></label>
                <label className={styles.campoAvulso}>Registro ANVISA (se houver)
                  <input className={styles.input} value={it.registro} onChange={e => mudarItem(i, 'registro', e.target.value)} placeholder="vazio = não aparece" /></label>
                <label className={styles.campoAvulso} style={{ flex: '0 1 120px' }}>Qtd. *
                  <input className={styles.input} inputMode="decimal" value={it.quantidade} onChange={e => mudarItem(i, 'quantidade', e.target.value)} /></label>
                <label className={styles.campoAvulso} style={{ flex: '0 1 150px' }}>Valor unit. (R$) *
                  <input className={styles.input} inputMode="decimal" value={it.valor_unitario} onChange={e => mudarItem(i, 'valor_unitario', e.target.value)} /></label>
                <div className={styles.campoAvulso} style={{ flex: '0 1 150px' }}>Subtotal
                  <b style={{ padding: '9px 0', color: 'var(--text-primary)' }}>{brl(subtotal(it))}</b></div>
                <button className={styles.btnGhost} onClick={() => remover(i)} disabled={form.itens.length === 1} title="Remover item" style={{ alignSelf: 'flex-end' }}>✕</button>
              </div>
            </div>
          ))}
        </div>
        <div className={styles.filters} style={{ justifyContent: 'space-between', marginTop: 12 }}>
          <button className={styles.btn} onClick={adicionar}>+ Adicionar item</button>
          <span style={{ fontSize: 15 }}>Total da proposta: <b>{brl(total)}</b></span>
        </div>
        {faltando && <p className={styles.sub} style={{ marginTop: 8 }}>Preencha órgão e, em cada item, descritivo, marca, quantidade e valor para gerar.</p>}
      </div>

      <div className={styles.aviso} style={{ background: 'var(--brand-glow)', borderColor: 'rgba(59,130,246,.35)', color: '#BFDBFE' }}>
        A proposta sai no mesmo modelo da Nutrópolis (timbrado, cláusulas, quadros e dados da empresa). Muda só o que você preencher aqui.
      </div>

      {ultima && (
        <div className={styles.panel}>
          <div className={styles.panelTitle}>Última gerada · {ultima.dados.orgao} · {brl(ultima.total)}</div>
          <div className={styles.rowActions} style={{ justifyContent: 'flex-start' }}>
            {ultima.arquivo.pdf && <a className={`${styles.btnSmall} ${styles.btnSmallPrimary}`} href={link(ultima.arquivo.pdf)} target="_blank" rel="noreferrer">Abrir PDF</a>}
            <a className={styles.btnSmall} href={link(ultima.arquivo.docx)}>Baixar DOCX (editável)</a>
          </div>
        </div>
      )}

      <div className={styles.tableWrap}>
        {historico.length === 0 ? (
          <div className={styles.emptyState}><p className={styles.emptyIcon}>🗂️</p><p>As propostas geradas aqui ficam guardadas nesta lista.</p></div>
        ) : (
          <table className={styles.table}>
            <thead><tr><th>Órgão / Pregão</th><th>Gerada em</th><th className={styles.num}>Total</th><th></th></tr></thead>
            <tbody>
              {historico.map(g => (
                <tr key={g.pasta}>
                  <td className={styles.cardTitle} data-label="">
                    <span className={styles.orgao}>{g.dados.orgao}</span>
                    <span className={styles.sub}>{[g.dados.pregao && `Pregão ${g.dados.pregao}`, g.dados.objeto, `${g.dados.itens.length} ite${g.dados.itens.length === 1 ? 'm' : 'ns'}`].filter(Boolean).join(' · ')}</span>
                  </td>
                  <td data-label="Gerada em">{dataBr(g.criado_em)}</td>
                  <td className={styles.num} data-label="Total">{brl(g.total)}</td>
                  <td className={styles.cardActions} data-label="">
                    <div className={styles.rowActions}>
                      {g.arquivo.pdf && <a className={`${styles.btnSmall} ${styles.btnSmallPrimary}`} href={link(g.arquivo.pdf)} target="_blank" rel="noreferrer">PDF</a>}
                      <a className={styles.btnSmall} href={link(g.arquivo.docx)}>DOCX</a>
                      <button className={styles.btnSmall} onClick={() => usarComoBase(g)}>Usar como base</button>
                    </div>
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
