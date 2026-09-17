'use client';

/**
 * The Repository tab of the Versions dashboard — GNC-2.1 (#4737).
 *
 * Importing a spec from a repository leaves a snapshot. **Binding** leaves a relationship: one
 * draft version becomes the API review unit of one repository ref and source path, and the digest
 * of the files that selection resolved to is remembered as the base later pushes are measured
 * against.
 *
 * The panel is built around the one rule that makes the feature safe: **a ref update is never a
 * change**. When a bound branch moves — through a provider webhook, or because somebody pressed
 * "Check for updates" here — a *sync candidate* appears, saying which commit the branch left and
 * which it arrived at. The draft is untouched until somebody applies or dismisses it, and
 * whichever they choose is recorded.
 *
 * Every rule about who may do this lives in apiome-rest: reading needs `projects:view`, every
 * write needs `versions:edit`, and binding additionally has to *prove* the tenant's stored
 * credential can read the repository before a row is written. The panel shows what comes back.
 *
 * Deciding *what a movement actually changed* is the Synchronization section below it
 * ({@link VersionSyncPanel}, GNC-2.3), which merges the three documents and shows the collisions —
 * and which likewise never rewrites the draft.
 */

import * as React from 'react';
import { ArrowUpRight, GitBranch, Link2Off, RefreshCw } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { formatRelativeWhen } from '@/app/components/ade/repositories/repositoryDetailModel';
import { VersionSyncPanel } from './VersionSyncPanel';
import { cn } from '@lib/utils';
import {
  BINDING_STATE_LABEL,
  BINDING_STATE_TONE,
  CANDIDATE_STATUS_LABEL,
  CANDIDATE_STATUS_TONE,
  bindingErrorMessage,
  bindingState,
  bindingSummary,
  candidateContentChanged,
  candidateSentence,
  shortSha,
  type DraftBinding,
  type ResolvableStatus,
  type SyncCandidate,
  type VersionBindingStatus,
} from '@lib/draft-bindings';

/** The part of a version row the panel reads. */
export interface BindableVersion {
  /** The revision id the binding hangs on. */
  id: string;
  /** The version label, e.g. `2.3.1`. */
  version_id: string;
  /** Published versions cannot be bound; an existing binding stays readable. */
  published?: boolean;
}

/** A registered repository, as `/api/repositories` returns it. */
interface RepositoryOption {
  id: string;
  repository_full_name?: string | null;
  clone_url?: string | null;
  default_branch?: string | null;
}

export interface VersionBindingPanelProps {
  /** The project whose versions can be bound. */
  projectId: string;
  /** The project's versions, newest first. */
  versions: readonly BindableVersion[];
  /** Pre-select this revision; the first draft otherwise. */
  initialVersionId?: string | null;
  /** Reference time for relative dates, in epoch ms; tests pin it. Defaults to mount time. */
  now?: number;
}

/** What the BFF routes answer with. */
type Envelope = Record<string, unknown> & { success?: boolean; error?: string; code?: string };

/**
 * Call a binding BFF route and parse its envelope.
 *
 * @param url - The route.
 * @param init - Fetch options.
 * @returns The parsed envelope.
 */
async function callBindings(url: string, init?: RequestInit): Promise<Envelope> {
  const response = await fetch(url, init);
  const payload = (await response.json().catch(() => ({}))) as Envelope;
  return payload;
}

/**
 * One binding's facts, as a definition list.
 *
 * @param props.binding - The binding.
 * @param props.now - Reference time for relative dates.
 */
function BindingFacts({ binding, now }: { binding: DraftBinding; now: number }) {
  // The card's head already names repository, ref and path; these are the facts it does not carry.
  return (
    <dl className="bnd-facts">
      <div className="bnd-facts__row">
        <dt>Commit</dt>
        <dd className="mono" data-testid="binding-commit">
          {shortSha(binding.commit_sha)}
        </dd>
      </div>
      <div className="bnd-facts__row">
        <dt>Source digest</dt>
        <dd className="mono bnd-facts__digest" title={binding.source_digest}>
          {binding.source_digest}
        </dd>
      </div>
      <div className="bnd-facts__row">
        <dt>In sync since</dt>
        <dd>
          <time dateTime={binding.synchronized_at} title={binding.synchronized_at}>
            {formatRelativeWhen(binding.synchronized_at, now)}
          </time>
        </dd>
      </div>
    </dl>
  );
}

