---
title: "Import an A2A Agent Card"
description: "Catalog an A2A agent's skills, tags, modes and security from its Agent Card."
sidebar_position: 11
tags: [import, a2a, agents]
---

An **A2A Agent Card** is the JSON document every [A2A (Agent2Agent)](https://a2a-protocol.org/latest/specification/)
agent publishes to describe itself: its name and provider, where to reach it, what its transport
supports, how to authenticate, and the **skills** it offers. MCP describes the tools an agent calls;
A2A describes the agents an agent calls. Apiome imports the card into the [Catalog](./catalog.mdx),
where each skill is listed with its tags.

## What you can import

| You have | Import it as |
| --- | --- |
| A card file (`agent-card.json`, `agent.json`, or any `.json`) | One file |
| A URL that serves the card | A URL |
| A running agent (`https://agent.example.com`) | **Live discovery** from `/.well-known/agent-card.json`, with `apiome import a2a --discover` |
| The card text on your clipboard | A paste |

Cards written before A2A 0.3 are served at `/.well-known/agent.json` and import the same way.

## Import it

**In the app:**

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the card — try
   `apiome-ui/examples/a2a/02-typical-travel-concierge.json` — or choose **URL**, enter the card's
   address as the **Document URL** (for example
   `https://agent.example.com/.well-known/agent-card.json`) and **click "Fetch and detect"**.
3. On **Detect & route**, Apiome reports **Auto-detected: A2A Agent Card** (`a2a`) and routes it to the
   Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

The URL is fetched by your browser, so the agent must allow cross-origin requests; when it does not,
download the card or use `--discover` below.

**With the CLI:**

```bash
# A file or URL
apiome import a2a ./agent-card.json
apiome import a2a --url https://agent.example.com/.well-known/agent-card.json

# Live discovery: give the agent's address, Apiome finds the card
apiome import a2a --discover https://agent.example.com
```

`--discover` tries `/.well-known/agent-card.json` on the agent's origin, then
`/.well-known/agent.json`. Only a `404` moves on to the second path; any other error stops the import.
Add `--dry-run` to preview the import without saving it. See [`apiome import`](../reference/cli/import.md#import-a2a).

## What Apiome reads

| In the card | Becomes |
| --- | --- |
| `name`, `provider.organization`, `version` | The item's name, namespace and version. The A2A `protocolVersion` is recorded separately. |
| Each entry of `skills` | A **skill** (an operation keyed `<agent>.<skill id>`), with its name and description |
| A skill's `tags` | The skill's **tags** |
| `inputModes` / `outputModes` (or the card's `defaultInputModes` / `defaultOutputModes`) | The media types the skill accepts and returns |
| `examples` | The skill's example prompts |
| `securitySchemes` and `security` | The agent's **security**. A skill with its own `security` keeps it; every other skill inherits the card's. |
| `url`, `preferredTransport`, `additionalInterfaces` | **Servers**, one per endpoint, labelled with the transport (`JSONRPC`, `GRPC`, `HTTP+JSON`) |
| `capabilities` | The agent's **capability flags**, every one kept (`streaming`, `pushNotifications`, `stateTransitionHistory` …). With `streaming: true` the skills are also marked as streaming. |

Apiome keeps the card as an **agent descriptor**: the agent's identity, provider, version, capability
flags and typed security schemes, with each skill as its own entry keyed by its `id`. The descriptor is
stored with the version, so every field of the card above comes back exactly as imported.

## Browse the skills

Open the item from **Bring in → Catalog**. The **Overview** tab lists a **Skills** group: each skill shows
its tags next to its name, and opens to its id, description, modes, examples and security. **Type in
the group's filter box** to narrow the list by skill name or tag — for example `flights` or `travel`.

## Versions and changes

Each import is fingerprinted from the normalized card, so re-importing an unchanged card (even with its
keys or skills reordered) is recognised as the same version. When you import a new release, the
version comparison reports:

- a skill **added** or **removed** (by skill `id`);
- a skill **changed** — a new description, tags, modes, examples or security;
- an **auth change** to `securitySchemes` or the card's `security`, or a **capability flag** turned on
  or off, as a change to the agent itself.

A skill is matched by its `id`, so renaming a skill reports one changed skill, never a removed one and
an added one.

## Lint rules

Apiome scores each card with the common rules plus these A2A rules.

| Rule | Severity | Fires when |
| --- | --- | --- |
| `a2a.security-undeclared-scheme` | error | A `security` requirement names a scheme `securitySchemes` does not define. |
| `a2a.duplicate-skill-id` | error | Two skills share an `id`. |
| `a2a.no-security` | warning | The card declares no security at all. |
| `a2a.unknown-scheme-type` | warning | A scheme's `type` is not `apiKey`, `http`, `oauth2`, `openIdConnect` or `mutualTLS`. |
| `a2a.apikey-in-query` | warning | An API key is sent in the query string. |
| `a2a.insecure-endpoint` | warning | An endpoint uses plain `http` (localhost is allowed). |
| `a2a.missing-required-field` | warning | `description`, `url`, `version`, `capabilities`, `defaultInputModes` or `defaultOutputModes` is missing. |
| `a2a.skill-missing-description` | warning | A skill has no description. |
| `a2a.skill-missing-tags` | info | A skill has no tags. |
| `a2a.skill-without-modes` | info | A skill has no input or output modes and the card sets no default. |

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_SEMANTIC_INVALID` | The card has no `name`, `skills` is not a list, or a skill has no `id` or `name`. |
| `FORMAT_MISMATCH` | The document is not an Agent Card — for example an OpenAPI or MCP file. |
| `INPUT_MALFORMED`, `INPUT_TRUNCATED`, `INPUT_ENCODING_INVALID` | The JSON is not valid, is cut off, or is not UTF-8. |

Live discovery also stops when the agent's address is private or internal: Apiome only fetches public
`http`/`https` addresses.

## Related

- [Supported formats](./supported-formats.md): the versions this importer reads.
- [Import a specification](./import-a-spec.md): every way to bring a document in.
- [Import ACP agent manifests](./acp-agent-manifest-import.md): the REST-native agent protocol.
- [Agents and models](./agents-and-models.mdx): register the agents that call your APIs.
- [Import agentic-web site manifests](./agents-manifest-import.md): find a site's Agent Cards from its agents.json or llms.txt.
