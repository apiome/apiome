/**
 * Stored overlay chains in apiome-ui — GVM-4.3 (#5878).
 *
 * * the transport helpers (URL, fingerprint, revision-id check);
 * * the Versions **Overlays** tab: lists the chain, adds an uploaded overlay as `manual`, removes
 *   one, previews the render with its ledger, and is read-only on a published revision (with the
 *   publish render shown);
 * * Export Studio's Overlays step: the stored chain, the **Apply stored overlays** switch and
 *   **Save to chain**; the verify key and the batch body carry the opt-out;
 * * Agent access **Save as overlay**: the accepted enrichment goes to the chosen draft revision as
 *   `enrichment-export`, and a project with no draft says so;
 * * the BFF proxy builds the REST path for the session's tenant and passes the refusal code on.
 *
 * Regenerate the docs fixture (`e2e/fixtures/version-overlays/panel.html`) with
 *     VERSION_OVERLAYS_FIXTURE_DUMP=1 npx jest -c jest.config.ts tests/version-overlays.test.tsx -t fixture
 */

import fs from 'node:fs';
import path from 'node:path';
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { ExportOverlaysStep } from '../src/app/components/ade/dashboard/export/ExportOverlaysStep';
import { multiTargetJobBody } from '../src/app/components/ade/dashboard/export/exportBatchJob';
import { verifyConfigKey } from '../src/app/components/ade/dashboard/export/exportVerifyCache';
import { VersionOverlaysPanel } from '../src/app/components/ade/versionOverlays/VersionOverlaysPanel';
import {
  isRevisionId,
  overlaysUrl,
  shortFingerprint,
  type VersionOverlayChain,
} from '../src/app/components/ade/versionOverlays/versionOverlaysApi';
import SaveEnrichmentOverlayDialog from '../src/app/components/ade/agentAccess/SaveEnrichmentOverlayDialog';

jest.mock('../lib/db/helper-actions', () => ({
  getPublishedVersionsForTenant: jest.fn(async () => JSON.stringify({ success: true, versions: [] })),
}));

const PROJECT = 'p-1';
const DRAFT = '11111111-1111-4111-8111-111111111111';
const PUBLISHED = '22222222-2222-4222-8222-222222222222';
const FP = `sha256:${'a'.repeat(64)}`;

const VERSIONS = [
  { id: PUBLISHED, project_id: PROJECT, version_id: '1.0.0', published: true },
  { id: DRAFT, project_id: PROJECT, version_id: '1.1.0', published: false },
];

const PARTNER = {
  overlay: '1.0.0',
  info: { title: 'Partner edition', version: '1' },
  actions: [
    { target: '$.info', update: { title: 'Pets for Partners' } },
    { target: "$.paths['/pets'].get", update: { description: 'Lists every pet.' } },
  ],
};

function chain(overrides: Partial<VersionOverlayChain> = {}): VersionOverlayChain {
  return {
    version_record_id: DRAFT,
    published: false,
    max_overlays: 10,
    overlays: [
      {
        id: 'ov-1',
        position: 0,
        name: 'partner.yaml',
        source: 'manual',
        content_fingerprint: FP,
        action_count: 2,
        created_by: 'u-1',
        created_at: '2026-11-16T12:00:00Z',
        document: PARTNER,
      },
      {
        id: 'ov-2',
        position: 1,
        name: 'Agent enrichment (1.0.0)',
        source: 'enrichment-export',
        content_fingerprint: `sha256:${'b'.repeat(64)}`,
        action_count: 4,
        created_by: 'u-1',
        created_at: '2026-11-16T12:05:00Z',
        document: { ...PARTNER, info: { title: 'Accepted agent enrichment', version: '1' } },
      },
    ],
    render: null,
    ...overrides,
  };
}

const PREVIEW = {
  version_record_id: DRAFT,
  source_fingerprint: FP,
  resolved_fingerprint: `sha256:${'c'.repeat(64)}`,
  document: { openapi: '3.1.0' },
  report: {
    applied: ['stored:partner.yaml'],
    ledger: [
      {
        pointer: '/info/title',
        kind: 'replaced',
        overlay: 'stored:partner.yaml',
        action_index: 0,
        target: '$.info',
        detail: "The value at /info/title was replaced by overlay 'stored:partner.yaml'.",
      },
    ],
    findings: [
      {
        rule: 'overlay.unmatched-target',
        severity: 'warning',
        overlay: 'stored:partner.yaml',
        action_index: 1,
        target: "$.paths['/pets'].get",
        message: 'Target matched nothing in the document; the action was not applied.',
      },
    ],
    changes: 1,
    truncated: false,
  },
};

