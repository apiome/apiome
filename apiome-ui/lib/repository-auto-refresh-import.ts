/**
 * Spec-faithful re-import resolution for repository auto-refresh (RAR-4.1, #3527).
 *
 * The REST spec-import worker (`scripts/rest-spec-import-worker.ts`) builds its
 * importer input from the *request* metadata. A repository auto-refresh job
 * (`source_kind === 'repository_auto_import'`, REPO-12.1) supplies no per-request
 * options, so without this module the worker would fall back to importer defaults
 * and silently drop the user's original import specification.
 *
 * This module hydrates the importer input from the stored import spec captured at
 * first import (RAR-1.1/1.2) and its source descriptor (RAR-1.3) so a refresh
 * routes, parses, and applies options identically to the original run:
 *
 *   auto-refresh job ──► stored spec (options + source descriptor) ──► importer input
 *
 * It is a pure, side-effect-free module (no DB, no I/O) so the worker can reuse it
 * and a golden-fixture test can assert byte-identical option application.
 */

import { parse as parseYaml } from 'yaml';

import { convertSwaggerToOpenAPI, isSwagger2 } from '../src/app/utils/swagger-converter';
import type { ImportJobInput } from './db/import-helper';

/**
 * Synthetic `source_kind` the REST layer stamps on a repository auto-refresh job
 * (REPO-12.1). It is not a real importer kind: when the worker sees it the actual
 * importer kind, options, and parsing come from the stored import spec instead of
 * the request metadata.
 */
export const AUTO_REFRESH_SOURCE_KIND = 'repository_auto_import';

/** Resolved importer discriminator the worker can hand to the importer. */
export type ResolvedImportSourceKind = 'openapi' | 'arazzo';

/**
 * The stored import spec (RAR-1.1/1.2/1.3), carried into the worker so a refresh
 * replays the original import. `options` is the verbatim options blob persisted at
 * first import (the camelCase `ImportJobInput['options']` shape) — read as-is, not
 * the lossy REST `SpecImportOptions` subset — so prefixes, type mappings, and other
 * advanced options survive the round-trip.
 */
export interface StoredImportSpec {
  /** Importer discriminator used at first import (for example `openapi-3`, `arazzo`). */
  source_kind: string;
  /** Resolved spec format the importer routed on (for example `swagger`); drives format detection on refresh. */
  format_override?: string | null;
  /** MIME type the document was read as at first import (for example `application/yaml`); drives parsing on refresh. */
  content_type?: string | null;
  /** Verbatim options blob persisted at first import. */
  options?: Record<string, unknown> | null;
  /** Envelope version of the stored spec (RAR-1.4). */
  spec_schema_version?: number;
}

/** Worker metadata: the importer target plus, for a refresh, the stored spec. */
export interface WorkerImportMetadata {
  source_kind: string;
  project: { name: string; slug: string; description?: string | null };
  version: { version_id: string; description?: string | null };
  existing_project_id?: string | null;
  options?: Record<string, unknown>;
  /**
   * The stored import spec for a repository auto-refresh. Required (and consulted)
   * only when `source_kind === 'repository_auto_import'`; ignored otherwise.
   */
  repository_import_spec?: StoredImportSpec | null;
}

/** The worker stdin payload from the REST layer. */
export interface WorkerImportPayload {
  tenant_id: string;
  user_id: string;
  rest_job_id: string;
  metadata: WorkerImportMetadata;
  document_base64: string;
  filename?: string | null;
  content_type?: string | null;
}

/**
 * Map an importer kind or resolved format to the importer discriminator the
 * importer registry understands.
 *
 * @param kind the importer kind (`openapi-3`, `arazzo`, …) or resolved format (`swagger`, …).
 * @returns the resolved `openapi` or `arazzo` discriminator.
 * @throws when the kind is not a REST-supported spec import kind.
 *
 * Swagger 2.0 (`swagger-2`, the CLI's discriminator from {@link infer_source_kind}) routes to the
 * `openapi` importer; the Swagger 2.0 document is up-converted to OpenAPI 3.1 in
 * {@link buildImportJobInput} before the importer sees it.
 */
export function mapSourceKind(kind: string): ResolvedImportSourceKind {
  const k = kind.trim().toLowerCase();
  if (
    k === 'openapi-3' ||
    k === 'openapi3' ||
    k === 'openapi' ||
    k === 'swagger' ||
    k === 'swagger-2' ||
    k === 'swagger2' ||
    k === 'swagger-2.0' ||
    k === 'swagger2.0'
  ) {
    return 'openapi';
  }
  if (k === 'arazzo') {
    return 'arazzo';
  }
  throw new Error(
    `Unsupported source_kind "${kind}" for REST import (supported: openapi-3, swagger-2, arazzo).`,
  );
}

