---
title: "Import ACP agent manifests"
description: "Catalog an ACP server's agents, capabilities, content types and tags."
sidebar_position: 12
tags: [import, acp, agents]
---

**ACP (Agent Communication Protocol)** is the REST-native agent protocol from IBM BeeAI under the
Linux Foundation: agents run over plain HTTP (`POST /runs`) and exchange MIME-typed multipart
messages. An ACP server lists the agents it hosts at `GET /agents`, and each agent describes itself
with an **agent manifest**. Apiome imports those manifests into the [Catalog](./catalog.mdx), next to
[A2A Agent Cards](./a2a-agent-card-import.md).

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| One agent manifest (`GET /agents/{name}`, or a saved `.json`) | A catalog item with one agent |
| A server's agent listing (`GET /agents`, `{"agents": [...]}`) | One catalog item with every agent the server hosts |
| A running ACP server (`https://acp.example.com`) | **Live discovery** of `<server>/agents`, with `apiome import acp --discover` |
| The JSON on your clipboard | A paste |

## Import it

**In the app:**

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the manifest or listing — try
   `apiome-ui/examples/acp/03-composition-agent-list.json` — or choose **URL**, enter the server's
   listing as the **Document URL** (for example `https://acp.example.com/agents`) and **click "Fetch and
   detect"**.
3. On **Detect & route**, Apiome reports **Auto-detected: ACP Agent Manifest** (`acp`) and routes it to
   the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

The URL is fetched by your browser, so the server must allow cross-origin requests; when it does not,
save the JSON or use `--discover` below.

**With the CLI:**

```bash
# A file or URL
apiome import acp ./agents.json
apiome import acp --url https://acp.example.com/agents

# Live discovery: give the server's address, Apiome fetches <server>/agents
apiome import acp --discover https://acp.example.com
```

`--discover` also accepts a server mounted under a path (`https://example.com/acp` fetches
`https://example.com/acp/agents`) and a single agent's URL (`https://acp.example.com/agents/chat`).
Add `--dry-run` to preview without saving. See [`apiome import`](../reference/cli/import.md#import-acp).

## What Apiome reads

| In the manifest | Becomes |
| --- | --- |
| Each agent (`name`, `description`) | An **agent** (a service keyed by its name) |
| Each entry of `metadata.capabilities` (`name`, `description`) | A **capability** of that agent (an operation keyed `<agent>.<capability>`) |
| `input_content_types` / `output_content_types` | The media types each capability accepts and returns. A manifest that leaves them out accepts anything (`*/*`), as ACP specifies. |
| `metadata.tags`, `metadata.domains` | The agent's **tags** and **domains**; each capability carries the agent's tags |
| `framework`, `programming_language`, `natural_languages`, `license`, `author`, `contributors`, `links`, `dependencies`, `recommended_models`, `documentation` | The agent's metadata |
| The `…/agents` URL a listing was fetched from | The item's **server** |

**Not read:** `status` (average tokens, run time, success rate) and the `created_at` / `updated_at`
stamps. They change on every deployment, so Apiome keeps them only in the stored source; they never
make an unchanged agent look like a new version.

## Browse the agents

Open the item from **Bring in → Catalog**. The **Overview** tab lists an **Agents** group: each agent
shows its tags and domains next to its name, and opens to its description, capabilities, content
types, framework, license and author. **Type in the group's filter box** to narrow the list by agent
name, tag or domain — for example `finance`. ACP and A2A items sit side by side in the Catalog under
the **Agent** paradigm.

## Versions and changes

Each import is fingerprinted from the normalized agents, so re-importing an unchanged listing — even
reordered, or with new `status` numbers — is the same version. Importing a new release reports:

- an agent **added** to or **removed** from the listing;
- a capability **added**, **removed** or **changed** (by capability name);
- a change to an agent's description, content types, tags, domains or other metadata, as a change to
  the agent itself.

## Lint rules

Apiome scores each document with the common rules plus these ACP rules.

| Rule | Severity | Fires when |
| --- | --- | --- |
| `acp.duplicate-agent-name` | error | Two agents in one listing share a name. |
| `acp.invalid-agent-name` | warning | A name is not an RFC 1123 label (lower-case letters, digits and `-`). |
| `acp.agent-missing-description` | warning | An agent has no description. |
| `acp.duplicate-capability-name` | warning | An agent declares a capability name twice. |
| `acp.capability-missing-description` | warning | A capability has no description. |
| `acp.no-capabilities` | info | An agent declares no capabilities. |
| `acp.untyped-content` | info | An agent leaves its input or output content types out, or declares only `*/*`. |
| `acp.missing-tags` | info | An agent has no tags and no domains. |
| `acp.missing-license` | info | An agent declares no SPDX license. |

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_SEMANTIC_INVALID` | The listing has no agents, or an agent has no `name`. |
| `FORMAT_MISMATCH` | The document is not an ACP manifest — for example an A2A Agent Card or an OpenAPI file. |
| `INPUT_MALFORMED`, `INPUT_TRUNCATED`, `INPUT_ENCODING_INVALID` | The JSON is not valid, is cut off, or is not UTF-8. |

Live discovery stops at a private or internal address: Apiome only fetches public `http`/`https`
addresses, and a server that answers with an error is reported rather than retried.

## Related

- [Import an A2A Agent Card](./a2a-agent-card-import.md): the other agent-to-agent protocol.
- [Supported formats](./supported-formats.md): the versions this importer reads.
- [Built-in lint rules](../build/lint-rules.md): every `acp.*` rule with its rationale.
