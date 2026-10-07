/**
 * Live-region sentences and the LiveRegion primitive — HIVE-10.2 (#5338), DESIGN.md §9
 * "live regions for save state and async jobs".
 */

import React from 'react';
import { act, render, renderHook, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import {
  importJobAnnouncement,
  resultCountAnnouncement,
  saveStateAnnouncement,
  settledRepositoriesAnnouncement,
} from '../lib/a11y/announcements';
import { LiveRegion } from '../src/app/components/ui/LiveRegion';
import { useSettledRepositoriesAnnouncement } from '../src/app/hooks/useSettledRepositoriesAnnouncement';

describe('importJobAnnouncement', () => {
  it('names the state and whole steps only', () => {
    expect(importJobAnnouncement('Running', { completed: 3, total: 8 })).toBe('Import running: step 3 of 8');
  });

  it('leaves steps out until the job has planned them', () => {
    expect(importJobAnnouncement('Queued', { completed: 0, total: 0 })).toBe('Import queued');
    expect(importJobAnnouncement('Completed')).toBe('Import completed');
    expect(importJobAnnouncement('Failed', null)).toBe('Import failed');
  });

  it('says nothing without a state', () => {
    expect(importJobAnnouncement('  ')).toBe('');
  });
});

describe('settledRepositoriesAnnouncement', () => {
  const was = (entries: Array<[string, string]>) => new Map(entries);

  it('announces one repository that finished', () => {
    expect(
      settledRepositoriesAnnouncement(was([['r1', 'scanning']]), [{ id: 'r1', name: 'acme/api', status: 'ready' }]),
    ).toBe('acme/api is ready');
    expect(
      settledRepositoriesAnnouncement(was([['r1', 'pending']]), [{ id: 'r1', name: 'acme/api', status: 'error' }]),
    ).toBe('acme/api failed to scan');
  });

  it('counts several at once', () => {
    expect(
      settledRepositoriesAnnouncement(was([['a', 'scanning'], ['b', 'pending']]), [
        { id: 'a', name: 'a', status: 'ready' },
        { id: 'b', name: 'b', status: 'ready' },
      ]),
    ).toBe('2 repositories finished scanning');
  });

  it('ignores first loads, repositories still in flight, and ones that were never in flight', () => {
    expect(settledRepositoriesAnnouncement(new Map(), [{ id: 'a', name: 'a', status: 'ready' }])).toBe('');
    expect(settledRepositoriesAnnouncement(was([['a', 'pending']]), [{ id: 'a', name: 'a', status: 'scanning' }])).toBe(
      '',
    );
    expect(settledRepositoriesAnnouncement(was([['a', 'ready']]), [{ id: 'a', name: 'a', status: 'archived' }])).toBe('');
  });
});

describe('saveStateAnnouncement', () => {
  it.each([
    [{ saving: true, dirty: true }, 'Saving…'],
    [{ saving: false, dirty: true, failed: true }, 'Save failed'],
    [{ saving: false, dirty: true }, 'Unsaved changes'],
    [{ saving: false, dirty: false }, 'All changes saved'],
  ])('%j → %s', (state, sentence) => {
    expect(saveStateAnnouncement(state)).toBe(sentence);
  });
});

describe('resultCountAnnouncement', () => {
  it('counts results for a typed query', () => {
    expect(resultCountAnnouncement(0, 'zzz')).toBe('No results');
    expect(resultCountAnnouncement(1, 'pets')).toBe('1 result');
    expect(resultCountAnnouncement(12, 'p')).toBe('12 results');
  });

  it('stays silent for the default (empty-query) list', () => {
    expect(resultCountAnnouncement(9, '  ')).toBe('');
  });
});

describe('LiveRegion', () => {
  it('is a polite, atomic status region that is always mounted', () => {
    render(<LiveRegion message="" data-testid="live" />);
    const region = screen.getByTestId('live');
    expect(region).toHaveAttribute('role', 'status');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toHaveAttribute('aria-atomic', 'true');
    expect(region).toHaveClass('sr-only');
    expect(region).toBeEmptyDOMElement();
  });

  it('renders the message as its text, so a change is what gets announced', () => {
    const { rerender } = render(<LiveRegion message="Saving…" data-testid="live" />);
    expect(screen.getByTestId('live')).toHaveTextContent('Saving…');
    rerender(<LiveRegion message="All changes saved" data-testid="live" />);
    expect(screen.getByTestId('live')).toHaveTextContent('All changes saved');
  });

  it('is an alert when assertive', () => {
    render(<LiveRegion message="Save failed" politeness="assertive" data-testid="live" />);
    expect(screen.getByTestId('live')).toHaveAttribute('role', 'alert');
    expect(screen.getByTestId('live')).toHaveAttribute('aria-live', 'assertive');
  });

  it('has no axe violations', async () => {
    const { container } = render(<LiveRegion message="Import running: step 1 of 2" />);
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe('useSettledRepositoriesAnnouncement', () => {
  it('is silent on first load and announces a repository that settles on a later poll', () => {
    const scanning = [{ id: 'r1', name: 'acme/api', status: 'scanning' }];
    const { result, rerender } = renderHook(({ rows }) => useSettledRepositoriesAnnouncement(rows), {
      initialProps: { rows: scanning },
    });
    expect(result.current).toBe('');
    act(() => rerender({ rows: [{ id: 'r1', name: 'acme/api', status: 'ready' }] }));
    expect(result.current).toBe('acme/api is ready');
  });

  it('keeps the last sentence when a later poll changes nothing', () => {
    const { result, rerender } = renderHook(({ rows }) => useSettledRepositoriesAnnouncement(rows), {
      initialProps: { rows: [{ id: 'r1', name: 'a', status: 'pending' }] },
    });
    act(() => rerender({ rows: [{ id: 'r1', name: 'a', status: 'ready' }] }));
    act(() => rerender({ rows: [{ id: 'r1', name: 'a', status: 'ready' }] }));
    expect(result.current).toBe('a is ready');
  });
});
