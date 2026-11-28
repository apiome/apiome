/**
 * **Contracts settings → Secrets, CI and commit statuses, Agents** — PFX-8.15 (#7312).
 *
 * Secrets:
 * * every secret with what uses it, never a value; a migrated secret reads **No value**, its webhook
 *   is shown off, and one note says what is waiting; axe passes;
 * * **New secret** posts the name, value and description; a bad name or an empty value is refused
 *   before anything is sent; **Set value** / **Replace value** put the value;
 * * **Delete** of a secret in use lists what uses it and sends nothing; an unused one is deleted.
 *
 * CI and commit statuses: the three switches; **Save switches** puts all three; the recipes switch
 * between the four CI systems and are the tested sources; the broker address; axe passes.
 *
 * Agents: the four switches, the two no tool uses yet say so; **Save switches** puts all four;
 * axe passes.
 *
 * Every tab is read-only without the Contracts admin permission and says so once; the tab strip
 * links all five tabs.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-settings-secrets`, `pact-settings-ci`
 * and `pact-settings-agents`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/navigation', () => ({ useRouter: () => ({ replace: jest.fn(), push: jest.fn() }) }));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import fixture from './fixtures/pact-contract-settings.json';
import ContractsSettingsClient from '../src/app/components/ade/pactSettings/ContractsSettingsClient';
import { PACT_CI_RECIPES } from '../lib/pact-ci-recipes.generated';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const SETTINGS = '/api/pact/contract-settings';
const SECRETS = '/api/pact/secrets';
const [STAGING, GITHUB, MIGRATED, UNUSED] = fixture.secrets.secrets;

type Answer = { status: number; body: unknown };
let answers: Record<string, (method: string, body: unknown) => Answer>;
let calls: Array<{ url: string; method: string; body?: unknown }>;

function installFetch() {
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const key = Object.keys(answers)
      .sort((a, b) => b.length - a.length)
      .find((candidate) => url.startsWith(candidate));
    const answer = key ? answers[key](method, body) : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: answer.status < 400, status: answer.status, json: async () => answer.body } as Response;
  }) as unknown as typeof fetch;
}

const writes = () => calls.filter((call) => call.method !== 'GET');

beforeEach(() => {
  calls = [];
  answers = {
    [SETTINGS]: () => ({ status: 200, body: fixture.settings }),
    [`${SETTINGS}/commit-statuses`]: (_m, body) => ({
      status: 200,
      body: { ...fixture.settings, commit_statuses: body },
    }),
    [`${SETTINGS}/agents`]: (_m, body) => ({ status: 200, body: { ...fixture.settings, agents: body } }),
    [SECRETS]: (method, body) =>
      method === 'POST' ? { status: 201, body: { ...UNUSED, ...(body as object) } } : { status: 200, body: fixture.secrets },
    [`${SECRETS}/`]: () => ({ status: 200, body: MIGRATED }),
    '/api/pact/broker-address': () => ({
      status: 200,
      body: { broker_base_url: 'https://api.apiome.dev/v1/tenants/acme/pact-broker' },
    }),
  };
  installFetch();
});

// ---------------------------------------------------------------------------------------------
// Secrets
// ---------------------------------------------------------------------------------------------

describe('Secrets', () => {
  it('lists every secret with what uses it, flags the one waiting for a value, and passes axe', async () => {
    const { container } = render(<ContractsSettingsClient tab="secrets" />);
    const table = await screen.findByTestId('psx-table');
    expect(within(table).getAllByRole('row')).toHaveLength(5);
    expect(screen.getByTestId(`psx-secret-${STAGING.name}`)).toHaveTextContent('verification target staging');
    expect(screen.getByTestId(`psx-secret-${GITHUB.name}`)).toHaveTextContent('3 webhooks');
    const migrated = screen.getByTestId(`psx-secret-${MIGRATED.name}`);
    expect(migrated).toHaveTextContent('No value');
    expect(migrated).toHaveTextContent('1 webhook (1 off)');
    expect(migrated).toHaveTextContent('From migration');
    expect(within(migrated).getByRole('button', { name: 'Set value' })).toBeInTheDocument();
    expect(screen.getByTestId(`psx-secret-${UNUSED.name}`)).toHaveTextContent('Nothing yet');
    expect(screen.getByTestId('psx-waiting')).toHaveTextContent(`${MIGRATED.name} has no value yet`);
    expect(screen.getAllByRole('status').filter((node) => node.dataset.testid === 'psx-waiting')).toHaveLength(1);
    // No value is ever on the page: only references.
    expect(container.textContent).not.toMatch(/ci-token-value|password123/);
    expect(screen.getByTestId('psx-command-block')).toHaveTextContent('POST /v1/tenants/{tenant}/pact-secrets');
    await waitFor(() => expect(screen.getByTestId('psx-new')).toBeInTheDocument());
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-settings-secrets', liveMarkup(container.firstElementChild!));
  });

  it('creates a secret, refusing a bad name or an empty value before sending', async () => {
    render(<ContractsSettingsClient tab="secrets" />);
    fireEvent.click(await screen.findByTestId('psx-new'));
    const dialog = screen.getByTestId('psx-secret-dialog');
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: '1bad-name' } });
    fireEvent.change(within(dialog).getByLabelText('Value'), { target: { value: 's3cret' } });
    fireEvent.click(within(dialog).getByTestId('psx-secret-save'));
    expect(within(dialog).getByTestId('psx-secret-error')).toHaveTextContent('A name starts with a letter');
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'slack_hook' } });
    fireEvent.change(within(dialog).getByLabelText('Value'), { target: { value: '' } });
    fireEvent.click(within(dialog).getByTestId('psx-secret-save'));
    expect(within(dialog).getByTestId('psx-secret-error')).toHaveTextContent('Enter the value.');
    expect(writes()).toHaveLength(0);

    fireEvent.change(within(dialog).getByLabelText('Value'), { target: { value: 'xoxb-123' } });
    fireEvent.change(within(dialog).getByLabelText('Description (optional)'), { target: { value: 'Slack' } });
    fireEvent.click(within(dialog).getByTestId('psx-secret-save'));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({ url: SECRETS, method: 'POST', body: { name: 'slack_hook', value: 'xoxb-123', description: 'Slack' } });
    await waitFor(() => expect(screen.queryByTestId('psx-secret-dialog')).not.toBeInTheDocument());
  });

  it('sets the value of a migrated secret', async () => {
    render(<ContractsSettingsClient tab="secrets" />);
    fireEvent.click(await screen.findByTestId(`psx-value-${MIGRATED.name}`));
    const dialog = screen.getByTestId('psx-secret-dialog');
    expect(dialog).toHaveTextContent(`Set the value of ${MIGRATED.name}`);
    expect(dialog).toHaveTextContent('Its webhooks are turned on once every secret they use has a value.');
    expect(within(dialog).queryByLabelText('Name')).not.toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText('Value'), { target: { value: 'the-real-password' } });
    fireEvent.click(within(dialog).getByTestId('psx-secret-save'));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({
      url: `${SECRETS}/${MIGRATED.id}`,
      method: 'PUT',
      body: { value: 'the-real-password', description: MIGRATED.description },
    });
  });

  it('does not delete a secret in use, and lists what uses it', async () => {
    render(<ContractsSettingsClient tab="secrets" />);
    fireEvent.click(await screen.findByTestId(`psx-delete-${GITHUB.name}`));
    const dialog = screen.getByTestId('psx-delete-dialog');
    expect(dialog).toHaveTextContent(`${GITHUB.name} is in use`);
    expect(within(dialog).getByTestId('psx-blockers')).toHaveTextContent('Webhook “Verify Ledger API”');
    expect(within(dialog).queryByTestId('psx-delete-confirm')).not.toBeInTheDocument();
    expect(writes()).toHaveLength(0);
  });

  it('deletes a secret nothing uses', async () => {
    render(<ContractsSettingsClient tab="secrets" />);
    fireEvent.click(await screen.findByTestId(`psx-delete-${UNUSED.name}`));
    fireEvent.click(screen.getByTestId('psx-delete-confirm'));
    await waitFor(() => expect(writes()).toEqual([{ url: `${SECRETS}/${UNUSED.id}`, method: 'DELETE', body: undefined }]));
  });

  it('shows REST’s refusal of a delete', async () => {
    answers[`${SECRETS}/`] = () => ({ status: 409, body: { success: false, error: 'the secret is still used by webhooks' } });
    render(<ContractsSettingsClient tab="secrets" />);
    fireEvent.click(await screen.findByTestId(`psx-delete-${UNUSED.name}`));
    fireEvent.click(screen.getByTestId('psx-delete-confirm'));
    expect(await screen.findByTestId('psx-delete-error')).toHaveTextContent('still used by webhooks');
  });

  it('is read-only without the Contracts admin permission', async () => {
    answers[SETTINGS] = () => ({ status: 200, body: { ...fixture.settings, can_edit: false } });
    render(<ContractsSettingsClient tab="secrets" />);
    expect(await screen.findByTestId('pcx-read-only')).toHaveTextContent('needs the Contracts admin permission');
    await screen.findByTestId('psx-table');
    expect(screen.queryByTestId('psx-new')).not.toBeInTheDocument();
    expect(screen.queryByTestId(`psx-value-${MIGRATED.name}`)).not.toBeInTheDocument();
    expect(screen.getAllByRole('note')).toHaveLength(1);
  });

  it('offers Try again when the secrets cannot be read', async () => {
    answers[SECRETS] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<ContractsSettingsClient tab="secrets" />);
    expect(await screen.findByText('The secrets could not be read')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------------
// CI and commit statuses
// ---------------------------------------------------------------------------------------------

describe('CI and commit statuses', () => {
  it('shows the switches, the recipes and the broker address, and passes axe', async () => {
    const { container } = render(<ContractsSettingsClient tab="ci" />);
    await screen.findByTestId('pci-switches');
    expect(screen.getByTestId('pci-consumer_commit-switch')).toBeChecked();
    expect(screen.getByTestId('pci-provider_commit-switch')).toBeChecked();
    expect(screen.getByTestId('pci-bidirectional-switch')).not.toBeChecked();
    expect(screen.getByTestId('pci-bidirectional')).toHaveTextContent('fires its verification webhooks');
    expect(screen.getByTestId('pci-recipe')).toHaveTextContent('apiome/apiome/pact-action@main');
    await waitFor(() =>
      expect(screen.getByTestId('pci-broker')).toHaveTextContent(
        'PACT_BROKER_BASE_URL=https://api.apiome.dev/v1/tenants/acme/pact-broker',
      ),
    );
    expect(screen.getByRole('link', { name: /Create a key with Pact scopes/ })).toHaveAttribute('href', '/ade/dashboard/api-keys');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-settings-ci', liveMarkup(container.firstElementChild!));
  });

  it('saves all three switches', async () => {
    render(<ContractsSettingsClient tab="ci" />);
    expect(await screen.findByTestId('pci-save')).toBeDisabled();
    fireEvent.click(screen.getByTestId('pci-bidirectional-switch'));
    fireEvent.click(screen.getByTestId('pci-save'));
    await waitFor(() => expect(screen.getByTestId('pci-message')).toHaveTextContent('Saved.'));
    expect(writes()).toEqual([
      {
        url: `${SETTINGS}/commit-statuses`,
        method: 'PUT',
        body: { consumer_commit: true, provider_commit: true, bidirectional: true },
      },
    ]);
  });

  it('shows REST’s refusal of a save', async () => {
    answers[`${SETTINGS}/commit-statuses`] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<ContractsSettingsClient tab="ci" />);
    fireEvent.click(await screen.findByTestId('pci-provider_commit-switch'));
    fireEvent.click(screen.getByTestId('pci-save'));
    expect(await screen.findByTestId('pci-message')).toHaveTextContent('Permission denied');
  });

  it.each(PACT_CI_RECIPES.map((recipe) => [recipe.id, recipe.label, recipe.file]))(
    'shows the %s recipe',
    async (id, label, file) => {
      render(<ContractsSettingsClient tab="ci" />);
      fireEvent.click(await screen.findByTestId(`pci-recipe-${id}`));
      expect(screen.getByTestId(`pci-recipe-${id}`)).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByTestId('pci-recipe')).toHaveAccessibleName(`${label} recipe`);
      expect(screen.getByTestId('pci-recipes')).toHaveTextContent(`Save it as ${file}`);
    },
  );

  it('is read-only without the Contracts admin permission', async () => {
    answers[SETTINGS] = () => ({ status: 200, body: { ...fixture.settings, can_edit: false } });
    render(<ContractsSettingsClient tab="ci" />);
    expect(await screen.findByTestId('pcx-read-only')).toBeInTheDocument();
    expect(screen.getByTestId('pci-bidirectional-switch')).toBeDisabled();
    expect(screen.queryByTestId('pci-save')).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------------
// Agents
// ---------------------------------------------------------------------------------------------

describe('Agents', () => {
  it('shows the four switches, says which no tool uses yet, and passes axe', async () => {
    const { container } = render(<ContractsSettingsClient tab="agents" />);
    await screen.findByTestId('pag-switches');
    expect(screen.getByTestId('pag-read-switch')).toBeChecked();
    expect(screen.getByTestId('pag-draft-switch')).toBeChecked();
    expect(screen.getByTestId('pag-publish-switch')).not.toBeChecked();
    expect(screen.getByTestId('pag-record-switch')).not.toBeChecked();
    expect(screen.getByTestId('pag-record')).toHaveTextContent('Never to an environment marked production.');
    expect(screen.getByTestId('pag-draft')).toHaveTextContent('No agent tool drafts pacts yet');
    expect(screen.getByTestId('pag-publish')).toHaveTextContent('No agent tool publishes yet');
    expect(screen.getByTestId('pag-command-block')).toHaveTextContent('PUT /v1/tenants/{tenant}/pact-contract-settings/agents');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-settings-agents', liveMarkup(container.firstElementChild!));
  });

  it('saves all four switches', async () => {
    render(<ContractsSettingsClient tab="agents" />);
    fireEvent.click(await screen.findByTestId('pag-record-switch'));
    fireEvent.click(screen.getByTestId('pag-save'));
    await waitFor(() => expect(screen.getByTestId('pag-message')).toHaveTextContent('Saved.'));
    expect(writes()).toEqual([
      { url: `${SETTINGS}/agents`, method: 'PUT', body: { read: true, draft: true, publish: false, record: true } },
    ]);
  });

  it('is read-only without the Contracts admin permission', async () => {
    answers[SETTINGS] = () => ({ status: 200, body: { ...fixture.settings, can_edit: false } });
    render(<ContractsSettingsClient tab="agents" />);
    expect(await screen.findByTestId('pcx-read-only')).toHaveTextContent('what agents may do');
    expect(screen.getByTestId('pag-read-switch')).toBeDisabled();
    expect(screen.queryByTestId('pag-save')).not.toBeInTheDocument();
  });
});

describe('The tab strip', () => {
  it('links all five tabs in the mockup’s order', async () => {
    render(<ContractsSettingsClient tab="agents" />);
    const tabs = within(await screen.findByTestId('pcx-tabs')).getAllByRole('link');
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'Clean-up',
      'Secrets',
      'CI and commit statuses',
      'Verification schedule',
      'Agents',
    ]);
    expect(screen.getByTestId('pcx-tab-agents')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByTestId('pcx-tab-ci')).toHaveAttribute('href', '/ade/dashboard/pacts/settings?tab=ci');
  });
});
