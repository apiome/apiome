/**
 * Command palette providers (SUX-4.5, apiome#6770; apiome/private-suite#2904).
 *
 * A surface contributes groups to the one palette instead of mounting a second one. This
 * suite pins the three parts of that contract:
 *
 *  1. **The registry** — namespacing, replacement and cleanup (`commandPaletteProviders.ts`).
 *  2. **The model** — provider groups merge by `order`, and only command groups survive `>`.
 *  3. **The host** — a provider's rows render in the same list, filter, run, and a
 *     `prematched` row survives a query it does not spell; the session tells the provider
 *     what is typed.
 */

import React from 'react';
import { act, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { Sparkles } from 'lucide-react';

const mockPush = jest.fn<void, [string]>();

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn(), refresh: jest.fn() }),
  usePathname: () => '/ade/dashboard',
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock('@lib/db/project-pins', () => ({
  listPinnedProjectsForSession: () => Promise.resolve([]),
}));

import CommandPaletteHost from '../src/app/components/shell/CommandPaletteHost';
import { openCommandPalette } from '../src/app/components/shell/commandPaletteBus';
import {
  DEFAULT_PROVIDER_GROUP_ORDER,
  PALETTE_GROUP_ORDER,
  buildCommandGroups,
  type PaletteCommand,
  type PaletteCommandGroup,
} from '../src/app/components/shell/commandPaletteModel';
import {
  getCommandPaletteProviderGroups,
  getCommandPaletteSession,
  namespaceProviderGroups,
  registerCommandPaletteProvider,
  resetCommandPaletteProviders,
  resetCommandPaletteSession,
  useCommandPaletteProvider,
  useCommandPaletteSession,
} from '../src/app/components/shell/commandPaletteProviders';
import { getPlatformNavGroups } from '../lib/platform-nav';

/**
 * A provider row with the defaults a test does not care about.
 *
 * @param id The row id, before namespacing.
 * @param overrides Anything to change.
 * @returns The command.
 */
function command(id: string, overrides: Partial<PaletteCommand> = {}): PaletteCommand {
  return {
    id,
    group: 'g',
    label: id,
    icon: 'plus',
    disabled: false,
    keywords: [id],
    ...overrides,
  };
}

/**
 * A provider group.
 *
 * @param id The group id, before namespacing.
 * @param commands Its rows.
 * @param overrides Anything to change.
 * @returns The group.
 */
function group(
  id: string,
  commands: PaletteCommand[],
  overrides: Partial<PaletteCommandGroup> = {}
): PaletteCommandGroup {
  return { id, heading: id, commands, ...overrides };
}

beforeEach(() => {
  mockPush.mockReset();
  window.localStorage.clear();
  resetCommandPaletteProviders();
  resetCommandPaletteSession();
});

describe('the registry', () => {
  it('namespaces group and command ids with the provider id', () => {
    const [namespaced] = namespaceProviderGroups('git', [group('verbs', [command('commit')])]);

    expect(namespaced.id).toBe('git:verbs');
    expect(namespaced.commands[0].id).toBe('git:commit');
    expect(namespaced.commands[0].group).toBe('git:verbs');
  });

  it('replaces a provider registered again under the same id', () => {
    registerCommandPaletteProvider({ id: 'p', groups: [group('a', [command('one')])] });
    registerCommandPaletteProvider({ id: 'p', groups: [group('a', [command('two')])] });

    const groups = getCommandPaletteProviderGroups();
    expect(groups).toHaveLength(1);
    expect(groups[0].commands.map((row) => row.id)).toEqual(['p:two']);
  });

  it('ignores a stale cleanup, so a remount is not undone by the unmount before it', () => {
    const first = registerCommandPaletteProvider({ id: 'p', groups: [group('a', [command('one')])] });
    registerCommandPaletteProvider({ id: 'p', groups: [group('a', [command('two')])] });

    first();

    expect(getCommandPaletteProviderGroups()[0].commands[0].id).toBe('p:two');
  });

  it('keeps providers apart, in registration order, and removes one on cleanup', () => {
    const removeA = registerCommandPaletteProvider({ id: 'a', groups: [group('x', [command('one')])] });
    registerCommandPaletteProvider({ id: 'b', groups: [group('x', [command('one')])] });

    expect(getCommandPaletteProviderGroups().map((row) => row.id)).toEqual(['a:x', 'b:x']);

    removeA();
    expect(getCommandPaletteProviderGroups().map((row) => row.id)).toEqual(['b:x']);
  });

  it('registers for the life of a component through the hook', () => {
    const groups = [group('x', [command('one')])];
    const view = renderHook(() => useCommandPaletteProvider('hooked', groups));

    expect(getCommandPaletteProviderGroups().map((row) => row.id)).toEqual(['hooked:x']);
    view.unmount();
    expect(getCommandPaletteProviderGroups()).toEqual([]);
  });
});

