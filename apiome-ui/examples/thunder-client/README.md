# Thunder Client collections — `thunder-client`

Fixtures for **FMT-10.2** ([#5475](https://github.com/apiome/apiome/issues/5475)) — the VS Code-native
client with a simple collection JSON, and the cheapest remaining member of the client family. The
`thunder-client` adapter imports these collections, with their environments, as one API.

**Detection markers.** `"clientName": "Thunder Client"` plus either `collectionName` + `requests[]`
(a collection, exported as `thunder-collection_*.json`) or `data[]` of `{name, value}` pairs (an
environment, exported as `thunder-environment_*.json`).

**Shape notes that matter for the importer**

- Folders are a **flat list** with `containerId` pointing at the parent folder (empty string = root);
  the hierarchy must be reconstructed from those ids, not from nesting.
- Path parameters are marked `"isPath": true` in `params[]` and appear in the URL as `:name`.
- Tests are declarative rows (`res-code`, `res-time`, `json-query`, `set-env-var`), not scripts.
- Collection-level `settings.auth` / `settings.headers` are inherited unless a request overrides them.

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-collection.json` | minimal | One GET at the collection root. |
| `02-typical-orders-collection.json` | typical | A folder, collection-level bearer auth and header, path and query params, declarative tests. |
| `03-environment-set/` | multi-file | `thunder-collection_*.json` plus `thunder-environment_*.json` — the file names are part of the format. |
| `04-stress-bodies-auth-and-tests.json` | stress | `json`/`formencoded`/`formdata` (with a file)/`graphql` bodies, `basic` and `oauth2` auth, a **nested folder via `containerId`**, disabled entries, a `preReq` variable setter, four test kinds. |
| `05-real-world-payments-collection.json` | real-world | A vendor sandbox: token capture through a `set-env-var` test, idempotency key, three folders, per-request auth override. |
| `07-composition-folder-hierarchy.json` | composition | A `containerId` chain two deep with per-folder settings and an auth override. |
| `negative/` | — | Missing comma, a collection with no requests, truncation, a **Hoppscotch** collection, UTF-16, folders/requests whose `containerId` points at ids that do not exist, and a standalone environment export (empty credential slots, `default` flag) uploaded without its collection. |

**Credential rule.** Every credential-shaped value is `""` or a `{{variable}}`. A saved Thunder Client
request *can* carry a literal token; the adapter never reads auth credentials and scrubs every other
value, and `tests/test_thunder_client_import.py` asserts it.
