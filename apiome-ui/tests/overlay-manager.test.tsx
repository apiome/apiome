/**
 * Overlay manager in Versions — COA-2.7 (#7050).
 *
 * * the draft model: a document round-trips through the form (other keys kept), every problem is
 *   tied to its field, Copy needs 1.1 and Reusable needs 1.2 and a declared component, the JSON view
 *   parses, and the preview helpers word match counts, values and provenance;
 * * the editor: builds an overlay with an **Update**, a **Remove** and a **Copy** action, previews it
 *   as an unsaved draft (per-action match counts, before / after rows), then saves it (POST for a
 *   new overlay, PUT keeping the source for an edit); a bad field is marked and nothing is sent; the
 *   JSON view edits the whole document; a stale preview says so;
 * * the panel: **New overlay** and **Edit** open the editor, **Preview** shows the action table and
 *   the before / after table, **Apply as version** posts the label and reports the new version,
 *   **Export with overlays** links Export Studio to the revision; none of the writes on a published
 *   revision;
 * * the BFF routes are pinned in `overlay-manager-routes.test.ts` (node environment).
 *
 * Regenerate the docs fixtures (`e2e/fixtures/version-overlays/manager-*.html`) with
 *     OVERLAY_MANAGER_FIXTURE_DUMP=1 npx jest -c jest.config.ts tests/overlay-manager.test.tsx -t fixture
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

import { OverlayEditorDialog } from '../src/app/components/ade/versionOverlays/OverlayEditorDialog';
import { VersionOverlaysPanel } from '../src/app/components/ade/versionOverlays/VersionOverlaysPanel';
import {
  blankAction,
  changedByLabel,
  documentToDraft,
  draftToDocument,
  formatDiffValue,
  matchSummary,
  matchTone,
  newOverlayDraft,
  outcomesFor,
  parseDraftJson,
  reusableActionNames,
} from '../src/app/components/ade/versionOverlays/overlayDraftModel';
import {
  applyVersionOverlays,
  overlaysUrl,
  previewVersionOverlayDraft,
  type OverlayActionOutcome,
  type VersionOverlayChain,
  type VersionOverlayPreview,
} from '../src/app/components/ade/versionOverlays/versionOverlaysApi';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const AXE_OPTIONS = {
  rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
} as const;

const PROJECT = 'p-1';
const DRAFT = '11111111-1111-4111-8111-111111111111';
const PUBLISHED = '22222222-2222-4222-8222-222222222222';
const FP = `sha256:${'a'.repeat(64)}`;

const VERSIONS = [
  { id: PUBLISHED, project_id: PROJECT, version_id: '1.0.0', published: true },
  { id: DRAFT, project_id: PROJECT, version_id: '1.1.0', published: false },
];

/** The acceptance overlay: an update, a remove and a copy. */
const PARTNER = {
  overlay: '1.1.0',
  info: { title: 'Partner edition', version: '1.0.0' },
  actions: [
    { target: '$.info', update: { title: 'Pets for Partners' } },
    { target: '$.servers[0]', remove: true },
    {
      target: "$.paths['/pets'].get",
      copy: "$['x-partner-defaults']",
      'x-note': 'kept',
    },
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
        name: 'partner-edition',
        source: 'lint-fix',
        content_fingerprint: FP,
        action_count: 3,
        created_by: 'u-1',
        created_at: '2026-11-20T12:00:00Z',
        document: PARTNER,
      },
    ],
    render: null,
    ...overrides,
  };
}

function outcome(
  overlay: string,
  index: number,
  kind: string,
  matches: number,
  status = 'applied'
): OverlayActionOutcome {
  return {
    overlay,
    action_index: index,
    target: PARTNER.actions[index]?.target ?? '',
    kind,
    ref: null,
    matches,
    changes: matches,
    status,
  };
}

