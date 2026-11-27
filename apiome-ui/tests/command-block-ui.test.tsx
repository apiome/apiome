/**
 * `CommandBlock` — **The same, from anywhere** (PFX-8.2, #7299) — and the webhook editor that is
 * its first form.
 *
 * Covers: the pills and their panels, Copy (and a refused clipboard said out loud), a surface that
 * cannot do the action, what no command carries, the scrub of a credential a builder missed, axe,
 * and — through the real editor — that the block follows the form as it is typed and never shows
 * a secret typed into it.
 */

import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import { COPY_FAILED, CommandBlock } from '../src/app/components/ui/CommandBlock';
import { WebhookEditor } from '../src/app/components/ade/pactWebhooks/WebhookPanels';
import { CommandBlockShowcase } from '../src/app/design-system/galleries/CommandBlockShowcase';
import type { CommandSurface } from '../lib/command-block';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };

const SURFACES: CommandSurface[] = [
  { id: 'apiome', label: 'apiome', text: 'apiome pact publish pacts/', notes: ['Reads PACT_BROKER_TOKEN.'] },
  { id: 'pact-cli', label: 'Pact CLI', text: null, unavailable: 'Pact CLI has no command for this.' },
  { id: 'rest', label: 'REST', text: 'POST /v1/x\n\n{"Authorization": "Bearer abcdefgh12345678"}' },
];

let writeText: jest.Mock;

beforeEach(() => {
  writeText = jest.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
});

/** Select a pill the way Radix listens for it. */
function choose(name: string) {
  const tab = screen.getByRole('tab', { name });
  fireEvent.mouseDown(tab, { button: 0 });
  fireEvent.click(tab);
}

