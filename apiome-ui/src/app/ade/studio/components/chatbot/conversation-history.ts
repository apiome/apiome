/**
 * Multi-turn conversation history helpers for the Studio AI chatbot (#260).
 *
 * The chat surface always passes the full transcript into the responder, but
 * a deterministic responder needs more than the raw array — it needs to know
 * whether the user is starting a new thread, asking a follow-up question,
 * or refining a previously generated schema. This module owns that
 * vocabulary so the demo responder (and the eventual Ollama transport in
 * #265) can speak about prior turns consistently.
 *
 * Three things live here:
 *
 *   1. {@link summarizeConversationHistory} parses the transcript + the just-
 *      sent prompt and returns a {@link ChatHistorySummary} containing the
 *      detected intent, the most recent assistant OpenAPI spec, any
 *      refinement operations the user requested, and short excerpts useful
 *      for prompt injection.
 *   2. {@link applyRefinementsToSpec} mutates a deep clone of an OpenAPI
 *      spec to add / remove / require / rename properties on its first
 *      schema — the operation set the demo responder advertises today.
 *   3. {@link buildConversationHistoryPreamble} renders a compact summary
 *      that backends can prepend to prompts so models see the same picture
 *      the UI does.
 *
 * Caps are exported as named constants so tests pin the contract.
 */

import { detectOpenApiSpecs, type DetectedOpenApiSpec } from './openapi-detection';
import { inferPropertyShapeFromName } from './property-name-schema-inference';
import type { ChatMessage } from './types';

/** Number of trailing turns kept in the prompt-injection excerpt list. */
export const CHAT_HISTORY_TURN_CAP = 8;
/** Per-excerpt character budget — keeps the preamble small. */
export const CHAT_HISTORY_EXCERPT_CHAR_CAP = 280;

export type ChatFollowUpIntent =
  /** No prior assistant turn exists yet. */
  | 'first-turn'
  /** Prior turns exist but this prompt doesn't reference them. */
  | 'standalone'
  /** User wants to modify the previously generated spec. */
  | 'refine-spec'
  /** User asked to make the spec/answer "more like X". */
  | 'comparison'
  /** User is asking a question about the previous reply. */
  | 'clarification'
  /** Open-ended re-roll ("actually", "instead", "try again"). */
  | 'iteration';

export type ChatRefinementOp =
  | { kind: 'add-property'; name: string; type?: string }
  | { kind: 'remove-property'; name: string }
  | { kind: 'require-property'; name: string }
  | { kind: 'rename-property'; from: string; to: string };

