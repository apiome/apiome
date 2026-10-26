# Insomnia exports — `insomnia`

Fixtures for **MFI-32.3** ([#4405](https://github.com/apiome/apiome/issues/4405)) — the Insomnia desktop API
client. The `insomnia` adapter imports a v4 JSON or v5 YAML export, with its environments, as one REST API.

**Detection markers.** v4: `"_type": "export"` with `"__export_format": 4` and `resources[]`
(`__export_source` names `insomnia.desktop.app`). v5: a first-level `type: collection.insomnia.rest/5.0` (or a
design document's `spec.insomnia.rest/5.0`; a global environment is `environment.insomnia.rest/5.0`).

**Shape notes that matter for the importer**

- v4 is a **flat** `resources[]` list linked by `parentId`: workspace → `request_group` folders → `request`s,
  and base `environment` → sub-environments. The tree is rebuilt from those links.
- v5 is **nested**: a folder is a `collection` item with `children`; environments sit in `environments:`
  with `subEnvironments`.
- Variables are Nunjucks, `{{ _.baseUrl }}` (also `{{ baseUrl }}` and dotted `{{ _.api.host }}`); template tags
  `{% response … %}` / `{% uuid %}` are evaluated by Insomnia at send time.
- Folders carry `authentication`, `headers` and their own `environment`; an empty request auth inherits.
- gRPC and WebSocket requests, unit tests, API specs, mock routes and cookie jars sit beside the HTTP requests.

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-v5-single-request.yaml` | minimal | One GET at the collection root. |
| `02-typical-v5-users-collection.yaml` | typical | Folders two deep, folder bearer auth and header, base + two sub-environments, `:userId` and `{{ _.userId }}` path params, a disabled parameter. |
| `03-environment-set/` | multi-file | A v5 collection plus a global environment file that defines its `{{ _.ordersHost }}`. |
| `04-stress-v4-all-shapes.json` | stress | JSON (bare variable) / form / multipart / GraphQL / XML / binary bodies; basic, OAuth 2, API key (header and query), digest, IAM, explicit-none and disabled auth; folders three deep with a folder environment; nested environment data; a template tag; a pre-request script; gRPC, WebSocket, unit tests, a cookie jar and a `secret` key-value variable. |
| `05-real-world-v4-payments-export.json` | real-world | A payments sandbox: token exchange with an after-response script, an `{% uuid %}` idempotency key, per-folder bearer auth, a Live sub-environment. |
| `06-composition-v4-users-export.json` | composition | The collection in `02` as a v4 export — both import identically. |
| `07-real-world-v5-design-document.yaml` | real-world | A design document: an OpenAPI spec, a test suite and a collection beside them. |
| `negative/` | — | Broken YAML, a collection with no requests, a truncated v4 export, a **Postman** collection, UTF-16, export format 3, a request whose `parentId` names nothing, and a global environment uploaded alone. |

**Credential rule.** Every credential-shaped value is an obviously fake `demo-…-not-real` string or a
`{{ _.variable }}` reference. The adapter never reads auth credentials or cookie jars and scrubs every other
value; the intake gate scrubs the stored source. `tests/test_insomnia_import.py` asserts both.
