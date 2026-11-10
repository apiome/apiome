'use client';

import { forwardRef, type KeyboardEvent } from 'react';
import { sanitizeSearchInput } from '../../utils/searchValidation';

interface SearchBoxProps {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  onKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void;
  onFocus?: () => void;
  onBlur?: () => void;
  placeholder?: string;
  size?: 'md' | 'lg';
  busy?: boolean;
  autoFocus?: boolean;
  /** Show the ⌘K hint inside the box. */
  shortcutHint?: boolean;
  /** Accessible name. */
  label?: string;
  /** Mark this box as the page's primary search input: `/` and ⌘K focus it instead of opening the palette. */
  primary?: boolean;
  id?: string;
  /** Controls `aria-expanded` / listbox wiring for an attached suggestion panel. */
  ariaControls?: string;
  ariaExpanded?: boolean;
  ariaActiveDescendant?: string;
}

function Spinner({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg className={`${className} animate-spin`} fill="none" viewBox="0 0 24 24" aria-hidden>
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

/**
 * The search input used by the home hero and the search page: one look, one clear button, one
 * submit button, and the keyboard hint. The palette has its own, lighter input.
 */
export const SearchBox = forwardRef<HTMLInputElement, SearchBoxProps>(function SearchBox(
  {
    value,
    onChange,
    onSubmit,
    onKeyDown,
    onFocus,
    onBlur,
    placeholder = 'Search operations, schemas, projects, organizations…',
    size = 'lg',
    busy = false,
    autoFocus = false,
    shortcutHint = true,
    label = 'Search the public catalog',
    primary = false,
    id,
    ariaControls,
    ariaExpanded,
    ariaActiveDescendant,
  },
  ref
) {
  const height = size === 'lg' ? 'h-13 text-lg' : 'h-10 text-base';
  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="relative"
    >
      <svg
        className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-fg-subtle"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.75}
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
      <input
        ref={ref}
        id={id}
        type="search"
        name="q"
        enterKeyHint="search"
        autoComplete="off"
        spellCheck={false}
        aria-label={label}
        data-search-primary={primary ? 'true' : undefined}
        aria-controls={ariaControls}
        aria-expanded={ariaExpanded}
        aria-activedescendant={ariaActiveDescendant}
        aria-autocomplete={ariaControls ? 'list' : undefined}
        role={ariaControls ? 'combobox' : undefined}
        value={value}
        onChange={(e) => onChange(sanitizeSearchInput(e.target.value))}
        onKeyDown={onKeyDown}
        onFocus={onFocus}
        onBlur={onBlur}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className={`${height} w-full rounded-lg border border-border bg-surface pl-12 pr-40 text-fg placeholder:text-fg-faint shadow-sm transition-colors focus-visible:border-accent focus-visible:outline-none [&::-webkit-search-cancel-button]:appearance-none`}
      />
      <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1.5">
        {value && !busy && (
          <button
            type="button"
            onClick={() => onChange('')}
            aria-label="Clear search"
            className="rounded-md p-1.5 text-fg-subtle transition-colors hover:bg-subtle hover:text-fg-muted"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
        {shortcutHint && !value && (
          <kbd className="hidden rounded-xs border border-border bg-subtle px-1.5 py-0.5 font-mono text-2xs font-medium text-fg-muted sm:inline-block">
            ⌘K
          </kbd>
        )}
        <button
          type="submit"
          disabled={busy}
          className={`btn-brand inline-flex items-center gap-1.5 ${size === 'lg' ? 'h-9 px-4 text-sm' : 'h-7 px-3 text-xs'} font-semibold disabled:opacity-80`}
        >
          {busy && <Spinner className="h-3.5 w-3.5" />}
          {busy ? 'Searching…' : 'Search'}
        </button>
      </div>
    </form>
  );
});
