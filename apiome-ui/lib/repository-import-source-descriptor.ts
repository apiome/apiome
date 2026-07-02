/**
 * Source-descriptor derivation for repository imports (RAR-1.3, #3514).
 *
 * A faithful auto-refresh must route and parse a repository file identically to
 * its first import. To do that the refresh worker (RAR-4.1) needs the values the
 * importer actually resolved the first time — not a fresh sniff that could detect
 * the format or syntax differently. This module turns the spec analysis produced
 * at import time into the persisted descriptor fields (`format_override`,
 * `content_type`) so they can be stored alongside the import spec.
 *
 * `source_kind` and the filename are captured elsewhere (the importer kind and the
 * `path` lineage key respectively); this helper covers only the two descriptor
 * fields that are otherwise derived by sniffing.
 */

/** The subset of the spec analysis this descriptor is derived from. */
export interface SourceDescriptorAnalysisInput {
  /** Resolved spec format from sniffing (e.g. `openapi`, `swagger`, `arazzo`). */
  format: string;
  /** Concrete document syntax the spec was parsed as. */
  syntax: string;
}

/** The persisted source-descriptor fields for a repository import. */
export interface RepositoryImportSourceDescriptor {
  /**
   * The resolved spec format the importer routed on, captured so a refresh
   * re-routes identically instead of re-sniffing. `null` when the format could
   * not be determined (`unknown`).
   */
  formatOverride: string | null;
  /**
   * The content type the document was read/parsed as, derived from its syntax,
   * so a refresh reads the bytes with the same parser. `null` when the syntax is
   * not recognized.
   */
  contentType: string | null;
}

/** Document-syntax → content-type used to read the spec. */
const SYNTAX_CONTENT_TYPES: Record<string, string> = {
  json: 'application/json',
  yaml: 'application/yaml',
  graphql: 'application/graphql',
  protobuf: 'application/x-protobuf',
  thrift: 'application/x-thrift',
};

/**
 * Map a document syntax to the content type used to read it. Returns `null` for
 * an unrecognized or empty syntax so an unknown value is stored as "no content
 * type" rather than a fabricated one.
 *
 * @param syntax the analysis `syntax` value (e.g. `json`, `yaml`).
 * @returns the content type, or `null` when the syntax is not recognized.
 */
export function contentTypeForSyntax(syntax: string | null | undefined): string | null {
  if (!syntax) return null;
  return SYNTAX_CONTENT_TYPES[syntax.trim().toLowerCase()] ?? null;
}

/**
 * Normalize the resolved spec format into the stored `format_override`. An
 * `unknown` (or empty) format yields `null` so the descriptor records "no
 * resolved format" instead of the literal sentinel.
 *
 * @param format the analysis `format` value.
 * @returns the resolved format, or `null` when it could not be determined.
 */
export function formatOverrideForFormat(format: string | null | undefined): string | null {
  if (!format) return null;
  const trimmed = format.trim();
  if (!trimmed || trimmed.toLowerCase() === 'unknown') return null;
  return trimmed;
}

/**
 * Derive the persisted source descriptor (`format_override`, `content_type`) from
 * the spec analysis resolved at import time.
 *
 * @param analysis the resolved `format` and `syntax` from the import analysis.
 * @returns the descriptor fields to persist with the import spec.
 */
export function deriveRepositoryImportSourceDescriptor(
  analysis: SourceDescriptorAnalysisInput
): RepositoryImportSourceDescriptor {
  return {
    formatOverride: formatOverrideForFormat(analysis.format),
    contentType: contentTypeForSyntax(analysis.syntax),
  };
}