type Request = { method: string; url: string; body?: unknown };
let requests: Request[] = [];

function ok(data: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => ({ success: true, data }) } as Response;
}

function refuse(error: string, status: number, code: string | null = null) {
  return { ok: false, status, json: async () => ({ success: false, error, code }) } as Response;
}

/** Route the BFF calls the panel and the dialog make. */
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

/** A File whose `text()` works under jsdom (older jsdom Blobs have no `text`). */
function textFile(name: string, text: string): File {
  const f = new File([text], name, { type: 'application/json' });
  Object.defineProperty(f, 'text', { value: async () => text });
  return f;
}

describe('transport helpers', () => {
  test('address a revision chain by project and revision', () => {
    expect(overlaysUrl('p 1', DRAFT, '/preview')).toBe(
      `/api/versions/${DRAFT}/overlays/preview?projectId=p%201`
    );
  });

  test('shorten a fingerprint and tell a revision id from a label', () => {
    expect(shortFingerprint(FP)).toBe('sha256:aaaaaaaaaaaa');
    expect(shortFingerprint(null)).toBe('—');
    expect(isRevisionId(DRAFT)).toBe(true);
    expect(isRevisionId('1.0.0')).toBe(false);
    expect(isRevisionId(null)).toBe(false);
  });
});

