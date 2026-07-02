/**
 * Shared abort-error detection for the Studio chatbot stack.
 *
 * Both the UI shell (ChatConversation) and the Ollama responder need to
 * distinguish AbortError from genuine failures so they can suppress noise
 * and surface partial streamed text instead of an error message.
 *
 * The optional `signal` parameter allows callers to also treat an already-aborted
 * signal as an abort, even when the error itself may not carry the AbortError name
 * (e.g. a Node.js fetch cancelled via `request.signal`).
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
