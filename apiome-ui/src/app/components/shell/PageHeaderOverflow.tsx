'use client';

import * as React from 'react';
import Link from 'next/link';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Ellipsis, type LucideIcon } from 'lucide-react';
import { Button } from '@/app/components/ui/Button';
import { Kbd } from '@/app/components/ui/Kbd';
import { cn } from '@lib/utils';

/**
 * The page header's ⋯ overflow menu (HIVE-11.3, #5599).
 *
 * Authority: `docs/mockups/proposals/versions-status-strip.html` annotation **2**
 * (`#more-menu`) and DESIGN.md §1.2 — *one primary, secondaries, overflow*. A header keeps
 * its primary action and at most two secondaries in sight; everything else a page can do to
 * the object it is about lives here, one click away.
 *
 * Rows are data ({@link PageHeaderOverflowItem}), not children, so the header can count
 * them and the rules below hold for every page:
 *
 * - A row is a link (`href`, optionally `external`) or a command (`onSelect`).
 * - **An unavailable row keeps its place and says why.** It is `aria-disabled` rather than
 *   Radix-`disabled` — a disabled Radix item leaves the arrow-key order, so the reader who
 *   most needs the reason could never reach it — and its `disabledReason` is part of its
 *   accessible name as well as its tooltip. Selecting it does nothing and keeps the menu open.
 * - A row behind a feature flag carries a quiet outline `badge` (`gitlike`), never the
 *   honey flag: honey is a brand mark (DESIGN.md §2), and the header no longer draws one.
 * - `kbd` prints the row's chord, which the page registers with the shortcut engine.
 *
 * Radix owns focus: arrow keys and typeahead move between rows, Enter selects, Esc closes
 * and returns focus to the ⋯ button.
 */

/** One row of the overflow menu. */
export interface PageHeaderOverflowItem {
  /** Stable id; the row's `data-testid` is `page-header-overflow-<id>`. */
  id: string;
  /** What the row says. */
  label: string;
  /** Optional glyph before the label. */
  icon?: LucideIcon;
  /** A link row: where it goes. */
  href?: string;
  /** Open `href` in a new tab (adds `rel="noopener noreferrer"`). */
  external?: boolean;
  /** A command row: what it does. */
  onSelect?: () => void;
  /** Why the row cannot be used right now. Set, the row is unavailable. */
  disabledReason?: string;
  /** A quiet outline badge after the label — the feature flag a row sits behind. */
  badge?: string;
  /** Chord chips at the row's end, e.g. `['⌘', '⇧', 'C']`. Drawn `aria-hidden`. */
  kbd?: readonly string[];
  /** The chord as `aria-keyshortcuts` spells it, e.g. `"Meta+Shift+C Control+Shift+C"`. */
  keyShortcuts?: string;
  /** Draw a hairline above this row. */
  separatorBefore?: boolean;
}

/** The overflow slot of `PageHeader`. */
export interface PageHeaderOverflow {
  /** The rows, in order. An empty list draws no ⋯ button. */
  items: readonly PageHeaderOverflowItem[];
  /** The ⋯ button's accessible name. Defaults to `"More actions"`. */
  label?: string;
  /** Optional small-caps heading above the first row, e.g. `"This project"`. */
  heading?: string;
}

/** The ⋯ button's default accessible name. */
export const PAGE_HEADER_OVERFLOW_LABEL = 'More actions';

/**
 * The ⋯ button and its menu.
 *
 * @param props.overflow See {@link PageHeaderOverflow}.
 * @returns The trigger and its portalled menu, or `null` when there are no rows.
 */
export function PageHeaderOverflowMenu({ overflow }: { overflow: PageHeaderOverflow }) {
  const { items, heading } = overflow;
  const label = overflow.label ?? PAGE_HEADER_OVERFLOW_LABEL;
  if (items.length === 0) return null;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={label}
          title={label}
          data-testid="page-header-overflow"
        >
          <Ellipsis aria-hidden />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="tnt-menu page-header__menu"
          sideOffset={4}
          align="end"
          collisionPadding={8}
          data-testid="page-header-overflow-menu"
        >
          {heading ? (
            <DropdownMenu.Label className="page-header__menu-label">{heading}</DropdownMenu.Label>
          ) : null}
          {items.map((item) => (
            <React.Fragment key={item.id}>
              {item.separatorBefore ? <DropdownMenu.Separator className="page-header__menu-sep" /> : null}
              <OverflowRow item={item} />
            </React.Fragment>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/**
 * One row: a link or a command, available or not.
 *
 * @param props.item The row.
 * @returns The `DropdownMenu.Item`.
 */
function OverflowRow({ item }: { item: PageHeaderOverflowItem }) {
  const Icon = item.icon;
  const unavailable = Boolean(item.disabledReason);

  const body = (
    <>
      {Icon ? <Icon aria-hidden /> : null}
      <span className="page-header__menu-text">{item.label}</span>
      {unavailable ? <span className="sr-only"> — {item.disabledReason}</span> : null}
      {item.badge ? <span className="page-header__menu-badge">{item.badge}</span> : null}
      {item.kbd ? <Kbd keys={[...item.kbd]} className="page-header__menu-kbd" /> : null}
    </>
  );

  return (
    <DropdownMenu.Item
      asChild={Boolean(item.href) && !unavailable}
      className={cn('tnt-menu__item page-header__menu-item')}
      aria-disabled={unavailable || undefined}
      aria-keyshortcuts={item.keyShortcuts}
      title={item.disabledReason}
      data-testid={`page-header-overflow-${item.id}`}
      onSelect={(event) => {
        if (unavailable) {
          event.preventDefault();
          return;
        }
        item.onSelect?.();
      }}
    >
      {item.href && !unavailable ? (
        item.external ? (
          <a href={item.href} target="_blank" rel="noopener noreferrer">
            {body}
          </a>
        ) : (
          <Link href={item.href}>{body}</Link>
        )
      ) : (
        body
      )}
    </DropdownMenu.Item>
  );
}

export default PageHeaderOverflowMenu;
