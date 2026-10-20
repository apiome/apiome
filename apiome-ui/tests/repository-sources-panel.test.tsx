/**
 * The Sources tab of the Versions dashboard, rendered (REPO-5.7, #2792).
 *
 * Mounts the real `RepositorySourcesPanel` against a mocked BFF route and pins the acceptance
 * criteria as a reader meets them: the project's contributing repositories are listed in
 * precedence order, and **every class and path shows its source** (or that no repository defined
 * it).
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { RepositorySourcesPanel } from '../src/app/components/ade/versions/RepositorySourcesPanel';

const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const REV_1 = '11111111-1111-4111-8111-111111111111';
const REV_2 = '22222222-2222-4222-8222-222222222222';
const VERSIONS = [
  { id: REV_2, version_id: '1.1.0' },
  { id: REV_1, version_id: '1.0.0' },
];

const source = (id: string, name: string, precedence: number, classes: number, paths: number) => ({
  id,
  repository_id: `repo-${id}`,
  repository_full_name: name,
  provider: 'github',
  branch: 'main',
  path: 'openapi.yaml',
  precedence,
  first_version_id: REV_1,
  last_version_id: REV_2,
  last_version_label: '1.1.0',
  last_blob_sha: null,
  class_count: classes,
  path_count: paths,
  created_at: '2026-10-19T12:00:00Z',
  updated_at: '2026-10-19T12:00:00Z',
});

const prov = (id: string, name: string, carried: string | null = null) => ({
  source_id: id,
  repository_id: `repo-${id}`,
  repository_full_name: name,
  branch: 'main',
  path: 'openapi.yaml',
  blob_sha: null,
  carried_from_version_id: carried,
});

const MERGED = {
  project_id: PROJECT_ID,
  sources: [source('s1', 'acme/users', 1, 1, 1), source('s2', 'acme/billing', 2, 1, 1)],
  version: { id: REV_2, version_label: '1.1.0' },
  entities: [
    { kind: 'class', key: 'Invoice', source: prov('s2', 'acme/billing') },
    { kind: 'class', key: 'Note', source: null },
    { kind: 'class', key: 'User', source: prov('s1', 'acme/users', REV_1) },
    { kind: 'path', key: '/invoices', source: prov('s2', 'acme/billing') },
    { kind: 'path', key: '/users', source: prov('s1', 'acme/users', REV_1) },
  ],
  counts: { classes: 3, paths: 2, attributed: 4, unattributed: 1 },
};

let replies: Record<string, { status: number; body: unknown }>;
let requested: string[];

beforeEach(() => {
  requested = [];
  replies = {};
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    // The PR-back section (REPO-5.8) asks which repositories can be synced to; none here.
    if (url.includes('/pr-back/')) {
      return { ok: true, status: 200, json: async () => ({ success: true, repositories: [] }) } as unknown as Response;
    }
    // Federation (V2-REPO-8.2): the switch and the merge history.
    if (url.endsWith('/repository-federation')) {
      return { ok: true, status: 200, json: async () => ({ success: true, enabled: true }) } as unknown as Response;
    }
    if (url.endsWith('/federation-merges')) {
      return { ok: true, status: 200, json: async () => ({ success: true, merges: [] }) } as unknown as Response;
    }
    requested.push(url);
    const version = new URL(url, 'http://ui.test').searchParams.get('version') ?? '';
    const reply = replies[version] ?? { status: 200, body: { success: true, ...MERGED } };
    // jsdom has no `Response`; the panel only reads `ok`, `status` and `json()`.
    return { ok: reply.status < 400, status: reply.status, json: async () => reply.body } as unknown as Response;
  }) as unknown as typeof fetch;
});

describe('RepositorySourcesPanel', () => {
  test('lists the contributing repositories in precedence order', async () => {
    render(<RepositorySourcesPanel projectId={PROJECT_ID} versions={VERSIONS} />);
    const list = await screen.findByTestId('repository-sources-list');
    const rows = within(list).getAllByTestId('repository-source');
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining('acme/users · main:openapi.yaml'),
      expect.stringContaining('acme/billing · main:openapi.yaml'),
    ]);
    expect(within(rows[0]).getByLabelText('Precedence 1')).toBeInTheDocument();
    expect(rows[1]).toHaveTextContent('Last imported into 1.1.0');
    expect(screen.getByTestId('repository-sources-summary')).toHaveTextContent(
      '2 repository files contribute. 4 of 5 classes and paths come from a repository.',
    );
    expect(requested[0]).toBe(`/api/projects/${PROJECT_ID}/repository-sources?version=${REV_2}`);
  });

  test('shows the source of every class and path', async () => {
    render(<RepositorySourcesPanel projectId={PROJECT_ID} versions={VERSIONS} />);
    const table = await screen.findByTestId('repository-sources-table');
    const row = (name: string) => within(table).getByText(name).closest('tr') as HTMLElement;
    expect(row('User')).toHaveTextContent('acme/users · main:openapi.yaml');
    expect(within(row('User')).getByTestId('rsrc-origin-carried')).toHaveTextContent('Carried forward');
    expect(within(row('/invoices')).getByTestId('rsrc-origin-imported')).toHaveTextContent('Imported');
    expect(within(row('Note')).getByTestId('rsrc-origin-unattributed')).toHaveTextContent('Not from a repository');
  });

  test('filters by kind, by source, and by search', async () => {
    render(<RepositorySourcesPanel projectId={PROJECT_ID} versions={VERSIONS} />);
    const table = await screen.findByTestId('repository-sources-table');
    fireEvent.click(screen.getByTestId('repository-sources-kind-path'));
    expect(within(table).queryByText('User')).not.toBeInTheDocument();
    expect(within(table).getByText('/users')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('repository-sources-kind-all'));
    fireEvent.change(screen.getByTestId('repository-sources-source-filter'), { target: { value: 'none' } });
    expect(within(table).getByText('Note')).toBeInTheDocument();
    expect(within(table).queryByText('Invoice')).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId('repository-sources-source-filter'), { target: { value: 'all' } });
    fireEvent.change(screen.getByTestId('repository-sources-search'), { target: { value: 'invoice' } });
    expect(within(table).getByText('Invoice')).toBeInTheDocument();
    expect(within(table).queryByText('User')).not.toBeInTheDocument();
  });

  test('switching the version reloads its provenance', async () => {
    render(<RepositorySourcesPanel projectId={PROJECT_ID} versions={VERSIONS} />);
    await screen.findByTestId('repository-sources-table');
    fireEvent.change(screen.getByTestId('repository-sources-version'), { target: { value: REV_1 } });
    await waitFor(() => expect(requested).toContain(`/api/projects/${PROJECT_ID}/repository-sources?version=${REV_1}`));
  });

  test('a project no repository contributes to says so', async () => {
    replies[REV_2] = {
      status: 200,
      body: { success: true, ...MERGED, sources: [], entities: [{ kind: 'class', key: 'Note', source: null }], counts: { classes: 1, paths: 0, attributed: 0, unattributed: 1 } },
    };
    render(<RepositorySourcesPanel projectId={PROJECT_ID} versions={VERSIONS} />);
    expect(await screen.findByTestId('repository-sources-none')).toHaveTextContent(
      'No repository contributes to this project',
    );
  });

  test('a failed read is reported', async () => {
    replies[REV_2] = { status: 404, body: { success: false, error: "no project 'x' in this tenant" } };
    render(<RepositorySourcesPanel projectId={PROJECT_ID} versions={VERSIONS} />);
    expect(await screen.findByTestId('repository-sources-error')).toHaveTextContent("no project 'x' in this tenant");
  });

  test('a project without versions has nothing to load', () => {
    render(<RepositorySourcesPanel projectId={PROJECT_ID} versions={[]} />);
    expect(screen.getByText('This project has no versions yet')).toBeInTheDocument();
    expect(requested).toEqual([]);
  });

  test('shows the federation switch and the merge history (V2-REPO-8.2)', async () => {
    render(<RepositorySourcesPanel projectId={PROJECT_ID} versions={VERSIONS} />);
    expect(await screen.findByTestId('federation-state')).toHaveTextContent('On');
    expect(await screen.findByTestId('project-merge-history-empty')).toHaveTextContent(
      'Merges appear here once a second repository file is imported into this project.',
    );
  });
});
