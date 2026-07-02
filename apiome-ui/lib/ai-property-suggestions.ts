/**
 * Parse structured AI responses for reusable property suggestions (#609) and
 * property_type_suggestions (alternative schemas for one name, #269).
 * Expects a single ```json ... ``` markdown block from those Ollama tasks.
 */

export type AiPropertySuggestion = {
  name: string;
  description?: string;
  schema: Record<string, unknown>;
  /** Optional user-facing rationale (parsed from `explanation` or `rationale` in JSON). */
  explanation?: string;
  thinking?: string;
  summary?: string;
};

export type AiPropertySuggestionsPayload = {
  thinking: string;
  summary: string;
  suggestions: AiPropertySuggestion[];
};

function extractLastJsonCodeBlock(text: string): string | null {
  const re = /```(?:json)?\s*([\s\S]*?)```/gi;
  let last: string | null = null;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    last = m[1].trim();
  }
  return last;
}

function isNonEmptyString(v: unknown): v is string {
  return typeof v === 'string' && v.trim().length > 0;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

export type ParseAiPropertySuggestionsOptions = {
  /** When set, every suggestion uses this name (fixes model drift for type-only tasks). */
  canonicalPropertyName?: string;
};

/** Text shown next to each suggestion in the Studio list (dedicated explanation, then model rationale, then description). */
export function suggestionPublicExplanation(s: AiPropertySuggestion): string | undefined {
  const e = s.explanation?.trim();
  if (e) return e;
  const t = s.thinking?.trim();
  if (t) return t;
  const d = s.description?.trim();
  if (d) return d;
  return undefined;
}

/**
 * Returns null if the response does not contain valid structured suggestions.
 */
export function parseAiPropertySuggestionsResponse(
  markdown: string,
  options?: ParseAiPropertySuggestionsOptions,
): AiPropertySuggestionsPayload | null {
  const raw = extractLastJsonCodeBlock(markdown.trim());
  if (!raw) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }

  if (!isPlainObject(parsed)) return null;

  const thinking = isNonEmptyString(parsed.thinking) ? parsed.thinking.trim() : '';
  const summary = isNonEmptyString(parsed.summary) ? parsed.summary.trim() : '';
  const suggestionsRaw = parsed.suggestions;

  if (!Array.isArray(suggestionsRaw) || suggestionsRaw.length === 0) return null;

  const suggestions: AiPropertySuggestion[] = [];

  const canonical = options?.canonicalPropertyName?.trim() || '';

  for (const item of suggestionsRaw) {
    if (!isPlainObject(item)) continue;
    let name = typeof item.name === 'string' ? item.name.trim() : '';
    if (canonical) {
      name = canonical;
    } else if (!name) {
      continue;
    }
    const schema = item.schema;
    if (!isPlainObject(schema)) continue;

    const description =
      typeof item.description === 'string' && item.description.trim()
        ? item.description.trim()
        : undefined;
    const expl =
      typeof item.explanation === 'string' && item.explanation.trim()
        ? item.explanation.trim()
        : typeof item.rationale === 'string' && item.rationale.trim()
          ? item.rationale.trim()
          : undefined;
    const st =
      typeof item.thinking === 'string' && item.thinking.trim() ? item.thinking.trim() : undefined;
    const su =
      typeof item.summary === 'string' && item.summary.trim() ? item.summary.trim() : undefined;

    suggestions.push({
      name,
      description,
      schema,
      ...(expl ? { explanation: expl } : {}),
      thinking: st,
      summary: su,
    });
  }

  if (suggestions.length === 0) return null;

  return {
    thinking,
    summary,
    suggestions,
  };
}
