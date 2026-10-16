/**
 * `StatusStrip` — one row of status chips, one open detail (HIVE-11.1, #5597).
 *
 * Pins the behaviour the ticket specifies: severity-first opening, exactly one detail row,
 * toggle / Collapse / Escape, the one-status and zero-status and loading shapes, the
 * accessibility contract, and session-only persistence (never `localStorage`).
 */

import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import {
  StatusStrip,
  readStoredStatus,
  resolveOpenStatus,
  severestStatusId,
  statusStripStorageKey,
  writeStoredStatus,
  type StatusStripItem,
} from '@/app/components/ui/StatusStrip';

const ITEMS: StatusStripItem[] = [
  { id: 'compat', tone: 'ok', label: 'Compatible', detail: 'v2.3.0 → v2.3.1', title: 'Compatible.', body: 'No breaking changes.' },
  { id: 'new', tone: 'accent', label: 'What’s new', title: 'What’s new in v2.4.0.' },
  {
    id: 'sunset',
    tone: 'warn',
    label: 'v2.2.0 deprecated',
    title: 'v2.2.0 is deprecated.',
    actions: <a href="#timeline">Sunset timeline</a>,
  },
];

/**
 * The chip button for a label.
 *
 * @param name The chip's accessible name (a prefix is enough).
 * @returns The button.
 */
function chip(name: RegExp) {
  return screen.getByRole('button', { name });
}

/**
 * Every detail row in the document — visible or hidden.
 *
 * @param container The render container.
 * @returns The rows.
 */
function details(container: HTMLElement) {
  return container.querySelectorAll('.status-strip__detail');
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
});

describe('severestStatusId', () => {
  it('ranks danger > warn > accent > ok', () => {
    expect(severestStatusId([{ id: 'a', tone: 'ok' }, { id: 'b', tone: 'accent' }])).toBe('b');
    expect(severestStatusId([{ id: 'a', tone: 'accent' }, { id: 'b', tone: 'warn' }])).toBe('b');
    expect(severestStatusId([{ id: 'a', tone: 'danger' }, { id: 'b', tone: 'warn' }])).toBe('a');
    expect(
      severestStatusId([
        { id: 'a', tone: 'ok' },
        { id: 'b', tone: 'danger' },
        { id: 'c', tone: 'warn' },
        { id: 'd', tone: 'accent' },
      ])
    ).toBe('b');
  });

  it('keeps the first of equals, and returns null for nothing', () => {
    expect(severestStatusId([{ id: 'a', tone: 'warn' }, { id: 'b', tone: 'warn' }])).toBe('a');
    expect(severestStatusId([])).toBeNull();
  });
});

describe('resolveOpenStatus', () => {
  it('follows severity with no choice, honours a choice, and honours "collapsed"', () => {
    expect(resolveOpenStatus(ITEMS, undefined)).toBe('sunset');
    expect(resolveOpenStatus(ITEMS, 'compat')).toBe('compat');
    expect(resolveOpenStatus(ITEMS, null)).toBeNull();
  });

  it('falls back to severity when the chosen status is gone', () => {
    expect(resolveOpenStatus(ITEMS, 'resolved-long-ago')).toBe('sunset');
  });
});

describe('StatusStrip — rendering', () => {
  it('opens the most severe chip on first paint, with exactly one detail row', () => {
    const { container } = render(<StatusStrip aria-label="Project status" items={ITEMS} />);
    expect(chip(/deprecated/)).toHaveAttribute('aria-expanded', 'true');
    expect(chip(/Compatible/)).toHaveAttribute('aria-expanded', 'false');
    expect(chip(/What’s new/)).toHaveAttribute('aria-expanded', 'false');
    expect(details(container)).toHaveLength(1);
    expect(details(container)[0]).toBeVisible();
    expect(details(container)[0]).toHaveAttribute('data-tone', 'warn');
    expect(screen.getByText('v2.2.0 is deprecated.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sunset timeline' })).toBeInTheDocument();
  });

  it('opens danger ahead of everything else', () => {
    render(
      <StatusStrip
        aria-label="Status"
        items={[...ITEMS, { id: 'break', tone: 'danger', label: 'Breaking', title: 'Breaking change.' }]}
      />
    );
    expect(chip(/Breaking/)).toHaveAttribute('aria-expanded', 'true');
  });

  it('draws the chip’s muted detail beside its label', () => {
    render(<StatusStrip aria-label="Status" items={ITEMS} />);
    expect(chip(/Compatible/)).toHaveTextContent('Compatiblev2.3.0 → v2.3.1');
  });

  it('renders nothing for zero statuses', () => {
    const { container } = render(<StatusStrip aria-label="Status" items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders one status already open and without Collapse', () => {
    const { container } = render(<StatusStrip aria-label="Status" items={[ITEMS[0]]} />);
    expect(chip(/Compatible/)).toHaveAttribute('aria-expanded', 'true');
    expect(screen.queryByRole('button', { name: /Collapse/ })).not.toBeInTheDocument();
    expect(details(container)[0]).toBeVisible();
  });

  it('renders one skeleton chip while loading', () => {
    const { container } = render(<StatusStrip aria-label="Status" items={ITEMS} loading />);
    expect(container.querySelectorAll('.status-strip__skeleton-chip')).toHaveLength(1);
    expect(container.querySelector('.status-strip')).toHaveAttribute('aria-busy', 'true');
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(screen.getByText('Loading status…')).toBeInTheDocument();
  });
});

