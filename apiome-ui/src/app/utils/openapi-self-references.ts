/**
 * OpenAPI 3.2.0 `$self` and `$ref` sibling overrides (OA6, #3503).
 *
 * `$self` is a document-level URI that names the document itself; a `$ref` is a URI
 * reference resolved against it. A `$ref` written as an absolute or relative URI can
 * therefore point back into the same document (`https://example.com/api.yaml#/...`,
 * `./api.yaml#/...`) or at another one.
 *
 *  - {@link resolveSelfReferences} rewrites every same-document `$ref` to its plain
 *    local fragment (`#/components/schemas/Customer`), which is the only spelling the
 *    importer resolves, and lists the references that point at other documents.
 *    A document without `$self` is returned unchanged, so 3.0 / 3.1 behavior is kept.
 *  - {@link applyRefSiblingOverrides} merges the `summary` / `description` written
 *    beside a `$ref` onto the resolved target as a local override.
 */

/** OpenAPI documents are walked untyped, like the other OpenAPI import utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * Base used to resolve a relative `$self`. It never leaves this module: only the
 * comparison "same document or not" is taken from resolved URLs.
 */
const PLACEHOLDER_BASE = 'https://apiome.invalid/';

/** Annotation keywords a `$ref` may carry that override its target (OpenAPI 3.1+). */
export const REF_SIBLING_OVERRIDE_KEYS = ['summary', 'description'] as const;

/** Result of {@link resolveSelfReferences}. */
export interface SelfReferenceResolution {
  /** The document to import: a rewritten copy when anything changed, else the input. */
  document: any;
  /** The `$self` the references were resolved against, when the document declares one. */
  self?: string;
  /** Number of `$ref`s rewritten from a URI to a local fragment. */
  rewritten: number;
  /** Distinct `$ref`s that point at another document, as written. */
  external: string[];
}

/**
 * Read a document's `$self`.
 *
 * @param doc - an OpenAPI document.
 * @returns the trimmed `$self`, or undefined when absent or not a string.
 */
export function getDocumentSelf(doc: any): string | undefined {
  const self = doc && typeof doc === 'object' ? doc.$self : undefined;
  return typeof self === 'string' && self.trim() ? self.trim() : undefined;
}

/**
 * Parse a URI reference against a base.
 *
 * @returns the URL, or null when it cannot be parsed.
 */
function parseUrl(reference: string, base: string | URL): URL | null {
  try {
    return new URL(reference, base);
  } catch {
    return null;
  }
}

/** A URL without its fragment, for "same document" comparisons. */
function withoutFragment(url: URL): string {
  const copy = new URL(url.href);
  copy.hash = '';
  return copy.href;
}

/**
 * Resolve the `$ref`s of a document against its `$self`.
 *
 * A `$ref` that already starts with `#` is local and left alone. Any other `$ref` is
 * resolved against `$self`: when it lands on the same document it is rewritten to its
 * fragment (kept exactly as written, `#` when it has none); otherwise it is left as
 * written and listed in `external`. A `$ref` that cannot be parsed is left alone.
 *
 * @param doc - an OpenAPI document (raw 3.2, or normalized by OA2).
 * @returns the document to import, and what was rewritten or found external.
 */
export function resolveSelfReferences(doc: any): SelfReferenceResolution {
  const self = getDocumentSelf(doc);
  if (!self) return { document: doc, rewritten: 0, external: [] };

  const base = parseUrl(self, PLACEHOLDER_BASE);
  if (!base) return { document: doc, self, rewritten: 0, external: [] };
  const selfDocument = withoutFragment(base);

  const external = new Set<string>();
  let rewritten = 0;

  /** Rewrite `$ref`s in place on the cloned document. */
  const walk = (node: any): void => {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    const ref = node.$ref;
    if (typeof ref === 'string' && ref && !ref.startsWith('#')) {
      const target = parseUrl(ref, base);
      if (target && withoutFragment(target) === selfDocument) {
        const hashAt = ref.indexOf('#');
        node.$ref = hashAt >= 0 ? ref.slice(hashAt) : '#';
        rewritten++;
      } else if (target) {
        external.add(ref);
      }
    }
    for (const value of Object.values(node)) walk(value);
  };

  const copy = JSON.parse(JSON.stringify(doc));
  walk(copy);
  return { document: rewritten > 0 ? copy : doc, self, rewritten, external: Array.from(external) };
}

/**
 * Merge a `$ref` node's sibling `summary` / `description` onto its resolved target.
 *
 * The sibling is a local override: it wins when present, and the target's own value
 * is kept when the `$ref` has no sibling. The target is never mutated.
 *
 * @param target - the schema the `$ref` resolves to.
 * @param refNode - the `$ref` node (`{ $ref, summary?, description? }`).
 * @returns the target with the overrides applied (the target itself when there are none).
 */
export function applyRefSiblingOverrides<T extends Record<string, any>>(target: T, refNode: any): T {
  if (!target || typeof target !== 'object' || !refNode || typeof refNode !== 'object') return target;
  const overrides: Record<string, unknown> = {};
  for (const key of REF_SIBLING_OVERRIDE_KEYS) {
    if (typeof refNode[key] === 'string' && refNode[key].trim()) overrides[key] = refNode[key];
  }
  return Object.keys(overrides).length > 0 ? { ...target, ...overrides } : target;
}

/**
 * Import warning for references that point at other documents.
 *
 * @param resolution - the result of {@link resolveSelfReferences}.
 * @returns the warning, or undefined when every reference stays in the document.
 */
export function describeExternalSelfReferences(resolution: SelfReferenceResolution): string | undefined {
  if (!resolution.self || resolution.external.length === 0) return undefined;
  return (
    `${resolution.external.length} reference${resolution.external.length === 1 ? '' : 's'} ` +
    `resolve${resolution.external.length === 1 ? 's' : ''} outside this document against $self ` +
    `"${resolution.self}" (${resolution.external.join(', ')}); ` +
    'they are kept as written and not followed by the import.'
  );
}
