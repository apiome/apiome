/**
 * Read a revision's OpenAPI document from the browser (COA-5.13, #7089).
 *
 * The version view, the compare view and the catalog's version diff show the document apiome-rest
 * renders once per change of a revision and keeps in the document store. They read it through the
 * `/api/versions/[versionId]/document` proxy; nothing is generated in the browser or in the Next.js
 * server.
 *
 * Reads are conditional. The digest REST sends (`X-Apiome-Content-Sha256`, also the `ETag`) is
 * remembered per revision and the printed text is kept in a small cache keyed by that digest. The
 * next read of the revision sends `If-None-Match`; a `304` returns the cached text without a
 * download. Because the cache is keyed by digest, two revisions with the same document share one
 * entry. The cache lives for the page: it is bounded by entry count and by total text size, and a
 * document too large for it is simply not kept.
 */

import { prettyDocumentText, sameDocumentDigest } from '@lib/revision-document-text';

/** A revision's document as the UI shows it. */
export interface RevisionDocument {
  /** The document as JSON text, two-space indented. */
  text: string;
  /** The SHA-256 of the document REST served, or `null` when it sent none. */
  sha256: string | null;
  /** True when REST answered `304` and the text came from this page's cache. */
  notModified: boolean;
}

/** A read that failed; `message` is what to tell the reader. */
export class RevisionDocumentError extends Error {
  /** HTTP status (0 when the request never completed). */
  readonly status: number;
  /** REST's `code`, when it sent one (for example `document-unreadable`). */
  readonly code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'RevisionDocumentError';
    this.status = status;
    this.code = code;
  }
}

/** Most documents kept at once. */
export const DOCUMENT_CACHE_MAX_ENTRIES = 8;
/** Most text kept at once, in UTF-16 code units (about 48 MB of memory). */
export const DOCUMENT_CACHE_MAX_CHARS = 24 * 1024 * 1024;
/** Most revisions whose last digest is remembered. */
const DIGEST_MEMORY_MAX = 500;

/** Printed text by digest, least recently used first. */
const textByDigest = new Map<string, string>();
/** The last digest seen for `projectId/versionId`. */
const digestByRevision = new Map<string, string>();
let cachedChars = 0;

function remember(digest: string, text: string): void {
  if (textByDigest.has(digest)) {
    cachedChars -= textByDigest.get(digest)!.length;
    textByDigest.delete(digest);
  }
  if (text.length > DOCUMENT_CACHE_MAX_CHARS) return;
  textByDigest.set(digest, text);
  cachedChars += text.length;
  while (textByDigest.size > DOCUMENT_CACHE_MAX_ENTRIES || cachedChars > DOCUMENT_CACHE_MAX_CHARS) {
    const oldest = textByDigest.keys().next().value as string;
    cachedChars -= textByDigest.get(oldest)!.length;
    textByDigest.delete(oldest);
  }
}

/** Read a cached text and mark it most recently used. */
function recall(digest: string): string | undefined {
  const text = textByDigest.get(digest);
  if (text === undefined) return undefined;
  textByDigest.delete(digest);
  textByDigest.set(digest, text);
  return text;
}

function rememberDigest(key: string, digest: string): void {
  digestByRevision.delete(key);
  digestByRevision.set(key, digest);
  if (digestByRevision.size > DIGEST_MEMORY_MAX) {
    digestByRevision.delete(digestByRevision.keys().next().value as string);
  }
}

/** Forget every cached document (tests, and a workspace switch). */
export function clearRevisionDocumentCache(): void {
  textByDigest.clear();
  digestByRevision.clear();
  cachedChars = 0;
}

/**
 * The proxy URL of a revision's document.
 *
 * @param projectId The project (or catalog item) UUID.
 * @param versionId The revision UUID.
 * @returns A same-origin URL.
 */
export function revisionDocumentHref(projectId: string, versionId: string): string {
  const query = new URLSearchParams({ projectId });
  return `/api/versions/${encodeURIComponent(versionId)}/document?${query.toString()}`;
}

async function request(href: string, etag: string | null, signal?: AbortSignal): Promise<Response> {
  try {
    return await fetch(href, {
      signal,
      cache: 'no-store',
      headers: etag ? { 'If-None-Match': `"${etag}"` } : undefined,
    });
  } catch (error) {
    if ((error as Error)?.name === 'AbortError') throw error;
    throw new RevisionDocumentError('The document could not be read.', 0);
  }
}

/**
 * Read a revision's OpenAPI document.
 *
 * @param projectId The project (or catalog item) UUID.
 * @param versionId The revision UUID.
 * @param signal Aborts the read.
 * @returns The document's text and digest.
 * @throws RevisionDocumentError when REST refuses or cannot be reached, or sends something that is
 *   not JSON. An aborted read rethrows the `AbortError`.
 */
export async function loadRevisionDocument(
  projectId: string,
  versionId: string,
  signal?: AbortSignal,
): Promise<RevisionDocument> {
  const key = `${projectId}/${versionId}`;
  const href = revisionDocumentHref(projectId, versionId);
  const known = digestByRevision.get(key) ?? null;
  // Only revalidate when the text is still held: a 304 with nothing to show would be useless.
  const etag = known && textByDigest.has(known) ? known : null;

  let response = await request(href, etag, signal);
  if (response.status === 304 && etag) {
    const cached = recall(etag);
    if (cached !== undefined) return { text: cached, sha256: etag, notModified: true };
    // Evicted between the check and the answer: ask again without the validator.
    response = await request(href, null, signal);
  }
  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as {
      error?: string;
      code?: string;
    } | null;
    throw new RevisionDocumentError(
      data?.error || `The document could not be read (HTTP ${response.status}).`,
      response.status,
      data?.code,
    );
  }

  const sha256 = response.headers.get('x-apiome-content-sha256');
  // The same document under another revision: reuse the printed text, skip the parse.
  const shared = sha256 ? recall(sha256) : undefined;
  let text: string;
  if (shared !== undefined) {
    text = shared;
    void response.body?.cancel().catch(() => undefined);
  } else {
    try {
      text = prettyDocumentText(await response.text());
    } catch (error) {
      if ((error as Error)?.name === 'AbortError') throw error;
      throw new RevisionDocumentError(
        'apiome-rest returned a document that is not JSON.',
        response.status,
      );
    }
  }
  if (sha256) {
    remember(sha256, text);
    rememberDigest(key, sha256);
  }
  return { text, sha256, notModified: false };
}

/**
 * Whether two documents are the same, judged by digest alone, so no diff need be computed.
 *
 * @param a One side.
 * @param b The other side.
 * @returns True only when both carry a digest and the digests are equal.
 */
export function sameRevisionDocument(
  a: Pick<RevisionDocument, 'sha256'>,
  b: Pick<RevisionDocument, 'sha256'>,
): boolean {
  return sameDocumentDigest(a.sha256, b.sha256);
}
