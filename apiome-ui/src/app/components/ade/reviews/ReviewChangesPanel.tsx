'use client';

/**
 * The review page's Changes tab — COL-2.2 (#4518).
 *
 * What changed between the project's newest published version and the version under review:
 *
 * - **Classified** (the default) — CTG-1.3's taxonomy, breaking changes first, grouped by path or
 *   component the way a stored changelog is (`groupReviewChanges`).
 * - **Plain diff** — the two OpenAPI documents side by side. It is also the fallback whenever the
 *   classified diff is unavailable, with a notice saying why.
 *
 * Loading is lazy twice over: the tab's pane only mounts when the Changes tab is first shown, and
 * the two documents behind the plain diff are only built when the plain diff is first shown.
 */

import * as React from 'react';
import { GitCompareArrows } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import { JsonDiffViewer } from '@/app/components/ui/code/JsonDiffViewer';
import { formatVersionWithPrefix } from '@/app/utils/version-display';
import { countsSummary, severityBadgeVariant, severityLabel } from '@lib/version-changelog';
import {
  changeCountText,
  groupReviewChanges,
  readablePointer,
  type ReviewChangesPayload,
} from '@lib/review-page';

/** The two ways to show the changes. */
type DiffView = 'classified' | 'plain';

/** A load in progress, failed, or done. */
type Loaded<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: T };

/** A BFF envelope. */
type Envelope<T> = Partial<T> & { success?: boolean; error?: string };

/**
 * GET a BFF route and parse its envelope.
 *
 * @param url - The route.
 * @returns The envelope.
 */
async function getEnvelope<T>(url: string): Promise<Envelope<T>> {
  const response = await fetch(url);
  return (await response.json()) as Envelope<T>;
}

export interface ReviewChangesPanelProps {
  /** The review whose version is compared. */
  reviewId: string;
}

/**
 * The Changes tab.
 *
 * @param props - See {@link ReviewChangesPanelProps}.
 * @returns The panel.
 */
