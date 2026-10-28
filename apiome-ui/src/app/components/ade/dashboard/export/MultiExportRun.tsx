'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, Loader2, ShieldCheck, Sparkles } from 'lucide-react';
import { Alert } from '../../../ui/Alert';
import { Badge } from '../../../ui/Badge';
import { Button } from '../../../ui/Button';
import type { ExportJobStatus } from './exportJob';
import {
  downloadMultiExportArchive,
  exportOutcomeRows,
  pollMultiExportJob,
  submitMultiExportJob,
  type MultiExportJobBody,
  type MultiExportResult,
} from './exportBatchJob';
import { tierTone } from './exportTargetCatalog';
import type { ExportFidelityTier } from './exportTargetCatalog';

/** Props for {@link MultiExportRun}. */
export interface MultiExportRunProps {
  /** The job body (without `dry_run`, which {@link mode} sets). */
  body: MultiExportJobBody;
  /** `verify` runs a dry run (fidelity only); `generate` runs the export and offers the `.zip`. */
  mode: 'verify' | 'generate';
  /** Display names: artifact ids and target keys → labels. Unknown ids show as-is. */
  labels?: Record<string, string>;
  /** Whether to show the Item column (a multi-item batch). */
  showItem?: boolean;
  /** The download name when the server names none. */
  archiveName: string;
  /** Called with every terminal status. */
  onSettled?: (status: ExportJobStatus) => void;
  /** Test seam: milliseconds between polls. */
  pollIntervalMs?: number;
}

type RunState =
  | { phase: 'idle' }
  | { phase: 'running'; percent: number }
  | { phase: 'done'; jobId: string; status: ExportJobStatus }
  | { phase: 'error'; message: string };

/**
 * One multi-target or multi-item export job, run in place (E1-3, #6219).
 *
 * A button starts the job; while it runs the percent shows; when it settles, an outcome table
 * lists each item × target (state, fidelity, error) and — for `generate` — **Download .zip**
 * saves the archive. Failures are per item on a batch; a job that failed outright shows its error.
 */
export function MultiExportRun({
  body,
  mode,
  labels = {},
  showItem = false,
  archiveName,
  onSettled,
  pollIntervalMs,
}: MultiExportRunProps) {
  const [run, setRun] = useState<RunState>({ phase: 'idle' });
  const [downloading, setDownloading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => abortRef.current?.abort(), []);

  const start = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRun({ phase: 'running', percent: 0 });
    try {
      const jobId = await submitMultiExportJob({ ...body, ...(mode === 'verify' ? { dry_run: true } : {}) });
      const status = await pollMultiExportJob(jobId, {
        signal: controller.signal,
        intervalMs: pollIntervalMs,
        onStatus: (s) => setRun({ phase: 'running', percent: s.percent ?? 0 }),
      });
      setRun({ phase: 'done', jobId, status });
      onSettled?.(status);
    } catch (e) {
      if (controller.signal.aborted) return;
      setRun({ phase: 'error', message: e instanceof Error ? e.message : 'The export failed.' });
    }
  }, [body, mode, onSettled, pollIntervalMs]);

  const download = useCallback(async () => {
    if (run.phase !== 'done') return;
    setDownloading(true);
    try {
      await downloadMultiExportArchive(run.jobId, archiveName);
    } catch (e) {
      setRun({ phase: 'error', message: e instanceof Error ? e.message : 'The archive could not be downloaded.' });
    } finally {
      setDownloading(false);
    }
  }, [run, archiveName]);

  const status = run.phase === 'done' ? run.status : null;
  const result = (status?.state === 'completed' ? status.result : null) as MultiExportResult | null;
  const rows = exportOutcomeRows(result);
  const failed = rows.filter((row) => row.state === 'failed').length;
  const label = (id: string) => labels[id] ?? id;

  return (
    <div className="xstd-stack" data-testid={`multi-export-${mode}`}>
      <div className="xstd-config">
        <Button
          onClick={() => void start()}
          disabled={run.phase === 'running'}
          title={run.phase === 'running' ? 'The export is running.' : undefined}
          variant={run.phase === 'done' ? 'outline' : 'default'}
          data-testid={`multi-export-${mode}-start`}
        >
          {mode === 'verify' ? <ShieldCheck aria-hidden /> : <Sparkles aria-hidden />}
          {run.phase === 'done' ? (mode === 'verify' ? 'Verify again' : 'Generate again') : mode === 'verify' ? 'Verify all targets' : 'Generate'}
        </Button>
        {run.phase === 'running' && (
          <span className="xstd-loading-row" role="status" data-testid="multi-export-progress">
            <Loader2 className="motion-safe:animate-spin" aria-hidden />
            {mode === 'verify' ? 'Verifying' : 'Exporting'}… {run.percent}%
          </span>
        )}
        {run.phase === 'done' && mode === 'generate' && status?.state === 'completed' && (
          <Button variant="outline" onClick={() => void download()} disabled={downloading}
            title={downloading ? 'The archive is downloading.' : undefined}
            data-testid="multi-export-download"
          >
            <Download aria-hidden />
            Download .zip
          </Button>
        )}
      </div>

      {run.phase === 'error' && (
        <Alert variant="error" data-testid="multi-export-error">
          {run.message}
        </Alert>
      )}
      {status && status.state !== 'completed' && (
        <Alert variant="error" data-testid="multi-export-error">
          {status.error?.message ?? `The export ${status.state}.`}
        </Alert>
      )}

      {rows.length > 0 && (
        <>
          <p className="xstd-quiet" role="status" data-testid="multi-export-summary">
            {failed === 0
              ? `${rows.length} of ${rows.length} completed${mode === 'verify' ? ' — fidelity measured, nothing generated' : ''}.`
              : `${rows.length - failed} of ${rows.length} completed, ${failed} failed — the archive holds the rest.`}
            {result?.fidelity_rollup
              ? ` Lowest fidelity: ${result.fidelity_rollup.tier}, ${result.fidelity_rollup.min_preserved_percent}% preserved.`
              : ''}
          </p>
          <table className="xstd-outcomes" data-testid="multi-export-outcomes">
            <thead>
              <tr>
                {showItem && <th scope="col">Item</th>}
                <th scope="col">Target</th>
                <th scope="col">Version</th>
                <th scope="col">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} data-state={row.state}>
                  {showItem && <td>{label(row.artifact)}</td>}
                  <td>{label(row.target)}</td>
                  <td>{row.version}</td>
                  <td>
                    {row.state === 'failed' ? (
                      <span className="xstd-outcomes__error">{row.error}</span>
                    ) : row.tier ? (
                      <Badge variant={tierTone(row.tier as ExportFidelityTier)}>
                        {row.tier}
                        {row.preservedPercent != null ? ` · ${row.preservedPercent}% preserved` : ''}
                      </Badge>
                    ) : (
                      'Completed'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
