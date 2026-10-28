/**
 * Multi-target and multi-item export jobs (E1-3, #6219).
 *
 * Two surfaces run one export job that delivers one `.zip`:
 *
 * - the Export studio's **Several targets** mode — one source × 2+ targets (MFX-39.1), every target
 *   with its default options; Verify runs it as a dry run (fidelity only), Generate for real;
 * - the Catalog bulk bar's **Export…** — several items × one target, a batch job (`items`, E1-3)
 *   whose failures are per item.
 *
 * This module holds what both share: the request bodies, the outcome rows a result reads as, and
 * the submit / poll / download calls over the existing `/api/export/jobs` proxies.
 */

import type { ExportJobStatus } from './exportJob';
import { downloadBlob, filenameFromDisposition } from './exportDownload';

/** The REST cap on item × target pairs in one batch export job. */
export const MAX_EXPORT_PAIRS = 100;

/** One requested target of a multi-target job. */
export interface ExportJobTargetSpec {
  /** The registry target key. */
  target: string;
}

/** One requested item of a multi-item batch job. */
export interface ExportJobItemRef {
  /** The artifact (catalog item / project) id. */
  artifact: string;
  /** The version to export; omitted for the latest. */
  version?: string;
}

/** The `POST /api/export/jobs` body for a multi-target or multi-item job. */
export interface MultiExportJobBody {
  artifact?: string;
  version?: string;
  items?: ExportJobItemRef[];
  targets: ExportJobTargetSpec[];
  dry_run?: boolean;
  confirm?: boolean;
}

/**
 * The body for one source exported to several targets (each with its defaults).
 *
 * @param artifact The source artifact id.
 * @param version The revision (UUID or label), or null for the latest.
 * @param targetKeys The target keys, in the order chosen; duplicates are dropped.
 * @param dryRun True to stop after the fidelity report (Verify).
 * @returns The request body.
 */
export function multiTargetJobBody(
  artifact: string,
  version: string | null,
  targetKeys: readonly string[],
  dryRun = false,
): MultiExportJobBody {
  return {
    artifact,
    ...(version ? { version } : {}),
    targets: [...new Set(targetKeys)].map((target) => ({ target })),
    ...(dryRun ? { dry_run: true } : {}),
  };
}

/**
 * The body for several items exported (each at its latest version) to one target.
 *
 * @param itemIds The artifact ids, in selection order; duplicates are dropped.
 * @param targetKey The target key.
 * @returns The request body.
 */
export function itemsBatchJobBody(itemIds: readonly string[], targetKey: string): MultiExportJobBody {
  return {
    items: [...new Set(itemIds)].map((artifact) => ({ artifact })),
    targets: [{ target: targetKey }],
  };
}

/** One item × target outcome, as the outcome table renders it. */
export interface ExportOutcomeRow {
  /** Stable row key. */
  key: string;
  /** The artifact id (a batch item) or the job's source. */
  artifact: string;
  /** The version label (or the requested reference). */
  version: string;
  /** The resolved target key. */
  target: string;
  /** Whether the item completed. */
  state: 'completed' | 'failed';
  /** The fidelity tier, when known. */
  tier: string | null;
  /** Share of constructs preserved, when known. */
  preservedPercent: number | null;
  /** The failure message of a failed item. */
  error: string | null;
}

interface FidelityLike {
  tier?: string | null;
  preserved_percent?: number | null;
  summary?: { tier?: string | null; preserved_percent?: number | null } | null;
}

/** The parts of a multi-target / batch `ExportJobResult` the outcome rows read. */
export interface MultiExportResult {
  artifact?: string;
  version_label?: string | null;
  dry_run?: boolean;
  download_path?: string | null;
  fidelity_rollup?: { tier: string; min_preserved_percent: number; target_count: number } | null;
  targets?: Array<{ target: string; fidelity?: FidelityLike | null }> | null;
  batch?: {
    item_count: number;
    completed_count: number;
    failed_count: number;
    items: Array<{
      artifact?: string | null;
      version: string;
      version_label?: string | null;
      target: string;
      state: 'completed' | 'failed';
      tier?: string | null;
      preserved_percent?: number | null;
      error?: { message?: string } | null;
    }>;
  } | null;
}

