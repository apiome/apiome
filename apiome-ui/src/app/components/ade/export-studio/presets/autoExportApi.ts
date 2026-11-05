/**
 * Auto-export on version publish — the client contract and the pure helpers (MFX-39.4, #4336).
 *
 * An auto-export subscription runs an export preset on every publish of a project and delivers it through
 * the preset's delivery profile, unless the export's loss reaches `haltAt` (and `approveLoss` is off). A
 * halted run is not delivered; a person can release it. The screens talk to `/api/export/auto-exports` and
 * `/api/export/auto-export-runs`.
 */

import { deliveryApi } from '../delivery/deliveryProfilesApi';

/** Where a subscription halts auto-delivery. */
export type HaltAt = 'warn' | 'critical';

/** A preset run on every publish of a project. */
export interface AutoExportSubscription {
  id: string;
  projectId: string;
  projectName: string | null;
  presetId: string;
  presetName: string | null;
  haltAt: HaltAt;
  approveLoss: boolean;
  active: boolean;
}

/** What one publish's auto-export did. */
export interface AutoExportRun {
  id: string;
  projectId: string;
  projectName: string | null;
  versionRecordId: string;
  subscriptionId: string | null;
  presetName: string;
  status: 'pending' | 'running' | 'delivered' | 'exported' | 'halted' | 'delivery_failed' | 'failed';
  lossSeverity: 'info' | 'warn' | 'critical' | null;
  lossReasons: string[];
  deliveries: { profileName?: string; profileId?: string; outcome?: string; errorCode?: string | null }[];
  errorCode: string | null;
  errorMessage: string | null;
  releasedAt: string | null;
  createdAt: string | null;
}

const JSON_HEADERS = { 'Content-Type': 'application/json' };

/** The subscriptions of one preset (by id). */
export async function fetchAutoExports(presetId: string): Promise<AutoExportSubscription[]> {
  const data = await deliveryApi<{ subscriptions?: AutoExportSubscription[] }>(
    `/api/export/auto-exports?preset=${encodeURIComponent(presetId)}`,
  );
  return Array.isArray(data?.subscriptions) ? data.subscriptions : [];
}

/** Run a preset on every publish of a project. */
export function createAutoExport(body: {
  projectId: string;
  preset: string;
  haltAt: HaltAt;
  approveLoss: boolean;
}): Promise<AutoExportSubscription> {
  return deliveryApi<AutoExportSubscription>('/api/export/auto-exports', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

/** Change a subscription. */
export function updateAutoExport(
  id: string,
  body: Partial<Pick<AutoExportSubscription, 'haltAt' | 'approveLoss' | 'active'>>,
): Promise<AutoExportSubscription> {
  return deliveryApi<AutoExportSubscription>(`/api/export/auto-exports/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

/** Stop running a preset on a project's publishes. */
export async function deleteAutoExport(id: string): Promise<void> {
  await deliveryApi<unknown>(`/api/export/auto-exports/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

/** The recent runs of one subscription. */
export async function fetchAutoExportRuns(subscriptionId: string, limit = 10): Promise<AutoExportRun[]> {
  const data = await deliveryApi<{ runs?: AutoExportRun[] }>(
    `/api/export/auto-export-runs?subscriptionId=${encodeURIComponent(subscriptionId)}&limit=${limit}`,
  );
  return Array.isArray(data?.runs) ? data.runs : [];
}

/** Deliver a halted run anyway. */
export function releaseAutoExportRun(runId: string): Promise<AutoExportRun> {
  return deliveryApi<AutoExportRun>(`/api/export/auto-export-runs/${encodeURIComponent(runId)}/release`, {
    method: 'POST',
  });
}

/** Each run status's label. */
export const RUN_STATUS_LABELS: Readonly<Record<AutoExportRun['status'], string>> = {
  pending: 'Queued',
  running: 'Running',
  delivered: 'Delivered',
  exported: 'Exported',
  halted: 'Halted',
  delivery_failed: 'Delivery failed',
  failed: 'Failed',
};

/**
 * The tone a run's status is drawn in.
 *
 * @param status The run's status.
 * @returns `ok`, `warn`, `danger` or `neutral`.
 */
export function runTone(status: AutoExportRun['status']): 'ok' | 'warn' | 'danger' | 'neutral' {
  if (status === 'delivered' || status === 'exported') return 'ok';
  if (status === 'halted') return 'warn';
  if (status === 'failed' || status === 'delivery_failed') return 'danger';
  return 'neutral';
}

/**
 * One line for what a subscription does.
 *
 * @param sub The subscription.
 * @returns e.g. `Halts at critical loss · loss pre-approved · off`.
 */
export function subscriptionSummary(sub: AutoExportSubscription): string {
  return [
    sub.approveLoss ? 'Delivers whatever the loss (pre-approved)' : `Halts at ${sub.haltAt} loss`,
    sub.active ? null : 'off',
  ]
    .filter(Boolean)
    .join(' · ');
}
