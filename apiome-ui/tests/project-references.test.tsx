/**
 * `$ref` hygiene in apiome-ui — COA-2.8 (#7051).
 *
 * * the model: statuses and reasons in the product's words, the policy line, the allowlist parser,
 *   digests, values and timestamps;
 * * the Versions **References** tab: lists every external reference with its places, status, last
 *   fetch and pin; **Refresh all** and a row's refresh post to the BFF and show a changed reference's
 *   diff under **Show changes** (acceptance: a changed remote ref is reported as a diff); **Pin** /
 *   **Unpin**; the cycle list; a source refusal shows an error; no references reads as
 *   self-contained;
 * * the policy card: everyone sees the policy; an administrator changes it (proxy-fetch needs a
 *   host); a non-administrator gets no **Change policy**.
 *
 * Regenerate the docs fixture (`e2e/fixtures/project-references/panel.html`) with
 *     PROJECT_REFERENCES_FIXTURE_DUMP=1 npx jest -c jest.config.ts tests/project-references.test.tsx -t fixture
 */

import fs from 'node:fs';
import path from 'node:path';
import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import { ProjectReferencesPanel } from '../src/app/components/ade/projectReferences/ProjectReferencesPanel';
import {
  STATUS_LABEL,
  formatValue,
  formatWhen,
  parseAllowlist,
  policySummary,
  reasonText,
  referencesUrl,
  shortDigest,
  type ExternalRefPolicy,
  type ProjectReferences,
} from '../src/app/components/ade/projectReferences/projectReferencesApi';

const AXE_OPTIONS = {
  rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
} as const;

const PROJECT = 'p-1';
const REVISION = '11111111-1111-4111-8111-111111111111';
const OLDER = '22222222-2222-4222-8222-222222222222';
const MONEY = 'https://schemas.example.com/common.json';
const ERRORS = 'https://errors.example.org/problem.json';
const LEGACY = 'https://legacy.internal.example.net/types.json';

const VERSIONS = [
  { id: OLDER, project_id: PROJECT, version_id: '1.0.0', published: true },
  { id: REVISION, project_id: PROJECT, version_id: '1.1.0', published: false },
];

const POLICY: ExternalRefPolicy = {
  mode: 'proxy-fetch',
  allowlist: ['*.example.com', 'errors.example.org'],
  resolution_allowed: true,
  fetches: true,
  can_edit: true,
};

function references(overrides: Partial<ProjectReferences> = {}): ProjectReferences {
  return {
    project_id: PROJECT,
    version_record_id: REVISION,
    version_label: '1.1.0',
    references: [
      {
        url: MONEY,
        host: 'schemas.example.com',
        locations: [
          { location: '#/components/schemas/Order/properties/total', ref: `${MONEY}#/Money` },
          { location: '#/components/schemas/Tax', ref: `${MONEY}#/Tax` },
        ],
        status: 'changed',
        reason: null,
        detail: null,
        digest: 'b'.repeat(64),
        fetched_at: '2026-11-20T14:05:00Z',
        checked_at: '2026-11-20T14:05:00Z',
        pinned: { digest: 'a'.repeat(64), at: '2026-11-18T09:00:00Z' },
        diff: {
          changes: [
            { pointer: '/Money/properties/amount/type', kind: 'changed', before: 'number', after: 'string' },
            { pointer: '/Money/required/1', kind: 'added', after: 'currency' },
          ],
          total: 2,
          truncated: false,
          against: 'pin',
          from_digest: 'a'.repeat(64),
          to_digest: 'b'.repeat(64),
        },
      },
      {
        url: ERRORS,
        host: 'errors.example.org',
        locations: [{ location: '#/paths/~1pets/get/responses/default', ref: `${ERRORS}#/Problem` }],
        status: 'ok',
        reason: null,
        detail: null,
        digest: 'c'.repeat(64),
        fetched_at: '2026-11-20T14:05:00Z',
        checked_at: '2026-11-20T14:05:00Z',
        pinned: null,
        diff: null,
      },
      {
        url: LEGACY,
        host: 'legacy.internal.example.net',
        locations: [{ location: '#/components/schemas/Legacy', ref: `${LEGACY}#/Legacy` }],
        status: 'blocked',
        reason: 'host-not-allowlisted',
        detail: "host 'legacy.internal.example.net' is not on this tenant's external $ref allowlist",
        digest: null,
        fetched_at: null,
        checked_at: '2026-11-20T14:05:00Z',
        pinned: null,
        diff: null,
      },
    ],
    summary: { changed: 1, ok: 1, blocked: 1 },
    cycles: [
      {
        refs: ['#/components/schemas/Category', '#/components/schemas/Node'],
        path: ['#/components/schemas/Category', '#/components/schemas/Node', '#/components/schemas/Category'],
      },
    ],
    cycle_total: 1,
    cycles_truncated: false,
    policy: POLICY,
    ...overrides,
  };
}

