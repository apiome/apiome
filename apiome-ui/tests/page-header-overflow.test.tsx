/**
 * `PageHeader`'s HIVE-11.3 slots (#5599): the ⋯ `overflow` menu, `primaryAction`, and the
 * `crumbSwitcher` that replaces the breadcrumb's last step — plus `BreadcrumbSwitcher`'s own
 * keyboard model and filter.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';
import { jest } from '@jest/globals';
import { GitMerge, Link2 } from 'lucide-react';

jest.mock('next/link', () => ({
  __esModule: true,
  default: React.forwardRef<HTMLAnchorElement, { href: string; children: React.ReactNode }>(function MockLink(
    { href, children, ...rest },
    ref,
  ) {
    return (
      <a ref={ref} href={href} {...rest}>
        {children}
      </a>
    );
  }),
}));

import { Button } from '@/app/components/ui/Button';
import PageHeader from '@/app/components/shell/PageHeader';
import {
  BreadcrumbSwitcher,
  filterBreadcrumbSwitcherItems,
  type BreadcrumbSwitcherProps,
} from '@/app/components/shell/BreadcrumbSwitcher';
import type { PageHeaderOverflowItem } from '@/app/components/shell/PageHeaderOverflow';

const CRUMBS = [
  { label: 'Home', href: '/home' },
  { label: 'Projects', href: '/projects' },
  { label: 'Payments API' },
];

const ITEMS = [
  { id: 'p1', label: 'Payments API', keywords: 'payments-api' },
  { id: 'p2', label: 'Orders Service', keywords: 'orders-service' },
  { id: 'p3', label: 'Inventory Events', keywords: 'inventory' },
];

/** Opens a Radix dropdown from its trigger (jsdom does not synthesise `pointerdown`). */
function openOverflow() {
  fireEvent.keyDown(screen.getByTestId('page-header-overflow'), {
    key: 'Enter',
  });
  return screen.findByTestId('page-header-overflow-menu');
}

/** A switcher with sensible copy and a spy. */
function Switcher(props: Partial<BreadcrumbSwitcherProps>) {
  return (
    <BreadcrumbSwitcher
      label="Payments API"
      items={ITEMS}
      currentId="p1"
      onSelect={() => undefined}
      triggerTitle="Switch project"
      menuLabel="Projects"
      searchLabel="Jump to project"
      searchPlaceholder="Jump to project…"
      emptyLabel="No matching projects"
      footer={{ label: 'All projects', href: '/projects' }}
      {...props}
    />
  );
}

