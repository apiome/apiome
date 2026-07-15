# MCP conformance rules

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_lint_rule_docs.py -->

Catalog for :mod:`app.mcp_conformance`. Every rule cites an MCP specification reference. Blocking rules include CLX-4.3 transparency fields. Fetch via `GET /v1/mcp/conformance/rules`.

<a id="protocol-declared-capability-empty"></a>
### `protocol.declared-capability-empty`

- **Category:** protocol
- **Severity:** info
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **Rationale:** A declared capability that lists nothing gives an agent a dead end.
- **Requires transcript:** False

<a id="protocol-empty-page-with-next-cursor"></a>
### `protocol.empty-page-with-next-cursor`

- **Category:** protocol
- **Severity:** warning
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/utilities/pagination
- **Rationale:** An empty page that still advertises nextCursor wastes a round trip per page.
- **Requires transcript:** True

<a id="protocol-error-code-non-standard"></a>
### `protocol.error-code-non-standard`

- **Category:** protocol
- **Severity:** warning
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- **Rationale:** An error code inside the JSON-RPC reserved band must be a defined code.
- **Requires transcript:** True

<a id="protocol-list-result-missing-items"></a>
### `protocol.list-result-missing-items`

- **Category:** protocol
- **Severity:** error
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/utilities/pagination
- **Rationale:** A list result MUST carry its item array, even when empty.
- **Requires transcript:** True
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- **Remediation:** Include the method's items key (`tools`, `resources`, `prompts`, …) as an array.
- **False-positive guidance:** Skipped (never failed) when no transcript was captured.
- **Fixture:** `mcp/unsafe/conformance/protocol-list-result-missing-items`
- **Scan modes:** `protocol`, `requires_transcript`

<a id="protocol-missing-protocol-version"></a>
### `protocol.missing-protocol-version`

- **Category:** protocol
- **Severity:** error
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **Rationale:** The initialize result MUST carry a protocolVersion; without one no version is agreed.
- **Requires transcript:** False
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **Remediation:** Return a supported `protocolVersion` string from initialize.
- **False-positive guidance:** Not a false positive when the field is present but empty — fix the server.
- **Fixture:** `mcp/unsafe/conformance/protocol-missing-protocol-version`
- **Scan modes:** `protocol`, `surface`

<a id="protocol-missing-server-name"></a>
### `protocol.missing-server-name`

- **Category:** protocol
- **Severity:** error
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **Rationale:** serverInfo.name identifies the server to the host and MUST be present.
- **Requires transcript:** False
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **Remediation:** Set a non-empty `serverInfo.name` on initialize.
- **False-positive guidance:** Whitespace-only names are treated as missing.
- **Fixture:** `mcp/unsafe/conformance/protocol-missing-server-name`
- **Scan modes:** `protocol`, `surface`

<a id="protocol-missing-server-version"></a>
### `protocol.missing-server-version`

- **Category:** protocol
- **Severity:** warning
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **Rationale:** serverInfo.version lets a host pin and audit a server build; it should be declared.
- **Requires transcript:** False

<a id="protocol-protocol-version-downgraded"></a>
### `protocol.protocol-version-downgraded`

- **Category:** protocol
- **Severity:** info
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **Rationale:** The server negotiated an older revision than the client offered.
- **Requires transcript:** True

<a id="protocol-response-id-not-echoed"></a>
### `protocol.response-id-not-echoed`

- **Category:** protocol
- **Severity:** error
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- **Rationale:** A response MUST echo the id of the request it answers, or it cannot be correlated.
- **Requires transcript:** True
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- **Remediation:** Echo the JSON-RPC request `id` on every successful or error response.
- **False-positive guidance:** Skipped when no transcript was captured; notifications (no id) are exempt.
- **Fixture:** `mcp/unsafe/conformance/protocol-response-id-not-echoed`
- **Scan modes:** `protocol`, `requires_transcript`

<a id="protocol-undeclared-capability-listed"></a>
### `protocol.undeclared-capability-listed`

- **Category:** protocol
- **Severity:** error
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **Rationale:** A server MUST NOT serve a capability it did not declare during initialize.
- **Requires transcript:** False
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **Remediation:** Declare the capability in initialize `capabilities`, or stop listing those items.
- **False-positive guidance:** Hosts that invent capability keys may need profile waivers — not silent skips.
- **Fixture:** `mcp/unsafe/conformance/protocol-undeclared-capability-listed`
- **Scan modes:** `protocol`, `surface`