export interface ChatHistoryExcerpt {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatHistorySummary {
  /** Number of user turns INCLUDING the just-sent prompt. */
  userTurnCount: number;
  /** Number of completed (non-pending) assistant turns BEFORE this one. */
  assistantTurnCount: number;
  intent: ChatFollowUpIntent;
  /** Most recent importable assistant OpenAPI spec, if any. */
  lastAssistantSpec: DetectedOpenApiSpec | null;
  /** When intent === 'comparison', the subject the user referenced. */
  comparisonSubject: string | null;
  /** Refinement operations parsed out of the prompt, in source order. */
  refinementOps: ChatRefinementOp[];
  /** Trimmed conversation excerpts (most recent last) for prompt injection. */
  recentExcerpts: ChatHistoryExcerpt[];
}

const REFINE_WORDS = [
  'refine', 'tweak', 'update', 'change', 'modify', 'adjust',
  'extend', 'iterate', 'improve', 'rework',
];
const ITERATION_WORDS = [
  'actually', 'instead', 'wait', 'try again', 'another version',
  'do it again', 'redo',
];
const CLARIFICATION_LEADERS = [
  'what', 'why', 'how', 'when', 'where', 'who',
  'can you explain', 'could you explain', 'tell me more',
  'what does', 'what is', 'what are', 'what do you mean',
];

/**
 * Build a {@link ChatHistorySummary} from the full transcript plus the new
 * prompt text.
 *
 * `messages` is the transcript INCLUDING the user's just-sent message, which
 * is typically the final entry in the array when the chat shell invokes the
 * responder.
 */
export function summarizeConversationHistory(
  messages: ChatMessage[],
  prompt: string,
): ChatHistorySummary {
  const trimmedPrompt = prompt.trim();
  const lower = trimmedPrompt.toLowerCase();
  const lastMessage = messages[messages.length - 1];
  const priorMessages =
    lastMessage &&
    lastMessage.role === 'user' &&
    lastMessage.content.trim() === trimmedPrompt
      ? messages.slice(0, -1)
      : messages;

  const userTurns = messages.filter((m) => m.role === 'user').length;
  const assistantTurns = priorMessages.filter(
    (m) => m.role === 'assistant' && !m.pending && m.content.trim().length > 0,
  ).length;

  const lastAssistantSpec = findLastAssistantSpec(priorMessages);
  const comparisonSubject = detectComparisonSubject(lower, trimmedPrompt);
  const refinementOps = extractRefinementOps(trimmedPrompt);

  const intent = detectIntent({
    assistantTurns,
    lower,
    hasSpec: lastAssistantSpec !== null,
    refinementOps,
    comparisonSubject,
  });

  const recentExcerpts = buildRecentExcerpts(priorMessages);

  return {
    userTurnCount: userTurns,
    assistantTurnCount: assistantTurns,
    intent,
    lastAssistantSpec,
    comparisonSubject,
    refinementOps,
    recentExcerpts,
  };
}

interface DetectIntentInput {
  assistantTurns: number;
  lower: string;
  hasSpec: boolean;
  refinementOps: ChatRefinementOp[];
  comparisonSubject: string | null;
}

function detectIntent({
  assistantTurns,
  lower,
  hasSpec,
  refinementOps,
  comparisonSubject,
}: DetectIntentInput): ChatFollowUpIntent {
  if (assistantTurns === 0) return 'first-turn';

  if (comparisonSubject) return 'comparison';

  if (hasSpec && (refinementOps.length > 0 || matchesAny(lower, REFINE_WORDS))) {
    return 'refine-spec';
  }

  if (matchesAny(lower, ITERATION_WORDS)) return 'iteration';

  if (looksLikeClarification(lower)) return 'clarification';

  return 'standalone';
}

function looksLikeClarification(lower: string): boolean {
  if (!lower.endsWith('?')) {
    // Allow leading question phrases even without the trailing punctuation.
    const startsWithLeader = CLARIFICATION_LEADERS.some((leader) =>
      lower === leader || lower.startsWith(`${leader} `),
    );
    if (!startsWithLeader) return false;
  }
  return CLARIFICATION_LEADERS.some((leader) =>
    lower === leader || lower.startsWith(`${leader} `) || lower.startsWith(`${leader}'s `),
  );
}

function matchesAny(haystack: string, needles: readonly string[]): boolean {
  return needles.some((needle) => haystack.includes(needle));
}

const COMPARISON_PATTERN =
  /\b(?:more like|similar to|like the|like a|like an)\s+([a-z0-9][a-z0-9 _-]{0,40}?)(?=[.!?,;]|$)/i;

function detectComparisonSubject(lower: string, original: string): string | null {
  const match = lower.match(COMPARISON_PATTERN);
  if (!match) return null;
  // Recover the original casing for the captured subject.
  const start = match.index! + match[0].length - match[1].length;
  const subject = original.slice(start, start + match[1].length).trim();
  return subject.length > 0 ? subject : null;
}

const IDENTIFIER = '[A-Za-z_][A-Za-z0-9_]*';

const REFINE_PATTERNS: ReadonlyArray<{
  regex: RegExp;
  build: (m: RegExpMatchArray) => ChatRefinementOp | null;
}> = [
  {
    regex: new RegExp(
      `\\b(?:rename|change)\\s+(?:property\\s+|field\\s+)?(${IDENTIFIER})\\s+to\\s+(${IDENTIFIER})`,
      'gi',
    ),
    build: (m) => ({ kind: 'rename-property', from: m[1], to: m[2] }),
  },
  {
    regex: new RegExp(
      `\\b(?:remove|drop|delete)\\s+(?:the\\s+)?(?:property\\s+|field\\s+)?(${IDENTIFIER})(?:\\s+(?:property|field))?`,
      'gi',
    ),
    build: (m) => ({ kind: 'remove-property', name: m[1] }),
  },
  {
    regex: new RegExp(
      `\\b(?:make|mark)\\s+(${IDENTIFIER})\\s+required\\b`,
      'gi',
    ),
    build: (m) => ({ kind: 'require-property', name: m[1] }),
  },
  {
    regex: new RegExp(
      `\\brequire\\s+(?:the\\s+)?(?:property\\s+|field\\s+)?(${IDENTIFIER})(?:\\s+(?:property|field))?`,
      'gi',
    ),
    build: (m) => ({ kind: 'require-property', name: m[1] }),
  },
  {
    regex: new RegExp(
      `\\b(?:add|include)\\s+(?:an?\\s+|the\\s+)?(${IDENTIFIER})\\s+(?:property|field)(?:\\s+(?:as|of\\s+type)\\s+(${IDENTIFIER}))?`,
      'gi',
    ),
    build: (m) => ({ kind: 'add-property', name: m[1], type: m[2]?.toLowerCase() }),
  },
  {
    regex: new RegExp(
      `\\b(?:add|include)\\s+(?:an?\\s+|the\\s+)?(${IDENTIFIER})\\s+(${IDENTIFIER})(?:\\s+(?:property|field))?`,
      'gi',
    ),
    build: (m) => {
      // Patterns like "add a phone string" / "add timestamp string"
      const possibleType = m[2].toLowerCase();
      if (!isJsonSchemaType(possibleType)) return null;
      return { kind: 'add-property', name: m[1], type: possibleType };
    },
  },
];

const JSON_SCHEMA_TYPES = new Set([
  'string', 'integer', 'number', 'boolean', 'object', 'array', 'null',
]);

function isJsonSchemaType(value: string): boolean {
  return JSON_SCHEMA_TYPES.has(value);
}

function extractRefinementOps(prompt: string): ChatRefinementOp[] {
  const indexed: Array<{ index: number; op: ChatRefinementOp }> = [];
  const seen = new Set<string>();
  for (const { regex, build } of REFINE_PATTERNS) {
    regex.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = regex.exec(prompt)) !== null) {
      const op = build(match);
      if (!op) continue;
      const key = opKey(op);
      if (seen.has(key)) continue;
      seen.add(key);
      indexed.push({ index: match.index, op });
    }
  }
  indexed.sort((a, b) => a.index - b.index);
  return indexed.map(({ op }) => op);
}

