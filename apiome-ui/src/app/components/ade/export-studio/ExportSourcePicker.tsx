'use client';

/**
 * ExportSourcePicker (E1-2, #6218) — Export studio's **Source** step when the studio is opened
 * without a source (the rail, the command palette).
 *
 * Two tabs: **Catalog items** — searched by name, slug, format or protocol, each row showing its
 * format and protocol pills — and **Projects** — a project, then one of its versions (or its latest).
 * Choosing navigates to the studio's resumable deep link (MFX-41.4) at **Target**; the browser's
 * Back returns here. Catalog items are only ever listed as catalog items, never as projects
 * (the Catalog/Projects boundary). The rules are pure, in `exportSourcePicker.ts`.
 *
 * Each list is a plain list of buttons: Tab moves through them, Enter or Space chooses, and every
 * button's name says what it opens.
 */

import * as React from 'react';
import { ChevronLeft, FolderKanban, Package } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { Input } from '@/app/components/ui/Input';
import { FormatPill } from '@/app/components/ui/catalog/FormatPill';
import { ProtocolPill } from '@/app/components/ui/catalog/ProtocolPill';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/app/components/ui/Tabs';
import { normalizeCatalogListItem } from '@/app/utils/catalog-list-item';
import {
  catalogSourceHref,
  filterCatalogSources,
  projectSourceHref,
  selectableProjects,
  selectableVersions,
  SOURCE_PICKER_KINDS,
  type PickerCatalogItem,
  type PickerProject,
  type PickerVersion,
  type SourcePickerKind,
} from './exportSourcePicker';

/** A lazily loaded list. */
type Load<T> = { status: 'idle' | 'loading' } | { status: 'error'; error: string } | { status: 'loaded'; rows: T[] };

/** GET a BFF list and read one array field from it. */
async function readList<T>(url: string, field: string, fallback: string): Promise<T[]> {
  const response = await fetch(url);
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || data.success === false || !Array.isArray(data[field])) {
    throw new Error((data && (data.error || data.detail)) || fallback);
  }
  return data[field] as T[];
}

/**
 * Load a list once `enabled` turns true, with a retry.
 *
 * @param enabled Whether to load (the tab or project is showing).
 * @param load The read.
 * @param key Reloads when it changes (the chosen project).
 * @returns The state and a retry.
 */
function useLazyList<T>(enabled: boolean, load: () => Promise<T[]>, key: string): [Load<T>, () => void] {
  const [state, setState] = React.useState<Load<T>>({ status: 'idle' });
  const [attempt, setAttempt] = React.useState(0);
  React.useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void (async () => {
      setState({ status: 'loading' });
      try {
        const rows = await load();
        if (!cancelled) setState({ status: 'loaded', rows });
      } catch (e) {
        if (!cancelled) setState({ status: 'error', error: e instanceof Error ? e.message : 'Could not load.' });
      }
    })();
    return () => {
      cancelled = true;
    };
    // `load` is rebuilt every render; `key` names what it reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, key, attempt]);
  return [state, () => setAttempt((n) => n + 1)];
}

/**
 * Render the picker.
 *
 * @returns The Source step's tabs and lists.
 */