describe('StatusStrip — interaction', () => {
  it('switches chips, keeping exactly one detail row', async () => {
    const user = userEvent.setup();
    const { container } = render(<StatusStrip aria-label="Status" items={ITEMS} />);
    await user.click(chip(/Compatible/));
    expect(chip(/Compatible/)).toHaveAttribute('aria-expanded', 'true');
    expect(chip(/deprecated/)).toHaveAttribute('aria-expanded', 'false');
    expect(details(container)).toHaveLength(1);
    expect(details(container)[0]).toHaveAttribute('data-tone', 'ok');
    expect(screen.getByText('Compatible.')).toBeInTheDocument();
    expect(screen.queryByText('v2.2.0 is deprecated.')).not.toBeInTheDocument();
  });

  it('collapses when the open chip is clicked, and from Collapse', async () => {
    const user = userEvent.setup();
    const { container } = render(<StatusStrip aria-label="Status" items={ITEMS} />);
    await user.click(chip(/deprecated/));
    expect(details(container)[0]).not.toBeVisible();
    expect(chip(/deprecated/)).toHaveAttribute('aria-expanded', 'false');
    // Nothing to collapse, so the button goes away.
    expect(screen.queryByRole('button', { name: /Collapse/ })).not.toBeInTheDocument();

    await user.click(chip(/What’s new/));
    await user.click(screen.getByRole('button', { name: /Collapse/ }));
    expect(details(container)[0]).not.toBeVisible();
  });

  it('is reachable by Tab, toggles with Enter and Space, and collapses on Escape', async () => {
    const user = userEvent.setup();
    const { container } = render(<StatusStrip aria-label="Status" items={ITEMS} />);

    await user.tab();
    expect(chip(/Compatible/)).toHaveFocus();
    await user.tab();
    expect(chip(/What’s new/)).toHaveFocus();
    await user.tab();
    expect(chip(/deprecated/)).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: /Collapse/ })).toHaveFocus();

    chip(/Compatible/).focus();
    await user.keyboard('{Enter}');
    expect(chip(/Compatible/)).toHaveAttribute('aria-expanded', 'true');
    await user.keyboard(' ');
    expect(chip(/Compatible/)).toHaveAttribute('aria-expanded', 'false');
    await user.keyboard(' ');
    expect(chip(/Compatible/)).toHaveAttribute('aria-expanded', 'true');

    await user.keyboard('{Escape}');
    expect(details(container)[0]).not.toBeVisible();
    expect(chip(/Compatible/)).toHaveFocus();
  });

  it('returns focus to the open chip when Escape is pressed inside the detail row', async () => {
    const user = userEvent.setup();
    render(<StatusStrip aria-label="Status" items={ITEMS} />);
    screen.getByRole('link', { name: 'Sunset timeline' }).focus();
    await user.keyboard('{Escape}');
    expect(chip(/deprecated/)).toHaveFocus();
    expect(chip(/deprecated/)).toHaveAttribute('aria-expanded', 'false');
  });

  it('ignores Escape when focus is outside the strip', () => {
    const { container } = render(
      <>
        <button type="button">Elsewhere</button>
        <StatusStrip aria-label="Status" items={ITEMS} />
      </>
    );
    fireEvent.keyDown(screen.getByRole('button', { name: 'Elsewhere' }), { key: 'Escape' });
    expect(details(container)[0]).toBeVisible();
  });
});