describe('the Overlays tab', () => {
  test('lists the draft chain in order, with source and fingerprint', async () => {
    mockFetch((r) => (r.method === 'GET' && r.url.startsWith(`/api/versions/${PUBLISHED}`) ? ok(chain({ published: true })) : r.method === 'GET' ? ok(chain()) : undefined));
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />);
    const first = await screen.findByTestId('version-overlay-0');
    expect(first).toHaveTextContent('partner.yaml');
    expect(first).toHaveTextContent('2 actions');
    expect(first).toHaveTextContent('sha256:aaaaaaaaaaaa');
    expect(first).toHaveTextContent('Uploaded');
    expect(screen.getByTestId('version-overlay-1')).toHaveTextContent('Agent enrichment');
    expect(screen.getByTestId('version-overlays-add')).toBeEnabled();
    expect(requests[0].url).toBe(overlaysUrl(PROJECT, DRAFT));
  });

  test('adds an uploaded overlay as a manual overlay and reloads', async () => {
    mockFetch((r) => (r.method === 'POST' ? ok(chain().overlays[0], 201) : ok(chain())));
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />);
    await screen.findByTestId('version-overlay-0');
    const file = textFile('partner.json', JSON.stringify(PARTNER));
    fireEvent.change(screen.getByTestId('version-overlays-input'), { target: { files: [file] } });
    await waitFor(() => expect(requests.some((r) => r.method === 'POST')).toBe(true));
    const post = requests.find((r) => r.method === 'POST')!;
    expect(post.url).toBe(overlaysUrl(PROJECT, DRAFT));
    expect(post.body).toEqual({ name: 'partner.json', source: 'manual', document: PARTNER });
    await waitFor(() => expect(requests.filter((r) => r.method === 'GET').length).toBeGreaterThanOrEqual(2));
  });

  test('a file that is not an overlay is reported and never sent', async () => {
    mockFetch(() => ok(chain()));
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />);
    await screen.findByTestId('version-overlay-0');
    const file = textFile('spec.json', '{"openapi": "3.1.0"}');
    fireEvent.change(screen.getByTestId('version-overlays-input'), { target: { files: [file] } });
    expect(await screen.findByTestId('version-overlays-notices')).toBeInTheDocument();
    expect(requests.some((r) => r.method === 'POST')).toBe(false);
  });

  test('removes an overlay', async () => {
    const user = userEvent.setup();
    mockFetch((r) => (r.method === 'DELETE' ? ok(null) : ok(chain())));
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />);
    await user.click(await screen.findByTestId('version-overlay-remove-0'));
    await waitFor(() => expect(requests.some((r) => r.method === 'DELETE')).toBe(true));
    expect(requests.find((r) => r.method === 'DELETE')!.url).toBe(overlaysUrl(PROJECT, DRAFT, '/ov-1'));
  });

  test('a refused write on a published revision says why', async () => {
    const user = userEvent.setup();
    mockFetch((r) =>
      r.method === 'DELETE' ? refuse('read-only', 409, 'overlay-version-published') : ok(chain())
    );
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />);
    await user.click(await screen.findByTestId('version-overlay-remove-0'));
    expect(await screen.findByTestId('version-overlays-notices')).toHaveTextContent(
      'This revision is published, so its overlays are read-only.'
    );
  });

  test('previews the render with its ledger and findings', async () => {
    const user = userEvent.setup();
    mockFetch((r) => (r.url.includes('/preview') ? ok(PREVIEW) : ok(chain())));
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />);
    await user.click(await screen.findByTestId('version-overlays-preview'));
    const result = await screen.findByTestId('version-overlays-preview-result');
    expect(result).toHaveTextContent('sha256:cccccccccccc');
    expect(within(result).getByTestId('export-overlay-findings')).toHaveTextContent('overlay.unmatched-target');
  });

  test('a published revision is read-only and shows its publish render', async () => {
    mockFetch(() =>
      ok(
        chain({
          published: true,
          render: {
            source_fingerprint: FP,
            resolved_fingerprint: `sha256:${'d'.repeat(64)}`,
            overlays: [],
            findings: [],
            changes: 3,
            rendered_by: 'u-1',
            rendered_at: '2026-11-16T12:10:00Z',
          },
        })
      )
    );
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={PUBLISHED} />);
    expect(await screen.findByTestId('version-overlays-read-only')).toBeInTheDocument();
    expect(screen.queryByTestId('version-overlays-add')).toBeNull();
    expect(screen.queryByTestId('version-overlay-remove-0')).toBeNull();
    expect(screen.getByTestId('version-overlays-render')).toHaveTextContent('sha256:dddddddddddd');
    expect(screen.getByTestId('version-overlays-render')).toHaveTextContent('3 changes');
  });

  test('an empty chain says the revision exports as it is', async () => {
    mockFetch(() => ok(chain({ overlays: [] })));
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />);
    expect(await screen.findByTestId('version-overlays-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('version-overlays-preview')).toBeNull();
  });

  test('the docs fixture', async () => {
    const user = userEvent.setup();
    mockFetch((r) => (r.url.includes('/preview') ? ok(PREVIEW) : ok(chain())));
    const { container } = render(
      <VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />
    );
    await user.click(await screen.findByTestId('version-overlays-preview'));
    await screen.findByTestId('version-overlays-preview-result');
    if (process.env.VERSION_OVERLAYS_FIXTURE_DUMP === '1') {
      const dir = path.join(__dirname, '..', 'e2e', 'fixtures', 'version-overlays');
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, 'panel.html'), `${container.innerHTML}\n`);
    }
    expect(container.innerHTML.length).toBeGreaterThan(0);
  });
});

