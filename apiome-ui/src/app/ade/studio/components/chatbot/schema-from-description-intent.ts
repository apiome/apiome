/**
 * Detect Studio chat prompts that ask for schema output from a plain-language
 * description (#267), without requiring words like "OpenAPI" or "spec".
 */

const SPEC_HINT_NEEDLES = ['openapi', 'spec', 'schema', 'api'] as const;

const DESCRIPTION_INTENT_PATTERNS: ReadonlyArray<RegExp> = [
  /\b(create|build|design|sketch|model|define|map out)\s+(a|an|the|my|our)\b/i,
  /\b(i|we)\s+(need|want)\s+(a|an|the|my|our|to\s+model|to\s+design|to\s+build)\b/i,
  /\b(class|classes|entity|entities)\s+(with|for|named|called|that|having)\b/i,
  /\b(data|domain|object)\s+model\b/i,
  /\b(user\s+stor(y|ies)|requirements(\s+document)?|requirements?\s+for)\b/i,
  /\bpaste(d)?\s+(the\s+)?requirements\b/i,
];

// Words that must NOT appear as the first "entity" after "I need/want" to avoid
// matching support phrases like "I need help and advice".
const ENTITY_LIST_EXCLUSIONS =
  /help|assistance|support|info|information|advice|guidance|clarification|you|someone|anything|something|more|some|just/;

// Matches "I need users, roles, and permissions" or "We want posts and comments":
// subject ("I"/"we") + verb ("need"/"want") + first entity (not a support/meta word)
// + at least one more entity connected by comma or "and".
const ENTITY_LIST_PATTERNS: ReadonlyArray<RegExp> = [
  new RegExp(
    `\\b(i|we)\\s+(need|want)\\s+(?!(${ENTITY_LIST_EXCLUSIONS.source})\\b)\\w+(?:\\s*,\\s*\\w+|\\s+and\\s+\\w+)`,
    'i',
  ),
];

const SMALL_TALK_PREFIX =
  /^(hi|hello|hey|thanks|thank you|ok|okay|bye|good morning|good afternoon)\b/i;

// Punctuation/whitespace that separates a greeting from the rest of the prompt.
const LEADING_PUNCTUATION = /^[\s,;!.]+/;

const MODELING_VOCAB =
  /\b(class|classes|entity|entities|schema|schemas|model|models|field|fields|property|properties|type|types|object|objects|record|records|table|tables|attribute|attributes)\b/i;

const MIN_CHARS = 16;
const MIN_CHARS_WITHOUT_MODELING_TERMS = 28;

/**
 * True when the user is likely asking for generated OpenAPI components/schemas
 * from a written description (possibly multi-sentence or pasted).
 */
export function userPromptRequestsSchemaFromDescription(prompt: string): boolean {
  const trimmed = prompt.trim();
  if (trimmed.length < MIN_CHARS) return false;

  const lower = trimmed.toLowerCase();
  if (SPEC_HINT_NEEDLES.some((n) => lower.includes(n))) return true;

  // Strip leading greeting/social phrase so "Hi, I need a blog platform…" is evaluated
  // on its meaningful tail rather than being rejected as small-talk.
  const content = SMALL_TALK_PREFIX.test(trimmed)
    ? trimmed.replace(SMALL_TALK_PREFIX, '').replace(LEADING_PUNCTUATION, '')
    : trimmed;

  // Pure greeting with no following domain content.
  if (content.length < MIN_CHARS) return false;

  // Entity-list patterns are specific enough to signal a schema request without
  // requiring explicit modeling vocabulary (e.g. "I need users, roles, and permissions").
  if (ENTITY_LIST_PATTERNS.some((re) => re.test(content))) return true;

  if (!DESCRIPTION_INTENT_PATTERNS.some((re) => re.test(content))) return false;

  if (content.length < MIN_CHARS_WITHOUT_MODELING_TERMS && !MODELING_VOCAB.test(content)) {
    return false;
  }

  return true;
}
