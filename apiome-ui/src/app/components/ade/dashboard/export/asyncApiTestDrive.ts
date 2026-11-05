/**
 * The Studio half of the AsyncAPI test drive (the AsyncAPI renderer) — MFX-44.4 (#4370).
 *
 * The emitted document is read here first, so a file that is not AsyncAPI 2.x / 3.x shows a notice
 * instead of an empty renderer, then posted into the sandboxed page (`/test-drive/asyncapi`, see
 * `lib/test-drive/asyncapi-viewer.ts`) — it never makes a server round-trip. The renderer itself
 * validates the document and draws its own error panel for one it rejects.
 */

import { parse as parseYaml } from 'yaml';

/** The AsyncAPI major versions the renderer reads. */
export const SUPPORTED_ASYNCAPI_MAJORS = ['2', '3'] as const;

/** The operation keys a 2.x channel item can hold. */
const V2_OPERATION_KEYS = ['publish', 'subscribe'];

/** A parsed AsyncAPI document, ready for the renderer. */
export interface AsyncApiTestDriveDocument {
  /** The document as an object. */
  spec: Record<string, unknown>;
  /** The `asyncapi` version string, e.g. `3.1.0` or `2.6.0`. */
  version: string;
  /** How many channels it declares. */
  channels: number;
  /** How many operations it declares (3.x `operations`; 2.x `publish` / `subscribe` per channel). */
  operations: number;
}

/** The outcome of reading an emitted file as AsyncAPI. */
export type AsyncApiParseResult = { ok: true; document: AsyncApiTestDriveDocument } | { ok: false; error: string };

/**
 * The number of keys of an object member, or 0 when it is not an object.
 *
 * @param value The member.
 * @returns Its key count.
 */
function keyCount(value: unknown): number {
  return value && typeof value === 'object' && !Array.isArray(value) ? Object.keys(value).length : 0;
}

/**
 * Count a document's operations.
 *
 * @param spec An AsyncAPI document.
 * @param major Its major version (`2` or `3`).
 * @returns The 3.x `operations` entries, or the 2.x `publish` / `subscribe` entries across channels.
 */
export function countAsyncApiOperations(spec: Record<string, unknown>, major: string): number {
  if (major !== '2') return keyCount(spec.operations);
  const channels = spec.channels;
  if (!channels || typeof channels !== 'object') return 0;
  let count = 0;
  for (const item of Object.values(channels as Record<string, unknown>)) {
    if (!item || typeof item !== 'object') continue;
    count += V2_OPERATION_KEYS.filter((key) => key in (item as Record<string, unknown>)).length;
  }
  return count;
}

/**
 * Read an emitted file as an AsyncAPI 2.x / 3.x document.
 *
 * @param text The file's text (JSON or YAML).
 * @returns The document, or why it cannot be shown.
 */
export function parseAsyncApiDocument(text: string): AsyncApiParseResult {
  let value: unknown;
  try {
    value = text.trimStart().startsWith('{') ? JSON.parse(text) : parseYaml(text);
  } catch (error) {
    return { ok: false, error: `The file is not valid JSON or YAML: ${error instanceof Error ? error.message : error}` };
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { ok: false, error: 'The file is not an AsyncAPI document.' };
  }
  const spec = value as Record<string, unknown>;
  if (typeof spec.asyncapi !== 'string') {
    return { ok: false, error: 'The file has no `asyncapi` version, so it is not an AsyncAPI document.' };
  }
  const version = spec.asyncapi;
  const major = version.split('.')[0];
  if (!(SUPPORTED_ASYNCAPI_MAJORS as readonly string[]).includes(major)) {
    return { ok: false, error: `AsyncAPI ${version} cannot be rendered here: the viewer reads AsyncAPI 2.x and 3.x.` };
  }
  return {
    ok: true,
    document: { spec, version, channels: keyCount(spec.channels), operations: countAsyncApiOperations(spec, major) },
  };
}

/**
 * The note's summary of the document, e.g. `AsyncAPI 3.1.0 · 2 channels · 3 operations`.
 *
 * @param document The parsed document.
 * @returns The summary.
 */
export function asyncApiSummaryText(document: Pick<AsyncApiTestDriveDocument, 'version' | 'channels' | 'operations'>): string {
  const count = (n: number, one: string) => `${n} ${n === 1 ? one : `${one}s`}`;
  return [`AsyncAPI ${document.version}`, count(document.channels, 'channel'), count(document.operations, 'operation')].join(' · ');
}

/**
 * The AsyncAPI viewer page's URL (`ASYNCAPI_VIEWER_PATH`; kept here so the client bundle does not pull in
 * the server-side page module).
 *
 * @returns The iframe's `src`.
 */
export function asyncApiViewerSrc(): string {
  return '/test-drive/asyncapi';
}