function opKey(op: ChatRefinementOp): string {
  switch (op.kind) {
    case 'rename-property':
      return `${op.kind}:${op.from.toLowerCase()}->${op.to.toLowerCase()}`;
    default:
      return `${op.kind}:${op.name.toLowerCase()}`;
  }
}

function findLastAssistantSpec(priorMessages: ChatMessage[]): DetectedOpenApiSpec | null {
  for (let i = priorMessages.length - 1; i >= 0; i -= 1) {
    const m = priorMessages[i];
    if (m.role !== 'assistant' || m.pending) continue;
    const specs = detectOpenApiSpecs(m.content);
    if (specs.length > 0) return specs[specs.length - 1];
  }
  return null;
}

function buildRecentExcerpts(priorMessages: ChatMessage[]): ChatHistoryExcerpt[] {
  const usable = priorMessages.filter(
    (m) => !m.pending && m.content.trim().length > 0,
  );
  const slice = usable.slice(-CHAT_HISTORY_TURN_CAP);
  return slice.map((m) => ({
    role: m.role,
    content: trimExcerpt(m.content),
  }));
}

function trimExcerpt(content: string): string {
  // Strip fenced code blocks so excerpts stay readable in a single line.
  const stripped = content.replace(/```[\s\S]*?```/g, '[code block omitted]');
  const compact = stripped.replace(/\s+/g, ' ').trim();
  if (compact.length <= CHAT_HISTORY_EXCERPT_CHAR_CAP) return compact;
  return `${compact.slice(0, CHAT_HISTORY_EXCERPT_CHAR_CAP - 1).trimEnd()}…`;
}

/**
 * Compact preamble describing the conversation so far. Returns an empty
 * string when there is nothing useful to inject (e.g. first turn).
 */
export function buildConversationHistoryPreamble(summary: ChatHistorySummary): string {
  if (summary.assistantTurnCount === 0 && summary.recentExcerpts.length === 0) {
    return '';
  }

  const lines: string[] = ['### Conversation so far'];
  lines.push(
    `- Turn ${summary.userTurnCount} of an ongoing thread (${summary.assistantTurnCount} prior assistant ${
      summary.assistantTurnCount === 1 ? 'reply' : 'replies'
    }).`,
  );

  switch (summary.intent) {
    case 'refine-spec':
      lines.push('- Treat this turn as a refinement of the last generated schema.');
      break;
    case 'comparison':
      if (summary.comparisonSubject) {
        lines.push(`- The user wants the answer to look more like: ${summary.comparisonSubject}.`);
      }
      break;
    case 'clarification':
      lines.push('- The user is asking a clarifying question about the previous reply.');
      break;
    case 'iteration':
      lines.push('- The user wants a different take on the previous reply.');
      break;
    default:
      break;
  }

  if (summary.recentExcerpts.length > 0) {
    lines.push('');
    lines.push('#### Recent turns');
    for (const excerpt of summary.recentExcerpts) {
      lines.push(`- **${excerpt.role}:** ${excerpt.content}`);
    }
  }

  if (summary.refinementOps.length > 0) {
    lines.push('');
    lines.push('#### Detected schema edits');
    for (const op of summary.refinementOps) {
      lines.push(`- ${describeOp(op)}`);
    }
  }

  return lines.join('\n');
}

