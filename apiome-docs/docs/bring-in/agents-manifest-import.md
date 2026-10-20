---
title: "Import agentic-web site manifests"
description: "Catalog a site's agents.json, agent.json, agents.txt or llms.txt and its discovery seeds."
sidebar_position: 13
tags: [import, agents, discovery]
---

A site that works with AI agents can publish a small **site manifest**, the agentic web's
`robots.txt`. It names the agent protocols the site speaks (A2A, MCP, ACP …), where their
descriptors live, and which payment layers (x402, AP2 …) it accepts. Apiome imports these manifests
into the [Catalog](./catalog.mdx). Each one also lists the [A2A Agent Cards](./a2a-agent-card-import.md),
[ACP servers](./acp-agent-manifest-import.md) and MCP servers it points at as **discovery seeds**:
the descriptors to import next.

## What you can import

| You have | Dialect | What Apiome makes of it |
| --- | --- | --- |
| `/agents.json` ([agents-txt.com](https://agents-txt.com)) | `agents-json` | `site`, the `mcp` / `a2a` / `skills` / `ucp` / `webmcp` endpoint lists, `authorization` and `payments` |
| `/.well-known/agent.json` ([Agent Web Protocol](https://www.agentwebprotocol.org)) | `awp` | `domain`, `intent`, `protocols`, `actions` (with `via`) and `auth` |
| `/agents.txt` | `agents-txt` | `MCP:`, `A2A:`, `Skills:`, `UCP:`, `WebMCP:` and `X-…` directives, `Protocols:` (payments), `Authorization:`, `Payments:` / `Identity:` policies |
| `/llms.txt` ([llmstxt.org](https://llmstxt.org)) | `llms-txt` | The title, summary and every `- [name](url)` link, classified by what it points at |
| A live site (`https://example.com`) | any | **Live discovery** of the first manifest the site serves, with `apiome import agents-manifest --discover` |

## Import it

**In the app:**

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the manifest. To try it, use
   `apiome-ui/examples/agents-manifest/03-composition-contoso-agent.json`. Or choose **URL**, enter
   the manifest as the **Document URL** (for example `https://example.com/agents.json`) and
   **click "Fetch and detect"**.
3. On **Detect & route**, Apiome reports **Auto-detected: Agentic-web Site Manifest**
   (`agents-manifest`) and routes it to the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Your browser fetches the URL, so the site must allow cross-origin requests. When it does not, save
the file or use `--discover` below. An `llms.txt` is plain Markdown, so name the file `llms.txt` when
you upload it; Apiome then recognizes it with full confidence.

**With the CLI:**

```bash
# A file or URL
apiome import agents-manifest ./agents.json
apiome import agents-manifest --url https://example.com/llms.txt

# Live discovery: give the site, Apiome finds its manifest
apiome import agents-manifest --discover https://example.com
```

`--discover` tries `/agents.json`, `/.well-known/agent.json`, `/agents.txt` and `/llms.txt`, in that
order, and imports the first one that is a manifest. It skips a path that returns an HTML page, and
an A2A Agent Card at `/.well-known/agent.json`, the legacy card path that AWP shares. A URL that
names a file (`https://example.com/docs/llms.txt`) is imported as it is. Add `--dry-run` to preview
without saving. See [`apiome import`](../reference/cli/import.md#import-agents-manifest).

## What Apiome reads

| In the manifest | Becomes |
| --- | --- |
| Each protocol the site declares (`a2a`, `mcp`, `acp`, `skills`, `ucp`, `webmcp`, `x-…`) | A **protocol** (a service keyed by the protocol id) |
| Each endpoint of that protocol | An **endpoint** (an operation keyed `<protocol>.<url>`), with its description, transport and version |
| Each AWP action (`id`, `method`, `endpoint`, `via`) | An **action**, under the protocol it is routed `via`, else under **Actions** |
| Each llms.txt link | An endpoint, classified by its target: an Agent Card (`a2a`), an MCP endpoint (`mcp`), an OpenAPI document (`openapi`), another manifest (`manifest`), a `SKILL.md` (`skills`), or documentation (`docs`) |
| `payments` / `Protocols:` / AWP payment protocols (x402, AP2, MPP, Skyfire) | **Payment layers**: metadata only, never endpoints |
| `site.url`, AWP `domain`, or the URL the manifest was fetched from | The item's **server**. Relative endpoints such as `/api/search` resolve against it. |

## Discovery seeds

Every A2A, ACP and MCP endpoint, and every nested manifest, that resolves to an absolute URL is
listed as a discovery seed with the importer that follows it:

| Seed protocol | Follow it with |
| --- | --- |
| `a2a` | `apiome import a2a --discover <url>`; an AWP entry seeds its `agent_card` |
| `acp` | `apiome import acp --discover <url>` |
| `mcp` | An MCP probe of the server |
| `manifest` | `apiome import agents-manifest --discover <url>` |

A manifest is a starting point for a crawl. Apiome lists the seeds and does not import them for
you.

## Browse the manifest

Open the item from **Bring in → Catalog**. The **Overview** tab shows these groups:

- **Endpoints**: one entry per declared address, with its protocol next to its name.
- **Actions**: AWP actions with their method, endpoint and routing.
- **Discovery seeds**: the descriptors to import next.
- **Payments**: each payment layer with its chains, methods or wallet.

**Type in a group's filter box** to narrow it. For example, `mcp` lists only MCP endpoints and seeds.

## Versions and changes

Each import is fingerprinted from the normalized manifest, so re-importing an unchanged manifest is
the same version, even when it is reordered. Importing it again after the site changes reports:

- an endpoint **added** or **removed** (by protocol and URL);
- an endpoint's description, transport or version **changed**;
- an AWP action **added**, **removed** or **changed** (by id).

## Lint rules

Apiome scores each manifest with the common rules plus these rules.

| Rule | Severity | Fires when |
| --- | --- | --- |
| `agents-manifest.broken-endpoint-ref` | error | An endpoint or action address is empty, not a URL, uses another scheme (`ftp://`), or is relative with no site to resolve it against. |
| `agents-manifest.undeclared-via` | error | An AWP action is routed `via` a protocol that `protocols` does not declare. |
| `agents-manifest.insecure-endpoint` | warning | An agent endpoint uses plain `http`. llms.txt documentation links are exempt. |
| `agents-manifest.duplicate-endpoint` | warning | The same protocol and URL are declared twice. |
| `agents-manifest.duplicate-action-id` | warning | Two AWP actions share an `id`. |
| `agents-manifest.no-agent-endpoints` | info | The manifest declares no A2A, ACP or MCP endpoint, so it seeds nothing. |

An `agents.txt` or `llms.txt` imported as a file has no site, so its relative paths are reported as
broken. Import it from its URL, or with `--discover`, so they resolve.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_SEMANTIC_INVALID` | The manifest declares no endpoint, action or payment layer, an AWP `actions` value is not a list, or an action has no `id`. |
| `FORMAT_MISMATCH` | The document is not a site manifest, for example an A2A Agent Card, an ACP manifest or an OpenAPI file. |
| `INPUT_MALFORMED`, `INPUT_TRUNCATED`, `INPUT_ENCODING_INVALID` | The JSON is not valid, is cut off, or the file is not UTF-8. |

Live discovery stops at a private or internal address. Apiome only fetches public `http` / `https`
addresses, and it reports a site that answers with an error rather than retrying it.

## Related

- [Import an A2A Agent Card](./a2a-agent-card-import.md): the descriptors an `a2a` seed points at.
- [Import ACP agent manifests](./acp-agent-manifest-import.md): the servers an `acp` seed points at.
- [Supported formats](./supported-formats.md): the dialects and versions this importer reads.
- [Built-in lint rules](../build/lint-rules.md): every `agents-manifest.*` rule with its rationale.