function preview(overlay = 'stored:partner-edition', draft: string | null = null): VersionOverlayPreview {
  return {
    version_record_id: DRAFT,
    source_fingerprint: FP,
    resolved_fingerprint: `sha256:${'c'.repeat(64)}`,
    document: { openapi: '3.1.0' },
    draft,
    report: {
      applied: [overlay],
      ledger: [
        {
          pointer: '/info/title',
          kind: 'replaced',
          overlay,
          action_index: 0,
          target: '$.info',
          detail: 'The value at /info/title was replaced.',
        },
        {
          pointer: '/servers/0',
          kind: 'removed',
          overlay,
          action_index: 1,
          target: '$.servers[0]',
          detail: 'The value at /servers/0 was removed.',
        },
        {
          pointer: '/paths/~1pets/get/x-owner',
          kind: 'set',
          overlay,
          action_index: 2,
          target: "$.paths['/pets'].get",
          detail: 'The value was set.',
        },
      ],
      findings: [],
      changes: 3,
      truncated: false,
      actions: [outcome(overlay, 0, 'update', 1), outcome(overlay, 1, 'remove', 1), outcome(overlay, 2, 'copy', 1)],
    },
    diff: [
      {
        pointer: '/info/title',
        kind: 'replaced',
        before: 'Pets',
        before_present: true,
        after: 'Pets for Partners',
        after_present: true,
        changed_by: [{ overlay, action_index: 0, target: '$.info', kind: 'replaced' }],
      },
      {
        pointer: '/servers/0',
        kind: 'removed',
        before: { url: 'https://internal.example.com' },
        before_present: true,
        after: null,
        after_present: false,
        changed_by: [{ overlay, action_index: 1, target: '$.servers[0]', kind: 'removed' }],
      },
      {
        pointer: '/paths/~1pets/get/x-owner',
        kind: 'set',
        before: null,
        before_present: false,
        after: 'partners',
        after_present: true,
        changed_by: [
          {
            overlay,
            action_index: 2,
            target: "$.paths['/pets'].get",
            kind: 'set',
          },
        ],
      },
    ],
  };
}

type Request = { method: string; url: string; body?: unknown };
let requests: Request[] = [];

function ok(data: unknown, status = 200) {
  return {
    ok: status < 400,
    status,
    json: async () => ({ success: true, data }),
  } as Response;
}

