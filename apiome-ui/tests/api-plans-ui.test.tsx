/**
 * API plans — APX-1.2 (#6099).
 *
 * * **Rules**: limits validate (a whole count of at least 1, every window once), the draft checks,
 *   the draft → body mapping (only the strategy's own auth settings), how limits read, the windows a
 *   new limit row may take, and the proxy forwarding the plan paths with only plan fields.
 * * **Plans section**: the plans table with **Declared only** and auth-mismatch flags; **New plan**
 *   refusing a bad limit before sending, then saving and showing the declared-only notice REST
 *   returns; **Edit** showing a plan's notices and warnings and saving its fields; **Delete** after a
 *   confirmation; axe passes.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `api-plan-editor`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/ade/dashboard/products/payments',
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: { user_id: 'u-1', current_tenant_id: 't-1' } } }),
}));

import ProductEditorClient from '../src/app/ade/dashboard/products/[slug]/ProductEditorClient';
import {
  draftFromPlan,
  draftToInput,
  emptyPlanDraft,
  freeWindows,
  limitsText,
  planDraftError,
  planLimitsError,
  type ApiPlan,
} from '../lib/api-plans';
import { productProxyBody, productProxyPath, type ApiProduct } from '../lib/api-products';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';
import { GATEWAYS, PLANS, plan } from './helpers/api-plans-fixtures';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };

const PRODUCT: ApiProduct = {
  id: 'p-1',
  slug: 'payments',
  name: 'Payments',
  summary: 'Card payments and refunds.',
  owner_team: null,
  visibility: 'workspace',
  state: 'published',
  member_count: 1,
  created_by: null,
  created_at: null,
  updated_at: null,
  members: [
    {
      id: '11111111-1111-4111-8111-111111111111',
      kind: 'project_latest',
      ref: 'r-1',
      slug: 'payments-api',
      name: 'Payments API',
      version_selector: null,
      environment: null,
      resolved_version: { id: 'v-1', label: '1.4.0', published: true },
      published: true,
      missing: false,
      created_at: null,
    },
  ],
  portal_ready: true,
};

/** A fetch answer (jsdom has no `Response`). */
function reply(value: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => value };
}

let calls: Array<{ url: string; method: string; body: unknown }> = [];
let plans: ApiPlan[];

beforeEach(() => {
  calls = [];
  plans = PLANS;
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method ?? 'GET');
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url === '/api/products/payments' && method === 'GET') return reply(PRODUCT);
    if (url === '/api/teams') return reply({ teams: [] });
    if (url === '/api/gateway-configs') return reply({ gatewayConfigs: GATEWAYS });
    if (url === '/api/products/payments/plans' && method === 'GET') return reply({ plans, count: plans.length });
    if (url === '/api/products/payments/plans' && method === 'POST') {
      return reply(
        plan({
          id: 'pl-partner',
          slug: 'partner',
          name: body.name,
          limits: body.limits,
          environments: [],
          warnings: [],
          notices: [
            {
              code: 'api-plan-declared-only',
              message: 'Declared only: the plan names no gateway environment, so Apiome records its limits but provisions nothing.',
            },
          ],
        }),
        201,
      );
    }
    if (url === '/api/products/payments/plans/standard' && method === 'PATCH') {
      return reply(plan({ ...body, environments: plans[1].environments, updated_at: '2026-11-16T11:00:00Z' }));
    }
    if (url === '/api/products/payments/plans/sandbox' && method === 'DELETE') return reply({ slug: 'sandbox' });
    return reply({ error: 'unexpected' }, 404);
  }) as unknown as typeof fetch;
});

