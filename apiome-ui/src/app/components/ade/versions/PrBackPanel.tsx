'use client';

/**
 * "Sync back to repositories" — PR-back on the Versions → Sources tab, REPO-5.8 (#2793).
 *
 * Changes used to flow one way: a repository file is imported into the project. This panel is
 * the way back: for each repository the project was imported from, render the chosen version and
 * open a pull request into its source files.
 *
 * - **Who may** is the repository's decision, not the project's: its PR-back settings (an allow
 *   or deny list) say whether this project may open pull requests at all. A repository that does
 *   not allow it shows why, in the words apiome-rest sends.
 * - **Preview first.** *Preview* runs a dry run — the files that would change, their change
 *   counts and the pull request description — and writes nothing. *Open pull request* does it.
 * - **One pull request per project and base branch.** Running it again for a newer version
 *   refreshes the open pull request instead of opening another, and the result says which.
 *
 * apiome-rest enforces `versions:publish` (`projects:view` for a preview) and audits every pull
 * request it opens.
 */

import * as React from 'react';
import { ExternalLink, GitPullRequest } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { CatalogTimelineSkeleton } from '@/app/components/ade/catalog/CatalogSkeletons';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import {
  PR_BACK_STATUS_LABEL,
  PR_BACK_STATUS_TONE,
  outcomeSentence,
  parsePrBackOutcome,
  parsePrBackRepositories,
  type PrBackOutcome,
  type PrBackRepository,
} from '@lib/pr-back';

export interface PrBackPanelProps {
  /** The project. */
  projectId: string;
  /** The revision to render (the Sources tab's selected version). */
  versionId: string;
  /** Its label, for the button copy. */
  versionLabel?: string | null;
}

/** Shown when the repositories cannot be read. */
const LOAD_ERROR = 'Could not load the repositories this project can sync back to.';

/** Shown when the sync request itself fails without a message. */
const SYNC_ERROR = 'The sync could not be started. Try again.';

/** A per-repository result: what came back, or why the request failed. */
interface RepositoryResult {
  outcome: PrBackOutcome | null;
  error: string | null;
}

/**
 * One repository's row: its files, whether the project may PR back, and the two actions.
 *
 * @param props - The repository, the busy flag, the result and the two handlers.
 * @returns The list item.
 */
function RepositoryRow({
  repository,
  busy,
  result,
  versionLabel,
  onRun,
}: {
  repository: PrBackRepository;
  busy: boolean;
  result: RepositoryResult | undefined;
  versionLabel?: string | null;
  onRun: (dryRun: boolean) => void;
}): React.JSX.Element {
  const name = repository.repositoryFullName ?? repository.repositoryId;
  const outcome = result?.outcome ?? null;
  return (
    <li className="prb-repo" data-testid="pr-back-repository">
      <div className="prb-repo__head">
        <span className="prb-repo__name mono">{name}</span>
        {repository.eligible ? (
          <Badge variant="ok" data-testid="pr-back-eligible">
            Can sync{repository.baseBranch ? ` into ${repository.baseBranch}` : ''}
          </Badge>
        ) : (
          <Badge variant="neutral" data-testid="pr-back-ineligible">
            Not allowed
          </Badge>
        )}
        <div className="prb-repo__actions">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!repository.eligible || busy}
            onClick={() => onRun(true)}
            data-testid="pr-back-preview"
          >
            Preview
          </Button>
          <Button
            type="button"
            variant="primary"
            size="sm"
            disabled={!repository.eligible || busy}
            onClick={() => onRun(false)}
            data-testid="pr-back-open"
          >
            <GitPullRequest aria-hidden />
            Open pull request
          </Button>
        </div>
      </div>

      <ul className="prb-files" aria-label={`Source files in ${name}`}>
        {repository.files.map((file) => (
          <li key={`${file.branch}:${file.path}`} className="prb-files__item mono">
            {file.path}
            <span className="prb-muted"> · {file.branch}</span>
          </li>
        ))}
      </ul>

      {!repository.eligible && repository.reason ? (
        <p className="prb-note" data-testid="pr-back-reason">
          {repository.reason}
        </p>
      ) : null}

      <div aria-live="polite" className="prb-result-slot">
        {busy ? <p className="prb-note">Rendering {versionLabel ?? 'the version'}…</p> : null}
        {result?.error ? (
          <Alert variant="error" data-testid="pr-back-error">
            {result.error}
          </Alert>
        ) : null}
        {outcome ? <OutcomeView outcome={outcome} /> : null}
      </div>
    </li>
  );
}

/**
 * What a sync did: the status, one sentence, the pull request link, each file and the
 * description it carries.
 *
 * @param props - The outcome.
 * @returns The result block.
 */
