/**
 * test_validation_modal.tsx — Ciclo TDD do Modal de Aprovação
 *
 * Regras testadas:
 * 1. Botão "Aprovar" fica DISABLED enquanto existir GAP não preenchido
 * 2. Preenchendo o GAP, o botão é habilitado
 * 3. O item_numero extraído pelo Agente 3 é visível (rastreabilidade)
 * 4. Clique em "Aprovar" dispara onApprove com os dados corretos (gapCorrections + justificativas)
 * 5. Clique em "Rejeitar" dispara onReject
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ValidationModal, type Edital, type LicitItem } from '../components/ValidationModal';

// ── Fixtures ───────────────────────────────────────────────────────────────
const EDITAL_FIXTURE: Edital = {
  id: 'edital-001',
  numero_pregao: '00012/2026',
  orgao: 'Hospital Municipal de São Paulo',
  status: 'pendente_revisao_juridica',
  licit_context: {
    impugnacoes: [],
  },
};

const ITEM_COM_GAP: LicitItem = {
  id: 'item-001',
  numero_item: 'Item 02',           // Agente 3 extraiu este número — deve ser visível
  descricao_original: 'Módulo proteico com Registro MS obrigatório',
  score_compatibilidade: 0.82,      // Âmbar — ressalva
  status: 'amarelo',
  justificativa: 'Requer recurso administrativo para justificar a RDC.',
  alertas: [
    'gap_de_informacao: validade_registro_ms', // Campo crítico nulo
  ],
};

const ITEM_SEM_GAP: LicitItem = {
  id: 'item-002',
  numero_item: 'Item 01',
  descricao_original: 'Suplemento hiperproteico 20g',
  score_compatibilidade: 0.96,
  status: 'verde',
  justificativa: 'Aprovado sem ressalvas.',
  alertas: [],
};

// ── Helpers ────────────────────────────────────────────────────────────────
function renderModal(itens: LicitItem[], overrides?: Partial<Edital>) {
  const onApprove = vi.fn().mockResolvedValue(undefined);
  const onReject = vi.fn().mockResolvedValue(undefined);
  const onClose = vi.fn();

  render(
    <ValidationModal
      edital={{ ...EDITAL_FIXTURE, ...overrides }}
      itens={itens}
      onClose={onClose}
      onApprove={onApprove}
      onReject={onReject}
    />
  );

  return { onApprove, onReject, onClose };
}

// ── Tests ──────────────────────────────────────────────────────────────────
describe('ValidationModal — TDD Gatekeeper Humano', () => {

  it('RASTREABILIDADE: exibe o numero_item extraído pelo Agente 3', () => {
    renderModal([ITEM_COM_GAP]);
    // O analista deve ver exatamente "Item 02" — não "Item 1", não "2"
    expect(screen.getByTestId('item-numero-item-001')).toHaveTextContent('Item 02');
  });

  it('ANTI-VIBE: botão Aprovar está DESABILITADO quando há GAP não preenchido', () => {
    renderModal([ITEM_COM_GAP]);
    const btnAprovar = screen.getByTestId('btn-aprovar');
    expect(btnAprovar).toBeDisabled();
  });

  it('ANTI-VIBE: aviso de GAP pendente está visível', () => {
    renderModal([ITEM_COM_GAP]);
    expect(screen.getByTestId('gap-warning')).toBeInTheDocument();
    expect(screen.getByTestId('gap-warning')).toHaveTextContent('GAP');
  });

  it('TRAFFIC LIGHT: badge do score Âmbar exibe a cor correta (0.82 → #F59E0B)', () => {
    renderModal([ITEM_COM_GAP]);
    const badge = screen.getByTestId('score-badge-item-001');
    expect(badge).toHaveTextContent('82%');
    // Verifica a classe CSS do badge âmbar
    expect(badge.className).toMatch(/badgeAmbar/);
  });

  it('GATEKEEPER: preencher o GAP habilita o botão Aprovar', async () => {
    const user = userEvent.setup();
    renderModal([ITEM_COM_GAP]);

    const btnAprovar = screen.getByTestId('btn-aprovar');
    expect(btnAprovar).toBeDisabled(); // Começa desabilitado

    const gapInput = screen.getByTestId('gap-input-item-001-validade_registro_ms');
    await user.type(gapInput, '31/12/2028');

    await waitFor(() => {
      expect(btnAprovar).not.toBeDisabled();
    });
  });

  it('GATEKEEPER: aprovar dispara onApprove com gapCorrections e justificativa', async () => {
    const user = userEvent.setup();
    const { onApprove } = renderModal([ITEM_COM_GAP]);

    // Preenche o campo de GAP
    await user.type(
      screen.getByTestId('gap-input-item-001-validade_registro_ms'),
      '31/12/2028'
    );

    // Edita a justificativa técnica
    const justInput = screen.getByTestId('justificativa-input-item-001');
    await user.clear(justInput);
    await user.type(justInput, 'Justificativa revisada pelo analista sênior.');

    // Confirma aprovação
    await user.click(screen.getByTestId('btn-aprovar'));

    await waitFor(() => {
      expect(onApprove).toHaveBeenCalledOnce();
      const [editalId, nota, gapCorrections, justificativas] = onApprove.mock.calls[0];

      expect(editalId).toBe('edital-001');

      // GAP preenchido deve estar no payload
      expect(gapCorrections['item-001:validade_registro_ms']).toBe('31/12/2028');

      // Justificativa editada deve estar no payload
      expect(justificativas['item-001']).toBe('Justificativa revisada pelo analista sênior.');
    });
  });

  it('REJEITAR: botão Rejeitar dispara onReject com edital_id', async () => {
    const user = userEvent.setup();
    const { onReject } = renderModal([ITEM_COM_GAP]);

    await user.click(screen.getByTestId('btn-rejeitar'));

    await waitFor(() => {
      expect(onReject).toHaveBeenCalledWith('edital-001');
    });
  });

  it('SEM GAP: quando não há GAP, o botão Aprovar está HABILITADO por padrão', () => {
    renderModal([ITEM_SEM_GAP]);
    expect(screen.getByTestId('btn-aprovar')).not.toBeDisabled();
    expect(screen.queryByTestId('gap-warning')).not.toBeInTheDocument();
  });

  it('IMPUGNAÇÃO: exibe minuta de impugnação quando presente no licit_context', () => {
    renderModal([ITEM_COM_GAP], {
      licit_context: {
        impugnacoes: ['Vício de Direcionamento — Lei 14.133/21, Art. 40.'],
      },
    });
    expect(screen.getByTestId('impugnacao-0')).toHaveTextContent('14.133');
  });
});
