/**
 * Catalog format / protocol / source-material registry (MFI-23.5, #4014).
 *
 * The headline metadata a catalog item carries off its latest imported revision (MFI-7.1/7.2) is
 * its **source format** (e.g. `openapi-3.1`, `grpc`, `graphql`), its **protocol / paradigm** (the
 * canonical `ApiParadigm`: REST / RPC / event / graph / data-schema / agent) and the **source
 * material** it came from (an uploaded file, a URL, pasted text, or a live discovery endpoint).
 *
 * This module is the single, data-driven lookup behind the catalog pills — modeled on
 * `project-domain-categories.ts`: a flat registry of entries plus pure resolver functions, so the
 * pill components (`FormatPill`, `ProtocolPill`, `SourceBadge`) stay presentational and the
 * format→icon/colour mapping can be unit-tested without rendering. Every resolver degrades
 * gracefully: an unknown-but-present format resolves to a neutral pill (never throws, never an empty
 * gap), and absent data resolves to `undefined` so a consumer can render nothing.
 *
 * No React here — only data + lucide icon references — so the registry is a plain importable map.
 */

import {
  FileJson,
  FileCode,
  Network,
  Share2,
  Radio,
  Database,
  Hammer,
  FileText,
  BookMarked,
  Binary,
  Braces,
  Cloud,
  Bot,
  Workflow,
  Upload,
  Link2,
  ClipboardPaste,
  Radar,
  type LucideIcon,
} from 'lucide-react';

/**
 * The fixed palette a pill can be tinted with. Centralising the colour here (rather than letting
 * each registry entry carry raw Tailwind literals) keeps the pills visually consistent and means a
 * new format only has to name a tone, not invent a colour. Each value is the full light+dark
 * `bg`/`text` class set for a pill.
 */
export type CatalogPillTone =
  | 'sky'
  | 'emerald'
  | 'violet'
  | 'pink'
  | 'orange'
  | 'slate'
  | 'amber'
  | 'red'
  | 'blue'
  | 'cyan'
  | 'indigo'
  | 'teal'
  | 'lime'
  | 'stone'
  | 'neutral';

/** Light+dark pill classes per tone. The neutral tone is the unknown-format fallback. */
export const CATALOG_PILL_TONE_CLASS: Readonly<Record<CatalogPillTone, string>> = {
  sky: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300',
  emerald: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  violet: 'bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300',
  pink: 'bg-pink-100 text-pink-800 dark:bg-pink-900/40 dark:text-pink-300',
  orange: 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300',
  slate: 'bg-slate-100 text-slate-800 dark:bg-slate-800/60 dark:text-slate-300',
  amber: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  red: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
  blue: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  cyan: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900/40 dark:text-cyan-300',
  indigo: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300',
  teal: 'bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300',
  lime: 'bg-lime-100 text-lime-800 dark:bg-lime-900/40 dark:text-lime-300',
  stone: 'bg-stone-100 text-stone-800 dark:bg-stone-800/60 dark:text-stone-300',
  neutral: 'bg-gray-100 text-gray-700 dark:bg-gray-700/60 dark:text-gray-300',
};

/** Normalise a raw token to a comparison key: lower-case, alphanumerics only (drops version/spacing). */
function normalizeToken(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, '');
}

// ==================== Formats ====================

/** A single registered import format (icon + tone + display label). */
export interface CatalogFormat {
  /** Canonical id (lower-case, alphanumeric) used as the registry key. */
  id: string;
  /** Human-friendly display label (e.g. `OpenAPI`, `gRPC`). */
  label: string;
  /** The lucide icon shown in the pill. */
  icon: LucideIcon;
  /** The pill tint. */
  tone: CatalogPillTone;
  /**
   * Extra normalised aliases that also resolve to this entry (the canonical `id` is always matched
   * without being repeated here). Versioned/spelled variants (e.g. `openapi30`, `protobuf`).
   */
  aliases?: readonly string[];
}

