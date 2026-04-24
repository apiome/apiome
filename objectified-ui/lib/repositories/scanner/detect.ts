export const SNIFF_MAX_BYTES = 64 * 1024;
export const STREAMING_SNIFF_THRESHOLD_BYTES = 5 * 1024 * 1024;

export type DetectedRepositorySpecFormat =
  | "openapi_3_0"
  | "openapi_3_1"
  | "swagger_2_0"
  | "asyncapi_2"
  | "asyncapi_3"
  | "arazzo_1"
  | "json_schema"
  | "graphql_sdl"
  | "protobuf"
  | "avro"
  | "unknown_spec";

export interface DetectRepositorySpecResult {
  format: DetectedRepositorySpecFormat;
  confidence: number;
  discriminator: string;
}

type SniffMode = "buffer" | "stream";
type SniffChunk = string | Uint8Array;
type SniffSource = string | Uint8Array | AsyncIterable<SniffChunk> | ReadableStream<Uint8Array>;

export interface DetectRepositorySpecInput {
  path: string;
  sizeBytes: number;
  readSnippet: (opts: { maxBytes: number; mode: SniffMode }) => Promise<SniffSource>;
}

interface DetectionEvidence {
  format: Exclude<DetectedRepositorySpecFormat, "unknown_spec">;
  confidence: number;
  discriminator: string;
}

type DetectionCandidate = Exclude<DetectedRepositorySpecFormat, "unknown_spec">;

const DIRECT_EXTENSION_FORMATS: Array<{
  regex: RegExp;
  format: DetectionCandidate;
}> = [
  { regex: /\.graphql$/i, format: "graphql_sdl" },
  { regex: /\.gql$/i, format: "graphql_sdl" },
  { regex: /\.proto$/i, format: "protobuf" },
  { regex: /\.avsc$/i, format: "avro" },
];

const OPENAPI_FILENAME_RE = /(openapi|swagger|oas)[^/]*(\.ya?ml|\.json)?$/i;
const ASYNCAPI_FILENAME_RE = /asyncapi[^/]*(\.ya?ml|\.json)?$/i;
const ARAZZO_FILENAME_RE = /arazzo[^/]*(\.ya?ml|\.json)?$/i;
const JSON_OR_YAML_RE = /\.(json|ya?ml)$/i;
const GRAPHQL_BLOCK_RE = /\b(?:schema\s*\{[\s\S]*?\}|type\s+query\b[\s\S]*?\})/i;

export async function detectRepositorySpecFormat(
  input: DetectRepositorySpecInput
): Promise<DetectRepositorySpecResult> {
  const phaseA = phaseAFilenameHeuristics(input.path);
  const mode: SniffMode = input.sizeBytes > STREAMING_SNIFF_THRESHOLD_BYTES ? "stream" : "buffer";
  const source = await input.readSnippet({ maxBytes: SNIFF_MAX_BYTES, mode });
  const sniffText = await readAtMost(source, SNIFF_MAX_BYTES);
  const phaseB = phaseBContentSniff(sniffText);
  const strongest = chooseBestEvidence(phaseA, phaseB);

  if (strongest) {
    return strongest;
  }

  return {
    format: "unknown_spec",
    confidence: 0.05,
    discriminator: "no_known_discriminator",
  };
}

function phaseAFilenameHeuristics(path: string): Set<DetectionCandidate> {
  const normalized = path.toLowerCase();
  const candidates = new Set<DetectionCandidate>();

  for (const item of DIRECT_EXTENSION_FORMATS) {
    if (item.regex.test(normalized)) {
      candidates.add(item.format);
    }
  }

  if (OPENAPI_FILENAME_RE.test(normalized)) {
    candidates.add("openapi_3_0");
    candidates.add("openapi_3_1");
    candidates.add("swagger_2_0");
  }

  if (ASYNCAPI_FILENAME_RE.test(normalized)) {
    candidates.add("asyncapi_2");
    candidates.add("asyncapi_3");
  }

  if (ARAZZO_FILENAME_RE.test(normalized)) {
    candidates.add("arazzo_1");
  }

  if (JSON_OR_YAML_RE.test(normalized)) {
    candidates.add("openapi_3_0");
    candidates.add("openapi_3_1");
    candidates.add("swagger_2_0");
    candidates.add("asyncapi_2");
    candidates.add("asyncapi_3");
    candidates.add("arazzo_1");
    candidates.add("json_schema");
    candidates.add("avro");
  }

  return candidates;
}

