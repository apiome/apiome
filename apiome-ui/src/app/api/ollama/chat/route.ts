/**
 * API route to chat with Ollama using Server-Sent Events (SSE)
 */

import { NextRequest } from 'next/server';
import { getEmbedding } from '@lib/embedding';
import { isAbortError } from '../../../ade/studio/components/chatbot/abort-errors';
import {
  findSemanticallySimilarCachedResponse,
  getCachedOllamaChatResponse,
  isOllamaQueryCacheDisabled,
  isOllamaSemanticCacheDisabled,
  ollamaChatCacheKey,
  ollamaChatMessagesFingerprint,
  ollamaChatSemanticContextKey,
  ollamaSemanticCacheThreshold,
  setCachedOllamaChatResponse,
} from './query-cache';
import { CLASS_NAMES_CAP } from '@lib/ai-schema-improvement-suggestions';

const OLLAMA_BASE_URL = process.env.OLLAMA_BASE_URL || 'http://localhost:11434';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function usageFromOllamaPayload(data: Record<string, unknown>): { promptTokens?: number; completionTokens?: number } | undefined {
  const p = data.prompt_eval_count;
  const c = data.eval_count;
  const usage: { promptTokens?: number; completionTokens?: number } = {};
  if (typeof p === 'number') usage.promptTokens = p;
  if (typeof c === 'number') usage.completionTokens = c;
  return Object.keys(usage).length > 0 ? usage : undefined;
}

function pickAssistantContent(data: Record<string, unknown>): string | undefined {
  const message = data.message;
  if (!message || typeof message !== 'object') return undefined;
  const raw = (message as { content?: unknown }).content;
  return typeof raw === 'string' && raw.length > 0 ? raw : undefined;
}

const CLASS_SKELETON_SYSTEM = `You are an expert at defining JSON Schema (OpenAPI 3.1) class/schema definitions. The user will describe a class they want to create.

# Output format

Optionally begin with markdown sections (in this order if you use both):

1. **Suggested properties**: a bullet list where each line is \`- propertyName — type\` using plain-language JSON Schema types (e.g. \`- email — string\`, \`- age — integer\`, \`- orders — array of Order (ref)\`). This gives the user a scannable summary before the full schema.

2. **Suggested relationships**: a bullet list describing associations between this class and others—cardinality, inverse navigations, or cross-cutting notes (e.g. \`- lineItems — one-to-many LineItem\`, \`- customer — many-to-one Customer\`, \`- consider inverse Customer.orders if you model both sides\`). Align with the \`$ref\` targets you use in the JSON below when applicable.

Then output exactly one JSON code block in this shape:
\`\`\`json
{
  "name": "ClassName",
  "description": "Optional short description of the class",
  "schema": {
    "type": "object",
    "properties": { ... },
    "required": [ ... ]
  }
}
\`\`\`

After that JSON block, add a markdown section titled exactly **Improvement suggestions** with 2–5 bullets: actionable schema/API notes for this class (e.g. \`allOf\` for shared bases, \`discriminator\` with \`oneOf\`, splitting large objects into referenced components, pagination or error-response considerations when list/query APIs are added later). Keep bullets specific to what you generated.

# Rules

- "name" must be PascalCase and contain only letters, numbers, and underscores (A-Za-z0-9_).
- "schema" must be a valid JSON Schema object. It must include "type": "object" and a "properties" object (can be empty {} for a placeholder).
- **Every property** under "schema.properties" must express its intended shape clearly:
  - Scalar or inline object: include a JSON Schema \`type\` (and \`format\` when useful, e.g. date-time, email).
  - Reference to another class: use \`"$ref": "#/components/schemas/ClassName"\` (no bare empty objects for named fields).
  - Arrays: always include \`"type": "array"\` and a typed \`items\` schema (primitive, inline object, or \`$ref\`).
  - Compositions (oneOf / anyOf / allOf): only when the user's request needs them; prefer simple typed properties otherwise.
- You may use any JSON Schema / OpenAPI 3.1 schema features in "schema": properties, required, allOf, anyOf, oneOf, discriminator, additionalProperties, unevaluatedProperties, patternProperties, dependentSchemas, dependentRequired, deprecated, deprecationMessage, minProperties, maxProperties, examples, xml, $id, $anchor, $comment, externalDocs, if/then/else, and x-* extensions.
- For $ref inside the schema, use format "#/components/schemas/ClassName" when referencing other classes.
- Property names in "properties" should be camelCase. Include "description" (and optionally "summary") on the schema and on properties where helpful.
- When the property name alone implies a shape, use the same defaults as Studio refinement inference: \`email\` → string \`format: "email"\` plus a sensible \`maxLength\`; \`password\` → \`minLength\`/\`maxLength\`; \`slug\`, \`sku\`, \`phone\`, postal codes, ISO country/currency codes → appropriate \`pattern\` (and lengths where fixed-width); \`percentage\` → number between 0 and 100; \`latitude\`/\`longitude\` → bounded numbers; \`age\` → integer with \`minimum\`/\`maximum\`; \`createdAt\`/\`updatedAt\` → \`format: "date-time"\`; \`price\` → number with \`minimum: 0\`; \`isActive\` → boolean; primary-key \`id\` → \`format: "uuid"\` and include it in \`required\`.
- Keep the class a clear skeleton: include the structure the user asked for, but you do not need to exhaust every option. Prefer properties and required; add allOf/anyOf/oneOf/discriminator/additionalProperties etc. only when they fit the user's description.
- Apart from the optional **Suggested properties** and **Suggested relationships** sections, the single JSON code block, and the required **Improvement suggestions** section, do not add other commentary.

# Iterative refinement

When the user's message includes a \`\`\`json block labeled as the **current** class definition (same shape as your output: name, optional description, schema) and asks you to change it, reply with a **complete merged** definition in the same output format. Preserve properties and constraints they did not ask to remove. Honor requests such as: add or remove fields, change which properties are required, add validations (minLength, maxLength, pattern, format, numeric bounds), add audit timestamps, or adjust descriptions.`;