function OutcomeView({ outcome }: { outcome: PrBackOutcome }): React.JSX.Element {
  return (
    <div className="prb-result" data-testid="pr-back-result">
      <div className="prb-result__head">
        <Badge variant={PR_BACK_STATUS_TONE[outcome.status]} data-testid={`pr-back-status-${outcome.status}`}>
          {PR_BACK_STATUS_LABEL[outcome.status]}
        </Badge>
        <span className="prb-result__sentence">{outcomeSentence(outcome)}</span>
        {outcome.pullRequestUrl ? (
          <a
            className="prb-link"
            href={outcome.pullRequestUrl}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="pr-back-link"
          >
            View pull request{outcome.pullRequestNumber ? ` #${outcome.pullRequestNumber}` : ''}
            <ExternalLink className="prb-glyph" aria-hidden />
          </a>
        ) : null}
      </div>

      {outcome.files.length > 0 ? (
        <ul className="prb-files" aria-label="Rendered files">
          {outcome.files.map((file) => (
            <li key={file.path} className="prb-files__item" data-testid="pr-back-file">
              <span className="mono">{file.path}</span>
              <Badge variant={file.status === 'unchanged' ? 'neutral' : 'accent'} square>
                {file.status}
              </Badge>
              <span className="prb-muted">
                {file.paths} path{file.paths === 1 ? '' : 's'} · {file.schemas} schema
                {file.schemas === 1 ? '' : 's'}
              </span>
              {[...file.notes, ...(file.foreignRefs.length > 0
                ? [`References schemas another file defines: ${file.foreignRefs.join(', ')}.`]
                : [])].map((note) => (
                <span key={note} className="prb-note prb-files__note">
                  {note}
                </span>
              ))}
            </li>
          ))}
        </ul>
      ) : null}

      {outcome.skipped.length > 0 ? (
        <ul className="prb-skipped" aria-label="Not rendered back">
          {outcome.skipped.map((sentence) => (
            <li key={sentence} className="prb-note">
              {sentence}
            </li>
          ))}
        </ul>
      ) : null}

      {outcome.body ? (
        <details className="prb-details">
          <summary>Pull request description</summary>
          {outcome.commitMessage ? (
            <p className="prb-note">
              Commit message: <span className="mono">{outcome.commitMessage}</span>
            </p>
          ) : null}
          <pre className="prb-body" data-testid="pr-back-body">
            {outcome.body}
          </pre>
        </details>
      ) : null}
    </div>
  );
}

/**
 * The PR-back section of the Sources tab.
 *
 * @param props - See {@link PrBackPanelProps}.
 * @returns The section, or nothing while the project has no repository to sync to.
 */
export function PrBackPanel({ projectId, versionId, versionLabel }: PrBackPanelProps): React.JSX.Element | null {
  const [repositories, setRepositories] = React.useState<PrBackRepository[] | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);
  // Keyed by version and repository: a result describes one version, so picking another shows none.
  const [results, setResults] = React.useState<Record<string, RepositoryResult>>({});

  // RC6-H3 (#6210): bumped by the load error's retry.
  const [attempt, setAttempt] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    (async () => {
      try {
        const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/pr-back/repositories`);
        const payload = await response.json().catch(() => null);
        const parsed = response.ok ? parsePrBackRepositories(payload) : null;
        if (cancelled) return;
        if (parsed) setRepositories(parsed);
        else setLoadError((payload as { error?: string } | null)?.error || LOAD_ERROR);
      } catch {
        if (!cancelled) setLoadError(LOAD_ERROR);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, attempt]);

  const run = React.useCallback(
    async (repositoryId: string, dryRun: boolean) => {
      const key = `${versionId}:${repositoryId}`;
      setBusy(repositoryId);
      setResults((current) => ({ ...current, [key]: { outcome: null, error: null } }));
      let result: RepositoryResult;
      try {
        const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/pr-back`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ repositoryId, version: versionId, dryRun }),
        });
        const payload = await response.json().catch(() => null);
        const outcome = response.ok ? parsePrBackOutcome(payload) : null;
        result = outcome
          ? { outcome, error: null }
          : { outcome: null, error: (payload as { error?: string } | null)?.error || SYNC_ERROR };
      } catch {
        result = { outcome: null, error: SYNC_ERROR };
      }
      setResults((current) => ({ ...current, [key]: result }));
      setBusy(null);
    },
    [projectId, versionId],
  );

  if (loadError) {
    return (
      <div className="rsrc-section" data-testid="pr-back-panel">
        <h3 className="rsrc-section__title">Sync back to repositories</h3>
        <ErrorState
          variant="compact"
          title="Couldn't load the repositories to sync back to"
          description={loadError}
          onRetry={() => setAttempt((count) => count + 1)}
          data-testid="pr-back-load-error"
        />
      </div>
    );
  }
  if (!repositories) {
    return (
      <div className="rsrc-section" data-testid="pr-back-panel">
        <h3 className="rsrc-section__title">Sync back to repositories</h3>
        <CatalogTimelineSkeleton message="Loading the repositories to sync back to…" testId="pr-back-loading" rows={2} />
      </div>
    );
  }
  // No repository this project may sync back to: the section has nothing to offer.
  if (repositories.length === 0) return null;

  return (
    <div className="rsrc-section" data-testid="pr-back-panel">
      <h3 className="rsrc-section__title">Sync back to repositories</h3>
      <p className="prb-note">
        Render {versionLabel ?? 'this version'} and open a pull request into the files it was imported from. Each
        repository decides which projects may — in its <strong>Settings</strong> tab.
      </p>
      <ul className="prb-list">
        {repositories.map((repository) => (
          <RepositoryRow
            key={repository.repositoryId}
            repository={repository}
            busy={busy === repository.repositoryId}
            result={results[`${versionId}:${repository.repositoryId}`]}
            versionLabel={versionLabel}
            onRun={(dryRun) => void run(repository.repositoryId, dryRun)}
          />
        ))}
      </ul>
    </div>
  );
}