export function ReviewChangesPanel({ reviewId }: ReviewChangesPanelProps) {
  const routeBase = `/api/reviews/${encodeURIComponent(reviewId)}`;
  const [changes, setChanges] = React.useState<Loaded<ReviewChangesPayload>>({ status: 'loading' });
  const [view, setView] = React.useState<DiffView>('classified');
  const [documents, setDocuments] = React.useState<Loaded<{ base: string; head: string }>>({ status: 'loading' });
  const documentsRequested = React.useRef(false);

  // The comparison.
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const json = await getEnvelope<ReviewChangesPayload>(`${routeBase}/changes`);
        if (cancelled) return;
        if (!json.success || !json.head) {
          setChanges({ status: 'error', message: json.error || 'Could not compare this version.' });
          return;
        }
        setChanges({ status: 'ready', data: json as ReviewChangesPayload });
      } catch (error) {
        if (!cancelled) {
          setChanges({ status: 'error', message: error instanceof Error ? error.message : 'Could not compare this version.' });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [routeBase]);

  const payload = changes.status === 'ready' ? changes.data : null;
  const effectiveView: DiffView = payload?.classifiedError ? 'plain' : view;
  const wantsDocuments = Boolean(payload?.baseline) && effectiveView === 'plain';

  // The two documents behind the plain diff, built the first time the plain diff is shown.
  React.useEffect(() => {
    if (!wantsDocuments || documentsRequested.current) return undefined;
    documentsRequested.current = true;
    let cancelled = false;
    (async () => {
      try {
        const [base, head] = await Promise.all([
          getEnvelope<{ spec: string }>(`${routeBase}/spec?side=base`),
          getEnvelope<{ spec: string }>(`${routeBase}/spec?side=head`),
        ]);
        if (cancelled) return;
        if (!base.success || typeof base.spec !== 'string' || !head.success || typeof head.spec !== 'string') {
          setDocuments({
            status: 'error',
            message: base.error || head.error || 'Could not build the documents to compare.',
          });
          return;
        }
        setDocuments({ status: 'ready', data: { base: base.spec, head: head.spec } });
      } catch (error) {
        if (!cancelled) {
          setDocuments({
            status: 'error',
            message: error instanceof Error ? error.message : 'Could not build the documents to compare.',
          });
        }
      }
    })();
    return () => {
      cancelled = true;
      // An interrupted build is asked for again the next time the plain diff is shown.
      documentsRequested.current = false;
    };
  }, [wantsDocuments, routeBase]);

  if (changes.status === 'loading') {
    return (
      <LoadingState
        message="Comparing with the newest published version…"
        minHeightClassName="rvw-min-h"
        data-testid="review-changes-loading"
      />
    );
  }

  if (changes.status === 'error') {
    return (
      <div className="rvw-state">
        <Alert variant="error" data-testid="review-changes-error">
          {changes.message}
        </Alert>
      </div>
    );
  }

  const data = changes.data;
  if (data.initialPublication || !data.baseline) {
    return (
      <EmptyState
        icon={<GitCompareArrows />}
        title="First publication"
        description="Nothing in this project is published yet, so there is nothing to compare this version with. Its whole document is on the Spec tab."
        data-testid="review-changes-initial"
      />
    );
  }

  const baselineName = formatVersionWithPrefix(data.baseline.label) || 'the newest published version';
  const sections = groupReviewChanges(data);
  const counts = countsSummary(data.counts);

  let body: React.ReactNode;
  if (effectiveView === 'plain') {
    if (documents.status === 'ready') {
      body = (
        <div className="rvw-diff" data-testid="review-plain-diff">
          <JsonDiffViewer original={documents.data.base} modified={documents.data.head} />
        </div>
      );
    } else if (documents.status === 'error') {
      body = (
        <Alert variant="error" data-testid="review-plain-diff-error">
          {documents.message}
        </Alert>
      );
    } else {
      body = (
        <LoadingState
          message="Building both documents…"
          minHeightClassName="rvw-min-h"
          data-testid="review-plain-diff-loading"
        />
      );
    }
  } else if (sections.length === 0) {
    body = (
      <EmptyState
        icon={<GitCompareArrows />}
        title="No changes"
        description={`This version's document matches ${baselineName}.`}
        data-testid="review-changes-none"
      />
    );
  } else {
    body = (
      <div className="rvw-severities" data-testid="review-classified">
        {sections.map((section) => (
          <section
            key={section.severity}
            className="rvw-severity"
            aria-label={`${severityLabel(section.severity)} changes`}
            data-testid={`review-severity-${section.severity}`}
          >
            <div className="rvw-severity__head">
              <Badge variant={severityBadgeVariant(section.severity)}>{severityLabel(section.severity)}</Badge>
              <span className="rvw-severity__count">{changeCountText(section.entries.length)}</span>
            </div>
            {section.groups.map((group) => (
              <div key={group.pathGroup} className="rvw-group">
                <div className="rvw-group__name mono">{readablePointer(group.pathGroup)}</div>
                <ul className="rvw-change-list">
                  {group.entries.map((entry, index) => (
                    <li key={`${entry.pointer}:${entry.ruleId}:${index}`} className="rvw-change" data-testid="review-change">
                      <span className="rvw-change__summary">{entry.summary}</span>
                      <code className="rvw-change__pointer mono">{readablePointer(entry.pointer)}</code>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </section>
        ))}
      </div>
    );
  }

  return (
    <section className="rvw-changes" aria-label="Changes" data-testid="review-changes">
      <div className="rvw-changes__head">
        <div className="rvw-changes__compare" data-testid="review-changes-compare">
          Compared with <strong className="rvw-changes__baseline">{baselineName}</strong>, the newest published
          version{data.classifiedError ? '' : ` · ${counts ?? 'no changes'}`}
        </div>
        <Segmented
          size="sm"
          value={effectiveView}
          onValueChange={(next) => setView(next as DiffView)}
          aria-label="How to show the changes"
        >
          <SegmentedItem value="classified" disabled={Boolean(data.classifiedError)} data-testid="review-view-classified">
            Classified
          </SegmentedItem>
          <SegmentedItem value="plain" data-testid="review-view-plain">
            Plain diff
          </SegmentedItem>
        </Segmented>
      </div>
      {data.classifiedError ? (
        <Alert variant="warning" data-testid="review-classified-error">
          The classified diff is unavailable ({data.classifiedError}), so the plain diff is shown instead.
        </Alert>
      ) : null}
      {body}
    </section>
  );
}