describe('API plan rules', () => {
  it('validates limits: a whole count of at least 1, every window once', () => {
    expect(planLimitsError([{ window: 'minute', requests: '100' }, { window: 'day', requests: '50000' }])).toBeNull();
    expect(planLimitsError([{ window: 'minute', requests: '0' }])).toMatch(/at least 1/);
    expect(planLimitsError([{ window: 'minute', requests: '-3' }])).toMatch(/at least 1/);
    expect(planLimitsError([{ window: 'minute', requests: '1.5' }])).toMatch(/whole number/);
    expect(planLimitsError([{ window: 'hour', requests: '5' }, { window: 'hour', requests: '6' }])).toMatch(
      /hour window is limited twice/,
    );
  });

  it('checks the rest of the draft', () => {
    const draft = { ...emptyPlanDraft(), name: 'Standard' };
    expect(planDraftError(draft)).toBeNull();
    expect(planDraftError({ ...draft, name: ' ' })).toMatch(/needs a name/);
    expect(planDraftError({ ...draft, concurrency: '0' })).toMatch(/Concurrency/);
    expect(planDraftError({ ...draft, credential_ttl_days: '4000' })).toMatch(/1 to 3650/);
    expect(planDraftError({ ...draft, terms_url: 'example.com/terms' })).toMatch(/http/);
  });

  it('sends only the strategy’s own auth settings', () => {
    const draft = {
      ...emptyPlanDraft(),
      name: ' Partner ',
      slug: 'Partner',
      header_name: 'X-Key',
      scopes: 'a b, a',
      idp_config_id: 'okta',
      concurrency: '10',
    };
    expect(draftToInput(draft, true)).toMatchObject({
      name: 'Partner',
      slug: 'partner',
      auth_strategy: 'key_auth',
      auth_config: { header_name: 'X-Key' },
      limits: [{ window: 'minute', requests: 100 }],
      concurrency: 10,
      credential_ttl_days: null,
    });
    const oauth = draftToInput({ ...draft, auth_strategy: 'oauth2_client_credentials' }, false);
    expect(oauth.auth_config).toEqual({ idp_config_id: 'okta', scopes: ['a', 'b'] });
    expect(oauth).not.toHaveProperty('slug');
  });

  it('round-trips a stored plan through the draft', () => {
    const stored = plan();
    const input = draftToInput(draftFromPlan(stored), false);
    expect(input.limits).toEqual(stored.limits);
    expect(input.environments).toEqual(['kong-prod-cp']);
    expect(input.billing_ref).toBe('price_standard');
  });

  it('reads limits and offers the free windows', () => {
    expect(limitsText(plan())).toBe('100 / minute · 50,000 / day');
    expect(limitsText({ limits: [], concurrency: 5 })).toBe('5 in flight');
    expect(limitsText({ limits: [], concurrency: null })).toBe('No limits');
    expect(freeWindows([{ window: 'minute', requests: '1' }])).toEqual(['second', 'hour', 'day', 'month']);
  });

  it('forwards the plan paths with only plan fields', () => {
    expect(productProxyPath(['payments', 'plans'], 'GET')).toBe('products/payments/plans');
    expect(productProxyPath(['payments', 'plans'], 'POST')).toBe('products/payments/plans');
    expect(productProxyPath(['payments', 'plans', 'standard'], 'PATCH')).toBe('products/payments/plans/standard');
    expect(productProxyPath(['payments', 'plans', 'standard'], 'DELETE')).toBe('products/payments/plans/standard');
    expect(productProxyPath(['payments', 'plans', 'standard'], 'POST')).toBeNull();
    expect(productProxyPath(['payments', 'plans', 'Bad Slug'], 'GET')).toBeNull();
    expect(productProxyPath(['payments', 'plans', 'standard', 'x'], 'GET')).toBeNull();
    expect(productProxyBody('products/payments/plans', 'POST', { name: 'P', slug: 'p', tenant: 'x' })).toEqual({
      name: 'P',
      slug: 'p',
    });
    expect(productProxyBody('products/payments/plans/p', 'PATCH', { slug: 'q', limits: [] })).toEqual({ limits: [] });
  });
});