function buildClassSkeletonSystem(options: {
  existingClassNames?: string[];
  existingProperties?: Array<{ name: string; description?: string | null; data?: Record<string, unknown> }>;
}): string {
  let extra = '';
  if (options.existingClassNames?.length) {
    extra += `\n\n# Existing classes in this version (reference with $ref: "#/components/schemas/ClassName")\n${options.existingClassNames.join(', ')}`;
  }
  if (options.existingProperties?.length) {
    extra += `\n\n# Existing project properties (reuse by using the exact "name" in your schema.properties; these are shared across classes)\n`;
    options.existingProperties.forEach((p) => {
      const d = p.data;
      const typeStr =
        typeof d?.type === 'string'
          ? d.type
          : d && '$ref' in d && d.$ref
            ? `$ref`
            : 'object';
      extra += `- ${p.name}: ${typeStr}${p.description ? ` — ${String(p.description).slice(0, 60)}` : ''}\n`;
    });
  }
  return CLASS_SKELETON_SYSTEM + extra;
}

const DATA_QUERY_SYSTEM = `You are an expert at helping users query and search structured data. The user is asking questions about data stored in tables (each table corresponds to a class/schema in their version). Your job is to:

1. Interpret their natural language question.
2. Suggest how to find the data: e.g. which table(s) to look at, what field or criteria might match (e.g. "search for records where name contains X", "filter by status = active").
3. If they ask for something that would require a specific query or filter, describe the filter or search in plain language and optionally as a simple JSON structure (e.g. { "field": "name", "op": "contains", "value": "..." }).

You do NOT have direct access to run queries. You are assisting the user to formulate their search. Be concise. If the user's question is ambiguous, ask for clarification. Vectorization and semantic search may be added later; for now suggest keyword or field-based search.`;

function buildDataQuerySystem(options: { tableNames?: string[]; currentTableName?: string }): string {
  let s = DATA_QUERY_SYSTEM;
  if (options.tableNames?.length) {
    s += `\n\n# Available tables in this version\n${options.tableNames.join(', ')}`;
  }
  if (options.currentTableName) {
    s += `\n\n# Table currently selected by the user\n${options.currentTableName}`;
  }
  return s;
}

const PROPERTY_SUGGESTIONS_SYSTEM = `You help API designers propose reusable JSON Schema property definitions for a project's property library (OpenAPI 3.1).

# Output format

Return exactly one markdown fenced JSON block and nothing else — no preamble, no commentary outside the fence:

\`\`\`json
{
  "thinking": "2–5 sentences: how you interpreted the request and how you chose the suggestions.",
  "summary": "2–4 sentences: overview of the suggestion set and how the user might adopt them in Studio.",
  "suggestions": [
    {
      "name": "camelCasePropertyName",
      "description": "Human-readable description for the property library.",
      "schema": { },
      "thinking": "1–3 sentences: user-facing rationale for this row (Studio shows it beside the label in the suggestion list).",
      "summary": "Very short label (e.g. primary email)"
    }
  ]
}
\`\`\`

# Rules

- "suggestions" must contain at least one item; for broad asks prefer roughly 3–8 distinct properties.
- Each "name" must be camelCase and unique within "suggestions".
- Each "schema" must be a valid JSON Schema object describing a single reusable property (the shape stored as property \`data\` in Studio — not wrapped in an outer "properties" object).
- Use "$ref": "#/components/schemas/ClassName" only when that class appears in **Existing classes** below; otherwise use inline types.
- Prefer practical constraints: string + format, bounded numbers, enums as JSON arrays, arrays with typed \`items\`, etc.
- Do not reuse names from **Existing project properties** unless the user explicitly wants a variant — then pick a clearly distinct camelCase name.
- When the user names a domain (healthcare, finance, IoT, etc.), you may align names and formats with common industry vocabularies (for example FHIR-style elements in healthcare) while still emitting valid JSON Schema the Studio property library can store.
- Consider archetypal class fields (e.g. User → email, password hash, displayName), standard cross-cutting fields (id, createdAt, updatedAt), and properties that complement **Existing project properties** when the user asks for a coherent set.
- "thinking" at the root is your overall reasoning; each suggestion's "thinking" is specific to that row and appears beside that suggestion in the Studio list (keep it concise).
- You may add "explanation" or "rationale" on a suggestion instead of or in addition to "thinking"; if present, the UI prefers that string as the list subtitle.`;

const PROPERTY_TYPE_SUGGESTIONS_SYSTEM = `You help API designers pick JSON Schema shapes for ONE reusable property in an OpenAPI 3.1 property library.

The user has already chosen a property name (and may describe a class or domain). You return several **alternative schemas** for that same name so they can compare types, formats, references, and constraints.

# Output format

Return exactly one markdown fenced JSON block and nothing else — no preamble, no commentary outside the fence:

\`\`\`json
{
  "thinking": "2–5 sentences: how you interpreted the property name, class context, and existing project properties.",
  "summary": "2–4 sentences: how the alternatives differ and when to pick each.",
  "suggestions": [
    {
      "name": "sameAsTargetPropertyName",
      "description": "Optional human-readable line for the library.",
      "schema": { },
      "thinking": "1–3 sentences: user-facing rationale for this alternative (Studio shows it beside the label in the list).",
      "summary": "Very short label (e.g. UUID string)"
    }
  ]
}
\`\`\`

# Rules

- "suggestions" must contain at least 2 items and usually 3–8 **distinct schema shapes** (not duplicate JSON).
- Every suggestion's "name" MUST match the **Target property name** given in the system context (identical spelling).
- Each "schema" must be a valid JSON Schema object for a single reusable property (the shape stored as property \`data\` in Studio — not wrapped in an outer "properties" object).
- Prefer a spread of practical alternatives: primitives with strong formats, bounded numbers, enums, arrays with typed \`items\`, or \`"$ref": "#/components/schemas/ClassName"\` when that class appears in **Existing classes**.
- Include at least one "boring but robust" option (e.g. plain string or ISO-8601 date-time) when other options are domain-specific.
- When the domain suggests it (e.g. healthcare), one alternative may mirror a well-known industry pattern (FHIR logical types) using standard JSON Schema — do not invent non-JSON-Schema keywords.
- Use **Existing project properties** to propose complementary or related shapes (e.g. foreign-key style refs, parallel timestamp fields) when relevant.
- "thinking" at the root is your overall reasoning; each suggestion's "thinking" is specific to that row and appears beside that alternative in the Studio list (keep it concise).
- You may add "explanation" or "rationale" on a suggestion instead of or in addition to "thinking"; if present, the UI prefers that string as the list subtitle.`;

