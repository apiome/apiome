'use client';

/**
 * **Verification result** — `/ade/dashboard/pacts/pacticipants/{provider}/verification/results/{id}`
 * (PFX-5.5, #6949).
 *
 * One verification result in full:
 *
 * * **Overview** — verdict, consumer and pact, provider build (version, branch, build link),
 *   verifier, trigger, duration, pending / work in progress, when it was published.
 * * **Interactions** — each interaction's outcome; a failed one is open, each mismatch with its
 *   expected and actual values side by side.
 * * **Requests** — the evidence run's requests and how each was judged, when Apiome ran it; why
 *   not otherwise (a Pact verifier published it, retention removed it, or the role cannot read
 *   evidence).
 * * **Raw log** — the whole result as plain text, with **Copy** and **Download**.
 *
 * **Re-run verification** replays the same pact on a verification target as the same provider
 * build (changeable) and publishes a new result.
 */

import * as React from 'react';
import Link from 'next/link';
import { Copy, Download, Play, RefreshCw } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { PACTICIPANTS_ROUTE, formatWhen, pacticipantRoute, safeHttpUrl } from '@lib/pact-pacticipants';
import { pactRoute, shortSha } from '@lib/pact-detail';
import {
  EVIDENCE_TEXT,
  formatDuration,
  interactionOutcomes,
  logFileName,
  renderVerificationLog,
  triggerLabel,
  verificationRoute,
  type EvidenceStatus,
  type ResultDetail,
  type RunBody,
  type TargetOption,
} from '@lib/pact-verification';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { EvidenceRequests, InteractionResults, ResultBadge, RunDialog } from './VerificationPanels';
import { fetchTargetOptions, fetchVerificationResult, rerunVerification } from './pactVerificationApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The read: loading (`data` null, no error), failed (`error`), or loaded. */
type Loaded = { data: ResultDetail | null; error: string | null };

/**
 * Hand the log to the reader as a file.
 *
 * @param name - The file name.
 * @param text - The log.
 */