describe('Plans section', () => {
  async function renderEditor() {
    const view = render(<ProductEditorClient slug="payments" />);
    await screen.findByTestId('product-plans-table');
    return view;
  }

  it('lists the plans with their flags', async () => {
    await renderEditor();
    const sandbox = screen.getByTestId('product-plan-sandbox');
    expect(within(sandbox).getByText('Declared only')).toBeInTheDocument();
    expect(within(sandbox).getByText('Automatic')).toBeInTheDocument();
    expect(within(sandbox).getByText('None')).toBeInTheDocument();
    const standard = screen.getByTestId('product-plan-standard');
    expect(within(standard).getByText('kong-prod-cp')).toBeInTheDocument();
    expect(within(standard).getByText('1 member does not match')).toBeInTheDocument();
  });

  it('refuses a bad limit before sending, then saves a new plan as declared only', async () => {
    await renderEditor();
    fireEvent.click(screen.getByTestId('plan-new'));
    const editor = await screen.findByTestId('plan-editor');
    fireEvent.change(within(editor).getByLabelText(/^Name/), { target: { value: 'Partner' } });
    fireEvent.change(within(editor).getByLabelText(/^Requests/), { target: { value: '0' } });
    fireEvent.click(within(editor).getByRole('button', { name: 'Save plan' }));
    expect(await within(editor).findByText(/at least 1/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);

    fireEvent.change(within(editor).getByLabelText(/^Requests/), { target: { value: '1000' } });
    fireEvent.click(within(editor).getByRole('button', { name: 'Save plan' }));
    expect(await screen.findByTestId('plan-notice')).toHaveTextContent(/names no gateway environment/);
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.url).toBe('/api/products/payments/plans');
    expect(post.body).toMatchObject({ name: 'Partner', limits: [{ window: 'minute', requests: 1000 }], environments: [] });
    expect(screen.getByTestId('product-plan-partner')).toHaveTextContent('Declared only');
  });

  it('edits a plan: notices, warnings, environments and a save of its fields', async () => {
    await renderEditor();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Standard' }));
    const editor = await screen.findByTestId('plan-editor');
    expect(within(editor).getByTestId('plan-notice')).toHaveTextContent(/kong-prod-cp cannot be provisioned yet/);
    expect(within(editor).getByTestId('plan-warnings')).toHaveTextContent(/Refunds API declares no API key scheme/);
    expect(within(editor).getByLabelText(/^Key header/)).toHaveValue('X-API-Key');
    expect(within(editor).getByRole('checkbox', { name: /Kong · prod-cp/ })).toBeChecked();

    fireEvent.click(within(editor).getByRole('checkbox', { name: /Kong · staging-cp/ }));
    fireEvent.click(within(editor).getByTestId('plan-add-limit'));
    fireEvent.change(within(editor).getAllByLabelText(/^Requests/)[2], { target: { value: '5' } });
    fireEvent.click(within(editor).getByRole('button', { name: 'Save plan' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const patch = calls.find((c) => c.method === 'PATCH')!;
    expect(patch.url).toBe('/api/products/payments/plans/standard');
    expect(patch.body).toMatchObject({
      environments: ['kong-prod-cp', 'kong-staging-cp'],
      limits: [
        { window: 'minute', requests: 100 },
        { window: 'day', requests: 50000 },
        { window: 'second', requests: 5 },
      ],
    });
    expect(patch.body).not.toHaveProperty('slug');
  });

  it('deletes a plan after a confirmation', async () => {
    await renderEditor();
    fireEvent.click(screen.getByRole('button', { name: 'Delete Sandbox' }));
    fireEvent.click(await screen.findByTestId('plan-delete-confirm'));
    await waitFor(() => expect(screen.queryByTestId('product-plan-sandbox')).toBeNull());
    expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/products/payments/plans/sandbox')).toBe(true);
  });

  it('says when the plans cannot be read', async () => {
    plans = [];
    const base = global.fetch;
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === '/api/products/payments/plans' ? reply({ error: 'plans are down' }, 503) : base(input, init),
    ) as unknown as typeof fetch;
    render(<ProductEditorClient slug="payments" />);
    expect(await screen.findByText('plans are down')).toBeInTheDocument();
  });

  it('passes axe and dumps the docs fixture', async () => {
    const { container } = await renderEditor();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Standard' }));
    await screen.findByTestId('plan-editor');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('api-plan-editor', liveMarkup((document.querySelector('.page') ?? container.firstElementChild)!));
  });
});