function buildPropertySuggestionsSystem(options: {
  existingClassNames?: string[];
  existingProperties?: Array<{ name: string; description?: string | null; data?: Record<string, unknown> }>;
}): string {
  let extra = '';
  if (options.existingClassNames?.length) {
    extra += `\n\n# Existing classes (reference only with $ref: "#/components/schemas/ClassName")\n${options.existingClassNames.join(', ')}`;
  }
  if (options.existingProperties?.length) {
    extra += `\n\n# Existing project properties (avoid duplicate names unless the user asks for variants)\n`;
    options.existingProperties.forEach((p) => {
      const d = p.data;
      const typeStr =
        typeof d?.type === 'string'
          ? d.type
          : d && typeof d === 'object' && '$ref' in d && d.$ref
            ? '$ref'
            : 'object';
      extra += `- ${p.name}: ${typeStr}${p.description ? ` — ${String(p.description).slice(0, 80)}` : ''}\n`;
    });
  }
  return PROPERTY_SUGGESTIONS_SYSTEM + extra;
}

const PROPERTY_DESCRIPTION_SYSTEM = `You write concise API documentation for JSON Schema properties used in OpenAPI 3.1.

# Task
Return **plain prose only**: one or two sentences describing what the property holds or represents for API consumers.

# Rules
- No markdown, no bullet lists, no JSON, no code fences — output readable sentences only.
- Infer intent from the property name (typically camelCase), the schema type/format/constraints, and optional class context.
- Avoid redundant openers like "This property is" unless it reads most natural that way.
- Prefer staying under 400 characters; use more only when enums, formats, or references need explicit explanation.
- When the schema uses a component reference (\`$ref\`), say briefly that the field relates to or embeds that referenced model.
- Use **Existing classes** / **Existing project properties** only to disambiguate names — do not invent domain facts unsupported by the schema.`;

function buildPropertyDescriptionSystem(options: {
  existingClassNames?: string[];
  existingProperties?: Array<{ name: string; description?: string | null; data?: Record<string, unknown> }>;
  targetPropertyName?: string;
  targetClassName?: string;
}): string {
  let s = PROPERTY_DESCRIPTION_SYSTEM;
  const tp = typeof options.targetPropertyName === 'string' ? options.targetPropertyName.trim() : '';
  if (tp) {
    s += `\n\n# Target property name\n${tp}\n`;
  }
  const tc = typeof options.targetClassName === 'string' ? options.targetClassName.trim() : '';
  if (tc) {
    s += `\n\n# Containing class\n${tc}\n`;
  }
  if (options.existingClassNames?.length) {
    s += `\n\n# Existing classes\n${options.existingClassNames.join(', ')}`;
  }
  if (options.existingProperties?.length) {
    s += `\n\n# Existing project properties\n`;
    options.existingProperties.forEach((p) => {
      const d = p.data;
      const typeStr =
        typeof d?.type === 'string'
          ? d.type
          : d && typeof d === 'object' && '$ref' in d && d.$ref
            ? '$ref'
            : 'object';
      s += `- ${p.name}: ${typeStr}${p.description ? ` — ${String(p.description).slice(0, 80)}` : ''}\n`;
    });
  }
  return s;
}

const PROPERTY_EXAMPLE_SYSTEM = `You produce one realistic JSON example value for a JSON Schema property used in OpenAPI 3.1 documentation.

# Task
Return **exactly one** markdown fenced JSON block and **nothing outside the fence** (no preamble, no trailing commentary):

\`\`\`json
{ "example": <any JSON value> }
\`\`\`

# Rules
- The value after \`"example"\` must be valid JSON (object, array, string, number, boolean, or null).
- Ground the value in the **property name**, optional **property documentation description**, optional **nested member** hints, and the **JSON Schema snapshot** from the user message.
- Respect **enum** (pick one listed value), **string formats** (email, uuid, date-time, uri, etc.), numeric **minimum** / **maximum**, and **pattern** when you can produce a matching string.
- For **$ref** properties, emit a small plausible stub object using clearly fictional data (for example ids like \`"550e8400-e29b-41d4-a716-446655440000"\`, names like \`"Sample Customer"\`). Do not use real people, organizations, or live URLs implied to be production systems.
- Avoid realistic secrets: no live API keys, tokens, or passwords — use obvious placeholders only when the field clearly expects a secret.
- When the schema describes an **array** at the root, \`example\` should be a JSON array (often one representative element).
- Prefer one concise representative value over large fixtures.
- Use **Existing classes** / **Existing project properties** only to disambiguate references — do not contradict the supplied schema.`;

function buildPropertyExampleSystem(options: {
  existingClassNames?: string[];
  existingProperties?: Array<{ name: string; description?: string | null; data?: Record<string, unknown> }>;
  targetPropertyName?: string;
  targetClassName?: string;
}): string {
  let s = PROPERTY_EXAMPLE_SYSTEM;
  const tp = typeof options.targetPropertyName === 'string' ? options.targetPropertyName.trim() : '';
  if (tp) {
    s += `\n\n# Target property name\n${tp}\n`;
  }
  const tc = typeof options.targetClassName === 'string' ? options.targetClassName.trim() : '';
  if (tc) {
    s += `\n\n# Containing class\n${tc}\n`;
  }
  if (options.existingClassNames?.length) {
    s += `\n\n# Existing classes\n${options.existingClassNames.join(', ')}`;
  }
  if (options.existingProperties?.length) {
    s += `\n\n# Existing project properties\n`;
    options.existingProperties.forEach((p) => {
      const d = p.data;
      const typeStr =
        typeof d?.type === 'string'
          ? d.type
          : d && typeof d === 'object' && '$ref' in d && d.$ref
            ? '$ref'
            : 'object';
      s += `- ${p.name}: ${typeStr}${p.description ? ` — ${String(p.description).slice(0, 80)}` : ''}\n`;
    });
  }
  return s;
}

