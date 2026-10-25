'use client';

import * as React from 'react';
import Link from 'next/link';
import { ChevronDown } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { ICON_SIZE, ICON_STROKE_WIDTH } from '@/app/components/ui/iconSizes';
import { cn } from '@lib/utils';
import {
  isPlatformNavItemActive,
  type PlatformNavGroupId,
  type ResolvedPlatformNavGroup,
  type ResolvedPlatformNavItem,
} from '@lib/platform-nav';
import { resolvePlatformNavIcon } from '@lib/platform-nav-icons';
import {
  defaultCollapsedNavGroups,
  readCollapsedNavGroups,
  toggleCollapsedNavGroup,
  writeCollapsedNavGroups,
} from './navGroupCollapse';
import { RAIL_ITEM_CLASS, RAIL_ITEM_HOVER_CLASS, RailTooltip } from './railChrome';

/**
 * The rail's grouped navigation (HIVE-3.1, #5287; `DESIGN.md` §5.2 and §6).
 *
 * Every destination comes from the model in `lib/platform-nav.ts` (HIVE-3.2), so this
 * component owns *chrome only*: the raised active pill, the 5 % hover tint, the folded
 * group, the tooltip an icon rail needs and the way a gated destination explains itself.
 * Adding a destination is a change to the model, never to this file.
 *
 * Three states a nav item can be in, and what each one is in the DOM:
 *
 * | State | Element | Announced as |
 * | --- | --- | --- |
 * | ordinary | `<a>` | a link |
 * | current page | `<a aria-current="page">` | "current page", plus the raised pill |
 * | workspace-gated | `<button aria-disabled>` | a disabled control, described by its reason |
 *
 * A gated item is a *focusable* button rather than an inert `<div>` on purpose: a disabled
 * `<div>` cannot be reached, so a keyboard reader never learns the destination exists, let
 * alone why it is unavailable (`DESIGN.md` §9).
 */

/** Props for {@link RailNav}. */
export interface RailNavProps {
  /** Groups from `getPlatformNavGroups()`, gating already resolved. */
  groups: readonly ResolvedPlatformNavGroup[];
  /** Current `usePathname()` value, for active state. */
  pathname: string | null;
  /**
   * Whether the rail is drawing icon-only right now.
   *
   * Two behaviours hang off it: names move into tooltips (they are no longer on screen),
   * and folded groups unfold — the heading that would fold them back is hidden, so leaving
   * a group folded would strand its destinations.
   */
  iconRail: boolean;
}

/**
 * One destination.
 *
 * @param props.item The resolved destination.
 * @param props.active Whether it is the current page.
 * @param props.iconRail Whether the rail is icon-only.
 * @returns The row, wrapped in a tooltip when something needs saying.
 */
function RailNavItem({
  item,
  active,
  iconRail,
}: {
  item: ResolvedPlatformNavItem;
  active: boolean;
  iconRail: boolean;
}) {
  const reasonId = `rail-nav-${item.id}-reason`;

  const label = (
    <span className="rail-label min-w-0 flex-1 items-center justify-between gap-2">
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
      {item.pill ? (
        <Badge variant="honey" className="shrink-0">
          {item.pill}
        </Badge>
      ) : null}
    </span>
  );

  // `createElement` rather than `<Icon />` from a local: the model names its glyph as a
  // string and `resolvePlatformNavIcon` *looks up* a module-level component — it does not
  // define one — so there is no per-render identity to reset. Spelling it this way also
  // keeps `react-hooks/static-components` from reading the lookup as a definition.
  const icon = React.createElement(resolvePlatformNavIcon(item.icon), {
    size: ICON_SIZE.rail,
    strokeWidth: ICON_STROKE_WIDTH,
    'aria-hidden': true,
    // `.rail-item__icon` (HIVE-14, `globals.css`) tints the glyph toward its group's hue, full
    // hue under the pointer and on the current page — read from the `data-area` the group
    // carries, so this row needs no colour of its own.
    className: 'rail-item__icon shrink-0 transition-colors duration-[var(--dur-fast)]',
  });

  const row = item.disabled ? (
    // Gated: focusable so it can be found and explained, but inert. `onClick` is not
    // needed — a button with no handler does nothing — yet the row is still marked
    // `aria-disabled` so assistive technology says so before the reason is read.
    <button
      type="button"
      aria-disabled="true"
      aria-describedby={item.disabledReason ? reasonId : undefined}
      data-testid={`rail-nav-${item.id}`}
      className={cn(RAIL_ITEM_CLASS, 'cursor-not-allowed text-fg-muted opacity-45')}
    >
      {icon}
      {label}
      {item.disabledReason ? (
        <span id={reasonId} className="sr-only">
          {item.disabledReason}
        </span>
      ) : null}
    </button>
  ) : (
    <Link
      href={item.href}
      aria-current={active ? 'page' : undefined}
      data-testid={`rail-nav-${item.id}`}
      target={item.external ? '_blank' : undefined}
      rel={item.external ? 'noreferrer' : undefined}
      className={cn(
        RAIL_ITEM_CLASS,
        RAIL_ITEM_HOVER_CLASS,
        // The current page (HIVE-14): `.rail-item--active` is the soft tint in the group's
        // hue with a 3 px bar; Home, which has no hue, keeps the raised white pill.
        active ? 'rail-item--active text-fg' : 'text-fg-muted'
      )}
    >
      {icon}
      {label}
    </Link>
  );

  // What the tooltip has to carry: the name, once the label is off screen; the reason,
  // whenever the destination is gated. Neither — no tooltip, because a tooltip repeating a
  // visible label is noise on every hover.
  const tip = [iconRail ? item.label : null, item.disabledReason ?? null]
    .filter(Boolean)
    .join(' — ');

  return (
    <RailTooltip label={tip} when={Boolean(tip)}>
      {row}
    </RailTooltip>
  );
}

