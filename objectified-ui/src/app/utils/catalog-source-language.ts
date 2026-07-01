/**
 * Catalog source-format → Monaco editor language mapping (MFI-25.4, #4089).
 *
 * The catalog detail's Source & Code tab renders a catalog item's *raw imported source* read-only in
 * Monaco. Monaco needs a language id to drive syntax highlighting; a catalog item only carries its
 * canonical `sourceFormat` (e.g. `grpc`, `graphql`, `openapi-3.1`). This module is the single,
 * data-driven bridge between the two — a pure function so it can be unit-tested without rendering the
 * editor, mirroring the pure-resolver style of {@link catalog-format-registry}.
 *
 * The mapping resolves the raw format through the format registry (so version/alias variants collapse
 * to a canonical id) and then looks up the Monaco language. Two formats are genuinely ambiguous on the
 * wire — OpenAPI/Swagger/AsyncAPI/Arazzo/RAML are authored as *either* JSON or YAML — so when a sample
 * of the fetched bytes is available the language is refined by sniffing the first non-blank character.
 * Everything degrades to `'plaintext'`, never throwing, so an unrecognised format still renders.
 */

import { resolveCatalogFormat } from './catalog-format-registry';

/**
 * The Monaco language id per canonical registry format id. Formats Monaco has no grammar for (Thrift,
 * ASN.1, COBOL copybooks, …) map to `plaintext` so the raw text still renders with line numbers.
 */
const FORMAT_LANGUAGE: Readonly<Record<string, string>> = {
  // Graph
  graphql: 'graphql',
  // RPC / binary IDLs
  grpc: 'protobuf',
  protobuf: 'protobuf',
  connectrpc: 'protobuf',
  capnproto: 'plaintext',
  flatbuffers: 'plaintext',
  thrift: 'plaintext',
  corbaidl: 'plaintext',
  oncrpc: 'plaintext',
  openrpc: 'json',
  xmlrpc: 'xml',
  // REST / event (JSON-or-YAML on the wire — refined by {@link sniffStructuredLanguage})
  openapi: 'yaml',
  swagger: 'yaml',
  asyncapi: 'yaml',
  arazzo: 'yaml',
  raml: 'yaml',
  // REST (fixed serialization)
  postman: 'json',
  odata: 'xml',
  wsdl: 'xml',
  wadl: 'xml',
  apiblueprint: 'markdown',
  smithy: 'plaintext',
  typespec: 'typescript',
  cloudevents: 'json',
  // Data schema
  jsonschema: 'json',
  jtd: 'json',
  avro: 'json',
  xsd: 'xml',
  asn1: 'plaintext',
  cobolcopybook: 'plaintext',
  // Healthcare / finance / mainframe
  fhir: 'json',
  hl7v2: 'plaintext',
  edix12: 'plaintext',
  iso20022: 'xml',
  iso8583: 'plaintext',
  fix: 'plaintext',
  zosconnect: 'json',
};

/** Formats authored as *either* JSON or YAML — their language is refined from the actual bytes. */
const JSON_OR_YAML_FORMATS: ReadonlySet<string> = new Set([
  'openapi',
  'swagger',
  'asyncapi',
  'arazzo',
  'raml',
]);

/**
 * Sniff a Monaco language from the first non-blank character of a raw source sample: an object/array
 * opener (`{`/`[`) is JSON, an angle bracket (`<`) is XML. Returns `undefined` when the sample is
 * empty or inconclusive (e.g. YAML, whose leading token is indistinguishable), so the caller keeps
 * its format-derived default.
 */
function sniffStructuredLanguage(rawSample: string | null | undefined): string | undefined {
  if (!rawSample) return undefined;
  const trimmed = rawSample.trimStart();
  if (!trimmed) return undefined;
  const first = trimmed[0];
  if (first === '{' || first === '[') return 'json';
  if (first === '<') return 'xml';
  return undefined;
}

/**
 * Resolve the Monaco editor language for a catalog item's raw source.
 *
 * @param sourceFormat The item's raw `sourceFormat` (any alias/version), or null/undefined.
 * @param rawSample An optional sample of the fetched source used to disambiguate JSON-or-YAML formats
 *   and to type otherwise-unknown formats; omit it (e.g. before the source has loaded) to get the
 *   format's static default.
 * @returns A Monaco language id (e.g. `graphql`, `protobuf`, `json`, `yaml`, `xml`), defaulting to
 *   `'plaintext'` for unrecognised or grammar-less formats.
 */
export function monacoLanguageForCatalogFormat(
  sourceFormat: string | null | undefined,
  rawSample?: string | null,
): string {
  const format = resolveCatalogFormat(sourceFormat);

  // Unknown-but-present (or absent) format: fall back to sniffing the bytes, else plaintext.
  if (!format) {
    return sniffStructuredLanguage(rawSample) ?? 'plaintext';
  }

  const base = FORMAT_LANGUAGE[format.id] ?? 'plaintext';

  // JSON-or-YAML formats: trust the bytes over the (arbitrary) YAML default when they're conclusive.
  if (JSON_OR_YAML_FORMATS.has(format.id)) {
    const sniffed = sniffStructuredLanguage(rawSample);
    if (sniffed) return sniffed;
  }

  return base;
}
