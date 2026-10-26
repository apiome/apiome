---
title: "Import a HAR capture"
description: "Record traffic in devtools or a proxy and catalog the inferred REST API."
sidebar_position: 36
tags: [import, har, capture, traffic, devtools, inferred]
---

A **HAR** (HTTP Archive) file is what your browser's devtools or a debugging proxy saves when it
records traffic. The **HAR** importer (`har`) reads a capture into the [Catalog](./catalog.mdx) as a
**REST** API, one catalog item per host the page called. You can then search, version, diff and
convert it like any other catalog item.

A capture is a list of concrete requests, not a specification, so Apiome **infers** the API from the
traffic: `GET /v1/users/101` and `GET /v1/users/102` become one operation, `GET /v1/users/{id}`, and
the request and response bodies become schemas merged across every sample. It uses the same engine
as the cURL, `.http`, [Hoppscotch](./hoppscotch-import.md) and
[Thunder Client](./thunder-client-import.md) imports, and labels everything it builds **inferred**
(see [Declared, inferred and synthesized](./inference-provenance.mdx)). The format shows as
**HAR (inferred)** in the catalog.

## Record a capture

1. Open the app whose API you want to catalog.
2. Open your browser's devtools and select the **Network** tab. Turn on **Preserve log**, so the
   capture survives page loads.
3. Use the app: open the screens, create, edit and delete things. Every call you make becomes a
   sample, and more samples give better schemas.
4. Save the capture. In Chrome or Edge, select the **Export HAR** button, or right-click the request
   list and choose **Save all as HAR**. In Firefox, right-click the request list and choose
   **Save All As HAR**.

A debugging proxy (Charles, Fiddler, mitmproxy, Proxyman) exports HAR as well.

Apiome recognises a capture by its shape: a JSON object whose `log` holds an `entries` list. HAR 1.2
is what every current tool writes; HAR 1.1, and captures with no `log.version`, are read the same
way.

## Import it