/**
 * How a folded heading's count reads to a screen reader, after the group name: the bare
 * number on screen would be announced as "Workspace 5" with nothing to say what it counts.
 *
 * @param count Destinations in the folded group.
 * @returns e.g. `"5 destinations"`, so the heading reads "Workspace 5 destinations".
 */
export function railGroupCountLabel(count: number): string {
  return `${count} ${count === 1 ? 'destination' : 'destinations'}`;
}

/**
 * The rail's primary navigation.
 *
 * @param props See {@link RailNavProps}.
 * @returns A `<nav aria-label="Primary">` of grouped destinations.
 */
export default function RailNav({ groups, pathname, iconRail }: RailNavProps) {
  // The first render folds the model's defaults (HIVE-12.1): the same on the server and the
  // client, and already right for a reader who has never folded a group. Their stored folds
  // are read after mount, never during render — the server has no `localStorage`, so
  // reading one while rendering would hand React a tree the client cannot reproduce.
  const [folded, setFolded] = React.useState<PlatformNavGroupId[]>(() =>
    defaultCollapsedNavGroups(groups)
  );

  // Mount only: a later `groups` (a contributed destination arriving) must not undo a fold
  // the reader has just made, so the read uses the groups the rail first rendered.
  const mountGroups = React.useRef(groups);
  React.useEffect(() => {
    setFolded(readCollapsedNavGroups(mountGroups.current));
  }, []);

  const toggleGroup = React.useCallback((groupId: PlatformNavGroupId) => {
    setFolded((current) => {
      const next = toggleCollapsedNavGroup(current, groupId);
      writeCollapsedNavGroups(next);
      return next;
    });
  }, []);

  return (
    <nav
      aria-label="Primary"
      data-testid="rail-nav"
      // The rail scrolls on its own so a long nav never scrolls the page with it, and the
      // scrollbar is hidden because the rail is chrome: `scrollbar-width: none` still
      // scrolls by wheel, drag and keyboard.
      className="min-h-0 flex-1 space-y-1 overflow-y-auto overflow-x-hidden px-3 pb-4 [scrollbar-width:none]"
    >
      {groups.map((group) => {
        const listId = `rail-group-${group.id}`;
        // Icon mode ignores folds: the heading that would undo them is not on screen.
        const isFolded = !iconRail && folded.includes(group.id);

        return (
          // `data-area` is the group's hue (HIVE-14): the `[data-area]` rules in `globals.css`
          // set `--area` for the dot, the icons and the active row inside.
          <div key={group.id} className="rail-group pt-1" data-area={group.id}>
            {group.label ? (
              <button
                type="button"
                onClick={() => toggleGroup(group.id)}
                aria-expanded={!isFolded}
                aria-controls={listId}
                data-testid={`rail-group-toggle-${group.id}`}
                className={cn(
                  'rail-label group/heading h-6 w-full select-none items-center gap-1.5 rounded-sm px-2.5',
                  'text-2xs font-semibold uppercase tracking-[0.08em] text-fg-subtle',
                  'transition-colors duration-[var(--dur-fast)] hover:text-fg-muted'
                )}
              >
                <span className="rail-group__dot" aria-hidden />
                {group.label}
                {/* Folded only: an open group shows its rows, so a count would repeat them.
                    The heading is a `.rail-label`, so the icon rail hides it with the rest. */}
                {isFolded ? (
                  <span
                    data-testid={`rail-group-count-${group.id}`}
                    className="ml-auto font-mono font-normal tracking-normal tabular-nums text-fg-muted"
                  >
                    <span aria-hidden>{group.items.length}</span>
                    <span className="sr-only">{railGroupCountLabel(group.items.length)}</span>
                  </span>
                ) : null}
                <ChevronDown
                  size={ICON_SIZE.button}
                  aria-hidden
                  className={cn(
                    'opacity-0 transition-[opacity,transform] duration-[var(--dur-base)] group-hover/heading:opacity-80',
                    // Pushed right, unless the count already took the free space.
                    isFolded ? 'ml-1 rotate-[-90deg] opacity-80' : 'ml-auto'
                  )}
                />
              </button>
            ) : null}

            <ul id={listId} hidden={isFolded} className="m-0 list-none space-y-0.5 p-0">
              {group.items.map((item) => (
                <li key={item.id}>
                  <RailNavItem
                    item={item}
                    active={isPlatformNavItemActive(item, pathname)}
                    iconRail={iconRail}
                  />
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}