const CLASS_DESCRIPTION_SYSTEM = `You write concise API documentation for JSON Schema object classes used in OpenAPI 3.1 component schemas.

# Task
Return **plain prose only**: one to three sentences describing what the class represents as a whole for API consumers.

# Rules
- No markdown, no bullet lists, no JSON, no code fences — output readable sentences only.
- Ground the summary in the provided **Summarized class shape**: member property names, optional member descriptions, summarized per-property schemas, and optional composition (allOf / anyOf / oneOf class names).
- Synthesize the entity the class models; do not paste a bullet list of fields.
- Avoid redundant openers like "This class is" unless it reads most natural that way.
- Prefer staying under 600 characters; use more only when composition or many references need explicit explanation.
- Use **Existing classes** / **Existing project properties** only to disambiguate references — do not invent domain facts unsupported by the supplied shape.`;

function buildClassDescriptionSystem(options: {
  existingClassNames?: string[];
  existingProperties?: Array<{ name: string; description?: string | null; data?: Record<string, unknown> }>;
  targetClassName?: string;
}): string {
  let s = CLASS_DESCRIPTION_SYSTEM;
  const tc = typeof options.targetClassName === 'string' ? options.targetClassName.trim() : '';
  if (tc) {
    s += `\n\n# Target class name\n${tc}\n`;
  }
  if (options.existingClassNames?.length) {
    s += `\n\n# Existing classes\n${options.existingClassNames.join(', ')}`;
  }
  if (options.existingProperties?.length) {
    s += `\n\n# Existing project properties\n`;
    options.existingProperties.forEach((p) => {
      const d = p.data;
      const typeStr =
        typeof d?.type === 'string'
          ? d.type
          : d && typeof d === 'object' && '$ref' in d && d.$ref
            ? '$ref'
            : 'object';
      s += `- ${p.name}: ${typeStr}${p.description ? ` — ${String(p.description).slice(0, 80)}` : ''}\n`;
    });
  }
  return s;
}

const OPERATION_DESCRIPTION_SYSTEM = `You draft OpenAPI-style documentation for a single HTTP operation in an API spec.

# Task
Return **exactly one** markdown fenced JSON block and **nothing outside the fence** (no preamble, no trailing commentary):

\`\`\`json
{
  "summary": "Short phrase for the operation summary field.",
  "description": "Markdown-friendly explanation for API consumers."
}
\`\`\`

# Rules
- Infer typical REST semantics from the **HTTP method** (GET fetch/list, POST create, PUT replace, PATCH partial update, DELETE remove, HEAD/OPTIONS as appropriate) and from the **path template** (collection vs single resource, nested resources, \`{parameter}\` placeholders).
- **summary**: single line, plain text (no Markdown), imperative or concise noun phrase; prefer staying under 120 characters and omit a trailing period unless it aids clarity.
- **description**: one to three short paragraphs and/or a small Markdown bullet list; explain what the operation does, how path parameters map to the resource, and mention idempotency or side effects only when strongly implied by the method and path. Stay factual—do not invent domain-specific business rules not suggested by the path.
- When the path lists template parameters, name them generically (e.g. "resource identifier") unless the segment name clearly implies a role (e.g. \`userId\`).
- Both **summary** and **description** must be non-empty strings.`;

function buildPropertyTypeSuggestionsSystem(options: {
  existingClassNames?: string[];
  existingProperties?: Array<{ name: string; description?: string | null; data?: Record<string, unknown> }>;
  targetPropertyName?: string;
  targetClassName?: string;
}): string {
  let s = PROPERTY_TYPE_SUGGESTIONS_SYSTEM;
  const tp = typeof options.targetPropertyName === 'string' ? options.targetPropertyName.trim() : '';
  if (tp) {
    s += `\n\n# Target property name (mandatory)\nEvery suggestion's "name" field must be exactly: ${tp}\n`;
  }
  const tc = typeof options.targetClassName === 'string' ? options.targetClassName.trim() : '';
  if (tc) {
    s += `\n\n# Class or domain context\n${tc}\n`;
  }
  if (options.existingClassNames?.length) {
    s += `\n\n# Existing classes (reference only with $ref: "#/components/schemas/ClassName")\n${options.existingClassNames.join(', ')}`;
  }
  if (options.existingProperties?.length) {
    s += `\n\n# Existing project properties\n`;
    options.existingProperties.forEach((p) => {
      const d = p.data;
      const typeStr =
        typeof d?.type === 'string'
          ? d.type
          : d && typeof d === 'object' && '$ref' in d && d.$ref
            ? '$ref'
            : 'object';
      s += `- ${p.name}: ${typeStr}${p.description ? ` — ${String(p.description).slice(0, 80)}` : ''}\n`;
    });
  }
  return s;
}