describe('CommandBlock', () => {
  it('shows the first surface, its notes, and one pill per surface', () => {
    render(<CommandBlock surfaces={SURFACES} />);
    expect(screen.getByRole('heading', { name: 'The same, from anywhere', level: 3 })).toBeInTheDocument();
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['apiome', 'Pact CLI', 'REST']);
    expect(screen.getByTestId('command-block-code')).toHaveTextContent('apiome pact publish pacts/');
    expect(screen.getByText('Reads PACT_BROKER_TOKEN.')).toBeInTheDocument();
  });

  it('copies the selected surface and says so', async () => {
    render(<CommandBlock surfaces={SURFACES} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy the apiome command' }));
    });
    expect(writeText).toHaveBeenCalledWith('apiome pact publish pacts/');
    expect(screen.getByRole('button', { name: 'Copied the apiome command' })).toBeInTheDocument();
  });

  it('says out loud when the browser refuses the clipboard', async () => {
    writeText.mockRejectedValue(new Error('denied'));
    render(<CommandBlock surfaces={SURFACES} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy the apiome command' }));
    });
    expect(screen.getByTestId('command-block-copy-failed')).toHaveTextContent(COPY_FAILED);
  });

  it('shows the reason, and cannot copy, on a surface that cannot do the action', () => {
    render(<CommandBlock surfaces={SURFACES} />);
    choose('Pact CLI');
    expect(screen.getByTestId('command-block-unavailable')).toHaveTextContent('Pact CLI has no command for this.');
    expect(screen.queryByTestId('command-block-code')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy the Pact CLI command' })).toBeDisabled();
  });

  it('scrubs a credential a builder let through, on screen and in the copy', async () => {
    render(<CommandBlock surfaces={SURFACES} />);
    choose('REST');
    expect(screen.getByTestId('command-block-code')).not.toHaveTextContent('abcdefgh12345678');
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy the REST command' }));
    });
    expect(writeText.mock.calls[0][0]).not.toContain('abcdefgh12345678');
    expect(writeText.mock.calls[0][0]).toContain('Bearer <redacted>');
  });

  it('lists what no command carries, and the footnote', () => {
    render(<CommandBlock surfaces={SURFACES} unsupported={['The signing secret is not carried.']} footnote="CI fills the version." />);
    expect(screen.getByTestId('command-block-unsupported')).toHaveTextContent('Not carried by the command');
    expect(screen.getByTestId('command-block-unsupported')).toHaveTextContent('The signing secret is not carried.');
    expect(screen.getByText('CI fills the version.')).toBeInTheDocument();
  });

  it('starts on the surface asked for, and draws nothing for no surfaces', () => {
    const { container, rerender } = render(<CommandBlock surfaces={SURFACES} defaultSurface="rest" headingLevel={4} />);
    expect(screen.getByRole('heading', { level: 4 })).toBeInTheDocument();
    expect(screen.getByTestId('command-block-code')).toHaveTextContent('POST /v1/x');
    rerender(<CommandBlock surfaces={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('has no axe violations', async () => {
    const { container } = render(<CommandBlock surfaces={SURFACES} unsupported={['x is not carried.']} />);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});

describe('the gallery specimen', () => {
  it('follows its publish form as it is typed', () => {
    render(<CommandBlockShowcase />);
    const block = screen.getByTestId('gallery-command-block-publish');
    expect(within(block).getByTestId('command-block-code')).toHaveTextContent('--branch feature/credit-notes');
    fireEvent.change(screen.getByLabelText('Branch'), { target: { value: 'main' } });
    expect(within(block).getByTestId('command-block-code')).toHaveTextContent('--branch main');
    expect(within(block).getByTestId('command-block-code')).not.toHaveTextContent('feature/credit-notes');
  });

  it('never shows the specimen webhook’s secrets', () => {
    const { container } = render(<CommandBlockShowcase />);
    for (const secret of ['s3cr3t-token-value', 'hunter2-hunter2', 'a-signing-secret-of-16+']) {
      expect(container).not.toHaveTextContent(secret);
    }
  });

  it('has no axe violations', async () => {
    const { container } = render(<CommandBlockShowcase />);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});

describe('the webhook editor’s block', () => {
  /** Render a new-webhook editor. */
  function editor() {
    render(<WebhookEditor webhook={null} onSave={jest.fn()} onTest={jest.fn()} onClose={jest.fn()} />);
    return screen.getByTestId('pwx-editor');
  }

  it('follows the form as it is typed', () => {
    const dialog = editor();
    const block = within(dialog).getByTestId('pwx-command-block');
    expect(within(block).getByTestId('command-block-code')).toHaveTextContent("apiome pact create-webhook '<url>'");
    fireEvent.change(within(dialog).getByLabelText('URL'), { target: { value: 'https://ci.example.com/hooks/verify' } });
    fireEvent.change(within(dialog).getByLabelText('Provider (optional)'), { target: { value: 'Ledger API' } });
    fireEvent.click(within(dialog).getByLabelText('Contract published'));
    const code = within(block).getByTestId('command-block-code');
    expect(code).toHaveTextContent('apiome pact create-webhook https://ci.example.com/hooks/verify');
    expect(code).toHaveTextContent("--provider 'Ledger API'");
    expect(code).toHaveTextContent('--contract-published');
  });

  it('never shows a password, a secret header or a signing secret typed into it', async () => {
    const dialog = editor();
    fireEvent.change(within(dialog).getByLabelText('URL'), { target: { value: 'https://ci.example.com/hooks/verify' } });
    fireEvent.change(within(dialog).getByLabelText(/^Headers — one/), {
      target: { value: 'Authorization: Bearer typed-header-secret' },
    });
    fireEvent.change(within(dialog).getByLabelText('Basic auth username (optional)'), { target: { value: 'ci-bot' } });
    fireEvent.change(within(dialog).getByLabelText('Password (optional)'), { target: { value: 'typed-password-1' } });
    fireEvent.change(within(dialog).getByLabelText('Signing secret (optional, 16 characters or more)'), {
      target: { value: 'typed-signing-secret-1' },
    });
    const block = within(dialog).getByTestId('pwx-command-block');
    for (const name of ['apiome', 'Pact CLI', 'GitHub Action', 'REST']) {
      const tab = within(block).getByRole('tab', { name });
      fireEvent.mouseDown(tab, { button: 0 });
      fireEvent.click(tab);
      for (const secret of ['typed-header-secret', 'typed-password-1', 'typed-signing-secret-1']) {
        expect(block).not.toHaveTextContent(secret);
      }
    }
    expect(within(block).getByTestId('command-block-code')).toHaveTextContent('"password": "$WEBHOOK_PASSWORD"');
    expect(within(block).getByTestId('command-block-unsupported')).toHaveTextContent('The signing secret');
  });

  it('shows REST only, with the reason, when editing a saved webhook', () => {
    const webhook = {
      uuid: '8f7f2a0e-3c1d-4f6b-9a55-1d2f4c6b7a90',
      description: 'Verify Ledger',
      events: [{ name: 'contract_published' }],
      enabled: true,
      request: { method: 'POST', url: 'https://ci.example.com/h', password: '**********', username: 'bot' },
    };
    render(<WebhookEditor webhook={webhook as never} onSave={jest.fn()} onClose={jest.fn()} />);
    const block = screen.getByTestId('pwx-command-block');
    expect(within(block).getByTestId('command-block-unavailable')).toHaveTextContent('No apiome pact command changes a saved webhook');
    const tab = within(block).getByRole('tab', { name: 'REST' });
    fireEvent.mouseDown(tab, { button: 0 });
    fireEvent.click(tab);
    expect(within(block).getByTestId('command-block-code')).toHaveTextContent(
      'PUT /v1/tenants/{tenant}/pact-broker/webhooks/8f7f2a0e-3c1d-4f6b-9a55-1d2f4c6b7a90',
    );
  });
});
