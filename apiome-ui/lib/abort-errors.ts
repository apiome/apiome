/**
 * Shared abort-error detection for streaming AI requests.
 */

export function isAbortError(error: unknown, signal?: AbortSignal): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (typeof error === 'object' &&
      error !== null &&
      (error as { name?: string }).name === 'AbortError') ||
    (signal?.aborted ?? false)
  );
}
