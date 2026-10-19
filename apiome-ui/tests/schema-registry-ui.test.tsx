/**
 * The schema registry UI — CDG-4.5 (#5977).
 *
 * * **Subjects tab**: loads only when active; lists the item's subjects (not other items') with
 *   their versions, ids, level and mode; reports the count; changing the level saves it; Detach asks
 *   first and then deletes the subject; Attach checks the name and posts the item; a failed read
 *   offers a retry; axe passes.
 * * **Schema registry page**: reads the defaults and subjects, saves the level and mode together,
 *   shows the tenant's Confluent URL, the API-key scope hint and the three serializer snippets;
 *   subjects link to their item's Subjects tab; axe passes.
 * * **Registry chip**: drawn only for an item that backs a subject, and opens its Subjects tab.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures (`catalog-item-subjects`,
 * `schema-registry`).
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

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'user-1', name: 'Ada', email: 'ada@example.com', current_tenant_id: 'tenant-1' } },
  }),
}));

import { CatalogSubjectsPanel } from '../src/app/components/ade/schemaRegistry/CatalogSubjectsPanel';
import SchemaRegistryClient from '../src/app/ade/dashboard/schema-registry/SchemaRegistryClient';
import { RegistryBadge } from '../src/app/components/ade/catalog/CatalogBadges';
import type { SchemaSubject, SubjectVersion } from '../lib/schema-registry';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const ITEM = '11111111-1111-4111-8111-111111111111';
const OTHER = '22222222-2222-4222-8222-222222222222';

function subject(name: string, over: Partial<SchemaSubject> = {}): SchemaSubject {
  return {
    name,
    strategy: 'topic',
    compatibilityLevel: null,
    effectiveCompatibilityLevel: 'BACKWARD',
    mode: 'READWRITE',
    projectId: ITEM,
    versionCount: 2,
    latestVersion: 2,
    createdAt: '2026-06-01T10:00:00Z',
    updatedAt: '2026-06-01T10:00:00Z',
    ...over,
  };
}

function version(subjectName: string, n: number, id: number): SubjectVersion {
  return {
    subject: subjectName,
    version: n,
    id,
    schemaType: 'AVRO',
    fingerprint: `sha256:${n}`,
    projectId: ITEM,
    versionRecordId: `33333333-3333-4333-8333-00000000000${n}`,
    createdAt: `2026-06-0${n}T10:00:00Z`,
  };
}

const SUBJECTS: SchemaSubject[] = [
  subject('orders-value'),
  subject('orders-key', { compatibilityLevel: 'NONE', effectiveCompatibilityLevel: 'NONE', versionCount: 1, latestVersion: 1, strategy: 'record' }),
  subject('payments-value', { projectId: OTHER, versionCount: 4, latestVersion: 4 }),
];

const VERSIONS: Record<string, SubjectVersion[]> = {
  'orders-value': [version('orders-value', 1, 1), version('orders-value', 2, 3)],
  'orders-key': [version('orders-key', 1, 2)],
};

type Call = { url: string; method: string; body: unknown };
let calls: Call[] = [];
let failSubjects = false;

const res = (body: unknown, status = 200) =>
  ({ ok: status >= 200 && status < 300, status, json: async () => body }) as unknown as Response;

beforeEach(() => {
  calls = [];
  failSubjects = false;
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url === '/api/schema-registry/config' && method === 'GET') {
      return res({
        compatibilityLevel: 'BACKWARD',
        mode: 'READWRITE',
        tenantSlug: 'acme',
        registryUrl: 'https://api.example.com/registry/schema/acme',
      });
    }
    if (url === '/api/schema-registry/config' && method === 'PUT') return res(body);
    if (url === '/api/schema-registry/subjects') {
      return failSubjects ? res({ success: false, error: 'apiome-rest not reachable' }, 503) : res({ subjects: SUBJECTS });
    }
    const versions = url.match(/^\/api\/schema-registry\/subjects\/([^/]+)\/versions$/);
    if (versions) return res({ subject: decodeURIComponent(versions[1]), versions: VERSIONS[decodeURIComponent(versions[1])] ?? [] });
    if (url.endsWith('/attach')) {
      return body?.projectId ? res({ ...version('new', 1, 9), created: true }) : res({ success: false, error: 'x' }, 422);
    }
    if (method === 'PUT') return res({ ...subject('orders-value'), ...body });
    if (method === 'DELETE') return res([1, 2]);
    return res({ success: false, error: 'unexpected' }, 500);
  }) as unknown as typeof fetch;
});

async function renderPanel(onCountChange = jest.fn()) {
  const view = render(<CatalogSubjectsPanel itemId={ITEM} itemSlug="orders" active onCountChange={onCountChange} />);
  await screen.findByTestId('catalog-subject-orders-value');
  return { ...view, onCountChange };
}

describe('the Subjects tab', () => {
  it('reads nothing until the tab is shown', () => {
    render(<CatalogSubjectsPanel itemId={ITEM} active={false} />);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("lists this item's subjects with their versions, ids, level and mode", async () => {
    const { onCountChange } = await renderPanel();
    expect(screen.queryByTestId('catalog-subject-payments-value')).not.toBeInTheDocument();
    const orders = screen.getByTestId('catalog-subject-orders-value');
    expect(within(orders).getByText('READWRITE')).toBeInTheDocument();
    expect(within(orders).getByTestId('catalog-subject-level-orders-value')).toHaveDisplayValue(
      'BACKWARD (workspace default)',
    );
    const rows = within(screen.getByTestId('catalog-subject-versions-orders-value')).getAllByRole('row');
    expect(rows).toHaveLength(3);
    expect(rows[2]).toHaveTextContent('23AVRO');
    expect(screen.getByTestId('catalog-subject-level-orders-key')).toHaveDisplayValue('NONE');
    expect(onCountChange).toHaveBeenCalledWith(2);
  });

  it('saves a new compatibility level and re-reads', async () => {
    await renderPanel();
    fireEvent.change(screen.getByTestId('catalog-subject-level-orders-value'), { target: { value: 'NONE' } });
    await waitFor(() =>
      expect(calls).toContainEqual({
        url: '/api/schema-registry/subjects/orders-value',
        method: 'PUT',
        body: { compatibilityLevel: 'NONE' },
      }),
    );
    await waitFor(() => expect(calls.filter((c) => c.url === '/api/schema-registry/subjects')).toHaveLength(2));
  });

  it('asks before detaching, then deletes the subject', async () => {
    await renderPanel();
    fireEvent.click(screen.getByTestId('catalog-subject-detach-orders-value'));
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
    expect(screen.getByRole('group', { name: 'Detach orders-value' })).toHaveTextContent('schema ids keep resolving');
    fireEvent.click(screen.getByTestId('catalog-subject-detach-confirm-orders-value'));
    await waitFor(() =>
      expect(calls).toContainEqual({ url: '/api/schema-registry/subjects/orders-value', method: 'DELETE', body: undefined }),
    );
  });

  it('cancelling the detach changes nothing', async () => {
    await renderPanel();
    fireEvent.click(screen.getByTestId('catalog-subject-detach-orders-value'));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByTestId('catalog-subject-detach-orders-value')).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
  });

  it('attaches the item to a subject with the chosen strategy', async () => {
    await renderPanel();
    const form = screen.getByTestId('catalog-subject-attach');
    expect(within(form).getByTestId('catalog-subject-attach-name')).toHaveValue('orders-value');
    fireEvent.change(within(form).getByTestId('catalog-subject-attach-name'), { target: { value: 'orders-v2-value' } });
    fireEvent.change(within(form).getByTestId('catalog-subject-attach-strategy'), { target: { value: 'record' } });
    fireEvent.click(within(form).getByTestId('catalog-subject-attach-submit'));
    await waitFor(() =>
      expect(calls).toContainEqual({
        url: '/api/schema-registry/subjects/orders-v2-value/attach',
        method: 'POST',
        body: { projectId: ITEM, strategy: 'record' },
      }),
    );
  });

  it('refuses an empty subject name without calling the API', async () => {
    await renderPanel();
    const name = screen.getByTestId('catalog-subject-attach-name');
    fireEvent.change(name, { target: { value: ' ' } });
    fireEvent.click(screen.getByTestId('catalog-subject-attach-submit'));
    expect(await screen.findByText(/Enter a subject name/)).toBeInTheDocument();
    expect(name).toHaveAttribute('aria-invalid', 'true');
    expect(calls.some((c) => c.url.endsWith('/attach'))).toBe(false);
  });

  it('says so when the item backs no subject', async () => {
    render(<CatalogSubjectsPanel itemId="44444444-4444-4444-8444-444444444444" active />);
    expect(await screen.findByText('No subjects yet')).toBeInTheDocument();
    expect(screen.getByTestId('catalog-subject-attach')).toBeInTheDocument();
  });

  it('offers a retry when the registry cannot be read', async () => {
    failSubjects = true;
    render(<CatalogSubjectsPanel itemId={ITEM} active />);
    expect(await screen.findByText('apiome-rest not reachable')).toBeInTheDocument();
    failSubjects = false;
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('catalog-subject-orders-value')).toBeInTheDocument();
  });

  it('passes axe and dumps the docs fixture', async () => {
    const { container } = await renderPanel();
    expect(await axe(container)).toHaveNoViolations();
    writeA11yFixture('catalog-item-subjects', liveMarkup(container.firstElementChild!));
  });
});

describe('the Schema registry page', () => {
  async function renderPage() {
    const view = render(<SchemaRegistryClient />);
    await screen.findByTestId('schema-registry-page');
    return view;
  }

  it('shows the defaults, the Confluent URL, the key hint and the subjects', async () => {
    await renderPage();
    expect(screen.getByTestId('registry-default-level')).toHaveValue('BACKWARD');
    expect(screen.getByTestId('registry-mode')).toHaveValue('READWRITE');
    expect(screen.getByTestId('registry-url')).toHaveTextContent('https://api.example.com/registry/schema/acme');
    expect(screen.getByTestId('registry-scope-hint')).toHaveTextContent('Schema registry: read + write');
    expect(screen.getByTestId('registry-scope-hint')).toHaveTextContent('registry:write');
    const row = screen.getByTestId('registry-subject-row-payments-value');
    expect(within(row).getByRole('link', { name: 'payments-value' })).toHaveAttribute(
      'href',
      `/ade/dashboard/catalog/${OTHER}?tab=subjects`,
    );
    expect(screen.getByTestId('registry-subject-row-orders-value')).toHaveTextContent('BACKWARD (workspace default)');
  });

  it('saves the level and the mode together', async () => {
    await renderPage();
    const save = screen.getByTestId('registry-settings-save');
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByTestId('registry-default-level'), { target: { value: 'NONE' } });
    fireEvent.change(screen.getByTestId('registry-mode'), { target: { value: 'READONLY' } });
    fireEvent.click(save);
    expect(await screen.findByRole('status')).toHaveTextContent('Saved.');
    expect(calls).toContainEqual({
      url: '/api/schema-registry/config',
      method: 'PUT',
      body: { compatibilityLevel: 'NONE', mode: 'READONLY' },
    });
    expect(screen.getByTestId('registry-settings-save')).toBeDisabled();
  });

  it('switches between the Python, Java and Spring snippets', async () => {
    await renderPage();
    expect(screen.getByTestId('registry-snippet')).toHaveTextContent('SchemaRegistryClient');
    fireEvent.click(screen.getByTestId('registry-snippet-tab-java'));
    expect(screen.getByTestId('registry-snippet')).toHaveTextContent(
      'schema.registry.url=https://api.example.com/registry/schema/acme',
    );
    fireEvent.click(screen.getByTestId('registry-snippet-tab-spring'));
    expect(screen.getByTestId('registry-snippet')).toHaveTextContent('spring:');
    expect(screen.getByTestId('registry-snippet')).toHaveTextContent('<api-key>');
  });

  it('offers a retry when the registry cannot be read', async () => {
    failSubjects = true;
    render(<SchemaRegistryClient />);
    expect(await screen.findByText('The schema registry could not be read')).toBeInTheDocument();
  });

  it('passes axe and dumps the docs fixture', async () => {
    const { container } = await renderPage();
    expect(await axe(container)).toHaveNoViolations();
    writeA11yFixture('schema-registry', liveMarkup((document.querySelector('.page') ?? container.firstElementChild)!));
  });
});

describe('the Registry chip', () => {
  it('is drawn only for an item that backs a subject', () => {
    const { container } = render(<RegistryBadge itemId={ITEM} subjects={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('names the subjects and opens the Subjects tab', () => {
    render(<RegistryBadge itemId={ITEM} subjects={['orders-key', 'orders-value']} />);
    const chip = screen.getByTestId('catalog-registry-badge');
    expect(chip).toHaveTextContent('Registry');
    expect(chip).toHaveAttribute('href', `/ade/dashboard/catalog/${ITEM}?tab=subjects`);
    expect(chip).toHaveAttribute('title', 'Schema registry subjects: orders-key, orders-value');
  });
});
