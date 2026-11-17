/**
 * Product and plan lifecycle — APX-1.4 (#6101).
 *
 * * **Rules**: the states each record may be saved in, the retirement date between a date input and
 *   the wire, when retiring is allowed, the replacement-plan candidates (published, same auth), the
 *   deprecation fields travelling only with `deprecated`, and the proxy forwarding **migrate** with
 *   only its own fields.
 * * **Plan editor**: a deprecated plan shows its notice, the **Deprecation** fields and **Migrate to
 *   plan…**; saving sends the deprecation; **Retired** waits for the date; the migrate dialog
 *   previews, migrates (no key changes), and reloads the plans when closed.
 * * **Product editor**: a deprecated product's retirement date and message are saved.
 * * **Sunset timeline**: deprecated and retired products and plans are listed with their date,
 *   status, replacement and message; axe passes.
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
  SunsetProductsTable,
  productLifecycleLabel,
  productRetireDay,
  productRowId,
  productRowName,
  type SunsetProductEntry,
} from '../src/app/components/ade/sunset';
import { canRetireNow, dateInputValue, retireAtFromInput, retireText, selectableStates } from '../lib/api-lifecycle';
import { draftFromPlan, draftToInput, successorChoices } from '../lib/api-plans';
import { productProxyBody, productProxyPath, type ApiProduct } from '../lib/api-products';
import { DEPRECATED_PLANS, GATEWAYS, plan } from './helpers/api-plans-fixtures';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };

const PRODUCT: ApiProduct = {
  id: 'p-1',
  slug: 'payments',
  name: 'Payments',
  summary: 'Card payments and refunds.',
  owner_team: null,
  visibility: 'workspace',
  state: 'published',
  member_count: 0,
  created_by: null,
  created_at: null,
  updated_at: null,
  members: [],
  portal_ready: true,
};

/** A fetch answer (jsdom has no `Response`). */
function reply(value: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => value };
}

let calls: Array<{ url: string; method: string; body: unknown }> = [];
let product: ApiProduct;

beforeEach(() => {
  calls = [];
  product = PRODUCT;
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method ?? 'GET');
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url === '/api/products/payments' && method === 'GET') return reply(product);
    if (url === '/api/products/payments' && method === 'PATCH') return reply({ ...product, ...body });
    if (url === '/api/gateway-configs') return reply({ gatewayConfigs: GATEWAYS });
    if (url === '/api/products/payments/plans' && method === 'GET') {
      return reply({ plans: DEPRECATED_PLANS, count: DEPRECATED_PLANS.length });
    }
    if (url === '/api/products/payments/plans/standard' && method === 'PATCH') {
      return reply({ ...DEPRECATED_PLANS[1], deprecation_message: body.deprecation_message, updated_at: 'later' });
    }
    if (url === '/api/products/payments/plans/standard/migrate' && method === 'POST') {
      return reply({
        from_plan: { slug: 'standard', name: 'Standard', state: 'deprecated' },
        to_plan: { slug: body.to, name: 'Premium', state: 'published' },
        dry_run: body.dry_run,
        from_group: 'plan:payments-standard',
        to_group: `plan:payments-${body.to}`,
        subscriptions: 0,
        credentials_changed: false,
        message: body.dry_run
          ? 'Would move 0 subscriptions from Standard to Premium; keys stay the same.'
          : 'No application is subscribed to Standard, so nothing moved. Premium is recorded as its replacement.',
      });
    }
    return reply({ error: 'unexpected' }, 404);
  }) as unknown as typeof fetch;
});