/**
 * The known import formats. Drawn from the formats the import adapters declare and the
 * `ApiParadigm` doc comments (OpenAPI/Swagger/RAML/OData/API-Blueprint/WSDL for REST,
 * gRPC/Smithy/Thrift for RPC, AsyncAPI/CloudEvents for event, GraphQL for graph,
 * Avro/JSON-Schema/Protobuf/XSD for data-schema). New formats append here; unknown formats fall
 * back to a neutral pill via {@link resolveCatalogFormat}.
 */
export const CATALOG_FORMATS: readonly CatalogFormat[] = [
  { id: 'openapi', label: 'OpenAPI', icon: FileJson, tone: 'sky', aliases: ['openapi30', 'openapi31', 'oas', 'oas3'] },
  { id: 'swagger', label: 'Swagger', icon: FileJson, tone: 'teal', aliases: ['swagger20', 'oas2'] },
  { id: 'grpc', label: 'gRPC', icon: Network, tone: 'emerald', aliases: ['protobufservice'] },
  { id: 'graphql', label: 'GraphQL', icon: Share2, tone: 'pink', aliases: ['gql', 'sdl'] },
  { id: 'asyncapi', label: 'AsyncAPI', icon: Radio, tone: 'violet', aliases: ['async'] },
  { id: 'cloudevents', label: 'CloudEvents', icon: Cloud, tone: 'sky' },
  { id: 'odata', label: 'OData', icon: Database, tone: 'orange', aliases: ['edmx'] },
  { id: 'wsdl', label: 'WSDL', icon: FileCode, tone: 'slate', aliases: ['soap'] },
  { id: 'smithy', label: 'Smithy', icon: Hammer, tone: 'amber' },
  { id: 'thrift', label: 'Thrift', icon: Network, tone: 'lime' },
  { id: 'raml', label: 'RAML', icon: BookMarked, tone: 'red' },
  { id: 'apiblueprint', label: 'API Blueprint', icon: FileText, tone: 'blue', aliases: ['blueprint', 'apib'] },
  { id: 'avro', label: 'Avro', icon: Binary, tone: 'cyan', aliases: ['avsc'] },
  { id: 'protobuf', label: 'Protobuf', icon: Binary, tone: 'teal', aliases: ['proto', 'proto3'] },
  { id: 'jsonschema', label: 'JSON Schema', icon: Braces, tone: 'indigo', aliases: ['json'] },
  { id: 'xsd', label: 'XSD', icon: FileCode, tone: 'stone', aliases: ['xmlschema'] },
] as const;

/** Build the alias→entry lookup once (canonical id plus every declared alias). */
const FORMAT_BY_KEY: ReadonlyMap<string, CatalogFormat> = (() => {
  const map = new Map<string, CatalogFormat>();
  for (const fmt of CATALOG_FORMATS) {
    map.set(fmt.id, fmt);
    for (const alias of fmt.aliases ?? []) map.set(normalizeToken(alias), fmt);
  }
  return map;
})();

/**
 * Resolve a raw `sourceFormat` string to a registered {@link CatalogFormat}.
 *
 * Matching is version-insensitive: `openapi-3.1`, `OpenAPI 3.0` and `openapi` all resolve to the
 * OpenAPI entry. The raw token is also tried with a trailing version segment stripped (so
 * `swagger-2.0` → `swagger`).
 *
 * @param format The raw format string off the item, or null/undefined.
 * @returns The matching registry entry, or `undefined` when the format is empty or unrecognised
 *   (callers render a neutral pill for the unrecognised-but-present case).
 */
export function resolveCatalogFormat(format: string | null | undefined): CatalogFormat | undefined {
  if (!format || !format.trim()) return undefined;
  const key = normalizeToken(format);
  if (FORMAT_BY_KEY.has(key)) return FORMAT_BY_KEY.get(key);
  // Try the leading non-numeric portion, so `openapi30` / `swagger20` match `openapi` / `swagger`.
  const leading = key.replace(/[0-9].*$/, '');
  if (leading && leading !== key && FORMAT_BY_KEY.has(leading)) return FORMAT_BY_KEY.get(leading);
  return undefined;
}

