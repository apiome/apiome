/**
 * COA-5.6 (#7082): a comparison that waits on a first render says so.
 *
 * Diffs and compatibility checks read each side's document from the document store; the first
 * read of a revision renders it. `ColdRenderNote` appears when the wait outlasts
 * `COLD_RENDER_NOTE_DELAY_MS`, inside `LoadingState` (the merge request / review Changes tab) or
 * as its own live region (the versions page's merge compatibility check).
 */

import * as React from 'react';
import { act, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  COLD_RENDER_NOTE_DELAY_MS,
  COLD_RENDER_NOTE_TEXT,
  ColdRenderNote,
} from '../src/app/components/ui/ColdRenderNote';
import { LoadingState } from '../src/app/components/ui/LoadingState';
import { ReviewChangesPanel } from '../src/app/components/ade/reviews/ReviewChangesPanel';

jest.mock('@/app/components/ui/code/JsonDiffViewer', () => ({ JsonDiffViewer: () => null }));

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

/** Move the fake clock forward inside `act`. */
function advance(ms: number) {
  act(() => {
    jest.advanceTimersByTime(ms);
  });
}

describe('ColdRenderNote', () => {
  it('stays hidden while the wait is short, then names the first render', () => {
    render(<ColdRenderNote />);
    expect(screen.queryByTestId('cold-render-note')).not.toBeInTheDocument();

    advance(COLD_RENDER_NOTE_DELAY_MS - 1);
    expect(screen.queryByTestId('cold-render-note')).not.toBeInTheDocument();

    advance(1);
    const note = screen.getByTestId('cold-render-note');
    expect(note).toHaveTextContent(COLD_RENDER_NOTE_TEXT);
    expect(note).toHaveClass('cold-render-note');
  });

  it('is not shown when the wait ends before the delay', () => {
    const { unmount } = render(<ColdRenderNote />);
    advance(COLD_RENDER_NOTE_DELAY_MS / 2);
    unmount();
    advance(COLD_RENDER_NOTE_DELAY_MS);
    expect(screen.queryByTestId('cold-render-note')).not.toBeInTheDocument();
  });

  it('is its own polite live region only when standalone', () => {
    render(<ColdRenderNote standalone delayMs={0} />);
    advance(0);
    const note = screen.getByRole('status');
    expect(note).toHaveAttribute('aria-live', 'polite');
  });

  it('inside a LoadingState adds no second live region', () => {
    render(
      <LoadingState
        message="Comparing with the merge base…"
        detail={<ColdRenderNote delayMs={0} />}
      />,
    );
    advance(0);
    expect(screen.getAllByRole('status')).toHaveLength(1);
    expect(screen.getByRole('status')).toHaveTextContent(COLD_RENDER_NOTE_TEXT);
  });
});

describe('LoadingState detail', () => {
  it('renders the detail under the message', () => {
    render(
      <LoadingState
        message="Building both documents…"
        detail={<span data-testid="detail">more</span>}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Building both documents…');
    expect(screen.getByTestId('detail')).toBeInTheDocument();
  });
});

describe('Changes tab on a cold render', () => {
  it('keeps comparing and adds the note once the wait runs long', () => {
    // A comparison that has not answered yet: the REST diff is rendering both documents.
    const pending = jest.fn(() => new Promise<Response>(() => {}));
    global.fetch = pending as unknown as typeof fetch;

    render(
      <ReviewChangesPanel routeBase="/api/merge-requests/mr-1" baselineRole="the merge base" />,
    );
    const loading = screen.getByTestId('review-changes-loading');
    expect(loading).toHaveTextContent('Comparing with the merge base…');
    expect(screen.queryByTestId('cold-render-note')).not.toBeInTheDocument();

    advance(COLD_RENDER_NOTE_DELAY_MS);
    expect(screen.getByTestId('review-changes-loading')).toHaveTextContent(COLD_RENDER_NOTE_TEXT);
    expect(pending).toHaveBeenCalledWith('/api/merge-requests/mr-1/changes');
  });
});
