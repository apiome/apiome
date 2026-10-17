'use client';

import * as React from 'react';
import Link from 'next/link';
import { Check, ChevronsUpDown } from 'lucide-react';
import { Input } from '@/app/components/ui/Input';
import { ICON_SIZE } from '@/app/components/ui/iconSizes';
import { cn } from '@lib/utils';
import {
  RAIL_MENU_ITEM_CLASS,
  RAIL_MENU_SEPARATOR_CLASS,
  RAIL_MENU_SURFACE_CLASS,
  useRailMenu,
} from './railMenu';

/**
 * `BreadcrumbSwitcher` — the last breadcrumb as a menu button (HIVE-11.3, #5599).
 *
 * Authority: `docs/mockups/proposals/versions-status-strip.html` annotation **1**
 * (`.crumb-switch` and `#project-switch`). A page about one object of a list — one project's
 * Versions — used to carry a `<select>` in its action cluster to move to a sibling. The
 * proposal moves that control to where the reader already looks for "where am I": the last
 * step of the trail becomes a button that opens a filtered menu of siblings.
 *
 * It is drawn by {@link import('./PageHeader').default PageHeader}'s `crumbSwitcher` slot,
 * in place of the last breadcrumb step.
 *
 * ### Keyboard
 *
 * - The trigger is `aria-haspopup="menu"`; **Enter** / **Space** open it with the filter
 *   focused. Typing filters (name, then `keywords`); **Enter** in the filter switches to the
 *   first match; **↓** / **↑** move into the list.
 * - In the list, **↑** / **↓** / **Home** / **End** move, **Enter** switches, and a printable key
 *   goes back to the filter and is typed there — the menu's typeahead.
 * - **Esc** closes from anywhere inside and returns focus to the trigger; so does switching.
 *
 * The keyboard and dismissal model is the rail's (`railMenu.tsx`): the filter field sits
 * *outside* the `role="menu"` element, because a `searchbox` is not a permitted child of a
 * menu (axe `aria-required-children`).
 */

/** One sibling the switcher offers. */
export interface BreadcrumbSwitcherItem {
  /** Stable id; what {@link BreadcrumbSwitcherProps.onSelect} receives. */
  id: string;
  /** The name the reader sees and filters on. */
  label: string;
  /** Something drawn before the name — a format pill. */
  leading?: React.ReactNode;
  /** Extra text the filter matches but nobody sees — a slug. */
  keywords?: string;
}

/** The link under the list that leaves for the whole collection. */
export interface BreadcrumbSwitcherFooter {
  /** e.g. `"All projects"`. */
  label: string;
  /** Where it goes. */
  href: string;
  /** Optional glyph before the label. */
  icon?: React.ReactNode;
}

/** Props for {@link BreadcrumbSwitcher}. */
export interface BreadcrumbSwitcherProps {
  /** The trigger's text — the current object's name. */
  label: string;
  /** The siblings, in display order. */
  items: readonly BreadcrumbSwitcherItem[];
  /** Which item is current (checked). */
  currentId: string | null;
  /** Switch to an item. Not called for the current one. */
  onSelect: (id: string) => void;
  /** The trigger's tooltip and the first half of its accessible description, e.g. `"Switch project"`. */
  triggerTitle: string;
  /** The menu's accessible name, e.g. `"Projects"`. */
  menuLabel: string;
  /** The filter's accessible name, e.g. `"Jump to project"`. */
  searchLabel: string;
  /** The filter's placeholder, e.g. `"Jump to project…"`. */
  searchPlaceholder: string;
  /** What an empty filter result says, e.g. `"No matching projects"`. */
  emptyLabel: string;
  /** Optional link under the list. */
  footer?: BreadcrumbSwitcherFooter;
  /** `data-testid` root; the trigger, menu, filter and items derive theirs from it. */
  testId?: string;
}

/**
 * The items whose label or keywords contain every word of the query, case-insensitively.
 *
 * @param items The siblings.
 * @param query What the reader typed; blank keeps everything.
 * @returns The matching items, in their original order.
 */
