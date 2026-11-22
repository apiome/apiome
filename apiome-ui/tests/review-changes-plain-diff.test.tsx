/**
 * The review / merge-request Changes tab's plain diff reads stored documents (COA-5.13, #7089).
 *
 * The two documents come from the `/spec?side=` routes, which now serve the document apiome-rest
 * keeps in the document store together with its digest. Pinned: both sides are requested, a
 * differing pair is handed to the diff viewer, and a pair with equal digests is called identical
 * without mounting the diff viewer at all.
 */

import React from 'react';
import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ReviewChangesPanel } from '../src/app/components/ade/reviews/ReviewChangesPanel';

jest.mock('@/app/components/ui/code/JsonDiffViewer', () => ({
  JsonDiffViewer: ({ original, modified }: { original: string; modified: string }) => (
    <div data-testid="mock-diff-viewer" data-original={original} data-modified={modified} />
  ),
}));

const CHANGES = {
  success: true,
  head: { id: 'head', label: '2.0.0' },
  baseline: { id: 'base', label: '1.0.0' },
  initialPublication: false,
  changes: [],
  counts: { total: 0 },
  maxSeverity: null,
  classifiedError: null,
};

/** What each `/spec?side=` answers. */
let sides: Record<string, unknown> = {};
let requested: string[] = [];

beforeEach(() => {
  requested = [];
  sides = {
    base: { success: true, spec: '{\n  "a": 1\n}', sha256: 'sha-base' },
    head: { success: true, spec: '{\n  "a": 2\n}', sha256: 'sha-head' },
  };
  global.fetch = jest.fn(async (input: unknown) => {
    const url = String(input);
    requested.push(url);
    const side = /side=(base|head)/.exec(url)?.[1];
    return { json: async () => (side ? sides[side] : CHANGES) };
  }) as unknown as typeof fetch;
});

async function openPlainDiff() {
  render(<ReviewChangesPanel reviewId="rv-1" />);
  fireEvent.click(await screen.findByTestId('review-view-plain'));
}

describe('the plain diff of two stored documents', () => {
  it('reads both sides and hands them to the diff viewer', async () => {
    await openPlainDiff();

    const viewer = await screen.findByTestId('mock-diff-viewer');
    expect(viewer).toHaveAttribute('data-original', '{\n  "a": 1\n}');
    expect(viewer).toHaveAttribute('data-modified', '{\n  "a": 2\n}');
    expect(requested).toEqual(
      expect.arrayContaining([
        '/api/reviews/rv-1/spec?side=base',
        '/api/reviews/rv-1/spec?side=head',
      ]),
    );
  });

  it('skips the diff when the digests are equal, and says the documents are identical', async () => {
    sides.head = { success: true, spec: '{\n  "a": 1\n}', sha256: 'sha-base' };
    await openPlainDiff();

    const identical = await screen.findByTestId('review-plain-diff-identical');
    expect(identical).toHaveTextContent('Identical documents');
    expect(identical).toHaveTextContent('v1.0.0');
    expect(screen.queryByTestId('mock-diff-viewer')).not.toBeInTheDocument();
  });

  it('still diffs when a side has no digest', async () => {
    sides.base = { success: true, spec: '{\n  "a": 1\n}', sha256: null };
    sides.head = { success: true, spec: '{\n  "a": 1\n}', sha256: null };
    await openPlainDiff();
    expect(await screen.findByTestId('mock-diff-viewer')).toBeInTheDocument();
  });

  it("shows the route's own message when a document cannot be read", async () => {
    sides.head = { success: false, error: 'The document store did not return the document.' };
    await openPlainDiff();
    expect(await screen.findByTestId('review-plain-diff-error')).toHaveTextContent(
      'The document store did not return the document.',
    );
  });
});