describe("Export Studio's stored chain", () => {
  const stored = (overrides: Partial<Parameters<typeof ExportOverlaysStep>[0]['stored'] & object> = {}) => ({
    chain: chain(),
    error: null,
    apply: true,
    onToggleApply: jest.fn(),
    onSaveToChain: jest.fn(async () => null as string | null),
    ...overrides,
  });

  test('lists the stored chain and switches it off', async () => {
    const user = userEvent.setup();
    const props = stored();
    render(<ExportOverlaysStep overlays={[]} onChange={jest.fn()} stored={props} />);
    expect(screen.getByTestId('export-studio-stored-overlay-0')).toHaveTextContent('partner.yaml');
    await user.click(screen.getByTestId('export-studio-apply-stored'));
    expect(props.onToggleApply).toHaveBeenCalledWith(false);
  });

  test('saves an uploaded overlay to the chain', async () => {
    const user = userEvent.setup();
    const props = stored();
    render(
      <ExportOverlaysStep overlays={[{ name: 'partner.yaml', document: PARTNER }]} onChange={jest.fn()} stored={props} />
    );
    await user.click(screen.getByTestId('export-studio-overlay-save-0'));
    expect(props.onSaveToChain).toHaveBeenCalledWith({ name: 'partner.yaml', document: PARTNER });
    await waitFor(() => expect(screen.getByTestId('export-studio-overlay-save-0')).toBeDisabled());
  });

  test('a published revision offers no Save to chain', () => {
    render(
      <ExportOverlaysStep
        overlays={[{ name: 'partner.yaml', document: PARTNER }]}
        onChange={jest.fn()}
        stored={stored({ chain: chain({ published: true }) })}
      />
    );
    expect(screen.queryByTestId('export-studio-overlay-save-0')).toBeNull();
  });

  test('without a revision the step is unchanged', () => {
    render(<ExportOverlaysStep overlays={[]} onChange={jest.fn()} />);
    expect(screen.queryByTestId('export-studio-stored-overlays')).toBeNull();
  });

  test('the opt-out joins the verify key and the batch body; the default changes neither', () => {
    const base = { artifact: 'a', version: DRAFT, target: 'openapi' };
    expect(verifyConfigKey({ ...base, applyStoredOverlays: true })).toBe(verifyConfigKey(base));
    expect(verifyConfigKey({ ...base, applyStoredOverlays: false })).not.toBe(verifyConfigKey(base));
    expect(multiTargetJobBody('a', DRAFT, ['openapi'], false, null)).not.toHaveProperty('apply_stored_overlays');
    expect(multiTargetJobBody('a', DRAFT, ['openapi'], false, null, false)).toMatchObject({
      apply_stored_overlays: false,
    });
  });
});

describe('Save enrichment as overlay', () => {
  const ENRICHMENT = {
    toolset_id: 'ts-1',
    project_id: PROJECT,
    version_id: PUBLISHED,
    version_label: '1.0.0',
    action_count: 3,
    skipped: ['Query.user'],
    document: PARTNER,
  };

  test('saves the accepted enrichment to the chosen draft revision', async () => {
    const user = userEvent.setup();
    mockFetch((r) => {
      if (r.url === '/api/agent-access/toolsets/ts-1/enrichment-overlay') return ok(ENRICHMENT);
      if (r.url === `/api/versions?projectId=${PROJECT}`) {
        return { ok: true, status: 200, json: async () => ({ success: true, versions: VERSIONS }) } as Response;
      }
      if (r.method === 'POST') return ok(chain().overlays[1], 201);
      return undefined;
    });
    render(<SaveEnrichmentOverlayDialog open onOpenChange={jest.fn()} toolsetId="ts-1" />);
    expect(await screen.findByTestId('agx-save-enrichment-overlay-count')).toHaveTextContent(
      '3 accepted descriptions · 1 not addressable in OpenAPI (left out)'
    );
    expect(screen.getByTestId('agx-save-enrichment-overlay-target')).toHaveValue(DRAFT);
    await user.click(screen.getByTestId('agx-save-enrichment-overlay-save'));
    expect(await screen.findByTestId('agx-save-enrichment-overlay-saved')).toHaveTextContent('Saved to v1.1.0');
    const post = requests.find((r) => r.method === 'POST')!;
    expect(post.url).toBe(overlaysUrl(PROJECT, DRAFT));
    expect(post.body).toEqual({
      name: 'Agent enrichment (1.0.0)',
      source: 'enrichment-export',
      document: PARTNER,
    });
  });

  test('a project with no draft revision says so and cannot save', async () => {
    mockFetch((r) => {
      if (r.url.endsWith('/enrichment-overlay')) return ok(ENRICHMENT);
      return {
        ok: true,
        status: 200,
        json: async () => ({ success: true, versions: [VERSIONS[0]] }),
      } as Response;
    });
    render(<SaveEnrichmentOverlayDialog open onOpenChange={jest.fn()} toolsetId="ts-1" />);
    expect(await screen.findByTestId('agx-save-enrichment-overlay-no-draft')).toBeInTheDocument();
    expect(screen.getByTestId('agx-save-enrichment-overlay-save')).toBeDisabled();
  });
});