export function filterBreadcrumbSwitcherItems<T extends BreadcrumbSwitcherItem>(
  items: readonly T[],
  query: string,
): T[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [...items];
  return items.filter((item) => {
    const haystack = `${item.label} ${item.keywords ?? ''}`.toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
}

/**
 * The switcher. See {@link BreadcrumbSwitcherProps}.
 *
 * @returns The trigger and, while open, its menu.
 */
export function BreadcrumbSwitcher({
  label,
  items,
  currentId,
  onSelect,
  triggerTitle,
  menuLabel,
  searchLabel,
  searchPlaceholder,
  emptyLabel,
  footer,
  testId = 'crumb-switch',
}: BreadcrumbSwitcherProps) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState('');
  const searchRef = React.useRef<HTMLInputElement | null>(null);
  const menuId = React.useId();

  const close = React.useCallback(() => {
    setOpen(false);
    setQuery('');
  }, []);

  const {
    anchorRef,
    triggerRef,
    menuRef,
    closeMenu,
    onMenuKeyDown,
    focusFirstItem,
    focusLastItem,
    itemTabIndex,
    onItemFocus,
  } = useRailMenu({ open, onClose: close });

  const filtered = React.useMemo(() => filterBreadcrumbSwitcherItems(items, query), [items, query]);

  /**
   * Switch to an item and put the menu away, focus back on the trigger.
   *
   * @param id The chosen item.
   */
  const choose = (id: string) => {
    closeMenu(true);
    if (id !== currentId) onSelect(id);
  };

  /**
   * The list's keys: the rail menu's arrows, plus typeahead — a printable key goes back to
   * the filter and is typed there.
   *
   * @param event The keydown on the `role="menu"` element.
   */
  const onListKeyDown = (event: React.KeyboardEvent) => {
    if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey && event.key !== ' ') {
      event.preventDefault();
      setQuery((current) => current + event.key);
      searchRef.current?.focus();
      return;
    }
    onMenuKeyDown(event);
  };

  return (
    <div ref={anchorRef} className="crumb-switch__anchor">
      <button
        ref={triggerRef}
        type="button"
        className="crumb-switch"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-current="page"
        title={triggerTitle}
        data-testid={testId}
        onClick={() => (open ? closeMenu(false) : setOpen(true))}
      >
        <span className="crumb-switch__label">{label}</span>
        <span className="sr-only"> — {triggerTitle.toLowerCase()}</span>
        <ChevronsUpDown aria-hidden />
      </button>

      {open ? (
        <div className={cn(RAIL_MENU_SURFACE_CLASS, 'crumb-switch__menu')} data-testid={`${testId}-menu`}>
          <div className="crumb-switch__search">
            <Input
              ref={searchRef}
              type="search"
              autoComplete="off"
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'ArrowDown') {
                  event.preventDefault();
                  focusFirstItem();
                } else if (event.key === 'ArrowUp') {
                  event.preventDefault();
                  focusLastItem();
                } else if (event.key === 'Enter') {
                  event.preventDefault();
                  if (filtered[0]) choose(filtered[0].id);
                }
              }}
              placeholder={searchPlaceholder}
              aria-label={searchLabel}
              aria-controls={menuId}
              data-testid={`${testId}-search`}
            />
          </div>

          {/* Outside the menu: a paragraph is not a permitted child of `role="menu"`, and a
              menu left with no items at all fails axe `aria-required-children`. */}
          {filtered.length === 0 ? <p className="crumb-switch__empty">{emptyLabel}</p> : null}

          {filtered.length > 0 || footer ? (
            <div
              ref={menuRef}
              id={menuId}
              role="menu"
              aria-label={menuLabel}
              onKeyDown={onListKeyDown}
              className="crumb-switch__list"
            >
              {filtered.length === 0 ? null : (
                <div role="none" className="crumb-switch__items">
                  {filtered.map((item, index) => {
                    const isCurrent = item.id === currentId;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="menuitemradio"
                        aria-checked={isCurrent}
                        tabIndex={itemTabIndex(index)}
                        onFocus={() => onItemFocus(index)}
                        onClick={() => choose(item.id)}
                        className={cn(RAIL_MENU_ITEM_CLASS, isCurrent && 'crumb-switch__item--current')}
                        data-testid={`${testId}-option-${item.id}`}
                      >
                        {item.leading}
                        <span className="crumb-switch__item-label">{item.label}</span>
                        {isCurrent ? (
                          <Check size={ICON_SIZE.dense} className="crumb-switch__check" aria-hidden />
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              )}

              {footer ? (
                <>
                  {filtered.length > 0 ? <div role="none" className={RAIL_MENU_SEPARATOR_CLASS} /> : null}
                  <Link
                    href={footer.href}
                    role="menuitem"
                    tabIndex={itemTabIndex(filtered.length)}
                    onFocus={() => onItemFocus(filtered.length)}
                    onClick={() => closeMenu(false)}
                    className={RAIL_MENU_ITEM_CLASS}
                    data-testid={`${testId}-footer`}
                  >
                    {footer.icon}
                    {footer.label}
                  </Link>
                </>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default BreadcrumbSwitcher;
