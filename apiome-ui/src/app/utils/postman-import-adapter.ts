/**
 * Postman Collection → OpenAPI through the REST import adapter (MFI-32.7, #4409).
 *
 * The **Postman Collection** import card used to convert in the browser
 * (`postman-to-openapi.ts`, now behind `FEATURE_LEGACY_POSTMAN_IMPORT`). It now sends the collection
 * to `POST /api/import/postman/openapi`, which runs the registered Postman import adapter — schemas
 * inferred from example bodies, credentials scrubbed — and returns OpenAPI 3.1 plus warnings.
 */

/** What a conversion returns: the OpenAPI document, or why there is none. */
export type PostmanAdapterResult =
  | { success: true; document: Record<string, unknown>; warnings: string[] }
  | { success: false; error: string; warnings: string[] };

/** The same-origin route the conversion is posted to. */
export const POSTMAN_TO_OPENAPI_ROUTE = '/api/import/postman/openapi';

/**
 * Convert a Postman collection to OpenAPI with the REST import adapter.
 *
 * @param json - The collection JSON text.
 * @param options.baseUrl - When given, the document's only server.
 * @param options.filename - The file name, used in the server's messages.
 * @param options.fetchImpl - The fetch to use (tests pass a stub).
 * @returns The OpenAPI document and warnings, or an error. Never throws.
 */
export async function convertPostmanWithAdapter(
  json: string,
  options: { baseUrl?: string; filename?: string; fetchImpl?: typeof fetch } = {}
): Promise<PostmanAdapterResult> {
  const doFetch = options.fetchImpl ?? fetch;
  let response: Response;
  try {
    response = await doFetch(POSTMAN_TO_OPENAPI_ROUTE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        document: json,
        ...(options.filename ? { filename: options.filename } : {}),
        ...(options.baseUrl ? { base_url: options.baseUrl } : {}),
      }),
    });
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? `Could not reach Apiome: ${error.message}` : 'Could not reach Apiome',
      warnings: [],
    };
  }
  const body = (await response.json().catch(() => null)) as
    | { success?: boolean; openapi?: unknown; warnings?: unknown; error?: unknown }
    | null;
  if (!response.ok || !body || body.success === false || !body.openapi || typeof body.openapi !== 'object') {
    const message = body && typeof body.error === 'string' && body.error ? body.error : `Conversion failed (${response.status})`;
    return { success: false, error: message, warnings: [] };
  }
  const warnings = Array.isArray(body.warnings) ? body.warnings.filter((w): w is string => typeof w === 'string') : [];
  return { success: true, document: body.openapi as Record<string, unknown>, warnings };
}
