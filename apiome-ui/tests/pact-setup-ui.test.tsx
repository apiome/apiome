/**
 * **Set up contracts** — PFX-8.20 (#7317), `/ade/dashboard/pacts/setup`.
 *
 * * six sections with Done / Next / To do, only the next one open; the aside counts progress and
 *   carries `apiome pact setup`; axe passes;
 * * **Who talks to whom**: only candidates that are not pacticipants yet are created, one request
 *   each; a refusal names its service; nothing detected offers Add one by hand and an import link;
 * * **Where things run**: existing environments cannot be created twice; a bad name is refused before
 *   anything is sent; production carries the contract switch;
 * * **Connect your pipelines**: the key is created with the Pact consumer + deploy scopes, shown once
 *   and recorded by id and prefix; secrets are written with it; each repository's outcome is listed;
 *   without a linked GitHub account the action is a copyable snippet;
 * * **The first consumer pact**: two paths, the choice saved, the button going to the page that does it;
 * * **The provider's side**: the spec-as-contract switch is put through the existing sources route;
 * * **Gate deploys**: pull requests for linked repositories; a skipped one shows its workflow;
 *   **Show the workflow** previews; **Finish set-up** marks the section;
 * * not an admin: readable, every action replaced by "Ask a Contracts admin";
 * * a migrated workspace says so; a failed read offers Try again.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `pact-setup`.
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
jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: { current_tenant_id: 'tenant-1' } } }),
}));
const createKey = jest.fn();
jest.mock('../src/app/components/ade/apiKeys/apiKeysApi', () => ({
  createApiKeyForTenant: (input: unknown) => createKey(input),
}));

import fixture from './fixtures/pact-setup.json';
import { SetupClient } from '../src/app/components/ade/pactSetup';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const SETUP = '/api/pact/setup';
const [BILLING, ORDERS] = fixture.github.repositories;
const KEY_ID = '55555555-5555-4555-8555-555555555555';
const SECRET = 'apk_live_0123456789abcdef';

type State = typeof fixture;
type Answer = { status: number; body: unknown };
let state: State;
let answers: Record<string, (method: string, body: unknown) => Answer>;
let calls: Array<{ url: string; method: string; body?: unknown }>;

/** The fixture with some sections' states replaced. */
function withStates(states: Partial<Record<string, string>>, extra: Partial<State> = {}): State {
  return {
    ...fixture,
    ...extra,
    sections: fixture.sections.map((section) => ({ ...section, state: states[section.id] ?? section.state })),
  } as State;
}

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

async function open(section: string) {
  const toggle = await screen.findByTestId(`pset-${section}-toggle`);
  if (toggle.getAttribute('aria-expanded') !== 'true') fireEvent.click(toggle);
  return screen.findByTestId(`pset-${section}-form`);
}

beforeEach(() => {
  calls = [];
  state = fixture;
  createKey.mockReset();
  createKey.mockResolvedValue({ id: KEY_ID, secret: SECRET, keyPrefix: 'apk_live_01...', scopes: ['pact:read', 'pact:publish'] });
  answers = {
    [SETUP]: (method) => (method === 'PUT' ? { status: 200, body: state } : { status: 200, body: state }),
    [`${SETUP}/github/secrets`]: (_m, body) => ({
      status: 200,
      body: {
        results: (body as { repository_ids: string[] }).repository_ids.map((id) => ({
          repository_id: id,
          full_name: id === BILLING.id ? BILLING.full_name : ORDERS.full_name,
          status: id === BILLING.id ? 'written' : 'skipped',
          reason: id === BILLING.id ? null : 'The linked account may not do this in acme/orders-ui.',
          names: id === BILLING.id ? ['PACT_BROKER_BASE_URL', 'PACT_BROKER_TOKEN'] : [],
        })),
      },
    }),
    [`${SETUP}/github/pull-requests`]: (_m, body) => {
      const sent = body as { preview: boolean; repositories: Array<{ repository_id: string; pacticipant: string }> };
      return {
        status: 200,
        body: {
          results: sent.repositories.map((row) => ({
            repository_id: row.repository_id,
            full_name: row.repository_id === BILLING.id ? BILLING.full_name : ORDERS.full_name,
            status: sent.preview ? 'preview' : row.repository_id === BILLING.id ? 'opened' : 'skipped',
            reason: sent.preview || row.repository_id === BILLING.id ? null : 'The linked account cannot push to acme/orders-ui. Add the workflow by hand.',
            url: sent.preview || row.repository_id !== BILLING.id ? null : 'https://github.com/acme/billing-service/pull/7',
            number: sent.preview || row.repository_id !== BILLING.id ? null : 7,
            path: '.github/workflows/apiome-contracts.yml',
            content: `name: apiome-contracts\n# ${row.pacticipant}\n`,
          })),
        },
      };
    },
    '/api/pact/pacticipants': (_m, body) => ({ status: 201, body: { slug: 'payments-api', ...(body as object), labels: [], aliases: [] } }),
    '/api/pact/environments': () => ({ status: 201, body: {} }),
    '/api/pact/provider-contracts/sources': () => ({ status: 200, body: {} }),
    '/api/pact/broker-address': () => ({ status: 200, body: { broker_base_url: 'https://api.apiome.dev/v1/tenants/acme/pact-broker' } }),
  };
  installFetch();
});

