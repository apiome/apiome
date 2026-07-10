/**
 * `POST /api/try-it/sample` — schema-driven request-body synthesis — SIM-3.4 (#4450).
 *
 * REST exposure of the SIM-1.3 synthesis engine for the Try It panel. The browser posts the
 * operation's request schema (plus the spec root for `$ref` resolution) and receives a
 * schema-valid sample body. Repeated calls with different seeds produce different samples.
 */

import { generateExample, parseMockSeed } from '../../../../../lib/tryit/synthesis';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const MAX_BODY_BYTES = 256 * 1024;

function problem(status: number, detail: string): Response {
  return Response.json({ detail }, { status });
}

export async function POST(request: Request): Promise<Response> {
  const contentLength = Number(request.headers.get('content-length') ?? '0');
  if (Number.isFinite(contentLength) && contentLength > MAX_BODY_BYTES) {
    return problem(413, 'The synthesis request is too large.');
  }

  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return problem(400, 'The synthesis request body is not valid JSON.');
  }

  if (raw == null || typeof raw !== 'object' || Array.isArray(raw)) {
    return problem(400, 'The synthesis request must be a JSON object.');
  }
  const body = raw as { schema?: unknown; spec?: unknown; seed?: unknown; field?: unknown };
  if (body.schema == null || typeof body.schema !== 'object') {
    return problem(400, 'A request `schema` object is required.');
  }

  const seed = parseMockSeed(
    typeof body.seed === 'number' || typeof body.seed === 'string' ? body.seed : null
  );
  const field = typeof body.field === 'string' && body.field.trim() !== '' ? body.field : 'root';
  const specRoot = body.spec ?? body.schema;

  try {
    const value = generateExample(body.schema, specRoot, { seed, field });
    return Response.json({ value, seed });
  } catch (err) {
    console.error('[try-it/sample] synthesis error:', err instanceof Error ? err.message : String(err));
    return problem(500, 'Request-body synthesis failed.');
  }
}