// ==================== Protocols (paradigms) ====================

/** A single API paradigm / protocol family (the canonical `ApiParadigm`, plus `agent`). */
export interface CatalogProtocol {
  /** Canonical id (lower-case, alphanumeric). */
  id: string;
  /** Display label (e.g. `REST`, `Data Schema`). */
  label: string;
  /** The lucide icon shown in the pill. */
  icon: LucideIcon;
  /** The pill tint. */
  tone: CatalogPillTone;
  /** Extra normalised aliases that resolve here (the canonical id is always matched). */
  aliases?: readonly string[];
}

/**
 * The protocols a catalog item can declare — the canonical `ApiParadigm` (REST / RPC / event /
 * graph / data-schema) plus `agent` (MCP-style agent surfaces). Unknown protocols degrade to a
 * neutral pill via {@link resolveCatalogProtocol}.
 */
export const CATALOG_PROTOCOLS: readonly CatalogProtocol[] = [
  { id: 'rest', label: 'REST', icon: Network, tone: 'indigo' },
  { id: 'rpc', label: 'RPC', icon: Workflow, tone: 'emerald' },
  { id: 'event', label: 'Event', icon: Radio, tone: 'violet', aliases: ['events', 'messaging'] },
  { id: 'graph', label: 'Graph', icon: Share2, tone: 'pink', aliases: ['graphql'] },
  { id: 'dataschema', label: 'Data Schema', icon: Braces, tone: 'cyan', aliases: ['dataschemas', 'schema', 'data'] },
  { id: 'agent', label: 'Agent', icon: Bot, tone: 'amber', aliases: ['mcp', 'agentic'] },
] as const;

/** Build the alias→entry lookup once (canonical id plus every declared alias). */
const PROTOCOL_BY_KEY: ReadonlyMap<string, CatalogProtocol> = (() => {
  const map = new Map<string, CatalogProtocol>();
  for (const proto of CATALOG_PROTOCOLS) {
    map.set(proto.id, proto);
    for (const alias of proto.aliases ?? []) map.set(normalizeToken(alias), proto);
  }
  return map;
})();

/**
 * Resolve a raw `protocol` / paradigm string to a registered {@link CatalogProtocol}.
 *
 * Matching is punctuation-insensitive, so `data_schema`, `data-schema` and `dataschema` all resolve
 * to the Data Schema entry.
 *
 * @param protocol The raw protocol string off the item, or null/undefined.
 * @returns The matching registry entry, or `undefined` when empty or unrecognised.
 */
export function resolveCatalogProtocol(protocol: string | null | undefined): CatalogProtocol | undefined {
  if (!protocol || !protocol.trim()) return undefined;
  return PROTOCOL_BY_KEY.get(normalizeToken(protocol));
}

// ==================== Source material ====================

/** The input kind a catalog item was imported from (mirrors the REST `InputKind` enum). */
export type CatalogSourceKind = 'file' | 'url' | 'paste' | 'discovery';

/** Display metadata for a source kind: a fallback label and the icon for its input kind. */
export interface CatalogSourceKindMeta {
  kind: CatalogSourceKind;
  /** Label used when the item carries no specific source label. */
  fallbackLabel: string;
  icon: LucideIcon;
}

/** Per-kind icon + fallback label. The discovery kind is the live-introspection case. */
export const CATALOG_SOURCE_KIND_META: Readonly<Record<CatalogSourceKind, CatalogSourceKindMeta>> = {
  file: { kind: 'file', fallbackLabel: 'Uploaded file', icon: Upload },
  url: { kind: 'url', fallbackLabel: 'Source URL', icon: Link2 },
  paste: { kind: 'paste', fallbackLabel: 'Pasted content', icon: ClipboardPaste },
  discovery: { kind: 'discovery', fallbackLabel: 'Live discovery', icon: Radar },
};