describe('the page', () => {
  it('draws six sections, opens only the next one, counts progress and passes axe', async () => {
    const { container } = render(<SetupClient />);
    await screen.findByTestId('pset-pipelines-form');
    expect(screen.getAllByRole('heading', { level: 2 }).slice(0, 6).map((heading) => heading.textContent)).toEqual([
      expect.stringContaining('Who talks to whom'),
      expect.stringContaining('Where things run'),
      expect.stringContaining('Connect your pipelines'),
      expect.stringContaining('The first consumer pact'),
      expect.stringContaining('The provider’s side'.replace('’', "'")),
      expect.stringContaining('Gate deploys and tell people'),
    ]);
    expect(screen.getByTestId('pset-pacticipants-state')).toHaveTextContent('Done');
    expect(screen.getByTestId('pset-pipelines-state')).toHaveTextContent('Next');
    expect(screen.getByTestId('pset-gates-state')).toHaveTextContent('To do');
    expect(screen.getByTestId('pset-pipelines-toggle')).toHaveAttribute('aria-expanded', 'true');
    for (const closed of ['pacticipants', 'environments', 'first-pact', 'provider', 'gates']) {
      expect(screen.getByTestId(`pset-${closed}-toggle`)).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByTestId(`pset-${closed}-form`)).not.toBeInTheDocument();
    }
    const progress = screen.getByTestId('pset-progress');
    expect(progress).toHaveTextContent('2/6');
    expect(screen.getByTestId('pset-minutes')).toHaveTextContent('About 8 minutes left');
    expect(screen.getByTestId('pset-command-block')).toHaveTextContent('apiome pact setup');
    expect(screen.getByTestId('pset-command-block')).toHaveTextContent('--environments production,staging');
    expect(screen.getByTestId('pset-migrate')).toHaveAttribute('href', '/ade/dashboard/pacts/migrate');
    expect(screen.getByTestId('pset-finish-later')).toHaveAttribute('href', '/ade/dashboard/pacts');
    expect(screen.getByTestId('contracts-tabs')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('pset-variables')).toHaveTextContent('https://api.apiome.dev/v1/tenants/acme/pact-broker'));
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-setup', liveMarkup(container.firstElementChild!));
  });

  it('toggles a section open and closed', async () => {
    render(<SetupClient />);
    await open('pacticipants');
    fireEvent.click(screen.getByTestId('pset-pacticipants-toggle'));
    expect(screen.queryByTestId('pset-pacticipants-form')).not.toBeInTheDocument();
    // The next section stays open: opening another does not close it.
    expect(screen.getByTestId('pset-pipelines-form')).toBeInTheDocument();
  });

  it('offers Try again when the set-up cannot be read', async () => {
    answers[SETUP] = () => ({ status: 503, body: { success: false, error: 'The Pact Broker is unavailable.' } });
    render(<SetupClient />);
    expect(await screen.findByText('The Pact Broker is unavailable.')).toBeInTheDocument();
    answers[SETUP] = () => ({ status: 200, body: fixture });
    fireEvent.click(screen.getByRole('button', { name: /Try again/ }));
    expect(await screen.findByTestId('pset-pipelines-form')).toBeInTheDocument();
  });

  it('refuses an answer it does not know rather than drawing half a page', async () => {
    answers[SETUP] = () => ({ status: 200, body: { sections: [] } });
    render(<SetupClient />);
    expect(await screen.findByText(/shape this page does not know/)).toBeInTheDocument();
  });

  it('says a migrated workspace was copied and that a finished one is done', async () => {
    state = withStates(
      { pipelines: 'done', 'first-pact': 'done', provider: 'done', gates: 'done' },
      { facts: { ...fixture.facts, migrated: true }, done: 6, complete: true } as Partial<State>,
    );
    render(<SetupClient />);
    expect(await screen.findByTestId('pset-migrated')).toHaveTextContent('copied from another broker');
    expect(screen.getByTestId('pset-complete')).toHaveTextContent('All six steps are done');
    expect(screen.getByTestId('pset-minutes')).toHaveTextContent('Everything is set up.');
    // Nothing is open when nothing is next.
    expect(screen.queryByTestId('pset-pipelines-form')).not.toBeInTheDocument();
  });
});

