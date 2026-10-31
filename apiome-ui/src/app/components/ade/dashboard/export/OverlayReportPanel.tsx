'use client';

import { AlertTriangle, Layers } from 'lucide-react';
import {
  OVERLAY_CHANGE_LABEL,
  overlayReportSummary,
  type ExportOverlayReport,
} from './exportOverlays';

interface OverlayReportPanelProps {
  /** The report from the verify result or the completed job. */
  report: ExportOverlayReport;
}

/**
 * What an export's overlays did (GVM-4.2, #5877): every action that could not be applied, then the
 * fidelity-ledger rows — one per changed value, naming the overlay that changed it — capped at 500
 * with a closing row that says how many changes the cap left out.
 *
 * Rendered on Verify (from the verify result) and on Review (from the job), so the user sees the
 * overlaid document's changes before and after generating.
 *
 * @param props.report The overlay report.
 * @returns The panel.
 */
export function OverlayReportPanel({ report }: OverlayReportPanelProps) {
  return (
    <section className="xstd-stack xstd-panel" data-testid="export-overlay-report" aria-label="Overlays">
      <div className="xstd-caps">
        <Layers aria-hidden />
        Overlays
      </div>
      <p className="xstd-quiet" data-testid="export-overlay-summary">
        {overlayReportSummary(report)}
      </p>

      {report.findings.length > 0 && (
        <ul className="xstd-overlay__list" data-testid="export-overlay-findings">
          {report.findings.map((finding) => (
            <li
              key={`${finding.overlay}-${finding.action_index}-${finding.rule}`}
              className="xstd-notice"
              data-tone={finding.severity === 'error' ? 'danger' : 'warn'}
            >
              <AlertTriangle aria-hidden />
              <span className="xstd-notice__grow">
                <span className="xstd-mono">{finding.rule}</span> · {finding.overlay}
                {finding.action_index >= 0 ? `, action ${finding.action_index + 1}` : ''}
                {finding.target ? (
                  <>
                    {' '}
                    (<span className="xstd-mono">{finding.target}</span>)
                  </>
                ) : null}
                : {finding.message}
              </span>
            </li>
          ))}
        </ul>
      )}

      {report.ledger.length > 0 && (
        <div className="xstd-overlay__ledger">
          <table className="xstd-outcomes" data-testid="export-overlay-ledger">
            <thead>
              <tr>
                <th scope="col">Value</th>
                <th scope="col">Change</th>
                <th scope="col">Overlay</th>
              </tr>
            </thead>
            <tbody>
              {report.ledger.map((row, index) =>
                row.kind === 'truncated' ? (
                  <tr key="truncated">
                    <td colSpan={3} className="xstd-quiet">
                      {row.detail}
                    </td>
                  </tr>
                ) : (
                  <tr key={`${row.pointer}-${index}`} title={row.detail}>
                    <td className="xstd-mono">{row.pointer || '/'}</td>
                    <td>{OVERLAY_CHANGE_LABEL[row.kind] ?? row.kind}</td>
                    <td>{row.overlay}</td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