const SCHEMA_IMPROVEMENT_SUGGESTIONS_SYSTEM = `You are a senior API and JSON Schema reviewer helping a team improve an OpenAPI 3.1–oriented data model in Apiome Studio.

You receive **measured canvas metrics** (class counts, documentation coverage, naming compliance, aggregate schema complexity, **conditional schema cyclomatic** (#612) from if/then/else, **dependency graph complexity** on refs/composition, **per-class cognitive complexity** scores, **maintainability index** (#613; higher = easier to evolve), samples of gaps). Your job is to propose **prioritized, actionable improvements** that a human can follow—similar in tone to:

- "Add descriptions to N classes to improve docs score"
- "Rename M properties to follow camelCase convention"
- "Split 'X' class — it has many properties (recommend decomposition when a class mixes unrelated concerns)"
- "Add pagination to 'GET /…' list endpoints" (when the user or digest implies large collections / list APIs)

# Output format

Return **exactly one** markdown fenced JSON block and **nothing outside the fence** (no preamble, no trailing commentary):

\`\`\`json
{
  "thinking": "2–5 sentences: how you read the metrics and what you prioritized.",
  "summary": "2–4 sentences: overall themes in your suggestion set.",
  "suggestions": [
    {
      "title": "Short imperative headline the user can scan (max ~120 chars).",
      "detail": "Concrete explanation: what to change, where to look, and why it helps quality or maintainability.",
      "category": "documentation",
      "effort": "quick_win",
      "estimatedOverallScoreDelta": 3,
      "apply": {
        "type": "set_class_description",
        "className": "ExactPascalCaseClassFromDigest",
        "description": "1–4 sentences; becomes the class description in Studio when the user bulk-applies."
      }
    }
  ]
}
\`\`\`

# Rules

- Emit **6–12** suggestions unless the digest is extremely small (then 3–5 is fine).
- Every "title" and "detail" must be non-empty strings.
- "category" must be one of: "documentation", "naming", "structure", "api", "performance", "other". Pick the best fit per row.
- Every row MUST include **"estimatedOverallScoreDelta"**: an **integer** (typically **0–12**, occasionally higher for broad fixes) estimating how many **points** the Studio **overall schema quality score (0–100)** in the digest would **increase** if that suggestion were **fully applied**. Use **0** only when the effect on the composite would be negligible. When the digest includes the current overall score line, anchor estimates to that baseline and the listed doc %, naming %, complexity, **conditional schema cyclomatic (#612)**, **dependency graph complexity (#611)**, **maintainability index (#613)**, and **per-class cognitive complexity** lines. Do not exceed **25**; use negative values only if a fix could realistically lower the composite (rare).
- Every row MUST include **"effort"**: one of \`"quick_win"\`, \`"moderate"\`, or \`"substantial"\`.
  - **quick_win**: small, localized edits (add missing descriptions, rename a few properties, tighten one validation) that a developer can often finish in minutes to an hour.
  - **moderate**: bounded refactors (split one busy class, normalize a small set of names, add a shared pattern across a few schemas).
  - **substantial**: broader design or cross-cutting work (large decompositions, API-wide pagination strategy, dependency reshaping).
- Order the **suggestions** array with **all quick_win items first**, then moderate, then substantial—so the JSON list itself reads as a prioritized backlog.
- Ground suggestions in the **digest numbers and named classes/properties** when present—do not invent entities that contradict the digest.
- It is acceptable to mention **future** API design (pagination, error models, versioning) when metrics imply large graphs, hubs, or wide classes—even if paths are not listed.
- Prefer distinct suggestions; do not repeat the same idea with different wording.
- Optional **apply** per suggestion (#256): include **only** when the row is a **documentation** fix that can be automated as filling a **currently empty** Studio description, and you can copy **exact** \`className\` / \`propertyName\` identifiers from the digest lists of missing documentation (never invent names).
  - **set_class_description**: \`{"type":"set_class_description","className":"<name>","description":"<text>"}\` — class must appear under classes missing description.
  - **set_property_description**: \`{"type":"set_property_description","className":"<Class>","propertyName":"<prop>","description":"<text>"}\` — pair must match a \`ClassName.propertyName\` line under properties missing description.
  - Omit **apply** for naming, structure, API design, or any suggestion that is not a straight empty-description fill.
  - At most **one** **apply** object per suggestion; descriptions must stay concise (well under 8000 characters).
- Do not output OpenAPI JSON, full schemas, or code blocks other than the single fenced JSON payload.`;

function buildSchemaImprovementSuggestionsSystem(options: {
  studioMetricsDigest: string;
  existingClassNames?: string[];
}): string {
  let s = SCHEMA_IMPROVEMENT_SUGGESTIONS_SYSTEM;
  s += `\n\n# Studio metrics digest\n\n${options.studioMetricsDigest.trim()}`;
  if (options.existingClassNames?.length) {
    const deduped = [...new Set(options.existingClassNames)].sort();
    const capped = deduped.slice(0, CLASS_NAMES_CAP);
    const overflow = deduped.length - capped.length;
    const suffix = overflow > 0 ? `, … and ${overflow} more` : '';
    s += `\n\n# Class names on canvas (PascalCase expected)\n${capped.join(', ')}${suffix}`;
  }
  return s;
}

const CANVAS_LAYOUT_RECOMMENDATIONS_SYSTEM = `You help Apiome Studio users arrange **ReactFlow** class diagrams.

The **Canvas layout analysis** JSON below was computed deterministically from the live canvas (classes, optional groups, and edges). It includes:
- recommendedDirection ("TB" or "LR") with rationale text
- stronglyConnectedComponents (directed cycles / tight clusters on the layout graph)
- hubClasses (high total degree after collapsing grouped classes into group nodes)
- hierarchyRoots (vertices with no incoming directed edges)
- weaklyConnectedComponentCount (relationship islands using undirected edges)

Respond in **markdown** with:
1. One short paragraph that agrees with or gently refines the TB vs LR recommendation for this graph.
2. A bullet list of 3–6 concrete steps for arranging or grouping nodes on the canvas (anchors, cycles, hubs, disconnected islands).
3. One sentence naming the main pitfall to avoid.

Rules:
- Reference only class or group labels that appear in the JSON.
- Stay under 350 words.
- Do not output JSON or fenced code blocks.`;

function buildCanvasLayoutRecommendationsSystem(layoutDigest: string): string {
  return `${CANVAS_LAYOUT_RECOMMENDATIONS_SYSTEM}\n\n# Canvas layout analysis JSON\n\n${layoutDigest}`;
}