describe('Who talks to whom', () => {
  it('creates only the candidates that are not pacticipants yet', async () => {
    render(<SetupClient />);
    const form = await open('pacticipants');
    expect(within(form).getByTestId('pset-candidate-billing-api')).toHaveTextContent('Already a pacticipant');
    expect(within(form).getByTestId('pset-candidate-billing-api')).toHaveTextContent('Payments team');
    expect(within(form).getByTestId('pset-candidate-orders-ui')).toHaveTextContent('Consumer');
    expect(within(form).getByTestId('pset-candidate-payments-api')).toHaveTextContent('No owner');
    expect(within(form).getByLabelText('Billing API is already a pacticipant')).toBeDisabled();
    fireEvent.click(within(form).getByTestId('pset-create-pacticipants'));
    await waitFor(() => expect(screen.getByTestId('pset-pacticipants-message')).toHaveTextContent('1 pacticipant created.'));
    expect(writes()).toEqual([{ url: '/api/pact/pacticipants', method: 'POST', body: { name: 'Payments API', project: 'payments-api' } }]);
  });

  it('names the service a refusal is about', async () => {
    answers['/api/pact/pacticipants'] = () => ({ status: 409, body: { success: false, error: "a pacticipant 'payments-api' already exists in this tenant" } });
    render(<SetupClient />);
    const form = await open('pacticipants');
    fireEvent.click(within(form).getByTestId('pset-create-pacticipants'));
    await waitFor(() => expect(screen.getByTestId('pset-pacticipants-message')).toHaveTextContent('Payments API: a pacticipant'));
    expect(screen.getByTestId('pset-pacticipants-message')).toHaveAttribute('role', 'alert');
  });

  it('creates nothing with nothing ticked', async () => {
    render(<SetupClient />);
    const form = await open('pacticipants');
    fireEvent.click(within(form).getByLabelText('Create Payments API'));
    expect(within(form).getByTestId('pset-create-pacticipants')).toBeDisabled();
  });

  it('offers Add one by hand and an import link when nothing is detected', async () => {
    state = withStates({ pacticipants: 'next', environments: 'todo', pipelines: 'todo' }, { candidates: [], facts: { ...fixture.facts, pacticipants: 0 } } as Partial<State>);
    render(<SetupClient />);
    const form = await screen.findByTestId('pset-pacticipants-form');
    expect(within(form).getByTestId('pset-nothing-detected')).toHaveTextContent('found no projects or repositories');
    expect(within(form).getByRole('link', { name: 'import a project' })).toHaveAttribute('href', '/ade/dashboard/import');
    expect(within(form).getByTestId('pset-add-by-hand')).toHaveAttribute('href', '/ade/dashboard/pacts/pacticipants');
    expect(within(form).queryByTestId('pset-create-pacticipants')).not.toBeInTheDocument();
  });

  it('says how many were left off a capped list', async () => {
    state = { ...fixture, candidates_omitted: 12 };
    render(<SetupClient />);
    await open('pacticipants');
    expect(screen.getByTestId('pset-candidates-omitted')).toHaveTextContent('12 more projects and repositories are not listed here');
  });
});

