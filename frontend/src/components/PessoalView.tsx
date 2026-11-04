'use client';
import styles from './painel.module.css';

// O Operação 30K é um HTML próprio que salva tudo no navegador (localStorage).
// Rodando no mesmo endereço do painel, os dados ficam guardados para localhost:3000.
const ARQUIVO = '/pessoal/operacao-30k.html';

export function PessoalView() {
  return (
    <>
      <div className={styles.frameBar}>
        <span>💰 Operação 30K · seus dados ficam salvos só neste navegador</span>
        <a className={styles.link} href={ARQUIVO} target="_blank" rel="noreferrer">Abrir em tela cheia ↗</a>
      </div>
      <iframe className={styles.frame} src={ARQUIVO} title="Operação 30K" />
    </>
  );
}
