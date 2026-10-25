'use client';

import { useState, type ReactNode } from 'react';
import { formatLabel, paradigmLabel } from '../../../../lib/browseFacets';
import type { CatalogSearchResponse } from '../../../../lib/search/hits';
import { HIT_KIND_LABELS, SCOPE_KINDS, type HitKind } from '../../../../lib/search/kinds';
import type { SearchRequest } from '../../../../lib/search/params';
import { methodTone } from './httpMethodTone';

/** The actions the rail can take; the page turns each into a navigation. */
export interface FacetRailActions {
  toggleOrg: (slug: string) => void;
  toggleMethod: (method: string) => void;
  toggleType: (kind: HitKind) => void;
  toggleFormat: (format: string) => void;
  toggleParadigm: (paradigm: string) => void;
  setDates: (after: string | null, before: string | null) => void;
  setAllVersions: (all: boolean) => void;
  clearAll: () => void;
}

function Section({
  title,
  children,
  count,
  defaultOpen = true,
}: {
  title: string;
  children: ReactNode;
  count?: number;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="border-b border-zinc-100 py-3 last:border-b-0 dark:border-zinc-800/80">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 text-left"
      >
        <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
          {title}
          {count ? <span className="ml-1.5 rounded-full bg-[var(--brand-soft)] px-1.5 text-[10px] text-[var(--brand-soft-text)]">{count}</span> : null}
        </span>
        <svg
          className={`h-3.5 w-3.5 text-zinc-400 transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && <div className="mt-2">{children}</div>}
    </section>
  );
}

function CheckRow({
  id,
  checked,
  onChange,
  label,
  count,
  mono = false,
}: {
  id: string;
  checked: boolean;
  onChange: () => void;
  label: ReactNode;
  count: number;
  mono?: boolean;
}) {
  return (
    <li className="flex items-center gap-2">
      <input
        type="checkbox"
        id={id}
        checked={checked}
        onChange={onChange}
        className="h-3.5 w-3.5 shrink-0 rounded border-zinc-300 accent-[var(--brand)]"
      />
      <label htmlFor={id} className={`min-w-0 flex-1 cursor-pointer truncate text-[13px] text-zinc-700 dark:text-zinc-300 ${mono ? 'font-mono text-[12px]' : ''}`}>
        {label}
      </label>
      <span className="font-mono text-[11px] tabular-nums text-zinc-400">{count.toLocaleString()}</span>
    </li>
  );
}

/**
 * The filter rail of the results page. Every control is a navigation (the URL is the state), so
 * the rail only knows what is selected (`request`) and what is available (`response.facets`).
 */
export function FacetRail({
  request,
  response,
  actions,
  activeCount,
}: {
  request: SearchRequest;
  response: CatalogSearchResponse;
  actions: FacetRailActions;
  activeCount: number;
}) {
  const { facets } = response;
  const [after, setAfter] = useState(request.after ?? '');
  const [before, setBefore] = useState(request.before ?? '');
  const scopeKinds = SCOPE_KINDS[request.scope];
  const kindOptions = facets.kinds.filter((k) => scopeKinds.includes(k.value as HitKind));

  const dateDirty = (after || '') !== (request.after ?? '') || (before || '') !== (request.before ?? '');

  return (
    <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-center gap-2 rounded-t-xl border-b border-zinc-200 bg-zinc-50/80 px-4 py-2.5 dark:border-zinc-800 dark:bg-zinc-900/40">
        <svg className="h-4 w-4 text-[var(--brand)]" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 4h18l-7 8v6l-4 2v-8L3 4z" />
        </svg>
        <h2 className="flex-1 text-[13px]! font-semibold text-zinc-900 dark:text-zinc-50">Filters</h2>
        {activeCount > 0 && (
          <button type="button" onClick={actions.clearAll} className="text-[11px] font-medium text-[var(--brand)] hover:underline">
            Clear all ({activeCount})
          </button>
        )}
      </div>

      <div className="px-4">
        <Section title="Versions">
          <div role="radiogroup" aria-label="Which versions to search" className="flex rounded-md border border-zinc-200 p-0.5 text-[12px] dark:border-zinc-700">
            {[
              { value: false, label: 'Latest only' },
              { value: true, label: 'All published' },
            ].map((opt) => (
              <button
                key={String(opt.value)}
                type="button"
                role="radio"
                aria-checked={request.allVersions === opt.value}
                onClick={() => actions.setAllVersions(opt.value)}
                className={`flex-1 rounded px-2 py-1 font-medium transition-colors ${
                  request.allVersions === opt.value
                    ? 'bg-[var(--brand)] text-white'
                    : 'text-zinc-600 hover:bg-zinc-50 dark:text-zinc-300 dark:hover:bg-zinc-800'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-[11px] text-zinc-500 dark:text-zinc-400">
            {request.allVersions
              ? 'Every published version of every project; the same item may appear once per version.'
              : "Each project's most recently published version."}
          </p>
        </Section>

        {kindOptions.length > 1 && (
          <Section title="Kind" count={request.types.length}>
            <ul className="space-y-1.5">
              {kindOptions.map((k) => (
                <CheckRow
                  key={k.value}
                  id={`kind-${k.value}`}
                  checked={request.types.includes(k.value as HitKind)}
                  onChange={() => actions.toggleType(k.value as HitKind)}
                  label={HIT_KIND_LABELS[k.value as HitKind]?.many ?? k.value}
                  count={k.count}
                />
              ))}
            </ul>
          </Section>
        )}

        {facets.methods.length > 0 && (
          <Section title="HTTP method" count={request.methods.length}>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="HTTP method">
              {facets.methods.map((m) => {
                const active = request.methods.includes(m.value);
                return (
                  <button
                    key={m.value}
                    type="button"
                    aria-pressed={active}
                    onClick={() => actions.toggleMethod(m.value)}
                    className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-mono text-[11px] font-semibold uppercase ring-1 ring-inset transition-opacity ${methodTone(m.value)} ${
                      active ? 'opacity-100 ring-2' : 'opacity-70 hover:opacity-100'
                    }`}
                  >
                    {m.value}
                    <span className="font-normal tabular-nums opacity-70">{m.count}</span>
                  </button>
                );
              })}
            </div>
          </Section>
        )}

        {(facets.orgs.length > 0 || request.orgs.length > 0) && (
          <Section title="Organization" count={request.orgs.length}>
            <ul className="max-h-56 space-y-1.5 overflow-y-auto pr-1">
              {facets.orgs.map((o) => (
                <CheckRow
                  key={o.value}
                  id={`org-${o.value}`}
                  checked={request.orgs.includes(o.value)}
                  onChange={() => actions.toggleOrg(o.value)}
                  label={o.label ?? o.value}
                  count={o.count}
                />
              ))}
              {request.orgs
                .filter((slug) => !facets.orgs.some((o) => o.value === slug))
                .map((slug) => (
                  <CheckRow key={slug} id={`org-${slug}`} checked onChange={() => actions.toggleOrg(slug)} label={slug} count={0} />
                ))}
            </ul>
          </Section>
        )}

        {(facets.paradigms.length > 0 || request.paradigms.length > 0) && (
          <Section title="Paradigm" count={request.paradigms.length}>
            <ul className="space-y-1.5">
              {facets.paradigms.map((p) => (
                <CheckRow
                  key={p.value}
                  id={`paradigm-${p.value}`}
                  checked={request.paradigms.includes(p.value)}
                  onChange={() => actions.toggleParadigm(p.value)}
                  label={paradigmLabel(p.value)}
                  count={p.count}
                />
              ))}
            </ul>
          </Section>
        )}

        {(facets.formats.length > 0 || request.formats.length > 0) && (
          <Section title="Format" count={request.formats.length}>
            <ul className="max-h-56 space-y-1.5 overflow-y-auto pr-1">
              {facets.formats.map((f) => (
                <CheckRow
                  key={f.value}
                  id={`format-${f.value}`}
                  checked={request.formats.includes(f.value)}
                  onChange={() => actions.toggleFormat(f.value)}
                  label={formatLabel(f.value)}
                  count={f.count}
                />
              ))}
            </ul>
          </Section>
        )}

        <Section title="Published" count={(request.after ? 1 : 0) + (request.before ? 1 : 0)} defaultOpen={Boolean(request.after || request.before)}>
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-[11px] text-zinc-500 dark:text-zinc-400">
              From
              <input
                type="date"
                value={after}
                onChange={(e) => setAfter(e.target.value)}
                className="mt-0.5 h-8 w-full rounded-md border border-zinc-200 bg-white px-2 text-[12px] text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
              />
            </label>
            <label className="block text-[11px] text-zinc-500 dark:text-zinc-400">
              Before
              <input
                type="date"
                value={before}
                onChange={(e) => setBefore(e.target.value)}
                className="mt-0.5 h-8 w-full rounded-md border border-zinc-200 bg-white px-2 text-[12px] text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
              />
            </label>
          </div>
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              disabled={!dateDirty}
              onClick={() => actions.setDates(after || null, before || null)}
              className="btn-brand-soft px-2.5 py-1 text-[11px] disabled:opacity-50"
            >
              Apply dates
            </button>
            {(request.after || request.before) && (
              <button
                type="button"
                onClick={() => {
                  setAfter('');
                  setBefore('');
                  actions.setDates(null, null);
                }}
                className="text-[11px] text-zinc-500 hover:underline dark:text-zinc-400"
              >
                Clear
              </button>
            )}
          </div>
        </Section>
      </div>
    </div>
  );
}
