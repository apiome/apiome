/**
 * Export history — the fetches (MFX-46.1, #4379). Every call goes through the `/api/export/runs…` proxy,
 * which scopes it to the signed-in workspace; failures throw the shared delivery-API error with REST's
 * message.
 */

import { deliveryApi } from '../delivery/deliveryProfilesApi';
import {
  historyQuery,
  type ExportRunActor,
  type ExportRunDetail,
  type ExportRunPage,
  type HistoryFilters,
} from './exportHistoryModel';

/**
 * One page of the workspace's export history.
 *
 * @param filters The filters.
 * @param page Zero-based page.
 * @returns The runs on that page and the total matching.
 */
export async function fetchExportRuns(filters: HistoryFilters, page: number): Promise<ExportRunPage> {
  const data = await deliveryApi<Partial<ExportRunPage>>(`/api/export/runs?${historyQuery(filters, page)}`);
  return {
    runs: Array.isArray(data?.runs) ? data.runs : [],
    total: typeof data?.total === 'number' ? data.total : 0,
    limit: typeof data?.limit === 'number' ? data.limit : 0,
    offset: typeof data?.offset === 'number' ? data.offset : 0,
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