describe('Where things run', () => {
  it('cannot create an environment twice and refuses a bad name before sending', async () => {
    render(<SetupClient />);
    const form = await open('environments');
    expect(within(form).getByTestId('pset-env-production').querySelector('input')).toBeDisabled();
    expect(within(form).getByTestId('pset-create-environments')).toBeDisabled();
    fireEvent.change(within(form).getByTestId('pset-env-another'), { target: { value: 'pre prod' } });
    fireEvent.click(within(form).getByTestId('pset-env-add'));
    expect(screen.getByTestId('pset-environments-message')).toHaveTextContent('one word');
    fireEvent.change(within(form).getByTestId('pset-env-another'), { target: { value: 'staging' } });
    fireEvent.click(within(form).getByTestId('pset-env-add'));
    expect(screen.getByTestId('pset-environments-message')).toHaveTextContent('already there');
    expect(writes()).toEqual([]);
  });

  it('creates the ticked environments, production with the contract switch', async () => {
    state = withStates({ environments: 'next', pipelines: 'todo' }, { facts: { ...fixture.facts, environments: [] } } as Partial<State>);
    render(<SetupClient />);
    const form = await screen.findByTestId('pset-environments-form');
    expect(within(form).getByTestId('pset-env-require-row')).toBeInTheDocument();
    fireEvent.change(within(form).getByTestId('pset-env-another'), { target: { value: 'qa' } });
    fireEvent.click(within(form).getByTestId('pset-env-add'));
    fireEvent.click(within(form).getByTestId('pset-create-environments'));
    await waitFor(() => expect(screen.getByTestId('pset-environments-message')).toHaveTextContent('3 environments created.'));
    expect(writes().map((call) => call.body)).toEqual([
      { name: 'production', displayName: 'Production', production: true, contractRequired: true, contacts: [] },
      { name: 'staging', displayName: 'Staging', production: false, contractRequired: false, contacts: [] },
      { name: 'qa', displayName: 'qa', production: false, contractRequired: false, contacts: [] },
    ]);
  });

  it('says which environment was refused and why', async () => {
    state = withStates({ environments: 'next', pipelines: 'todo' }, { facts: { ...fixture.facts, environments: [] } } as Partial<State>);
    answers['/api/pact/environments'] = (_m, body) =>
      (body as { name: string }).name === 'staging' ? { status: 409, body: { success: false, error: 'the name is taken' } } : { status: 201, body: {} };
    render(<SetupClient />);
    const form = await screen.findByTestId('pset-environments-form');
    fireEvent.click(within(form).getByTestId('pset-create-environments'));
    await waitFor(() => expect(screen.getByTestId('pset-environments-message')).toHaveTextContent('1 created. Not created — staging: the name is taken'));
  });
});

