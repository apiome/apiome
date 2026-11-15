/**
 * The merge request components' one way to call their BFF routes — COL-4.3 (#4527).
 *
 * Every route answers an envelope: `{success: true, …}` or `{success: false, error, code?, detail?}`.
 * {@link callMergeRequestApi} sends the request, parses the envelope (a non-JSON body becomes a
 * failure naming the status), and returns it, so a component only branches on `success`.
 */

/** A BFF envelope. */
export type MergeRequestEnvelope<T> = Partial<T> & {
  success?: boolean;
  error?: string;
  code?: string;
  detail?: Record<string, unknown>;
};

/**
 * Call a merge request BFF route.
 *
 * @param url - The route.
 * @param body - A JSON body; sends a POST when given, a GET otherwise.
 * @returns The parsed envelope.
 */
export async function callMergeRequestApi<T>(url: string, body?: unknown): Promise<MergeRequestEnvelope<T>> {
  try {
    const response = await fetch(
      url,
      body === undefined
        ? undefined
        : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    );
    try {
      return (await response.json()) as MergeRequestEnvelope<T>;
    } catch {
      return { success: false, error: `The server answered ${response.status}.` } as MergeRequestEnvelope<T>;
    }
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'The request did not reach the server.',
    } as MergeRequestEnvelope<T>;
  }
}
