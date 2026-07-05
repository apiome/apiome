/**
 * Export target → Monaco language, file extension, and download filename (MFX-9.4, #3869).
 *
 * The multi-format export surface lets a version be emitted to a registered target (OpenAPI and
 * AsyncAPI today; Arazzo, GraphQL, … as their emitter epics land). A target card previews the emitted artifact and
 * offers it for download, both of which need three pieces of client metadata the backend emitter
 * descriptor does not spell out directly: the Monaco language id for syntax highlighting, the file
 * extension, and a sensible download filename. This module is the single, data-driven bridge — pure
 * functions so they can be unit-tested without rendering the editor, mirroring the import-side
 * {@link file://./catalog-source-language.ts} resolver.
 *
 * Targets are keyed by the emitter's canonical id — either its registry `format` (`openapi-3.1`,
 * `swagger-2.0`, `asyncapi-3`) or its `key` (`openapi`, `asyncapi`). Version suffixes collapse to the
 * base id, so a new OpenAPI or AsyncAPI dialect maps without a code change. Unlike a raw imported
 * source (authored as either JSON or YAML), an emitter emits a **canonical serialization** —
 * OpenAPI/Swagger/AsyncAPI emit JSON — so the default language is JSON, refined to YAML/XML only when a
 * byte sample of the actual artifact says otherwise (e.g. the CLI's `--yaml` output). Everything
 * unknown degrades to `plaintext`, never throwing.
 *
 * The full registry-driven export dialog + target-card grid is a later epic (MFX-EPIC-41); this
 * module is the small client-metadata layer that grid — and any emitted-artifact viewer — reads.
 */

/** The client metadata one export target carries: highlight language, extension, and filename stem. */
interface ExportTargetMeta {
  /** Monaco language id for the emitter's canonical serialization. */
  readonly language: string;
  /** File extension (with leading dot) for the emitter's canonical serialization. */
  readonly extension: string;
  /** Download filename stem (no extension), e.g. `openapi` → `openapi.json`. */
  readonly baseName: string;
}

/**
 * Per canonical export-target id. OpenAPI and its Swagger 2.0 downgrade both emit JSON documents
 * (`openapi.json` / `swagger.json`); AsyncAPI 3 emits a JSON document too (`asyncapi.json`, MFX-11.5);
 * the no-op `sample` emitter is plaintext.
 */
const EXPORT_TARGET_LANGUAGE: Readonly<Record<string, ExportTargetMeta>> = {
  openapi: { language: 'json', extension: '.json', baseName: 'openapi' },
  swagger: { language: 'json', extension: '.json', baseName: 'swagger' },
  asyncapi: { language: 'json', extension: '.json', baseName: 'asyncapi' },
  sample: { language: 'plaintext', extension: '.txt', baseName: 'sample' },
};

/** Targets whose emitted serialization can vary (JSON default, YAML/XML sniffed from the bytes). */
const SERIALIZED_TARGETS: ReadonlySet<string> = new Set(['openapi', 'swagger', 'asyncapi']);

/** Monaco language id → file extension for a sniff-refined serialization. */
const LANGUAGE_EXTENSION: Readonly<Record<string, string>> = {
  json: '.json',
  yaml: '.yaml',
  xml: '.xml',
};

/**
 * Collapse an emitter `format`/`key` to its base target id: lower-cased, with any version or variant
 * suffix dropped (`openapi-3.1` → `openapi`, `swagger-2.0` → `swagger`). Returns `undefined` when the
 * base id is not a known export target.
 */
function resolveExportTargetId(target: string | null | undefined): string | undefined {
  const normalized = (target ?? '').trim().toLowerCase();
  if (!normalized) return undefined;
  if (normalized in EXPORT_TARGET_LANGUAGE) return normalized;
  const base = normalized.split(/[-\s]/, 1)[0];
  return base in EXPORT_TARGET_LANGUAGE ? base : undefined;
}

/**
 * Sniff the serialization language from the first non-blank characters of an emitted artifact: an
 * object/array opener (`{`/`[`) is JSON, an angle bracket (`<`) is XML, and a YAML document marker
 * (`---`, `%YAML`) or a top-level `key:` mapping line is YAML. Returns `undefined` when the sample is
 * empty or inconclusive, so the caller keeps the target's canonical default.
 */
function sniffSerialization(sample: string | null | undefined): string | undefined {
  if (!sample) return undefined;
  const trimmed = sample.replace(/^\uFEFF/, '').trimStart();
  if (!trimmed) return undefined;
  const first = trimmed[0];
  if (first === '{' || first === '[') return 'json';
  if (first === '<') return 'xml';
  if (trimmed.startsWith('---') || trimmed.startsWith('%YAML')) return 'yaml';
  // A top-level `key:` line (not a comment, not already handled) reads as YAML.
  if (/^[^\s:#][^:\n]*:(\s|$)/.test(trimmed)) return 'yaml';
  return undefined;
}

/**
 * Resolve the Monaco editor language for an emitted export artifact.
 *
 * @param targetFormat The emitter `format` or `key` (any version variant), or null/undefined.
 * @param sample An optional sample of the emitted bytes used to refine JSON-or-YAML targets and to
 *   type otherwise-unknown targets; omit it to get the target's canonical default.
 * @returns A Monaco language id (`json`, `yaml`, `xml`, `plaintext`), defaulting to `'plaintext'` for
 *   unrecognised targets.
 */
export function monacoLanguageForExportTarget(
  targetFormat: string | null | undefined,
  sample?: string | null,
): string {
  const id = resolveExportTargetId(targetFormat);
  if (!id) {
    return sniffSerialization(sample) ?? 'plaintext';
  }
  const base = EXPORT_TARGET_LANGUAGE[id].language;
  if (SERIALIZED_TARGETS.has(id)) {
    const sniffed = sniffSerialization(sample);
    if (sniffed) return sniffed;
  }
  return base;
}

/**
 * Resolve the file extension (with leading dot) for an emitted export artifact.
 *
 * @param targetFormat The emitter `format` or `key` (any version variant), or null/undefined.
 * @param sample An optional sample of the emitted bytes used to refine the serialization.
 * @returns An extension like `.json` / `.yaml`; `.txt` for unrecognised targets.
 */
export function fileExtensionForExportTarget(
  targetFormat: string | null | undefined,
  sample?: string | null,
): string {
  const id = resolveExportTargetId(targetFormat);
  const language = monacoLanguageForExportTarget(targetFormat, sample);
  const sniffedExtension = LANGUAGE_EXTENSION[language];
  if (sniffedExtension) return sniffedExtension;
  return id ? EXPORT_TARGET_LANGUAGE[id].extension : '.txt';
}

/**
 * Resolve a download filename for an emitted export artifact, e.g. `openapi` → `openapi.json`
 * (or `openapi.yaml` when the sample bytes are YAML).
 *
 * @param targetFormat The emitter `format` or `key` (any version variant), or null/undefined.
 * @param sample An optional sample of the emitted bytes used to refine the serialization.
 * @returns A filename with extension; `export.txt` for unrecognised targets.
 */
export function downloadFileNameForExportTarget(
  targetFormat: string | null | undefined,
  sample?: string | null,
): string {
  const id = resolveExportTargetId(targetFormat);
  const baseName = id ? EXPORT_TARGET_LANGUAGE[id].baseName : 'export';
  return `${baseName}${fileExtensionForExportTarget(targetFormat, sample)}`;
}
