'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CatalogSearchHit, FacetBucket } from '../../../../lib/search/hits';
import { hitHref } from '../../../../lib/search/hits';
import { HIT_KIND_LABELS, scopeOfKind, type HitKind } from '../../../../lib/search/kinds';
import { parseQuery, textNeedles } from '../../../../lib/search/query';
import { toSearchParams } from '../../../../lib/search/params';
import { sanitizeSearchInput } from '../../utils/searchValidation';
import { HitRow } from './HitRow';
import {
  clearRecentSearches,
  isTypingTarget,
  onOpenSearchPalette,
  pushRecentSearch,
  readRecentSearches,
} from './searchPaletteBus';

interface SuggestResponse {
  q: string;
  rows: CatalogSearchHit[];
  total: number;
  totalAllKinds: number;
  kinds: FacetBucket[];
  tookMs: number;
}

/** A row in the palette list: a hit, a "see all" link, or a quick link. */
type PaletteItem =
  | { id: string; kind: 'search'; label: string; href: string }
  | { id: string; kind: 'hit'; hit: CatalogSearchHit; href: string }
  | { id: string; kind: 'more'; label: string; count: number; href: string }
  | { id: string; kind: 'recent'; query: string; href: string }
  | { id: string; kind: 'link'; label: string; hint?: string; href: string };

const QUICK_LINKS: { label: string; hint: string; href: string }[] = [
  { label: 'Discover', hint: 'Home — rails and the organization directory', href: '/' },
  { label: 'All operations', hint: 'Every operation across the latest versions', href: '/search?type=operation' },
  { label: 'All schemas', hint: 'Every schema across the latest versions', href: '/search?type=schema' },
  { label: 'Recently published', hint: 'Newest versions first', href: '/search?scope=catalog&type=version&all=1' },
  { label: 'MCP catalog', hint: 'Public Model Context Protocol servers', href: '/mcp' },
];

const DEBOUNCE_MS = 160;

/**
 * The ⌘K search palette: live suggestions from the catalog engine, recent searches, and a handful
 * of jump links. Mounted once in the layout; opened from the navbar, ⌘K / Ctrl+K, or `/`.
 */
