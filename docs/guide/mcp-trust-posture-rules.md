# MCP trust-posture rules

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_lint_rule_docs.py -->

Catalog for :mod:`app.mcp_trust_posture`, mapped to the OWASP MCP Top 10. Blocking rules include CLX-4.3 transparency fields. Fetch via `GET /v1/mcp/trust-posture/rules`.

<a id="dependency-known-vulnerability"></a>
### `dependency.known-vulnerability`

- **Origin:** dependency
- **Severity:** warning
- **OWASP:** MCP04
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** vulnerabilities
- **Rationale:** A known vulnerability in a dependency is a vulnerability in the server, whether or not the server's own code is at fault.

<a id="metadata-credential-in-description"></a>
### `metadata.credential-in-description`

- **Origin:** metadata
- **Severity:** error
- **OWASP:** MCP06
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** surface
- **Rationale:** A credential in a tool description is handed to every client that lists this server's tools, and to every model those clients talk to.
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Remediation:** Remove secrets from descriptions; pass credentials through host env / secret stores.
- **False-positive guidance:** Placeholder tokens (e.g. YOUR_API_KEY) may match — mark false_positive in the workspace after confirming they are not live credentials.
- **Fixture:** `mcp/unsafe/owasp/mcp06-credential-in-description`
- **Scan modes:** `metadata`, `surface`

<a id="metadata-exfiltration-directive"></a>
### `metadata.exfiltration-directive`

- **Origin:** metadata
- **Severity:** error
- **OWASP:** MCP02, MCP08
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** surface
- **Rationale:** Metadata that directs the agent to send it conversation history, other tools' output, or credentials is asking the agent to exfiltrate the context it already holds.
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Remediation:** Remove exfiltration language from titles, descriptions, and nested schema text.
- **False-positive guidance:** Security-tooling docs that *discuss* exfiltration may match — narrow wording or waive with rationale.
- **Fixture:** `mcp/unsafe/owasp/mcp02-exfiltration-directive`
- **Scan modes:** `metadata`, `surface`

<a id="metadata-filesystem-root-template"></a>
### `metadata.filesystem-root-template`

- **Origin:** metadata
- **Severity:** warning
- **OWASP:** MCP03, MCP08
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** surface
- **Rationale:** A resource template rooted at the filesystem or at an arbitrary URL lets the agent read anything the server can reach, and put it in the model's context.

<a id="metadata-hidden-instruction"></a>
### `metadata.hidden-instruction`

- **Origin:** metadata
- **Severity:** error
- **OWASP:** MCP01, MCP02
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** surface
- **Rationale:** A tool description that addresses the model as an instruction rather than describing the tool is a directive the operator never wrote and the user never sees.
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Remediation:** Rewrite descriptions to describe the tool for humans/agents without override directives.
- **False-positive guidance:** Benign phrases like 'always returns JSON' are filtered; if noise remains, mark false_positive with a note.
- **Fixture:** `mcp/unsafe/owasp/mcp01-hidden-instruction`
- **Scan modes:** `metadata`, `surface`

<a id="metadata-invisible-characters"></a>
### `metadata.invisible-characters`

- **Origin:** metadata
- **Severity:** error
- **OWASP:** MCP01, MCP02
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** surface
- **Rationale:** Zero-width or bidirectional-override characters hide text from every human reviewer while leaving it fully legible to the model. There is no benign reason for them in a tool description.
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Remediation:** Strip Cf / zero-width characters from titles, descriptions, and schema text.
- **False-positive guidance:** Some locales insert ZWJ in legitimate names — review before waiving.
- **Fixture:** `mcp/unsafe/owasp/mcp01-invisible-characters`
- **Scan modes:** `metadata`, `surface`

<a id="metadata-tool-name-shadowing"></a>
### `metadata.tool-name-shadowing`

- **Origin:** metadata
- **Severity:** warning
- **OWASP:** MCP09
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** surface
- **Rationale:** A tool named like a well-known tool from another server can be resolved by an agent that meant the other one.