function phaseBContentSniff(content: string): DetectionEvidence[] {
  const evidences: DetectionEvidence[] = [];
  const lower = content.toLowerCase();
  const trimmed = content.trim();

  const openapi31 = matchVersionedField(content, "openapi", /^3\.1(?:\.\d+)?$/);
  if (openapi31) {
    evidences.push({
      format: "openapi_3_1",
      confidence: 0.98,
      discriminator: `openapi:${openapi31}`,
    });
  }

  const openapi30 = matchVersionedField(content, "openapi", /^3\.0(?:\.\d+)?$/);
  if (openapi30) {
    evidences.push({
      format: "openapi_3_0",
      confidence: 0.98,
      discriminator: `openapi:${openapi30}`,
    });
  }

  const swagger20 = matchVersionedField(content, "swagger", /^2\.0$/);
  if (swagger20) {
    evidences.push({
      format: "swagger_2_0",
      confidence: 0.98,
      discriminator: `swagger:${swagger20}`,
    });
  }

  const async2 = matchVersionedField(content, "asyncapi", /^2(?:\.\d+)?(?:\.\d+)?$/);
  if (async2) {
    evidences.push({
      format: "asyncapi_2",
      confidence: 0.98,
      discriminator: `asyncapi:${async2}`,
    });
  }

  const async3 = matchVersionedField(content, "asyncapi", /^3(?:\.\d+)?(?:\.\d+)?$/);
  if (async3) {
    evidences.push({
      format: "asyncapi_3",
      confidence: 0.98,
      discriminator: `asyncapi:${async3}`,
    });
  }

  const arazzo1 = matchVersionedField(content, "arazzo", /^1(?:\.\d+)?(?:\.\d+)?$/);
  if (arazzo1) {
    evidences.push({
      format: "arazzo_1",
      confidence: 0.98,
      discriminator: `arazzo:${arazzo1}`,
    });
  }

  if (/^\s*syntax\s*=\s*"proto3"\s*;/m.test(content)) {
    evidences.push({
      format: "protobuf",
      confidence: 0.98,
      discriminator: 'line:syntax="proto3"',
    });
  }

  if (GRAPHQL_BLOCK_RE.test(trimmed)) {
    evidences.push({
      format: "graphql_sdl",
      confidence: 0.9,
      discriminator: trimmed.toLowerCase().startsWith("type query")
        ? "line:type Query"
        : "line:schema { ... }",
    });
  }

  if (looksLikeJsonSchema(content, lower)) {
    evidences.push({
      format: "json_schema",
      confidence: 0.88,
      discriminator: jsonSchemaDiscriminator(content, lower),
    });
  }

  if (looksLikeAvro(content)) {
    evidences.push({
      format: "avro",
      confidence: 0.9,
      discriminator: "json_keys:name+type+fields",
    });
  }

  return evidences;
}

function chooseBestEvidence(
  phaseA: Set<DetectionCandidate>,
  phaseB: DetectionEvidence[]
): DetectRepositorySpecResult | null {
  if (phaseB.length === 0) {
    return null;
  }

  const evidence =
    phaseA.size > 0 ? phaseB.filter((item) => phaseA.has(item.format)) : phaseB;
  if (evidence.length === 0) {
    return null;
  }

  evidence.sort((a, b) => b.confidence - a.confidence);
  const winner = evidence[0];
  if (!winner) {
    return null;
  }

  return {
    format: winner.format,
    confidence: Number(winner.confidence.toFixed(2)),
    discriminator: winner.discriminator,
  };
}

