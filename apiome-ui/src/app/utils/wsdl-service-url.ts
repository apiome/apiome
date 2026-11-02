/**
 * SOAP service support for the catalog importer's URL intake (MFI-13.6, #3793).
 *
 * A SOAP service publishes its description at its endpoint with a query: `?wsdl` on every stack,
 * and on WCF also `?singleWsdl` — the same description with every `wsdl:import` and `xs:import`
 * already inlined. A browser fetch of `?wsdl` gets only the root document, so a description split
 * across `?wsdl=wsdl0` / `?xsd=xsd0` would arrive without its types. When the URL a user enters is a
 * SOAP description URL, the importer therefore tries `?singleWsdl` first and falls back to `?wsdl`,
 * the way `apiome import wsdl --discover` does (`apiome_cli.import_.wsdl.wsdl_candidate_urls`).
 *
 * Only URLs that are plainly SOAP are rewritten, so every other URL import is fetched as entered:
 *
 * | URL entered                         | Tried, in order                     |
 * | ----------------------------------- | ----------------------------------- |
 * | `…/Calculator.svc?wsdl`             | `…?singleWsdl`, then `…?wsdl`       |
 * | `…/Calculator.svc` or `…/Service.asmx` | `…?singleWsdl`, then `…?wsdl`    |
 * | `…?singleWsdl`, `…/calc.wsdl`, anything else | the URL as entered         |
 */

/** The query keys that select a description, compared case-insensitively. */
const WSDL_KEYS = new Set(['wsdl', 'singlewsdl']);

/** Endpoint suffixes of the SOAP stacks that answer `?wsdl` (WCF `.svc`, ASMX `.asmx`). */
const SOAP_ENDPOINT = /\.(svc|asmx)$/i;

/** Root elements of a WSDL 1.1 or 2.0 description, as the CLI's `_is_wsdl` matches them. */
const WSDL_ROOTS = ['<wsdl:definitions', '<definitions', '<wsdl:description', '<description'];

/**
 * `url` with its description query (`wsdl` / `singleWsdl`) replaced by `key`.
 *
 * @param url The parsed URL; not mutated.
 * @param key `singleWsdl` or `wsdl`.
 * @returns The rewritten URL, other query parameters kept in order, fragment dropped.
 */
function withDescriptionQuery(url: URL, key: string): string {
  const kept = [...url.searchParams.entries()].filter(([name]) => !WSDL_KEYS.has(name.toLowerCase()));
  const query = [new URLSearchParams(kept).toString(), key].filter(Boolean).join('&');
  return `${url.origin}${url.pathname}?${query}`;
}

/**
 * The description URLs to try for a SOAP service URL, best first.
 *
 * @param serviceUrl The URL the user entered.
 * @returns `[…?singleWsdl, …?wsdl]` for a `?wsdl` URL or a bare `.svc` / `.asmx` endpoint; `null`
 *   for any other URL (including `?singleWsdl`, which is already the inlined description), which is
 *   fetched as entered.
 */
export function wsdlCandidateUrls(serviceUrl: string): string[] | null {
  let parsed: URL;
  try {
    parsed = new URL((serviceUrl ?? '').trim());
  } catch {
    return null;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
  const keys = new Set([...parsed.searchParams.keys()].map((key) => key.toLowerCase()));
  if (keys.has('singlewsdl')) return null;
  const isWsdlQuery = keys.has('wsdl');
  const isBareEndpoint = !parsed.search && SOAP_ENDPOINT.test(parsed.pathname);
  if (!isWsdlQuery && !isBareEndpoint) return null;
  return [withDescriptionQuery(parsed, 'singleWsdl'), withDescriptionQuery(parsed, 'wsdl')];
}

/**
 * Whether a response body is a WSDL description (1.1 or 2.0).
 *
 * Only the head of the text is inspected, so a large or hostile body costs nothing.
 *
 * @param text The response body.
 * @returns `true` when a WSDL root element appears in its first 4 KB.
 */
export function isWsdlText(text: string): boolean {
  const head = (text ?? '').slice(0, 4096);
  return WSDL_ROOTS.some((root) => head.includes(root));
}

/**
 * Find a SOAP service's description among its candidate URLs.
 *
 * A candidate that fails to fetch (a non-WCF service answers `?singleWsdl` with 400 or 404) or that
 * answers with something other than WSDL (an HTML help page) is skipped.
 *
 * @param serviceUrl The URL the user entered.
 * @param fetchText Fetches a URL's body as text; throws for a failed request.
 * @returns The first candidate that answered with WSDL and its text, or `null` when the URL is not
 *   a SOAP description URL or no candidate answered with WSDL (the caller then fetches the URL as
 *   entered, so its error is the one reported).
 */
export async function fetchWsdlDescription(
  serviceUrl: string,
  fetchText: (url: string) => Promise<string>,
): Promise<{ url: string; text: string } | null> {
  const candidates = wsdlCandidateUrls(serviceUrl);
  if (!candidates) return null;
  for (const candidate of candidates) {
    try {
      const text = await fetchText(candidate);
      if (isWsdlText(text)) return { url: candidate, text };
    } catch {
      // Try the next candidate; a service that offers neither is fetched as entered by the caller.
    }
  }
  return null;
}
