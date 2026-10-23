'use client';

/**
 * Tenant-wide auto-refresh health, as one panel (RAR-5.5, #3536; re-drawn by HIVE-7.3, #5320).
 *
 * Authority: `docs/mockups/sources/repositories.html` §Refresh activity — the
 * `N specs tracked · N refreshed (24h)` line, the five state chips with zeros muted, the
 * drill-in list of affected repositories, and the healthy / empty sentences.
 *
 * The data and the aggregation are unchanged: `GET /api/repositories/refresh-activity` returns
 * per-lineage signals, and {@link summarizeRefreshActivity} derives every state with the same
 * RAR-2.3 state machine the Specs tab uses, so the panel's tallies and the per-file chips can
 * never disagree.
 *
 * ### What HIVE-7.3 changed
 *
 * Only the skin, and one thing that was not skin. The chips were
 * `refreshStatusChipToneClasses` — `border-amber-300/60 bg-amber-50/50 text-amber-950 dark:…`
 * triples, one per state, which froze five colours on two palettes out of the nine the app
 * ships. They resolve through {@link REFRESH_STATUS_TONE} now, which is the shared status
 * vocabulary, so the panel obeys the ticket's "health states map to the shared status
 * vocabulary" criterion along with the repository health badge.
 *
 * The thing that was not skin: a zero chip was `opacity-50 grayscale`, which took a legible
 * `text-amber-950` down to roughly 2:1 against its own fill. A zero is now the `outline` tone —
 * a hairline chip with muted ink, at full opacity. It still recedes; it is still readable.
 */

import * as React from 'react';
import Link from 'next/link';
import { ChevronRight, FolderGit2, RefreshCw } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { Card } from '@/app/components/ui/Card';
import { Spinner } from '@/app/components/ui/Spinner';
import { getRefreshStatusPresentation } from '@/app/components/ade/dashboard/repositories/repository-refresh-status-chip-copy';
import {
  summarizeRefreshActivity,
  type RefreshActivitySignal,
  type RefreshActivitySummary,
} from '@/app/components/ade/dashboard/repositories/repository-refresh-activity';

import { REFRESH_STATUS_ORDER, REFRESH_STATUS_TONE } from './repositoriesModel';

/** How many affected repositories the drill-in list shows before summarising the rest. */
export const AFFECTED_REPOS_SHOWN = 5;

/** Deep-link to a repository's Specs tab (per-file refresh states + actions). */
export function repositoryRefreshSpecsHref(repositoryId: string): string {
  return `/ade/dashboard/repositories/${encodeURIComponent(repositoryId)}/preview?tab=specs`;
}

/** What the panel says while its own read is in flight. */
export const REFRESH_ACTIVITY_LOADING = 'Loading refresh activity…';

/** …and when that read failed. */
export const REFRESH_ACTIVITY_ERROR = 'Could not load refresh activity';

/**
 * One state-count chip — "Stale 4".
 *
 * A zero takes the `outline` tone rather than the state's own: attention should land on the
 * states that have something in them, and an outline chip is how the vocabulary already spells
 * "set aside".
 *
 * @param props.code The refresh state.
 * @param props.count How many lineages are in it.
 * @returns The chip.
 */
function StateCountChip({
  code,
  count,
}: {
  code: (typeof REFRESH_STATUS_ORDER)[number];
  count: number;
}) {
  const presentation = getRefreshStatusPresentation(code);
  return (
    <Badge
      variant={count === 0 ? 'outline' : REFRESH_STATUS_TONE[code]}
      dot={count > 0}
      title={presentation.description}
      aria-label={`${presentation.label}: ${count}`}
      data-testid={`refresh-activity-count-${code}`}
      className="repo-refresh__chip"
    >
      {presentation.label}
      <span className="repo-refresh__n">{count.toLocaleString()}</span>
    </Badge>
  );
}

export interface RepositoryRefreshActivityPanelViewProps {
  /** The aggregated tallies from {@link summarizeRefreshActivity}. */
  summary: RefreshActivitySummary;
}

/**
 * The panel, given a summary. See {@link RepositoryRefreshActivityPanelViewProps}.
 *
 * Split from the fetching wrapper below so the view can be unit-tested with a fixed summary.
 *
 * @returns The card.
 */