<a id="metadata-unauthenticated-write-capability"></a>
### `metadata.unauthenticated-write-capability`

- **Origin:** metadata
- **Severity:** warning
- **OWASP:** MCP07
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** surface
- **Rationale:** A server exposing state-changing tools while advertising no authentication is either unauthenticated or undocumented, and a reviewer cannot tell which.

<a id="metadata-unconstrained-command-parameter"></a>
### `metadata.unconstrained-command-parameter`

- **Origin:** metadata
- **Severity:** warning
- **OWASP:** MCP03, MCP05
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** surface
- **Rationale:** A tool taking a free-form command, query, path, or script has the authority of whatever it passes that string to — which is far more than the tool's name implies.

<a id="metadata-undeclared-destructive-tool"></a>
### `metadata.undeclared-destructive-tool`

- **Origin:** metadata
- **Severity:** warning
- **OWASP:** MCP03, MCP10
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** surface
- **Rationale:** A tool that deletes, drops, or overwrites without the destructiveHint annotation reads to a client exactly like one that does not — so no client can warn a user before it runs.

<a id="protocol-proven-auth-bypass"></a>
### `protocol.proven-auth-bypass`

- **Origin:** protocol
- **Severity:** error
- **OWASP:** MCP07
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** probe
- **Rationale:** A dynamic probe obtained privileged data from the server without authorization. This is not a signal to review — it is a reproduced authorization bypass.
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Remediation:** Enforce authorization on every method, including capability listings; serve no data to an unauthenticated or unauthorized caller.
- **False-positive guidance:** Only fires with exploit-tier probe evidence — never from static patterns. If a probe harness is mis-flagged, fix the probe before waiving.
- **Fixture:** `mcp/unsafe/owasp/mcp07-proven-auth-bypass`
- **Scan modes:** `probe`, `requires_probe`

<a id="protocol-proven-input-injection"></a>
### `protocol.proven-input-injection`

- **Origin:** protocol
- **Severity:** error
- **OWASP:** MCP01
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** probe
- **Rationale:** A dynamic probe demonstrated that attacker-controlled input reaches a tool's output path unescaped — a reproduced injection, not a static indicator.
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Remediation:** Escape or reject untrusted input in tool output; never echo caller-supplied strings into model-visible content without sanitization.
- **False-positive guidance:** Requires consent-gated exploit probe evidence. Observed-only probes never upgrade to proven findings.
- **Fixture:** `mcp/unsafe/owasp/mcp01-proven-input-injection`
- **Scan modes:** `probe`, `requires_probe`

<a id="source-broad-filesystem-mount"></a>
### `source.broad-filesystem-mount`

- **Origin:** source
- **Severity:** warning
- **OWASP:** MCP03, MCP08
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** A broad host mount lets the server read the host — and hand what it reads to the agent.

<a id="source-broad-oauth-scope"></a>
### `source.broad-oauth-scope`

- **Origin:** source
- **Severity:** warning
- **OWASP:** MCP03, MCP07
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** The blast radius of a compromise is the authority granted, not the authority used.

<a id="source-committed-private-key"></a>
### `source.committed-private-key`

- **Origin:** source
- **Severity:** error
- **OWASP:** MCP06
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** A committed private key stays in git history after the file is deleted.
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Remediation:** Rotate the key, purge it from history, and load secrets from a secret manager.
- **False-positive guidance:** Obviously fake PEM training fixtures may match — quarantine them outside scanned paths or mark false_positive.
- **Fixture:** `mcp/unsafe/owasp/mcp06-committed-private-key`
- **Scan modes:** `source`, `requires_source`

<a id="source-dynamic-code-evaluation"></a>
### `source.dynamic-code-evaluation`

- **Origin:** source
- **Severity:** warning
- **OWASP:** MCP05
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** Runtime code evaluation turns any injection into arbitrary code execution.

