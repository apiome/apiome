/**
 * Client helpers for the usage-data controls — RDG-5.4 (#5789).
 *
 * Everything talks to the `/api/usage` proxy, which forwards to the REST layer's tenant-scoped
 * usage endpoints and answers `{success, data}` or `{success: false, error, code?}`. These
 * wrappers throw the message, so a caller can `try`/`catch` one way for every write. The export
 * is not fetched here: it is a download link ({@link exportHref}).
 */

import type {
  BodySampleWindow,
  RetentionDays,
  ToolsetBodySamples,
  UsageRetention,
  UsageSource,
  UsageSourceList,
} from './usageDataModel';

/**
 * Call the proxy and unwrap its envelope.
 *
 * @param path The path under `/api/usage`.
 * @param init Fetch options.
 * @returns The `data` payload.
 * @throws Error carrying the proxy's message when the call failed.
 */
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/usage${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  const body = await response.json().catch(() => null);
  if (!body?.success) throw new Error(body?.error || 'Request failed');
  return body.data as T;
}

/** The workspace's retention: caps, its own values and what applies. */
export function fetchRetention(): Promise<UsageRetention> {
  return call<UsageRetention>('/:retention');
}

/**
 * Lower (or reset) the workspace's retention.
 *
 * @param values The days to keep; `null` goes back to the tier cap.
 * @returns The retention after the change.
 */
export function saveRetention(values: RetentionDays): Promise<UsageRetention> {
  return call<UsageRetention>('/:retention', { method: 'PUT', body: JSON.stringify(values) });
}

/**
 * The project's usage sources and agent toolsets.
 *
 * @param projectRef Project slug or id.
 * @returns The list, with the acknowledgement sentence.
 */
export function fetchUsageSources(projectRef: string): Promise<UsageSourceList> {
  return call<UsageSourceList>(`/${encodeURIComponent(projectRef)}/sources`);
}

/**
 * Change what a source captures.
 *
 * @param projectRef Project slug or id.
 * @param sourceId The source.
 * @param patch `samplingRate`, `fieldCapture` and/or `bodySamples`.
 * @returns The source after the change.
 */
export function updateUsageSource(
  projectRef: string,
  sourceId: string,
  patch: { samplingRate?: number; fieldCapture?: boolean; bodySamples?: BodySampleWindow },
): Promise<UsageSource> {
  return call<UsageSource>(`/${encodeURIComponent(projectRef)}/sources/${encodeURIComponent(sourceId)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
}

/**
 * Open or close an agent toolset's body capture.
 *
 * @param toolsetId The toolset.
 * @param window The window (`rate: 0` closes it).
 * @returns The toolset after the change.
 */
export function updateToolsetBodySamples(toolsetId: string, window: BodySampleWindow): Promise<ToolsetBodySamples> {
  return call<ToolsetBodySamples>(`/:toolsets/${encodeURIComponent(toolsetId)}/body-samples`, {
    method: 'PATCH',
    body: JSON.stringify(window),
  });
}
