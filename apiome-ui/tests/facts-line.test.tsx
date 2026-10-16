/**
 * `FactsLine` — a stat strip folded into one line (HIVE-11.5, #5601).
 *
 * Pins reading order, the empty ("0 items") and loading lines, the Show/Hide stats toggle and
 * its ARIA wiring, and the per-page `hive.<page>.stats` persistence.
 */

import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import { FactsLine, type FactsLineFact } from '@/app/components/ui/FactsLine';

const FACTS: FactsLineFact[] = [
  { id: 'items', value: 3, label: 'items' },
  { id: 'formats', value: 2, label: 'formats', formats: ['graphql', 'asyncapi'] },
  { id: 'quality', label: 'avg quality', value: 'B · 83', labelFirst: true },
  { id: 'gone', label: '1 deleted · 1 disabled', muted: true },
];

const STATS = <div data-testid="stat-grid">grid</div>;

/**
 * The facts list.
 *
 * @returns The `<ul>`.
 */
function list() {
  return screen.getByRole('list', { name: 'Summary' });
}

beforeEach(() => {
  window.localStorage.clear();
  jest.restoreAllMocks();
});

describe('FactsLine — the line', () => {
  it('draws each fact as a list item, value first unless labelFirst', () => {
    render(<FactsLine page="catalog" facts={FACTS} />);
    const items = within(list()).getAllByRole('listitem');
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent('3 items');
    expect(items[0].querySelector('b')).toHaveTextContent('3');
    expect(items[2]).toHaveTextContent('avg quality B · 83');
    expect(items[3]).toHaveClass('facts__item--muted');
    expect(items[3].querySelector('b')).toBeNull();
  });

  it('draws inline format pills', () => {
    render(<FactsLine page="catalog" facts={FACTS} />);
    const pills = within(within(list()).getAllByRole('listitem')[1]).getAllByTestId('format-pill');
    expect(pills).toHaveLength(2);
  });

  it('reads "0 items" with no toggle when empty', () => {
    render(<FactsLine page="catalog" facts={FACTS} stats={STATS} empty />);
    const items = within(list()).getAllByRole('listitem');
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent('0 items');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('stat-grid')).not.toBeInTheDocument();
  });

  it('names the empty count with emptyLabel', () => {
    render(<FactsLine page="repos" facts={[]} empty emptyLabel="repositories" />);
    expect(list()).toHaveTextContent('0 repositories');
  });

  it('keeps the empty line empty even when stats were left expanded', () => {
    window.localStorage.setItem('hive.catalog.stats', '1');
    render(<FactsLine page="catalog" facts={FACTS} stats={STATS} empty />);
    expect(screen.queryByTestId('stat-grid')).not.toBeInTheDocument();
  });

  it('draws one skeleton while loading', () => {
    const { container } = render(<FactsLine page="catalog" facts={FACTS} loading />);
    expect(container.querySelectorAll('.facts__skeleton')).toHaveLength(1);
    expect(container.querySelector('.facts-line')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByText('Loading summary…')).toBeInTheDocument();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('has no toggle without a stats grid', () => {
    render(<FactsLine page="catalog" facts={FACTS} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('FactsLine — Show stats', () => {
  it('reveals and hides the grid in place, with aria-expanded and aria-controls', async () => {
    const user = userEvent.setup();
    render(<FactsLine page="catalog" facts={FACTS} stats={STATS} />);
    const toggle = screen.getByRole('button', { name: 'Show stats' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveAttribute('type', 'button');
    const region = document.getElementById(toggle.getAttribute('aria-controls')!);
    expect(region).not.toBeNull();
    expect(region).toContainElement(screen.getByTestId('stat-grid'));
    expect(region).not.toBeVisible();

    await user.click(toggle);
    expect(screen.getByRole('button', { name: 'Hide stats' })).toHaveAttribute('aria-expanded', 'true');
    expect(region).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Hide stats' }));
    expect(screen.getByRole('button', { name: 'Show stats' })).toHaveAttribute('aria-expanded', 'false');
    expect(region).not.toBeVisible();
  });

  it('toggles from the keyboard', async () => {
    const user = userEvent.setup();
    render(<FactsLine page="catalog" facts={FACTS} stats={STATS} />);
    await user.tab();
    expect(screen.getByRole('button', { name: 'Show stats' })).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('button', { name: 'Hide stats' })).toHaveAttribute('aria-expanded', 'true');
  });
});

describe('FactsLine — persistence', () => {
  it('remembers the expanded state per page in localStorage', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<FactsLine page="catalog" facts={FACTS} stats={STATS} />);
    await user.click(screen.getByRole('button', { name: 'Show stats' }));
    expect(window.localStorage.getItem('hive.catalog.stats')).toBe('1');
    unmount();

    render(<FactsLine page="catalog" facts={FACTS} stats={STATS} />);
    expect(screen.getByRole('button', { name: 'Hide stats' })).toBeInTheDocument();
  });

  it('remembers collapsing, and keeps pages apart', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem('hive.catalog.stats', '1');
    render(<FactsLine page="catalog" facts={FACTS} stats={STATS} />);
    await user.click(screen.getByRole('button', { name: 'Hide stats' }));
    expect(window.localStorage.getItem('hive.catalog.stats')).toBe('0');
    expect(window.localStorage.getItem('hive.members.stats')).toBeNull();
  });

  it('starts collapsed and keeps working when storage throws', async () => {
    const user = userEvent.setup();
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    render(<FactsLine page="catalog" facts={FACTS} stats={STATS} />);
    await user.click(screen.getByRole('button', { name: 'Show stats' }));
    expect(screen.getByRole('button', { name: 'Hide stats' })).toBeInTheDocument();
  });
});

describe('FactsLine — accessibility', () => {
  it.each([
    ['collapsed', false],
    ['empty', true],
  ])('has no axe violations (%s)', async (_label, empty) => {
    const { container } = render(<FactsLine page="catalog" facts={FACTS} stats={STATS} empty={empty} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no axe violations while loading', async () => {
    const { container } = render(<FactsLine page="catalog" facts={[]} loading />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