/**
 * One outstanding sync candidate, with the two decisions it accepts.
 *
 * @param props.candidate - The candidate.
 * @param props.busy - True while a decision is in flight.
 * @param props.onResolve - Called with the decision the reader chose.
 * @param props.now - Reference time for relative dates.
 */
function PendingCandidate({
  candidate,
  busy,
  onResolve,
  now,
}: {
  candidate: SyncCandidate;
  busy: boolean;
  onResolve: (status: ResolvableStatus) => void;
  now: number;
}) {
  const changed = candidateContentChanged(candidate);
  return (
    <li className="bnd-candidate" data-testid={`binding-candidate-${candidate.id}`}>
      <p className="bnd-candidate__what">{candidateSentence(candidate)}</p>
      <p className="bnd-candidate__meta">
        <time dateTime={candidate.detected_at} title={candidate.detected_at}>
          {formatRelativeWhen(candidate.detected_at, now)}
        </time>
        <span aria-hidden>·</span>
        <span data-testid="binding-candidate-content">
          {changed === null
            ? 'The files at that commit have not been read yet'
            : changed
              ? 'The selected files differ from the bound source'
              : 'The selected files are identical to the bound source'}
        </span>
      </p>
      <div className="bnd-candidate__actions">
        <Button size="sm" disabled={busy} onClick={() => onResolve('applied')}>
          Mark in sync
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => onResolve('dismissed')}>
          Dismiss
        </Button>
      </div>
    </li>
  );
}

/**
 * The Repository tab: bind a draft to a branch, and decide what happens when that branch moves.
 *
 * @param props - See {@link VersionBindingPanelProps}.
 */
