'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import styles from '../components/painel.module.css';
import { EditaisView } from '../components/EditaisView';
import { ProdutosView } from '../components/ProdutosView';
import { InteligenciaView } from '../components/InteligenciaView';
import { PessoalView } from '../components/PessoalView';
import { AprendizadoView } from '../components/AprendizadoView';
import { DocumentosView } from '../components/DocumentosView';
import { PropostaAvulsaView } from '../components/PropostaAvulsaView';
import { useWarRoom } from '../hooks/useWarRoom';
import { api } from '../lib/api';

type Aba = 'editais' | 'documentos' | 'proposta' | 'produtos' | 'inteligencia' | 'aprendizado' | 'pessoal';
const ABAS: { id: Aba; icone: string; nome: string }[] = [
  { id: 'editais', icone: '📋', nome: 'Editais' },
  { id: 'documentos', icone: '🗂️', nome: 'Documentos' },
  { id: 'proposta', icone: '📝', nome: 'Gerar proposta' },
  { id: 'produtos', icone: '📦', nome: 'Produtos' },
  { id: 'inteligencia', icone: '🧠', nome: 'Inteligência' },
  { id: 'aprendizado', icone: '🎓', nome: 'Aprendizado' },
  { id: 'pessoal', icone: '💰', nome: 'Pessoal' },
];
const abaDaUrl = (): Aba => {
  const h = typeof window === 'undefined' ? '' : window.location.hash.slice(1);
  return (ABAS.some(a => a.id === h) ? h : 'editais') as Aba;
};

// A War Room só liga quando houver URL configurada (Agente 8 ainda fora do pipeline).
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || undefined;

export default function Painel() {
  const [aba, setAba] = useState<Aba>('editais');
  const [online, setOnline] = useState<boolean | null>(null);
  const [toast, setToast] = useState<{ msg: string; tipo: 'ok' | 'err' } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const warRoom = useWarRoom(WS_URL);

  // A aba fica na URL (#produtos etc.): F5 e o botão voltar funcionam.
  useEffect(() => {
    const sync = () => setAba(abaDaUrl());
    sync();
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  const trocar = (nova: Aba) => {
    window.history.pushState(null, '', `#${nova}`);
    setAba(nova);
  };

  const avisar = useCallback((msg: string, tipo: 'ok' | 'err') => {
    clearTimeout(timer.current);
    setToast({ msg, tipo });
    timer.current = setTimeout(() => setToast(null), 4500);
  }, []);

  useEffect(() => {
    const checar = () => api('editais/resumo').then(() => setOnline(true)).catch(() => setOnline(false));
    checar();
    const t = setInterval(checar, 60_000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className={styles.root}>
      <aside className={styles.sidebar}>
        <div className={styles.logo}>
          <div className={styles.logoIcon}>LA</div>
          <div>
            <div className={styles.logoName}>LicitAttivos</div>
            <div className={styles.logoSub}>Attivos Magisttrais</div>
          </div>
        </div>
        <nav className={styles.nav} aria-label="Seções">
          {ABAS.map(a => (
            <button key={a.id} className={`${styles.navItem} ${aba === a.id ? styles.navActive : ''}`}
              onClick={() => trocar(a.id)} aria-current={aba === a.id ? 'page' : undefined}>
              <span className={styles.navIcon}>{a.icone}</span>{a.nome}
            </button>
          ))}
        </nav>
        <div className={styles.sidebarFooter}>
          <div className={styles.status}>
            <span className={`${styles.dot} ${online === null ? '' : online ? styles.dotOn : styles.dotOff}`} />
            {online === null ? 'Verificando API...' : online ? 'API online' : 'API offline'}
          </div>
          {warRoom.enabled && (
            <div className={styles.status}>
              <span className={`${styles.dot} ${warRoom.connected ? styles.dotOn : styles.dotOff}`} />
              War Room {warRoom.connected ? 'conectada' : 'offline'}
            </div>
          )}
        </div>
      </aside>

      <main className={`${styles.main} ${aba === 'pessoal' ? styles.mainFull : ''}`}>
        {aba === 'editais' && <EditaisView avisar={avisar} />}
        {aba === 'documentos' && <DocumentosView avisar={avisar} />}
        {aba === 'proposta' && <PropostaAvulsaView avisar={avisar} />}
        {aba === 'produtos' && <ProdutosView avisar={avisar} />}
        {aba === 'inteligencia' && <InteligenciaView avisar={avisar} />}
        {aba === 'aprendizado' && <AprendizadoView avisar={avisar} />}
        {aba === 'pessoal' && <PessoalView />}
      </main>

      {toast && (
        <div className={`${styles.toast} ${toast.tipo === 'ok' ? styles.toastOk : styles.toastErr}`} role="status">
          {toast.tipo === 'ok' ? '✓' : '✕'} {toast.msg}
        </div>
      )}
    </div>
  );
}
