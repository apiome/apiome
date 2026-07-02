/**
 * Resolved-type model (#3476).
 *
 * Pure helpers that turn a property's persisted type binding (`$ref` +
 * `primitive_id`, #3475) into its *effective* JSON Schema and a human-readable
 * summary, and that validate an example value against that schema. Kept free of
 * React so they can be unit-tested directly and reused by both the Designer
 * (class-property editor) and the Paths editor.
 */

import { validatePayloadAgainstSchema, type ValidationResult } from '@lib/database/validateSchema';
import { buildTypeRef, type Primitive } from './PrimitiveSelector';

/** One labelled constraint extracted from an effective schema (e.g. `minLength: 3`). */
export interface SchemaConstraint {
  label: string;
  value: string;
}

/** Structured, display-ready summary of a resolved type's effective schema. */
export interface ResolvedTypeSummary {
  /** JSON Schema `type` (e.g. `string`); `unknown` when the schema omits it. */
  type: string;
  /** JSON Schema `format` (e.g. `date`, `email`) when present. */
  format?: string;
  /** The validation constraints declared on the schema, in display order. */
  constraints: SchemaConstraint[];
}

/**
 * Resolve a property's persisted binding to the primitive row it points at.
 *
 * Prefers the stored FK (`primitive_id`) — an exact, scope-safe match — and
 * falls back to matching the stable registry `$ref` against `buildTypeRef`.
 * Returns `null` when neither identifies a primitive in the supplied list.
 *
 * @param ref          the stored registry `$ref` (e.g. `std/v0/types/date`), if any
 * @param primitiveId  the stored resolved primitive id (FK), if any
 * @param primitives   the candidate primitives to resolve against
 */
export function resolvePrimitiveRef(
  ref: string | null | undefined,
  primitiveId: string | null | undefined,
  primitives: Primitive[],
): Primitive | null {
  if (primitiveId) {
    const byId = primitives.find((p) => p.id === primitiveId);
    if (byId) return byId;
  }
  if (ref && ref.trim()) {
    const target = ref.trim();
    const byRef = primitives.find((p) => buildTypeRef(p) === target);
    if (byRef) return byRef;
  }
  return null;
}

/**
 * Summarize an effective JSON Schema into a type label, optional format and an
 * ordered list of validation constraints for display. Mirrors the constraint
 * set the type picker applies onto a property, so the preview matches what a
 * bound type actually enforces.
 */
export function summarizeEffectiveSchema(schema: Record<string, unknown>): ResolvedTypeSummary {
  const typeValue = schema.type;
  const type = Array.isArray(typeValue)
    ? typeValue.map(String).join(' | ')
    : typeof typeValue === 'string'
      ? typeValue
      : 'unknown';
  const format = typeof schema.format === 'string' ? schema.format : undefined;

  const constraints: SchemaConstraint[] = [];
  const push = (label: string, value: unknown) => constraints.push({ label, value: String(value) });

  if (schema.pattern !== undefined) push('pattern', schema.pattern);
  if (schema.minLength !== undefined) push('minLength', schema.minLength);
  if (schema.maxLength !== undefined) push('maxLength', schema.maxLength);
  if (schema.minimum !== undefined) push('minimum', schema.minimum);
  if (schema.maximum !== undefined) push('maximum', schema.maximum);
  if (schema.exclusiveMinimum !== undefined) push('exclusiveMinimum', schema.exclusiveMinimum);
  if (schema.exclusiveMaximum !== undefined) push('exclusiveMaximum', schema.exclusiveMaximum);
  if (schema.multipleOf !== undefined) push('multipleOf', schema.multipleOf);
  if (schema.minItems !== undefined) push('minItems', schema.minItems);
  if (schema.maxItems !== undefined) push('maxItems', schema.maxItems);
  if (schema.uniqueItems) push('uniqueItems', true);
  if (Array.isArray(schema.enum)) {
    const items = schema.enum as unknown[];
    const shown = items.slice(0, 5).map(String).join(', ');
    push('enum', `[${shown}${items.length > 5 ? ', …' : ''}]`);
  }
  if (schema.const !== undefined) {
    push('const', typeof schema.const === 'string' ? schema.const : JSON.stringify(schema.const));
  }

  return { type, format, constraints };
}

/** Result of coercing + validating an example value against an effective schema. */
export interface ExampleValidationResult extends ValidationResult {
  /** The example coerced to the schema's JSON type (what was actually validated). */
  coerced?: unknown;
}

/**
 * Coerce a raw text example to the JSON type implied by an effective schema.
 *
 * The Designer captures examples as free text. To validate them against a
 * 2020-12 schema we first lift the string into the schema's expected JSON type:
 * numbers/integers parse numerically, booleans parse `true`/`false`, and
 * arrays/objects parse as JSON. Strings pass through untouched. Throws when the
 * text cannot be coerced (e.g. non-numeric text for a `number`), so callers can
 * surface a precise "not valid JSON / not a number" message.
 */
export function coerceExampleValue(raw: string, schema: Record<string, unknown>): unknown {
  const type = Array.isArray(schema.type) ? schema.type[0] : schema.type;

  switch (type) {
    case 'number':
    case 'integer': {
      const trimmed = raw.trim();
      const n = Number(trimmed);
      if (trimmed === '' || Number.isNaN(n)) {
        throw new Error(`"${raw}" is not a valid ${type}`);
      }
      return n;
    }
    case 'boolean': {
      const lowered = raw.trim().toLowerCase();
      if (lowered === 'true') return true;
      if (lowered === 'false') return false;
      throw new Error(`"${raw}" is not a valid boolean (use true or false)`);
    }
    case 'array':
    case 'object': {
      try {
        return JSON.parse(raw);
      } catch {
        throw new Error(`"${raw}" is not valid JSON for a ${type}`);
      }
    }
    case 'null':
      return null;
    default:
      // string (and untyped) — keep the raw text.
      return raw;
  }
}

/**
 * Validate a raw text example against a resolved effective schema.
 *
 * Coerces the example to the schema's JSON type first (see
 * {@link coerceExampleValue}); a coercion failure is reported as a single
 * validation error rather than thrown. Returns the AJV (2020-12) verdict plus
 * the coerced value that was checked.
 */
export function validateExampleAgainstSchema(
  raw: string,
  schema: Record<string, unknown>,
): ExampleValidationResult {
  let coerced: unknown;
  try {
    coerced = coerceExampleValue(raw, schema);
  } catch (err) {
    return {
      valid: false,
      errors: [{ message: err instanceof Error ? err.message : 'Could not parse example value' }],
    };
  }
  const result = validatePayloadAgainstSchema(coerced, schema);
  return { ...result, coerced };
}