describe('lifecycle rules', () => {
  it('offers only the lifecycle steps REST accepts', () => {
    expect(selectableStates(null)).toEqual(['draft', 'published']);
    expect(selectableStates('draft')).toEqual(['draft', 'published']);
    expect(selectableStates('published')).toEqual(['draft', 'published', 'deprecated']);
    expect(selectableStates('deprecated')).toEqual(['published', 'deprecated', 'retired']);
    expect(selectableStates('retired')).toEqual(['retired']);
  });

  it('converts the retirement date and says when retiring is allowed', () => {
    expect(dateInputValue('2027-03-31T00:00:00+00:00')).toBe('2027-03-31');
    expect(dateInputValue(null)).toBe('');
    expect(retireAtFromInput(' 2027-03-31 ')).toBe('2027-03-31T00:00:00Z');
    expect(retireAtFromInput('')).toBeNull();
    expect(retireAtFromInput('31/03/2027')).toBeNull();
    const now = new Date('2026-11-16T12:00:00Z');
    expect(canRetireNow(null, now)).toBe(true);
    expect(canRetireNow('2026-11-01T00:00:00Z', now)).toBe(true);
    expect(canRetireNow('2027-03-31T00:00:00Z', now)).toBe(false);
    expect(retireText('2027-03-31T00:00:00Z')).toBe('Retires on 2027-03-31');
    expect(retireText(null)).toBe('No retirement date');
  });

  it('offers only published plans with the same auth as replacements', () => {
    const [sandbox, standard, premium] = DEPRECATED_PLANS;
    const mtls = plan({ id: 'pl-mtls', slug: 'partner', auth_strategy: 'mtls' });
    const draft = plan({ id: 'pl-beta', slug: 'beta', state: 'draft' });
    expect(successorChoices([sandbox, standard, premium, mtls, draft], standard).map((p) => p.slug)).toEqual([
      'sandbox',
      'premium',
    ]);
  });

  it('sends the deprecation fields only with a deprecated plan', () => {
    const deprecated = draftToInput(draftFromPlan(DEPRECATED_PLANS[1]), false);
    expect(deprecated).toMatchObject({
      state: 'deprecated',
      retire_at: '2027-03-31T00:00:00Z',
      successor: 'premium',
      deprecation_message: expect.stringMatching(/Move to Premium/),
    });
    const published = draftToInput(draftFromPlan(plan()), false);
    expect(published).not.toHaveProperty('retire_at');
    expect(published).not.toHaveProperty('successor');
    // A create never carries them.
    expect(draftToInput({ ...draftFromPlan(DEPRECATED_PLANS[1]), slug: 'x' }, true)).not.toHaveProperty('successor');
  });

  it('forwards migrate with only its own fields', () => {
    expect(productProxyPath(['payments', 'plans', 'standard', 'migrate'], 'POST')).toBe(
      'products/payments/plans/standard/migrate',
    );
    expect(productProxyPath(['payments', 'plans', 'standard', 'migrate'], 'GET')).toBeNull();
    expect(productProxyPath(['payments', 'plans', 'standard', 'retire'], 'POST')).toBeNull();
    expect(productProxyPath(['payments', 'members', 'x', 'migrate'], 'POST')).toBeNull();
    expect(productProxyPath(['payments', 'plans', 'Bad Slug', 'migrate'], 'POST')).toBeNull();
    expect(
      productProxyBody('products/payments/plans/standard/migrate', 'POST', { to: 'premium', dry_run: true, name: 'x' }),
    ).toEqual({ to: 'premium', dry_run: true });
    expect(
      productProxyBody('products/payments/plans/standard', 'PATCH', { successor: 'premium', retire_at: null, id: 'x' }),
    ).toEqual({ successor: 'premium', retire_at: null });
    expect(productProxyBody('products/payments', 'PATCH', { retire_at: 'x', deprecation_message: 'm', id: 'y' })).toEqual({
      retire_at: 'x',
      deprecation_message: 'm',
    });
  });
});

