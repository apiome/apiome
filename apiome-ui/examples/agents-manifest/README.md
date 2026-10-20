# Agentic-web site manifest — `agents-manifest`

Fixtures for **MFI-18.3** ([#3976](https://github.com/apiome/apiome/issues/3976)): cataloging the
site-level manifests of the agentic web, which work as `robots.txt` for agents. The
`agents-manifest` adapter (`app.agents_manifest_import_source`) claims every entry here.

**Shape.** Four dialects, one adapter:

- **`agents.json`** ([agents-txt.com](https://agents-txt.com)) has `site {name, url}`, the endpoint lists `mcp`, `a2a`, `skills`, `ucp`, `webmcp` (URL strings or `{url, description}`), and `payments {x402: {...}, ...}`.
- **`agent.json`** ([Agent Web Protocol](https://www.agentwebprotocol.org)) has `awp_version`, `domain`, `intent`, `protocols {a2a: {endpoint, agent_card}, mcp: {...}, x402: {...}}`, `actions [{id, method, endpoint, via}]` and `auth`.
- **`agents.txt`** is made of `Directive: value` lines: `MCP:`, `A2A:`, `Skills:`, `UCP:`, `WebMCP:`, `Protocols:` (payments), `Authorization:`, plus `X-…` experiments.
- **`llms.txt`** ([llmstxt.org](https://llmstxt.org)) has an H1 title, a `>` summary, and H2 sections of `- [name](url): notes` links.

**Detection marker.**

- JSON dialects are matched by shape: an `awp_version` key (AWP), or an endpoint list beside `site` / `payments` / an agents-txt `standard` (agents.json).
- `agents.txt` is matched by an endpoint directive that carries a value.
- `llms.txt` is matched by an H1 plus a linked H2 section. Shape alone gives confidence 0.75; a file named `llms.txt` raises it to 0.9.
- An A2A card or an ACP manifest never matches.

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-agents.txt` | minimal | One `MCP:` directive. |
| `02-typical-northwind-agents.json` | typical | agents.json with MCP, two A2A agents, a skill, authorization and x402/MPP payments. |
| `03-composition-contoso-agent.json` | composition | AWP manifest: A2A (with a relative `agent_card`), MCP and ACP protocols, x402/AP2 payment layers, and actions with and without `via`. |
| `04-stress-edge-cases.agents.txt` | stress | Every broken reference: a duplicate, plain http, a relative path with no site, an empty value, "not a url", `ftp://`. Also an `X-` protocol, unknown directives, a line that is not a directive, policies and Unicode. |
| `05-real-world-fabrikam-docs.llms.txt` | real-world | A developer-docs `llms.txt` whose links include an MCP server, an Agent Card, an OpenAPI document and a nested manifest. |
| `06-typical-northwind-agents-v2.json` | typical | The next crawl of `02`, used as the diff fixture: an MCP endpoint added, an A2A agent removed, a description edited, MPP dropped. |
| `negative/` | — | Trailing comma, a manifest with no declarations, truncation, an A2A card, UTF-16. |

**The contract the adapter meets.**

- Paradigm is `agent`.
- Each protocol is a service, and each endpoint is an operation keyed `<protocol>.<url>`. Each AWP action is an operation under its `via` protocol, or under `actions` when it has none.
- Payment layers are metadata (`extras.payments`), never services.
- The A2A, ACP, MCP and nested-manifest endpoints are listed as `extras.discovery_seeds`.
- The multi-file rung is waived.
