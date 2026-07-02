import type { PropertyFormData } from '@/app/components/ade/studio/PropertyFormFields';

/**
 * Extracts the last ```json ... ``` (or ``` ... ```) code block from LLM output (#621).
 * Case-insensitive and tolerates preamble/trailing text, matching the pattern used in other AI parsers.
 */
function extractLastJsonCodeBlock(text: string): string | null {
  const re = /```(?:json)?\s*([\s\S]*?)```/gi;
  let last: string | null = null;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    last = m[1].trim();
  }
  return last;
}

/**
 * Parses LLM output for OpenAPI operation summary + description (#621).
 * Expects a JSON object (optionally inside a markdown fence) with non-empty string fields
 * `summary` and `description`. Returns null unless both fields are present and non-empty.
 */
export function parseGeneratedOperationDocs(raw: string): { summary: string; description: string } | null {
  let t = raw.trim();
  if (!t) return null;
  const fenced = extractLastJsonCodeBlock(t);
  if (fenced) t = fenced;

  let parsed: unknown;
  try {
    parsed = JSON.parse(t);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  const o = parsed as Record<string, unknown>;
  const summaryRaw = typeof o.summary === 'string' ? o.summary.trim().replace(/\s+/g, ' ') : '';
  const descriptionRaw = typeof o.description === 'string' ? o.description.trim() : '';
  if (!summaryRaw || !descriptionRaw) return null;
  return {
    summary: summaryRaw.slice(0, 400),
    description: descriptionRaw.slice(0, 16_000),
  };
}

/**
 * Parses LLM output for a single JSON Schema example value (#622).
 * Expects a JSON object (optionally inside a markdown fence) with an `example` key holding any JSON-serializable value.
 * Returns null only when parsing fails; use `.value` which may be null when the model emits `"example": null`.
 */
export function parseGeneratedPropertyExample(raw: string): { value: unknown } | null {
  let t = raw.trim();
  if (!t) return null;
  const fenced = extractLastJsonCodeBlock(t);
  if (fenced) t = fenced;

  let parsed: unknown;
  try {
    parsed = JSON.parse(t);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  const o = parsed as Record<string, unknown>;
  if (!Object.prototype.hasOwnProperty.call(o, 'example')) return null;
  return { value: o.example };
}

export function normalizeGeneratedPropertyDescription(raw: string): string {
  let t = raw.trim();
  if (!t) return '';
  const fenceWrapped = /^```[a-zA-Z]*\n?([\s\S]*?)\n?```$/;
  const m = t.match(fenceWrapped);
  if (m) t = m[1].trim();
  t = t.replace(/^#{1,6}\s+/gm, '').replace(/\*\*([^*]+)\*\*/g, '$1');
  const firstBlock = t.split(/\n\n+/)[0] ?? t;
  return firstBlock.replace(/\s+/g, ' ').trim().slice(0, 4000);
}

const DESCRIPTION_SCHEMA_KEYS = [
  'type',
  'format',
  'pattern',
  '$ref',
  'items',
  'enum',
  'const',
  'additionalProperties',
  'properties',
  'required',
  'oneOf',
  'anyOf',
  'allOf',
  'prefixItems',
  'tupleMode',
  'minLength',
  'maxLength',
  'minimum',
  'maximum',
  'exclusiveMinimum',
  'exclusiveMaximum',
  'minItems',
  'maxItems',
  'uniqueItems',
  'nullable',
  'description',
  'title',
  'deprecated',
  'readOnly',
  'writeOnly',
] as const;

function truncateDeep(value: unknown, depth: number): unknown {
  if (depth <= 0) return '[…]';
  if (value === null || value === undefined) return value;
  if (typeof value === 'string') {
    const cap = 320;
    const ellipsis = '…';
    const contentCap = cap - ellipsis.length;
    return value.length > cap ? `${value.slice(0, contentCap)}${ellipsis}` : value;
  }
  if (typeof value !== 'object') return value;
  if (Array.isArray(value)) {
    const cap = 12;
    const slice = value.slice(0, cap).map((x) => truncateDeep(x, depth - 1));
    return value.length > cap ? [...slice, `… +${value.length - cap} more`] : slice;
  }
  const o = value as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(o)) {
    out[k] = truncateDeep(o[k], depth - 1);
  }
  return out;
}

/**
 * Reduces persisted property `data` JSON for prompt size while keeping type semantics.
 */
export function summarizeStoredPropertyData(data: unknown): Record<string, unknown> {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return {};
  const src = data as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const k of DESCRIPTION_SCHEMA_KEYS) {
    if (!(k in src)) continue;
    out[k] = truncateDeep(src[k], 3);
  }
  if (Object.keys(out).length > 0) return out;
  return truncateDeep(src, 2) as Record<string, unknown>;
}

type SeedPropertyLike = {
  $ref?: string;
  items?: { $ref?: string; type?: string };
  type?: string | string[];
} | null;

/** Canvas / API class member row shape for AI class descriptions (#620). */
export type ClassMemberLike = {
  name?: string;
  description?: string | null;
  data?: unknown;
};

/**
 * Builds a compact JSON payload from class members and composition for `class_description` prompts (#620).
 */
export function buildClassDescriptionAiPayload(input: {
  members: ClassMemberLike[];
  composition?: { allOf?: string[]; anyOf?: string[]; oneOf?: string[] };
}): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  for (const m of input.members) {
    if (!m || typeof m !== 'object') continue;
    const name = typeof m.name === 'string' ? m.name.trim() : '';
    if (!name) continue;
    let data: Record<string, unknown> = {};
    if (typeof m.data === 'string') {
      try {
        data = JSON.parse(m.data) as Record<string, unknown>;
      } catch {
        data = {};
      }
    } else if (m.data !== null && typeof m.data === 'object' && !Array.isArray(m.data)) {
      data = { ...(m.data as Record<string, unknown>) };
    }
    const schema = summarizeStoredPropertyData(data);
    const md = m.description;
    const memberDesc =
      md != null && String(md).trim() ? String(md).trim().slice(0, 2000) : undefined;
    properties[name] = memberDesc ? { memberDescription: memberDesc, schema } : { schema };
  }
  const out: Record<string, unknown> = { properties };
  const c = input.composition;
  if (c) {
    const comp: Record<string, unknown> = {};
    if (c.allOf?.length) comp.allOf = c.allOf;
    if (c.anyOf?.length) comp.anyOf = c.anyOf;
    if (c.oneOf?.length) comp.oneOf = c.oneOf;
    if (Object.keys(comp).length > 0) out.composition = comp;
  }
  return out;
}