/**
 * Build the importer options from a stored/raw options blob, accepting both the
 * snake_case REST shape and the camelCase `ImportJobInput` shape so the same logic
 * serves request metadata and the verbatim stored spec. `incrementalMode` is forced
 * on: the REST worker always imports incrementally so the transaction is not held
 * across HTTP requests, independent of how the option was stored.
 *
 * @param o a raw options record (snake_case or camelCase keys).
 * @returns the normalized `ImportJobInput['options']`.
 */
export function optionsFromRecord(o: Record<string, unknown>): ImportJobInput['options'] {
  const sel = (o.selected_schemas ?? o.selectedSchemas) as unknown;
  const selectedSchemas = Array.isArray(sel) ? (sel as string[]) : [];
  return {
    selectedSchemas,
    dryRun: Boolean(o.dry_run ?? o.dryRun),
    incrementalMode: true,
    autoLayout: Boolean(o.auto_layout ?? o.autoLayout),
    createRelationships: Boolean(o.create_relationships ?? o.createRelationships),
    applyNamingConvention: Boolean(o.apply_naming_convention ?? o.applyNamingConvention),
    classNamingConvention: (o.class_naming_convention ?? o.classNamingConvention) as
      | ImportJobInput['options']['classNamingConvention']
      | undefined,
    propertyNamingConvention: (o.property_naming_convention ?? o.propertyNamingConvention) as
      | ImportJobInput['options']['propertyNamingConvention']
      | undefined,
    classNameMap: (o.class_name_map ?? o.classNameMap) as Record<string, string> | undefined,
    classPrefix: (o.class_prefix ?? o.classPrefix) as string | undefined,
    classSuffix: (o.class_suffix ?? o.classSuffix) as string | undefined,
    typeMapping: (o.type_mapping ?? o.typeMapping) as Record<string, unknown> | undefined,
    defaultValues: (o.default_values ?? o.defaultValues) as Record<string, unknown> | undefined,
    requiredOverrides: (o.required_overrides ?? o.requiredOverrides) as
      | Record<string, Record<string, boolean>>
      | undefined,
    descriptionOverrides: (o.description_overrides ?? o.descriptionOverrides) as
      | Record<string, Record<string, string>>
      | undefined,
    generateExamples: Boolean(o.generate_examples ?? o.generateExamples),
    skipDuplicateVersions: Boolean(o.skip_duplicate_versions ?? o.skipDuplicateVersions),
  };
}

/**
 * Parse a specification document. When `contentType` resolves to JSON or YAML the
 * matching parser is used so a refresh reads the bytes exactly as the first import
 * did (the stored source descriptor driving detection); otherwise the syntax is
 * sniffed from the leading character.
 *
 * @param text the decoded document text.
 * @param contentType the stored/declared content type, or null to sniff.
 * @returns the parsed document.
 * @throws when the document cannot be parsed.
 */
export function parseSpecDocument(text: string, contentType?: string | null): unknown {
  const ct = (contentType ?? '').trim().toLowerCase();
  const t = text.trim();
  const looksLikeJson = t.startsWith('{') || t.startsWith('[');

  // An explicit YAML hint always wins — and a YAML parser also accepts JSON, so it is safe even if
  // the body is actually JSON.
  if (ct.includes('yaml') || ct.includes('yml')) {
    return parseYaml(text) as unknown;
  }
  // Honor a JSON hint only when the body actually looks like JSON. Callers can mislabel the content
  // type (e.g. the CLI uploads a re-serialized YAML body of a `.yaml` file as `application/json`),
  // so a non-JSON-looking body falls back to YAML rather than being force-fed to `JSON.parse`.
  if (ct.includes('json')) {
    return (looksLikeJson ? JSON.parse(text) : parseYaml(text)) as unknown;
  }
  // No usable content-type hint: sniff JSON vs YAML from the first token.
  if (looksLikeJson) {
    return JSON.parse(text) as unknown;
  }
  return parseYaml(text) as unknown;
}

/** The importer kind, options, and parse hint resolved for one import job. */
export interface ResolvedImport {
  sourceKind: ResolvedImportSourceKind;
  options: ImportJobInput['options'];
  /** Content type to parse with (stored descriptor on refresh; else null to sniff). */
  contentType: string | null;
  /** Resolved spec format override carried from the stored descriptor, when any. */
  formatOverride: string | null;
}

