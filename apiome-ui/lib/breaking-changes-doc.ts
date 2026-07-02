/**
 * Deterministic Markdown breaking-changes / release-notes text from schema diff (#746).
 * Uses the same structural diff as `compareSchemas` (schema-aware #506).
 */

import {
  compareSchemas,
  formatPropertyDiffLine,
  type DiffSummary,
  type SchemaDiff,
} from './schema-diff';

/** Bump when output shape or classification rules change (determinism contract). */
export const BREAKING_CHANGES_DOC_TEMPLATE_ID = 'apiome-breaking-changes' as const;
export const BREAKING_CHANGES_DOC_TEMPLATE_VERSION = 1;

const DOCISH_KEYS = new Set(['description', 'title', 'example']);

const CONSTRAINT_KEYS = new Set([
  'minimum',
  'maximum',
  'exclusiveMinimum',
  'exclusiveMaximum',
  'minLength',
  'maxLength',
  'pattern',
  'minItems',
  'maxItems',
  'multipleOf',
  'uniqueItems',
]);

/** OpenAPI-style stable pointer: `components.schemas…` (dots, no leading slash). */
export function stableOpenApiComponentId(path: string): string {
  return `components.${path}`;
}

function enumChangeKind(oldVal: unknown, newVal: unknown): 'narrow' | 'widen' | 'other' {
  const o = oldVal != null && typeof oldVal === 'object' ? (oldVal as { enum?: unknown }).enum : undefined;
  const n = newVal != null && typeof newVal === 'object' ? (newVal as { enum?: unknown }).enum : undefined;
  if (!Array.isArray(o) || !Array.isArray(n) || o.length === 0) {
    return 'other';
  }
  const lost = o.filter((x) => !n.includes(x));
  const gained = n.filter((x) => !o.includes(x));
  if (lost.length && gained.length) {
    return 'other';
  }
  if (lost.length) {
    return 'narrow';
  }
  if (gained.length) {
    return 'widen';
  }
  return 'other';
}

function nullableBreaking(oldVal: unknown, newVal: unknown): boolean {
  const o = oldVal != null && typeof oldVal === 'object' ? (oldVal as { nullable?: unknown }).nullable : undefined;
  const n = newVal != null && typeof newVal === 'object' ? (newVal as { nullable?: unknown }).nullable : undefined;
  return o === true && n === false;
}

function classifyModifiedSchema(d: SchemaDiff): 'breaking' | 'other' {
  const changes = d.changes ?? [];
  if (changes.length === 0) {
    return 'other';
  }
  if (changes.every((c) => c === 'description')) {
    return 'other';
  }
  return 'breaking';
}

function classifyModifiedProperty(d: SchemaDiff): 'breaking' | 'other' {
  const changes = d.changes ?? [];
  if (changes.length === 0) {
    return 'other';
  }
  if (changes.every((c) => DOCISH_KEYS.has(c))) {
    return 'other';
  }

  if (changes.includes('nullable') && nullableBreaking(d.oldValue, d.newValue)) {
    return 'breaking';
  }
  if (changes.includes('nullable') && !nullableBreaking(d.oldValue, d.newValue)) {
    // Widening nullability — non-breaking
  }

  if (changes.includes('enum')) {
    const kind = enumChangeKind(d.oldValue, d.newValue);
    const rest = changes.filter((c) => c !== 'enum');
    if (kind === 'widen' && rest.every((c) => DOCISH_KEYS.has(c))) {
      return 'other';
    }
    if (kind === 'narrow') {
      return 'breaking';
    }
  }

  for (const c of changes) {
    if (c === 'enum') {
      continue;
    }
    if (DOCISH_KEYS.has(c)) {
      continue;
    }
    if (c === 'nullable' && !nullableBreaking(d.oldValue, d.newValue)) {
      continue;
    }
    if (
      c === 'type' ||
      c === '$ref' ||
      c === 'items' ||
      c === 'readOnly' ||
      c === 'writeOnly' ||
      c === 'deprecated' ||
      c === 'default' ||
      c === 'format' ||
      CONSTRAINT_KEYS.has(c)
    ) {
      return 'breaking';
    }
    // Unknown key: treat as breaking for API contracts
    return 'breaking';
  }

  if (changes.includes('enum')) {
    return enumChangeKind(d.oldValue, d.newValue) === 'widen' ? 'other' : 'breaking';
  }

  return 'other';
}

function isRedundantUnderSchemaOp(
  d: SchemaDiff,
  sameType: 'added' | 'removed',
  bucket: SchemaDiff[]
): boolean {
  if (d.itemType !== 'property' || d.type !== sameType) {
    return false;
  }
  const m = d.path.match(/^schemas\.([^.]+)\.properties\./);
  if (!m) {
    return false;
  }
  const className = m[1];
  return bucket.some(
    (x) =>
      x.itemType === 'schema' &&
      x.type === sameType &&
      x.path === `schemas.${className}`
  );
}