export async function POST(request: NextRequest) {
  try {
    const {
      model,
      messages,
      task,
      existingClassNames,
      existingProperties,
      tableNames,
      currentTableName,
      versionId,
      schemaContextFingerprint,
      studioMetricsDigest,
      canvasLayoutDigest,
      targetPropertyName,
      targetClassName,
    } = await request.json();

    if (typeof model !== 'string' || !model.trim() || !messages || !Array.isArray(messages)) {
      return new Response(
        JSON.stringify({ error: 'Invalid request: model and messages are required' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } }
      );
    }

    const isClassSkeleton = task === 'class_skeleton';
    const isDataQuery = task === 'data_query';
    const isPropertySuggestions = task === 'property_suggestions';
    const isPropertyTypeSuggestions = task === 'property_type_suggestions';
    const isPropertyDescription = task === 'property_description';
    const isPropertyExample = task === 'property_example';
    const isClassDescription = task === 'class_description';
    const isOperationDescription = task === 'operation_description';
    const isSchemaImprovementSuggestions = task === 'schema_improvement_suggestions';
    const isCanvasLayoutRecommendations = task === 'canvas_layout_recommendations';
    const usesPropertyLibraryContext =
      isClassSkeleton ||
      isPropertySuggestions ||
      isPropertyTypeSuggestions ||
      isPropertyDescription ||
      isPropertyExample ||
      isClassDescription;

    const digestStr =
      typeof studioMetricsDigest === 'string' && studioMetricsDigest.trim().length > 0
        ? studioMetricsDigest.trim().slice(0, 64_000)
        : '';

    const canvasLayoutDigestStr =
      typeof canvasLayoutDigest === 'string' && canvasLayoutDigest.trim().length > 0
        ? canvasLayoutDigest.trim().slice(0, 64_000)
        : '';

    if (isSchemaImprovementSuggestions && !digestStr) {
      return new Response(
        JSON.stringify({ error: 'Invalid request: studioMetricsDigest is required for schema_improvement_suggestions' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } },
      );
    }

    if (isCanvasLayoutRecommendations && !canvasLayoutDigestStr) {
      return new Response(
        JSON.stringify({ error: 'Invalid request: canvasLayoutDigest is required for canvas_layout_recommendations' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } },
      );
    }

    // Create a system message to guide the LLM
    const systemContent = isClassSkeleton
      ? buildClassSkeletonSystem({
          existingClassNames: Array.isArray(existingClassNames) ? existingClassNames : undefined,
          existingProperties: Array.isArray(existingProperties) ? existingProperties : undefined,
        })
      : isDataQuery
        ? buildDataQuerySystem({
            tableNames: Array.isArray(tableNames) ? tableNames : undefined,
            currentTableName: typeof currentTableName === 'string' ? currentTableName : undefined,
          })
        : isPropertySuggestions
          ? buildPropertySuggestionsSystem({
              existingClassNames: Array.isArray(existingClassNames) ? existingClassNames : undefined,
              existingProperties: Array.isArray(existingProperties) ? existingProperties : undefined,
            })
          : isPropertyTypeSuggestions
            ? buildPropertyTypeSuggestionsSystem({
                existingClassNames: Array.isArray(existingClassNames) ? existingClassNames : undefined,
                existingProperties: Array.isArray(existingProperties) ? existingProperties : undefined,
                targetPropertyName: typeof targetPropertyName === 'string' ? targetPropertyName : undefined,
                targetClassName: typeof targetClassName === 'string' ? targetClassName : undefined,
              })
            : isPropertyDescription
              ? buildPropertyDescriptionSystem({
                  existingClassNames: Array.isArray(existingClassNames) ? existingClassNames : undefined,
                  existingProperties: Array.isArray(existingProperties) ? existingProperties : undefined,
                  targetPropertyName: typeof targetPropertyName === 'string' ? targetPropertyName : undefined,
                  targetClassName: typeof targetClassName === 'string' ? targetClassName : undefined,
                })
              : isPropertyExample
                ? buildPropertyExampleSystem({
                    existingClassNames: Array.isArray(existingClassNames) ? existingClassNames : undefined,
                    existingProperties: Array.isArray(existingProperties) ? existingProperties : undefined,
                    targetPropertyName: typeof targetPropertyName === 'string' ? targetPropertyName : undefined,
                    targetClassName: typeof targetClassName === 'string' ? targetClassName : undefined,
                  })
              : isClassDescription
                ? buildClassDescriptionSystem({
                    existingClassNames: Array.isArray(existingClassNames) ? existingClassNames : undefined,
                    existingProperties: Array.isArray(existingProperties) ? existingProperties : undefined,
                    targetClassName: typeof targetClassName === 'string' ? targetClassName : undefined,
                  })
                : isOperationDescription
                  ? OPERATION_DESCRIPTION_SYSTEM
            : isSchemaImprovementSuggestions
              ? buildSchemaImprovementSuggestionsSystem({
                  studioMetricsDigest: digestStr,
                  existingClassNames: Array.isArray(existingClassNames)
                    ? existingClassNames.filter((n: unknown): n is string => typeof n === 'string' && n.trim().length > 0)
                    : undefined,
                })
              : isCanvasLayoutRecommendations
                ? buildCanvasLayoutRecommendationsSystem(canvasLayoutDigestStr)
            : `You are an expert API designer and OpenAPI specification generator. Your task is to help users create OpenAPI 3.1.0 specifications based on their natural language descriptions.

# Rules

- When the user describes a domain, product, entities, or pasted requirements in plain language — even if they never say "OpenAPI" or "schema" — treat that as a request to produce or extend \`#/components/schemas\` accordingly (unless they clearly want non-schema advice only).
- Always generate valid OpenAPI 3.1.0 specifications
- When generating a complete specification, wrap it in a JSON code block: \`\`\`json\n{spec}\n\`\`\`
- Include proper info section with title, version, description, license, contact details
- Add servers section with at least one server URL (localhost is fine), and tags section with relevant tags
- Generate only schemas. Do not generate paths or path items inside the JSON document.
- Use components/schemas for all schema definitions
- Always generate descriptions and summaries to all properties and schemas
- Encourage using $ref for schema references when properties are reused
- Avoid duplicating properties: use $ref instead
- **CRITICAL: $ref must ONLY reference complete schemas in #/components/schemas, NEVER individual properties within a schema**
- **CORRECT: { "$ref": "#/components/schemas/User" }**
- When you need to reference a class/schema, use: "#/components/schemas/ClassName"
- Use advanced schema features like patternProperties, discriminators, conditional rules, and allOf/oneOf/anyOf where applicable
- Keep prose concise; put brief rationale into **Improvement suggestions** bullets where it helps
- Support incremental improvements to existing specs
- Do not generate clips of schemas in the response: The output should be the final schema
- Do not make up rules or constructs that are not possible in OpenAPI 3.1.0

# Generation instructions

- Do not output or generate paths.
- Only generate a complete OpenAPI Specification with a \`#/components/schemas\` section.
- Schemas must include a summary and description
- Examples must be provided for all schemas and properties of type "object" where applicable, and must be "examples" as an array, not singular "example"
- Property names are camelCase
- Schema and Tag names are PascalCase
- Objects cannot be outside of the properties definitions - all objects must contain properties unless they are allOf/oneOf/anyOf discriminators
- **$ref MUST reference complete schemas only**: Use "#/components/schemas/ClassName" format

# Important

- Schema must contain "openapi: 3.1.0" at the root level
- Properties must be defined in the properties section of the schema, and cannot reference a type outside of the schema like "#/components/schemas/User/properties/email" or "#/components/schemas/User#/properties/email". Instead, use "#/components/schemas/Email" or "#/components/schemas/Phone" respectively.
- All properties must include summaries and descriptions
- All classes must include summaries and descriptions
- All properties of type "object" must include examples
- All classes must include examples
- Examples must be provided in an "examples" array

Make adjustments to the schema as needed based on user feedback and requests for changes.

# Improvement suggestions (#495)

Immediately after the JSON code block, add a markdown section titled exactly **Improvement suggestions** with a bullet list of 2–5 short, actionable items tailored to the schemas you produced and the user's domain. Each bullet should read like a concrete next step (not generic platitudes). Draw from these patterns when they apply; rephrase for context:

- Consider adding pagination to list or collection endpoints when this API exposes large result sets (e.g. cursor or offset/limit).
- Consider modeling shared fields once with \`allOf\` when several schemas repeat the same base shape (inheritance / composition).
- Consider adding a \`discriminator\` when polymorphic types use \`oneOf\`/\`anyOf\` and variants need stable identification.
- Consider splitting an oversized schema into smaller \`#/components/schemas\` pieces composed with \`$ref\` when one object mixes unrelated concerns.
- Consider standard error responses (validation, not found, conflict, etc.) when operations are documented later.

Do not repeat the full JSON spec outside the code block. Do not add other sections beyond the spec JSON and **Improvement suggestions**, unless the user explicitly asks for a different layout.`;

    const systemMessage = {
      role: 'system',
      content: systemContent,
    };

    // Prepare messages with system prompt
    const fullMessages = [systemMessage, ...messages];

    const improvementClassNames =
      isSchemaImprovementSuggestions && Array.isArray(existingClassNames) ? existingClassNames : undefined;

    const cacheKey = ollamaChatCacheKey({
      model: typeof model === 'string' ? model : '',
      task: typeof task === 'string' ? task : undefined,
      existingClassNames: usesPropertyLibraryContext ? existingClassNames : improvementClassNames,
      existingProperties: usesPropertyLibraryContext ? existingProperties : undefined,
      tableNames: isDataQuery ? tableNames : undefined,
      currentTableName: isDataQuery ? currentTableName : undefined,
      versionId: typeof versionId === 'string' ? versionId : undefined,
      schemaContextFingerprint,
      studioMetricsDigest: isSchemaImprovementSuggestions ? digestStr : undefined,
      canvasLayoutDigest: isCanvasLayoutRecommendations ? canvasLayoutDigestStr : undefined,
      messages,
    });

    const semanticContextKey = ollamaChatSemanticContextKey({
      model: typeof model === 'string' ? model : '',
      task: typeof task === 'string' ? task : undefined,
      existingClassNames: usesPropertyLibraryContext ? existingClassNames : improvementClassNames,
      existingProperties: usesPropertyLibraryContext ? existingProperties : undefined,
      tableNames: isDataQuery ? tableNames : undefined,
      currentTableName: isDataQuery ? currentTableName : undefined,
      versionId: typeof versionId === 'string' ? versionId : undefined,
      schemaContextFingerprint,
      studioMetricsDigest: isSchemaImprovementSuggestions ? digestStr : undefined,
      canvasLayoutDigest: isCanvasLayoutRecommendations ? canvasLayoutDigestStr : undefined,
    });

    const cached = getCachedOllamaChatResponse(cacheKey);
    if (cached) {
      const encoder = new TextEncoder();
      const hitStream = new ReadableStream({
        start(controller) {
          if (request.signal.aborted) {
            controller.close();
            return;
          }
          const event: Record<string, unknown> = { done: true, content: cached.text };
          if (cached.usage) event.usage = cached.usage;
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
          controller.enqueue(encoder.encode('data: [DONE]\n\n'));
          controller.close();
        },
      });
      return new Response(hitStream, {
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
          'X-Ollama-Chat-Cache': 'HIT',
        },
      });
    }

    let messagesEmbedding: number[] | null = null;
    if (!isOllamaQueryCacheDisabled() && !isOllamaSemanticCacheDisabled()) {
      messagesEmbedding = await getEmbedding(ollamaChatMessagesFingerprint(messages), {
        signal: request.signal,
      });
      if (request.signal.aborted) {
        return new Response(null, { status: 499 });
      }
    }

    if (messagesEmbedding) {
      const semanticHit = findSemanticallySimilarCachedResponse({
        semanticContextKey,
        embedding: messagesEmbedding,
        threshold: ollamaSemanticCacheThreshold(),
      });
      if (semanticHit) {
        const { entry: similar } = semanticHit;
        // Promote into exact cache so repeated identical prompts skip the embed roundtrip.
        setCachedOllamaChatResponse(cacheKey, {
          text: similar.text,
          semanticContextKey,
          embedding: messagesEmbedding,
        });
        const encoder = new TextEncoder();
        const hitStream = new ReadableStream({
          start(controller) {
            if (request.signal.aborted) {
              controller.close();
              return;
            }
            // Do not forward usage: those token counts belong to the original request.
            const event: Record<string, unknown> = { done: true, content: similar.text };
            controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
            controller.enqueue(encoder.encode('data: [DONE]\n\n'));
            controller.close();
          },
        });
        return new Response(hitStream, {
          headers: {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            Connection: 'keep-alive',
            'X-Ollama-Chat-Cache': 'HIT-SEMANTIC',
          },
        });
      }
    }

    // Make request to Ollama with streaming
    const ollamaResponse = await fetch(`${OLLAMA_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model,
        messages: fullMessages,
        stream: true,
      }),
      signal: request.signal,
    });

    if (!ollamaResponse.ok) {
      throw new Error(`Ollama API error: ${ollamaResponse.statusText}`);
    }

    // Create a ReadableStream to process the streaming response
    const encoder = new TextEncoder();
    const decoder = new TextDecoder();

    const stream = new ReadableStream({
      async start(controller) {
        const reader = ollamaResponse.body?.getReader();
        if (!reader) {
          controller.close();
          return;
        }

        let closed = false;

        function safeEnqueue(data: Uint8Array): boolean {
          if (closed) return false;
          try {
            controller.enqueue(data);
            return true;
          } catch (e) {
            if (e instanceof TypeError && String(e.message).includes('already closed')) {
              closed = true;
              return false;
            }
            throw e;
          }
        }

        function safeClose(): void {
          if (closed) return;
          try {
            controller.close();
            closed = true;
          } catch (e) {
            if (e instanceof TypeError && String(e.message).includes('already closed')) {
              closed = true;
            } else {
              throw e;
            }
          }
        }

        let buffer = '';
        let fullAssistant = '';
        let lastUsage: { promptTokens?: number; completionTokens?: number } | undefined;
        let sawOllamaDone = false;

        function ingestAssistantPayload(data: Record<string, unknown>): {
          content: string | undefined;
          usage: { promptTokens?: number; completionTokens?: number } | undefined;
          done: boolean;
        } {
          const content = pickAssistantContent(data);
          const usage = usageFromOllamaPayload(data);
          const done = Boolean(data.done);
          if (content) fullAssistant += content;
          if (usage) lastUsage = usage;
          if (done) sawOllamaDone = true;
          return { content, usage, done };
        }

        function tryStoreCache(): void {
          if (request.signal.aborted || closed) return;
          if (!sawOllamaDone) return;
          if (fullAssistant.trim().length === 0) return;
          const semanticMeta =
            messagesEmbedding && !isOllamaSemanticCacheDisabled()
              ? { semanticContextKey, embedding: messagesEmbedding }
              : {};
          setCachedOllamaChatResponse(cacheKey, {
            text: fullAssistant,
            usage: lastUsage,
            ...semanticMeta,
          });
        }

        try {
          while (true) {
            const { done, value } = await reader.read();

            if (done) {
              // Process any remaining buffer
              if (buffer.trim() && !closed) {
                try {
                  const data = JSON.parse(buffer) as Record<string, unknown>;
                  const { content, usage, done: isDone } = ingestAssistantPayload(data);
                  if (content || usage) {
                    const event: Record<string, unknown> = { done: isDone };
                    if (content) event.content = content;
                    if (usage) event.usage = usage;
                    safeEnqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
                  }
                } catch {
                  // Ignore parse errors on final buffer
                }
              }

              if (!closed) {
                tryStoreCache();
                safeEnqueue(encoder.encode('data: [DONE]\n\n'));
                safeClose();
              }
              break;
            }

            // Decode the chunk with streaming enabled
            const chunk = decoder.decode(value, { stream: true });
            buffer += chunk;

            // Process complete lines immediately (split by newline)
            const lines = buffer.split('\n');

            // Keep the last incomplete line in the buffer
            buffer = lines.pop() || '';

            // Process each complete line immediately
            for (const line of lines) {
              if (!line.trim() || closed) continue;

              try {
                const data = JSON.parse(line) as Record<string, unknown>;
                const { content, usage, done: isDone } = ingestAssistantPayload(data);

                if (content || usage) {
                  const event: Record<string, unknown> = { done: isDone };
                  if (content) event.content = content;
                  if (usage) event.usage = usage;
                  if (!safeEnqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))) {
                    break;
                  }
                }

                // If this is the last message, signal completion
                if (isDone) {
                  tryStoreCache();
                  safeEnqueue(encoder.encode('data: [DONE]\n\n'));
                  safeClose();
                  return;
                }
              } catch (parseError) {
                // Only log actual JSON parse errors, not controller-closed from client disconnect
                if (parseError instanceof SyntaxError || (parseError instanceof TypeError && !String(parseError.message).includes('already closed'))) {
                  console.error('Error parsing Ollama response line:', parseError, 'Line:', line);
                }
              }
            }
          }
        } catch (error) {
          if (!closed) {
            if (!isAbortError(error, request.signal)) {
              console.error('Error reading stream:', error);
            }
            try {
              controller.error(error);
            } catch {
              // Controller may already be closed (e.g. client disconnected)
            }
          }
        }
      },
    });

    // Return SSE response
    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
        'X-Ollama-Chat-Cache': 'MISS',
      },
    });
  } catch (error: unknown) {
    // AbortError is normal (client disconnected or user clicked Stop) — don't log or 500.
    if (isAbortError(error, request.signal)) {
      return new Response(null, { status: 499 });
    }
    console.error('Error in Ollama chat:', error);
    const message = error instanceof Error ? error.message : 'Failed to process chat request';
    return new Response(
      JSON.stringify({ error: message || 'Failed to process chat request' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
}