/**
 * Resolve the importer kind, options, and parse hint for an import job.
 *
 * For a repository auto-refresh (`source_kind === 'repository_auto_import'`) these
 * come from the stored import spec so the refresh replays the original request:
 * the importer kind is routed from the stored source descriptor
 * (`format_override` preferred, else the stored `source_kind`), options are
 * hydrated from the stored options blob, and parsing follows the stored
 * `content_type`. For every other kind they come from the request metadata, with
 * format sniffed from the document as before.
 *
 * @param meta the worker import metadata.
 * @returns the resolved importer kind, options, and parse hints.
 * @throws when an auto-refresh job is missing its stored spec, or the kind is unsupported.
 */
export function resolveImport(meta: WorkerImportMetadata): ResolvedImport {
  if (meta.source_kind.trim().toLowerCase() === AUTO_REFRESH_SOURCE_KIND) {
    const spec = meta.repository_import_spec;
    if (!spec || !spec.source_kind || !spec.source_kind.trim()) {
      throw new Error(
        'Repository auto-refresh job is missing its stored import spec; cannot replay the ' +
          'original import options (RAR-4.1). Expected metadata.repository_import_spec.source_kind.',
      );
    }
    // The source descriptor drives format detection on refresh: prefer the resolved
    // format the importer recorded the first time, falling back to the importer kind.
    const routingKind = spec.format_override?.trim() || spec.source_kind;
    return {
      sourceKind: mapSourceKind(routingKind),
      options: optionsFromRecord(spec.options ?? {}),
      contentType: spec.content_type ?? null,
      formatOverride: spec.format_override?.trim() || null,
    };
  }
  return {
    sourceKind: mapSourceKind(meta.source_kind),
    options: optionsFromRecord(meta.options ?? {}),
    contentType: null,
    formatOverride: null,
  };
}

/**
 * Build the full importer input for the worker from its stdin payload, decoding and
 * parsing the document and resolving kind/options/descriptor. For a repository
 * auto-refresh this yields the same importer input the original import produced
 * (modulo the always-incremental REST execution mode).
 *
 * @param payload the worker stdin payload.
 * @returns the importer input to hand to `startImport`.
 * @throws when the document cannot be decoded/parsed or the kind is unsupported.
 */
export function buildImportJobInput(payload: WorkerImportPayload): ImportJobInput {
  const meta = payload.metadata;
  const resolved = resolveImport(meta);

  let document: unknown;
  try {
    const bytes = Buffer.from(payload.document_base64, 'base64');
    const text = bytes.toString('utf8');
    // The stored descriptor's content type wins on refresh; otherwise honor the
    // request content type when present, else sniff.
    document = parseSpecDocument(text, resolved.contentType ?? payload.content_type ?? null);
  } catch (e: unknown) {
    throw new Error(`Could not parse specification document: ${(e as Error)?.message ?? e}`);
  }

  // Swagger 2.0 (OpenAPI 2.0) is imported through the OpenAPI 3 importer, which reads schemas from
  // `components.schemas`. A Swagger 2.0 document keeps them under `definitions`, so it must first be
  // up-converted to OpenAPI 3.1 — exactly what the UI's browser import does via
  // `convertSwaggerToOpenAPI`. Mirroring it here lets the REST/CLI worker import Swagger 2.0 (the
  // CLI's `import auto` resolves such documents to `source_kind: "swagger-2"`) instead of producing
  // an empty import.
  if (resolved.sourceKind === 'openapi' && isSwagger2(document)) {
    const conversion = convertSwaggerToOpenAPI(document);
    if (!conversion.success) {
      throw new Error(`Swagger 2.0 to OpenAPI 3 conversion failed: ${conversion.error ?? 'unknown error'}`);
    }
    document = conversion.document;
  }

  const existing = meta.existing_project_id?.trim();
  return {
    tenantId: payload.tenant_id,
    userId: payload.user_id,
    sourceKind: resolved.sourceKind,
    document,
    project: {
      name: meta.project.name,
      slug: meta.project.slug,
      description: meta.project.description ?? undefined,
    },
    version: {
      versionId: meta.version.version_id,
      description: meta.version.description ?? null,
    },
    options: resolved.options,
    existingProjectId: existing !== undefined && existing !== '' ? existing : undefined,
  };
}
