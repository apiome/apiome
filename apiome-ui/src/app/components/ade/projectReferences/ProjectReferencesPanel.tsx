'use client';

/**
 * The Versions screen's **References** tab — COA-2.8 (#7051).
 *
 * For the chosen revision's OpenAPI document it lists every external `$ref` — the URL, every place
 * it is used, when it was last fetched and its status — plus the document's circular internal
 * references. **Refresh** fetches the references now, under the workspace's external reference
 * policy (shown at the top; administrators can change it here) and the SSRF guard; a reference
 * whose document changed reads **Changed**, with the changes listed under **Show changes**.
 * **Pin** accepts a reference's last fetched document: while pinned, every refresh compares
 * against the pin, so a remote change stays reported until someone pins again.
 */

import { Fragment, useCallback, useEffect, useId, useMemo, useState } from 'react';
import { Link2, Pin, PinOff, RefreshCw, Repeat } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { Label } from '@/app/components/ui/Label';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { formatVersionWithPrefix } from '@/app/utils/version-display';

import { ExternalRefPolicyCard } from './ExternalRefPolicyCard';
import {
  STATUS_LABEL,
  STATUS_TONE,
  fetchProjectReferences,
  formatValue,
  formatWhen,
  pinProjectReference,
  reasonText,
  refreshProjectReferences,
  shortDigest,
  unpinProjectReference,
  type ExternalRefPolicy,
  type ProjectReference,
  type ProjectReferences,
} from './projectReferencesApi';

/** A revision the panel can show (the Versions page's rows). */
export interface ReferencesRevision {
  id: string;
  project_id: string;
  version_id: string;
  published: boolean;
  deleted_at?: string | null;
}

/** Props for {@link ProjectReferencesPanel}. */
export interface ProjectReferencesPanelProps {
  /** The selected project. */
  projectId: string;
  /** The project's revisions. */
  versions: readonly ReferencesRevision[];
  /** The revision to open first, when it is in `versions`. */
  initialRevisionId?: string | null;
}

/**
 * Render the panel. See {@link ProjectReferencesPanelProps}.
 *
 * @returns The panel.
 */