describe('the plan editor', () => {
  async function openStandard() {
    const view = render(<ProductEditorClient slug="payments" />);
    await screen.findByTestId('product-plans-table');
    fireEvent.click(screen.getByRole('button', { name: 'Edit Standard' }));
    const editor = await screen.findByTestId('plan-editor');
    return { view, editor };
  }

  it('lists a deprecated plan with its retirement date and replacement', async () => {
    render(<ProductEditorClient slug="payments" />);
    await screen.findByTestId('product-plans-table');
    expect(screen.getByTestId('plan-retires-standard')).toHaveTextContent('Retires on 2027-03-31 · moves to Premium');
  });

  it('shows the deprecation and saves it', async () => {
    const { editor } = await openStandard();
    expect(within(editor).getAllByTestId('plan-notice')[1]).toHaveTextContent(/new subscriptions are blocked/);
    expect(within(editor).getByLabelText(/^Retire on/)).toHaveValue('2027-03-31');
    expect(within(editor).getByText(/Retired is available from 2027-03-31/)).toBeInTheDocument();

    fireEvent.change(within(editor).getByLabelText(/^Message to subscribers/), { target: { value: 'Move by March.' } });
    fireEvent.click(within(editor).getByRole('button', { name: 'Save plan' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(calls.find((c) => c.method === 'PATCH')!.body).toMatchObject({
      state: 'deprecated',
      retire_at: '2027-03-31T00:00:00Z',
      successor: 'premium',
      deprecation_message: 'Move by March.',
    });
  });

  it('previews and migrates without changing keys, then reloads the plans', async () => {
    const { editor } = await openStandard();
    fireEvent.click(within(editor).getByTestId('plan-migrate'));
    const dialog = await screen.findByTestId('plan-migrate-dialog');

    fireEvent.click(within(dialog).getByTestId('plan-migrate-preview'));
    expect(await within(dialog).findByTestId('plan-migrate-result')).toHaveTextContent(/Would move 0 subscriptions/);
    expect(within(dialog).getByTestId('plan-migrate-result')).toHaveTextContent(
      'plan:payments-standard → plan:payments-premium',
    );

    fireEvent.click(within(dialog).getByTestId('plan-migrate-confirm'));
    expect(await within(dialog).findByText(/Premium is recorded as its replacement/)).toBeInTheDocument();
    const migrations = calls.filter((c) => c.url.endsWith('/migrate'));
    expect(migrations.map((c) => c.body)).toEqual([
      { to: 'premium', dry_run: true },
      { to: 'premium', dry_run: false },
    ]);

    const reads = calls.filter((c) => c.url === '/api/products/payments/plans' && c.method === 'GET').length;
    fireEvent.click(within(dialog).getByTestId('plan-migrate-done'));
    await waitFor(() =>
      expect(calls.filter((c) => c.url === '/api/products/payments/plans' && c.method === 'GET').length).toBe(reads + 1),
    );
  });

  it('passes axe with the deprecation open', async () => {
    const { view } = await openStandard();
    expect(await axe(view.container, AXE_OPTIONS)).toHaveNoViolations();
  });
});

describe('the product editor', () => {
  it('saves a deprecated product’s retirement date and message', async () => {
    product = {
      ...PRODUCT,
      state: 'deprecated',
      retire_at: '2027-06-30T00:00:00+00:00',
      deprecation_message: null,
    };
    render(<ProductEditorClient slug="payments" />);
    const section = await screen.findByTestId('product-deprecation');
    expect(within(section).getByLabelText(/^Retire on/)).toHaveValue('2027-06-30');
    expect(screen.getByText(/Retired is available from 2027-06-30/)).toBeInTheDocument();

    fireEvent.change(within(section).getByLabelText(/^Retire on/), { target: { value: '2027-07-31' } });
    fireEvent.change(within(section).getByLabelText(/^Deprecation message/), { target: { value: 'Use v2.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save product' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH' && c.url === '/api/products/payments')).toBe(true));
    expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({
      retire_at: '2027-07-31T00:00:00Z',
      deprecation_message: 'Use v2.',
    });
  });

  it('shows no deprecation fields for a published product', async () => {
    render(<ProductEditorClient slug="payments" />);
    await screen.findByTestId('product-details');
    expect(screen.queryByTestId('product-deprecation')).toBeNull();
  });
});

describe('the sunset timeline’s products and plans', () => {
  const ENTRIES: SunsetProductEntry[] = [
    {
      kind: 'plan',
      productSlug: 'payments',
      productName: 'Payments',
      planSlug: 'standard',
      planName: 'Standard',
      state: 'deprecated',
      retireAt: '2026-12-01T00:00:00+00:00',
      timelineStatus: 'imminent',
      lifecyclePhase: 'deprecated',
      deprecationMessage: 'Move to Premium.',
      successorPlanSlug: 'premium',
      successorPlanName: 'Premium',
    },
    {
      kind: 'product',
      productSlug: 'ledger',
      productName: 'Ledger',
      state: 'retired',
      retireAt: '2026-10-01T00:00:00+00:00',
      retiredAt: '2026-10-02T09:00:00+00:00',
      timelineStatus: 'past',
      lifecyclePhase: 'retired',
    },
  ];

  it('names, dates and labels each row', () => {
    expect(ENTRIES.map(productRowId)).toEqual(['payments/standard', 'ledger']);
    expect(ENTRIES.map(productRowName)).toEqual(['Payments · Standard', 'Ledger']);
    expect(ENTRIES.map(productRetireDay)).toEqual(['2026-12-01', '2026-10-02']);
    expect(productLifecycleLabel('sunset_reached')).toMatch(/ready to retire/);
    expect(productLifecycleLabel('unknown')).toBe('Deprecated (no new subscriptions)');
  });

  it('renders a row per product or plan, linking to the product', async () => {
    const { container } = render(<SunsetProductsTable entries={ENTRIES} />);
    const table = screen.getByTestId('sunset-products-table');
    expect(within(table).getByRole('link', { name: 'Payments · Standard' })).toHaveAttribute(
      'href',
      '/ade/dashboard/products/payments',
    );
    expect(screen.getByTestId('sunset-product-status-payments/standard')).toHaveTextContent('imminent');
    expect(screen.getByTestId('sunset-product-status-ledger')).toHaveTextContent('past');
    expect(within(table).getByText('Premium')).toBeInTheDocument();
    expect(within(table).getByText('Move to Premium.')).toBeInTheDocument();
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('renders nothing without entries', () => {
    const { container } = render(<SunsetProductsTable entries={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