function downloadText(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/**
 * One verification result's page.
 *
 * @param props - The provider's handle and the result's id from the route.
 * @returns The page.
 */
export default function VerificationResultClient({ slug, resultId }: { slug: string; resultId: string }) {
  const [detail, setDetail] = React.useState<Loaded>({ data: null, error: null });
  const [copied, setCopied] = React.useState<string | null>(null);
  const [rerunOpen, setRerunOpen] = React.useState(false);
  const [targets, setTargets] = React.useState<TargetOption[] | null>(null);
  const [targetsError, setTargetsError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setDetail({ data: null, error: null });
    try {
      setDetail({ data: await fetchVerificationResult(slug, resultId), error: null });
    } catch (caught) {
      setDetail({ data: null, error: describeFailure(caught, 'Could not load the verification result') });
    }
  }, [slug, resultId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const data = detail.data;
  const log = React.useMemo(() => (data ? renderVerificationLog(data) : ''), [data]);
  const outcomes = React.useMemo(() => (data ? interactionOutcomes(data.test_results) : []), [data]);
  const providerName = data?.provider_name ?? slug;
  const result = data?.result;
  const title = result ? `Result ${result.number} — ${result.consumer_name}` : 'Verification result';

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(log);
      setCopied('The log is copied.');
    } catch {
      setCopied('The log could not be copied; select it and copy it instead.');
    }
  };

  const openRerun = () => {
    setRerunOpen(true);
    if (targets === null) {
      fetchTargetOptions()
        .then(setTargets)
        .catch((caught) => setTargetsError(describeFailure(caught, 'Could not load the verification targets')));
    }
  };

  const rerun = async (body: RunBody) => {
    if (!result) throw new Error('Nothing to run.');
    return rerunVerification(slug, result.consumer, result.pact_version_sha, body);
  };

  return (
    <Page>
      <PageHeader
        title={title}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: providerName, href: pacticipantRoute(slug) },
          { label: 'Verification', href: verificationRoute(slug) },
          { label: result ? `Result ${result.number}` : 'Result' },
        ]}
        description="One verification result: each interaction's expected and actual values, the requests sent, and the log."
        actions={
          <>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCw aria-hidden />
              Refresh
            </Button>
            {result && result.kind !== 'bidirectional' ? (
              <Button onClick={openRerun} data-testid="pvx-result-rerun">
                <Play aria-hidden />
                Re-run verification
              </Button>
            ) : null}
          </>
        }
      />
      <PageBody>
        <div className="ppx pvx" data-testid="pact-verification-result">
          {detail.error ? (
            <EmptyState
              variant="compact"
              titleAs="h2"
              tone="danger"
              title="This verification result could not be read"
              description={detail.error}
              action={
                <div className="ppx__actions">
                  <Button variant="soft" onClick={() => void load()}>
                    <RefreshCw aria-hidden />
                    Try again
                  </Button>
                  <Link className="ppx__link" href={verificationRoute(slug)}>
                    All verification results
                  </Link>
                </div>
              }
            />
          ) : data === null || !result ? (
            <LoadingState message="Reading the verification result…" minHeightClassName="min-h-[6rem]" />
          ) : (
            <>
              <section className="ppx__panel" aria-labelledby="pvx-overview-title" data-testid="pvx-overview">
                <div className="ppx__panel-head">
                  <h2 id="pvx-overview-title" className="ppx__title">
                    Overview
                  </h2>
                  <ResultBadge result={result} />
                </div>
                <dl className="ppx__facts">
                  <div className="ppx__fact">
                    <dt>Pact</dt>
                    <dd>
                      <Link className="ppx__link" href={pactRoute(result.consumer, slug, result.consumer_version)}>
                        {result.consumer_name} → {providerName}
                      </Link>{' '}
                      <span className="ppx__muted ppx__mono" title={result.pact_version_sha}>
                        {shortSha(result.pact_version_sha)}
                      </span>
                    </dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Provider build</dt>
                    <dd className="ppx__mono">
                      {result.provider_version}
                      {result.provider_branch ? ` · ${result.provider_branch}` : ''}
                    </dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>CI build</dt>
                    <dd>
                      {safeHttpUrl(result.build_url) ? (
                        <a
                          className="ppx__link"
                          href={safeHttpUrl(result.build_url) as string}
                          target="_blank"
                          rel="noreferrer noopener"
                        >
                          Open the build
                        </a>
                      ) : (
                        <span className="ppx__muted">Not given</span>
                      )}
                    </dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Verifier</dt>
                    <dd>{result.kind === 'bidirectional' ? 'Bi-directional comparison' : (result.verified_by ?? '—')}</dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Trigger</dt>
                    <dd data-testid="pvx-trigger">{triggerLabel(result.trigger)}</dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Duration</dt>
                    <dd>{formatDuration(result.duration_ms)}</dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Interactions</dt>
                    <dd>
                      {result.counts.passed} of {result.counts.total} passed
                    </dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Published</dt>
                    <dd className="ppx__when">{formatWhen(result.created_at)}</dd>
                  </div>
                  {result.pending || result.wip ? (
                    <div className="ppx__fact">
                      <dt>Pact state</dt>
                      <dd className="ppx__chips">
                        {result.pending ? <Badge variant="neutral">Pending</Badge> : null}
                        {result.wip ? <Badge variant="neutral">Work in progress</Badge> : null}
                      </dd>
                    </div>
                  ) : null}
                </dl>
              </section>

              <section className="ppx__panel" aria-labelledby="pvx-interactions-title">
                <div className="ppx__panel-head">
                  <h2 id="pvx-interactions-title" className="ppx__title">
                    Interactions
                  </h2>
                  <span className="ppx__meta">{outcomes.length}</span>
                </div>
                <InteractionResults outcomes={outcomes} />
              </section>

              <section className="ppx__panel" aria-labelledby="pvx-requests-title" data-testid="pvx-requests">
                <div className="ppx__panel-head">
                  <h2 id="pvx-requests-title" className="ppx__title">
                    Requests
                  </h2>
                </div>
                {data.evidence ? (
                  <EvidenceRequests run={data.evidence} />
                ) : (
                  <p className="ppx__statement" data-testid="pvx-evidence-note">
                    {EVIDENCE_TEXT[data.evidence_status as Exclude<EvidenceStatus, 'attached'>] ??
                      'No request log is held for this result.'}
                  </p>
                )}
              </section>

              <section className="ppx__panel" aria-labelledby="pvx-log-title" data-testid="pvx-log">
                <div className="ppx__panel-head">
                  <h2 id="pvx-log-title" className="ppx__title">
                    Raw log
                  </h2>
                  <span className="ppx__actions">
                    <Button variant="outline" size="sm" onClick={() => void copy()} data-testid="pvx-log-copy">
                      <Copy aria-hidden />
                      Copy
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => downloadText(logFileName(data), log)}
                      data-testid="pvx-log-download"
                    >
                      <Download aria-hidden />
                      Download
                    </Button>
                  </span>
                </div>
                {copied ? (
                  <p className="ppx__muted" role="status">
                    {copied}
                  </p>
                ) : null}
                <pre className="ppx__snippet pvx-log" tabIndex={0} aria-label="Raw verification log">
                  {log}
                </pre>
              </section>
            </>
          )}
        </div>
        {rerunOpen && result ? (
          <RunDialog
            request={{
              mode: 'rerun',
              title: `Re-run ${result.consumer_name}'s pact`,
              description: `Replay pact ${shortSha(result.pact_version_sha)} against a verification target and publish a new result.`,
              providerVersion: result.provider_version,
              providerBranch: result.provider_branch,
            }}
            targets={targets}
            targetsError={targetsError}
            onRun={rerun}
            onClose={() => setRerunOpen(false)}
          />
        ) : null}
      </PageBody>
    </Page>
  );
}