function fidelityOf(fidelity: FidelityLike | null | undefined): Pick<ExportOutcomeRow, 'tier' | 'preservedPercent'> {
  const summary = fidelity?.summary ?? fidelity ?? null;
  return {
    tier: summary?.tier ?? null,
    preservedPercent: typeof summary?.preserved_percent === 'number' ? summary.preserved_percent : null,
  };
}

/**
 * The outcome rows of a completed multi-target or batch job.
 *
 * A batch lists every item (completed or failed); a multi-target job lists every target (all
 * completed — the job is all-or-nothing).
 *
 * @param result The job's result.
 * @returns One row per item × target, in submission order.
 */
export function exportOutcomeRows(result: MultiExportResult | null | undefined): ExportOutcomeRow[] {
  if (!result) return [];
  if (result.batch) {
    return result.batch.items.map((item, index) => ({
      key: `${index}-${item.artifact ?? ''}-${item.target}`,
      artifact: item.artifact ?? result.artifact ?? '',
      version: item.version_label ?? item.version,
      target: item.target,
      state: item.state,
      ...fidelityOf({ tier: item.tier, preserved_percent: item.preserved_percent }),
      error: item.state === 'failed' ? item.error?.message ?? 'This item failed.' : null,
    }));
  }
  return (result.targets ?? []).map((target, index) => ({
    key: `${index}-${target.target}`,
    artifact: result.artifact ?? '',
    version: result.version_label ?? '',
    target: target.target,
    state: 'completed' as const,
    ...fidelityOf(target.fidelity),
    error: null,
  }));
}

/** Read a `{ success, error }` envelope's message, or a fallback. */
async function errorMessage(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => null);
  const error = data?.error ?? data?.detail;
  if (typeof error === 'string' && error) return error;
  if (Array.isArray(error) && typeof error[0]?.msg === 'string') return error[0].msg;
  if (error && typeof error.message === 'string') return error.message;
  return fallback;
}

/**
 * Submit a multi-target or batch export job.
 *
 * @param body The job body.
 * @returns The new job's id.
 * @throws Error with the server's message when the job was refused.
 */
export async function submitMultiExportJob(body: MultiExportJobBody): Promise<string> {
  const res = await fetch('/api/export/jobs', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorMessage(res, 'The export could not be started.'));
  const data = await res.json();
  if (typeof data?.job_id !== 'string') throw new Error('The export could not be started.');
  return data.job_id;
}

/**
 * Poll an export job until it is terminal.
 *
 * @param jobId The job id.
 * @param options `onStatus` sees every poll; `signal` stops polling (the promise rejects);
 *   `intervalMs` paces the polls.
 * @returns The terminal status.
 */
export async function pollMultiExportJob(
  jobId: string,
  options: { onStatus?: (status: ExportJobStatus) => void; signal?: AbortSignal; intervalMs?: number } = {},
): Promise<ExportJobStatus> {
  const { onStatus, signal, intervalMs = 1000 } = options;
  for (;;) {
    if (signal?.aborted) throw new DOMException('Polling stopped', 'AbortError');
    const res = await fetch(`/api/export/jobs/${encodeURIComponent(jobId)}`, {
      credentials: 'include',
      signal,
    });
    if (!res.ok) throw new Error(await errorMessage(res, 'The export status could not be read.'));
    const status = (await res.json()) as ExportJobStatus;
    onStatus?.(status);
    if (status.state === 'completed' || status.state === 'failed' || status.state === 'canceled') {
      return status;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

/**
 * Download a completed job's archive as a file.
 *
 * @param jobId The job id.
 * @param fallbackName The filename when the server names none.
 * @throws Error when the archive could not be fetched.
 */
export async function downloadMultiExportArchive(jobId: string, fallbackName: string): Promise<void> {
  const res = await fetch(`/api/export/jobs/${encodeURIComponent(jobId)}/download`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error(await errorMessage(res, 'The archive could not be downloaded.'));
  const name = filenameFromDisposition(res.headers.get('content-disposition')) || fallbackName;
  downloadBlob(await res.blob(), name);
}
