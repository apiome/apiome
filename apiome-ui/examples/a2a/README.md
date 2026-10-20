# A2A Agent Card — `a2a`

Fixtures for **MFI-18.1** ([#3974](https://github.com/apiome/apiome/issues/3974)) — cataloging an
A2A (Agent2Agent) agent from the Agent Card it publishes at `/.well-known/agent-card.json`. The
`a2a` adapter (`app.a2a_import_source`) claims every entry here.

**Shape.** An Agent Card names the agent (`name`, `description`, `version`, `provider`), says where to
reach it (`url` + `preferredTransport`, `additionalInterfaces`), what the transport supports
(`capabilities`), how to authenticate (`securitySchemes` + `security`), and lists its `skills` — each
with an `id`, `name`, `description`, `tags`, `examples` and input / output modes.

**Detection marker.** A `name` string and a `skills` array whose members carry an `id`, beside at
least one card-only key (`protocolVersion`, `capabilities`, `defaultInputModes`, …).

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-echo-agent.json` | minimal | One skill, default modes, no security (lint reports `a2a.no-security`). |
| `02-typical-travel-concierge.json` | typical | Four tagged skills, OAuth 2.0, streaming, per-skill output modes. |
| `03-composition-multi-interface-skill-auth.json` | composition | Three transports, OIDC + mTLS, a skill with its own security, a required extension. |
| `04-stress-edge-cases.json` | stress | Duplicate and numeric skill ids, undeclared and unknown schemes, an API key in the query, plain HTTP, signatures, Unicode. |
| `05-real-world-georoute-planner.json` | real-world | Reconstruction of the sample card in the A2A specification. |
| `06-typical-travel-concierge-v3.json` | typical | The next release of `02`: a skill added (`search-rail`, `book-trip`), one removed (`visa-requirements`), one edited, and the security changed — the diff fixture. |
| `negative/` | — | Trailing comma, a skill with an empty `id`, truncation, an OpenAPI document, UTF-16. |

**The contract the adapter meets.** Paradigm `agent`. The agent is one service (its `extras` carry the
security schemes and requirements, so an auth change diffs as a changed service); each skill is an
operation keyed `<agent>.<skill id>` whose `tags` are the skill's tags; input / output modes are the
request / response content types. The multi-file rung is waived: a card is one self-contained document.
