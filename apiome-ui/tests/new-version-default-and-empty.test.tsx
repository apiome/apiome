/**
 * COA-4.3a (#7126): New version copies the head by default; an empty version is flagged.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  defaultCopySource,
  isEmptyOpenApiDocument,
  type VersionBranchRow,
} from '../src/app/components/ade/versions/versionsModel';
import { useVersionIsEmpty } from '../src/app/components/ade/versions/useVersionIsEmpty';

const branch = (id: string, name: string, tip: string, extra: Partial<VersionBranchRow> = {}): VersionBranchRow => ({
  id,
  name,
  tip_version_id: tip,
  ...extra,
});

describe('defaultCopySource', () => {
  it('copies the head (newest) revision when there are no branches', () => {
    expect(defaultCopySource([{ id: 'v2' }, { id: 'v1' }], [])).toEqual({
      branchKey: 'blank',
      sourceVersionId: 'v2',
    });
  });

  it('is blank only when the project has no versions', () => {
    expect(defaultCopySource([], [])).toEqual({ branchKey: 'blank', sourceVersionId: '' });
  });

  it('uses the default branch tip with two or more branches', () => {
    const branches = [branch('b1', 'feature', 't1'), branch('b2', 'trunk', 't2', { is_default: true })];
    expect(defaultCopySource([{ id: 'v9' }], branches)).toEqual({
      branchKey: 'branch:b2',
      sourceVersionId: 't2',
    });
  });

  it('falls back to a branch named main, then the first branch', () => {
    expect(
      defaultCopySource([], [branch('b1', 'dev', 't1'), branch('b2', 'main', 't2')]).sourceVersionId,
    ).toBe('t2');
    expect(defaultCopySource([], [branch('b1', 'dev', 't1'), branch('b2', 'x', 't2')]).sourceVersionId).toBe('t1');
  });

  it('uses the only branch tip with a single branch', () => {
    expect(defaultCopySource([{ id: 'v1' }], [branch('b1', 'main', 'tip')]).sourceVersionId).toBe('tip');
  });
});

describe('isEmptyOpenApiDocument', () => {
  it('is empty with no paths and no schemas', () => {
    expect(isEmptyOpenApiDocument({ openapi: '3.1.0', paths: {} })).toBe(true);
    expect(
      isEmptyOpenApiDocument({ openapi: '3.1.0', paths: { '/a': { parameters: [] } }, components: { schemas: {} } }),
    ).toBe(true);
  });

  it('does not judge a body that is not an OpenAPI document', () => {
    expect(isEmptyOpenApiDocument(null)).toBe(false);
    expect(isEmptyOpenApiDocument({ score: 72 })).toBe(false);
  });

  it('is not empty with an operation or a schema', () => {
    expect(isEmptyOpenApiDocument({ openapi: '3.1.0', paths: { '/a': { get: {} } } })).toBe(false);
    expect(isEmptyOpenApiDocument({ openapi: '3.1.0', components: { schemas: { Pet: {} } } })).toBe(false);
    expect(isEmptyOpenApiDocument({ swagger: '2.0', definitions: { Pet: {} } })).toBe(false);
  });
});

function Probe({ enabled = true }: { enabled?: boolean }) {
  const empty = useVersionIsEmpty('p1', 'v1', enabled);
  return <span data-testid="probe">{String(empty)}</span>;
}

describe('useVersionIsEmpty', () => {
  afterEach(() => jest.restoreAllMocks());

  it('reports an empty document', async () => {
    global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ openapi: '3.1.0', paths: {} }) })) as never;
    render(<Probe />);
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('true'));
  });

  it('reports a populated document', async () => {
    global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ openapi: '3.1.0', paths: { '/a': { get: {} } } }) })) as never;
    render(<Probe />);
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('false'));
  });

  it('stays unknown on a failed read and does not fetch when disabled', async () => {
    global.fetch = jest.fn(async () => ({ ok: false, status: 500 })) as never;
    const { rerender } = render(<Probe />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(screen.getByTestId('probe')).toHaveTextContent('null');
    (global.fetch as jest.Mock).mockClear();
    rerender(<Probe enabled={false} />);
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