export interface BreakingChangesBullet {
  /** Stable identifier (OpenAPI component path). */
  stableId: string;
  /** Markdown bullet body after `- ` (no leading dash). */
  text: string;
  category: 'breaking' | 'additions' | 'other';
}

/**
 * Build classified bullets from a diff summary. Sorted by `(stableId, text)` for determinism.
 */
export function buildBreakingChangesBullets(summary: DiffSummary): BreakingChangesBullet[] {
  const out: BreakingChangesBullet[] = [];

  for (const d of summary.removed) {
    if (isRedundantUnderSchemaOp(d, 'removed', summary.removed)) {
      continue;
    }
    const id = stableOpenApiComponentId(d.path);
    const line = formatPropertyDiffLine(d);
    out.push({
      stableId: id,
      text: `\`${id}\` — ${line}`,
      category: 'breaking',
    });
  }

  for (const d of summary.added) {
    if (isRedundantUnderSchemaOp(d, 'added', summary.added)) {
      continue;
    }
    const id = stableOpenApiComponentId(d.path);
    const line = formatPropertyDiffLine(d);
    out.push({
      stableId: id,
      text: `\`${id}\` — ${line}`,
      category: 'additions',
    });
  }

  for (const d of summary.modified) {
    if (d.itemType === 'schema') {
      const cat = classifyModifiedSchema(d);
      const id = stableOpenApiComponentId(d.path);
      const line = formatPropertyDiffLine(d);
      out.push({
        stableId: id,
        text: `\`${id}\` — ${line}`,
        category: cat === 'breaking' ? 'breaking' : 'other',
      });
      continue;
    }
    if (d.itemType === 'property') {
      const cat = classifyModifiedProperty(d);
      const id = stableOpenApiComponentId(d.path);
      const line = formatPropertyDiffLine(d);
      out.push({
        stableId: id,
        text: `\`${id}\` — ${line}`,
        category: cat === 'breaking' ? 'breaking' : 'other',
      });
    }
  }

  out.sort((a, b) => {
    if (a.stableId < b.stableId) return -1;
    if (a.stableId > b.stableId) return 1;
    if (a.text < b.text) return -1;
    if (a.text > b.text) return 1;
    return 0;
  });

  return out;
}

export interface GenerateBreakingChangesMarkdownOptions {
  /** e.g. `v1.0.0 (base)` */
  baseLabel?: string;
  /** e.g. `v1.1.0 (target)` */
  targetLabel?: string;
}

/**
 * Full Markdown document: Breaking / Additions / Other, deterministic ordering, template version noted.
 */
export function generateBreakingChangesMarkdownFromSummary(
  summary: DiffSummary,
  options?: GenerateBreakingChangesMarkdownOptions
): string {
  const bullets = buildBreakingChangesBullets(summary);
  const breaking = bullets.filter((b) => b.category === 'breaking').map((b) => b.text);
  const additions = bullets.filter((b) => b.category === 'additions').map((b) => b.text);
  const other = bullets.filter((b) => b.category === 'other').map((b) => b.text);

  const base = options?.baseLabel ?? 'base';
  const target = options?.targetLabel ?? 'target';

  const lines: string[] = [
    `<!-- ${BREAKING_CHANGES_DOC_TEMPLATE_ID} v${BREAKING_CHANGES_DOC_TEMPLATE_VERSION} -->`,
    '',
    `# Schema changes (generated)`,
    '',
    `**Range:** ${base} → ${target}`,
    '',
    `**Template:** \`${BREAKING_CHANGES_DOC_TEMPLATE_ID}\` v${BREAKING_CHANGES_DOC_TEMPLATE_VERSION}`,
    '',
    `## Breaking`,
    '',
  ];

  if (breaking.length === 0) {
    lines.push('_None._', '');
  } else {
    for (const b of breaking) {
      lines.push(`- ${b}`, '');
    }
  }

  lines.push(`## Additions`, '');
  if (additions.length === 0) {
    lines.push('_None._', '');
  } else {
    for (const b of additions) {
      lines.push(`- ${b}`, '');
    }
  }

  lines.push(`## Other`, '');
  if (other.length === 0) {
    lines.push('_None._', '');
  } else {
    for (const b of other) {
      lines.push(`- ${b}`, '');
    }
  }

  return lines.join('\n').replace(/\n+$/, '\n');
}

/**
 * Compare two specs and emit breaking-changes Markdown (same inputs as schema-aware diff).
 */
export function generateBreakingChangesMarkdown(
  spec1: unknown,
  spec2: unknown,
  options?: GenerateBreakingChangesMarkdownOptions
): string {
  const summary = compareSchemas(spec1, spec2);
  return generateBreakingChangesMarkdownFromSummary(summary, options);
}
