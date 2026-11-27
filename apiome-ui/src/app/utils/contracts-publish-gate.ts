/**
 * Types and fetch helper for the contracts publish gate (PFX-7.3, #6963).
 *
 * The verdict is computed by apiome-rest — the Pact can-i-deploy verdict for the revision's
 * version, read under the tenant's `contracts.publishPolicy`. The UI never re-derives
 * "deployable"; it fetches the server assessment and presents it.
 */

/** Tenant policy level: what a failing contract does to a publish. */
export type ContractsPublishPolicy = 'off' | 'warn' | 'block';

/**
 * The assessment outcome. Only `blocked` refuses a publish. `pending` is a missing verification
 * result ("not verified yet" is not "failed"); `unavailable` means the verdict could not be read.
 */
export type ContractsPublishStatus =
  | 'disabled'
  | 'no-contracts'
  | 'ok'
  | 'warning'
  | 'blocked'
  | 'pending'
  | 'unavailable';

/** One per-row reason from can-i-deploy, e.g. "Verification failed for web". */
export interface ContractsPublishReason {
  type: string;
  code: string;
  text: string;
}

export interface ContractsPublishGate {
  policy: ContractsPublishPolicy;
  status: ContractsPublishStatus;
  /** The gate has a warning or a block to report. */
  triggered: boolean;
  /** Publish is refused unless force-published with a reason. */
  blocked: boolean;
  pacticipant: string | null;
  version: string | null;
  environment: string | null;
  /** Null while a verification result is missing. */
  deployable: boolean | null;
  reasons: ContractsPublishReason[];
  counts: Record<string, number>;
  reason: string | null;
  detail: string | null;
  message: string;
}

/** Short label per status, for the badge. */
const STATUS_LABELS: Record<ContractsPublishStatus, string> = {
  blocked: 'Blocked',
  warning: 'Warning',
  pending: 'Pending',
  ok: 'Deployable',
  'no-contracts': 'No contracts',
  disabled: 'Off',
  unavailable: 'Not checked',
};

/** Return the display label for a gate status (defensive fallback for unknowns). */
export function contractsGateStatusLabel(status: string): string {
  return STATUS_LABELS[status as ContractsPublishStatus] ?? 'Not checked';
}

/**
 * Whether the gate has something to say in the dialog.
 *
 * A warning, a block, or a pending verification surface; everything else is silent so a
 * project without contracts sees no friction.
 */
export function contractsGateIsVisible(gate: ContractsPublishGate | null): boolean {
  return !!gate && (gate.triggered || gate.status === 'pending');
}

/**
 * Fetch the gate assessment for a revision via the Next.js proxy.
 * @throws Error with the server message when the request fails.
 */
export async function fetchContractsPublishGate(
  projectId: string,
  versionId: string,
  options?: { signal?: AbortSignal }
): Promise<ContractsPublishGate> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(versionId)}/contracts-publish-gate`,
    { method: 'GET', signal: options?.signal }
  );
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || data.success === false) {
    const message =
      (data && (data.error || data.detail)) ||
      `Failed to load the contracts gate (HTTP ${response.status})`;
    throw new Error(typeof message === 'string' ? message : 'Failed to load the contracts gate');
  }
  return data as ContractsPublishGate;
}
