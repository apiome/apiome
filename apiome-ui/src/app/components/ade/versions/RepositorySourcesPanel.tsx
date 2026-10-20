'use client';

/**
 * The Sources tab of the Versions dashboard — REPO-5.7 (#2792).
 *
 * A project can source from several repositories (one per service). Every import of a repository
 * file into the project builds a version that merges every contributing file: the importing
 * file's classes and paths, plus everything the other files defined, carried forward. Two files
 * defining the same class or path fail the import — so every class and path here has exactly one
 * source, and this panel shows which:
 *
 * - **Contributing repositories** — each file in precedence order (1 contributed first), with how
 *   many of the chosen version's classes and paths it defines and the version it last went into.
 * - **Provenance** — every class and path of the version with its source file and how it got
 *   there: *Imported* by this version's import, *Carried forward* by a merge, or *Not from a
 *   repository* (edited in Apiome, or imported before multi-repository merge).
 *
 * - **Sync back to repositories** (REPO-5.8, #2793) — {@link PrBackPanel}: render the chosen
 *   version and open a pull request into the files it was imported from.
 *
 * The provenance reads need `projects:view`; opening a pull request needs `versions:publish`.
 */

import * as React from 'react';
import { Boxes, GitMerge, Route } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import {
  DataTable,
  DataTableFilterChip,
  DataTableSearch,
  DataTableToolbar,
  type DataTableColumn,
} from '@/app/components/ui/DataTable';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { FormField } from '@/app/components/ui/FormField';
import { LoadingState } from '@/app/components/ui/LoadingState';
import {
  ENTITY_ORIGIN_LABEL,
  ENTITY_ORIGIN_TONE,
  entityOrigin,
  filterEntities,
  parseRepositorySourcesReply,
  provenanceSummary,
  sourceLabel,
  type EntityProvenance,
  type KindFilter,
  type ProjectRepositorySourcesReply,
  type SourceFilter,
} from '@lib/repository-sources';

import { PrBackPanel } from './PrBackPanel';

/** The part of a version row the panel reads. */
export interface SourcesVersion {
  /** The revision id. */
  id: string;
  /** The version label, e.g. `2.3.1`. */
  version_id: string;
}

export interface RepositorySourcesPanelProps {
  /** The project. */
  projectId: string;
  /** The project's versions, newest first. */
  versions: readonly SourcesVersion[];
  /** Pre-select this revision; the newest otherwise. */
  initialVersionId?: string | null;
}

/** Shown when the sources cannot be read. */
const LOAD_ERROR = 'Could not load the repository sources. Reload the page to try again.';

const KIND_FILTERS: ReadonlyArray<{ value: KindFilter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'class', label: 'Classes' },
  { value: 'path', label: 'Paths' },
];

/** Rows of the provenance table carry a stable id. */
type ProvenanceRow = EntityProvenance & { rowId: string };

const COLUMNS: ReadonlyArray<DataTableColumn<ProvenanceRow>> = [
  {
    id: 'kind',
    header: 'Kind',
    skeletonWidth: '4rem',
    cell: (row) => (
      <Badge variant="neutral" square>
        {row.kind === 'class' ? 'Class' : 'Path'}
      </Badge>
    ),
  },
  {
    id: 'name',
    header: 'Name',
    skeletonWidth: '12rem',
    className: 'rsrc-cell-name',
    cell: (row) => <span className="mono">{row.key}</span>,
  },
  {
    id: 'source',
    header: 'Source',
    skeletonWidth: '16rem',
    className: 'rsrc-cell-source',
    cell: (row) =>
      row.source ? (
        <span className="mono" data-testid="rsrc-entity-source">
          {sourceLabel(row.source)}
        </span>
      ) : (
        <span className="rsrc-muted">—</span>
      ),
  },
  {
    id: 'origin',
    header: 'Origin',
    skeletonWidth: '7rem',
    cell: (row) => {
      const origin = entityOrigin(row);
      return (
        <Badge variant={ENTITY_ORIGIN_TONE[origin]} data-testid={`rsrc-origin-${origin}`}>
          {ENTITY_ORIGIN_LABEL[origin]}
        </Badge>
      );
    },
  },
];

/**
 * The Sources tab.
 *
 * @param props - See {@link RepositorySourcesPanelProps}.
 * @returns The contributing repositories and the version's provenance table.
 */
