'use client';

/**
 * The Versions toolbar's two overlay filters (HIVE-11.4, #5600).
 *
 * Authority: `docs/mockups/proposals/versions-status-strip.html` callout **5** — an
 * *Any time ▾* button that opens a *Created between* popover (From / To, three quick ranges,
 * Clear and Apply), and an *All authors ▾* button that opens a menu of the authors in the
 * loaded list, each with their avatar.
 *
 * Plus the toolbar's search box, which keeps a draft of its own so typing does not rewrite
 * the address bar on every keystroke.
 *
 * Both overlays are Radix overlays in their modal mode, which is what the acceptance criteria ask of
 * them: focus moves in and is trapped while open, **Escape** closes, and focus goes back to
 * the trigger. Neither fetches — the values are the toolbar's, and the page applies them.
 */

import * as React from 'react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import * as Popover from '@radix-ui/react-popover';
import { Calendar, Check, ChevronDown, User } from 'lucide-react';

import { Avatar } from '@/app/components/ui/Avatar';
import { Button } from '@/app/components/ui/Button';
import { DataTableFilterChip, DataTableSearch } from '@/app/components/ui/DataTable';
import { Input } from '@/app/components/ui/Input';
import { cn } from '@lib/utils';

import {
  isVersionsDateRangeValid,
  VERSIONS_DATE_PRESET_LABEL,
  VERSIONS_DATE_PRESETS,
  versionsAuthorLabel,
  versionsDatePresetFor,
  versionsDatePresetRange,
  versionsDateRangeLabel,
  type VersionAuthorOption,
  type VersionsDateRange,
} from './versionsToolbarModel';

/** Radix `RadioGroup` cannot use the empty string as a value; this stands in for "all authors". */
const ALL_AUTHORS = '__all__';

/** How long the search box waits after the last keystroke before it filters (ms). */
export const VERSIONS_SEARCH_DEBOUNCE_MS = 250;

// ---------------------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------------------

export interface VersionsSearchFieldProps {
  /** The applied search text — the URL's `q`. */
  value: string;
  /** Apply new search text, after the debounce. */
  onChange: (next: string) => void;
}

/**
 * The toolbar's search box (*Message, changelog, commit…*).
 *
 * The input edits a local draft and hands it on {@link VERSIONS_SEARCH_DEBOUNCE_MS} after
 * the last keystroke. A `value` that changes from outside — *Clear filters*, Back, a project
 * switch — replaces the draft, unless it is only the draft's own trimmed form coming back.
 *
 * @returns The search input.
 */