describe('StatusStrip — session persistence', () => {
  it('remembers the open chip per storageKey in sessionStorage, never localStorage', async () => {
    const user = userEvent.setup();
    const setItem = jest.spyOn(Storage.prototype, 'setItem');
    const { unmount } = render(<StatusStrip aria-label="Status" items={ITEMS} storageKey="versions:p1" />);
    await user.click(chip(/Compatible/));
    expect(window.sessionStorage.getItem(statusStripStorageKey('versions:p1'))).toBe('"compat"');
    expect(window.localStorage.length).toBe(0);
    for (const call of setItem.mock.contexts) expect(call).toBe(window.sessionStorage);
    unmount();

    render(<StatusStrip aria-label="Status" items={ITEMS} storageKey="versions:p1" />);
    expect(chip(/Compatible/)).toHaveAttribute('aria-expanded', 'true');
    setItem.mockRestore();
  });

  it('remembers "collapsed" too', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<StatusStrip aria-label="Status" items={ITEMS} storageKey="versions:p1" />);
    await user.click(screen.getByRole('button', { name: /Collapse/ }));
    expect(readStoredStatus('versions:p1')).toBeNull();
    unmount();

    const { container } = render(<StatusStrip aria-label="Status" items={ITEMS} storageKey="versions:p1" />);
    expect(details(container)[0]).not.toBeVisible();
  });

  it('writes and reads under a caller-owned prefix when one is given', async () => {
    const user = userEvent.setup();
    writeStoredStatus('p1', 'compat', 'hive.versions.status.');
    expect(window.sessionStorage.getItem('hive.versions.status.p1')).toBe('"compat"');
    expect(readStoredStatus('p1', 'hive.versions.status.')).toBe('compat');
    expect(readStoredStatus('p1')).toBeUndefined();

    render(<StatusStrip aria-label="Status" items={ITEMS} storageKey="p1" storagePrefix="hive.versions.status." />);
    expect(chip(/Compatible/)).toHaveAttribute('aria-expanded', 'true');
    await user.click(screen.getByRole('button', { name: /Collapse/ }));
    expect(window.sessionStorage.getItem('hive.versions.status.p1')).toBe('null');
    expect(window.sessionStorage.getItem(statusStripStorageKey('p1'))).toBeNull();
  });

  it('keeps each key separate', () => {
    writeStoredStatus('versions:p1', 'compat');
    render(<StatusStrip aria-label="Status" items={ITEMS} storageKey="versions:p2" />);
    expect(chip(/deprecated/)).toHaveAttribute('aria-expanded', 'true');
  });

  it('does not write anything until the reader chooses, or without a storageKey', async () => {
    const user = userEvent.setup();
    render(<StatusStrip aria-label="Status" items={ITEMS} />);
    await user.click(chip(/Compatible/));
    expect(window.sessionStorage.length).toBe(0);
  });

  it('treats unreadable or foreign values as "no choice"', () => {
    window.sessionStorage.setItem(statusStripStorageKey('k'), '{not json');
    expect(readStoredStatus('k')).toBeUndefined();
    window.sessionStorage.setItem(statusStripStorageKey('k'), '42');
    expect(readStoredStatus('k')).toBeUndefined();
    expect(readStoredStatus('missing')).toBeUndefined();
  });

  it('keeps working when storage throws', async () => {
    const user = userEvent.setup();
    const getItem = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    render(<StatusStrip aria-label="Status" items={ITEMS} storageKey="k" />);
    expect(chip(/deprecated/)).toHaveAttribute('aria-expanded', 'true');
    await user.click(chip(/Compatible/));
    expect(chip(/Compatible/)).toHaveAttribute('aria-expanded', 'true');
    getItem.mockRestore();
    setItem.mockRestore();
  });

  it('falls back to severity when the remembered chip is gone', async () => {
    writeStoredStatus('k', 'compat');
    await act(async () => {
      render(<StatusStrip aria-label="Status" items={ITEMS.slice(1)} storageKey="k" />);
    });
    expect(chip(/deprecated/)).toHaveAttribute('aria-expanded', 'true');
  });
});

describe('StatusStrip — accessibility', () => {
  it('groups the chips under the given name and wires them to one live detail row', () => {
    const { container } = render(<StatusStrip aria-label="Project status" items={ITEMS} />);
    const group = screen.getByRole('group', { name: 'Project status' });
    expect(group.querySelectorAll('button.status-chip')).toHaveLength(3);
    const detail = details(container)[0];
    expect(detail).toHaveAttribute('aria-live', 'polite');
    for (const button of group.querySelectorAll('button')) {
      expect(button).toHaveAttribute('aria-controls', detail.id);
      expect(button).toHaveAttribute('type', 'button');
    }
  });

  it.each([
    ['three statuses', ITEMS],
    ['one status', [ITEMS[0]]],
  ])('has no axe violations with %s', async (_label, items) => {
    const { container } = render(<StatusStrip aria-label="Project status" items={items} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no axe violations while loading', async () => {
    const { container } = render(<StatusStrip aria-label="Project status" items={[]} loading />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