<a id="source-hardcoded-provider-credential"></a>
### `source.hardcoded-provider-credential`

- **Origin:** source
- **Severity:** error
- **OWASP:** MCP06
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** A recognizable provider credential in source is readable by everyone with repository access, and by everyone who ever had it.
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Remediation:** Remove the credential, rotate it, and inject via environment / vault.
- **False-positive guidance:** Documented example keys (AKIAIOSFODNN7EXAMPLE) are intentional corpus fixtures; production repos should not contain them.
- **Fixture:** `mcp/unsafe/owasp/mcp06-hardcoded-provider-credential`
- **Scan modes:** `source`, `requires_source`

<a id="source-high-entropy-secret"></a>
### `source.high-entropy-secret`

- **Origin:** source
- **Severity:** warning
- **OWASP:** MCP06
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** A credential-shaped, high-entropy literal is more likely a live secret than a placeholder.

<a id="source-host-network-access"></a>
### `source.host-network-access`

- **Origin:** source
- **Severity:** warning
- **OWASP:** MCP03
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** Host networking reaches services that believe they are only reachable from localhost.

<a id="source-permissive-cors"></a>
### `source.permissive-cors`

- **Origin:** source
- **Severity:** warning
- **OWASP:** MCP07
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** Wildcard CORS with credentials lets any page a user visits drive the server as that user.

<a id="source-privileged-container"></a>
### `source.privileged-container`

- **Origin:** source
- **Severity:** error
- **OWASP:** MCP03
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** A privileged container is not a boundary: compromising the server compromises the host.
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Remediation:** Drop `privileged: true` and grant only the capabilities the workload needs.
- **False-positive guidance:** Lab-only compose files used solely in CI may be waived with expiry.
- **Fixture:** `mcp/unsafe/owasp/mcp03-privileged-container`
- **Scan modes:** `source`, `requires_source`

<a id="source-remote-script-execution"></a>
### `source.remote-script-execution`

- **Origin:** source
- **Severity:** error
- **OWASP:** MCP04, MCP05
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** Piping a downloaded script into a shell gives whoever controls that URL control of the build.
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Remediation:** Vendor scripts, pin digests, and install via package managers with checksums.
- **False-positive guidance:** Comments describing the anti-pattern may match — keep discussions out of scannable Dockerfile/`*.sh` files.
- **Fixture:** `mcp/unsafe/owasp/mcp04-remote-script-execution`
- **Scan modes:** `source`, `requires_source`

<a id="source-tls-verification-disabled"></a>
### `source.tls-verification-disabled`

- **Origin:** source
- **Severity:** error
- **OWASP:** MCP07
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** Unverified TLS is encrypted but unauthenticated, and defenceless against an active attacker.
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Remediation:** Enable certificate verification; remove `-k` / `verify=False` / reject-unauthorized=0.
- **False-positive guidance:** Local-dev overrides in non-production configs may be waived with environment scope.
- **Fixture:** `mcp/unsafe/owasp/mcp07-tls-verification-disabled`
- **Scan modes:** `source`, `requires_source`

<a id="source-unpinned-base-image"></a>
### `source.unpinned-base-image`

- **Origin:** source
- **Severity:** warning
- **OWASP:** MCP04
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** An unpinned base image means the artifact reviewed and the artifact deployed may differ.

<a id="source-unpinned-reference"></a>
### `source.unpinned-reference`

- **Origin:** source
- **Severity:** warning
- **OWASP:** MCP04
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source_link
- **Rationale:** A source linked by a moving reference cannot be re-scanned to the same bytes, so no finding about it — including a clean result — is reproducible.

<a id="source-unsafe-command-execution"></a>
### `source.unsafe-command-execution`

- **Origin:** source
- **Severity:** warning
- **OWASP:** MCP05
- **Reference:** https://owasp.org/www-project-mcp-top-10/
- **Requires:** source
- **Rationale:** A shell reachable from tool arguments is a shell reachable from an untrusted prompt.