describe('Connect your pipelines', () => {
  it('creates a scoped key, shows it once, records it and writes the secrets with it', async () => {
    render(<SetupClient />);
    const form = await screen.findByTestId('pset-pipelines-form');
    expect(within(form).getByTestId('pset-write-secrets')).toBeDisabled();
    fireEvent.click(within(form).getByTestId('pset-create-key'));
    expect(await screen.findByTestId('pset-key-secret')).toHaveTextContent(SECRET);
    expect(createKey).toHaveBeenCalledWith(expect.objectContaining({ tenantId: 'tenant-1', scopes: ['pact:read', 'pact:publish'], expiresInDays: null }));
    expect(createKey.mock.calls[0][0].name).toMatch(/^Contracts CI \(set-up /);
    expect(writes()).toEqual([{ url: SETUP, method: 'PUT', body: { ci_key: { id: KEY_ID, prefix: 'apk_live_01...' } } }]);
    // The key is the one written; no second key is offered while it is on the page.
    expect(within(form).queryByTestId('pset-create-key')).not.toBeInTheDocument();
    expect(within(form).queryByTestId('pset-key-paste')).not.toBeInTheDocument();
    fireEvent.click(within(form).getByTestId('pset-write-secrets'));
    const results = await screen.findByTestId('pset-secrets-results');
    expect(results).toHaveTextContent('acme/billing-service — PACT_BROKER_BASE_URL and PACT_BROKER_TOKEN written.');
    expect(results).toHaveTextContent('acme/orders-ui — not written. The linked account may not do this');
    expect(writes()[1]).toEqual({ url: `${SETUP}/github/secrets`, method: 'POST', body: { repository_ids: [BILLING.id, ORDERS.id], token: SECRET } });
    // Collapsing and reopening keeps the key on the page.
    fireEvent.click(screen.getByTestId('pset-pipelines-toggle'));
    fireEvent.click(screen.getByTestId('pset-pipelines-toggle'));
    expect(screen.getByTestId('pset-key-secret')).toHaveTextContent(SECRET);
  });

  it('shows a recorded key instead of creating a second one, and takes a pasted key for the secrets', async () => {
    state = { ...fixture, saved: { ...fixture.saved, ci_key: { id: KEY_ID, prefix: 'apk_live_01...' } } } as unknown as State;
    render(<SetupClient />);
    const form = await screen.findByTestId('pset-pipelines-form');
    expect(within(form).getByTestId('pset-key-saved')).toHaveTextContent('apk_live_01...');
    expect(within(form).getByTestId('pset-create-key')).toHaveTextContent('Create another key');
    fireEvent.click(within(form).getByTestId(`pset-repo-${ORDERS.id}`).querySelector('input')!);
    fireEvent.change(within(form).getByTestId('pset-key-paste'), { target: { value: SECRET } });
    fireEvent.click(within(form).getByTestId('pset-write-secrets'));
    await screen.findByTestId('pset-secrets-results');
    expect(writes()).toEqual([{ url: `${SETUP}/github/secrets`, method: 'POST', body: { repository_ids: [BILLING.id], token: SECRET } }]);
    expect(createKey).not.toHaveBeenCalled();
  });

  it('says so when the key cannot be created, and when it was created but not recorded', async () => {
    createKey.mockRejectedValueOnce(new Error('A key with this name already exists'));
    render(<SetupClient />);
    const form = await screen.findByTestId('pset-pipelines-form');
    fireEvent.click(within(form).getByTestId('pset-create-key'));
    await waitFor(() => expect(screen.getByTestId('pset-pipelines-message')).toHaveTextContent('A key with this name already exists'));
    answers[SETUP] = (method) => (method === 'PUT' ? { status: 403, body: { success: false, error: 'Permission denied' } } : { status: 200, body: fixture });
    fireEvent.click(within(form).getByTestId('pset-create-key'));
    await waitFor(() => expect(screen.getByTestId('pset-pipelines-message')).toHaveTextContent('created but the set-up could not record it (Permission denied)'));
    expect(screen.getByTestId('pset-key-secret')).toHaveTextContent(SECRET);
  });

  it('degrades to copyable commands without a linked GitHub account', async () => {
    state = {
      ...fixture,
      github: { linked: false, reason: 'No registered repository has a linked GitHub account, so Apiome cannot write to one.', repositories: [{ ...ORDERS, linked: false }] },
    } as unknown as State;
    render(<SetupClient />);
    const form = await screen.findByTestId('pset-pipelines-form');
    const snippet = within(form).getByTestId('pset-secrets-snippet');
    expect(snippet).toHaveTextContent('No registered repository has a linked GitHub account');
    await waitFor(() =>
      expect(within(snippet).getByTestId('pset-secrets-commands')).toHaveTextContent(
        'gh secret set PACT_BROKER_BASE_URL --repo acme/orders-ui --body "https://api.apiome.dev/v1/tenants/acme/pact-broker"',
      ),
    );
    expect(within(snippet).getByTestId('pset-secrets-commands')).toHaveTextContent('"$APIOME_API_KEY"');
    expect(within(form).queryByTestId('pset-write-secrets')).not.toBeInTheDocument();
  });

  it('marks pipelines connected by hand', async () => {
    render(<SetupClient />);
    const form = await screen.findByTestId('pset-pipelines-form');
    fireEvent.click(within(form).getByTestId('pset-pipelines-mark'));
    await waitFor(() => expect(writes()).toEqual([{ url: SETUP, method: 'PUT', body: { mark: { pipelines: true } } }]));
  });

  it('copies the variables', async () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<SetupClient />);
    await screen.findByTestId('pset-pipelines-form');
    fireEvent.click(screen.getByTestId('pset-variables-copy'));
    await waitFor(() => expect(screen.getByTestId('pset-variables-copy')).toHaveTextContent('Copied'));
    expect(writeText.mock.calls[0][0]).toContain('PACT_BROKER_TOKEN=<the key above>');
  });
});

describe('The first consumer pact', () => {
  it('offers two paths, saves the choice and goes to the page that does it', async () => {
    render(<SetupClient />);
    const form = await open('first-pact');
    expect(within(form).getAllByRole('radio')).toHaveLength(2);
    expect(within(form).queryByText(/mock/i)).not.toBeInTheDocument();
    expect(within(form).getByTestId('pset-first-pact-go')).toHaveAttribute('href', '/ade/dashboard/pacts/publish');
    fireEvent.click(within(form).getByLabelText(/Start from the spec/));
    await waitFor(() => expect(writes()).toEqual([{ url: SETUP, method: 'PUT', body: { first_pact_path: 'spec' } }]));
    expect(within(form).getByTestId('pset-first-pact-go')).toHaveAttribute('href', '/ade/dashboard/pacts/export?kind=pact');
    expect(within(form).getByTestId('pset-first-pact-go')).toHaveTextContent('Derive a pact');
  });
});