export function RepositoryRefreshActivityPanelView({
  summary,
}: RepositoryRefreshActivityPanelViewProps) {
  const shown = summary.affectedRepositories.slice(0, AFFECTED_REPOS_SHOWN);
  const hidden = summary.affectedRepositories.length - shown.length;

  return (
    <Card className="repo-refresh" data-testid="refresh-activity-card">
      <div className="repo-refresh__head">
        <h2 className="repo-refresh__title">
          <RefreshCw aria-hidden />
          Refresh activity
        </h2>
        <p className="repo-refresh__count">
          {summary.total === 0
            ? 'No imported specs tracked yet'
            : `${summary.total.toLocaleString()} spec${summary.total === 1 ? '' : 's'} tracked · ${summary.refreshedRecently.toLocaleString()} refreshed (24h)`}
        </p>
      </div>

      {summary.total === 0 ? (
        <p className="repo-refresh__empty">
          Import a spec from a repository and its auto-refresh health will appear here.
        </p>
      ) : (
        <>
          <div className="repo-refresh__chips">
            {REFRESH_STATUS_ORDER.map((code) => (
              <StateCountChip key={code} code={code} count={summary.counts[code]} />
            ))}
          </div>

          {shown.length > 0 ? (
            <ul className="repo-refresh__list">
              {shown.map((repository) => (
                <li key={repository.repositoryId}>
                  <Link
                    href={repositoryRefreshSpecsHref(repository.repositoryId)}
                    title={`Open the Specs tab for ${repository.repositoryName}`}
                    data-testid="refresh-activity-repo-link"
                    className="repo-refresh__row"
                  >
                    <FolderGit2 aria-hidden className="repo-refresh__row-glyph" />
                    <span className="repo-refresh__row-name">{repository.repositoryName}</span>
                    <span className="repo-refresh__row-detail">
                      {[
                        repository.counts.stale > 0 ? `${repository.counts.stale} stale` : null,
                        repository.counts.diverged > 0
                          ? `${repository.counts.diverged} diverged`
                          : null,
                        repository.counts.failed > 0 ? `${repository.counts.failed} failed` : null,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                    <ChevronRight aria-hidden className="repo-refresh__row-chevron" />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="repo-refresh__healthy">
              All repositories healthy — nothing stale, diverged, or failed.
            </p>
          )}

          {hidden > 0 ? (
            <p className="repo-refresh__more">
              +{hidden.toLocaleString()} more{' '}
              {hidden === 1 ? 'repository needs' : 'repositories need'} attention.
            </p>
          ) : null}
        </>
      )}
    </Card>
  );
}

/** What {@link useRefreshActivity} returns. */
export interface RefreshActivityState {
  /** The aggregated tallies, once read. */
  summary: RefreshActivitySummary | null;
  /** True until the first read settles. */
  loading: boolean;
  /** Why the read failed, if it did. */
  error: string | null;
}

/**
 * Read the tenant's refresh signals once and aggregate them.
 *
 * Shared by the panel and by the facts-line chip that opens it (HIVE-11.7), so the page reads
 * `/api/repositories/refresh-activity` once and the chip's count is the panel's count.
 *
 * @returns The summary, the loading flag and any error.
 */
export function useRefreshActivity(): RefreshActivityState {
  const [state, setState] = React.useState<RefreshActivityState>({
    summary: null,
    loading: true,
    error: null,
  });

  React.useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch('/api/repositories/refresh-activity', {
          credentials: 'include',
        });
        const data = (await response.json().catch(() => ({}))) as {
          success?: boolean;
          signals?: RefreshActivitySignal[];
          error?: string;
        };
        if (!response.ok || data.success !== true) {
          throw new Error(typeof data.error === 'string' ? data.error : response.statusText);
        }
        if (!cancelled) {
          setState({
            summary: summarizeRefreshActivity(Array.isArray(data.signals) ? data.signals : [], Date.now()),
            loading: false,
            error: null,
          });
        }
      } catch (caught) {
        if (!cancelled) {
          setState({
            summary: null,
            loading: false,
            error: caught instanceof Error ? caught.message : REFRESH_ACTIVITY_ERROR,
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}

/**
 * The panel body for a given read: loading, failed, or the view.
 *
 * @param props.state From {@link useRefreshActivity}.
 * @returns The panel.
 */
export function RepositoryRefreshActivityPanelBody({ state }: { state: RefreshActivityState }) {
  if (state.loading) {
    return (
      <Card className="repo-refresh repo-refresh--waiting" data-testid="refresh-activity-loading" aria-busy>
        <Spinner size="sm" label={REFRESH_ACTIVITY_LOADING} />
        {REFRESH_ACTIVITY_LOADING}
      </Card>
    );
  }

  if (state.error || !state.summary) {
    return (
      <Card className="repo-refresh repo-refresh--failed" data-testid="refresh-activity-error">
        {state.error ?? REFRESH_ACTIVITY_ERROR}
      </Card>
    );
  }

  return <RepositoryRefreshActivityPanelView summary={state.summary} />;
}

/**
 * The fetching wrapper: read the tenant's refresh signals, aggregate them, draw the view.
 *
 * @returns The panel, or its loading / error state.
 */
export function RepositoryRefreshActivityPanel() {
  return <RepositoryRefreshActivityPanelBody state={useRefreshActivity()} />;
}

export default RepositoryRefreshActivityPanel;
