# Bruno collections — `bruno`

Fixtures for **MFI-32.4** ([#4406](https://github.com/apiome/apiome/issues/4406)) — Bruno, the git-native API
client. The `bruno` adapter imports a collection folder (as an archive, or from a git selection) as one REST API,
and a single `.bru` request on its own.

**Detection markers.** `bruno.json` with `"type": "collection"` and a `version` is the root an archive or git
selection resolves to; a request `.bru` has a `meta {` block and a method block (`get {`, `post {` …).

**Shape notes that matter for the importer**

- A collection is a **folder**: `bruno.json`, one `.bru` per request, `collection.bru` and `folder.bru`
  settings (headers, `auth { mode }`, `vars:pre-request`, scripts), and `environments/<name>.bru`
  (`vars { }` plus `vars:secret [ ]`, whose values live on the user's machine).
- `.bru` blocks: dictionaries (`key: value`, `~` disables, `"quoted keys"`, `'''` multi-line values), text
  blocks (`body:json`, `script:*`, `tests`, `docs`) and list blocks (`vars:secret [ ]`).
- A request keeps **every** body block it ever had; the method block's `body:` mode picks the one sent.
- Paths are recorded relative to `bruno.json`, so the archive's wrapping folder and a git selection prefix
  give the same model and fingerprint.

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-get.bru` | minimal | One GET with `meta` and a method block. |
| `02-typical-create-order.bru` | typical | A JSON body, bearer auth, query params, request variables, `assert`. |
| `03-users-collection.zip` | composition | A whole collection folder, zipped (its tree nests deeper than a corpus set directory allows): `bruno.json`, `collection.bru` (bearer auth, header, script), folders with `folder.bru` names / headers / basic auth, two environments with `vars:secret`, path params, JSON and multipart bodies, `tests`, `assert`, `vars:post-response`. |
| `04-stress-every-block.bru` | stress | Every block kind: OAuth 2 auth beside an unused bearer block, four body blocks with `formUrlEncoded` selected, a quoted key, a `'''` value, disabled entries, `{{process.env.*}}`, scripts, tests, `docs` with a brace on an indented line, `settings`, an unknown block. |
| `05-real-world-capture-payment.bru` | real-world | A payments capture: basic auth with an empty password, a form body, request variables, a post-response script. |
| `06-composition-graphql-with-vars.bru` | composition | `body:graphql` + `body:graphql:vars` with a bare variable, API-key auth from a variable. |
| `07-flat-orders-collection/` | multi-file | A flat collection folder: `bruno.json`, `collection.bru` (API-key auth, a variable) and two requests that inherit it. |
| `negative/` | — | A line outside any block, an environment alone, an unclosed block, a **Postman** collection, UTF-16, and `bruno.json` alone. |

**Credential rule.** Every credential-shaped value is an obviously fake `demo-…-not-real` string or a
`{{variable}}`. The adapter never reads auth credentials and scrubs every other value; the intake gate scrubs
the stored source. `tests/test_bruno_import.py` asserts both.