type Request = { method: string; url: string; body?: unknown };
let requests: Request[] = [];

function ok(data: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => ({ success: true, data }) } as Response;
}

function refuse(error: string, status: number, code: string | null = null) {
  return { ok: false, status, json: async () => ({ success: false, error, code }) } as Response;
}

function mockFetch(handler: (r: Request) => Response | undefined) {
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request: Request = {
      method: init?.method ?? 'GET',
      url: String(input),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    requests.push(request);
    return handler(request) ?? refuse(`unexpected ${request.method} ${request.url}`, 500);
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  requests = [];
});

function renderPanel() {
  return render(<ProjectReferencesPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={REVISION} />);
}

// ---------------------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------------------

describe('the references model', () => {
  test('words statuses, reasons and the policy', () => {
    expect(STATUS_LABEL['not-fetched']).toBe('Not fetched');
    expect(reasonText({ reason: 'blocked-by-tenant-policy', detail: null })).toBe(
      "The workspace's external reference policy is Block."
    );
    expect(reasonText({ reason: 'something-new', detail: 'raw detail' })).toBe('raw detail');
    expect(reasonText({ reason: null, detail: null })).toBeNull();
    expect(policySummary(POLICY)).toBe('Fetch allowlisted hosts only: *.example.com, errors.example.org.');
    expect(policySummary({ ...POLICY, mode: 'block' })).toBe('Block: nothing is fetched.');
    expect(policySummary({ ...POLICY, mode: 'inline', allowlist: [] })).toBe('Fetch: any public host.');
    expect(policySummary({ ...POLICY, allowlist: [] })).toMatch(/allowlist is empty/);
    expect(policySummary({ ...POLICY, resolution_allowed: false })).toMatch(/turned off for this deployment/);
  });

  test('parses an allowlist and formats digests, values and times', () => {
    expect(parseAllowlist(' a.com \n\n*.b.com, c.org ')).toEqual(['a.com', '*.b.com', 'c.org']);
    expect(shortDigest('sha256:' + 'f'.repeat(64))).toBe('ffffffffffff');
    expect(shortDigest(null)).toBe('—');
    expect(formatValue('x', false)).toBe('—');
    expect(formatValue({ a: 1 }, true)).toBe('{"a":1}');
    expect(formatWhen('2026-11-20T14:05:30Z')).toBe('2026-11-20 14:05 UTC');
    expect(formatWhen(null)).toBe('—');
    expect(referencesUrl('p 1', '/pin')).toBe('/api/projects/p%201/references/pin');
  });
});

// ---------------------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------------------

