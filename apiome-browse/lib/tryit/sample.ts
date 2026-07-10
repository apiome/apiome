/**
 * Client helper for `POST /api/try-it/sample` — SIM-3.4 (#4450).
 */

export class SampleSynthesisError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = 'SampleSynthesisError';
  }
}

/** Request a schema-valid synthesized body from the browse sample endpoint. */
export async function fetchGeneratedBodySample(input: {
  schema: Record<string, unknown>;
  spec: unknown;
  seed: number;
  field?: string;
}): Promise<{ value: unknown; seed: number }> {
  const response = await fetch('/api/try-it/sample', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      schema: input.schema,
      spec: input.spec,
      seed: input.seed,
      field: input.field ?? 'requestBody',
    }),
  });
  const payload = (await response.json().catch(() => null)) as
    | { value?: unknown; seed?: number; detail?: string }
    | null;
  if (!response.ok) {
    throw new SampleSynthesisError(payload?.detail ?? 'Sample synthesis failed.', response.status);
  }
  return { value: payload?.value, seed: payload?.seed ?? input.seed };
}
