'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useMemo, useState } from 'react';
import type { BrowseFacetAxis, BrowseFacetSelection } from '../../lib/browseFacets';
import {
  NO_FACET_SELECTION,
  computeFacetOptions,
  describeFacetSelection,
  filterByFacets,
  hasFacetSelection,
  toggleFacet,
} from '../../lib/browseFacets';
import {
  SUPPORTED_FORMATS_DOC_URL,
  describeFormatSurface,
  describeParadigms,
} from '../../lib/formatSurface';
import { AppShell } from './components/AppShell';
import { DataTable } from './components/DataTable';
import { DiscoveryRail } from './components/DiscoveryRail';
import { FacetFilter, FacetValueChips } from './components/FacetFilter';
import { SpecCard } from './components/SpecCard';
import { SearchBox } from './components/search/SearchBox';
import { OperatorChips } from './components/search/SyntaxHelp';
import { MethodBadge } from './components/search/httpMethodTone';
import { pushRecentSearch } from './components/search/searchPaletteBus';
import { toSearchParams, type SearchUrlState } from '../../lib/search/params';

const HERO_EXAMPLES: { label: string; q: string }[] = [
  { label: 'POST operations', q: 'method:POST' },
  { label: 'Order schemas', q: 'type:schema order' },
  { label: 'Payments', q: 'payments' },
  { label: 'Webhooks', q: '"webhook"' },
];

const HERO_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];

function searchUrl(state: SearchUrlState): string {
  const qs = toSearchParams(state);
  return qs ? `/search?${qs}` : '/search';
}

interface Tenant {
  id: string;
  name: string;
  slug: string;
  description?: string;
  created_at?: string;
  /**
   * Distinct paradigms this organization publishes, under the stored column's name (MFI-6.1).
   */
  protocols?: string[] | null;
  /** Distinct source formats this organization publishes (MFI-6.1). */
  formats?: string[] | null;
}

interface RecentVersion {
  id: string;
  version_id: string;
  description?: string;
  published_at?: string;
  project_name: string;
  project_slug: string;
  project_description?: string;
  tenant_name: string;
  tenant_slug: string;
}

interface PopularProject {
  id: string;
  name: string;
  slug: string;
  description?: string;
  tenant_name: string;
  tenant_slug: string;
  version_count: number;
  latest_published_at?: string;
}

interface HomeClientProps {
  tenants: Tenant[];
  recentVersions: RecentVersion[];
  popularProjects: PopularProject[];
  newestTenants: Tenant[];
}

