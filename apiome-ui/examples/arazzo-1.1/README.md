# Arazzo 1.1 workflows — `arazzo-1.1`

Fixtures for **FMT-3.1** ([#5426](https://github.com/apiome/apiome/issues/5426)) — the May 2026
revision that lets one workflow span synchronous (OpenAPI) and asynchronous (AsyncAPI) APIs. The
shipped `arazzo/` corpus covers 1.0 only; these entries are the 1.1 half, plus a 1.0 baseline that
must still round-trip **as 1.0** (the emitter may not silently upgrade).

They sit in their own directory rather than in `arazzo/` because they were authored ahead of the
adapter. As of #5426 the `arazzo` adapter reads both minor versions, so every entry here is live:
each carries `adapter_key: arazzo` and runs in the corpus import, negative, golden and parity
suites alongside the 1.0 set.

**Detection marker.** Top-level `arazzo: 1.1.x`.

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-single-step.yaml` | minimal | One source description, one step, one criterion. |
| `02-typical-checkout-flow.yaml` | typical | Inputs, step outputs threaded between steps, request bodies. |
| `03-composition-reusable-components.yaml` | composition | `components.{inputs,parameters,successActions,failureActions}` reached by `$ref`, plus `dependsOn` between workflows. |
| `04-stress-criteria-vocabulary.yaml` | stress | `simple`/`regex`/`jsonpath`/`xpath` criteria, versioned criterion objects, `operationPath` and `operationRef`. |
| `05-real-world-order-to-cash.yaml` | real-world | The 1.1 headline: REST step → two AsyncAPI event steps → REST step, with `$message.payload` criteria. |
| `06-sourced-set/` | multi-file | Workflow whose `sourceDescriptions` resolve to a sibling OpenAPI file. |
| `07-version-1.0-baseline.yaml` | typical | A 1.0.1 document; import must record 1.0 and emit 1.0. |
| `08-oai-querystring-runtime-expression.arazzo.yaml` | stress | OAI schema fixture: an `in: querystring` parameter built from a runtime expression. |
| `09-oai-static-querystring.arazzo.yaml` | stress | OAI schema fixture: a static `querystring` parameter. |
| `10-oai-components-parameter-reference.arazzo.yaml` | composition | OAI schema fixture: a step parameter reached through `$components.parameters`. |
| `11-oai-workflow-parameter-reference.arazzo.yaml` | composition | OAI schema fixture: a workflow-level parameter reached through `$components.parameters`. |
| `12-oai-channel-path.arazzo.yaml` | stress | OAI schema fixture: a step whose only target is `channelPath`, with `action` and `correlationId`. |
| `13-oai-openapi-and-asyncapi.arazzo.yaml` | real-world | OAI schema fixture: one workflow over an OpenAPI and an AsyncAPI source, with timeouts. |
| `14-oai-payload-replacement-selector.arazzo.yaml` | stress | OAI schema fixture: request-body replacements addressed by selector objects. |
| `15-redocly-cafe-workflows.arazzo.yaml` | real-world | Redocly CLI's 1.1 lint fixture: `$self`, `querystring`, `channelPath`, selectors, `timeout`. |
| `16-specmatic-place-order.arazzo.yaml` | real-world | Specmatic's PlaceOrder workflow over four OpenAPI sources. |
| `negative/` | — | Broken flow sequence, a step that names no operation, truncation, an AsyncAPI document, UTF-16, and an out-of-range `arazzo: 2.0.0`. |

**Foreign-source goldens (COA-1.4, [#7040](https://github.com/apiome/apiome/issues/7040)).** Entries 08–16
here, and `arazzo/08`–`12`, are `origin: derived`: copied unchanged from the OpenAPI Initiative,
Redocly and Specmatic (or, for `arazzo/12`, assembled from Spectral's ruleset examples), below a
three-line attribution header, with the upstream commit pinned in the manifest's `source_url`.
`apiome-rest/tests/test_arazzo_conformance_corpus.py` requires each to pass the official schema,
import, and export back field for field. Do not edit their bodies: re-copy from upstream instead.

**Grounding note.** The async steps use the 1.1 `sourceDescriptions[].type: asyncapi` form with
`$message.payload` criteria contexts. Both are what the adapter keys off: a step whose source is
declared `asyncapi`, or whose criteria read `$message.*`, is normalized as an asynchronous step
(`extras.asyncStep`). Record any deviation from the published 1.1 JSON Schema in the manifest
`notes` rather than editing a fixture silently.