export function SearchPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<SuggestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const [recent, setRecent] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const requestSeq = useRef(0);

  const close = useCallback(() => {
    setOpen(false);
    setLoading(false);
    const el = returnFocus.current;
    returnFocus.current = null;
    if (el && document.contains(el)) el.focus();
  }, []);

  const openWith = useCallback((initial: string) => {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setQuery(initial);
    setResult(null);
    setActive(0);
    setRecent(readRecentSearches());
    setOpen(true);
  }, []);

  // Open requests from anywhere.
  useEffect(() => onOpenSearchPalette(openWith), [openWith]);

  // Global shortcuts. On the results page the big box is the primary input, so the shortcuts focus
  // it instead of stacking a palette over it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const primary = document.querySelector<HTMLInputElement>('[data-search-primary]');
      const isCmdK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k';
      const isSlash = e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey && !isTypingTarget(e.target);
      if (!isCmdK && !isSlash) return;
      e.preventDefault();
      if (open) {
        if (isCmdK) close();
        return;
      }
      if (primary) {
        primary.focus();
        primary.select();
        return;
      }
      openWith('');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, openWith, close]);

  // Focus and scroll lock while open.
  useEffect(() => {
    if (!open) return;
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      cancelAnimationFrame(id);
      document.body.style.overflow = prevOverflow;
    };
  }, [open]);

  // Debounced suggestions.
  useEffect(() => {
    if (!open) return;
    const q = query.trim();
    if (!q) {
      setResult(null);
      setLoading(false);
      return;
    }
    const seq = ++requestSeq.current;
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search/suggest?q=${encodeURIComponent(q)}`, { cache: 'no-store' });
        if (!res.ok) throw new Error(String(res.status));
        const body = (await res.json()) as SuggestResponse;
        if (seq === requestSeq.current) {
          setResult(body);
          setActive(0);
        }
      } catch {
        if (seq === requestSeq.current) setResult({ q, rows: [], total: 0, totalAllKinds: 0, kinds: [], tookMs: 0 });
      } finally {
        if (seq === requestSeq.current) setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, open]);

  const needles = useMemo(() => textNeedles(parseQuery(query)), [query]);

  const items = useMemo<PaletteItem[]>(() => {
    const q = query.trim();
    if (!q) {
      const out: PaletteItem[] = recent.map((r) => ({
        id: `recent-${r}`,
        kind: 'recent',
        query: r,
        href: `/search?${toSearchParams({ q: r })}`,
      }));
      for (const link of QUICK_LINKS) out.push({ id: `link-${link.href}`, kind: 'link', ...link });
      return out;
    }
    const out: PaletteItem[] = [
      { id: 'search-all', kind: 'search', label: q, href: `/search?${toSearchParams({ q })}` },
    ];
    for (const hit of result?.rows ?? []) out.push({ id: `hit-${hit.hit_id}`, kind: 'hit', hit, href: hitHref(hit) });
    for (const bucket of result?.kinds ?? []) {
      const kind = bucket.value as HitKind;
      if (!(kind in HIT_KIND_LABELS)) continue;
      out.push({
        id: `more-${kind}`,
        kind: 'more',
        label: HIT_KIND_LABELS[kind].many,
        count: bucket.count,
        href: `/search?${toSearchParams({ q, scope: scopeOfKind(kind), type: kind })}`,
      });
    }
    return out;
  }, [query, result, recent]);

  const activeIndex = items.length === 0 ? 0 : Math.min(active, items.length - 1);

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  const go = useCallback(
    (item: PaletteItem) => {
      if (item.kind === 'search' || item.kind === 'more') pushRecentSearch(query);
      if (item.kind === 'recent') pushRecentSearch(item.query);
      close();
      router.push(item.href);
    },
    [close, router, query]
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => (items.length ? (i + 1) % items.length : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => (items.length ? (i - 1 + items.length) % items.length : 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const item = items[activeIndex];
      if (item) go(item);
      else if (query.trim()) go({ id: 'x', kind: 'search', label: query, href: `/search?${toSearchParams({ q: query.trim() })}` });
    } else if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  };

  if (!open) return null;

  const listboxId = 'search-palette-listbox';
  const activeId = items[activeIndex] ? `palette-${items[activeIndex].id}` : undefined;
  const q = query.trim();

  return (
    <div className="fixed inset-0 z-[60]" role="presentation">
      <div className="absolute inset-0 bg-zinc-900/40 backdrop-blur-sm" onClick={close} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search the catalog"
        className="animate-fade-in absolute left-1/2 top-[10vh] w-[min(720px,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-950"
      >
        <div className="flex items-center gap-3 border-b border-zinc-200 px-4 dark:border-zinc-800">
          <svg className="h-5 w-5 shrink-0 text-zinc-400" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded="true"
            aria-controls={listboxId}
            aria-activedescendant={activeId}
            aria-autocomplete="list"
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(e) => setQuery(sanitizeSearchInput(e.target.value))}
            onKeyDown={onKeyDown}
            placeholder="Search operations, schemas, projects… try method:POST path:/orders"
            className="h-14 min-w-0 flex-1 bg-transparent text-[15px] text-zinc-900 placeholder-zinc-400 focus:outline-none dark:text-zinc-100 dark:placeholder-zinc-500"
          />
          {loading ? (
            <svg className="h-4 w-4 animate-spin text-[var(--brand)]" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <kbd className="rounded border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400">
              esc
            </kbd>
          )}
        </div>

        <ul
          id={listboxId}
          ref={listRef}
          role="listbox"
          aria-label={q ? `Suggestions for ${q}` : 'Recent searches and shortcuts'}
          className="max-h-[min(60vh,560px)] overflow-y-auto p-2"
        >
          {!q && recent.length > 0 && (
            <li className="flex items-center justify-between px-2 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-400" role="presentation">
              Recent
              <button
                type="button"
                className="font-normal normal-case text-[var(--brand)] hover:underline"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  clearRecentSearches();
                  setRecent([]);
                }}
              >
                Clear
              </button>
            </li>
          )}
          {items.map((item, index) => {
            const isActive = index === activeIndex;
            if (item.kind === 'hit') {
              return (
                <div key={item.id} data-index={index} role="option" aria-selected={isActive} id={`palette-${item.id}`} className="mb-1.5" onMouseEnter={() => setActive(index)}>
                  <HitRow hit={item.hit} needles={needles} compact active={isActive} onSelect={() => go(item)} />
                </div>
              );
            }
            const baseRow = `flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-[13px] transition-colors ${
              isActive ? 'bg-[var(--brand-soft)] text-[var(--brand-soft-text)]' : 'text-zinc-700 hover:bg-zinc-50 dark:text-zinc-200 dark:hover:bg-zinc-900'
            }`;
            return (
              <li key={item.id} data-index={index} role="option" aria-selected={isActive} id={`palette-${item.id}`} onMouseEnter={() => setActive(index)}>
                {item.kind === 'link' && index === items.findIndex((i) => i.kind === 'link') && (
                  <div className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">Go to</div>
                )}
                <Link href={item.href} onClick={(e) => { e.preventDefault(); go(item); }} className={baseRow}>
                  {item.kind === 'search' && (
                    <>
                      <span aria-hidden="true" className="text-[var(--brand)]">↵</span>
                      <span className="min-w-0 flex-1 truncate">
                        Search the catalog for <span className="font-mono font-medium">&ldquo;{item.label}&rdquo;</span>
                      </span>
                      {result && !loading && (
                        <span className="shrink-0 text-[11px] tabular-nums text-zinc-400">
                          {result.totalAllKinds.toLocaleString()} {result.totalAllKinds === 1 ? 'match' : 'matches'}
                        </span>
                      )}
                    </>
                  )}
                  {item.kind === 'more' && (
                    <>
                      <span aria-hidden="true" className="text-zinc-400">→</span>
                      <span className="min-w-0 flex-1 truncate">
                        All <span className="font-medium">{item.label.toLowerCase()}</span> matching &ldquo;{q}&rdquo;
                      </span>
                      <span className="shrink-0 font-mono text-[11px] tabular-nums text-zinc-400">{item.count.toLocaleString()}</span>
                    </>
                  )}
                  {item.kind === 'recent' && (
                    <>
                      <svg className="h-4 w-4 shrink-0 text-zinc-400" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{item.query}</span>
                    </>
                  )}
                  {item.kind === 'link' && (
                    <>
                      <span aria-hidden="true" className="hex inline-block h-2 w-2 shrink-0 bg-[var(--gold)]" />
                      <span className="min-w-0 flex-1 truncate">
                        {item.label}
                        {item.hint && <span className="ml-2 text-[11px] text-zinc-400">{item.hint}</span>}
                      </span>
                    </>
                  )}
                </Link>
              </li>
            );
          })}
          {q && !loading && result && result.rows.length === 0 && (
            <li className="px-3 py-6 text-center text-[13px] text-zinc-500 dark:text-zinc-400" role="presentation">
              Nothing in the latest versions matches <span className="font-mono">&ldquo;{q}&rdquo;</span>. Press Enter to search every version and filter.
            </li>
          )}
        </ul>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-zinc-200 px-4 py-2 text-[11px] text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          <span><kbd className="font-mono">↑↓</kbd> move</span>
          <span><kbd className="font-mono">↵</kbd> open</span>
          <span><kbd className="font-mono">esc</kbd> close</span>
          <span className="ml-auto hidden sm:inline">
            Operators: <code className="font-mono">method:</code> <code className="font-mono">path:</code> <code className="font-mono">org:</code> <code className="font-mono">type:</code> <code className="font-mono">&quot;phrase&quot;</code> <code className="font-mono">-word</code>
          </span>
        </div>
      </div>
    </div>
  );
}
