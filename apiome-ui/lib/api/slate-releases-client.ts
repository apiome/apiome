/**
 * Client for the managed Slate deployment control plane — APX-3.1 (private-suite#2456).
 *
 * Calls the `/api/slate/*` Next proxy, which mints the REST JWT server-side; the browser
 * never sees a tenant slug or a token. Every function returns a result object rather than
 * throwing, matching `rest-client.ts` and `paths-client.ts`.
 *
 * **Refusals are not errors.** The control plane answers a blocked promotion or rollback
 * with 409 and a named `reason` plus an operator-facing `message`. Collapsing that into a
 * generic failure string would leave the Release Center with a greyed-out control and
 * nothing to say about it, so refusals are surfaced as a distinct `refusal` field with the
 * reason preserved. Callers can render the sentence verbatim.
 */

/** Reasons the control plane can refuse to change routing. Mirrors the backend vocabulary. */
export type SlateRefusalReason =
  | 'not-built'
  | 'not-promotable'
  | 'already-active'
  | 'nothing-active'
  | 'no-rollback-target'
  | 'stale-approval'
  | 'approval-required'
  | 'artifact-reaped'
  | 'signature-invalid'
  | 'partial-region'
  | 'concurrent-activation';

/** A named refusal with the sentence to show the operator. */
export interface SlateRefusal {
  reason: SlateRefusalReason | string;
  message: string;
  /** Present on a concurrency conflict, so the caller can re-read and retry deliberately. */
  expectedRoutingVersion?: number;
  actualRoutingVersion?: number;
}

/** The built artifact a release routes to. */
export interface SlateReleaseArtifact {
  digest: string;
  sourceDigest?: string | null;
  configDigest?: string | null;
  pageCount: number;
  sizeBytes: number;
  builtAt?: string | null;
  /** False when the stored signature does not verify against the stored digests. */
  signatureVerified: boolean;
  /** False once retention has reaped the bytes; a reaped artifact is not a rollback target. */
  retained: boolean;
}

/** One immutable release, as the control plane reports it. */
export interface SlateRelease {
  id: string;
  releaseRef: string;
  environment: string;
  environmentId: string;
  status: string;
  source: { commit: string; ref: string; message: string };
  artifact: SlateReleaseArtifact;
  actor: { id?: string | null; name: string; kind: 'user' | 'automation' };
  createdAt: string;
  activatedAt?: string | null;
  activationCompletedAt?: string | null;
  deactivatedAt?: string | null;
  traffic?: {
    percent: number;
    requestsPerMinute: number;
    regions: Array<{ regionId?: string; label?: string; status: string }>;
  } | null;
  impact: Record<string, unknown>;
  domains: Array<Record<string, unknown>>;
  checks: Array<Record<string, unknown>>;
  phases: Array<Record<string, unknown>>;
  approvals: Array<Record<string, unknown>>;
  changedPages: Array<Record<string, unknown>>;
  logs: Array<Record<string, unknown>>;
  audit: Array<Record<string, unknown>>;
}

/** Lane state: what is serving, how far it reached, and against what budget. */
export interface SlateEnvironment {
  id: string;
  siteId: string;
  kind: 'production' | 'staging' | 'preview' | string;
  name: string;
  activeReleaseId: string | null;
  routingVersion: number;
  robotsExcluded: boolean;
  accessPolicy: string;
  expiresAt?: string | null;
  rollout: {
    state: 'complete' | 'partial' | 'failed' | 'pending' | string;
    total: number;
    active: number;
    activating: number;
    failed: number;
    outstanding: string[];
  };
  activationSlo: {
    state: 'not-started' | 'within' | 'breaching' | 'breached' | string;
    elapsedSeconds: number | null;
    budgetSeconds: number;
    inProgress: boolean;
  };
  domains: Array<Record<string, unknown>>;
}

/** What an activation would do. `rebuilds` is always false — promotion routes, never builds. */
export interface SlateActivationPlan {
  action: 'promotion' | 'rollback';
  environmentId: string;
  releaseId: string;
  artifactDigest: string;
  replacesReleaseId: string | null;
  expectedRoutingVersion: number;
  rebuilds: false;
  invalidatedPages: number;
}

/** Outcome of a promotion or rollback. */
export interface SlateActivationResult {
  applied: boolean;
  dryRun: boolean;
  plan: SlateActivationPlan;
  activationId?: string | null;
  routingVersion?: number | null;
  activatedAt?: string | null;
}

/** Uniform result shape: success, a named refusal, or a transport/server error. */
export type SlateResult<T> =
  | { success: true; data: T }
  | { success: false; refusal: SlateRefusal; error?: undefined }
  | { success: false; error: string; refusal?: undefined };

/** Statuses that carry a named refusal rather than a generic failure. */
const REFUSAL_STATUS = 409;

