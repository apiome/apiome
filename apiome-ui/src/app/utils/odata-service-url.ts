/**
 * OData service-root support for the catalog importer's URL intake (MFI-11.6, #3781).
 *
 * An OData service publishes its model at `<service root>/$metadata`; its root answers with a
 * **service document** that lists the entity sets but carries no model. When the URL a user enters
 * returns a service document, the importer follows it to `$metadata` and imports that instead, so a
 * service root works in the wizard the same way it does for `apiome import odata --discover`.
 *
 * The URL rules mirror the CLI (`apiome_cli.import_.odata.odata_metadata_url`) and the REST
 * adapter's live discovery (`app.odata_discovery.service_urls`): a trailing `/` or `/$metadata` is
 * dropped from the path, `/$metadata` is appended, and the query string (SAP's `sap-client=100`) is
 * kept.
 */

const METADATA = '$metadata';

/** The AtomPub namespace a v2 / v3 XML service document's `<service>` root is declared in. */
const ATOM_PUB_NS = 'http://www.w3.org/2007/app';

/**
 * Return the `$metadata` URL for an OData service root (or its `$metadata` URL).
 *
 * @param serviceUrl The service root (`https://host/odata/trippin/`) or its `$metadata` URL.
 * @returns `<service root>/$metadata`, query string kept, fragment dropped; `null` when the URL is
 *   not an absolute `http` / `https` URL.
 */
export function odataMetadataUrl(serviceUrl: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL((serviceUrl ?? '').trim());
  } catch {
    return null;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
  let path = parsed.pathname.replace(/\/+$/, '');
  if (path.endsWith(`/${METADATA}`)) {
    path = path.slice(0, -METADATA.length).replace(/\/+$/, '');
  }
  parsed.pathname = `${path}/${METADATA}`;
  parsed.hash = '';
  // `URL` percent-encodes nothing in `$metadata`, so the result reads as the user would write it.
  return parsed.toString();
}

/**
 * Whether a JSON value is an OData service document.
 *
 * - **v4**: `{"@odata.context": ".../$metadata", "value": [...]}`.
 * - **v3 (JSON light)**: `{"odata.metadata": ".../$metadata", "value": [...]}`.
 * - **v2 / v3 (verbose)**: `{"d": {"EntitySets": [...]}}`.
 *
 * A bare `{"value": [...]}` is **not** enough — plenty of non-OData APIs answer that way — so a v4 or
 * v3 light document must also name its metadata context.
 *
 * @param document The parsed JSON.
 * @returns `true` for a service document of any version.
 */
function isJsonServiceDocument(document: unknown): boolean {
  if (!document || typeof document !== 'object' || Array.isArray(document)) return false;
  const record = document as Record<string, unknown>;
  if (Array.isArray(record.value)) {
    const context = record['@odata.context'] ?? record['odata.metadata'];
    return typeof context === 'string' && context.includes(METADATA);
  }
  const verbose = record.d;
  return (
    !!verbose &&
    typeof verbose === 'object' &&
    Array.isArray((verbose as Record<string, unknown>).EntitySets)
  );
}

/**
 * Whether XML text is an AtomPub service document (`<service xmlns="http://www.w3.org/2007/app">`),
 * the XML service document of OData v2 and v3.
 *
 * Only the root element is inspected, by pattern rather than by parsing, so hostile or very large
 * text costs nothing; EDMX metadata (`<edmx:Edmx>`) never matches.
 *
 * @param text The response body.
 * @returns `true` when the root element is an AtomPub `service`.
 */
function isAtomServiceDocument(text: string): boolean {
  const head = text.slice(0, 4096);
  const root = /<(?!\?|!)([A-Za-z_][\w.-]*:)?([A-Za-z_][\w.-]*)\b[^>]*>/.exec(head);
  if (!root || root[2] !== 'service') return false;
  return root[0].includes(ATOM_PUB_NS);
}

/**
 * When a fetched URL answered with an OData service document, the `$metadata` URL to import instead.
 *
 * @param url The URL that was fetched.
 * @param text The response body.
 * @returns The `$metadata` URL for the service, or `null` when the body is not a service document
 *   (it is imported as it is).
 */
export function odataMetadataUrlForServiceDocument(url: string, text: string): string | null {
  const trimmed = (text ?? '').trimStart();
  let isServiceDocument = false;
  if (trimmed.startsWith('{')) {
    try {
      isServiceDocument = isJsonServiceDocument(JSON.parse(trimmed));
    } catch {
      return null;
    }
  } else if (trimmed.startsWith('<')) {
    isServiceDocument = isAtomServiceDocument(trimmed);
  }
  if (!isServiceDocument) return null;
  const metadataUrl = odataMetadataUrl(url);
  // A service document fetched from its own `$metadata` URL would loop; import what came back.
  if (!metadataUrl || new URL(url.trim()).pathname.replace(/\/+$/, '').endsWith(`/${METADATA}`)) {
    return null;
  }
  return metadataUrl;
}
