/**
 * OpenAPI 3.2 constructs in a project's generated document (COA-2.5, #7048).
 *
 * A project revision stores its paths as rows; the export generator
 * ({@link ./openapi-paths-generator.ts}) turns them into an OpenAPI document for a chosen target
 * version. Four OpenAPI 3.2 additions depend on that target:
 *
 *  - the `QUERY` method and other non-standard methods: the Path Item's `query` field and its
 *    `additionalOperations` map (3.2), else the `x-apiome-query-operation` /
 *    `x-apiome-additional-operations` stashes the importer reads back (3.1);
 *  - streaming media types: a content row flagged `item_schema` writes `itemSchema` (3.2), else the
 *    `x-apiome-item-schema` stash (3.1);
 *  - the `querystring` parameter location: written only for 3.2 — a 3.1 Parameter Object has no
 *    such location, so the parameter is left out;
 *  - the tag hierarchy: a Tag Object's `summary` / `parent` / `kind` are written only for 3.2.
 *
 * Everything here is pure, so the generator and its tests share one definition of "what 3.2 adds".
 */

import { STASHED_ITEM_SCHEMA_EXTENSION } from '../../src/app/utils/openapi-stream-media-types';
import { TAG_TAXONOMY_METADATA_KEY, type ParsedTag } from '../../src/app/utils/openapi-tag-taxonomy';

/** The parameter location OpenAPI 3.2 adds: the whole query string as one value. */
export const QUERYSTRING_LOCATION = 'querystring';

/** Media type a `querystring` parameter's `content` uses when none was stored. */
export const DEFAULT_QUERYSTRING_MEDIA_TYPE = 'application/x-www-form-urlencoded';

/**
 * Whether a target OpenAPI version has the 3.2 constructs.
 *
 * @param openapiVersion - the target version (`3.2.0`, `3.1.0`, …); `undefined` means the
 *   generator's conservative default, 3.1.
 * @returns true for any 3.2.x version.
 */
export function isOpenApi32(openapiVersion?: string | null): boolean {
  return typeof openapiVersion === 'string' && /^3\.2(\.|$)/.test(openapiVersion.trim());
}

/**
 * The Media Type Object key an element schema is written under.
 *
 * @param is32 - whether the target is OpenAPI 3.2.
 * @returns `itemSchema` for 3.2, else the `x-apiome-item-schema` stash.
 */
export function itemSchemaKey(is32: boolean): string {
  return is32 ? 'itemSchema' : STASHED_ITEM_SCHEMA_EXTENSION;
}

/**
 * Move the schema of every streaming media type from `schema` to its element-schema key.
 *
 * The content rows store an element schema in the same `class_id` / `inline_schema` columns as a
 * body schema, so the builders write it as `schema`; this renames it for the rows flagged
 * `item_schema`. A media type without a built `schema` is left alone.
 *
 * @param content - a built `content` map (mutated).
 * @param contentTypes - the stored content rows, keyed by `media_type`.
 * @param is32 - whether the target is OpenAPI 3.2.
 * @returns the same `content` map.
 */
export function applyItemSchemaKeys(
  content: Record<string, unknown>,
  contentTypes: ReadonlyArray<{ media_type: string; item_schema?: boolean | null }>,
  is32: boolean
): Record<string, unknown> {
  const key = itemSchemaKey(is32);
  for (const ct of contentTypes) {
    if (ct.item_schema !== true) continue;
    const media = content[ct.media_type];
    if (!media || typeof media !== 'object') continue;
    const mediaObject = media as Record<string, unknown>;
    if (mediaObject.schema === undefined) continue;
    mediaObject[key] = mediaObject.schema;
    delete mediaObject.schema;
  }
  return content;
}

/** One Tag Object as written to the document. */
export interface DocumentTag {
  name: string;
  summary?: string;
  description?: string;
  parent?: string;
  kind?: string;
  externalDocs?: { url: string; description?: string };
}

/**
 * Read the stored tag list from project metadata.
 *
 * @param metadata - the project's metadata (`projects.metadata`), or undefined.
 * @returns the tags kept under `x-apiome-tag-taxonomy`, in their stored order; empty when none.
 */
export function readStoredTags(metadata: Record<string, unknown> | null | undefined): ParsedTag[] {
  const taxonomy = metadata?.[TAG_TAXONOMY_METADATA_KEY];
  if (!taxonomy || typeof taxonomy !== 'object') return [];
  const tags = (taxonomy as { tags?: unknown }).tags;
  if (!Array.isArray(tags)) return [];
  return tags.filter(
    (tag): tag is ParsedTag =>
      Boolean(tag) && typeof tag === 'object' && typeof (tag as ParsedTag).name === 'string' && (tag as ParsedTag).name.trim() !== ''
  );
}

/**
 * Build the document's top-level `tags` for a target version.
 *
 * OpenAPI 3.2 writes `summary`, `parent` and `kind`; any other version writes only the fields its
 * Tag Object has (`name`, `description`, `externalDocs`). A `parent` naming a tag that is not in the
 * list is not written, so the document never points at a missing tag.
 *
 * @param tags - the stored tags.
 * @param is32 - whether the target is OpenAPI 3.2.
 * @returns the Tag Objects, in stored order.
 */
export function buildDocumentTags(tags: ReadonlyArray<ParsedTag>, is32: boolean): DocumentTag[] {
  const names = new Set(tags.map((tag) => tag.name));
  return tags.map((tag) => {
    const out: DocumentTag = { name: tag.name };
    if (is32 && tag.summary) out.summary = tag.summary;
    if (tag.description) out.description = tag.description;
    if (is32 && tag.parent && tag.parent !== tag.name && names.has(tag.parent)) out.parent = tag.parent;
    if (is32 && tag.kind) out.kind = tag.kind;
    if (tag.externalDocs?.url) out.externalDocs = tag.externalDocs;
    return out;
  });
}

/**
 * Project metadata as written to the document's `x-metadata` extension: the tag list is left out,
 * because it is written as the document's `tags`.
 *
 * @param metadata - the project's metadata.
 * @returns a copy without `x-apiome-tag-taxonomy`, or undefined when nothing else is left.
 */
export function metadataWithoutTags<T extends Record<string, unknown>>(metadata: T | undefined): T | undefined {
  if (!metadata || !(TAG_TAXONOMY_METADATA_KEY in metadata)) return metadata;
  const rest: Record<string, unknown> = { ...metadata };
  delete rest[TAG_TAXONOMY_METADATA_KEY];
  return Object.keys(rest).length > 0 ? (rest as T) : undefined;
}