function refuse(error: string, status: number, code: string | null = null) {
  return {
    ok: false,
    status,
    json: async () => ({ success: false, error, code }),
  } as Response;
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

// ---------------------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------------------

describe('the draft model', () => {
  test('a document round-trips through the form, keeping keys the form does not edit', () => {
    const document = {
      ...PARTNER,
      extends: 'https://example.com/openapi.yaml',
      'x-team': 'core',
    };
    const draft = documentToDraft('partner', document);
    expect(draft.actions.map((a) => a.kind)).toEqual(['update', 'remove', 'copy']);
    expect(draft.title).toBe('Partner edition');
    const built = draftToDocument(draft);
    expect(built.ok).toBe(true);
    if (built.ok) expect(built.document).toEqual(document);
  });

  test('a reusable action reads and writes its component name', () => {
    const document = {
      overlay: '1.2.0',
      info: { title: 'R', version: '1' },
      components: {
        actions: {
          'tag/partner': { fields: { update: { 'x-partner': true } } },
        },
      },
      actions: [{ $ref: '#/components/actions/tag~1partner', target: '$.paths.*.get' }],
    };
    const draft = documentToDraft('r', document);
    expect(draft.actions[0]).toMatchObject({ kind: 'ref', ref: 'tag/partner' });
    expect(reusableActionNames(draft)).toEqual(['tag/partner']);
    const built = draftToDocument(draft);
    expect(built.ok && built.document.actions).toEqual(document.actions);
  });

  test('every problem is tied to its field and nothing is built', () => {
    const draft = newOverlayDraft();
    draft.version = '1.0.0';
    draft.actions = [
      { ...blankAction('update'), target: 'info', update: '{not json' },
      { ...blankAction('copy'), target: '$.info', copy: '' },
      { ...blankAction('ref'), target: '$.info', ref: 'missing' },
    ];
    const built = draftToDocument(draft);
    expect(built.ok).toBe(false);
    if (built.ok) return;
    const fields = built.problems.map((p) => `${p.index}:${p.field}`);
    expect(fields).toEqual(expect.arrayContaining(['-1:name', '-1:title', '0:target', '0:update', '1:copy', '2:ref']));
    expect(built.problems.find((p) => p.index === 1)?.message).toMatch(/Copy needs Overlay 1.1/);
  });

  test('an overlay with no actions is refused', () => {
    const draft = { ...newOverlayDraft(), name: 'n', title: 't', actions: [] };
    const built = draftToDocument(draft);
    expect(!built.ok && built.problems[0].field).toBe('actions');
  });

  test('the JSON view parses an Overlay document and refuses anything else', () => {
    expect(parseDraftJson('n', JSON.stringify(PARTNER))).toMatchObject({
      ok: true,
    });
    expect(parseDraftJson('n', '{')).toEqual({
      ok: false,
      error: 'The document is not valid JSON.',
    });
    expect(parseDraftJson('n', '{"openapi":"3.1.0"}').ok).toBe(false);
  });

  test('preview helpers word counts, values and provenance', () => {
    expect(matchSummary(outcome('o', 0, 'update', 3))).toBe('3 matches');
    expect(matchSummary(outcome('o', 0, 'update', 1))).toBe('1 match');
    expect(matchSummary(outcome('o', 0, 'update', 0, 'unmatched'))).toBe('No match');
    expect(matchSummary(outcome('o', 0, 'copy', 1, 'invalid'))).toBe('Not applied');
    expect(matchTone(outcome('o', 0, 'update', 0, 'unmatched'))).toBe('warn');
    expect(matchTone(outcome('o', 0, 'copy', 1, 'invalid'))).toBe('danger');
    expect(formatDiffValue('x', false)).toBe('—');
    expect(formatDiffValue({ a: 1 }, true)).toBe('{"a":1}');
    expect(formatDiffValue('y'.repeat(400), true)).toHaveLength(160);
    expect(
      changedByLabel({
        ...preview().diff![0],
        changed_by: [
          { overlay: 'stored:a', action_index: 0, target: '$', kind: 'set' },
          {
            overlay: 'draft:b',
            action_index: 2,
            target: '$',
            kind: 'replaced',
          },
        ],
      })
    ).toBe('a, action 1 → b, action 3');
    const rows = outcomesFor(preview('draft:x', 'draft:x'), 'draft:x');
    expect([...rows.keys()]).toEqual([0, 1, 2]);
    expect(outcomesFor(null, 'draft:x').size).toBe(0);
  });

  test('the transport posts drafts and applies with or without a label', async () => {
    mockFetch(() => ok({}));
    await previewVersionOverlayDraft(PROJECT, DRAFT, { name: 'n', document: PARTNER }, 'ov-1');
    await applyVersionOverlays(PROJECT, DRAFT, '  ');
    await applyVersionOverlays(PROJECT, DRAFT, '2.0.0');
    expect(requests[0]).toEqual({
      method: 'POST',
      url: overlaysUrl(PROJECT, DRAFT, '/preview'),
      body: {
        draft: { name: 'n', document: PARTNER },
        replace_overlay_id: 'ov-1',
      },
    });
    expect(requests[1].body).toEqual({});
    expect(requests[2]).toMatchObject({
      url: overlaysUrl(PROJECT, DRAFT, '/apply'),
      body: { version_label: '2.0.0' },
    });
  });
});

// ---------------------------------------------------------------------------------------
// Editor
// ---------------------------------------------------------------------------------------

/** Fill the new-overlay form with the acceptance overlay's three actions. */
async function fillAcceptanceOverlay(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByTestId('overlay-editor-name'), 'partner-edition');
  await user.type(screen.getByTestId('overlay-editor-title'), 'Partner edition');
  await user.type(screen.getByTestId('overlay-editor-target-0'), '$.info');
  const update = screen.getByTestId('overlay-editor-update-0');
  await user.clear(update);
  await user.click(update);
  await user.paste('{"title": "Pets for Partners"}');

  await user.click(screen.getByTestId('overlay-editor-add-action'));
  await user.selectOptions(screen.getByTestId('overlay-editor-kind-1'), 'remove');
  await user.click(screen.getByTestId('overlay-editor-target-1'));
  await user.paste('$.servers[0]');

  await user.click(screen.getByTestId('overlay-editor-add-action'));
  await user.selectOptions(screen.getByTestId('overlay-editor-kind-2'), 'copy');
  await user.click(screen.getByTestId('overlay-editor-target-2'));
  await user.paste("$.paths['/pets'].get");
  await user.click(screen.getByTestId('overlay-editor-copy-2'));
  await user.paste("$['x-partner-defaults']");
}

