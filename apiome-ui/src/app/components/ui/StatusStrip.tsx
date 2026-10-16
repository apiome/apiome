'use client';

import * as React from 'react';
import {
  ChevronUp,
  CircleCheck,
  Info,
  OctagonAlert,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react';

import { cn } from '../../../../lib/utils';
import { Button } from './Button';
import { ICON_SIZE } from './iconSizes';
import { Skeleton } from './Skeleton';

/**
 * StatusStrip — several statuses about one object, in one row (HIVE-11.1, #5597).
 *
 * Authority: `docs/mockups/proposals/versions-status-strip.html` (annotation 3) and
 * `docs/mockups/PROPOSALS.md` §2.1. A page that has several things to say about an object —
 * "compatible", "what's new", "deprecated", "server is ahead" — used to stack one full-width
 * `Alert` per statement. The strip is the overlay-free replacement: a card holding one row of
 * status chips (icon · label · muted detail) and **at most one** open detail row below it
 * (icon · title · body · actions).
 *
 * ```tsx
 * <StatusStrip
 *   aria-label="Project status"
 *   storageKey={`versions:${projectId}`}
 *   items={[
 *     { id: 'compat', tone: 'ok', label: 'Compatible', detail: 'v2.3.0 → v2.3.1',
 *       title: 'Compatible.', body: 'No breaking changes.', actions: <Button size="sm">View report</Button> },
 *     { id: 'sunset', tone: 'warn', label: 'v2.2.0 deprecated', title: 'v2.2.0 is deprecated.' },
 *   ]}
 * />
 * ```
 *
 * ### Behaviour
 *
 * - The most severe chip opens on first paint (`danger` > `warn` > `accent` > `ok`; the first
 *   of equals wins) — see {@link severestStatusId}.
 * - Clicking a closed chip opens it; clicking the open chip, pressing **Collapse**, or pressing
 *   Escape while focus is inside the strip hides the detail row.
 * - The reader's choice (a chip, or "none") is remembered per `storageKey` in `sessionStorage`
 *   — for this tab's session only, never across devices — see {@link readStoredStatus}.
 * - One status: its chip renders already open and there is no Collapse button. Zero statuses:
 *   nothing renders. `loading`: one skeleton chip.
 *
 * ### Accessibility
 *
 * Chips are `<button aria-expanded aria-controls>` inside a `role="group"` named by
 * `aria-label`. There is exactly one `.status-strip__detail` element; it is `aria-live="polite"`
 * so switching chips reads the new detail, and it is `hidden` (not unmounted) when collapsed so
 * the live region exists before its content changes. Colour is never the only signal: every
 * chip carries an icon and a label.
 *
 * Everything visual is in the `STATUS STRIP` section of `globals.css`, in tokens only.
 */

/** The tones a strip spends — the status vocabulary's four "meaning" tones. */
export type StatusStripTone = 'ok' | 'accent' | 'warn' | 'danger';

/** Severity rank of each tone; higher opens first. */
export const STATUS_STRIP_SEVERITY: Readonly<Record<StatusStripTone, number>> = {
  ok: 0,
  accent: 1,
  warn: 2,
  danger: 3,
};

/** The glyph a chip and its detail row draw when the item names none. */
const DEFAULT_ICON: Readonly<Record<StatusStripTone, LucideIcon>> = {
  ok: CircleCheck,
  accent: Info,
  warn: TriangleAlert,
  danger: OctagonAlert,
};

/** Prefix of every `sessionStorage` key the strip writes. */
export const STATUS_STRIP_STORAGE_PREFIX = 'hive.statusStrip.';

/** One status of a {@link StatusStrip}: a chip, and the detail row it opens. */
export interface StatusStripItem {
  /** Stable identifier, unique within the strip; it is what `sessionStorage` remembers. */
  id: string;
  /** Severity and colour. */
  tone: StatusStripTone;
  /** The chip's label, e.g. `Compatible`. */
  label: React.ReactNode;
  /** Optional muted text after the chip's label, e.g. `v2.3.0 → v2.3.1`. */
  detail?: React.ReactNode;
  /** Optional glyph; defaults to the tone's icon. */
  icon?: LucideIcon;
  /** The detail row's lead sentence, drawn in full ink. */
  title: React.ReactNode;
  /** Optional detail copy after the title. */
  body?: React.ReactNode;
  /** Optional actions at the end of the detail row (small buttons or links). */
  actions?: React.ReactNode;
}

/** Props for {@link StatusStrip}. */
export interface StatusStripProps {
  /** The statuses, in reading order. An empty list renders nothing. */
  items: readonly StatusStripItem[];
  /** Names the chip group for assistive technology, e.g. `Project status`. */
  'aria-label': string;
  /**
   * Where the open chip is remembered for the session. Omit it and the strip forgets on
   * reload; give each object its own key (`versions:<projectId>`) so two projects do not share
   * a choice.
   */
  storageKey?: string;
  /**
   * The namespace `storageKey` is written under. Defaults to
   * {@link STATUS_STRIP_STORAGE_PREFIX}; a page that owns a documented key of its own (Versions
   * writes `hive.versions.status.<projectId>`) passes its prefix here.
   */
  storagePrefix?: string;
  /** Draws one skeleton chip instead of `items`. */
  loading?: boolean;
  /** The small caps caption at the start of the row. Defaults to `Status`. */
  caption?: string;
  /** Extra classes for the card. */
  className?: string;
}

/**
 * The id of the most severe item — the one that opens on first paint.
 *
 * @param items The strip's statuses, in reading order.
 * @returns The id of the highest-severity item (first of equals), or `null` for an empty list.
 */
export function severestStatusId(items: readonly Pick<StatusStripItem, 'id' | 'tone'>[]): string | null {
  let best: Pick<StatusStripItem, 'id' | 'tone'> | null = null;
  for (const item of items) {
    if (!best || STATUS_STRIP_SEVERITY[item.tone] > STATUS_STRIP_SEVERITY[best.tone]) best = item;
  }
  return best ? best.id : null;
}

/**
 * The `sessionStorage` key for one strip.
 *
 * @param storageKey The caller's key.
 * @param prefix The namespace; defaults to {@link STATUS_STRIP_STORAGE_PREFIX}.
 * @returns The namespaced key.
 */
export function statusStripStorageKey(storageKey: string, prefix: string = STATUS_STRIP_STORAGE_PREFIX): string {
  return `${prefix}${storageKey}`;
}

/**
 * What the reader last chose for a strip this session.
 *
 * @param storageKey The caller's key.
 * @param prefix The namespace; defaults to {@link STATUS_STRIP_STORAGE_PREFIX}.
 * @returns `undefined` when nothing is stored (or storage is unavailable), `null` when the
 *   reader collapsed the strip, otherwise the open item's id.
 */
export function readStoredStatus(
  storageKey: string,
  prefix: string = STATUS_STRIP_STORAGE_PREFIX
): string | null | undefined {
  try {
    const raw = window.sessionStorage.getItem(statusStripStorageKey(storageKey, prefix));
    if (raw === null) return undefined;
    const value: unknown = JSON.parse(raw);
    if (value === null || typeof value === 'string') return value;
    return undefined;
  } catch {
    return undefined;
  }
}

/**
 * Remembers the reader's choice for a strip, for this session only.
 *
 * @param storageKey The caller's key.
 * @param open The open item's id, or `null` when collapsed.
 * @param prefix The namespace; defaults to {@link STATUS_STRIP_STORAGE_PREFIX}.
 */
export function writeStoredStatus(
  storageKey: string,
  open: string | null,
  prefix: string = STATUS_STRIP_STORAGE_PREFIX
): void {
  try {
    window.sessionStorage.setItem(statusStripStorageKey(storageKey, prefix), JSON.stringify(open));
  } catch {
    // Private windows and blocked storage: the strip still works, it just forgets.
  }
}

/**
 * Which item is open, given what the reader chose and what is on the page now.
 *
 * A choice that names an item no longer present falls back to severity, so a status that
 * resolves itself does not leave the strip collapsed for no reason.
 *
 * @param items The strip's statuses.
 * @param choice `undefined` for "no choice yet", `null` for "collapsed", else an item id.
 * @returns The open item's id, or `null` when collapsed.
 */
export function resolveOpenStatus(
  items: readonly Pick<StatusStripItem, 'id' | 'tone'>[],
  choice: string | null | undefined
): string | null {
  if (choice === null) return null;
  if (choice !== undefined && items.some((item) => item.id === choice)) return choice;
  return severestStatusId(items);
}

/**
 * One row of status chips with at most one open detail row.
 *
 * @param props See {@link StatusStripProps}.
 * @returns The strip, or `null` when there is nothing to say.
 */
export function StatusStrip({
  items,
  'aria-label': ariaLabel,
  storageKey,
  storagePrefix = STATUS_STRIP_STORAGE_PREFIX,
  loading = false,
  caption = 'Status',
  className,
}: StatusStripProps) {
  const detailId = React.useId();
  // `undefined` until the reader chooses (or a stored choice is read after mount, so the
  // server and first client render agree).
  const [choice, setChoice] = React.useState<string | null | undefined>(undefined);
  const chipRefs = React.useRef(new Map<string, HTMLButtonElement>());

  React.useEffect(() => {
    if (storageKey) setChoice(readStoredStatus(storageKey, storagePrefix));
  }, [storageKey, storagePrefix]);

  const open = resolveOpenStatus(items, choice);

  /**
   * Records a choice and remembers it for the session.
   *
   * @param next The item to open, or `null` to collapse.
   */
  const choose = (next: string | null) => {
    setChoice(next);
    if (storageKey) writeStoredStatus(storageKey, next, storagePrefix);
  };

  /**
   * Escape collapses while focus is inside; focus returns to the chip that was open, since the
   * control the reader was on may be inside the row that just hid.
   *
   * @param event The key event bubbled to the strip.
   */
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Escape' || open === null) return;
    event.stopPropagation();
    const chip = chipRefs.current.get(open);
    choose(null);
    chip?.focus();
  };

  if (loading) {
    return (
      <div className={cn('status-strip', className)} aria-busy="true">
        <div className="status-strip__row">
          <span className="status-strip__caption">{caption}</span>
          <Skeleton className="status-strip__skeleton-chip" />
          <span className="sr-only">Loading status…</span>
        </div>
      </div>
    );
  }

  if (items.length === 0) return null;

  const openItem = items.find((item) => item.id === open) ?? null;
  const OpenIcon = openItem ? (openItem.icon ?? DEFAULT_ICON[openItem.tone]) : null;

  return (
    <div className={cn('status-strip', className)} onKeyDown={onKeyDown}>
      <div className="status-strip__row">
        <span className="status-strip__caption" aria-hidden>
          {caption}
        </span>
        <div role="group" aria-label={ariaLabel} className="status-strip__chips">
          {items.map((item) => {
            const Icon = item.icon ?? DEFAULT_ICON[item.tone];
            const isOpen = item.id === open;
            return (
              <button
                key={item.id}
                ref={(node) => {
                  if (node) chipRefs.current.set(item.id, node);
                  else chipRefs.current.delete(item.id);
                }}
                type="button"
                className={cn('status-chip', `status-chip--${item.tone}`, isOpen && 'is-open')}
                aria-expanded={isOpen}
                aria-controls={detailId}
                onClick={() => choose(isOpen ? null : item.id)}
              >
                <Icon size={ICON_SIZE.button} aria-hidden />
                <span>{item.label}</span>
                {item.detail ? <span className="status-chip__detail">{item.detail}</span> : null}
              </button>
            );
          })}
        </div>
        {items.length > 1 && open !== null ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="status-strip__collapse"
            onClick={() => choose(null)}
          >
            Collapse
            <ChevronUp aria-hidden />
          </Button>
        ) : null}
      </div>
      <div
        id={detailId}
        className="status-strip__detail"
        data-tone={openItem?.tone}
        aria-live="polite"
        hidden={!openItem}
      >
        {openItem && OpenIcon ? (
          <>
            <OpenIcon size={ICON_SIZE.dense} aria-hidden className="status-strip__detail-icon" />
            <div className="status-strip__detail-copy">
              <span className="status-strip__detail-title">{openItem.title}</span>
              {openItem.body ? <> {openItem.body}</> : null}
            </div>
            {openItem.actions ? (
              <div className="status-strip__detail-actions">{openItem.actions}</div>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}

export default StatusStrip;