describe("The provider's side", () => {
  it('turns the spec into the contract through the sources route', async () => {
    render(<SetupClient />);
    const form = await open('provider');
    const row = within(form).getByTestId('pset-provider-billing-service');
    expect(row).toHaveTextContent('Use each published version of Billing API as the provider contract of Billing Service');
    fireEvent.click(within(row).getByTestId('pset-provider-billing-service-on'));
    await waitFor(() => expect(screen.getByTestId('pset-provider-message')).toHaveTextContent('Turned on for Billing Service.'));
    expect(writes()).toEqual([{ url: '/api/pact/provider-contracts/sources', method: 'PUT', body: { provider: 'billing-service', onProjectPublish: true } }]);
    expect(within(form).getByTestId('pset-provider-verify')).toHaveAttribute('href', '/ade/dashboard/pacts/verification/new');
  });

  it('shows a source that is on and cannot turn it on twice; a refusal is shown', async () => {
    state = { ...fixture, candidates: fixture.candidates.map((candidate, index) => (index === 0 ? { ...candidate, contract_source: true } : candidate)) };
    const { unmount } = render(<SetupClient />);
    let form = await open('provider');
    expect(within(form).getByTestId('pset-provider-billing-service')).toHaveTextContent('On');
    expect(within(form).queryByTestId('pset-provider-billing-service-on')).not.toBeInTheDocument();
    unmount();
    state = fixture;
    answers['/api/pact/provider-contracts/sources'] = () => ({ status: 422, body: { success: false, error: 'the pacticipant is bound to no project' } });
    render(<SetupClient />);
    form = await open('provider');
    fireEvent.click(within(form).getByTestId('pset-provider-billing-service-on'));
    await waitFor(() => expect(screen.getByTestId('pset-provider-message')).toHaveTextContent('bound to no project'));
  });

  it('says when no pacticipant is bound to a project', async () => {
    state = { ...fixture, candidates: [] };
    render(<SetupClient />);
    const form = await open('provider');
    expect(within(form).getByTestId('pset-no-providers')).toBeInTheDocument();
  });
});