describe('the overlay editor', () => {
  test('creates an overlay with update, remove and copy, previews it, then saves it', async () => {
    const user = userEvent.setup();
    const onSaved = jest.fn();
    mockFetch((r) =>
      r.url.includes('/preview')
        ? ok(preview('draft:partner-edition', 'draft:partner-edition'))
        : r.method === 'POST'
          ? ok(chain().overlays[0], 201)
          : undefined
    );
    render(
      <OverlayEditorDialog
        open
        onOpenChange={() => undefined}
        projectId={PROJECT}
        revisionId={DRAFT}
        onSaved={onSaved}
      />
    );
    await fillAcceptanceOverlay(user);
    await user.click(screen.getByTestId('overlay-editor-preview-button'));

    const shown = await screen.findByTestId('overlay-editor-preview');
    const sent = requests.find((r) => r.url.includes('/preview'))!;
    expect(sent.method).toBe('POST');
    const draftDoc = (sent.body as { draft: { document: { actions: unknown[] } } }).draft.document;
    expect(draftDoc.actions).toEqual([
      { target: '$.info', update: { title: 'Pets for Partners' } },
      { target: '$.servers[0]', remove: true },
      { target: "$.paths['/pets'].get", copy: "$['x-partner-defaults']" },
    ]);
    expect((sent.body as Record<string, unknown>).replace_overlay_id).toBeUndefined();
    expect(within(screen.getByTestId('overlay-editor-action-0')).getByText('1 match')).toBeInTheDocument();
    const diff = within(shown).getByTestId('overlay-diff-table');
    expect(diff).toHaveTextContent('Pets for Partners');
    expect(diff).toHaveTextContent('partner-edition, action 3');

    await user.click(screen.getByTestId('overlay-editor-save'));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const post = requests.find((r) => r.method === 'POST' && !r.url.includes('/preview'))!;
    expect(post.url).toBe(overlaysUrl(PROJECT, DRAFT));
    expect(post.body).toMatchObject({
      name: 'partner-edition',
      source: 'manual',
    });
  });

  test('editing previews in place and saves with PUT, keeping the source and extra keys', async () => {
    const user = userEvent.setup();
    mockFetch((r) =>
      r.url.includes('/preview')
        ? ok(preview('stored:partner-edition', 'stored:partner-edition'))
        : ok(chain().overlays[0])
    );
    const stored = chain().overlays[0];
    render(
      <OverlayEditorDialog
        open
        onOpenChange={() => undefined}
        projectId={PROJECT}
        revisionId={DRAFT}
        overlay={stored}
      />
    );
    expect(screen.getByTestId('overlay-editor-kind-2')).toHaveValue('copy');
    await user.click(screen.getByTestId('overlay-editor-preview-button'));
    await screen.findByTestId('overlay-editor-preview');
    expect((requests[0].body as Record<string, unknown>).replace_overlay_id).toBe('ov-1');

    await user.type(screen.getByTestId('overlay-editor-title'), ' 2');
    expect(screen.getByTestId('overlay-editor-preview-stale')).toBeInTheDocument();

    await user.click(screen.getByTestId('overlay-editor-save'));
    await waitFor(() => expect(requests.some((r) => r.method === 'PUT')).toBe(true));
    const put = requests.find((r) => r.method === 'PUT')!;
    expect(put.url).toBe(overlaysUrl(PROJECT, DRAFT, '/ov-1'));
    const body = put.body as { source: string; document: typeof PARTNER };
    expect(body.source).toBe('lint-fix');
    expect(body.document.info.title).toBe('Partner edition 2');
    expect(body.document.actions[2]).toEqual(PARTNER.actions[2]);
  });

  test('a bad field is marked and nothing is sent', async () => {
    const user = userEvent.setup();
    mockFetch(() => undefined);
    render(<OverlayEditorDialog open onOpenChange={() => undefined} projectId={PROJECT} revisionId={DRAFT} />);
    await user.click(screen.getByTestId('overlay-editor-save'));
    expect(await screen.findByTestId('overlay-editor-error')).toHaveTextContent('Fix the fields marked below.');
    expect(screen.getByText('Name the overlay.')).toBeInTheDocument();
    expect(requests).toHaveLength(0);
  });

  test('the JSON view edits the whole document', async () => {
    const user = userEvent.setup();
    mockFetch((r) => (r.method === 'PUT' ? ok(chain().overlays[0]) : undefined));
    render(
      <OverlayEditorDialog
        open
        onOpenChange={() => undefined}
        projectId={PROJECT}
        revisionId={DRAFT}
        overlay={chain().overlays[0]}
      />
    );
    await user.click(screen.getByRole('radio', { name: 'JSON' }));
    const json = screen.getByTestId('overlay-editor-json') as HTMLTextAreaElement;
    expect(JSON.parse(json.value)).toEqual(PARTNER);
    await user.clear(json);
    await user.click(json);
    await user.paste(JSON.stringify({ ...PARTNER, actions: [PARTNER.actions[1]] }));
    await user.click(screen.getByTestId('overlay-editor-save'));
    await waitFor(() => expect(requests.some((r) => r.method === 'PUT')).toBe(true));
    expect((requests[0].body as { document: { actions: unknown[] } }).document.actions).toEqual([PARTNER.actions[1]]);
  });

  test('a refused save shows REST’s message and stays open', async () => {
    const user = userEvent.setup();
    const onOpenChange = jest.fn();
    mockFetch(() => refuse('This revision is published.', 409, 'overlay-version-published'));
    render(
      <OverlayEditorDialog
        open
        onOpenChange={onOpenChange}
        projectId={PROJECT}
        revisionId={DRAFT}
        overlay={chain().overlays[0]}
      />
    );
    await user.click(screen.getByTestId('overlay-editor-save'));
    expect(await screen.findByTestId('overlay-editor-error')).toHaveTextContent('This revision is published.');
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  test('has no axe violations', async () => {
    mockFetch(() => undefined);
    render(
      <OverlayEditorDialog
        open
        onOpenChange={() => undefined}
        projectId={PROJECT}
        revisionId={DRAFT}
        overlay={chain().overlays[0]}
      />
    );
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
  });
});

// ---------------------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------------------

describe('the Overlays tab as an overlay manager', () => {
  test('preview lists every action with its match count and the before / after values', async () => {
    const user = userEvent.setup();
    mockFetch((r) => (r.url.includes('/preview') ? ok(preview()) : ok(chain())));
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />);
    await user.click(await screen.findByTestId('version-overlays-preview'));
    const actions = await screen.findByTestId('overlay-actions-table');
    expect(within(actions).getAllByRole('row')).toHaveLength(4);
    expect(actions).toHaveTextContent('3. Copy');
    const diff = screen.getByTestId('overlay-diff-table');
    expect(diff).toHaveTextContent('https://internal.example.com');
    expect(diff).toHaveTextContent('partner-edition, action 2');
  });

  test('New overlay and Edit open the editor; saving reloads the chain', async () => {
    const user = userEvent.setup();
    mockFetch((r) => (r.method === 'PUT' ? ok(chain().overlays[0]) : ok(chain())));
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />);
    await user.click(await screen.findByTestId('version-overlays-new'));
    expect(screen.getByRole('dialog', { name: 'New overlay' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await user.click(screen.getByTestId('version-overlay-edit-0'));
    expect(screen.getByRole('dialog', { name: 'Edit overlay — partner-edition' })).toBeInTheDocument();
    const gets = requests.filter((r) => r.method === 'GET').length;
    await user.click(screen.getByTestId('overlay-editor-save'));
    await waitFor(() => expect(requests.filter((r) => r.method === 'GET').length).toBeGreaterThan(gets));
  });

  test('Apply as version posts the label and reports the new version', async () => {
    const user = userEvent.setup();
    const onVersionCreated = jest.fn();
    mockFetch((r) =>
      r.url.includes('/apply')
        ? ok(
            {
              project_id: PROJECT,
              version_record_id: 'new-rev',
              version_label: '1.2.0',
              source_version_record_id: DRAFT,
              overlay_count: 1,
              change_count: 3,
            },
            201
          )
        : ok(chain())
    );
    render(
      <VersionOverlaysPanel
        projectId={PROJECT}
        versions={VERSIONS}
        initialRevisionId={DRAFT}
        onVersionCreated={onVersionCreated}
      />
    );
    await user.click(await screen.findByTestId('version-overlays-apply'));
    await user.type(screen.getByTestId('overlay-apply-label'), '1.0.0');
    expect(screen.getByText('Version 1.0.0 already exists. Choose another label.')).toBeInTheDocument();
    expect(screen.getByTestId('overlay-apply-confirm')).toBeDisabled();
    await user.clear(screen.getByTestId('overlay-apply-label'));
    await user.type(screen.getByTestId('overlay-apply-label'), '1.2.0');
    await user.click(screen.getByTestId('overlay-apply-confirm'));
    expect(await screen.findByTestId('overlay-apply-done')).toHaveTextContent('Created version 1.2.0 with 3 changes.');
    expect(requests.find((r) => r.url.includes('/apply'))!.body).toEqual({
      version_label: '1.2.0',
    });
    expect(onVersionCreated).toHaveBeenCalledWith(expect.objectContaining({ version_record_id: 'new-rev' }));
  });

  test('a refused apply says why', async () => {
    const user = userEvent.setup();
    mockFetch((r) =>
      r.url.includes('/apply')
        ? refuse('The overlays change nothing in this revision.', 409, 'overlay-no-changes')
        : ok(chain())
    );
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />);
    await user.click(await screen.findByTestId('version-overlays-apply'));
    await user.click(screen.getByTestId('overlay-apply-confirm'));
    expect(await screen.findByTestId('overlay-apply-error')).toHaveTextContent('change nothing');
  });

  test('Export with overlays opens Export Studio on the revision', async () => {
    mockFetch(() => ok(chain()));
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />);
    const link = await screen.findByTestId('version-overlays-export');
    const href = new URL(link.getAttribute('href')!, 'http://x');
    expect(href.pathname).toBe('/ade/dashboard/export/studio');
    expect(href.searchParams.get('artifact')).toBe(PROJECT);
    expect(href.searchParams.get('version')).toBe(DRAFT);
    expect(href.searchParams.get('from')).toBe('versions');
  });

  test('a published revision can preview, apply and export, but not edit', async () => {
    mockFetch(() => ok(chain({ published: true })));
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={PUBLISHED} />);
    expect(await screen.findByTestId('version-overlays-apply')).toBeInTheDocument();
    expect(screen.getByTestId('version-overlays-export')).toBeInTheDocument();
    expect(screen.queryByTestId('version-overlays-new')).toBeNull();
    expect(screen.queryByTestId('version-overlay-edit-0')).toBeNull();
  });

  test('an empty chain offers New overlay but nothing to preview, apply or export', async () => {
    mockFetch(() => ok(chain({ overlays: [] })));
    render(<VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />);
    expect(await screen.findByTestId('version-overlays-new')).toBeEnabled();
    expect(screen.queryByTestId('version-overlays-apply')).toBeNull();
    expect(screen.queryByTestId('version-overlays-export')).toBeNull();
  });
});

