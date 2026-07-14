'use client';

/**
 * MCP trust-posture panel (CLX-3.2, #4856).
 *
 * Renders a snapshot's source / supply-chain / trust-posture report: findings grouped by OWASP MCP
 * risk, each tagged with its evidence origin (metadata / source / dependency), the coverage gaps
 * where a rule could not be evaluated, and the gate decision.
 *
 * The panel's defining responsibility is honesty about what the scan does and does not know:
 *
 * - A prominent banner states that **every finding is a signal, not a demonstrated exploit** — for
 *   exactly as long as that is true. It is driven by the report's own `provenCount`, so the day a
 *   dynamic probe (CLX-3.3, #4857) proves something, the banner changes on its own.
 * - Each finding carries an explicit "Signal — not proven exploitable" label, never a bare red chip.
 * - Skipped rules are shown as visible coverage gaps, so an unscanned lane never reads as clean.
 *
 * Styling uses shared dashboard classes and token utilities only — no hard-coded values.
 */

import * as React from 'react';
import { Badge } from '@/app/components/ui/Badge';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { EmptyState } from '@/app/components/ui/EmptyState';
import {
  dashboardContentStackClass,
  dashboardPanelPaddedClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';
import {
  fetchPostureReport,
  groupFindingsByOwasp,
  hasProvenFindings,
  originChipClass,
  severityChipClass,
  type PostureReport,
} from '@/app/utils/mcp-trust-posture';

export type McpTrustPosturePanelProps = {
  endpointId: string;
  versionId: string;
  profile?: string;
};

export function McpTrustPosturePanel({ endpointId, versionId, profile }: McpTrustPosturePanelProps) {
  const [report, setReport] = React.useState<PostureReport | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!endpointId || !versionId) return;
    let cancelled = false;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const result = await fetchPostureReport(endpointId, versionId, {
          profile,
          signal: controller.signal,
        });
        if (!cancelled) setReport(result);
      } catch (e) {
        if (cancelled || controller.signal.aborted) return;
        setError(e instanceof Error ? e.message : 'Failed to load trust posture.');
        setReport(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [endpointId, versionId, profile]);

  if (loading) return <LoadingState message="Loading trust posture…" />;
  if (error) {
    return (
      <EmptyState
        title="Trust posture unavailable"
        description={error}
      />
    );
  }
  if (!report) return null;

  const groups = groupFindingsByOwasp(report.findings);
  const proven = hasProvenFindings(report);

  return (
    <div className={dashboardContentStackClass}>
      {/* The honesty banner. Present for as long as nothing has been proven — driven by the report,
          not hard-coded, so it retires itself when CLX-3.3 probes arrive. */}
      {!proven ? (
        <div
          className="rounded-md border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200"
          role="note"
        >
          Every finding below is a <strong>signal to review</strong>, not a demonstrated exploit.
          Static analysis can indicate risk; it cannot prove a server is exploitable. Confirmation
          requires a dynamic probe.
        </div>
      ) : null}

      <section className={dashboardPanelPaddedClass}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Trust posture</h3>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              Profile {report.profile} · OWASP MCP {report.owaspRevision} · score {report.score}/100
              (grade {report.grade})
            </p>
          </div>
          <Badge variant={report.gate.passed ? 'success' : 'error'} title="Gate decision">
            Gate {report.gate.passed ? 'passed' : 'failed'}
          </Badge>
        </div>
        {report.gate.reasons.length > 0 ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-gray-600 dark:text-gray-400">
            {report.gate.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : null}
      </section>

      {groups.length === 0 ? (
        <EmptyState
          title="No trust-posture findings"
          description="No signals were raised by the rules that could be evaluated for this snapshot."
        />
      ) : (
        groups.map(({ riskId, findings }) => (
          <section key={riskId} className={dashboardPanelPaddedClass}>
            <div className="flex items-center justify-between gap-3">
              <h4 className="text-sm font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                {riskId}
              </h4>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {findings.length} finding{findings.length === 1 ? '' : 's'}
              </span>
            </div>
            <ul className="mt-3 space-y-3">
              {findings.map((finding) => (
                <li
                  key={finding.id}
                  className="rounded-md border border-gray-200 p-3 dark:border-gray-700"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs font-medium ${severityChipClass(finding.severity)}`}
                    >
                      {finding.severity}
                    </span>
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs font-medium ${originChipClass(finding.origin)}`}
                      title="Which evidence lane this came from"
                    >
                      {finding.originLabel || finding.origin}
                    </span>
                    {/* The exploitability label is never omitted — it is the honesty guarantee. */}
                    <span
                      className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-600 dark:bg-gray-800 dark:text-gray-300"
                      title="Static findings are signals, not demonstrated exploits"
                    >
                      {finding.exploitabilityLabel}
                    </span>
                    <code className="text-xs text-gray-500 dark:text-gray-400">{finding.path}</code>
                  </div>
                  <p className="mt-2 text-sm text-gray-800 dark:text-gray-200">{finding.message}</p>
                  {finding.excerpt ? (
                    <pre className="mt-2 overflow-x-auto rounded bg-gray-50 p-2 text-xs text-gray-700 dark:bg-gray-900 dark:text-gray-300">
                      {finding.excerpt}
                    </pre>
                  ) : null}
                  {finding.remediation ? (
                    <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">
                      <strong>Remediation:</strong> {finding.remediation}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ))
      )}

      {/* Coverage gaps. Shown, not hidden: a rule with no evidence was not evaluated, and that is a
          different thing from a rule that passed. */}
      {report.skippedRules.length > 0 ? (
        <section className={dashboardPanelPaddedClass}>
          <h4 className="text-sm font-semibold text-gray-900 dark:text-white">
            Not evaluated ({report.skippedRules.length})
          </h4>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
            These rules could not run for lack of evidence. They are <strong>not passing</strong> —
            they are unverified.
          </p>
          <ul className="mt-2 space-y-1 text-sm text-gray-600 dark:text-gray-400">
            {report.skippedRules.map((ruleId) => (
              <li key={ruleId}>
                <code className="text-xs">{ruleId}</code>
                {report.skipReasons[ruleId] ? ` — ${report.skipReasons[ruleId]}` : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {report.owaspCoverage.uncovered.length > 0 ? (
        <section className={dashboardPanelPaddedClass}>
          <h4 className="text-sm font-semibold text-gray-900 dark:text-white">OWASP coverage</h4>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
            The evaluated rules do not cover these OWASP MCP risks. An unmentioned risk is not an
            absent one — it is one this scan cannot speak to:{' '}
            <span className="font-medium">{report.owaspCoverage.uncovered.join(', ')}</span>.
          </p>
        </section>
      ) : null}
    </div>
  );
}