describe('Gate deploys and tell people', () => {
  it('opens pull requests for the ticked repositories and shows the workflow of a skipped one', async () => {
    render(<SetupClient />);
    const form = await open('gates');
    expect(within(form).getByTestId('pset-gate-environment')).toHaveValue('production');
    expect(within(form).getByTestId(`pset-gate-repo-${BILLING.id}-name`)).toHaveValue('Billing Service');
    fireEvent.click(within(form).getByTestId('pset-open-pull-requests'));
    const results = await screen.findByTestId('pset-pull-request-results');
    expect(writes()).toEqual([
      {
        url: `${SETUP}/github/pull-requests`,
        method: 'POST',
        body: {
          repositories: [
            { repository_id: BILLING.id, pacticipant: 'Billing Service' },
            { repository_id: ORDERS.id, pacticipant: 'Orders UI' },
          ],
          environment: 'production',
          can_i_deploy: true,
          record_deployment: true,
          preview: false,
        },
      },
    ]);
    expect(within(results).getByRole('link', { name: '#7' })).toHaveAttribute('href', 'https://github.com/acme/billing-service/pull/7');
    expect(results).toHaveTextContent('acme/orders-ui — No pull request. The linked account cannot push');
    expect(within(results).getByTestId(`pset-workflow-${ORDERS.id}`)).toHaveTextContent('# Orders UI');
    expect(within(results).queryByTestId(`pset-workflow-${BILLING.id}`)).not.toBeInTheDocument();
  });

  it('needs a pacticipant for every ticked repository and at least one step', async () => {
    render(<SetupClient />);
    const form = await open('gates');
    fireEvent.change(within(form).getByTestId(`pset-gate-repo-${ORDERS.id}-name`), { target: { value: ' ' } });
    expect(within(form).getByTestId('pset-gate-unnamed')).toHaveTextContent('acme/orders-ui');
    expect(within(form).getByTestId('pset-open-pull-requests')).toBeDisabled();
    fireEvent.click(within(form).getByLabelText('Include acme/orders-ui'));
    expect(within(form).getByTestId('pset-open-pull-requests')).toHaveTextContent('Open 1 pull request');
    fireEvent.click(within(form).getByTestId('pset-gate-cid'));
    fireEvent.click(within(form).getByTestId('pset-gate-record'));
    expect(within(form).getByTestId('pset-open-pull-requests')).toBeDisabled();
    expect(writes()).toEqual([]);
  });

  it('previews the workflow, and only previews without a linked GitHub account', async () => {
    state = {
      ...fixture,
      github: { linked: false, reason: 'No registered repository has a linked GitHub account, so Apiome cannot write to one.', repositories: [{ ...BILLING, linked: false }] },
    } as unknown as State;
    render(<SetupClient />);
    const form = await open('gates');
    expect(within(form).getByTestId('pset-gates-degraded')).toHaveTextContent('No registered repository has a linked GitHub account');
    expect(within(form).queryByTestId('pset-open-pull-requests')).not.toBeInTheDocument();
    fireEvent.click(within(form).getByTestId('pset-show-workflow'));
    const results = await screen.findByTestId('pset-pull-request-results');
    expect(writes()[0].body).toMatchObject({ preview: true, repositories: [{ repository_id: BILLING.id, pacticipant: 'Billing Service' }] });
    expect(within(results).getByTestId(`pset-workflow-${BILLING.id}`)).toHaveTextContent('name: apiome-contracts');
    expect(results).toHaveTextContent('.github/workflows/apiome-contracts.yml');
  });

  it('points to the pipeline recipes when no GitHub repository is registered', async () => {
    state = { ...fixture, github: { linked: false, reason: 'No GitHub repository is registered in this workspace.', repositories: [] } } as unknown as State;
    render(<SetupClient />);
    const form = await open('gates');
    expect(within(form).getByTestId('pset-gates-recipes')).toHaveTextContent('GitLab CI');
    expect(within(form).queryByTestId('pset-show-workflow')).not.toBeInTheDocument();
    expect(within(form).getByTestId('pset-gates-settings')).toHaveAttribute('href', '/ade/dashboard/pacts/settings?tab=ci');
  });

  it('finishes the set-up, and says when GitHub could not be reached', async () => {
    render(<SetupClient />);
    const form = await open('gates');
    fireEvent.click(within(form).getByTestId('pset-finish'));
    await waitFor(() => expect(writes()).toEqual([{ url: SETUP, method: 'PUT', body: { mark: { gates: true } } }]));
    answers[`${SETUP}/github/pull-requests`] = () => ({ status: 503, body: { success: false, error: 'The Pact Broker is unavailable.' } });
    await waitFor(() => expect(within(form).getByTestId('pset-open-pull-requests')).toBeEnabled());
    fireEvent.click(within(form).getByTestId('pset-open-pull-requests'));
    await waitFor(() => expect(screen.getByTestId('pset-gates-message')).toHaveTextContent('The Pact Broker is unavailable.'));
  });
});

describe('not a Contracts admin', () => {
  it('is readable, with every action replaced by Ask a Contracts admin', async () => {
    state = { ...fixture, can_edit: false };
    const { container } = render(<SetupClient />);
    expect(await screen.findByTestId('pset-read-only')).toHaveTextContent('ask a Contracts admin');
    for (const section of ['pacticipants', 'environments', 'provider', 'gates']) await open(section);
    expect(screen.getAllByTestId('pset-ask-admin').length).toBeGreaterThanOrEqual(5);
    for (const action of [
      'pset-create-pacticipants',
      'pset-create-environments',
      'pset-env-add',
      'pset-create-key',
      'pset-write-secrets',
      'pset-pipelines-mark',
      'pset-provider-billing-service-on',
      'pset-provider-mark',
      'pset-open-pull-requests',
      'pset-finish',
    ]) {
      expect(screen.queryByTestId(action)).not.toBeInTheDocument();
    }
    // Reading stays possible: the variables, the candidates and the workflow preview.
    expect(screen.getByTestId('pset-variables')).toBeInTheDocument();
    expect(screen.getByTestId('pset-candidate-payments-api')).toBeInTheDocument();
    expect(screen.getByTestId('pset-show-workflow')).toBeEnabled();
    expect(writes()).toEqual([]);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});
