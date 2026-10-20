/**
 * Federation on screen (V2-REPO-8.2, #2806): the merge-history model and its conflict diff, the
 * history list in both scopes, and the federation switch — mounted against a mocked BFF.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, jest, test, beforeEach } from '@jest/globals';

import { FederationMergeHistory } from '../src/app/components/ade/versions/FederationMergeHistory';
import { FederationSwitch } from '../src/app/components/ade/versions/FederationSwitch';
import {
  FEDERATION_STATUS_LABEL,
  conflictDiff,
  definitionText,
  mergeSentence,
  parseFederationMerges,
  parseFederationSetting,
  type FederationMerge,
} from '@lib/repository-federation';

const PROJECT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

const CONFLICT = {
  kind: 'class',
  key: 'User',
  sources: [
    {
      role: 'existing',
      repositoryFullName: 'acme/users',
      branch: 'main',
      path: 'openapi.yaml',
      definition: { type: 'object', properties: { id: { type: 'string' } } },
    },
    {
      role: 'incoming',
      repositoryFullName: 'acme/billing',
      branch: 'main',
      path: 'spec.yaml',
      definition: { type: 'object', properties: { id: { type: 'integer' } } },
    },
  ],
};

const MERGES = {
  success: true,
  merges: [
    {
      id: 'm2',
      projectId: PROJECT,
      projectName: 'Shop',
      status: 'conflicted',
      versionId: null,
      versionLabel: null,
      repositoryFullName: 'acme/billing',
      branch: 'main',
      path: 'spec.yaml',
      sourceCount: 2,
      classesCarried: 0,
      pathsCarried: 0,
      removedCount: 0,
      conflictCount: 3,
      sources: [],
      conflicts: [CONFLICT],
      createdAt: '2026-10-19T12:05:00Z',
    },
    {
      id: 'm1',
      projectId: PROJECT,
      projectName: 'Shop',
      status: 'merged',
      versionId: 'v2',
      versionLabel: '1.2.0',
      repositoryFullName: 'acme/billing',
      branch: 'main',
      path: 'spec.yaml',
      sourceCount: 2,
      classesCarried: 1,
      pathsCarried: 2,
      removedCount: 0,
      conflictCount: 0,
      sources: [{ repositoryFullName: 'acme/users', branch: 'main', path: 'openapi.yaml', precedence: 1 }],
      conflicts: [],
      createdAt: '2026-10-19T12:00:00Z',
    },
  ],
};

function reply(status: number, body: unknown) {
  return { ok: status < 400, status, json: async () => body } as unknown as Response;
}

describe('the model', () => {
  test('parses history and refuses malformed rows', () => {
    expect(parseFederationMerges({})).toBeNull();
    const merges = parseFederationMerges({ merges: [...MERGES.merges, { id: 'x', status: 'nope' }] }) as FederationMerge[];
    expect(merges.map((m) => m.id)).toEqual(['m2', 'm1']);
    expect(merges[0].conflicts[0].sources.map((s) => s.role)).toEqual(['existing', 'incoming']);
    const oneSided = parseFederationMerges({
      merges: [{ ...MERGES.merges[0], conflicts: [{ ...CONFLICT, sources: [CONFLICT.sources[0]] }] }],
    });
    expect(oneSided?.[0].conflicts).toEqual([]);
  });

  test('parses the switch', () => {
    expect(parseFederationSetting({ enabled: false })).toBe(false);
    expect(parseFederationSetting({ enabled: 'yes' })).toBeNull();
  });

  test('sentences', () => {
    const [conflicted, merged] = parseFederationMerges(MERGES) as FederationMerge[];
    expect(mergeSentence(merged)).toBe('Merged 2 files into 1.2.0: carried 1 class and 2 paths from other files.');
    expect(mergeSentence(conflicted)).toBe(
      '3 definitions collided with another repository file, so the import wrote nothing.',
    );
    expect(mergeSentence({ ...merged, status: 'replaced', removedCount: 4 })).toMatch(/dropping 4 class\(es\)/);
    expect(FEDERATION_STATUS_LABEL.conflicted).toBe('Conflict');
  });

  test('the conflict diff marks who has each line', () => {
    const [conflicted] = parseFederationMerges(MERGES) as FederationMerge[];
    const lines = conflictDiff(conflicted.conflicts[0]);
    expect(lines.filter((l) => l.change === 'existing').map((l) => l.text.trim())).toEqual(['"type": "string"']);
    expect(lines.filter((l) => l.change === 'incoming').map((l) => l.text.trim())).toEqual(['"type": "integer"']);
    expect(lines.some((l) => l.change === 'same' && l.text.includes('"properties"'))).toBe(true);
  });

  test('definition text covers missing and truncated definitions, and sorts keys', () => {
    expect(definitionText(null)).toBe('(definition not available)');
    expect(definitionText({ $truncated: true, bytes: 25000 })).toBe('(definition too large to keep: 25,000 bytes)');
    expect(definitionText({ b: 1, a: [{ d: 1, c: 2 }] })).toBe(
      '{\n  "a": [\n    {\n      "c": 2,\n      "d": 1\n    }\n  ],\n  "b": 1\n}',
    );
  });
});

describe('FederationMergeHistory', () => {
  beforeEach(() => {
    global.fetch = jest.fn(async () => reply(200, MERGES)) as unknown as typeof fetch;
  });

  test('project scope names the imported file and opens a conflict diff', async () => {
    render(
      <FederationMergeHistory url="/api/projects/p/federation-merges" scope="project" emptyDescription="none" />,
    );
    const rows = await screen.findAllByTestId('federation-merge');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByTestId('federation-status-conflicted')).toHaveTextContent('Conflict');
    expect(rows[0].querySelector('.fed-row__name')).toHaveTextContent('acme/billing (main:spec.yaml)');
    expect(within(rows[0]).getByText('Show the conflict (of 3)')).toBeInTheDocument();
    const diff = within(rows[0]).getByTestId('federation-diff');
    expect(diff.querySelector('[data-change="existing"]')).toHaveTextContent('"type": "string"');
    expect(diff.querySelector('[data-change="incoming"]')).toHaveTextContent('"type": "integer"');
    expect(within(rows[0]).getByText('acme/users (main:openapi.yaml)')).toBeInTheDocument();
    expect(within(rows[1]).getByTestId('federation-status-merged')).toBeInTheDocument();
    expect(within(rows[1]).queryByTestId('federation-conflict')).not.toBeInTheDocument();
  });

  test('repository scope names the project and the file', async () => {
    render(
      <FederationMergeHistory url="/api/repositories/r/federation-merges" scope="repository" emptyDescription="none" />,
    );
    const [row] = await screen.findAllByTestId('federation-merge');
    expect(within(row).getByText('Shop')).toBeInTheDocument();
    expect(within(row).getByText('main:spec.yaml')).toBeInTheDocument();
  });

  test('empty and error states', async () => {
    global.fetch = jest.fn(async () => reply(200, { success: true, merges: [] })) as unknown as typeof fetch;
    const { unmount } = render(
      <FederationMergeHistory url="/x" scope="project" emptyDescription="Nothing merged yet." />,
    );
    expect(await screen.findByTestId('federation-history-empty')).toHaveTextContent('Nothing merged yet.');
    unmount();
    global.fetch = jest.fn(async () => reply(403, { success: false, error: 'Forbidden' })) as unknown as typeof fetch;
    render(<FederationMergeHistory url="/x" scope="project" emptyDescription="" />);
    expect(await screen.findByTestId('federation-history-error')).toHaveTextContent('Forbidden');
  });
});

describe('FederationSwitch', () => {
  test('reads the switch, explains it, and saves a change', async () => {
    const puts: unknown[] = [];
    global.fetch = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        puts.push(JSON.parse(String(init.body)));
        return reply(200, { success: true, projectId: PROJECT, enabled: false });
      }
      return reply(200, { success: true, projectId: PROJECT, enabled: true });
    }) as unknown as typeof fetch;
    const changed = jest.fn();
    render(<FederationSwitch projectId={PROJECT} onChanged={changed} />);
    expect(await screen.findByTestId('federation-state')).toHaveTextContent('On');
    expect(screen.getByTestId('federation-explanation')).toHaveTextContent(/merged with the other contributing files/);
    fireEvent.click(screen.getByLabelText('Merge repository files into one API'));
    await waitFor(() => expect(screen.getByTestId('federation-state')).toHaveTextContent('Off'));
    expect(puts).toEqual([{ enabled: false }]);
    expect(changed).toHaveBeenCalledWith(false);
    expect(screen.getByTestId('federation-explanation')).toHaveTextContent(/replaces the API/);
  });

  test('a refused change keeps the old value and says why', async () => {
    global.fetch = jest.fn(async (_url: RequestInfo | URL, init?: RequestInit) =>
      init?.method === 'PUT'
        ? reply(403, { success: false, error: 'You need projects:edit.' })
        : reply(200, { success: true, enabled: true }),
    ) as unknown as typeof fetch;
    render(<FederationSwitch projectId={PROJECT} />);
    await screen.findByTestId('federation-state');
    fireEvent.click(screen.getByLabelText('Merge repository files into one API'));
    expect(await screen.findByTestId('federation-switch-error')).toHaveTextContent('You need projects:edit.');
    expect(screen.getByTestId('federation-state')).toHaveTextContent('On');
  });
});