Import the `.har` file like any other specification: in the [import wizard](./import-wizard.mdx),
with `apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)).
Apiome picks **HAR (inferred)** (`har`).

- **In the app:** in **Import to catalog**, choose the **HAR (inferred)** card (the activity icon),
  or upload the file on **File Upload** and let Apiome detect it.
- **From the CLI:** `apiome import har ./session.har`. Add `--dry-run` to preview without saving.

To import several recording sessions as one API, put the `.har` files in one archive (`.zip`,
`.tar.gz`) and import the archive: `apiome import har ./sessions.zip`.

## What is left out

A capture records the whole page load, not just the API. Apiome leaves out, and counts:

| Left out | How Apiome recognises it |
| --- | --- |
| **Page assets**: the HTML document, scripts, stylesheets, fonts, images, media, manifests, source maps | The browser's resource type, the file extension (`.js`, `.css`, `.woff2` …) or the response media type (`text/html`, `image/*` …) |
| **Analytics and monitoring**: Google Analytics and Tag Manager, Segment, Mixpanel, Amplitude, Hotjar, Sentry, Datadog RUM, New Relic and similar | The host |
| **CORS preflights** | The `OPTIONS` method |
| **Non-HTTP entries**: `data:` and `blob:` URLs, WebSockets, browser-extension URLs | The URL scheme |

Headers the browser sets by itself (`User-Agent`, `Accept-Language`, `Referer`, `sec-*`, HTTP/2
`:authority` …) are not API parameters either, so they are dropped from every request.

## One catalog item per host

A page often calls more than one API (its own API, an auth service, a payments provider). Each host
becomes **its own catalog item**. By default Apiome imports the host with the most API calls, and the
coverage ledger lists the calls to the other hosts it left out. To catalog another host, import the
same capture again and name the host in the `har_hosts` option.

## Tune the import

These options go in the import's `options` (see the import request in the
[REST reference](../reference/rest/spec-import.md)):

| Option | What it does |
| --- | --- |
| `har_hosts` | The host or hosts to import, such as `["auth.example.io"]` or `"api.example.com:8443"`. Naming two hosts imports both into one catalog item. A host the capture has no API calls to is refused, and the error lists the hosts it has. |
| `har_include` | `host/path` patterns to keep even when the filter would leave them out, such as `["api.example.com/v1/config.js"]`. `*` matches any run of characters. |
| `har_exclude` | `host/path` patterns to always leave out, such as `["*/internal/*"]`. An exclude pattern wins over an include pattern. |
| `har_keep_noise` | `true` turns the filter off, so assets, analytics calls and preflights are imported too. Non-HTTP entries are still left out. |

## What each part becomes

| In the capture | In the catalog item |
| --- | --- |
| Requests with the same method and path shape | One **operation**, keyed by its method and path template. Numeric, UUID and hash path segments become **path parameters** (`/v1/users/{id}`) |
| The URL's scheme, host and port | A **server** (`https://api.example.com`) |
| Query parameters | **Query parameters**. A parameter sent by some calls to an operation and not others is optional |
| Request headers your app sets (`Authorization`, `X-Api-Key`, `Content-Type`, custom `X-…` headers) | **Header parameters** |
| A JSON request body | A request **schema** inferred from the body, merged across samples |
| A form-encoded or multipart body | The request keeps its media type (`application/x-www-form-urlencoded`, `multipart/form-data`) |
| A JSON response body, including a base64-encoded one | A response **schema** for that status code, merged across samples |
| An `Authorization`, `X-Api-Key` or `Cookie` header | The operation's auth **scheme** (`bearer`, `basic`, `apiKey`, `cookie`). **Never the credential** |
| A blocked request (status `0`) | An operation with no response |
| An XML, text or binary body | Nothing is inferred from it; the operation is kept |

Every operation records how many samples it was built from.

## Credentials are never kept

A capture carries live session cookies, bearer tokens and API keys. Apiome keeps none of them:

- **Cookies are never read.** The `cookies` lists on requests and responses are skipped. A `Cookie`
  header is kept by name only, as cookie auth.
- **`Authorization` keeps its scheme only.** `Bearer eyJ…` becomes the `bearer` scheme; the token is
  dropped.
- **Every other value is scrubbed** before it reaches the catalog item: URLs, query and header values,
  and request and response bodies. A header or parameter whose name says it holds a secret
  (`X-Api-Key`, `access_token`, `password` …) is redacted whatever its value looks like.
- **The stored copy of your upload is scrubbed too.** Apiome keeps the uploaded file so it can be
  converted later. For HAR, secret scrubbing is always on, whatever your workspace's scrub mode, and
  cannot be switched off ([Secrets in collections and captures](./collection-secret-scrubbing.md)). It replaces every cookie value in a `cookies` list, the `Cookie`,
  `Set-Cookie` and `Authorization` header values, and secret-named fields inside the JSON bodies
  with `«redacted»`.

## What is declared, not imported

The coverage ledger records what the import left out or withheld:

- **Page assets, analytics calls, CORS preflights, non-HTTP entries, pattern exclusions**: each with
  how many entries were left out and up to 25 of their URLs.
- **Calls to another host**: the host and the URLs, so you can import it next.
- **A withheld credential**: the request's auth scheme is kept and its credential is not.
- **Cookies**: the requests that sent them.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | The file is not valid JSON, or an entry has no `request.url` or `request.method`. |
| `INPUT_TRUNCATED` | The JSON ends while a value is still open. The capture was cut short while saving. |
| `INPUT_SEMANTIC_INVALID` | The capture has no entries; every entry was left out (a page load with no API calls — the error says how to keep them); `har_hosts` names a host the capture has no API calls to; or a `har_*` option has the wrong type. |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |
| `FORMAT_MISMATCH` | The JSON is not a HAR capture, such as a Postman collection or an OpenAPI document. Import it as that format instead. |

## Related

- [Supported formats](./supported-formats.md): what this importer reads.
- [Declared, inferred and synthesized](./inference-provenance.mdx): why everything a capture import
  builds is labelled inferred.
- [Import a specification](./import-a-spec.md): the import job and its options.
- [Import a Thunder Client collection](./thunder-client-import.md): the same engine for saved requests.
