/**
 * Read and download a revision's stored original from the browser (COA-5.7, #7083).
 *
 * Everything goes through the `/api/versions/[versionId]/original` proxy, which forwards to
 * `GET /v1/versions/{tenant}/{project}/{version}/original`. The two expected refusals carry a
 * `code` and are turned into a sentence here ({@link originalErrorMessage}), so the version view,
 * the catalog page and the compare view word them the same way.
 */

/** Why an original could not be read. */
export interface OriginalFailure {
  ok: false;
  /** HTTP status (0 when the request never completed). */
  status: number;
  /** `original-not-stored`, `original-withheld`, `original-unreadable`, or `undefined`. */
  code?: string;
  /** What to tell the reader. */
  error: string;
}

/** An original read as text. */
export interface OriginalText {
  ok: true;
  text: string;
  /** The file name REST offered. */
  filename: string;
  /** `X-Apiome-Content-Sha256`, when sent. */
  sha256: string | null;
  /** Length in bytes. */
  size: number;
}

/**
 * The proxy URL of a revision's original.
 *
 * @param projectId The project UUID.
 * @param versionId The revision UUID.
 * @param part A file of a stored set, by its path inside the set.
 * @returns A same-origin URL.
 */
export function versionOriginalHref(projectId: string, versionId: string, part?: string | null): string {
  const query = new URLSearchParams({ projectId });
  if (part) query.set('part', part);
  return `/api/versions/${encodeURIComponent(versionId)}/original?${query.toString()}`;
}

/**
 * The file name a `Content-Disposition` header offers (`filename*` wins).
 *
 * @param header The header, or `null`.
 * @param fallback The name to use when none is offered.
 * @returns A bare file name.
 */
export function filenameFromDisposition(header: string | null, fallback = 'original'): string {
  if (!header) return fallback;
  const star = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header);
  const plain = /filename\s*=\s*"([^"]*)"/i.exec(header);
  let name = '';
  try {
    name = star ? decodeURIComponent(star[1].trim()) : plain ? plain[1] : '';
  } catch {
    name = plain ? plain[1] : '';
  }
  const base = name.replace(/\\/g, '/').split('/').pop()?.trim() ?? '';
  return base && base !== '.' && base !== '..' ? base : fallback;
}

/**
 * Word an original's refusal for the reader.
 *
 * @param code The refusal's `code`.
 * @param fallback REST's own message, used for any other refusal.
 * @returns The sentence.
 */
export function originalErrorMessage(code: string | undefined, fallback?: string): string {
  switch (code) {
    case 'original-not-stored':
      return 'No original file is stored for this version.';
    case 'original-withheld':
      return 'The original was withheld at import under the intake policy, so it cannot be downloaded.';
    case 'original-unreadable':
      return 'The document store did not return the original. Try again, or ask an administrator.';
    default:
      return fallback || 'The original could not be downloaded.';
  }
}

async function failure(response: Response): Promise<OriginalFailure> {
  const data = (await response.json().catch(() => null)) as { error?: string; code?: string } | null;
  return {
    ok: false,
    status: response.status,
    code: data?.code,
    error: originalErrorMessage(data?.code, data?.error),
  };
}

/**
 * Read a revision's original as text (the compare view's Originals mode).
 *
 * @param projectId The project UUID.
 * @param versionId The revision UUID.
 * @param signal Aborts the read.
 * @returns The text and its name, or why it could not be read.
 */
export async function fetchVersionOriginalText(
  projectId: string,
  versionId: string,
  signal?: AbortSignal,
): Promise<OriginalText | OriginalFailure> {
  let response: Response;
  try {
    response = await fetch(versionOriginalHref(projectId, versionId), { signal, cache: 'no-store' });
  } catch (error) {
    if ((error as Error)?.name === 'AbortError') throw error;
    return { ok: false, status: 0, error: 'The original could not be downloaded.' };
  }
  if (!response.ok) return failure(response);
  const buffer = await response.arrayBuffer();
  return {
    ok: true,
    text: new TextDecoder('utf-8').decode(buffer),
    filename: filenameFromDisposition(response.headers.get('content-disposition')),
    sha256: response.headers.get('x-apiome-content-sha256'),
    size: buffer.byteLength,
  };
}

/**
 * Download a revision's original as a file, under the name REST offered.
 *
 * Fetches first (rather than navigating to the URL) so a refusal becomes a message on the page
 * instead of a JSON page in a new tab.
 *
 * @param projectId The project UUID.
 * @param versionId The revision UUID.
 * @returns `{ ok: true, filename }`, or why it could not be downloaded.
 */
export async function downloadVersionOriginal(
  projectId: string,
  versionId: string,
): Promise<{ ok: true; filename: string } | OriginalFailure> {
  let response: Response;
  try {
    response = await fetch(versionOriginalHref(projectId, versionId), { cache: 'no-store' });
  } catch {
    return { ok: false, status: 0, error: 'The original could not be downloaded.' };
  }
  if (!response.ok) return failure(response);
  const filename = filenameFromDisposition(response.headers.get('content-disposition'));
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  return { ok: true, filename };
}
