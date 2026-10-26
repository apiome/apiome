/**
 * OpenAPI 3.2.0 hierarchical tag taxonomy (OA5, #3502).
 *
 * OpenAPI 3.2 enriches the Tag Object with `summary`, a `parent` (naming another tag,
 * which makes tags a tree) and a `kind` (e.g. `nav`, `badge`, `audience`). The OA2
 * normalization layer ({@link ./openapi32-converter.ts}) leaves these fields in place;
 * this module reads them so the taxonomy survives import:
 *
 *  - {@link parseTagObjects} reads the full Tag Objects of a document;
 *  - {@link buildTagTaxonomy} resolves `parent` links into a navigable tree, rejecting
 *    unknown parents and cycles with a warning;
 *  - {@link toStoredTagTaxonomy} is the compact form kept on the project's metadata
 *    under {@link TAG_TAXONOMY_METADATA_KEY};
 *  - {@link CLASS_TAGS_EXTENSION} names the class-schema provenance listing the tags a
 *    schema declares (`x-tags`, `x-tag`, `tags`, read by `getSchemaTags`).
 */

/** OpenAPI documents are walked untyped, like the other OpenAPI import utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

/** Project-metadata key the imported tag taxonomy is stored under. */
export const TAG_TAXONOMY_METADATA_KEY = 'x-apiome-tag-taxonomy';

/** Class-schema extension listing the tags the source schema declared. */
export const CLASS_TAGS_EXTENSION = 'x-apiome-tags';

/** Version of the {@link StoredTagTaxonomy} shape. */
export const TAG_TAXONOMY_FORMAT_VERSION = 1;

/** One Tag Object as declared in the document (OpenAPI 3.0 – 3.2 fields). */
export interface ParsedTag {
  name: string;
  summary?: string;
  description?: string;
  /** Name of the parent tag (3.2), as declared. */
  parent?: string;
  /** Tag kind (3.2), e.g. `nav`, `badge`, `audience`. */
  kind?: string;
  externalDocs?: { url: string; description?: string };
}

/** A tag in the resolved hierarchy. */
export interface TagTreeNode extends ParsedTag {
  /** Depth in the tree; roots are 0. */
  depth: number;
  /** Child tags, in document order. */
  children: TagTreeNode[];
}

/** The resolved taxonomy of a document. */
export interface TagTaxonomy {
  /** Every declared tag, in document order. `parent` is kept only when it was resolved. */
  tags: ParsedTag[];
  /** Root tags of the hierarchy, each with its descendants. */
  roots: TagTreeNode[];
  /** Problems found while resolving (duplicate names, unknown parents, cycles). */
  warnings: string[];
}

/** The taxonomy as stored on project metadata: the tags, with their resolved parents. */
export interface StoredTagTaxonomy {
  version: number;
  tags: ParsedTag[];
}

/** Return a trimmed non-empty string, or undefined. */
function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

/**
 * Read the Tag Objects of a document.
 *
 * Entries without a name are skipped; a name declared twice keeps its first
 * declaration and is reported.
 *
 * @param rawTags - the document's `tags` array.
 * @returns the parsed tags in document order, and warnings.
 */
export function parseTagObjects(rawTags: unknown): { tags: ParsedTag[]; warnings: string[] } {
  const tags: ParsedTag[] = [];
  const warnings: string[] = [];
  if (!Array.isArray(rawTags)) return { tags, warnings };

  const seen = new Set<string>();
  for (const raw of rawTags) {
    if (!raw || typeof raw !== 'object') continue;
    const name = text((raw as any).name);
    if (!name) continue;
    if (seen.has(name)) {
      warnings.push(`Tag "${name}" is declared more than once; the first declaration was kept.`);
      continue;
    }
    seen.add(name);

    const tag: ParsedTag = { name };
    const summary = text((raw as any).summary);
    const description = text((raw as any).description);
    const parent = text((raw as any).parent);
    const kind = text((raw as any).kind);
    const docs = (raw as any).externalDocs;
    if (summary) tag.summary = summary;
    if (description) tag.description = description;
    if (parent) tag.parent = parent;
    if (kind) tag.kind = kind;
    if (docs && typeof docs === 'object' && text(docs.url)) {
      tag.externalDocs = { url: text(docs.url)!, ...(text(docs.description) ? { description: text(docs.description) } : {}) };
    }
    tags.push(tag);
  }
  return { tags, warnings };
}

/**
 * Resolve a document's tags into a hierarchy.
 *
 * A `parent` that names no declared tag is dropped (the tag becomes a root). Every
 * tag on a `parent` cycle (including a tag that is its own parent) has its `parent`
 * dropped, so the cycle members become roots; tags hanging below a cycle stay
 * attached to their parent. Each case is reported once.
 *
 * @param doc - an OpenAPI document (raw 3.2, or normalized by OA2).
 * @returns the tags, the tree roots, and warnings.
 */
export function buildTagTaxonomy(doc: any): TagTaxonomy {
  const parsed = parseTagObjects(doc && typeof doc === 'object' ? doc.tags : undefined);
  const warnings = [...parsed.warnings];
  const byName = new Map(parsed.tags.map((t) => [t.name, t]));

  // Drop parents that name no declared tag.
  for (const tag of parsed.tags) {
    if (tag.parent && !byName.has(tag.parent)) {
      warnings.push(`Tag "${tag.name}" names an undeclared parent "${tag.parent}"; it was imported as a top-level tag.`);
      delete tag.parent;
    }
  }

  // Find cycles by following parent links; a node seen twice on one walk closes a cycle.
  const onCycle = new Set<string>();
  for (const start of parsed.tags) {
    const walk: string[] = [];
    let current: ParsedTag | undefined = start;
    while (current && !onCycle.has(current.name)) {
      const index = walk.indexOf(current.name);
      if (index >= 0) {
        const cycle = walk.slice(index);
        cycle.forEach((name) => onCycle.add(name));
        warnings.push(
          `Tag parent cycle ${[...cycle, cycle[0]].map((n) => `"${n}"`).join(' → ')}; ` +
          'their parent links were ignored and they were imported as top-level tags.'
        );
        break;
      }
      walk.push(current.name);
      current = current.parent ? byName.get(current.parent) : undefined;
    }
  }
  for (const name of onCycle) delete byName.get(name)!.parent;

  // Build the tree in document order.
  const nodes = new Map<string, TagTreeNode>(parsed.tags.map((t) => [t.name, { ...t, depth: 0, children: [] }]));
  const roots: TagTreeNode[] = [];
  for (const tag of parsed.tags) {
    const node = nodes.get(tag.name)!;
    if (tag.parent) nodes.get(tag.parent)!.children.push(node);
    else roots.push(node);
  }
  const setDepth = (node: TagTreeNode, depth: number): void => {
    node.depth = depth;
    node.children.forEach((child) => setDepth(child, depth + 1));
  };
  roots.forEach((root) => setDepth(root, 0));

  return { tags: parsed.tags, roots, warnings };
}

/**
 * Compact form of a taxonomy for project metadata.
 *
 * @param taxonomy - a resolved taxonomy.
 * @returns the stored form, or undefined when the document declares no tags.
 */
export function toStoredTagTaxonomy(taxonomy: TagTaxonomy): StoredTagTaxonomy | undefined {
  if (taxonomy.tags.length === 0) return undefined;
  return { version: TAG_TAXONOMY_FORMAT_VERSION, tags: taxonomy.tags.map((t) => ({ ...t })) };
}

