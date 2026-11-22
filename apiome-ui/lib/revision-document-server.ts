/**
 * Read a revision's OpenAPI document from apiome-rest, from a Next.js route (COA-5.13, #7089).
 *
 * The merge-request and review spec routes used to build the document here with a TypeScript
 * generator that queried Postgres. They now read the document apiome-rest renders once and keeps in
 * the document store: `GET /v1/versions/{tenant}/{project}/{version}/document`. REST checks
 * `versions:view` for the signed-in user, so a revision the caller cannot see is never returned.
 */

import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';
import { prettyDocumentText } from '@lib/revision-document-text';

/** Who is asking, as the route's context already holds it. */
export interface RevisionDocumentCaller {
  /** The signed-in user (for the REST credentials). */
  user: Parameters<typeof createRestAuthHeaders>[0];
  /** The slug of the user's current workspace. */
  tenantSlug: string;
}

/** A document read from REST. */
export interface RevisionDocumentRead {
  ok: true;
  /** The document as JSON text, two-space indented. */
  spec: string;
  /** The SHA-256 of the document REST served; equal for two revisions with the same document. */
  sha256: string | null;
}

/** Why a document could not be read. */
export interface RevisionDocumentFailure {
  ok: false;
  /** The status to answer with: REST's own error status, or 502. */
  status: number;
  /** What to tell the reader. */
  error: string;
  /** REST's `detail.code`, when it sent one. */
  code?: string;
}

/**
 * Read one revision's rendered OpenAPI document.
 *
 * @param caller The signed-in user and workspace.
 * @param projectId The project (or catalog item) UUID.
 * @param versionId The revision UUID.
 * @returns The document and its digest, or the failure to answer with. Never throws.
 */
export async function fetchRevisionDocument(
  caller: RevisionDocumentCaller,
  projectId: string,
  versionId: string,
): Promise<RevisionDocumentRead | RevisionDocumentFailure> {
  const url =
    `${REST_API_BASE_URL}/versions/${encodeURIComponent(caller.tenantSlug)}` +
    `/${encodeURIComponent(projectId)}/${encodeURIComponent(versionId)}/document`;
  const headers: Record<string, string> = { ...createRestAuthHeaders(caller.user) };
  delete headers['Content-Type'];

  let rest: Response;
  try {
    rest = await fetch(url, { method: 'GET', headers, cache: 'no-store' });
  } catch {
    return { ok: false, status: 502, error: 'apiome-rest could not be reached.' };
  }
  if (!rest.ok) {
    const data = (await rest.json().catch(() => null)) as { detail?: unknown } | null;
    const detail = data?.detail as string | { message?: unknown; code?: unknown } | undefined;
    const message =
      typeof detail === 'string'
        ? detail
        : typeof detail?.message === 'string'
          ? detail.message
          : null;
    return {
      ok: false,
      status: rest.status >= 400 ? rest.status : 502,
      error: message || `The document could not be read (HTTP ${rest.status}).`,
      code:
        typeof detail === 'object' && typeof detail?.code === 'string' ? detail.code : undefined,
    };
  }
  try {
    return {
      ok: true,
      spec: prettyDocumentText(await rest.text()),
      sha256: rest.headers.get('x-apiome-content-sha256'),
    };
  } catch {
    return { ok: false, status: 502, error: 'apiome-rest returned a document that is not JSON.' };
  }
}