function describeOp(op: ChatRefinementOp): string {
  switch (op.kind) {
    case 'add-property':
      return op.type
        ? `Add property \`${op.name}\` of type \`${op.type}\`.`
        : `Add property \`${op.name}\`.`;
    case 'remove-property':
      return `Remove property \`${op.name}\`.`;
    case 'require-property':
      return `Mark property \`${op.name}\` as required.`;
    case 'rename-property':
      return `Rename property \`${op.from}\` to \`${op.to}\`.`;
  }
}

interface SchemaShape {
  type?: string;
  description?: string;
  properties?: Record<string, Record<string, unknown>>;
  required?: string[];
  [key: string]: unknown;
}

/**
 * Apply a sequence of refinement ops to the FIRST schema declared under
 * `components.schemas` in `spec`. Returns a deep clone — never mutates the
 * caller's object. If the spec has no schemas, the clone is returned
 * untouched.
 */
export function applyRefinementsToSpec(
  spec: Record<string, unknown>,
  ops: ChatRefinementOp[],
): Record<string, unknown> {
  const clone = deepClone(spec);
  if (ops.length === 0) return clone;
  const schema = getFirstSchema(clone);
  if (!schema) return clone;
  schema.properties = schema.properties ?? {};
  schema.required = Array.isArray(schema.required) ? [...schema.required] : [];

  for (const op of ops) {
    applyOpToSchema(schema, op);
  }
  pruneRequired(schema);
  return clone;
}

function applyOpToSchema(schema: SchemaShape, op: ChatRefinementOp): void {
  const props = schema.properties!;
  switch (op.kind) {
    case 'add-property': {
      if (props[op.name]) {
        if (op.type) {
          // Explicit type provided — replace the entire shape to avoid stale
          // constraints (format, minimum, etc.) left over from previous inference.
          props[op.name] = {
            type: op.type,
            ...(props[op.name].description ? { description: props[op.name].description } : {}),
          };
        }
      } else if (op.type) {
        props[op.name] = {
          type: op.type,
          description: `Added in follow-up: ${op.name}.`,
        };
      } else {
        const inferred = inferPropertyShapeFromName(op.name);
        props[op.name] = {
          type: 'string',
          ...inferred.schema,
          description: `Added in follow-up: ${op.name}.`,
        };
        if (inferred.suggestRequired && !schema.required!.includes(op.name)) {
          schema.required!.push(op.name);
        }
      }
      return;
    }
    case 'remove-property': {
      delete props[op.name];
      schema.required = schema.required!.filter((n) => n !== op.name);
      return;
    }
    case 'require-property': {
      if (!props[op.name]) {
        const inferred = inferPropertyShapeFromName(op.name);
        props[op.name] = {
          type: 'string',
          ...inferred.schema,
          description: `Added (required) in follow-up: ${op.name}.`,
        };
      }
      if (!schema.required!.includes(op.name)) schema.required!.push(op.name);
      return;
    }
    case 'rename-property': {
      const existing = props[op.from];
      if (!existing) return;
      delete props[op.from];
      props[op.to] = existing;
      schema.required = schema.required!.map((n) => (n === op.from ? op.to : n));
      return;
    }
  }
}

function pruneRequired(schema: SchemaShape): void {
  if (!schema.required) return;
  const propNames = new Set(Object.keys(schema.properties ?? {}));
  schema.required = schema.required.filter((n) => propNames.has(n));
  if (schema.required.length === 0) delete schema.required;
}

function getFirstSchema(spec: Record<string, unknown>): SchemaShape | null {
  const components = spec.components as Record<string, unknown> | undefined;
  const schemas = components?.schemas as Record<string, SchemaShape> | undefined;
  if (!schemas) return null;
  const names = Object.keys(schemas);
  if (names.length === 0) return null;
  return schemas[names[0]];
}

function deepClone<T>(value: T): T {
  if (typeof structuredClone === 'function') {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value)) as T;
}
