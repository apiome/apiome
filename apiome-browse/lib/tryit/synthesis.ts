/**
 * Schema-driven request-body synthesis for the Try It panel — SIM-3.4 (#4450).
 *
 * TypeScript port of the apiome-mock SIM-1.3 synthesizer, kept framework-free so it is unit-tested
 * under Vitest and invoked from the `POST /api/try-it/sample` route.
 */

import { createHash } from 'node:crypto';
import { resolveRef } from './operation';

const MAX_DEPTH = 6;
const MAX_ARRAY_ITEMS = 5;

const FIRST_NAMES = ['Ada', 'Bjarne', 'Grace', 'Linus', 'Margaret', 'Dennis', 'Barbara', 'Ken'];
const LAST_NAMES = ['Lovelace', 'Stroustrup', 'Hopper', 'Torvalds', 'Hamilton', 'Ritchie', 'Liskov'];
const WORDS = ['lorem', 'ipsum', 'dolor', 'sit', 'amet', 'consectetur', 'adipiscing', 'elit'];

/** Parse a seed query value into a stable integer (mirrors mock `?__seed=`). */
export function parseMockSeed(raw: string | number | null | undefined): number {
  if (raw == null || String(raw).trim() === '') return 0;
  const text = String(raw).trim();
  const parsed = Number.parseInt(text, 10);
  if (!Number.isNaN(parsed)) return parsed;
  const digest = createHash('sha256').update(text).digest('hex');
  return Number.parseInt(digest.slice(0, 16), 16);
}

/** Deterministic pseudo-random state for one `(seed, field, depth)` tuple. */
class SeededRng {
  private state: number;

  constructor(seed: number, field: string, depth: number) {
    const digest = createHash('sha256')
      .update([String(seed), field, String(depth)].join('\0'))
      .digest('hex');
    this.state = seed ^ Number.parseInt(digest.slice(0, 16), 16);
  }

  next(): number {
    this.state = (this.state * 1664525 + 1013904223) >>> 0;
    return this.state / 0x1_0000_0000;
  }

  int(min: number, max: number): number {
    return Math.floor(this.next() * (max - min + 1)) + min;
  }

  choice<T>(items: readonly T[]): T {
    return items[this.int(0, items.length - 1)];
  }

  bool(): boolean {
    return this.next() >= 0.5;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function schemaType(schema: Record<string, unknown>): string | null {
  const t = schema.type;
  if (Array.isArray(t)) {
    const nonNull = t.find((entry) => entry !== 'null');
    return nonNull != null ? String(nonNull) : t[0] != null ? String(t[0]) : null;
  }
  if (t) return String(t);
  if ('properties' in schema) return 'object';
  if ('items' in schema || 'prefixItems' in schema) return 'array';
  return null;
}

function derefSchema(schema: unknown, root: unknown): Record<string, unknown> | null {
  const resolved = resolveRef(root, schema);
  return resolved;
}

function mergeAllOf(schema: Record<string, unknown>, root: unknown): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...schema };
  delete merged.allOf;
  const props: Record<string, unknown> = { ...(merged.properties as Record<string, unknown> | undefined) };
  const required: string[] = [...((merged.required as string[] | undefined) ?? [])];
  for (const subNode of (schema.allOf as unknown[]) ?? []) {
    let sub = derefSchema(subNode, root);
    if (!sub) continue;
    if (Array.isArray(sub.allOf)) sub = mergeAllOf(sub, root);
    if (sub.type && !merged.type) merged.type = sub.type;
    if (isObject(sub.properties)) Object.assign(props, sub.properties);
    if (Array.isArray(sub.required)) required.push(...sub.required.map(String));
  }
  if (Object.keys(props).length > 0) {
    merged.properties = props;
    merged.type ??= 'object';
  }
  if (required.length > 0) merged.required = [...new Set(required)].sort();
  return merged;
}

function clampString(value: string, schema: Record<string, unknown>): string {
  let out = value;
  const minLen = schema.minLength;
  const maxLen = schema.maxLength;
  if (typeof minLen === 'number' && out.length < minLen) {
    out = (out + 'x'.repeat(minLen)).slice(0, minLen);
  }
  if (typeof maxLen === 'number' && out.length > maxLen) {
    out = out.slice(0, maxLen);
  }
  return out;
}

