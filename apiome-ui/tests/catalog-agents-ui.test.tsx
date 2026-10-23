/**
 * Agent and model entities — CDG-5.2 (#5980).
 *
 * * **Rules**: the proxy forwards only its paths, methods and fields; the deprecation label.
 * * **Agent page**: model with its deprecation called out, owner, keys by name, prefix and status
 *   (never a secret), what it consumes per project and the usage link; Unlink, Link key, Retire and
 *   Delete call the API; the Graph tab draws the consumer's dependencies; axe passes.
 * * **Model page**: provider, hosting, data handling, deprecation and the agents running it; the
 *   deprecation date is saved and cleared; axe passes.
 * * **Dialogs**: Register agent and Add model check their fields and send what was entered.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `agent-entity` and `model-entity`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockPush = jest.fn();

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/ade/dashboard/catalog/agents/support-bot',
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: { user_id: 'u-1', current_tenant_id: 't-1' } } }),
}));

import AgentDetailClient from '../src/app/ade/dashboard/catalog/agents/[slug]/AgentDetailClient';
import ModelDetailClient from '../src/app/ade/dashboard/catalog/models/[slug]/ModelDetailClient';
import { AddModelDialog, RegisterAgentDialog } from '../src/app/components/ade/catalogAgents/CatalogAgentDialogs';
import {
  catalogAgentProxyBody,
  catalogAgentProxyPath,
  deprecationLabel,
  type CatalogAgent,
  type CatalogModel,
} from '../lib/catalog-agents';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const KEY = '88888888-8888-4888-8888-888888888888';
const KEY_2 = '99999999-9999-4999-8999-999999999999';
const OWNER = { team: { id: 't-1', slug: 'payments', name: 'Payments' }, status: 'confirmed' as const, source: 'manual' };

const AGENT: CatalogAgent = {
  id: '55555555-5555-4555-8555-555555555555',
  slug: 'support-bot',
  name: 'Support bot',
  description: 'Answers order questions in the help centre.',
  runtime: 'LangGraph on Cloud Run',
  status: 'active',
  model: {
    id: 'm-1', slug: 'claude-3', name: 'Claude 3 Sonnet', provider: 'Anthropic', modelVersion: '2024-02-29',
    deprecatedAt: '2026-01-15T00:00:00Z', deprecated: true,
  },
  owner: OWNER,
  keys: [
    {
      id: KEY, name: 'support-bot-prod', keyPrefix: 'ak_1a2b3c4d5...', status: 'active', toolsetId: 'ts-1',
      projectId: 'p-1', projectName: 'Orders API', versionLabel: '2.1.0', enabledTools: 4, revokedAt: null, lastUsedAt: null,
    },
  ],
  consumers: [{ consumerId: 'c-1', projectId: 'p-1', projectName: 'Orders API', operationCount: 4 }],
  usageHref: '/ade/dashboard/mcp/agents?tab=usage',
  createdAt: '2026-06-01T10:00:00Z',
  updatedAt: '2026-06-01T10:00:00Z',
};

const MODEL: CatalogModel = {
  id: 'm-1', slug: 'claude-3', name: 'Claude 3 Sonnet', provider: 'Anthropic', modelName: 'claude-3-sonnet',
  modelVersion: '2024-02-29', hosting: 'api',
  dataHandling: 'Zero data retention under the enterprise agreement; processed in the US.',
  deprecatedAt: '2026-01-15T00:00:00Z', deprecated: true, owner: null,
  agents: [{ id: AGENT.id, slug: 'support-bot', name: 'Support bot', status: 'active' }],
  createdAt: null, updatedAt: null,
};

type Call = { url: string; method: string; body: unknown };
let calls: Call[] = [];

const res = (body: unknown, status = 200) =>
  ({ ok: status >= 200 && status < 300, status, json: async () => body }) as unknown as Response;

// Agents and models is held back in RC6 (lib/feature-release.ts); these suites test it, so re-open it.
const PREVIEW_FEATURES = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
beforeAll(() => {
  process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'catalog-entities,teams,dependency-graph';
});
afterAll(() => {
  if (PREVIEW_FEATURES === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = PREVIEW_FEATURES;
});

beforeEach(() => {
  calls = [];
  mockPush.mockReset();
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url === '/api/agent-access/keys') {
      return res({ success: true, data: { keys: [
        { id: KEY, name: 'support-bot-prod', keyPrefix: 'ak_1a2b3c4d5...', status: 'active' },
        { id: KEY_2, name: 'support-bot-staging', keyPrefix: 'ak_9z8y7x6w5...', status: 'active' },
        { id: 'revoked-1', name: 'old', keyPrefix: 'ak_0...', status: 'revoked' },
      ] } });
    }
    if (url === '/api/teams') return res({ teams: [{ id: 't-1', slug: 'payments', name: 'Payments' }] });
    if (url.startsWith('/api/graph/edges')) return res({ edges: [], total: 0, truncated: false, limit: 500, offset: 0 });
    if (url === '/api/catalog-models' && method === 'GET') return res({ models: [MODEL] });
    if (url.startsWith('/api/catalog-models')) {
      if (method === 'DELETE') return res(null, 204);
      if (method === 'PATCH') return res({ ...MODEL, deprecatedAt: body.deprecatedAt, deprecated: false });
      if (method === 'POST') return res({ ...MODEL, ...body }, 201);
      return res(MODEL);
    }
    if (url.startsWith('/api/catalog-agents')) {
      if (method === 'DELETE' && !url.includes('/keys/')) return res(null, 204);
      if (method === 'PATCH') return res({ ...AGENT, ...body });
      if (method === 'POST') return res({ ...AGENT, ...body }, 201);
      return res(AGENT);
    }
    return res({ success: true });
  }) as unknown as typeof fetch;
});

describe('the rules', () => {
  it('forwards only the agent and model paths and methods', () => {
    expect(catalogAgentProxyPath('catalog-agents', [], 'GET')).toBe('catalog-agents');
    expect(catalogAgentProxyPath('catalog-agents', [], 'DELETE')).toBeNull();
    expect(catalogAgentProxyPath('catalog-agents', ['support-bot'], 'PATCH')).toBe('catalog-agents/support-bot');
    expect(catalogAgentProxyPath('catalog-agents', ['support-bot', 'keys', KEY], 'PUT')).toBe(
      `catalog-agents/support-bot/keys/${KEY}`,
    );
    expect(catalogAgentProxyPath('catalog-agents', ['support-bot', 'keys', 'nope'], 'PUT')).toBeNull();
    expect(catalogAgentProxyPath('catalog-models', ['claude', 'keys', KEY], 'PUT')).toBeNull();
    expect(catalogAgentProxyPath('catalog-agents', ['../x'], 'GET')).toBeNull();
    expect(catalogAgentProxyPath('catalog-models', [MODEL.agents[0].id], 'GET')).toBe(`catalog-models/${MODEL.agents[0].id}`);
  });

  it('forwards only each collection’s fields', () => {
    expect(catalogAgentProxyBody('catalog-agents', { name: 'x', keyIds: [KEY, 'bad'], tenant_id: 'other', secret: 's' })).toEqual({
      name: 'x', keyIds: [KEY],
    });
    expect(catalogAgentProxyBody('catalog-models', { provider: 'p', deprecatedAt: null, keyIds: [KEY] })).toEqual({
      provider: 'p', deprecatedAt: null,
    });
  });

  it('labels a deprecation in the past or the future', () => {
    expect(deprecationLabel({ deprecatedAt: null, deprecated: false })).toBeNull();
    expect(deprecationLabel({ deprecatedAt: '2026-01-15T00:00:00Z', deprecated: true })).toMatch(/^Deprecated since /);
    expect(deprecationLabel({ deprecatedAt: '2030-01-15T00:00:00Z', deprecated: false })).toMatch(/^Deprecated from /);
  });
});

describe('the agent page', () => {
  async function renderAgent() {
    const view = render(<AgentDetailClient slug="support-bot" />);
    await screen.findByTestId('agent-detail');
    return view;
  }

  it('shows the model with its deprecation, the owner, the keys and what it consumes', async () => {
    await renderAgent();
    expect(screen.getByTestId('agent-model')).toHaveTextContent('Claude 3 Sonnet');
    expect(screen.getByTestId('agent-model-deprecation')).toHaveTextContent(/Deprecated since .*Claude 3 Sonnet/);
    expect(screen.getByTestId('entity-owner-cell')).toHaveTextContent('Payments');
    const key = screen.getByTestId(`agent-key-${KEY}`);
    expect(key).toHaveTextContent('support-bot-prod');
    expect(key).toHaveTextContent('ak_1a2b3c4d5...');
    expect(key).toHaveTextContent('Orders API');
    expect(screen.getByTestId('agent-consumers')).toHaveTextContent('Orders API · 4 operations');
    expect(screen.getByTestId('agent-usage-link')).toHaveAttribute('href', '/ade/dashboard/mcp/agents?tab=usage');
  });

  it('never shows a secret', async () => {
    const { container } = await renderAgent();
    expect(container.textContent).not.toMatch(/ak_[0-9a-f]{64}/);
    expect(container.innerHTML).not.toMatch(/key_?hash|secret/i);
  });

  it('unlinks, links, retires and deletes through the API', async () => {
    await renderAgent();
    fireEvent.click(screen.getByTestId(`agent-unlink-${KEY}`));
    await waitFor(() =>
      expect(calls).toContainEqual({ url: `/api/catalog-agents/support-bot/keys/${KEY}`, method: 'DELETE', body: undefined }),
    );

    fireEvent.click(screen.getByTestId('agent-link-key'));
    const select = await screen.findByTestId('agent-link-select');
    expect(within(select).queryByText(/support-bot-prod/)).not.toBeInTheDocument(); // already linked
    expect(within(select).queryByText(/old/)).not.toBeInTheDocument(); // revoked
    fireEvent.change(select, { target: { value: KEY_2 } });
    fireEvent.click(screen.getByTestId('agent-link-submit'));
    await waitFor(() =>
      expect(calls).toContainEqual({ url: `/api/catalog-agents/support-bot/keys/${KEY_2}`, method: 'PUT', body: undefined }),
    );

    await waitFor(() => expect(screen.getByTestId('agent-retire')).toBeEnabled());
    fireEvent.click(screen.getByTestId('agent-retire'));
    await waitFor(() =>
      expect(calls).toContainEqual({ url: '/api/catalog-agents/support-bot', method: 'PATCH', body: { status: 'retired' } }),
    );

    await waitFor(() => expect(screen.getByTestId('agent-delete')).toBeEnabled());
    fireEvent.click(screen.getByTestId('agent-delete'));
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/ade/dashboard/catalog?kind=agent'));
  });

  it('assigns an owner team', async () => {
    await renderAgent();
    const select = screen.getByTestId('entity-owner-select');
    await waitFor(() => expect(within(select).getByText('Payments')).toBeInTheDocument());
    fireEvent.change(select, { target: { value: 'payments' } });
    fireEvent.click(screen.getByTestId('entity-owner-assign'));
    await waitFor(() =>
      expect(calls).toContainEqual({
        url: '/api/owners/assign', method: 'POST', body: { team: 'payments', entities: [{ kind: 'agent', id: AGENT.id }] },
      }),
    );
  });

  it('draws the consumer’s graph on the Graph tab', async () => {
    await renderAgent();
    fireEvent.mouseDown(screen.getByTestId('agent-tab-graph'));
    fireEvent.click(screen.getByTestId('agent-tab-graph'));
    await waitFor(() => expect(calls.some((call) => call.url.startsWith('/api/graph/edges/consumer/c-1'))).toBe(true));
  });

  it('passes axe and dumps the docs fixture', async () => {
    const { container } = await renderAgent();
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('agent-entity', liveMarkup((document.querySelector('.page') ?? container.firstElementChild)!));
  });
});

describe('the model page', () => {
  async function renderModel() {
    const view = render(<ModelDetailClient slug="claude-3" />);
    await screen.findByTestId('model-detail');
    return view;
  }

  it('shows the model, its deprecation and the agents running it', async () => {
    await renderModel();
    expect(screen.getByTestId('model-detail')).toHaveTextContent('Anthropic');
    expect(screen.getByTestId('model-detail')).toHaveTextContent("Provider's API");
    expect(screen.getByTestId('model-detail')).toHaveTextContent('Zero data retention');
    expect(screen.getByTestId('model-deprecation')).toHaveTextContent(/Deprecated since/);
    expect(within(screen.getByTestId('model-agents')).getByRole('link', { name: 'Support bot' })).toHaveAttribute(
      'href',
      '/ade/dashboard/catalog/agents/support-bot',
    );
  });

  it('saves and clears the deprecation date', async () => {
    await renderModel();
    const input = screen.getByTestId('model-deprecated-input');
    expect(input).toHaveValue('2026-01-15');
    fireEvent.change(input, { target: { value: '2027-03-01' } });
    fireEvent.click(screen.getByTestId('model-deprecated-save'));
    await waitFor(() =>
      expect(calls).toContainEqual({
        url: '/api/catalog-models/claude-3', method: 'PATCH', body: { deprecatedAt: '2027-03-01T00:00:00.000Z' },
      }),
    );
    fireEvent.click(await screen.findByTestId('model-deprecated-clear'));
    await waitFor(() =>
      expect(calls).toContainEqual({ url: '/api/catalog-models/claude-3', method: 'PATCH', body: { deprecatedAt: null } }),
    );
  });

  it('passes axe and dumps the docs fixture', async () => {
    const { container } = await renderModel();
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('model-entity', liveMarkup((document.querySelector('.page') ?? container.firstElementChild)!));
  });
});

describe('the dialogs', () => {
  it('registers an agent with a model and keys', async () => {
    const onCreated = jest.fn();
    render(<RegisterAgentDialog open onOpenChange={jest.fn()} onCreated={onCreated} />);
    await screen.findByTestId(`register-agent-key-${KEY}`);
    fireEvent.click(screen.getByTestId('register-agent-submit'));
    expect(await screen.findByText(/Enter a name/)).toBeInTheDocument();
    expect(calls.some((call) => call.method === 'POST')).toBe(false);

    fireEvent.change(screen.getByTestId('register-agent-name'), { target: { value: 'Support bot' } });
    fireEvent.change(screen.getByTestId('register-agent-runtime'), { target: { value: 'LangGraph' } });
    await waitFor(() => expect(screen.getByTestId('register-agent-model')).toHaveTextContent('Claude 3 Sonnet'));
    fireEvent.change(screen.getByTestId('register-agent-model'), { target: { value: 'claude-3' } });
    fireEvent.click(screen.getByTestId(`register-agent-key-${KEY}`));
    expect(screen.queryByTestId('register-agent-key-revoked-1')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('register-agent-submit'));
    await waitFor(() =>
      expect(calls).toContainEqual({
        url: '/api/catalog-agents', method: 'POST',
        body: { name: 'Support bot', runtime: 'LangGraph', model: 'claude-3', keyIds: [KEY] },
      }),
    );
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
  });

  it('adds a model', async () => {
    const onCreated = jest.fn();
    render(<AddModelDialog open onOpenChange={jest.fn()} onCreated={onCreated} />);
    fireEvent.click(screen.getByTestId('add-model-submit'));
    expect(await screen.findByText('Enter the provider and the model name.')).toBeInTheDocument();
    fireEvent.change(screen.getByTestId('add-model-provider'), { target: { value: 'Meta' } });
    fireEvent.change(screen.getByTestId('add-model-name'), { target: { value: 'llama-3-70b' } });
    fireEvent.change(screen.getByTestId('add-model-hosting'), { target: { value: 'self_hosted' } });
    fireEvent.change(screen.getByTestId('add-model-deprecated'), { target: { value: '2027-01-01' } });
    fireEvent.click(screen.getByTestId('add-model-submit'));
    await waitFor(() =>
      expect(calls).toContainEqual({
        url: '/api/catalog-models', method: 'POST',
        body: { provider: 'Meta', modelName: 'llama-3-70b', hosting: 'self_hosted', deprecatedAt: '2027-01-01T00:00:00.000Z' },
      }),
    );
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
  });
});