function relativeTime(iso?: string): string | undefined {
  if (!iso) return undefined;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return undefined;
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.round(months / 12)}y ago`;
}

function monogram(name: string): string {
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() ?? '').join('') || name[0]?.toUpperCase() || '?';
}

export function HomeClient({
  tenants,
  recentVersions,
  popularProjects,
  newestTenants,
}: HomeClientProps) {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [facets, setFacets] = useState<BrowseFacetSelection>(NO_FACET_SELECTION);

  const onToggleFacet = useCallback((axis: BrowseFacetAxis, value: string) => {
    setFacets((current) => toggleFacet(current, axis, value));
  }, []);

  const onClearFacets = useCallback(() => setFacets(NO_FACET_SELECTION), []);

  // Counts are over the whole directory and ignore the current selection, so the chip row always
  // shows what else is available to pick (the same contract the /v1/browse API's facets have).
  const paradigmOptions = useMemo(() => computeFacetOptions(tenants, 'paradigm'), [tenants]);
  const formatOptions = useMemo(() => computeFacetOptions(tenants, 'format'), [tenants]);
  const filteredTenants = useMemo(() => filterByFacets(tenants, facets), [tenants, facets]);
  const facetsActive = hasFacetSelection(facets);

  const onSubmit = () => {
    const q = query.trim();
    if (q) pushRecentSearch(q);
    router.push(searchUrl(q ? { q } : {}));
  };

  const insertOperator = (operator: string) => {
    const base = query.trimEnd();
    setQuery(operator === '"phrase"' ? `${base} ""`.trimStart() : operator === '-word' ? `${base} -`.trimStart() : `${base} ${operator}`.trimStart());
  };

  return (
    <>
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-zinc-200/80 bg-gradient-to-b from-white to-zinc-50 py-12 sm:py-16 dark:border-zinc-800/80 dark:from-zinc-950 dark:to-zinc-950/40">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 -z-0 h-72 bg-[radial-gradient(ellipse_at_top_left,rgba(16,128,208,0.10),transparent_55%),radial-gradient(ellipse_at_top_right,rgba(242,196,28,0.10),transparent_55%)] dark:bg-[radial-gradient(ellipse_at_top_left,rgba(46,151,221,0.16),transparent_55%),radial-gradient(ellipse_at_top_right,rgba(242,196,28,0.09),transparent_55%)]"
        />
        <div aria-hidden="true" className="pointer-events-none absolute -left-10 top-8 -z-0 hidden lg:block">
          <div className="hex h-40 w-36 rotate-6 bg-gradient-to-br from-sky-500/15 to-sky-500/0 dark:from-sky-400/15" />
          <div className="hex -mt-10 ml-24 h-24 w-[5.5rem] -rotate-3 bg-gradient-to-br from-amber-400/25 to-amber-400/0 dark:from-amber-400/15" />
        </div>
        <div aria-hidden="true" className="pointer-events-none absolute -right-8 bottom-4 -z-0 hidden lg:block">
          <div className="hex h-36 w-32 -rotate-6 bg-gradient-to-tl from-blue-700/15 to-blue-700/0 dark:from-blue-400/10" />
          <div className="hex -mt-24 -ml-16 h-20 w-[4.5rem] rotate-12 bg-gradient-to-br from-amber-400/20 to-amber-400/0 dark:from-amber-400/10" />
        </div>
        <AppShell>
          <div className="relative mx-auto max-w-3xl text-center">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-zinc-200/80 bg-white/80 px-3 py-1 text-[12px] font-medium text-zinc-600 shadow-xs backdrop-blur dark:border-zinc-800/80 dark:bg-zinc-900/60 dark:text-zinc-400">
              <span aria-hidden="true" className="hex inline-block h-2 w-2 bg-[var(--gold)]"></span>
              Public API specification directory
            </div>
            <h1 className="text-balance text-[2rem] font-semibold tracking-tight text-zinc-900 sm:text-[2.5rem] dark:text-zinc-50">
              Discover, browse, and compare{' '}
              <span className="bg-gradient-to-r from-[var(--brand-navy)] via-[#1080d0] to-[var(--brand)] bg-clip-text text-transparent dark:from-sky-300 dark:via-sky-400 dark:to-sky-500">
                public API specifications
              </span>
            </h1>
            <p className="mx-auto mt-3 max-w-xl text-pretty text-[15px] leading-relaxed text-zinc-600 dark:text-zinc-400">
              An always-current directory of API descriptions published by organizations on Apiome —
              across {describeParadigms()}.
            </p>
            <p className="mx-auto mt-2 max-w-xl text-pretty text-[13px] leading-relaxed text-zinc-500 dark:text-zinc-500">
              Apiome reads and writes {describeFormatSurface()}.{' '}
              <a
                href={SUPPORTED_FORMATS_DOC_URL}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-[var(--brand)] transition-colors hover:underline"
              >
                See every supported format
              </a>
              .
            </p>

            <div className="mx-auto mt-7 max-w-2xl space-y-3 text-left">
              <SearchBox
                value={query}
                onChange={setQuery}
                onSubmit={onSubmit}
                placeholder="Search operations, schemas, projects, organizations…"
                label="Search the public catalog"
              />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-400 dark:text-zinc-500">Try</span>
                  {HERO_EXAMPLES.map((ex) => (
                    <button
                      key={ex.q}
                      type="button"
                      onClick={() => {
                        pushRecentSearch(ex.q);
                        router.push(searchUrl({ q: ex.q }));
                      }}
                      className="rounded-full border border-zinc-200 bg-white/80 px-2.5 py-0.5 text-[12px] text-zinc-600 shadow-xs transition-colors hover:border-[var(--brand)] hover:text-[var(--brand)] dark:border-zinc-700 dark:bg-zinc-900/60 dark:text-zinc-300"
                      title={ex.q}
                    >
                      {ex.label}
                    </button>
                  ))}
                </div>
                <OperatorChips onInsert={insertOperator} compact />
              </div>
            </div>
          </div>
        </AppShell>
      </section>

      {/* Discovery rails */}
      <AppShell containerSize="wide">
        <div className="space-y-10 py-10">
          {/* Browse by: one click into a filter-only search */}
          <section aria-labelledby="browse-by-heading" className="space-y-3">
            <div>
              <h2 id="browse-by-heading" className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
                Browse by
              </h2>
              <p className="mt-0.5 text-[13px] text-zinc-500 dark:text-zinc-400">
                Every tile is a search — add words or filters once you are there.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <Link
                href={searchUrl({ type: 'operation' })}
                className="group flex items-start gap-3 rounded-xl border border-zinc-200 bg-white p-4 shadow-xs transition-all hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-sky-800"
              >
                <div className="hex flex h-10 w-10 shrink-0 items-center justify-center bg-gradient-to-br from-emerald-500/25 to-emerald-500/5 text-emerald-700 dark:text-emerald-300">
                  <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </div>
                <div className="min-w-0">
                  <div className="text-[15px] font-semibold text-zinc-900 group-hover:text-[var(--brand)] dark:text-zinc-50">Operations</div>
                  <p className="mt-0.5 text-[13px] text-zinc-600 dark:text-zinc-400">Every endpoint across the latest published versions, by method and path.</p>
                  <div className="mt-2 flex flex-wrap gap-1.5" aria-label="By HTTP method">
                    {HERO_METHODS.map((m) => (
                      <span key={m} className="pointer-events-none">
                        <MethodBadge method={m} size="sm" />
                      </span>
                    ))}
                  </div>
                </div>
              </Link>
              <Link
                href={searchUrl({ type: 'schema' })}
                className="group flex items-start gap-3 rounded-xl border border-zinc-200 bg-white p-4 shadow-xs transition-all hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-sky-800"
              >
                <div className="hex flex h-10 w-10 shrink-0 items-center justify-center bg-gradient-to-br from-violet-500/25 to-violet-500/5 text-violet-700 dark:text-violet-300">
                  <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                  </svg>
                </div>
                <div className="min-w-0">
                  <div className="text-[15px] font-semibold text-zinc-900 group-hover:text-[var(--brand)] dark:text-zinc-50">Schemas &amp; models</div>
                  <p className="mt-0.5 text-[13px] text-zinc-600 dark:text-zinc-400">Data models and their properties, searchable by name, description and field.</p>
                </div>
              </Link>
              <Link
                href={searchUrl({ scope: 'catalog', type: 'version', all: '1' })}
                className="group flex items-start gap-3 rounded-xl border border-zinc-200 bg-white p-4 shadow-xs transition-all hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-sky-800"
              >
                <div className="hex flex h-10 w-10 shrink-0 items-center justify-center bg-gradient-to-br from-amber-400/35 to-amber-400/10 text-amber-700 dark:text-amber-300">
                  <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a3 3 0 11-6 0 3 3 0 016 0zM6 21l5-5m0 0l5 5m-5-5V3" />
                  </svg>
                </div>
                <div className="min-w-0">
                  <div className="text-[15px] font-semibold text-zinc-900 group-hover:text-[var(--brand)] dark:text-zinc-50">Versions &amp; release notes</div>
                  <p className="mt-0.5 text-[13px] text-zinc-600 dark:text-zinc-400">Every published version, newest first, with its notes and changelog.</p>
                </div>
              </Link>
            </div>
            {(paradigmOptions.length > 0 || formatOptions.length > 0) && (
              <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                <span className="mr-1 font-medium uppercase tracking-wider text-zinc-400 dark:text-zinc-500">Or by</span>
                {paradigmOptions.map((o) => (
                  <Link key={`p-${o.value}`} href={searchUrl({ paradigm: o.value })} className="rounded-full border border-zinc-200 bg-white px-2.5 py-0.5 text-zinc-600 shadow-xs transition-colors hover:border-[var(--brand)] hover:text-[var(--brand)] dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
                    {o.label} <span className="tabular-nums text-zinc-400">{o.count}</span>
                  </Link>
                ))}
                {formatOptions.slice(0, 8).map((o) => (
                  <Link key={`f-${o.value}`} href={searchUrl({ format: o.value })} className="rounded-full border border-zinc-200 bg-white px-2.5 py-0.5 text-zinc-600 shadow-xs transition-colors hover:border-[var(--brand)] hover:text-[var(--brand)] dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
                    {o.label} <span className="tabular-nums text-zinc-400">{o.count}</span>
                  </Link>
                ))}
              </div>
            )}
          </section>

          <DiscoveryRail
            title="Recently published"
            description="Latest version updates across the directory."
            seeAllHref={searchUrl({ scope: 'catalog', type: 'version', all: '1' })}
            itemCount={recentVersions.length}
            emptyMessage="No versions have been published yet."
          >
            {recentVersions.map((v) => (
              <div key={v.id} className="w-[300px] shrink-0">
                <SpecCard
                  variant="version"
                  href={`/tenant/${v.tenant_slug}/${v.project_slug}/${v.version_id}`}
                  title={`v${v.version_id}`}
                  subtitle={v.project_name}
                  description={v.description || v.project_description || `Published by ${v.tenant_name}`}
                  badge={
                    relativeTime(v.published_at)
                      ? { label: relativeTime(v.published_at) as string, tone: 'success' }
                      : undefined
                  }
                  meta={[{ label: v.tenant_name }, { label: v.project_name }]}
                />
              </div>
            ))}
          </DiscoveryRail>

          <DiscoveryRail
            title="Most active projects"
            description="Projects with the largest published version history."
            seeAllHref="#organizations"
            seeAllLabel="Browse all"
            itemCount={popularProjects.length}
            emptyMessage="No projects to highlight yet."
          >
            {popularProjects.map((p) => (
              <div key={p.id} className="w-[300px] shrink-0">
                <SpecCard
                  variant="project"
                  href={`/tenant/${p.tenant_slug}/${p.slug}`}
                  title={p.name}
                  subtitle={p.tenant_name}
                  description={p.description}
                  badge={{
                    label: `${p.version_count} ${p.version_count === 1 ? 'version' : 'versions'}`,
                    tone: 'brand',
                  }}
                  meta={
                    p.latest_published_at
                      ? [{ label: 'Updated', value: relativeTime(p.latest_published_at) }]
                      : undefined
                  }
                />
              </div>
            ))}
          </DiscoveryRail>

          <DiscoveryRail
            title="New organizations"
            description="The most recently onboarded publishers."
            seeAllHref="#organizations"
            seeAllLabel="Browse all"
            itemCount={newestTenants.length}
            emptyMessage="No organizations yet."
          >
            {newestTenants.map((t) => (
              <div key={t.id} className="w-[280px] shrink-0">
                <SpecCard
                  variant="tenant"
                  href={`/tenant/${t.slug}`}
                  title={t.name}
                  subtitle={`/${t.slug}`}
                  description={t.description}
                  monogram={monogram(t.name)}
                  meta={
                    t.created_at
                      ? [{ label: 'Joined', value: relativeTime(t.created_at) }]
                      : undefined
                  }
                />
              </div>
            ))}
          </DiscoveryRail>

          {/* Organization directory */}
          <section id="organizations" className="scroll-mt-20 space-y-4 pt-4">
            <header className="flex flex-wrap items-end justify-between gap-3 border-t border-zinc-200/80 pt-8 dark:border-zinc-800/80">
              <div>
                <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
                  All organizations
                </h2>
                <p className="mt-0.5 text-[13px] text-zinc-500 dark:text-zinc-400">
                  {facetsActive
                    ? `${filteredTenants.length} of ${tenants.length} organization${
                        tenants.length === 1 ? '' : 's'
                      } publish ${describeFacetSelection(facets)}.`
                    : `${tenants.length} organization${
                        tenants.length === 1 ? '' : 's'
                      } with at least one published public specification.`}
                </p>
              </div>
            </header>

            <FacetFilter
              paradigmOptions={paradigmOptions}
              formatOptions={formatOptions}
              selection={facets}
              onToggle={onToggleFacet}
              onClear={onClearFacets}
              entityLabel="organizations"
            />

            <DataTable
              data={filteredTenants}
              keyField="id"
              getRowHref={(tenant) => `/tenant/${tenant.slug}`}
              searchable={true}
              searchPlaceholder="Filter organizations..."
              searchFields={['name', 'slug', 'description']}
              emptyMessage={
                facetsActive
                  ? 'No organizations publish the selected protocol/format.'
                  : 'No organizations with published specifications available.'
              }
              columns={[
                {
                  key: 'name',
                  header: 'Organization',
                  sortable: true,
                  render: (tenant) => (
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-sky-500/15 to-sky-500/5 text-[12px] font-semibold text-sky-700 ring-1 ring-inset ring-sky-500/30 dark:text-sky-300">
                        {monogram(tenant.name)}
                      </div>
                      <div className="min-w-0">
                        <div className="truncate font-medium text-zinc-900 group-hover:text-[var(--brand)] dark:text-zinc-50">
                          {tenant.name}
                        </div>
                        <div className="truncate text-xs text-zinc-500 dark:text-zinc-400">
                          /{tenant.slug}
                        </div>
                      </div>
                    </div>
                  ),
                },
                {
                  key: 'description',
                  header: 'Description',
                  render: (tenant) => (
                    <span className="line-clamp-2 text-zinc-600 dark:text-zinc-400">
                      {tenant.description || '—'}
                    </span>
                  ),
                },
                {
                  key: 'protocols',
                  header: 'Publishes',
                  width: 'w-48',
                  render: (tenant) => (
                    <FacetValueChips protocols={tenant.protocols} formats={tenant.formats} />
                  ),
                },
                {
                  key: 'created_at',
                  header: 'Joined',
                  width: 'w-32',
                  sortable: true,
                  render: (tenant) => (
                    <span className="text-zinc-500 dark:text-zinc-400">
                      {tenant.created_at ? new Date(tenant.created_at).toLocaleDateString() : '—'}
                    </span>
                  ),
                },
                {
                  key: 'actions',
                  header: '',
                  width: 'w-12',
                  render: () => (
                    <svg
                      className="h-4 w-4 text-zinc-400 transition-colors group-hover:text-[var(--brand)]"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2}
                      viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                    </svg>
                  ),
                },
              ]}
            />
          </section>
        </div>
      </AppShell>
    </>
  );
}