/**
 * Builds a compact JSON Schema snapshot from the property dialog form for AI description (#619).
 */
export function draftPropertySchemaFromDialogForm(input: {
  propertyType: string;
  propertyIsArray: boolean;
  formData: PropertyFormData;
  seedProperty: SeedPropertyLike;
}): Record<string, unknown> {
  const { propertyType, propertyIsArray, formData, seedProperty } = input;
  const nullable = Boolean(formData.nullable);
  const arrayType: string | string[] = nullable ? ['array', 'null'] : 'array';

  const valueHints = (): Record<string, unknown> => {
    const o: Record<string, unknown> = {};
    if (formData.format?.trim()) o.format = formData.format.trim();
    if (formData.pattern?.trim()) o.pattern = formData.pattern.trim();
    if (formData.enum && formData.enum.length > 0) o.enum = formData.enum.slice(0, 24);
    if (formData.minLength?.trim()) {
      const n = Number.parseInt(formData.minLength, 10);
      if (!Number.isNaN(n)) o.minLength = n;
    }
    if (formData.maxLength?.trim()) {
      const n = Number.parseInt(formData.maxLength, 10);
      if (!Number.isNaN(n)) o.maxLength = n;
    }
    if (formData.minimum?.trim()) {
      const n = Number.parseFloat(formData.minimum);
      if (!Number.isNaN(n)) {
        if (formData.minimumType === 'exclusive') o.exclusiveMinimum = n;
        else o.minimum = n;
      }
    }
    if (formData.maximum?.trim()) {
      const n = Number.parseFloat(formData.maximum);
      if (!Number.isNaN(n)) {
        if (formData.maximumType === 'exclusive') o.exclusiveMaximum = n;
        else o.maximum = n;
      }
    }
    return o;
  };

  const arrayHints = (): Record<string, unknown> => {
    const o: Record<string, unknown> = {};
    if (formData.minItems?.trim()) {
      const n = Number.parseInt(formData.minItems, 10);
      if (!Number.isNaN(n)) o.minItems = n;
    }
    if (formData.maxItems?.trim()) {
      const n = Number.parseInt(formData.maxItems, 10);
      if (!Number.isNaN(n)) o.maxItems = n;
    }
    if (formData.uniqueItems) o.uniqueItems = true;
    if (formData.tupleMode && formData.prefixItems?.length) {
      o.prefixItems = truncateDeep(formData.prefixItems, 3);
      o.tupleMode = true;
    }
    return o;
  };

  if (propertyType === '$ref') {
    const ref =
      (seedProperty && typeof seedProperty.$ref === 'string' && seedProperty.$ref) ||
      (seedProperty?.items && typeof seedProperty.items.$ref === 'string' && seedProperty.items.$ref) ||
      '';
    if (propertyIsArray) {
      return {
        type: arrayType,
        items: ref ? { $ref: ref, ...valueHints() } : { type: 'object', ...valueHints() },
        ...arrayHints(),
      };
    }
    return ref ? { $ref: ref, ...valueHints() } : { type: 'object', ...valueHints() };
  }

  const itemType = propertyType || 'string';

  const elementSchema = (includeNullable: boolean): Record<string, unknown> => {
    const base = valueHints();
    if (includeNullable) return { type: [itemType, 'null'], ...base };
    return { type: itemType, ...base };
  };

  if (propertyIsArray) {
    return {
      type: arrayType,
      items: elementSchema(false),
      ...arrayHints(),
    };
  }

  return elementSchema(nullable);
}
