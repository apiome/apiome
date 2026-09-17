'use client';

/**
 * The Synchronization section of the Repository tab — GNC-2.3 (#4739).
 *
 * A bound draft has three descriptions of the same API — the repository at the commit it was last
 * synchronized with, the repository at the commit its branch moved to, and the draft itself — and
 * they drift apart independently. This section runs the **three-way merge** of the three and shows
 * what it found: the incoming changes that touch nothing anybody has been editing, and, for every
 * place both sides moved, a conflict with all three values side by side and a link to the exact
 * line of the repository file it lives at.
 *
 * The sentence the whole surface is built around: **nothing here changes the draft.** Merging
 * reads three documents and records a result; settling a conflict records which side a person
 * chose. That is why the changes are "would apply" rather than "applied", and why the two buttons
 * say "take" and "keep" rather than "accept" and "revert" — there is nothing to revert, because
 * nothing has happened to the version.
 *
 * Every rule about who may do this lives in apiome-rest: reading needs `projects:view`, merging and
 * settling need `versions:edit`, and merging additionally *proves* the tenant's stored credential
 * can read both commits before it records anything.
 */

import * as React from 'react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { Input } from '@/app/components/ui/Input';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { formatRelativeWhen } from '@/app/components/ade/repositories/repositoryDetailModel';
import {
  SYNC_GUARD_SENTENCE,
  SYNC_KIND_LABEL,
  SYNC_SIDE_LABEL,
  SYNC_STATUS_LABEL,
  SYNC_STATUS_TONE,
  conflictLocation,
  formatConflictValue,
  planSentence,
  shortSha,
  syncErrorMessage,
  type SyncChange,
  type SyncConflict,
  type SyncPlan,
  type SyncResolution,
  type VersionSyncStatus,
} from '@lib/spec-sync';

export interface VersionSyncPanelProps {
  /** The project the bound version belongs to. */
  projectId: string;
  /** The revision whose binding is merged. */
  versionId: string;
  /** Whether that version has an active binding; without one there is nothing to merge against. */
  bound: boolean;
  /** Reference time for relative dates, in epoch ms; tests pin it. Defaults to mount time. */
  now?: number;
}

/** What the BFF routes answer with. */
type Envelope = Record<string, unknown> & { success?: boolean; error?: string; code?: string };

/**
 * Call a synchronization BFF route and parse its envelope.
 *
 * @param url - The route.
 * @param init - Fetch options.
 * @returns The parsed envelope.
 */
async function callSync(url: string, init?: RequestInit): Promise<Envelope> {
  const response = await fetch(url, init);
  return (await response.json().catch(() => ({}))) as Envelope;
}

/**
 * The three digests a merge was computed from, as a definition list.
 *
 * They are the whole evidence of *which bytes* a result describes, which is why they are on screen
 * rather than only in the audit trail: a merge is only as trustworthy as the three documents
 * somebody can check it was made from.
 *
 * @param props.plan - The merge result.
 */