describe('the model', () => {
  const navGroups = getPlatformNavGroups({ currentTenantId: 't-1' });

  it('places a provider group between Recent and Jump to by default', () => {
    const groups = buildCommandGroups({
      navGroups,
      currentTenantId: 't-1',
      recents: [{ id: 'r', label: 'R', href: '/ade/r', at: 1 }],
      providerGroups: namespaceProviderGroups('p', [group('mine', [command('one')])]),
    });

    expect(groups.map((row) => row.id)).toEqual(['recent', 'p:mine', 'jump', 'action']);
    expect(DEFAULT_PROVIDER_GROUP_ORDER).toBeGreaterThan(PALETTE_GROUP_ORDER.recent);
    expect(DEFAULT_PROVIDER_GROUP_ORDER).toBeLessThan(PALETTE_GROUP_ORDER.jump);
  });

  it('honours a provider order, and drops an empty provider group', () => {
    const groups = buildCommandGroups({
      navGroups,
      currentTenantId: 't-1',
      providerGroups: namespaceProviderGroups('p', [
        group('first', [command('one')], { order: 1 }),
        group('last', [command('two')], { order: 999 }),
        group('empty', []),
      ]),
    });

    expect(groups.map((row) => row.id)).toEqual(['p:first', 'jump', 'action', 'p:last']);
  });

  it('keeps only command groups when the reader types >', () => {
    const groups = buildCommandGroups({
      navGroups,
      currentTenantId: 't-1',
      commandsOnly: true,
      providerGroups: namespaceProviderGroups('p', [
        group('results', [command('hit')]),
        group('verbs', [command('run')], { keepInCommandsMode: true, order: 450 }),
      ]),
    });

    expect(groups.map((row) => row.id)).toEqual(['action', 'p:verbs']);
  });
});

/**
 * A provider that answers from the palette's query, the way a server search would.
 *
 * Rows are `prematched`: their labels never contain the query, so the fuzzy filter alone
 * would hide them.
 */
function SearchingProvider() {
  const { open, query } = useCommandPaletteSession();
  const groups = React.useMemo(
    () =>
      open && query.trim().length >= 2
        ? [
            group('results', [
              command('related', {
                label: 'Invoice billing',
                keywords: ['Invoice billing'],
                prematched: true,
              }),
            ]),
          ]
        : [],
    [open, query]
  );
  useCommandPaletteProvider('search', groups);
  return null;
}

describe('the host', () => {
  it('draws, filters and runs a provider row in the one palette', async () => {
    const run = jest.fn();
    const user = userEvent.setup();

    function Provider() {
      const groups = React.useMemo(
        () => [
          group(
            'canvas',
            [
              command('layout', {
                label: 'Auto-layout the canvas',
                keywords: ['layout', 'arrange'],
                run,
                keys: ['⇧', 'L'],
                iconComponent: Sparkles,
                detail: 'Re-flows the drawn nodes',
              }),
            ],
            { heading: 'Canvas' }
          ),
        ],
        []
      );
      useCommandPaletteProvider('designer', groups);
      return null;
    }

    render(
      <>
        <Provider />
        <CommandPaletteHost currentTenantId="t-1" />
      </>
    );

    await user.keyboard('{Meta>}k{/Meta}');
    const dialog = await screen.findByRole('dialog');

    // Exactly one palette, holding both the platform's rows and the provider's.
    expect(screen.getAllByRole('dialog')).toHaveLength(1);
    expect(within(dialog).getByTestId('palette-group-designer:canvas')).toHaveTextContent('Canvas');
    expect(within(dialog).getByTestId('palette-group-jump')).toBeInTheDocument();
    const row = within(dialog).getByTestId('palette-item-designer:layout');
    expect(row).toHaveAttribute('title', 'Re-flows the drawn nodes');

    await user.keyboard('arrange');
    expect(within(dialog).getByTestId('palette-item-designer:layout')).toBeInTheDocument();

    await user.click(within(dialog).getByTestId('palette-item-designer:layout'));
    expect(run).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('publishes the session, so a provider can search; prematched rows survive the filter', async () => {
    const user = userEvent.setup();
    render(
      <>
        <SearchingProvider />
        <CommandPaletteHost currentTenantId="t-1" />
      </>
    );

    expect(getCommandPaletteSession()).toEqual({ open: false, query: '' });

    await act(async () => {
      openCommandPalette({ query: 'cust' });
    });
    const dialog = await screen.findByRole('dialog');
    expect(getCommandPaletteSession()).toEqual({ open: true, query: 'cust' });

    // "Invoice billing" does not contain "cust" — it is shown because the provider said so.
    expect(await within(dialog).findByTestId('palette-item-search:related')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    await waitFor(() => expect(getCommandPaletteSession().open).toBe(false));
  });
});