// ---------------------------------------------------------------------------------------
// Docs fixtures
// ---------------------------------------------------------------------------------------

describe('docs fixture', () => {
  const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'version-overlays');

  test('the fixture: the Overlays tab with a preview', async () => {
    const user = userEvent.setup();
    mockFetch((r) => (r.url.includes('/preview') ? ok(preview()) : ok(chain())));
    const { container } = render(
      <VersionOverlaysPanel projectId={PROJECT} versions={VERSIONS} initialRevisionId={DRAFT} />
    );
    await user.click(await screen.findByTestId('version-overlays-preview'));
    await screen.findByTestId('overlay-diff-table');
    if (process.env.OVERLAY_MANAGER_FIXTURE_DUMP === '1') {
      fs.mkdirSync(out, { recursive: true });
      fs.writeFileSync(path.join(out, 'manager-list.html'), `${container.innerHTML}\n`);
    }
    expect(container.innerHTML.length).toBeGreaterThan(0);
  });

  test('the fixture: the editor with a draft preview', async () => {
    const user = userEvent.setup();
    mockFetch(() => ok(preview('draft:partner-edition', 'draft:partner-edition')));
    render(<OverlayEditorDialog open onOpenChange={() => undefined} projectId={PROJECT} revisionId={DRAFT} />);
    await fillAcceptanceOverlay(user);
    await user.click(screen.getByTestId('overlay-editor-preview-button'));
    await screen.findByTestId('overlay-editor-preview');
    const dialog = screen.getByTestId('overlay-editor');
    if (process.env.OVERLAY_MANAGER_FIXTURE_DUMP === '1') {
      fs.mkdirSync(out, { recursive: true });
      // A static dump keeps attributes, not live state: mark each select's chosen option.
      dialog.querySelectorAll('select').forEach((select) => {
        select.querySelectorAll('option').forEach((option) => {
          option.toggleAttribute('selected', option.value === select.value);
        });
      });
      const overlay = document.querySelector('.hive-overlay') as HTMLElement;
      fs.writeFileSync(path.join(out, 'manager-editor.html'), overlay.outerHTML + dialog.outerHTML);
    }
    expect(dialog).toBeInTheDocument();
  });
});
