/**
 * The review page's Suggestions tab (COL-4.2, #4526): render, suggest, apply, reject, stale.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ReviewSuggestionsPanel } from '../src/app/components/ade/reviews/ReviewSuggestionsPanel';
import type { ReviewSuggestion, SuggestionTarget } from '../lib/review-suggestions';

jest.mock('@/app/components/ui/code/JsonDiffViewer', () => ({
  JsonDiffViewer: ({ original, modified }: { original: string; modified: string }) =>
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('react').createElement('div', { 'data-testid': 'json-diff-viewer', 'data-original': original, 'data-modified': modified }),
}));

const TARGETS: SuggestionTarget[] = [
  { type: 'class', id: 'c1', label: 'Pet', element: { description: 'A pet', schema: { type: 'object' } } },
  { type: 'property', id: 'p1', label: 'Pet.name', element: { description: 'Name', data: { type: 'string', maxLength: 50 } } },
];

const suggestion = (over: Partial<ReviewSuggestion> = {}): ReviewSuggestion => ({
  id: 's1',
  review_id: 'r1',
  version_id: 'v1',
  author_id: 'rex',
  author_name: 'Rex',
  target_type: 'property',
  target_id: 'p1',
  target_label: 'Pet.name',
  note: 'Names can be longer',
  base: { description: 'Name', data: { type: 'string', maxLength: 50 } },
  patch: [{ op: 'replace', path: '/data/maxLength', value: 100 }],
  proposed: { description: 'Name', data: { type: 'string', maxLength: 100 } },
  status: 'open',
  conflict_paths: [],
  stale: false,
  decided_by: null,
  decided_by_name: null,
  decided_at: null,
  reason: null,
  created_at: '',
  ...over,
});

type Reply = { suggestions: ReviewSuggestion[]; canDecide: boolean };

function mockFetch(list: () => Reply, onPost: (url: string, body: unknown) => unknown = () => ({ success: true })) {
  const fetchMock = jest.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      return { json: async () => onPost(url, JSON.parse(String(init.body ?? '{}'))) } as Response;
    }
    return { json: async () => ({ success: true, targets: TARGETS, ...list() }) } as Response;
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

afterEach(() => jest.restoreAllMocks());

it('shows a suggestion as a diff with Apply and Reject for the requester', async () => {
  const fetchMock = mockFetch(() => ({ suggestions: [suggestion()], canDecide: true }));
  render(<ReviewSuggestionsPanel reviewId="r1" viewerId="rita" writable />);
  const item = await screen.findByTestId('suggestion-s1');
  expect(within(item).getByText('Pet.name')).toBeInTheDocument();
  expect(within(item).getByText('Names can be longer')).toBeInTheDocument();
  expect(within(item).getByTestId('json-diff-viewer').getAttribute('data-modified')).toContain('"maxLength": 100');
  fireEvent.click(within(item).getByRole('button', { name: 'Apply' }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/reviews/r1/suggestions/s1/apply', expect.objectContaining({ method: 'POST' })));
  expect(await screen.findByText('Applied to Pet.name.')).toBeInTheDocument();
});

it('lets the author withdraw but not apply', async () => {
  mockFetch(() => ({ suggestions: [suggestion()], canDecide: true }));
  render(<ReviewSuggestionsPanel reviewId="r1" viewerId="rex" writable />);
  const item = await screen.findByTestId('suggestion-s1');
  expect(within(item).queryByRole('button', { name: 'Apply' })).toBeNull();
  expect(within(item).getByRole('button', { name: 'Withdraw' })).toBeInTheDocument();
});

it('marks a stale suggestion and disables Apply', async () => {
  mockFetch(() => ({ suggestions: [suggestion({ stale: true, conflict_paths: ['data.maxLength'] })], canDecide: true }));
  render(<ReviewSuggestionsPanel reviewId="r1" viewerId="rita" writable />);
  const item = await screen.findByTestId('suggestion-s1');
  expect(within(item).getByText('Stale')).toBeInTheDocument();
  expect(within(item).getByText(/changed since: data\.maxLength/)).toBeInTheDocument();
  expect(within(item).getByRole('button', { name: 'Apply' })).toBeDisabled();
});

it('shows the server refusal when an apply goes stale', async () => {
  mockFetch(
    () => ({ suggestions: [suggestion()], canDecide: true }),
    () => ({ success: false, code: 'suggestion-stale', error: 'The element changed since this was suggested.' })
  );
  render(<ReviewSuggestionsPanel reviewId="r1" viewerId="rita" writable />);
  fireEvent.click(within(await screen.findByTestId('suggestion-s1')).getByRole('button', { name: 'Apply' }));
  expect(await screen.findByText('The element changed since this was suggested.')).toBeInTheDocument();
});

it('builds the patch from a field edit when a reviewer suggests', async () => {
  let posted: unknown = null;
  mockFetch(
    () => ({ suggestions: [], canDecide: false }),
    (url, body) => {
      posted = { url, body };
      return { success: true, suggestion: suggestion() };
    }
  );
  render(<ReviewSuggestionsPanel reviewId="r1" viewerId="rex" writable />);
  expect(await screen.findByText('No suggestions yet')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Element'), { target: { value: 'property:p1' } });
  fireEvent.change(screen.getByLabelText('Field'), { target: { value: 'maxLength' } });
  expect(screen.getByLabelText('New value')).toHaveValue('50');
  fireEvent.change(screen.getByLabelText('New value'), { target: { value: '100' } });
  fireEvent.change(screen.getByLabelText('Why (optional)'), { target: { value: 'Longer names' } });
  fireEvent.click(screen.getByRole('button', { name: 'Suggest' }));
  await waitFor(() =>
    expect(posted).toEqual({
      url: '/api/reviews/r1/suggestions',
      body: {
        target_type: 'property',
        target_id: 'p1',
        patch: [
          { op: 'test', path: '/data/maxLength', value: 50 },
          { op: 'replace', path: '/data/maxLength', value: 100 },
        ],
        note: 'Longer names',
      },
    })
  );
});

it('refuses a suggestion that changes nothing without calling the server', async () => {
  const fetchMock = mockFetch(() => ({ suggestions: [], canDecide: false }));
  render(<ReviewSuggestionsPanel reviewId="r1" viewerId="rex" writable />);
  await screen.findByText('No suggestions yet');
  fireEvent.click(screen.getByRole('button', { name: 'Suggest' }));
  expect(await screen.findByText(/That is the current value/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('hides the form and the actions on a withdrawn review', async () => {
  mockFetch(() => ({ suggestions: [suggestion()], canDecide: true }));
  render(<ReviewSuggestionsPanel reviewId="r1" viewerId="rita" writable={false} />);
  const item = await screen.findByTestId('suggestion-s1');
  expect(within(item).queryByRole('button', { name: 'Apply' })).toBeNull();
  expect(screen.queryByRole('form', { name: 'Suggest a change' })).toBeNull();
});
