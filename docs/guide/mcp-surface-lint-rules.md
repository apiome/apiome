# MCP surface lint rules

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_lint_rule_docs.py -->

Catalog for :mod:`app.mcp_lint`. Blocking rules include CLX-4.3 transparency fields. Fetch via `GET /v1/mcp/lint/rules`.

<a id="annotation-read-only-contradicts-destructive"></a>
### `annotation.read-only-contradicts-destructive`

- **Category:** annotation
- **Severity:** warning

<a id="annotation-read-only-contradicts-non-idempotent"></a>
### `annotation.read-only-contradicts-non-idempotent`

- **Category:** annotation
- **Severity:** warning

<a id="naming-item-name-missing"></a>
### `naming.item-name-missing`

- **Category:** naming
- **Severity:** error
- **Rationale:** Every capability item must carry a non-empty name so agents can address it.
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- **Remediation:** Set a stable, non-empty `name` on the tool, resource, template, or prompt.
- **False-positive guidance:** Rare — only when a transport strips names the server actually sends.
- **Fixture:** `mcp/unsafe/surface/naming-item-name-missing`
- **Scan modes:** `lint`, `surface`

<a id="quality-item-missing-title"></a>
### `quality.item-missing-title`

- **Category:** quality
- **Severity:** info

<a id="quality-prompt-argument-missing-description"></a>
### `quality.prompt-argument-missing-description`

- **Category:** quality
- **Severity:** warning

<a id="quality-prompt-argument-missing-required"></a>
### `quality.prompt-argument-missing-required`

- **Category:** quality
- **Severity:** info

<a id="quality-resource-missing-mime-type"></a>
### `quality.resource-missing-mime-type`

- **Category:** quality
- **Severity:** warning

<a id="quality-resource-template-missing-mime-type"></a>
### `quality.resource-template-missing-mime-type`

- **Category:** quality
- **Severity:** warning

<a id="quality-server-missing-instructions"></a>
### `quality.server-missing-instructions`

- **Category:** quality
- **Severity:** info

<a id="quality-tool-missing-description"></a>
### `quality.tool-missing-description`

- **Category:** quality
- **Severity:** warning

<a id="quality-tool-missing-output-schema"></a>
### `quality.tool-missing-output-schema`

- **Category:** quality
- **Severity:** info

<a id="schema-resource-invalid-uri"></a>
### `schema.resource-invalid-uri`

- **Category:** schema
- **Severity:** error
- **Rationale:** Resources must advertise an absolute URI with a scheme.
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/resources
- **Remediation:** Provide a scheme-qualified URI (e.g. `file:///…` or `https://…`).
- **False-positive guidance:** Custom schemes are allowed if they include a scheme delimiter.
- **Fixture:** `mcp/unsafe/surface/schema-resource-invalid-uri`
- **Scan modes:** `lint`, `surface`

<a id="schema-resource-template-invalid-uri-template"></a>
### `schema.resource-template-invalid-uri-template`

- **Category:** schema
- **Severity:** error
- **Rationale:** Resource templates must declare a well-formed URI template.
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/resources
- **Remediation:** Set `uriTemplate` with balanced `{var}` placeholders and a URI scheme.
- **False-positive guidance:** RFC 6570 level differences are tolerated if braces balance.
- **Fixture:** `mcp/unsafe/surface/schema-resource-template-invalid-uri-template`
- **Scan modes:** `lint`, `surface`

<a id="schema-tool-input-schema-invalid"></a>
### `schema.tool-input-schema-invalid`

- **Category:** schema
- **Severity:** error
- **Rationale:** Tools must declare a JSON Schema object as inputSchema.
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- **Remediation:** Set `inputSchema` to a JSON Schema with `"type": "object"` (and object properties).
- **False-positive guidance:** Empty-object schemas (`properties: {}`) are valid when the tool takes no args.
- **Fixture:** `mcp/unsafe/surface/schema-tool-input-schema-invalid`
- **Scan modes:** `lint`, `surface`

<a id="security-over-broad-auth-scope"></a>
### `security.over-broad-auth-scope`

- **Category:** security
- **Severity:** warning

<a id="security-ssrf-risky-resource-uri"></a>
### `security.ssrf-risky-resource-uri`

- **Category:** security
- **Severity:** warning

<a id="security-tool-token-passthrough-parameter"></a>
### `security.tool-token-passthrough-parameter`

- **Category:** security
- **Severity:** warning

<a id="structure-duplicate-item-name"></a>
### `structure.duplicate-item-name`

- **Category:** structure
- **Severity:** warning

<a id="structure-empty-surface"></a>
### `structure.empty-surface`

- **Category:** structure
- **Severity:** info
