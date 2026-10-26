# HAR captures — `har`

Fixtures for **MFI-32.2** ([#4404](https://github.com/apiome/apiome/issues/4404)) — HTTP Archive files saved
from a browser's devtools (*Network → Save all as HAR*) or a debugging proxy. The `har` adapter infers a
REST API from the recorded traffic through the shared inferred-spec engine.

**Detection marker.** A JSON object whose `log` holds an `entries` list — `{"log": {"version": "1.2", …,
"entries": […]}}`. HAR 1.1 and captures with no `log.version` are read the same way.

**Shape notes that matter for the importer**

- A capture records the whole page load: documents, scripts, stylesheets, fonts, images, analytics
  beacons and CORS preflights sit beside the API calls and must be left out.
- Chrome adds `_resourceType` (`fetch`, `xhr`, `script`, `image` …) and HTTP/2 pseudo-headers
  (`:authority`, `:path`); Firefox and proxies do not.
- A page often calls several hosts; each host becomes its own catalog item.
- Response bodies may be base64 (`content.encoding: "base64"`); blocked requests have status `0`.

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-single-call.har` | minimal | One GET with only the fields HAR 1.2 requires. |
| `02-typical-devtools-crud.har` | typical | A Chrome devtools capture of a CRUD page: assets, an analytics beacon and a preflight to filter; list / get ×3 / create / update / delete calls that cluster into `/v1/users/{id}`. |
| `03-multi-session/` | multi-file | Two recording sessions against one API, imported together. |
| `04-stress-mixed-capture.har` | stress | UUID and hash path segments, a base64 body, form and multipart bodies, CSV / text responses, a blocked request, a `304`, `data:` / `wss:` / extension URLs, an event stream, a source map, Sentry and Segment calls. |
| `05-real-world-dashboard.har` | real-world | A dashboard SPA calling its API, an auth service, a CDN and three vendors; cookie and bearer auth. The API host is selected by default. |
| `06-composition-sample-widening.har` | composition | Several samples of the same endpoints whose bodies differ — nested objects, nullable and optional fields, integer/number widening. |
| `07-firefox-har-1.1-todos.har` | real-world | A Firefox HAR 1.1 export: no `_resourceType`, plain HTTP on `localhost:8080`, `X-Api-Key` auth. |
| `negative/` | — | Missing comma, a capture with no entries, truncation, a **Postman** collection, UTF-16, and a page load with no API calls at all. |

**Credential rule.** Every credential-shaped value is an obviously fake `demo-…-not-real` string. A real
capture carries live cookies and tokens; the adapter never reads cookies, keeps only the `Authorization`
scheme, and scrubs every other value, and the stored source is scrubbed by the intake gate.
`tests/test_har_import.py` asserts both.