export function ExportSourcePicker() {
  const router = useRouter();
  const [kind, setKind] = React.useState<SourcePickerKind>('catalog');
  const [query, setQuery] = React.useState('');
  const [project, setProject] = React.useState<PickerProject | null>(null);

  const [catalog, retryCatalog] = useLazyList<PickerCatalogItem>(
    kind === 'catalog',
    async () =>
      (await readList<Record<string, unknown>>('/api/catalog', 'catalog', 'The catalog could not be loaded.')).map(
        (raw) => normalizeCatalogListItem(raw),
      ),
    'catalog',
  );
  const [projects, retryProjects] = useLazyList<PickerProject>(
    kind === 'projects',
    () => readList<PickerProject>('/api/projects', 'projects', 'The projects could not be loaded.'),
    'projects',
  );
  const [versions, retryVersions] = useLazyList<PickerVersion>(
    kind === 'projects' && project !== null,
    () =>
      readList<PickerVersion>(
        `/api/versions?projectId=${encodeURIComponent(project?.id ?? '')}`,
        'versions',
        'The versions could not be loaded.',
      ),
    project?.id ?? '',
  );

  const go = (href: string) => router.push(href);
  const items = catalog.status === 'loaded' ? filterCatalogSources(catalog.rows, query) : [];

  return (
    <div className="xstd-stack" data-testid="export-source-picker">
      <div className="xstd-caps">
        <Package aria-hidden />
        Choose what to export
      </div>
      <div className="xstd-pick__intro">
        Pick a catalog item, or a project and one of its versions. The studio then opens on it at{' '}
        <strong>Target</strong>.
      </div>

      <Tabs value={kind} onValueChange={(value) => setKind(value as SourcePickerKind)}>
        <TabsList aria-label="Kind of source">
          {SOURCE_PICKER_KINDS.map((tab) => (
            <TabsTrigger key={tab.id} value={tab.id} data-testid={`export-source-tab-${tab.id}`}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="catalog" className="xstd-pick">
          <Input
            type="search"
            aria-label="Search catalog items"
            placeholder="Search name, slug, format or protocol"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            data-testid="export-source-search"
          />
          {catalog.status === 'error' ? (
            <ErrorState title="The catalog could not be loaded" description={catalog.error} onRetry={retryCatalog} />
          ) : catalog.status !== 'loaded' ? (
            <div className="xstd-pick__note" role="status">
              Loading catalog items…
            </div>
          ) : items.length === 0 ? (
            <div className="xstd-pick__note" role="status" data-testid="export-source-catalog-empty">
              {query.trim() ? `No catalog item matches “${query.trim()}”.` : 'The catalog is empty.'}
            </div>
          ) : (
            <ul className="xstd-pick__list" aria-label="Catalog items" data-testid="export-source-catalog">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className="xstd-pick__row"
                    aria-label={`Export catalog item ${item.name}`}
                    onClick={() => go(catalogSourceHref(item))}
                    data-testid={`export-source-item-${item.id}`}
                  >
                    <span className="xstd-pick__name">{item.name}</span>
                    {item.slug ? <span className="xstd-pick__sub mono">{item.slug}</span> : null}
                    <span className="xstd-pick__pills">
                      <FormatPill format={item.sourceFormat} />
                      <ProtocolPill protocol={item.protocol} />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </TabsContent>

        <TabsContent value="projects" className="xstd-pick">
          {project ? (
            <>
              <div className="xstd-pick__crumb">
                <Button variant="ghost" size="sm" onClick={() => setProject(null)} data-testid="export-source-change-project">
                  <ChevronLeft aria-hidden />
                  All projects
                </Button>
                <span className="xstd-pick__name">{project.name}</span>
              </div>
              {versions.status === 'error' ? (
                <ErrorState
                  title="The versions could not be loaded"
                  description={versions.error}
                  onRetry={retryVersions}
                />
              ) : versions.status !== 'loaded' ? (
                <div className="xstd-pick__note" role="status">
                  Loading versions…
                </div>
              ) : (
                <ul className="xstd-pick__list" aria-label={`Versions of ${project.name}`} data-testid="export-source-versions">
                  <li>
                    <button
                      type="button"
                      className="xstd-pick__row"
                      aria-label={`Export the latest version of ${project.name}`}
                      onClick={() => go(projectSourceHref(project, null))}
                      data-testid="export-source-version-latest"
                    >
                      <span className="xstd-pick__name">Latest version</span>
                    </button>
                  </li>
                  {selectableVersions(versions.rows).map((version) => (
                    <li key={version.id}>
                      <button
                        type="button"
                        className="xstd-pick__row"
                        aria-label={`Export ${project.name} version ${version.version_id}`}
                        onClick={() => go(projectSourceHref(project, version))}
                        data-testid={`export-source-version-${version.id}`}
                      >
                        <span className="xstd-pick__name mono">{version.version_id}</span>
                        {version.published ? <Badge status="published">Published</Badge> : null}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : projects.status === 'error' ? (
            <ErrorState title="The projects could not be loaded" description={projects.error} onRetry={retryProjects} />
          ) : projects.status !== 'loaded' ? (
            <div className="xstd-pick__note" role="status">
              Loading projects…
            </div>
          ) : selectableProjects(projects.rows).length === 0 ? (
            <div className="xstd-pick__note" role="status" data-testid="export-source-projects-empty">
              There are no projects yet. Convert a catalog item, or import an OpenAPI document as a project.
            </div>
          ) : (
            <ul className="xstd-pick__list" aria-label="Projects" data-testid="export-source-projects">
              {selectableProjects(projects.rows).map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    className="xstd-pick__row"
                    aria-label={`Choose a version of ${row.name}`}
                    onClick={() => setProject(row)}
                    data-testid={`export-source-project-${row.id}`}
                  >
                    <FolderKanban aria-hidden className="xstd-pick__glyph" />
                    <span className="xstd-pick__name">{row.name}</span>
                    {row.slug ? <span className="xstd-pick__sub mono">{row.slug}</span> : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
