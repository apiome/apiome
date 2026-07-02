/**
 * Detection helpers for OpenAPI specs embedded inside ```json fenced code
 * blocks (#258). The chatbot uses these to decide whether to offer a
 * "Import this spec" affordance on an assistant message.
 *
 * Heuristics intentionally stay loose: the chat surface only needs to know
 * *probable* specs so it can show the import button — the importer downstream
 * does the real validation.
 */

export interface DetectedOpenApiSpec {
  /** Raw JSON text inside the fence (no fence markers). */
  raw: string;
  /** Parsed spec — guaranteed to be a non-null object. */
  spec: Record<string, unknown>;
  /** OpenAPI 3.x version string when present (e.g. "3.1.0"). */
  version?: string;
  /** True when the legacy `swagger` 2.0 key was used instead of `openapi`. */
  swagger?: boolean;
}

const JSON_FENCE_PATTERN = /```json\s*\n([\s\S]*?)\n```/gi;

/**
 * Return every `\`\`\`json` block in `markdown` that parses as JSON and looks
 * like an OpenAPI spec. Order matches the order the blocks appear in the
 * markdown so callers can correlate with on-screen position.
 */
export function detectOpenApiSpecs(markdown: string): DetectedOpenApiSpec[] {
  if (!markdown) return [];

  const found: DetectedOpenApiSpec[] = [];
  // The regex is stateful across exec calls; reset before each scan.
  JSON_FENCE_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = JSON_FENCE_PATTERN.exec(markdown)) !== null) {
    const raw = match[1].trim();
    if (!raw) continue;

    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      continue;
    }

    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) continue;
    const spec = parsed as Record<string, unknown>;

    const version =
      typeof spec.openapi === 'string' && /^3\./.test(spec.openapi as string)
        ? (spec.openapi as string)
        : undefined;
    const swagger = typeof spec.swagger === 'string' && /^2\./.test(spec.swagger as string);

    const looksLikeSpec =
      Boolean(version) ||
      swagger ||
      // Structural fallback: an `info` block with either `paths` or `components`
      // is overwhelmingly an OpenAPI document even without the version key.
      (isObject(spec.info) && (isObject(spec.paths) || isObject(spec.components)));

    if (!looksLikeSpec) continue;

    found.push({ raw, spec, version, swagger: swagger || undefined });
  }

  return found;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Convenience for callers that only care whether a message has at least one
 * importable spec — e.g. to decide if the import button should render.
 */
export function hasOpenApiSpec(markdown: string): boolean {
  return detectOpenApiSpecs(markdown).length > 0;
}