function looksLikeJsonSchema(content: string, lower: string): boolean {
  if (/"\$schema"\s*:\s*"[^"]*json-schema[^"]*"/i.test(content)) {
    return true;
  }
  if (/\$schema\s*:\s*["'][^"']*json-schema[^"']*["']/i.test(content)) {
    return true;
  }
  return /\btype\b/.test(lower) && /\bproperties\b/.test(lower);
}

function jsonSchemaDiscriminator(content: string, lower: string): string {
  if (/"\$schema"\s*:\s*"[^"]*json-schema[^"]*"/i.test(content)) {
    return "key:$schema(json-schema)";
  }
  if (/\$schema\s*:\s*["'][^"']*json-schema[^"']*["']/i.test(content)) {
    return "key:$schema(json-schema)";
  }
  if (/\btype\b/.test(lower) && /\bproperties\b/.test(lower)) {
    return "keys:type+properties";
  }
  return "json_schema_heuristic";
}

function looksLikeAvro(content: string): boolean {
  const hasName = /"name"\s*:\s*"[^"]+"/.test(content);
  const hasType = /"type"\s*:\s*"[^"]+"/.test(content);
  const hasFields = /"fields"\s*:\s*\[/.test(content);
  return hasName && hasType && hasFields;
}

function matchVersionedField(content: string, key: string, valuePattern: RegExp): string | null {
  const jsonPattern = new RegExp(`"${key}"\\s*:\\s*"([^"]+)"`, "i");
  const yamlPattern = new RegExp(`^\\s*${key}\\s*:\\s*["']?([^"'\\n#]+)["']?`, "im");
  const jsonMatch = content.match(jsonPattern);
  if (jsonMatch?.[1] && valuePattern.test(jsonMatch[1].trim())) {
    return jsonMatch[1].trim();
  }
  const yamlMatch = content.match(yamlPattern);
  if (yamlMatch?.[1] && valuePattern.test(yamlMatch[1].trim())) {
    return yamlMatch[1].trim();
  }
  return null;
}

async function readAtMost(source: SniffSource, maxBytes: number): Promise<string> {
  if (typeof source === "string") {
    return source.slice(0, maxBytes);
  }

  if (source instanceof Uint8Array) {
    return decodeUtf8(source.subarray(0, maxBytes));
  }

  if (isReadableStream(source)) {
    return readFromReadableStream(source, maxBytes);
  }

  return readFromAsyncIterable(source, maxBytes);
}

function isReadableStream(source: SniffSource): source is ReadableStream<Uint8Array> {
  return typeof source === "object" && source !== null && "getReader" in source;
}

async function readFromReadableStream(
  stream: ReadableStream<Uint8Array>,
  maxBytes: number
): Promise<string> {
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  let fullyConsumed = false;
  try {
    while (total < maxBytes) {
      const next = await reader.read();
      if (next.done) {
        fullyConsumed = true;
        break;
      }
      if (!next.value) {
        break;
      }
      const value = next.value;
      const take = Math.min(value.length, maxBytes - total);
      chunks.push(value.subarray(0, take));
      total += take;
    }
  } finally {
    if (fullyConsumed) {
      reader.releaseLock();
    } else {
      try {
        await reader.cancel();
      } catch {
        // Preserve existing behavior if cleanup fails.
      }
    }
  }
  return decodeUtf8(joinChunks(chunks, total));
}

async function readFromAsyncIterable(
  iterable: AsyncIterable<SniffChunk>,
  maxBytes: number
): Promise<string> {
  const chunks: Uint8Array[] = [];
  let total = 0;
  for await (const chunk of iterable) {
    if (total >= maxBytes) {
      break;
    }
    const bytes = typeof chunk === "string" ? new TextEncoder().encode(chunk) : chunk;
    const take = Math.min(bytes.length, maxBytes - total);
    chunks.push(bytes.subarray(0, take));
    total += take;
  }
  return decodeUtf8(joinChunks(chunks, total));
}

function joinChunks(chunks: Uint8Array[], totalBytes: number): Uint8Array {
  if (chunks.length === 1) {
    return chunks[0] ?? new Uint8Array(0);
  }
  const output = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.length;
  }
  return output;
}

function decodeUtf8(bytes: Uint8Array): string {
  return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
}