describe('the References tab', () => {
  test('lists references with places, status, last fetch and pin, and the cycles', async () => {
    mockFetch(() => ok(references()));
    renderPanel();
    const first = await screen.findByTestId('project-reference-0');
    expect(requests[0].url).toBe(`${referencesUrl(PROJECT)}?version=${REVISION}`);
    expect(first).toHaveTextContent(MONEY);
    expect(first).toHaveTextContent('2 places');
    expect(first).toHaveTextContent('Changed');
    expect(first).toHaveTextContent('2026-11-20 14:05 UTC');
    expect(first).toHaveTextContent('aaaaaaaaaaaa');
    expect(screen.getByTestId('project-reference-2')).toHaveTextContent('This host is not on the allowlist.');
    expect(screen.getByTestId('project-references-summary')).toHaveTextContent(
      '3 external references · 1 changed · 1 blocked'
    );
    expect(screen.getByTestId('project-references-cycles')).toHaveTextContent(
      '#/components/schemas/Category → #/components/schemas/Node → #/components/schemas/Category'
    );
    expect(screen.getByTestId('external-ref-policy-summary')).toHaveTextContent('Fetch allowlisted hosts only');
  });

  test('a changed reference shows its diff against the pin', async () => {
    const user = userEvent.setup();
    mockFetch(() => ok(references()));
    renderPanel();
    await user.click(await screen.findByTestId('project-reference-toggle-0'));
    const diff = screen.getByTestId('project-reference-diff-0');
    expect(diff).toHaveTextContent('2 changes compared with the pinned document');
    const rows = within(diff).getAllByRole('row');
    expect(rows[1]).toHaveTextContent('/Money/properties/amount/type');
    expect(rows[1]).toHaveTextContent('number');
    expect(rows[1]).toHaveTextContent('string');
    expect(rows[2]).toHaveTextContent('Added');
  });

  test('Refresh all posts the revision and reports a detected change', async () => {
    const user = userEvent.setup();
    const before = references({
      references: references().references.map((r) => ({ ...r, status: 'ok' as const, diff: null })),
      summary: { ok: 3 },
    });
    mockFetch((r) => (r.url.endsWith('/refresh') ? ok({ ...references(), refreshed: 3 }) : ok(before)));
    renderPanel();
    await user.click(await screen.findByTestId('project-references-refresh-all'));
    const post = requests.find((r) => r.method === 'POST')!;
    expect(post).toEqual({ method: 'POST', url: referencesUrl(PROJECT, '/refresh'), body: { version: REVISION } });
    expect(await screen.findByTestId('project-references-notice')).toHaveTextContent('1 reference has changed.');
    expect(screen.getByTestId('project-reference-status-0')).toHaveTextContent('Changed');
  });

  test("a row's refresh sends only its URL and opens its changes", async () => {
    const user = userEvent.setup();
    mockFetch((r) => (r.url.endsWith('/refresh') ? ok({ ...references(), refreshed: 1 }) : ok(references())));
    renderPanel();
    await user.click(await screen.findByTestId('project-reference-refresh-0'));
    await waitFor(() => expect(requests.some((r) => r.method === 'POST')).toBe(true));
    expect(requests.find((r) => r.method === 'POST')!.body).toEqual({ version: REVISION, urls: [MONEY] });
    expect(await screen.findByTestId('project-reference-diff-0')).toBeInTheDocument();
    expect(screen.getByTestId('project-references-notice')).toHaveTextContent('1 reference has changed.');
  });

  test('pin and unpin call the BFF and reload', async () => {
    const user = userEvent.setup();
    mockFetch((r) => (r.method === 'GET' ? ok(references()) : ok(references().references[1])));
    renderPanel();
    await user.click(await screen.findByTestId('project-reference-pin-1'));
    await waitFor(() => expect(requests.some((r) => r.method === 'PUT')).toBe(true));
    expect(requests.find((r) => r.method === 'PUT')).toMatchObject({
      url: referencesUrl(PROJECT, '/pin'),
      body: { url: ERRORS },
    });
    await user.click(screen.getByTestId('project-reference-pin-0'));
    await waitFor(() => expect(requests.some((r) => r.method === 'DELETE')).toBe(true));
    expect(requests.find((r) => r.method === 'DELETE')!.url).toBe(
      `${referencesUrl(PROJECT, '/pin')}?url=${encodeURIComponent(MONEY)}`
    );
    await waitFor(() => expect(requests.filter((r) => r.method === 'GET').length).toBeGreaterThanOrEqual(3));
  });

  test('a never-fetched reference cannot be pinned', async () => {
    mockFetch(() => ok(references()));
    renderPanel();
    expect(await screen.findByTestId('project-reference-pin-2')).toBeDisabled();
  });

  test('a refused refresh says why', async () => {
    const user = userEvent.setup();
    mockFetch((r) => (r.method === 'POST' ? refuse('Forbidden', 403) : ok(references())));
    renderPanel();
    await user.click(await screen.findByTestId('project-references-refresh-all'));
    expect(await screen.findByTestId('project-references-notice')).toHaveTextContent('Forbidden');
  });

  test('a version without a single-document source shows an error', async () => {
    mockFetch(() => refuse('This version was imported from several files.', 409, 'unsupported-source'));
    renderPanel();
    expect(await screen.findByText('This version was imported from several files.')).toBeInTheDocument();
  });

  test('no references reads as self-contained and offers nothing to refresh', async () => {
    mockFetch(() => ok(references({ references: [], summary: {}, cycles: [], cycle_total: 0 })));
    renderPanel();
    expect(await screen.findByTestId('project-references-empty')).toBeInTheDocument();
    expect(screen.getByTestId('project-references-refresh-all')).toBeDisabled();
    expect(screen.getByTestId('project-references-cycles')).toHaveTextContent('No circular references.');
  });

  test('switching revision loads that revision', async () => {
    const user = userEvent.setup();
    mockFetch(() => ok(references()));
    renderPanel();
    await screen.findByTestId('project-reference-0');
    await user.selectOptions(screen.getByTestId('project-references-revision'), OLDER);
    await waitFor(() => expect(requests.some((r) => r.url.endsWith(`version=${OLDER}`))).toBe(true));
  });

  test('has no axe violations', async () => {
    mockFetch(() => ok(references()));
    const { container } = renderPanel();
    await screen.findByTestId('project-reference-0');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});

// ---------------------------------------------------------------------------------------
// Policy card
// ---------------------------------------------------------------------------------------

describe('the external reference policy', () => {
  test('an administrator changes the mode and allowlist', async () => {
    const user = userEvent.setup();
    const saved = { ...POLICY, mode: 'inline' as const, allowlist: ['*.acme.com'] };
    mockFetch((r) => (r.method === 'PUT' ? ok(saved) : ok(references())));
    renderPanel();
    await user.click(await screen.findByTestId('external-ref-policy-edit'));
    await user.selectOptions(screen.getByTestId('external-ref-policy-mode'), 'inline');
    const list = screen.getByTestId('external-ref-policy-allowlist');
    await user.clear(list);
    await user.type(list, '*.acme.com');
    await user.click(screen.getByTestId('external-ref-policy-save'));
    await waitFor(() =>
      expect(screen.getByTestId('external-ref-policy-summary')).toHaveTextContent('Fetch: *.acme.com.')
    );
    expect(requests.find((r) => r.method === 'PUT')).toEqual({
      method: 'PUT',
      url: '/api/external-ref-policy',
      body: { mode: 'inline', allowlist: ['*.acme.com'] },
    });
  });

  test('proxy-fetch needs a host before it can be saved', async () => {
    const user = userEvent.setup();
    mockFetch(() => ok(references()));
    renderPanel();
    await user.click(await screen.findByTestId('external-ref-policy-edit'));
    await user.clear(screen.getByTestId('external-ref-policy-allowlist'));
    expect(screen.getByText('Add at least one host.')).toBeInTheDocument();
    expect(screen.getByTestId('external-ref-policy-save')).toBeDisabled();
  });

  test('a refused save shows the message', async () => {
    const user = userEvent.setup();
    mockFetch((r) => (r.method === 'PUT' ? refuse("'bad host!' is not a hostname pattern.", 422) : ok(references())));
    renderPanel();
    await user.click(await screen.findByTestId('external-ref-policy-edit'));
    await user.click(screen.getByTestId('external-ref-policy-save'));
    expect(await screen.findByTestId('external-ref-policy-error')).toHaveTextContent('is not a hostname pattern');
  });

  test('a member sees the policy but cannot change it', async () => {
    mockFetch(() => ok(references({ policy: { ...POLICY, can_edit: false } })));
    renderPanel();
    expect(await screen.findByTestId('external-ref-policy')).toHaveTextContent(
      'Workspace administrators can change it.'
    );
    expect(screen.queryByTestId('external-ref-policy-edit')).toBeNull();
  });
});

// ---------------------------------------------------------------------------------------
// Docs fixture
// ---------------------------------------------------------------------------------------

describe('docs fixture', () => {
  test('the fixture: references with a changed one open', async () => {
    const user = userEvent.setup();
    mockFetch(() => ok(references()));
    const { container } = renderPanel();
    await user.click(await screen.findByTestId('project-reference-toggle-0'));
    await screen.findByTestId('project-reference-diff-0');
    if (process.env.PROJECT_REFERENCES_FIXTURE_DUMP === '1') {
      // A static dump keeps attributes, not live state: mark each select's chosen option.
      container.querySelectorAll('select').forEach((select) => {
        select.querySelectorAll('option').forEach((option) => {
          option.toggleAttribute('selected', option.value === select.value);
        });
      });
      const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'project-references');
      fs.mkdirSync(out, { recursive: true });
      fs.writeFileSync(path.join(out, 'panel.html'), `${container.innerHTML}\n`);
    }
    expect(container.innerHTML.length).toBeGreaterThan(0);
  });
});