/** A resolved source-material descriptor: an input kind and a human label to show on the badge. */
export interface CatalogSource {
  kind: CatalogSourceKind;
  /** The label to display (file name / URL host / "Live discovery"). */
  label: string;
  /** The full, untruncated source value (file name or URL) for a tooltip; may equal `label`. */
  title: string;
}

/** Normalise a raw input-kind token to a {@link CatalogSourceKind}, or undefined when unknown. */
function normalizeSourceKind(value: string | null | undefined): CatalogSourceKind | undefined {
  if (!value) return undefined;
  const key = normalizeToken(value);
  if (key === 'file' || key === 'upload') return 'file';
  if (key === 'url' || key === 'uri' || key === 'link') return 'url';
  if (key === 'paste' || key === 'clipboard' || key === 'pasted' || key === 'inline') return 'paste';
  if (key === 'discovery' || key === 'livediscovery' || key === 'live' || key === 'endpoint') return 'discovery';
  return undefined;
}

/** Reduce a URL to a compact host (+path head) label; returns the raw string if it does not parse. */
function compactUrlLabel(raw: string): string {
  try {
    const u = new URL(raw);
    return u.host + (u.pathname && u.pathname !== '/' ? u.pathname : '');
  } catch {
    return raw;
  }
}

/** The candidate keys, in priority order, that may carry the source label across metadata shapes. */
const SOURCE_LABEL_KEYS = ['sourceLabel', 'source_label', 'sourceUri', 'source_uri', 'sourceUrl', 'source_url', 'fileName', 'file_name', 'filename'] as const;
/** The candidate keys, in priority order, that may carry the input kind across metadata shapes. */
const SOURCE_KIND_KEYS = ['inputKind', 'input_kind', 'sourceKind', 'source_kind'] as const;

/** Read the first present, non-empty string value among `keys` from a loose metadata bag. */
function firstString(bag: Record<string, unknown> | null | undefined, keys: readonly string[]): string | undefined {
  if (!bag) return undefined;
  for (const k of keys) {
    const v = bag[k];
    if (typeof v === 'string' && v.trim()) return v.trim();
  }
  return undefined;
}

/**
 * Derive the source-material descriptor for a catalog item from its loose metadata bags.
 *
 * The import path records source provenance onto the item's `formatMetadata` (preferred) or generic
 * `metadata` (MFI-7.x). This reads the kind (`inputKind`/`input_kind`/…) and a label
 * (`sourceLabel`/`sourceUri`/`fileName`/…) from either bag — tolerating both camelCase and
 * snake_case — and produces a compact, display-ready {@link CatalogSource}. When no kind is
 * recorded it is inferred from the label (a parseable `http(s)` URL → `url`, otherwise `file`).
 *
 * @param formatMetadata The item's `formatMetadata` bag (preferred source of provenance).
 * @param metadata The item's generic `metadata` bag (fallback).
 * @returns The resolved source, or `undefined` when no source material is recorded (badge hidden).
 */
export function resolveCatalogSource(
  formatMetadata: Record<string, unknown> | null | undefined,
  metadata: Record<string, unknown> | null | undefined,
): CatalogSource | undefined {
  const rawLabel = firstString(formatMetadata, SOURCE_LABEL_KEYS) ?? firstString(metadata, SOURCE_LABEL_KEYS);
  const rawKind = firstString(formatMetadata, SOURCE_KIND_KEYS) ?? firstString(metadata, SOURCE_KIND_KEYS);

  let kind = normalizeSourceKind(rawKind);

  // Infer the kind from the label when none was recorded.
  if (!kind) {
    if (!rawLabel) return undefined;
    kind = /^https?:\/\//i.test(rawLabel) ? 'url' : 'file';
  }

  // Discovery without a label still renders (it is meaningful on its own).
  if (!rawLabel) {
    if (kind === 'discovery') {
      const meta = CATALOG_SOURCE_KIND_META[kind];
      return { kind, label: meta.fallbackLabel, title: meta.fallbackLabel };
    }
    return undefined;
  }

  const label = kind === 'url' ? compactUrlLabel(rawLabel) : rawLabel;
  return { kind, label, title: rawLabel };
}