describe('PageHeader overflow and primary action', () => {
  const merge = jest.fn();
  const copy = jest.fn();
  const items: PageHeaderOverflowItem[] = [
    {
      id: 'merge',
      label: 'Merge branches…',
      icon: GitMerge,
      onSelect: merge,
      disabledReason: 'Needs two branches',
      badge: 'gitlike',
    },
    { id: 'published', label: 'Published surface', href: '/published' },
    {
      id: 'guide',
      label: 'Guide',
      href: 'https://example.com',
      external: true,
    },
    {
      id: 'copy',
      label: 'Copy link',
      icon: Link2,
      onSelect: copy,
      kbd: ['⌘', '⇧', 'C'],
      separatorBefore: true,
    },
  ];

  beforeEach(() => {
    merge.mockClear();
    copy.mockClear();
  });

  it('draws secondaries, then ⋯, then the primary action', () => {
    render(
      <PageHeader
        title="Payments API"
        actions={<Button variant="outline">Compare</Button>}
        overflow={{ items }}
        primaryAction={<Button>New version</Button>}
      />,
    );
    const names = within(screen.getByTestId('page-header-actions'))
      .getAllByRole('button')
      .map((button) => button.getAttribute('aria-label') ?? button.textContent);
    expect(names).toEqual(['Compare', 'More actions', 'New version']);
  });

  it('draws no ⋯ button for an empty overflow, and still draws a lone primary action', () => {
    render(<PageHeader title="X" overflow={{ items: [] }} primaryAction={<Button>New</Button>} />);
    expect(screen.queryByTestId('page-header-overflow')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New' })).toBeInTheDocument();
  });

  it('counts a primary passed as primaryAction toward the one-primary rule', () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    render(<PageHeader title="X" actions={<Button>One</Button>} primaryAction={<Button>Two</Button>} />);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('2 primary actions'));
    warn.mockRestore();
  });

  it('renders links, commands, a heading, a separator, chord chips and an outline badge', async () => {
    render(<PageHeader title="X" overflow={{ items, heading: 'This project', label: 'Project actions' }} />);
    expect(screen.getByTestId('page-header-overflow')).toHaveAccessibleName('Project actions');
    const menu = await openOverflow();
    expect(within(menu).getByText('This project')).toHaveClass('page-header__menu-label');
    expect(within(menu).getByTestId('page-header-overflow-published')).toHaveAttribute('href', '/published');
    const guide = within(menu).getByTestId('page-header-overflow-guide');
    expect(guide).toHaveAttribute('target', '_blank');
    expect(guide).toHaveAttribute('rel', 'noopener noreferrer');
    expect(within(menu).getAllByRole('separator')).toHaveLength(1);
    expect(within(menu).getByTestId('page-header-overflow-copy')).toHaveTextContent('⌘⇧C');
    expect(within(menu).getByText('gitlike')).toHaveClass('page-header__menu-badge');

    fireEvent.click(within(menu).getByTestId('page-header-overflow-copy'));
    expect(copy).toHaveBeenCalledTimes(1);
  });

  it('keeps an unavailable row reachable, states why, and does nothing when chosen', async () => {
    render(<PageHeader title="X" overflow={{ items }} />);
    const menu = await openOverflow();
    const row = within(menu).getByTestId('page-header-overflow-merge');
    expect(row).toHaveAttribute('aria-disabled', 'true');
    expect(row).not.toHaveAttribute('data-disabled');
    expect(row).toHaveAttribute('title', 'Needs two branches');
    expect(row).toHaveAccessibleName(expect.stringContaining('Needs two branches'));
    fireEvent.click(row);
    expect(merge).not.toHaveBeenCalled();
    // The menu stays open, so the reader can pick something else.
    expect(screen.getByTestId('page-header-overflow-menu')).toBeInTheDocument();
  });

  it('has no axe violations with the menu open', async () => {
    const { container } = render(<PageHeader title="X" breadcrumb={CRUMBS} overflow={{ items }} />);
    await openOverflow();
    // `region` is about a whole page's landmarks; this test mounts a header alone, and the
    // menu portals to `<body>` outside it.
    expect(
      await axe(container.ownerDocument.body, {
        rules: { region: { enabled: false } },
      }),
    ).toHaveNoViolations();
  });
});

describe('PageHeader crumbSwitcher', () => {
  it('replaces the last breadcrumb step and keeps the rest of the trail', () => {
    render(<PageHeader title="Payments API" breadcrumb={CRUMBS} crumbSwitcher={<Switcher />} />);
    const trail = screen.getByTestId('page-breadcrumb');
    expect(within(trail).getByRole('link', { name: 'Projects' })).toHaveAttribute('href', '/projects');
    const trigger = within(trail).getByTestId('crumb-switch');
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveAttribute('aria-current', 'page');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(within(trail).getAllByText('Payments API')).toHaveLength(1);
  });
});