export function ProjectReferencesPanel({ projectId, versions, initialRevisionId }: ProjectReferencesPanelProps) {
  const revisions = useMemo(
    () =>
      versions
        .filter((v) => v.project_id === projectId && !v.deleted_at)
        .sort((a, b) => b.version_id.localeCompare(a.version_id, undefined, { numeric: true })),
    [versions, projectId]
  );
  const [revisionId, setRevisionId] = useState('');
  const [data, setData] = useState<ProjectReferences | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const selectId = useId();

  useEffect(() => {
    if (revisions.length === 0) {
      setRevisionId('');
      return;
    }
    if (!revisionId || !revisions.some((r) => r.id === revisionId)) {
      const initial = revisions.find((r) => r.id === initialRevisionId);
      setRevisionId((initial ?? revisions[0]).id);
    }
  }, [revisions, revisionId, initialRevisionId]);

  useEffect(() => {
    if (!revisionId) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchProjectReferences(projectId, revisionId)
      .then((next) => {
        if (cancelled) return;
        setData(next);
        setError(null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setData(null);
        setError(e instanceof Error ? e.message : 'The references could not be loaded.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, revisionId, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  /** Refresh every reference, or one. */
  const handleRefresh = async (url?: string) => {
    setBusy(url ?? '*');
    setNotice(null);
    try {
      const next = await refreshProjectReferences(projectId, revisionId, url ? [url] : undefined);
      setData(next);
      const changed = next.references.filter((r) => r.status === 'changed').length;
      setNotice(
        changed > 0
          ? `${changed} ${changed === 1 ? 'reference has' : 'references have'} changed. Open Show changes to see what.`
          : `Refreshed ${next.refreshed ?? 0} ${next.refreshed === 1 ? 'reference' : 'references'}.`
      );
      if (url) setOpen((current) => ({ ...current, [url]: true }));
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'The references could not be refreshed.');
    } finally {
      setBusy(null);
    }
  };

  /** Pin or unpin one reference, then reload the list. */
  const handlePin = async (reference: ProjectReference) => {
    setBusy(reference.url);
    setNotice(null);
    try {
      if (reference.pinned) await unpinProjectReference(projectId, reference.url);
      else await pinProjectReference(projectId, reference.url);
      reload();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'The pin could not be changed.');
    } finally {
      setBusy(null);
    }
  };

  const handlePolicySaved = (policy: ExternalRefPolicy) => {
    setData((current) => (current ? { ...current, policy } : current));
  };

  if (revisions.length === 0) {
    return (
      <p className="xstd-empty" data-testid="project-references-no-revisions">
        This project has no revisions yet.
      </p>
    );
  }

  const references = data?.references ?? [];

  return (
    <section className="xstd-stack xstd-panel" data-testid="project-references" aria-label="References">
      <div className="xstd-caps">
        <Link2 aria-hidden />
        References
      </div>
      <p className="hive-quiet">
        The external <span className="xstd-mono">$ref</span>s this revision&apos;s OpenAPI document depends on, when
        each was last fetched, and whether it has changed since. Pin a reference to keep reporting changes against the
        version you accepted.
      </p>

      <div className="xstd-stack xstd-stack--tight">
        <Label htmlFor={selectId}>Revision</Label>
        <select
          id={selectId}
          className="hive-control vovl-select"
          value={revisionId}
          onChange={(event) => setRevisionId(event.target.value)}
          data-testid="project-references-revision"
        >
          {revisions.map((r) => (
            <option key={r.id} value={r.id}>
              {formatVersionWithPrefix(r.version_id)}
              {r.published ? ' (published)' : ' (draft)'}
            </option>
          ))}
        </select>
      </div>

      {loading && !data ? (
        <LoadingState message="Loading references…" data-testid="project-references-loading" />
      ) : error ? (
        <ErrorState title="References could not be loaded" description={error} onRetry={reload} />
      ) : data ? (
        <>
          <ExternalRefPolicyCard policy={data.policy} onSaved={handlePolicySaved} />

          <div className="vovl-actions">
            <Button
              variant="outline"
              onClick={() => void handleRefresh()}
              disabled={busy !== null || references.length === 0}
              title={
                references.length === 0
                  ? 'This revision has no external references'
                  : busy
                    ? 'Wait for the request to finish'
                    : undefined
              }
              data-testid="project-references-refresh-all"
            >
              <RefreshCw className="h-4 w-4" aria-hidden />
              {busy === '*' ? 'Refreshing…' : 'Refresh all'}
            </Button>
            <span className="hive-quiet" data-testid="project-references-summary">
              {references.length} external {references.length === 1 ? 'reference' : 'references'}
              {(Object.entries(data.summary) as Array<[keyof typeof STATUS_LABEL, number]>)
                .filter(([status]) => status !== 'ok')
                .map(([status, count]) => ` · ${count} ${STATUS_LABEL[status].toLowerCase()}`)
                .join('')}
            </span>
          </div>

          {notice ? (
            <p className="xstd-notice" data-tone="accent" role="status" data-testid="project-references-notice">
              {notice}
            </p>
          ) : null}

          {references.length === 0 ? (
            <p className="xstd-empty" data-testid="project-references-empty">
              No external references — this document is self-contained.
            </p>
          ) : (
            <div className="xstd-overlay__ledger">
              <table className="xstd-outcomes" data-testid="project-references-table">
                <thead>
                  <tr>
                    <th scope="col">Reference</th>
                    <th scope="col">Used at</th>
                    <th scope="col">Status</th>
                    <th scope="col">Last fetched</th>
                    <th scope="col">Pinned</th>
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {references.map((reference, index) => (
                    <Fragment key={reference.url}>
                      <ReferenceRow
                        reference={reference}
                        index={index}
                        busy={busy}
                        expanded={!!open[reference.url]}
                        onToggle={() =>
                          setOpen((current) => ({ ...current, [reference.url]: !current[reference.url] }))
                        }
                        onRefresh={() => void handleRefresh(reference.url)}
                        onPin={() => void handlePin(reference)}
                      />
                      {open[reference.url] && reference.diff ? (
                        <tr data-testid={`project-reference-diff-${index}`}>
                          <td colSpan={6}>
                            <ReferenceDiffTable reference={reference} />
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <section
            className="xstd-stack xstd-stack--tight"
            aria-label="Circular references"
            data-testid="project-references-cycles"
          >
            <div className="xstd-caps">
              <Repeat aria-hidden />
              Circular references
            </div>
            {data.cycles.length === 0 ? (
              <p className="hive-quiet">No circular references.</p>
            ) : (
              <>
                <p className="hive-quiet">
                  {data.cycle_total} {data.cycle_total === 1 ? 'loop' : 'loops'} of internal references. They are valid
                  OpenAPI; a dereferenced export keeps the reference that closes each loop.
                </p>
                <ul className="xstd-overlay__list">
                  {data.cycles.map((cycle) => (
                    <li key={cycle.refs.join('|')} className="xstd-mono rfx-cycle">
                      {cycle.path.join(' → ')}
                    </li>
                  ))}
                </ul>
                {data.cycles_truncated ? (
                  <p className="hive-quiet">Only the first {data.cycles.length} loops are listed.</p>
                ) : null}
              </>
            )}
          </section>
        </>
      ) : null}
    </section>
  );
}

/** Props for {@link ReferenceRow}. */
interface ReferenceRowProps {
  reference: ProjectReference;
  index: number;
  busy: string | null;
  expanded: boolean;
  onToggle: () => void;
  onRefresh: () => void;
  onPin: () => void;
}

/**
 * One reference's row: URL, places used, status, last fetch, pin and its actions.
 *
 * @returns The table row.
 */
function ReferenceRow({ reference, index, busy, expanded, onToggle, onRefresh, onPin }: ReferenceRowProps) {
  const why = reasonText(reference);
  const canPin = Boolean(reference.digest);
  return (
    <tr data-testid={`project-reference-${index}`} data-status={reference.status}>
      <td>
        <span className="xstd-mono rfx-url">{reference.url}</span>
      </td>
      <td>
        <details className="rfx-places">
          <summary>
            {reference.locations.length} {reference.locations.length === 1 ? 'place' : 'places'}
          </summary>
          <ul className="rfx-places__list">
            {reference.locations.map((location) => (
              <li key={`${location.location}-${location.ref}`} className="xstd-mono">
                {location.location}
              </li>
            ))}
          </ul>
        </details>
      </td>
      <td>
        <Badge variant={STATUS_TONE[reference.status]} data-testid={`project-reference-status-${index}`}>
          {STATUS_LABEL[reference.status]}
        </Badge>
        {why ? <p className="hive-quiet rfx-reason">{why}</p> : null}
      </td>
      <td>
        {formatWhen(reference.fetched_at)}
        {reference.digest ? <p className="hive-quiet xstd-mono">{shortDigest(reference.digest)}</p> : null}
      </td>
      <td>
        {reference.pinned ? (
          <span className="xstd-mono" title={`Pinned ${formatWhen(reference.pinned.at)}`}>
            {shortDigest(reference.pinned.digest)}
          </span>
        ) : (
          '—'
        )}
      </td>
      <td>
        <div className="rfx-row-actions">
          {reference.diff ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={onToggle}
              aria-expanded={expanded}
              data-testid={`project-reference-toggle-${index}`}
            >
              {expanded ? 'Hide changes' : 'Show changes'}
            </Button>
          ) : null}
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Refresh ${reference.url}`}
            title={busy ? 'Wait for the request to finish' : `Refresh ${reference.url}`}
            disabled={busy !== null}
            onClick={onRefresh}
            data-testid={`project-reference-refresh-${index}`}
          >
            <RefreshCw aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={reference.pinned ? `Unpin ${reference.url}` : `Pin ${reference.url}`}
            title={
              !canPin && !reference.pinned
                ? 'Refresh this reference before pinning it'
                : reference.pinned
                  ? 'Unpin: compare with the previous fetch again'
                  : 'Pin: accept the last fetched document'
            }
            disabled={busy !== null || (!canPin && !reference.pinned)}
            onClick={onPin}
            data-testid={`project-reference-pin-${index}`}
          >
            {reference.pinned ? <PinOff aria-hidden /> : <Pin aria-hidden />}
          </Button>
        </div>
      </td>
    </tr>
  );
}

/**
 * The changes a refresh found in one reference's document.
 *
 * @param props.reference A reference with a `diff`.
 * @returns The table.
 */
function ReferenceDiffTable({ reference }: { reference: ProjectReference }) {
  const diff = reference.diff;
  if (!diff) return null;
  return (
    <div className="xstd-stack xstd-stack--tight rfx-diff">
      <p className="hive-quiet">
        {diff.total} {diff.total === 1 ? 'change' : 'changes'} compared with{' '}
        {diff.against === 'pin' ? 'the pinned document' : 'the previous fetch'} ({shortDigest(diff.from_digest)} →{' '}
        {shortDigest(diff.to_digest)}).
        {diff.truncated ? ` Only the first ${diff.changes.length} are listed.` : ''}
      </p>
      <table className="xstd-outcomes" data-testid="project-reference-changes">
        <thead>
          <tr>
            <th scope="col">Value</th>
            <th scope="col">Change</th>
            <th scope="col">Before</th>
            <th scope="col">After</th>
          </tr>
        </thead>
        <tbody>
          {diff.changes.map((change) => (
            <tr key={`${change.pointer}-${change.kind}`}>
              <td className="xstd-mono">{change.pointer || '/'}</td>
              <td>{change.kind === 'added' ? 'Added' : change.kind === 'removed' ? 'Removed' : 'Changed'}</td>
              <td className="xstd-mono vovl-diff__before">{formatValue(change.before, 'before' in change)}</td>
              <td className="xstd-mono vovl-diff__after">{formatValue(change.after, 'after' in change)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