export function VersionsSearchField({ value, onChange }: VersionsSearchFieldProps) {
  const [draft, setDraft] = React.useState(value);
  // The latest callback, read by the debounce timer without re-arming it on every render.
  const onChangeRef = React.useRef(onChange);
  React.useEffect(() => {
    onChangeRef.current = onChange;
  });

  // Outside changes win over the draft; the draft's own echo (trimmed) does not.
  React.useEffect(() => {
    setDraft((current) => (current.trim() === value ? current : value));
  }, [value]);

  React.useEffect(() => {
    if (draft.trim() === value) return undefined;
    const timer = window.setTimeout(() => onChangeRef.current(draft.trim()), VERSIONS_SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [draft, value]);

  return (
    <DataTableSearch
      id="history-timeline-search"
      className="ver-toolbar-search"
      placeholder="Message, changelog, commit…"
      aria-label="Search revisions"
      autoComplete="off"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
    />
  );
}

// ---------------------------------------------------------------------------------------
// Any time ▾
// ---------------------------------------------------------------------------------------

export interface VersionsDateFilterProps {
  /** The applied range — `YYYY-MM-DD` or `''` on each side. */
  value: VersionsDateRange;
  /** Apply a new range (Apply, or Clear with `{ from: '', to: '' }`). */
  onChange: (next: VersionsDateRange) => void;
  /** The clock the quick ranges are measured from. Defaults to now; injectable for tests. */
  now?: Date;
}

/**
 * The date trigger and its *Created between* popover.
 *
 * The inputs edit a draft that only reaches the table on **Apply**, so typing a year one
 * digit at a time does not re-filter the list four times. A quick range fills the draft; the
 * draft is re-read from `value` every time the popover opens, so cancelling (Escape, a click
 * outside) leaves the table as it was.
 *
 * @returns The trigger button, with its popover.
 */
export function VersionsDateFilter({ value, onChange, now }: VersionsDateFilterProps) {
  const [open, setOpen] = React.useState(false);
  const [draft, setDraft] = React.useState<VersionsDateRange>(value);
  const clock = now ?? new Date();
  const active = !!(value.from || value.to);
  const valid = isVersionsDateRangeValid(draft);
  const draftPreset = versionsDatePresetFor(draft, clock);

  const handleOpenChange = (next: boolean) => {
    if (next) setDraft(value);
    setOpen(next);
  };

  const apply = (next: VersionsDateRange) => {
    onChange(next);
    setOpen(false);
  };

  return (
    <Popover.Root open={open} onOpenChange={handleOpenChange} modal>
      <Popover.Trigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn('ver-toolbar-trigger', active && 'is-active')}
          aria-haspopup="dialog"
          data-testid="versions-date-filter"
        >
          <Calendar aria-hidden />
          {versionsDateRangeLabel(value, clock)}
          <ChevronDown aria-hidden />
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="tnt-menu ver-date-pop"
          sideOffset={4}
          align="start"
          aria-labelledby="versions-date-filter-title"
          data-testid="versions-date-filter-popover"
        >
          <h2 className="ver-date-pop__title" id="versions-date-filter-title">
            Created between
          </h2>
          <div className="ver-date-pop__grid">
            <label className="ver-date-pop__field">
              <span>From</span>
              <Input
                id="history-date-from"
                type="date"
                aria-label="From date"
                value={draft.from}
                max={draft.to || undefined}
                onChange={(event) => setDraft((current) => ({ ...current, from: event.target.value }))}
              />
            </label>
            <label className="ver-date-pop__field">
              <span>To</span>
              <Input
                id="history-date-to"
                type="date"
                aria-label="To date"
                value={draft.to}
                min={draft.from || undefined}
                onChange={(event) => setDraft((current) => ({ ...current, to: event.target.value }))}
              />
            </label>
          </div>
          {!valid ? (
            <p className="ver-date-pop__error" role="alert">
              From must be on or before To.
            </p>
          ) : null}
          <div className="ver-date-pop__presets" role="group" aria-label="Quick ranges">
            {VERSIONS_DATE_PRESETS.map((preset) => (
              <DataTableFilterChip
                key={preset}
                active={draftPreset === preset}
                data-testid={`versions-date-preset-${preset}`}
                onClick={() => setDraft(versionsDatePresetRange(preset, clock))}
              >
                {VERSIONS_DATE_PRESET_LABEL[preset]}
              </DataTableFilterChip>
            ))}
          </div>
          <div className="ver-date-pop__actions">
            <Button
              variant="ghost"
              size="sm"
              data-testid="versions-date-filter-clear"
              onClick={() => apply({ from: '', to: '' })}
            >
              Clear
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={!valid}
              data-testid="versions-date-filter-apply"
              onClick={() => apply(draft)}
            >
              Apply
            </Button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

// ---------------------------------------------------------------------------------------
// All authors ▾
// ---------------------------------------------------------------------------------------

export interface VersionsAuthorFilterProps {
  /** The applied creator id, `''` for all. */
  value: string;
  /** Apply a new author (`''` for all). */
  onChange: (next: string) => void;
  /** The authors present in the loaded list. */
  options: readonly VersionAuthorOption[];
}

/**
 * The author trigger and its menu.
 *
 * A radio group inside a Radix menu, so each row announces as `menuitemradio` with its
 * checked state, and arrow keys and typeahead walk the names. Each author carries the
 * deterministic avatar tint the rest of the app gives them.
 *
 * @returns The trigger button, with its menu.
 */
export function VersionsAuthorFilter({ value, onChange, options }: VersionsAuthorFilterProps) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn('ver-toolbar-trigger', value && 'is-active')}
          data-testid="versions-author-filter"
        >
          <User aria-hidden />
          {versionsAuthorLabel(value, options)}
          <ChevronDown aria-hidden />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="tnt-menu ver-author-menu"
          sideOffset={4}
          align="start"
          data-testid="versions-author-filter-menu"
        >
          <DropdownMenu.RadioGroup
            value={value || ALL_AUTHORS}
            onValueChange={(next) => onChange(next === ALL_AUTHORS ? '' : next)}
          >
            <DropdownMenu.RadioItem
              value={ALL_AUTHORS}
              className="tnt-menu__item ver-author-menu__item"
              data-testid="versions-author-all"
            >
              <span className="ver-author-menu__mark" aria-hidden>
                <DropdownMenu.ItemIndicator>
                  <Check />
                </DropdownMenu.ItemIndicator>
              </span>
              All authors
            </DropdownMenu.RadioItem>
            {options.map((option) => (
              <DropdownMenu.RadioItem
                key={option.id}
                value={option.id}
                className="tnt-menu__item ver-author-menu__item"
                data-testid={`versions-author-${option.id}`}
              >
                <span className="ver-author-menu__mark" aria-hidden>
                  <DropdownMenu.ItemIndicator>
                    <Check />
                  </DropdownMenu.ItemIndicator>
                </span>
                <Avatar size="xs" name={option.label} seed={option.id} />
                <span className="ver-author-menu__name">{option.label}</span>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