export function VersionBindingPanel({
  projectId,
  versions,
  initialVersionId,
  now,
}: VersionBindingPanelProps) {
  // A lazy initializer rather than a call in the render body: the clock is read once, at mount,
  // so a re-render never shifts every relative date on the screen.
  const [mountedAt] = React.useState(() => Date.now());
  const reference = now ?? mountedAt;

  // The first draft is what a reader almost always means: a published version cannot be bound,
  // and binding is an activity of the version being worked on.
  const defaultVersionId = React.useMemo(() => {
    if (initialVersionId && versions.some((version) => version.id === initialVersionId)) {
      return initialVersionId;
    }
    return versions.find((version) => !version.published)?.id ?? versions[0]?.id ?? '';
  }, [initialVersionId, versions]);

  const [versionId, setVersionId] = React.useState(defaultVersionId);
  React.useEffect(() => setVersionId(defaultVersionId), [defaultVersionId]);

  const [status, setStatus] = React.useState<VersionBindingStatus | null>(null);
  const [repositories, setRepositories] = React.useState<RepositoryOption[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const [repositoryId, setRepositoryId] = React.useState('');
  const [ref, setRef] = React.useState('');
  const [path, setPath] = React.useState('');

  const base = `/api/projects/${encodeURIComponent(projectId)}/bindings`;
  const query = `?version=${encodeURIComponent(versionId)}`;

  const load = React.useCallback(async () => {
    if (!versionId) return;
    setLoading(true);
    setError(null);
    const payload = await callBindings(`${base}${query}`);
    setLoading(false);
    if (payload.success) {
      setStatus(payload as unknown as VersionBindingStatus);
    } else {
      setStatus(null);
      setError(bindingErrorMessage(payload.code, payload.error ?? 'The binding could not be read'));
    }
  }, [base, query, versionId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  React.useEffect(() => {
    let cancelled = false;
    void (async () => {
      const payload = await callBindings('/api/repositories');
      const rows = Array.isArray(payload.repositories) ? (payload.repositories as RepositoryOption[]) : [];
      if (!cancelled) setRepositories(rows);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /**
   * Run a write and fold its answer back into the panel.
   *
   * @param url - The route.
   * @param init - Fetch options.
   * @param success - What to say when it worked.
   */
  const write = React.useCallback(
    async (url: string, init: RequestInit, success: string) => {
      setBusy(true);
      setError(null);
      setNotice(null);
      const payload = await callBindings(url, init);
      setBusy(false);
      if (payload.success) {
        setNotice(success);
        await load();
        return;
      }
      setError(bindingErrorMessage(payload.code, payload.error ?? 'The request failed'));
    },
    [load]
  );

  const selectedRepository = repositories.find((row) => row.id === repositoryId);
  const binding = status?.binding?.binding ?? null;
  const pending = status?.binding?.pending ?? [];
  const settled = status?.binding?.history ?? [];
  const released = status?.released ?? [];

  const bind = () =>
    write(
      `${base}${query}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repository_id: repositoryId,
          ref: ref.trim(),
          path: path.trim(),
          replace: Boolean(binding),
        }),
      },
      binding ? 'Bound to the new branch. The previous binding is kept as history.' : 'Bound.'
    );

  if (versions.length === 0) {
    return (
      <section className="bnd" data-testid="version-binding-panel">
        <EmptyState
          className="bnd-state"
          title="This project has no versions yet"
          description="Create a version first; a binding makes one draft the review unit of a branch."
        />
      </section>
    );
  }

  return (
    <section className="bnd" data-testid="version-binding-panel">
      <div className="bnd-toolbar">
        <FormField label="Version" htmlFor="binding-version">
          <select
            id="binding-version"
            className="hive-control bnd-select"
            value={versionId}
            onChange={(event) => setVersionId(event.target.value)}
            data-testid="binding-version-select"
          >
            {versions.map((version) => (
              <option key={version.id} value={version.id}>
                {version.version_id}
                {version.published ? ' (published)' : ''}
              </option>
            ))}
          </select>
        </FormField>
        {binding ? (
          <div className="bnd-toolbar__actions">
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() =>
                write(`${base}/check${query}`, { method: 'POST' }, 'Checked. A new commit was found.')
              }
              data-testid="binding-check"
            >
              <RefreshCw aria-hidden />
              Check for updates
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() =>
                write(`${base}${query}`, { method: 'DELETE' }, 'Released. The binding is kept as history.')
              }
              data-testid="binding-release"
            >
              <Link2Off aria-hidden />
              Release
            </Button>
          </div>
        ) : null}
      </div>

      {error ? (
        <Alert variant="error" data-testid="binding-error">
          {error}
        </Alert>
      ) : null}
      {notice ? (
        <Alert variant="success" data-testid="binding-notice">
          {notice}
        </Alert>
      ) : null}

      {loading ? <LoadingState className="bnd-state" message="Loading the repository binding…" /> : null}

      {!loading && status && binding ? (
        <div className="bnd-card" data-testid="binding-card">
          <div className="bnd-card__head">
            <GitBranch className="bnd-card__glyph" aria-hidden />
            <span className="bnd-card__title mono">{bindingSummary(binding)}</span>
            <Badge variant={BINDING_STATE_TONE[bindingState(binding)] as 'success'}>
              {BINDING_STATE_LABEL[bindingState(binding)]}
            </Badge>
            {binding.browse_url ? (
              <a className="bnd-card__link" href={binding.browse_url} target="_blank" rel="noreferrer">
                Browse source
                <ArrowUpRight className="bnd-card__glyph" aria-hidden />
              </a>
            ) : null}
          </div>
          <BindingFacts binding={binding} now={reference} />
        </div>
      ) : null}

      {!loading && status && !binding ? (
        <EmptyState
          className="bnd-state"
          title="This version is not bound to a branch"
          description="Bind it to make one repository ref and source path the review unit of this draft."
        />
      ) : null}

      {!loading && status && !status.published ? (
        <form
          className="bnd-form"
          data-testid="binding-form"
          onSubmit={(event) => {
            event.preventDefault();
            void bind();
          }}
        >
          <h3 className="bnd-form__title">{binding ? 'Bind somewhere else' : 'Bind this draft'}</h3>
          <div className="bnd-form__grid">
            <FormField
              label="Repository"
              htmlFor="binding-repository"
              helperText="Registered repositories only — the stored credential is what authorizes the read."
            >
              <select
                id="binding-repository"
                className="hive-control bnd-select"
                value={repositoryId}
                disabled={busy || repositories.length === 0}
                onChange={(event) => setRepositoryId(event.target.value)}
                data-testid="binding-repository-select"
              >
                <option value="">
                  {repositories.length === 0 ? 'No repositories registered' : 'Select a repository…'}
                </option>
                {repositories.map((repository) => (
                  <option key={repository.id} value={repository.id}>
                    {repository.repository_full_name || repository.clone_url || repository.id}
                  </option>
                ))}
              </select>
            </FormField>
            <FormField
              label="Branch"
              htmlFor="binding-ref"
              helperText={
                selectedRepository?.default_branch
                  ? `Defaults to ${selectedRepository.default_branch}.`
                  : "Defaults to the repository's default branch."
              }
            >
              <Input
                id="binding-ref"
                value={ref}
                disabled={busy}
                placeholder={selectedRepository?.default_branch ?? 'main'}
                onChange={(event) => setRef(event.target.value)}
                data-testid="binding-ref-input"
              />
            </FormField>
            <FormField
              label="Source path"
              htmlFor="binding-path"
              helperText="A file, a directory, or a glob. Empty selects the whole tree."
            >
              <Input
                id="binding-path"
                value={path}
                disabled={busy}
                placeholder="spec/openapi.yaml"
                onChange={(event) => setPath(event.target.value)}
                data-testid="binding-path-input"
              />
            </FormField>
          </div>
          <Button type="submit" disabled={busy || !repositoryId} data-testid="binding-submit">
            {binding ? 'Replace binding' : 'Bind'}
          </Button>
        </form>
      ) : null}

      {!loading && status?.published && !binding ? (
        <p className="bnd-note">A published version cannot be bound to a branch.</p>
      ) : null}

      {pending.length > 0 ? (
        <div className="bnd-section" data-testid="binding-pending">
          <h3 className="bnd-section__title">Waiting for a decision</h3>
          <p className="bnd-section__note">
            The branch moved. Nothing about this draft has changed — say what should happen.
          </p>
          <ul className="bnd-list">
            {pending.map((candidate) => (
              <PendingCandidate
                key={candidate.id}
                candidate={candidate}
                busy={busy}
                now={reference}
                onResolve={(resolution) =>
                  void write(
                    `${base}/candidates/${encodeURIComponent(candidate.id)}${query}`,
                    {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ status: resolution }),
                    },
                    resolution === 'applied'
                      ? 'Recorded as in sync with that commit.'
                      : 'Dismissed. The binding is unchanged.'
                  )
                }
              />
            ))}
          </ul>
        </div>
      ) : null}

      {binding ? (
        <VersionSyncPanel
          projectId={projectId}
          versionId={versionId}
          bound={Boolean(binding)}
          now={now}
        />
      ) : null}

      {settled.length > 0 ? (
        <div className="bnd-section" data-testid="binding-history">
          <h3 className="bnd-section__title">Settled updates</h3>
          <ul className="bnd-list">
            {settled.map((candidate) => (
              <li key={candidate.id} className="bnd-settled">
                <span className="bnd-settled__what">{candidateSentence(candidate)}</span>
                <Badge variant={CANDIDATE_STATUS_TONE[candidate.status] as 'success'}>
                  {CANDIDATE_STATUS_LABEL[candidate.status]}
                </Badge>
                {candidate.resolved_by_name ? (
                  <span className="bnd-settled__who">{candidate.resolved_by_name}</span>
                ) : null}
                {candidate.resolution_note ? (
                  <span className="bnd-settled__note">{candidate.resolution_note}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {released.length > 0 ? (
        <div className="bnd-section" data-testid="binding-released">
          <h3 className="bnd-section__title">Previously bound to</h3>
          <ul className="bnd-list">
            {released.map((row) => (
              <li key={row.id} className={cn('bnd-settled', 'bnd-settled--released')}>
                <span className="bnd-settled__what mono">{bindingSummary(row)}</span>
                <Badge variant={BINDING_STATE_TONE[bindingState(row)] as 'secondary'}>
                  {BINDING_STATE_LABEL[bindingState(row)]}
                </Badge>
                <span className="bnd-settled__who mono">{shortSha(row.commit_sha)}</span>
                {row.released_at ? (
                  <time dateTime={row.released_at} title={row.released_at} className="bnd-settled__note">
                    {formatRelativeWhen(row.released_at, reference)}
                  </time>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