function uuidLike(rng: SeededRng): string {
  const hex = Array.from({ length: 32 }, () => rng.int(0, 15).toString(16)).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-8${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function isoTimestamp(rng: SeededRng): string {
  return `20${rng.int(20, 29)}-${String(rng.int(1, 12)).padStart(2, '0')}-${String(rng.int(1, 28)).padStart(2, '0')}T${String(rng.int(0, 23)).padStart(2, '0')}:${String(rng.int(0, 59)).padStart(2, '0')}:${String(rng.int(0, 59)).padStart(2, '0')}Z`;
}

function stringForField(field: string, rng: SeededRng): string {
  const lowered = field.toLowerCase().replace(/[-_]/g, '');
  if (lowered.includes('email')) {
    return `${rng.choice(FIRST_NAMES).toLowerCase()}.${rng.choice(LAST_NAMES).toLowerCase()}@example.com`;
  }
  if (lowered.includes('uuid') || lowered.endsWith('id')) return uuidLike(rng);
  if (lowered.includes('created') || lowered.includes('updated') || lowered.includes('timestamp')) {
    return isoTimestamp(rng);
  }
  if (lowered.includes('name')) return `${rng.choice(FIRST_NAMES)} ${rng.choice(LAST_NAMES)}`;
  if (lowered.includes('url') || lowered.includes('uri')) {
    return `https://example.com/${rng.choice(WORDS)}/${rng.int(1, 999)}`;
  }
  return rng.choice(WORDS);
}

function stringForFormat(format: string, field: string, rng: SeededRng): string | null {
  if (format === 'email') return stringForField('email', rng);
  if (format === 'uuid') return uuidLike(rng);
  if (format === 'date') {
    return `20${rng.int(20, 29)}-${String(rng.int(1, 12)).padStart(2, '0')}-${String(rng.int(1, 28)).padStart(2, '0')}`;
  }
  if (format === 'date-time' || format === 'datetime') return isoTimestamp(rng);
  if (format === 'uri' || format === 'url' || format === 'uri-reference') {
    return stringForField('url', rng);
  }
  if (format === 'ipv4' || format === 'ip') {
    return Array.from({ length: 4 }, () => String(rng.int(1, 254))).join('.');
  }
  return stringForField(field, rng);
}

function genNumber(schema: Record<string, unknown>, rng: SeededRng, integer: boolean): number {
  let min = typeof schema.minimum === 'number' ? schema.minimum : 0;
  let max = typeof schema.maximum === 'number' ? schema.maximum : min + 100;
  if (max < min) [min, max] = [max, min];
  const value = rng.int(Math.ceil(min), Math.floor(max));
  return integer ? value : value + rng.int(0, 99) / 100;
}

function genString(schema: Record<string, unknown>, field: string, rng: SeededRng): string {
  const format = typeof schema.format === 'string' ? schema.format : null;
  if (format) {
    const byFormat = stringForFormat(format, field, rng);
    if (byFormat) return clampString(byFormat, schema);
  }
  return clampString(stringForField(field, rng), schema);
}

function genObject(
  schema: Record<string, unknown>,
  root: unknown,
  seed: number,
  field: string,
  depth: number,
  rng: SeededRng
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  const properties = { ...((schema.properties as Record<string, unknown> | undefined) ?? {}) };
  const required = new Set((schema.required as string[] | undefined) ?? []);
  const entries =
    depth >= MAX_DEPTH
      ? Object.entries(properties).filter(([name]) => required.has(name))
      : Object.entries(properties);

  for (const [propName, propSchema] of entries) {
    result[propName] = generateExample(propSchema, root, { seed, field: propName, depth: depth + 1 });
  }

  if (Object.keys(properties).length === 0 && isObject(schema.additionalProperties)) {
    result.key = generateExample(schema.additionalProperties, root, {
      seed,
      field: 'value',
      depth: depth + 1,
    });
  }
  return result;
}

function genArray(
  schema: Record<string, unknown>,
  root: unknown,
  seed: number,
  field: string,
  depth: number,
  rng: SeededRng
): unknown[] {
  const minItems = typeof schema.minItems === 'number' ? schema.minItems : 1;
  const maxItems =
    typeof schema.maxItems === 'number'
      ? Math.min(schema.maxItems, MAX_ARRAY_ITEMS)
      : Math.min(minItems || 1, MAX_ARRAY_ITEMS);
  const count = Math.max(minItems, Math.min(maxItems, rng.int(1, Math.max(1, maxItems))));
  const items = schema.items;
  if (!items) return [];
  return Array.from({ length: count }, (_, index) =>
    generateExample(items, root, { seed, field: `${field}[${index}]`, depth: depth + 1 })
  );
}

export interface GenerateExampleOptions {
  seed?: number;
  field?: string;
  depth?: number;
}

/**
 * Generate a schema-valid example value from a JSON Schema fragment.
 *
 * Explicit author intent (`const`, `example`, `examples`, `default`, `enum`) wins before synthesis.
 */
export function generateExample(
  schemaNode: unknown,
  root: unknown = null,
  options: GenerateExampleOptions = {}
): unknown {
  const seed = options.seed ?? 0;
  const field = options.field ?? 'root';
  const depth = options.depth ?? 0;
  const specRoot = root ?? schemaNode;

  let schema = derefSchema(schemaNode, specRoot);
  if (!schema) return null;

  const rng = new SeededRng(seed, field, depth);

  if ('const' in schema) return schema.const;
  if ('example' in schema) return schema.example;

  const examples = schema.examples;
  if (Array.isArray(examples) && examples.length > 0) return examples[0];
  if (isObject(examples)) {
    const first = Object.values(examples)[0];
    if (isObject(first) && 'value' in first) return first.value;
    return first;
  }

  if ('default' in schema) return schema.default;
  if (Array.isArray(schema.enum) && schema.enum.length > 0) return schema.enum[0];

  if (Array.isArray(schema.allOf)) {
    schema = mergeAllOf(schema, specRoot);
  }

  for (const combinator of ['oneOf', 'anyOf'] as const) {
    const branches = schema[combinator];
    if (Array.isArray(branches) && branches.length > 0) {
      const branch = derefSchema(branches[0], specRoot);
      if (branch) {
        return generateExample(branch, specRoot, { seed, field, depth: depth + 1 });
      }
    }
  }

  const jtype = schemaType(schema);
  if (jtype === 'object' || 'properties' in schema) {
    return genObject(schema, specRoot, seed, field, depth, rng);
  }
  if (jtype === 'array') {
    return genArray(schema, specRoot, seed, field, depth, rng);
  }
  if (jtype === 'boolean') return rng.bool();
  if (jtype === 'integer') return genNumber(schema, rng, true);
  if (jtype === 'number') return genNumber(schema, rng, false);
  if (jtype === 'null') return null;
  if (jtype === 'string') return genString(schema, field, rng);

  return clampString(stringForField(field, rng), schema);
}