<a id="protocol-unknown-capability-declared"></a>
### `protocol.unknown-capability-declared`

- **Category:** protocol
- **Severity:** info
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **Rationale:** A capability key outside the spec's vocabulary belongs under 'experimental'.
- **Requires transcript:** False

<a id="protocol-unsupported-protocol-version"></a>
### `protocol.unsupported-protocol-version`

- **Category:** protocol
- **Severity:** error
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **Rationale:** The negotiated protocol version MUST be a revision this client speaks.
- **Requires transcript:** False
- **Reference:** https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **Remediation:** Negotiate a supported protocolVersion from the client's offered set.
- **False-positive guidance:** Bump Apiome's supported-version set only via an intentional release.
- **Fixture:** `mcp/unsafe/conformance/protocol-unsupported-protocol-version`
- **Scan modes:** `protocol`, `surface`

<a id="readiness-tool-description-too-brief"></a>
### `readiness.tool-description-too-brief`

- **Category:** readiness
- **Severity:** warning
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- **Rationale:** A description under 40 characters cannot distinguish a tool from its siblings, so an agent selects it by name alone.
- **Requires transcript:** False

<a id="readiness-tool-destructive-not-declared"></a>
### `readiness.tool-destructive-not-declared`

- **Category:** readiness
- **Severity:** warning
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- **Rationale:** A destructive operation that does not declare destructiveHint may be auto-approved by a host that would otherwise have demanded confirmation.
- **Requires transcript:** False

<a id="readiness-tool-missing-annotations"></a>
### `readiness.tool-missing-annotations`

- **Category:** readiness
- **Severity:** info
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- **Rationale:** Without behavioural annotations a host cannot reason about a tool's safety at all.
- **Requires transcript:** False

<a id="readiness-tool-missing-output-schema"></a>
### `readiness.tool-missing-output-schema`

- **Category:** readiness
- **Severity:** info
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- **Rationale:** Without an outputSchema an agent cannot predict or validate a tool's result shape.
- **Requires transcript:** False

<a id="readiness-tool-missing-recovery-guidance"></a>
### `readiness.tool-missing-recovery-guidance`

- **Category:** readiness
- **Severity:** info
- **Spec version:** 2025-06-18
- **Spec reference:** https://www.anthropic.com/engineering/writing-tools-for-agents
- **Rationale:** A description that never mentions the failure path leaves an agent with no recovery strategy when the call errors.
- **Requires transcript:** False

<a id="readiness-tool-name-unconventional"></a>
### `readiness.tool-name-unconventional`

- **Category:** readiness
- **Severity:** info
- **Spec version:** 2025-06-18
- **Spec reference:** https://www.anthropic.com/engineering/writing-tools-for-agents
- **Rationale:** A name matching no common convention is hard for a model to reproduce exactly.
- **Requires transcript:** False

<a id="readiness-tool-naming-inconsistent"></a>
### `readiness.tool-naming-inconsistent`

- **Category:** readiness
- **Severity:** info
- **Spec version:** 2025-06-18
- **Spec reference:** https://www.anthropic.com/engineering/writing-tools-for-agents
- **Rationale:** Mixed naming conventions across one server's tools make every name a guess.
- **Requires transcript:** False

<a id="readiness-tool-parameter-missing-description"></a>
### `readiness.tool-parameter-missing-description`

- **Category:** readiness
- **Severity:** warning
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- **Rationale:** An undocumented parameter forces an agent to infer its meaning from its name.
- **Requires transcript:** False

<a id="readiness-tool-parameter-unconstrained"></a>
### `readiness.tool-parameter-unconstrained`

- **Category:** readiness
- **Severity:** info
- **Spec version:** 2025-06-18
- **Spec reference:** https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- **Rationale:** A free-text parameter with no enum, format, pattern, or bounds invites invalid arguments an agent cannot self-check.
- **Requires transcript:** False

<a id="readiness-tool-unbounded-list"></a>
### `readiness.tool-unbounded-list`

- **Category:** readiness
- **Severity:** warning
- **Spec version:** 2025-06-18
- **Spec reference:** https://www.anthropic.com/engineering/writing-tools-for-agents
- **Rationale:** A collection-returning tool with no limit/cursor parameter can flood an agent's context with an unbounded result set.
- **Requires transcript:** False
