/**
 * Export history — the fetches (MFX-46.1, #4379). Every call goes through the `/api/export/runs…` proxy,
 * which scopes it to the signed-in workspace; failures throw the shared delivery-API error with REST's
 * message.
 */

import { readPage, type PageInfo, type PageRequest } from '@lib/cursor-pages';
import { deliveryApi } from '../delivery/deliveryProfilesApi';
import {
  historyQuery,
  type ExportRunActor,
  type ExportRunDetail,
  type ExportRunPage,
  type ExportRunSummary,
  type HistoryFilters,
} from './exportHistoryModel';

/**
 * One page of the workspace's export history.
 *
 * @param filters The filters.
 * @param page Where the page starts (the previous page's cursor), and whether to count.
 * @returns The runs on that page and what it says about the rest: whether another page follows,
 *   its cursor, and the total when it was asked for.
 */
export async function fetchExportRuns(
  filters: HistoryFilters,
  page: PageRequest = {}
): Promise<{ runs: ExportRunSummary[]; page: PageInfo }> {
  const data = await deliveryApi<Partial<ExportRunPage>>(`/api/export/runs?${historyQuery(filters, page)}`);
  return {
    runs: Array.isArray(data?.runs) ? data.runs : [],
    page: readPage(data),
  };
}

/**
 * One run with its stored reports.
 *
 * @param jobId The export job.
 * @returns The run.
 */
export function fetchExportRun(jobId: string): Promise<ExportRunDetail> {
  return deliveryApi<ExportRunDetail>(`/api/export/runs/${encodeURIComponent(jobId)}`);
}

/** The people in the history, most recent first (for the actor filter). */
export async function fetchExportRunActors(): Promise<ExportRunActor[]> {
  const data = await deliveryApi<{ actors?: ExportRunActor[] }>('/api/export/runs/actors');
  return Array.isArray(data?.actors) ? data.actors : [];
}

export { DeliveryProfilesError as ExportHistoryError } from '../delivery/deliveryProfilesApi';
