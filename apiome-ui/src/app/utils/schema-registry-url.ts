/**
 * Confluent Schema Registry support for the catalog importer's URL intake (MFI-12.6, #3787).
 *
 * A Confluent-compatible registry answers its subject and schema routes with a JSON **envelope** —
 * `{"subject", "version", "id", "schema": "<escaped schema text>"}` — not with the schema itself,
 * and lists a subject's versions as `[1, 2, 3]`. Each schema's raw text is served at a sibling
 * route ending in `/schema`. When the URL a user enters returns one of those responses, the
 * importer follows it to the raw schema and imports that instead, so a registry URL works in the
 * wizard the same way it does for `apiome import avro --registry`.
 *
 * | URL entered                                 | Followed to                                  |
 * | ------------------------------------------- | -------------------------------------------- |
 * | `…/subjects/<subject>/versions/<version>`   | `…/subjects/<subject>/versions/<version>/schema` |
 * | `…/subjects/<subject>/versions`             | `…/subjects/<subject>/versions/latest/schema` |
 * | `…/schemas/ids/<id>`                        | `…/schemas/ids/<id>/schema`                  |
 *
 * The raw-schema routes are the ones the CLI (`apiome_cli.import_.avro_registry`) reads. Only Avro
 * envelopes are followed: Confluent omits `schemaType` for Avro, so an envelope naming `JSON` or
 * `PROTOBUF` is left as it is.
 */

/** `…/subjects/<subject>/versions` or `…/subjects/<subject>/versions/<version>`. */
const SUBJECT_VERSION_PATH = /\/subjects\/[^/]+\/versions(?:\/([^/]+))?$/;

/** `…/schemas/ids/<id>`. */
const SCHEMA_ID_PATH = /\/schemas\/ids\/\d+$/;

/**
 * Whether a parsed JSON value is a registry schema envelope for an Avro schema.
 *
 * @param document The parsed response body.
 * @returns `true` when it carries the schema as a string and is (or defaults to) `AVRO`.
 */
function isAvroEnvelope(document: unknown): boolean {
  if (!document || typeof document !== 'object' || Array.isArray(document)) return false;
  const record = document as Record<string, unknown>;
  if (typeof record.schema !== 'string') return false;
  const schemaType = record.schemaType;
  return schemaType === undefined || schemaType === null || schemaType === 'AVRO';
}

/**
 * Whether a parsed JSON value is a registry version list (`[1, 2, 3]`).
 *
 * @param document The parsed response body.
 * @returns `true` for a non-empty array of positive integers.
 */
function isVersionList(document: unknown): boolean {
  return (
    Array.isArray(document) &&
    document.length > 0 &&
    document.every((entry) => Number.isInteger(entry) && (entry as number) > 0)
  );
}

/**
 * When a fetched URL answered with a schema-registry response, the raw-schema URL to import instead.
 *
 * Both the path and the body must match, so an unrelated API that happens to use `/subjects/` or
 * to answer with a `schema` string is imported as it is.
 *
 * @param url The URL that was fetched.
 * @param text The response body.
 * @returns The raw-schema URL (query string kept, fragment dropped), or `null` when the response is
 *   not a registry envelope or version list for that path.
 */
export function schemaRegistryRawSchemaUrl(url: string, text: string): string | null {
  const trimmed = (text ?? '').trimStart();
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return null;
  let parsed: URL;
  let document: unknown;
  try {
    parsed = new URL((url ?? '').trim());
    document = JSON.parse(trimmed);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
  const path = parsed.pathname.replace(/\/+$/, '');

  const subjectMatch = SUBJECT_VERSION_PATH.exec(path);
  if (subjectMatch) {
    const version = subjectMatch[1];
    if (version === undefined) {
      if (!isVersionList(document)) return null;
      parsed.pathname = `${path}/latest/schema`;
    } else {
      if (!isAvroEnvelope(document)) return null;
      parsed.pathname = `${path}/schema`;
    }
  } else if (SCHEMA_ID_PATH.test(path)) {
    if (!isAvroEnvelope(document)) return null;
    parsed.pathname = `${path}/schema`;
  } else {
    return null;
  }
  parsed.hash = '';
  return parsed.toString();
}