describe('BreadcrumbSwitcher', () => {
  it('filters on every word of the query, across label and keywords', () => {
    expect(filterBreadcrumbSwitcherItems(ITEMS, '').map((i) => i.id)).toEqual(['p1', 'p2', 'p3']);
    expect(filterBreadcrumbSwitcherItems(ITEMS, 'ORD').map((i) => i.id)).toEqual(['p2']);
    expect(filterBreadcrumbSwitcherItems(ITEMS, 'service orders').map((i) => i.id)).toEqual(['p2']);
    expect(filterBreadcrumbSwitcherItems(ITEMS, 'inventory').map((i) => i.id)).toEqual(['p3']);
    expect(filterBreadcrumbSwitcherItems(ITEMS, 'nothing')).toEqual([]);
  });

  it('opens with the filter focused, checks the current item and offers the footer link', () => {
    render(<Switcher />);
    fireEvent.click(screen.getByTestId('crumb-switch'));
    expect(screen.getByTestId('crumb-switch')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('searchbox', { name: 'Jump to project' })).toHaveFocus();
    const menu = screen.getByRole('menu', { name: 'Projects' });
    const options = within(menu).getAllByRole('menuitemradio');
    expect(options.map((o) => o.getAttribute('aria-checked'))).toEqual(['true', 'false', 'false']);
    expect(within(menu).getByRole('menuitem', { name: 'All projects' })).toHaveAttribute('href', '/projects');
  });

  it('moves with the arrows, switches with Enter and returns focus to the trigger', () => {
    const onSelect = jest.fn();
    render(<Switcher onSelect={onSelect} />);
    const trigger = screen.getByTestId('crumb-switch');
    fireEvent.click(trigger);
    const search = screen.getByRole('searchbox', { name: 'Jump to project' });
    fireEvent.keyDown(search, { key: 'ArrowDown' });
    const menu = screen.getByRole('menu', { name: 'Projects' });
    expect(screen.getByTestId('crumb-switch-option-p1')).toHaveFocus();
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    expect(screen.getByTestId('crumb-switch-option-p2')).toHaveFocus();
    fireEvent.keyDown(menu, { key: 'End' });
    expect(screen.getByTestId('crumb-switch-footer')).toHaveFocus();
    fireEvent.keyDown(menu, { key: 'Home' });
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    // Enter on a focused button is its click.
    fireEvent.click(screen.getByTestId('crumb-switch-option-p2'));
    expect(onSelect).toHaveBeenCalledWith('p2');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('sends a printable key from the list back to the filter (typeahead)', () => {
    render(<Switcher />);
    fireEvent.click(screen.getByTestId('crumb-switch'));
    fireEvent.keyDown(screen.getByRole('searchbox'), { key: 'ArrowDown' });
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'i' });
    const search = screen.getByRole('searchbox');
    expect(search).toHaveFocus();
    expect(search).toHaveValue('i');
    expect(
      within(screen.getByRole('menu'))
        .getAllByRole('menuitemradio')
        .map((o) => o.textContent),
    ).toEqual(['Payments API', 'Orders Service', 'Inventory Events']);
  });

  it('closes on Escape and restores focus, without switching', () => {
    const onSelect = jest.fn();
    render(<Switcher onSelect={onSelect} />);
    const trigger = screen.getByTestId('crumb-switch');
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole('searchbox'), { key: 'Escape' });
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('does not call onSelect for the current item, and Enter in the filter picks the first match', () => {
    const onSelect = jest.fn();
    render(<Switcher onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId('crumb-switch'));
    fireEvent.click(screen.getByTestId('crumb-switch-option-p1'));
    expect(onSelect).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('crumb-switch'));
    const search = screen.getByRole('searchbox');
    fireEvent.change(search, { target: { value: 'inv' } });
    fireEvent.keyDown(search, { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledWith('p3');
  });

  it('says so when nothing matches, outside the menu, and keeps the footer reachable', () => {
    render(<Switcher />);
    fireEvent.click(screen.getByTestId('crumb-switch'));
    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: 'zzz' },
    });
    const empty = screen.getByText('No matching projects');
    const menu = screen.getByRole('menu');
    expect(menu).not.toContainElement(empty);
    expect(within(menu).queryAllByRole('menuitemradio')).toHaveLength(0);
    expect(within(menu).getByRole('menuitem', { name: 'All projects' })).toBeInTheDocument();
  });

  it('closes when a click lands outside', async () => {
    render(
      <>
        <Switcher />
        <button type="button">elsewhere</button>
      </>,
    );
    fireEvent.click(screen.getByTestId('crumb-switch'));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    await act(async () => {
      fireEvent.pointerDown(screen.getByRole('button', { name: 'elsewhere' }));
    });
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
  });

  it('has no axe violations open', async () => {
    const { container } = render(
      <PageHeader title="Payments API" breadcrumb={CRUMBS} crumbSwitcher={<Switcher />} />,
    );
    fireEvent.click(screen.getByTestId('crumb-switch'));
    expect(await axe(container)).toHaveNoViolations();
  });
});