export function RepositorySourcesPanel({
  projectId,
  versions,
  initialVersionId,
}: RepositorySourcesPanelProps): React.JSX.Element {
  const [versionId, setVersionId] = React.useState<string>(
    () =>
      (initialVersionId && versions.some((v) => v.id === initialVersionId) ? initialVersionId : versions[0]?.id) ?? '',
  );
  const [reply, setReply] = React.useState<ProjectRepositorySourcesReply | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [kind, setKind] = React.useState<KindFilter>('all');
  const [source, setSource] = React.useState<SourceFilter>('all');
  const [query, setQuery] = React.useState('');

  React.useEffect(() => {
    if (!versionId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const response = await fetch(
          `/api/projects/${encodeURIComponent(projectId)}/repository-sources?version=${encodeURIComponent(versionId)}`,
        );
        const payload = await response.json().catch(() => null);
        const parsed = response.ok ? parseRepositorySourcesReply(payload) : null;
        if (cancelled) return;
        if (!parsed) {
          setReply(null);
          setError(
            (payload as { error?: string } | null)?.error || LOAD_ERROR,
          );
        } else {
          setReply(parsed);
        }
      } catch {
        if (!cancelled) setError(LOAD_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, versionId]);

  const rows = React.useMemo<ProvenanceRow[]>(
    () =>
      filterEntities(reply?.entities ?? [], { kind, source, query }).map((entity) => ({
        ...entity,
        rowId: `${entity.kind}:${entity.key}`,
      })),
    [reply, kind, source, query],
  );
  const kindCounts: Record<KindFilter, number> = {
    all: reply?.entities.length ?? 0,
    class: reply?.counts.classes ?? 0,
    path: reply?.counts.paths ?? 0,
  };

  if (versions.length === 0) {
    return (
      <section className="rsrc" data-testid="repository-sources-panel">
        <EmptyState
          className="rsrc-state"
          icon={<GitMerge aria-hidden />}
          title="This project has no versions yet"
          description="Import a repository file to start the project's merged surface."
        />
      </section>
    );
  }

  const sources = reply?.sources ?? [];

  return (
    <section className="rsrc" data-testid="repository-sources-panel">
      <div className="rsrc-toolbar">
        <FormField label="Version" htmlFor="repository-sources-version">
          <select
            id="repository-sources-version"
            className="hive-control rsrc-select"
            value={versionId}
            onChange={(event) => setVersionId(event.target.value)}
            data-testid="repository-sources-version"
          >
            {versions.map((version) => (
              <option key={version.id} value={version.id}>
                {version.version_id}
              </option>
            ))}
          </select>
        </FormField>
        {reply ? (
          <p className="rsrc-summary" data-testid="repository-sources-summary">
            {provenanceSummary(reply)}
          </p>
        ) : null}
      </div>

      {error ? (
        <Alert variant="error" data-testid="repository-sources-error">
          {error}
        </Alert>
      ) : null}

      {loading && !reply ? <LoadingState className="rsrc-state" message="Loading repository sources…" /> : null}

      {reply ? (
        <>
          <div className="rsrc-section">
            <h3 className="rsrc-section__title">Contributing repositories</h3>
            {sources.length === 0 ? (
              <EmptyState
                variant="inline"
                icon={<GitMerge aria-hidden />}
                title="No repository contributes to this project"
                description="Map & import a repository file into this project to start its merged surface."
                titleAs="p"
                data-testid="repository-sources-none"
              />
            ) : (
              <ol className="rsrc-list" data-testid="repository-sources-list">
                {sources.map((row) => (
                  <li key={row.id} className="rsrc-source" data-testid="repository-source">
                    <span className="rsrc-source__rank" aria-label={`Precedence ${row.precedence}`}>
                      {row.precedence}
                    </span>
                    <span className="rsrc-source__name mono">{sourceLabel(row)}</span>
                    <span className="rsrc-source__counts">
                      <Boxes className="rsrc-glyph" aria-hidden />
                      {row.class_count} class{row.class_count === 1 ? '' : 'es'}
                      <Route className="rsrc-glyph" aria-hidden />
                      {row.path_count} path{row.path_count === 1 ? '' : 's'}
                    </span>
                    {row.last_version_label ? (
                      <span className="rsrc-source__last">Last imported into {row.last_version_label}</span>
                    ) : null}
                  </li>
                ))}
              </ol>
            )}
          </div>

          {/* Hides itself when no repository holds the project's files (pre-REPO-5.7 imports included). */}
          <PrBackPanel projectId={projectId} versionId={versionId} versionLabel={reply.version?.version_label} />

          <DataTable
            caption="Where each class and path came from"
            columns={COLUMNS}
            rows={rows}
            getRowId={(row) => row.rowId}
            getRowLabel={(row) => row.key}
            dense
            loading={loading}
            loadingLabel="Loading provenance…"
            data-testid="repository-sources-table"
            toolbar={
              <DataTableToolbar>
                <DataTableSearch
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Filter classes and paths…"
                  aria-label="Filter classes and paths"
                  data-testid="repository-sources-search"
                />
                {KIND_FILTERS.map((entry) => (
                  <DataTableFilterChip
                    key={entry.value}
                    active={kind === entry.value}
                    count={kindCounts[entry.value]}
                    onClick={() => setKind(entry.value)}
                    data-testid={`repository-sources-kind-${entry.value}`}
                  >
                    {entry.label}
                  </DataTableFilterChip>
                ))}
                <select
                  className="hive-control rsrc-select"
                  value={source}
                  onChange={(event) => setSource(event.target.value)}
                  aria-label="Filter by source"
                  data-testid="repository-sources-source-filter"
                >
                  <option value="all">All sources</option>
                  {sources.map((row) => (
                    <option key={row.id} value={row.id}>
                      {sourceLabel(row)}
                    </option>
                  ))}
                  <option value="none">Not from a repository</option>
                </select>
              </DataTableToolbar>
            }
            empty={
              <EmptyState
                variant="compact"
                icon={<GitMerge aria-hidden />}
                title={reply.entities.length === 0 ? 'This version has no classes or paths' : 'Nothing matches these filters'}
                description={
                  reply.entities.length === 0 ? undefined : 'Clear the search box or pick another source.'
                }
              />
            }
          />
        </>
      ) : null}
    </section>
  );
}
