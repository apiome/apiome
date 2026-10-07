---
title: "MCP surface lint rules"
description: "Every lint rule Apiome applies to an MCP server's tool surface."
sidebar_position: 4
tags: [mcp, governance, reference]
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_lint_rule_docs.py -->

Catalog for :mod:`app.mcp_lint`. Blocking rules include CLX-4.3 transparency fields. Fetch via `GET /v1/mcp/lint/rules`.

### `annotation.read-only-contradicts-destructive` {#annotation-read-only-contradicts-destructive}

- **Category:** annotation
- **Severity:** warning

### `annotation.read-only-contradicts-non-idempotent` {#annotation-read-only-contradicts-non-idempotent}

- **Category:** annotation
- **Severity:** warning

### `naming.item-name-missing` {#naming-item-name-missing}

- **Category:** naming
- **Severity:** error
- **Rationale:** Every capability item must carry a non-empty name so agents can address it.
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- **Remediation:** Set a stable, non-empty `name` on the tool, resource, template, or prompt.
- **False-positive guidance:** Rare — only when a transport strips names the server actually sends.
- **Fixture:** `mcp/unsafe/surface/naming-item-name-missing`
- **Scan modes:** `lint`, `surface`

### `quality.item-missing-title` {#quality-item-missing-title}

- **Category:** quality
- **Severity:** info

### `quality.prompt-argument-missing-description` {#quality-prompt-argument-missing-description}

- **Category:** quality
- **Severity:** warning

### `quality.prompt-argument-missing-required` {#quality-prompt-argument-missing-required}

- **Category:** quality
- **Severity:** info

### `quality.resource-missing-mime-type` {#quality-resource-missing-mime-type}

- **Category:** quality
- **Severity:** warning

### `quality.resource-template-missing-mime-type` {#quality-resource-template-missing-mime-type}

- **Category:** quality
- **Severity:** warning

### `quality.server-missing-instructions` {#quality-server-missing-instructions}

- **Category:** quality
- **Severity:** info

### `quality.tool-missing-description` {#quality-tool-missing-description}

- **Category:** quality
- **Severity:** warning

### `quality.tool-missing-output-schema` {#quality-tool-missing-output-schema}

- **Category:** quality
- **Severity:** info

### `schema.resource-invalid-uri` {#schema-resource-invalid-uri}

- **Category:** schema
- **Severity:** error
- **Rationale:** Resources must advertise an absolute URI with a scheme.
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/resources
- **Remediation:** Provide a scheme-qualified URI (e.g. `file:///…` or `https://…`).
- **False-positive guidance:** Custom schemes are allowed if they include a scheme delimiter.
- **Fixture:** `mcp/unsafe/surface/schema-resource-invalid-uri`
- **Scan modes:** `lint`, `surface`

### `schema.resource-template-invalid-uri-template` {#schema-resource-template-invalid-uri-template}

- **Category:** schema
- **Severity:** error
- **Rationale:** Resource templates must declare a well-formed URI template.
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/resources
- **Remediation:** Set `uriTemplate` with balanced `{var}` placeholders and a URI scheme.
- **False-positive guidance:** RFC 6570 level differences are tolerated if braces balance.
- **Fixture:** `mcp/unsafe/surface/schema-resource-template-invalid-uri-template`
- **Scan modes:** `lint`, `surface`

### `schema.tool-input-schema-invalid` {#schema-tool-input-schema-invalid}

- **Category:** schema
- **Severity:** error
- **Rationale:** Tools must declare a JSON Schema object as inputSchema.
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- **Remediation:** Set `inputSchema` to a JSON Schema with `"type": "object"` (and object properties).
- **False-positive guidance:** Empty-object schemas (`properties: {}`) are valid when the tool takes no args.
- **Fixture:** `mcp/unsafe/surface/schema-tool-input-schema-invalid`
- **Scan modes:** `lint`, `surface`

### `security.over-broad-auth-scope` {#security-over-broad-auth-scope}

- **Category:** security
- **Severity:** warning

### `security.ssrf-risky-resource-uri` {#security-ssrf-risky-resource-uri}

- **Category:** security
- **Severity:** warning

### `security.tool-token-passthrough-parameter` {#security-tool-token-passthrough-parameter}

- **Category:** security
- **Severity:** warning

### `structure.duplicate-item-name` {#structure-duplicate-item-name}

- **Category:** structure
- **Severity:** warning

### `structure.empty-surface` {#structure-empty-surface}

- **Category:** structure
- **Severity:** info
