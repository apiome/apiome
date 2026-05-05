/**
 * Quick-action phrase detection for Studio AI chat (#518).
 *
 * When an assistant message contains specific CTAs (plain or wrapped in
 * markdown bold), the chat shell surfaces matching buttons. Copy uses the
 * first non-empty ```json```/```jsonc``` fence anywhere in the message (even if a
 * ```yaml```/```yml``` fence appears earlier), falling back to the first non-empty
 * ```yaml```/```yml``` fence when no JSON/JSONC fence exists.
 */

export type StudioChatWorkspaceActionKind = 'create_class' | 'batch_add_properties' | 'apply_current_class';

export interface StudioChatWorkspaceAction {
  kind: StudioChatWorkspaceActionKind;
  /**
   * Raw assistant markdown from chat after the user confirms **Create this class**
   * in the preview dialog (#528). The layout opens Add Class in AI mode with this
   * message seeded so the user can review and create.
   */
  assistantMarkdown?: string;
}

/** Parsed `{ name, description, schema }` from a ```json``` block in assistant output. */
export interface ParsedAiClassDefinition {
  name: string;
  description: string | null;
  schema: unknown;
}

/** One row for UI previews: property name and a short suggested JSON Schema type label (#530). */
export interface SchemaPropertySummaryRow {
  name: string;
  suggestedType: string;
}

function propertiesRecordFromSchema(schema: unknown): Record<string, unknown> | null {
  if (!schema || typeof schema !== 'object' || Array.isArray(schema)) return null;
  const raw = (schema as { properties?: unknown }).properties;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  return raw as Record<string, unknown>;
}

function formatSuggestedJsonSchemaType(sub: unknown): string {
  if (!sub || typeof sub !== 'object' || Array.isArray(sub)) return 'object';
  const o = sub as Record<string, unknown>;

  if (typeof o.$ref === 'string') {
    const ref = o.$ref;
    const leaf = ref.split('/').pop();
    return leaf ? `ref (${leaf})` : ref;
  }

  const t = o.type;
  if (typeof t === 'string') {
    if (t === 'array') {
      if (o.items === undefined) return 'array';
      const inner = formatSuggestedJsonSchemaType(o.items);
      return inner === 'array' ? 'array' : `array<${inner}>`;
    }
    return t;
  }

  if (Array.isArray(t)) {
    return t.filter((x): x is string => typeof x === 'string').join(' | ') || 'mixed';
  }

  if (Array.isArray(o.oneOf)) return `oneOf(${o.oneOf.length})`;
  if (Array.isArray(o.anyOf)) return `anyOf(${o.anyOf.length})`;
  if (Array.isArray(o.allOf)) return `allOf(${o.allOf.length})`;
  if (o.enum !== undefined) return 'enum';
  if ('const' in o) return 'const';

  return 'object';
}

/**
 * Lists `schema.properties` keys with short type labels for preview UI (#530).
 */
export function summarizeJsonSchemaProperties(schema: unknown): SchemaPropertySummaryRow[] {
  const props = propertiesRecordFromSchema(schema);
  if (!props) return [];
  return Object.entries(props).map(([name, sub]) => ({
    name,
    suggestedType: formatSuggestedJsonSchemaType(sub),
  }));
}

export type DetectedChatQuickAction =
  | { kind: 'create_class' }
  | { kind: 'batch_add_properties' }
  | { kind: 'apply_current_class' }
  | { kind: 'copy_generated_payload'; payload: string };

const FENCE_RE = /```([a-zA-Z0-9_-]+)\s*\n([\s\S]*?)```/g;

function phrasePresent(markdown: string, phrase: string): boolean {
  return markdown.toLowerCase().includes(phrase.toLowerCase());
}

/**
 * First non-empty ```json``` / ```jsonc``` body, else first ```yaml``` / ```yml```.
 */
export function extractFirstJsonOrYamlFenceBody(markdown: string): string | null {
  if (!markdown) return null;
  FENCE_RE.lastIndex = 0;
  let firstJson: string | null = null;
  let firstYaml: string | null = null;
  let m: RegExpExecArray | null;
  while ((m = FENCE_RE.exec(markdown)) !== null) {
    const lang = m[1].toLowerCase();
    const body = m[2].trim();
    if (!body) continue;
    if ((lang === 'json' || lang === 'jsonc') && firstJson === null) {
      firstJson = body;
    }
    if ((lang === 'yaml' || lang === 'yml') && firstYaml === null) {
      firstYaml = body;
    }
  }
  return firstJson ?? firstYaml ?? null;
}

/**
 * Extracts the class skeleton JSON from assistant markdown (same shape as the
 * Create Class with AI flow in ClassEditDialog).
 *
 * Uses {@link extractFirstJsonOrYamlFenceBody} so that both ```json and
 * ```jsonc fences are accepted and a trailing newline before the closing
 * fence is not required.
 */
export function parseClassDefinitionFromAssistantMarkdown(content: string): ParsedAiClassDefinition | null {
  if (!content) return null;
  const body = extractFirstJsonOrYamlFenceBody(content);
  if (!body) return null;
  try {
    const parsed = JSON.parse(body) as Record<string, unknown>;
    if (!parsed || typeof parsed.name !== 'string' || !parsed.schema) return null;
    const name = parsed.name.replace(/[^A-Za-z0-9_]/g, '') || '';
    if (!name) return null;
    return {
      name,
      description: typeof parsed.description === 'string' ? parsed.description : null,
      schema: parsed.schema,
    };
  } catch {
    return null;
  }
}

/**
 * Returns quick actions in stable UI order. Kinds are unique; `copy_generated_payload`
 * is only included when the phrase appears and a JSON/YAML fence exists.
 */
export function detectChatQuickActions(markdown: string): DetectedChatQuickAction[] {
  if (!markdown) return [];
  const out: DetectedChatQuickAction[] = [];
  const seen = new Set<DetectedChatQuickAction['kind']>();

  const push = (action: DetectedChatQuickAction) => {
    if (seen.has(action.kind)) return;
    seen.add(action.kind);
    out.push(action);
  };

  if (phrasePresent(markdown, 'create this class')) {
    push({ kind: 'create_class' });
  }
  if (phrasePresent(markdown, 'add these properties')) {
    push({ kind: 'batch_add_properties' });
  }
  if (phrasePresent(markdown, 'apply to current class')) {
    push({ kind: 'apply_current_class' });
  }
  if (phrasePresent(markdown, 'copy to clipboard')) {
    const payload = extractFirstJsonOrYamlFenceBody(markdown);
    if (payload) {
      push({ kind: 'copy_generated_payload', payload });
    }
  }

  return out;
}