/**
 * Issue a request to the Slate proxy and normalize the outcome.
 *
 * @param path - Path under `/api/slate`.
 * @param init - Fetch options; omit for a GET.
 * @returns A success, a named refusal, or an error string.
 */
async function request<T>(path: string, init?: RequestInit): Promise<SlateResult<T>> {
  try {
    const response = await fetch(`/api/slate${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });

    const payload = await response.json().catch(() => null);

    if (response.status === REFUSAL_STATUS) {
      // FastAPI nests the structured refusal under `detail`; the proxy forwards it intact.
      const detail = (payload?.detail ?? payload) as Record<string, unknown> | null;
      return {
        success: false,
        refusal: {
          reason: String(detail?.reason ?? detail?.code ?? 'refused'),
          message: String(detail?.message ?? 'Routing cannot change for this release.'),
          expectedRoutingVersion: detail?.expectedRoutingVersion as number | undefined,
          actualRoutingVersion: detail?.actualRoutingVersion as number | undefined,
        },
      };
    }

    if (!response.ok) {
      const detail = payload?.detail;
      const message =
        (typeof detail === 'object' && detail !== null
          ? (detail as Record<string, unknown>).message
          : detail) ??
        payload?.error ??
        `HTTP ${response.status}`;
      return { success: false, error: String(message) };
    }

    return { success: true, data: payload as T };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Request failed',
    };
  }
}

/**
 * List a site's release timeline, newest first.
 *
 * @param siteId - The hosted site.
 * @param environmentId - Restrict the timeline to one lane.
 * @param limit - Maximum releases to return.
 * @returns The releases, or a failure.
 */
export async function listSlateReleases(
  siteId: string,
  environmentId?: string,
  limit?: number
): Promise<SlateResult<{ releases: SlateRelease[] }>> {
  const params = new URLSearchParams();
  if (environmentId) params.set('environmentId', environmentId);
  if (limit) params.set('limit', String(limit));
  const query = params.toString();
  return request(`/sites/${encodeURIComponent(siteId)}/releases${query ? `?${query}` : ''}`);
}

/**
 * Load one release with its full evidence.
 *
 * @param releaseId - The release.
 * @returns The release, or a failure.
 */
export async function getSlateRelease(releaseId: string): Promise<SlateResult<SlateRelease>> {
  return request(`/releases/${encodeURIComponent(releaseId)}`);
}

/**
 * Load a lane's state: active release, rollout progress and activation SLO.
 *
 * @param environmentId - The lane.
 * @returns The environment, or a failure.
 */
export async function getSlateEnvironment(
  environmentId: string
): Promise<SlateResult<SlateEnvironment>> {
  return request(`/environments/${encodeURIComponent(environmentId)}`);
}

/**
 * Promote a release: route the lane to already-built bytes. Never rebuilds.
 *
 * @param environmentId - The lane to change.
 * @param releaseId - The release to route to.
 * @param options - `dryRun` validates every gate and returns the plan without changing
 *                  routing; `requireApproval` enforces the lane's approval policy.
 * @returns The activation outcome, or a named refusal.
 */
export async function promoteSlateRelease(
  environmentId: string,
  releaseId: string,
  options?: { dryRun?: boolean; requireApproval?: boolean }
): Promise<SlateResult<SlateActivationResult>> {
  return request(`/environments/${encodeURIComponent(environmentId)}/promote`, {
    method: 'POST',
    body: JSON.stringify({
      releaseId,
      dryRun: options?.dryRun ?? false,
      requireApproval: options?.requireApproval ?? false,
    }),
  });
}

/**
 * Roll a lane back to its most recent retained artifact.
 *
 * Deliberately takes no release id: the control plane selects the target, so the UI cannot
 * ask to roll back to bytes that retention has already reaped.
 *
 * @param environmentId - The lane to roll back.
 * @param options - `dryRun` validates and returns the plan without changing routing.
 * @returns The activation outcome, or a named refusal.
 */
export async function rollbackSlateEnvironment(
  environmentId: string,
  options?: { dryRun?: boolean }
): Promise<SlateResult<SlateActivationResult>> {
  return request(`/environments/${encodeURIComponent(environmentId)}/rollback`, {
    method: 'POST',
    body: JSON.stringify({ dryRun: options?.dryRun ?? false }),
  });
}

/**
 * Run the retention sweep for one lane.
 *
 * @param siteId - The hosted site.
 * @param environmentId - The lane whose history to sweep.
 * @returns How many artifacts were reaped, or a failure.
 */
export async function runSlateRetention(
  siteId: string,
  environmentId: string
): Promise<
  SlateResult<{ reaped: number; reapedReleaseIds: string[]; retainedReleases: number }>
> {
  return request(
    `/sites/${encodeURIComponent(siteId)}/retention?environmentId=${encodeURIComponent(
      environmentId
    )}`,
    { method: 'POST' }
  );
}