function PlanFacts({ plan }: { plan: SyncPlan }) {
  const rows: Array<{ label: string; value: string; title: string }> = [
    {
      label: 'Last synchronized',
      value: shortSha(plan.base_commit_sha),
      title: `${plan.base_commit_sha} · ${plan.base_digest}`,
    },
    {
      label: 'In the repository',
      value: shortSha(plan.git_commit_sha),
      title: `${plan.git_commit_sha} · ${plan.git_digest}`,
    },
    { label: 'This draft', value: plan.draft_digest, title: plan.draft_digest },
  ];
  return (
    <dl className="syn-facts">
      {rows.map((row) => (
        <div className="syn-facts__row" key={row.label}>
          <dt>{row.label}</dt>
          <dd className="mono syn-facts__value" title={row.title}>
            {row.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * One incoming change the merge would apply.
 *
 * @param props.change - The change.
 */
function AppliedChange({ change }: { change: SyncChange }) {
  return (
    <li className="syn-change">
      <span className="syn-change__kind">{SYNC_KIND_LABEL[change.kind]}</span>
      <span className="syn-change__group">{change.group}</span>
      <span className="syn-change__pointer mono">{change.pointer || '/'}</span>
    </li>
  );
}

/**
 * One conflict, with all three values and the two decisions it accepts.
 *
 * @param props.conflict - The conflict.
 * @param props.busy - True while a decision is in flight.
 * @param props.note - The note typed for this conflict, if any.
 * @param props.onNote - Called as the note is typed.
 * @param props.onResolve - Called with the side the reader chose.
 * @param props.now - Reference time for relative dates.
 */
function ConflictRow({
  conflict,
  busy,
  note,
  onNote,
  onResolve,
  now,
}: {
  conflict: SyncConflict;
  busy: boolean;
  note: string;
  onNote: (value: string) => void;
  onResolve: (resolution: SyncResolution) => void;
  now: number;
}) {
  const location = conflictLocation(conflict);
  const settled = Boolean(conflict.resolution);
  const sides: Array<{ side: 'base' | SyncResolution; value: unknown; kind: SyncChange['kind'] }> = [
    { side: 'base', value: conflict.base_value, kind: conflict.git_kind },
    { side: 'git', value: conflict.git_value, kind: conflict.git_kind },
    { side: 'draft', value: conflict.draft_value, kind: conflict.draft_kind },
  ];
  return (
    <li className="syn-conflict" data-testid={`sync-conflict-${conflict.id}`}>
      <div className="syn-conflict__head">
        <span className="syn-conflict__pointer mono">{conflict.pointer || '/'}</span>
        <span className="syn-conflict__group">{conflict.group_key}</span>
        {conflict.source_url ? (
          <a
            className="syn-conflict__link"
            href={conflict.source_url}
            target="_blank"
            rel="noreferrer"
          >
            {location || 'Open in the repository'}
          </a>
        ) : location ? (
          <span className="syn-conflict__where mono">{location}</span>
        ) : null}
      </div>

      <div className="syn-sides">
        {sides.map((entry) => (
          <div className="syn-side" key={entry.side}>
            <p className="syn-side__label">{SYNC_SIDE_LABEL[entry.side]}</p>
            <pre className="syn-side__value mono">
              {formatConflictValue(entry.value, entry.kind, entry.side)}
            </pre>
          </div>
        ))}
      </div>

      {settled ? (
        <p className="syn-conflict__settled" data-testid={`sync-conflict-settled-${conflict.id}`}>
          Settled towards {SYNC_SIDE_LABEL[conflict.resolution as SyncResolution].toLowerCase()}
          {conflict.resolved_by_name ? ` by ${conflict.resolved_by_name}` : ''}
          {conflict.resolved_at ? ` ${formatRelativeWhen(conflict.resolved_at, now)}` : ''}
          {conflict.resolution_note ? ` — ${conflict.resolution_note}` : ''}
        </p>
      ) : (
        <div className="syn-conflict__decide">
          <Input
            aria-label={`Why, for ${conflict.pointer || 'the document root'}`}
            className="syn-conflict__note"
            placeholder="Why (optional)"
            value={note}
            disabled={busy}
            onChange={(event) => onNote(event.target.value)}
          />
          <div className="syn-conflict__actions">
            <Button size="sm" disabled={busy} onClick={() => onResolve('git')}>
              Take the repository&rsquo;s
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => onResolve('draft')}>
              Keep this draft&rsquo;s
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

/**
 * The Synchronization section: merge a bound draft against its branch, and decide the overlaps.
 *
 * @param props - See {@link VersionSyncPanelProps}.
 */
export function VersionSyncPanel({ projectId, versionId, bound, now }: VersionSyncPanelProps) {
  // A lazy initializer rather than a call in the render body: the clock is read once, at mount, so
  // a re-render never shifts every relative date on the screen.
  const [mountedAt] = React.useState(() => Date.now());
  const reference = now ?? mountedAt;

  const [status, setStatus] = React.useState<VersionSyncStatus | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [notes, setNotes] = React.useState<Record<string, string>>({});

  const base = `/api/projects/${encodeURIComponent(projectId)}/bindings/sync`;
  const query = `?version=${encodeURIComponent(versionId)}`;

  const load = React.useCallback(async () => {
    if (!versionId || !bound) {
      setStatus(null);
      return;
    }
    setLoading(true);
    setError(null);
    const payload = await callSync(`${base}${query}`);
    setLoading(false);
    if (payload.success) {
      setStatus(payload as unknown as VersionSyncStatus);
    } else {
      setStatus(null);
      setError(
        syncErrorMessage(payload.code, payload.error ?? 'The merge results could not be read')
      );
    }
  }, [base, bound, query, versionId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  /**
   * Run a write and fold its answer back into the section.
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
      const payload = await callSync(url, init);
      setBusy(false);
      if (payload.success) {
        setNotice(success);
        await load();
        return;
      }
      setError(syncErrorMessage(payload.code, payload.error ?? 'The request failed'));
    },
    [load]
  );

  const plan = status?.latest?.plan ?? null;
  const conflicts = status?.latest?.conflicts ?? [];
  const guard = plan ? SYNC_GUARD_SENTENCE[plan.guard] : null;

  const merge = (refresh: boolean) =>
    write(
      `${base}${query}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(refresh ? { refresh: true } : {}),
      },
      refresh ? 'Merged again from the repository.' : 'Merged. Nothing about this draft changed.'
    );

  const settle = (conflict: SyncConflict, resolution: SyncResolution) =>
    write(
      `${base}/plans/${encodeURIComponent(conflict.plan_id)}` +
        `/conflicts/${encodeURIComponent(conflict.id)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resolution,
          ...(notes[conflict.id]?.trim() ? { note: notes[conflict.id].trim() } : {}),
        }),
      },
      'Recorded. The draft is unchanged either way.'
    );

  if (!bound) return null;

  return (
    <section className="syn" data-testid="version-sync-panel">
      <div className="syn-head">
        <h3 className="syn-head__title">Synchronization</h3>
        <div className="syn-head__actions">
          <Button size="sm" disabled={busy} onClick={() => void merge(false)} data-testid="sync-merge">
            Merge branch changes
          </Button>
          {plan ? (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => void merge(true)}
              data-testid="sync-refresh"
            >
              Merge again
            </Button>
          ) : null}
        </div>
      </div>
      <p className="syn-head__note">
        A merge compares the repository&rsquo;s changes with this draft&rsquo;s against their common
        base. It never rewrites the draft &mdash; it says what would apply and what collides.
      </p>

      {error ? (
        <Alert variant="error" data-testid="sync-error">
          {error}
        </Alert>
      ) : null}
      {notice ? (
        <Alert variant="success" data-testid="sync-notice">
          {notice}
        </Alert>
      ) : null}

      {loading ? <LoadingState className="syn-state" message="Loading the merge results…" /> : null}

      {!loading && !plan ? (
        <EmptyState
          className="syn-state"
          title="This draft has not been merged with its branch yet"
          description="Merge to see which repository changes would apply and which collide with your edits."
        />
      ) : null}

      {!loading && plan ? (
        <div className="syn-card" data-testid="sync-plan">
          <div className="syn-card__head">
            <Badge variant={SYNC_STATUS_TONE[plan.status] as 'success'}>
              {SYNC_STATUS_LABEL[plan.status]}
            </Badge>
            <span className="syn-card__what">{planSentence(plan)}</span>
            <time
              className="syn-card__when"
              dateTime={plan.created_at}
              title={plan.created_at}
            >
              {formatRelativeWhen(plan.created_at, reference)}
            </time>
          </div>

          {plan.stale ? (
            <Alert variant="warning" data-testid="sync-stale">
              This draft has been edited since the merge ran, so the result below describes a
              document that no longer exists. Merge again.
            </Alert>
          ) : null}
          {guard ? (
            <Alert variant="warning" data-testid="sync-guard">
              {guard}
            </Alert>
          ) : null}

          <PlanFacts plan={plan} />

          {plan.changes.length > 0 ? (
            <div className="syn-section" data-testid="sync-changes">
              <h4 className="syn-section__title">Would apply</h4>
              <p className="syn-section__note">
                These touch nothing this draft has changed, so the merge can place them without a
                decision.
              </p>
              <ul className="syn-list">
                {plan.changes.map((change) => (
                  <AppliedChange change={change} key={change.pointer} />
                ))}
              </ul>
            </div>
          ) : null}

          {conflicts.length > 0 ? (
            <div className="syn-section" data-testid="sync-conflicts">
              <h4 className="syn-section__title">Needs a decision</h4>
              <p className="syn-section__note">
                Both the repository and this draft changed these, in different directions. Choosing
                a side records the decision; nothing is written to the draft.
                {plan.conflicts_truncated
                  ? ' This merge collided in more places than one result holds, so these are the ' +
                    'first of a longer list — narrow the source path, or merge a smaller change.'
                  : ''}
              </p>
              <ul className="syn-list">
                {conflicts.map((conflict) => (
                  <ConflictRow
                    key={conflict.id}
                    conflict={conflict}
                    busy={busy}
                    now={reference}
                    note={notes[conflict.id] ?? ''}
                    onNote={(value) =>
                      setNotes((current) => ({ ...current, [conflict.id]: value }))
                    }
                    onResolve={(resolution) => void settle(conflict, resolution)}
                  />
                ))}
              </ul>
            </div>
          ) : null}

          {plan.local_count > 0 ? (
            <p className="syn-note" data-testid="sync-local">
              {plan.local_count} {plan.local_count === 1 ? 'change' : 'changes'} in this draft that
              the repository did not touch {plan.local_count === 1 ? 'is' : 'are'} left exactly as
              {plan.local_count === 1 ? ' it is' : ' they are'}.
            </p>
          ) : null}
        </div>
      ) : null}

      {!loading && (status?.history.length ?? 0) > 0 ? (
        <div className="syn-section" data-testid="sync-history">
          <h4 className="syn-section__title">Earlier merges</h4>
          <ul className="syn-list">
            {status?.history.map((earlier) => (
              <li className="syn-past" key={earlier.id}>
                <Badge variant={SYNC_STATUS_TONE[earlier.status] as 'secondary'}>
                  {SYNC_STATUS_LABEL[earlier.status]}
                </Badge>
                <span className="syn-past__what mono">
                  {shortSha(earlier.base_commit_sha)} → {shortSha(earlier.git_commit_sha)}
                </span>
                <time
                  className="syn-past__when"
                  dateTime={earlier.created_at}
                  title={earlier.created_at}
                >
                  {formatRelativeWhen(earlier.created_at, reference)}
                </time>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
