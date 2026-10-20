# ACP agent manifest — `acp`

Fixtures for **MFI-18.2** ([#3975](https://github.com/apiome/apiome/issues/3975)) — cataloging agents
that speak ACP (Agent Communication Protocol), the REST-native alternative to A2A. The `acp` adapter
(`app.acp_import_source`) claims every entry here.

**Shape.** An ACP server lists its agents at `GET /agents` as `{"agents": [manifest, …]}` and describes
one at `GET /agents/{name}`. A manifest has a `name`, a `description`, `input_content_types` /
`output_content_types`, and `metadata`: `capabilities` (name + description), `tags`, `domains`,
`framework`, `programming_language`, `natural_languages`, `license`, `author`, `links`, `dependencies`,
`recommended_models`. Its `status` and timestamps are runtime facts.

**Detection marker.** A `name` beside `input_content_types` / `output_content_types` or an ACP
`metadata` key, or an `{"agents": [...]}` object whose every member is such a manifest. An A2A card
(`skills`) never matches.

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-echo-agent.json` | minimal | One agent, one capability. |
| `02-typical-research-agent.json` | typical | Full metadata: capabilities, tags, domains, author, links, dependencies, `status`. |
| `03-composition-agent-list.json` | composition | A `GET /agents` listing of three agents that depend on each other. |
| `04-stress-edge-cases.json` | stress | Duplicate agent and capability names, a non-RFC-1123 name, `*/*` and missing content types, Unicode, vendor keys. |
| `05-real-world-beeai-style-listing.json` | real-world | Reconstruction of a BeeAI platform listing. |
| `06-typical-research-agent-v2.json` | typical | The next release of `02`: a capability added and one removed, plus moved runtime `status` that must not change the fingerprint — the diff fixture. |
| `negative/` | — | Trailing comma, an empty agent list, truncation, an A2A card, UTF-16. |

**The contract the adapter meets.** Paradigm `agent`. Each agent is a service (its metadata on `extras`),
each capability an operation keyed `<agent>.<capability>` carrying the agent's tags and content types.
`status`, `created_at` and `updated_at` stay in `raw` only. The multi-file rung is waived.
