"""Trust-posture rule packs: metadata, source, and dependency origins (CLX-3.2, #4856).

The concrete rules behind :mod:`app.mcp_trust_posture`. Three packs, one per evidence lane, each
registering itself on import:

* **metadata** — reads the discovery surface: what the server *says about itself*. Runs for every
  catalogued endpoint, needs nothing but the stored snapshot, and is fully recomputable offline.
* **source** — folds in :mod:`app.mcp_static_checks`: what the server's *artifact contains*. Needs a
  linked source; skipped and reported when there is none.
* **dependency** — folds in :mod:`app.mcp_vulnerability`: what the server *pulls in*. Needs a
  completed vulnerability lookup; skipped and reported when it did not run.

The metadata pack is the interesting one, because it is reasoning about *adversarial text*. A tool
description is written by the server and read by a model, which makes it an injection surface: the
model cannot distinguish "here is what this tool does" from "ignore your previous instructions".
These rules look for the shapes that abuse gets written in — hidden instructions, invisible
characters, tool names that impersonate other servers' tools, resource templates rooted at ``/``.

What these rules do NOT claim
-----------------------------
Every finding here is a **signal**, and the engine makes that structural: :func:`make_finding` cannot
produce anything else. A tool whose description contains "ignore previous instructions" is a strong
indicator of poisoning, but a static reading cannot prove the server is malicious — the phrase could
appear in a tool that legitimately *documents* prompt-injection defenses. So the rule fires, the
reviewer looks, and nothing in the report says "exploitable". Proving that needs a dynamic probe,
which is CLX-3.3 (#4857).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .mcp_client.normalize import CapabilityItem, DiscoverySurface
from .mcp_lint import item_path
from .mcp_owasp import (
    MCP01_PROMPT_INJECTION,
    MCP02_TOOL_POISONING,
    MCP03_EXCESSIVE_PERMISSIONS,
    MCP04_SUPPLY_CHAIN,
    MCP05_COMMAND_EXECUTION,
    MCP06_SECRET_EXPOSURE,
    MCP07_AUTH_FAILURE,
    MCP08_CONTEXT_OVERSHARING,
    MCP09_TOOL_SHADOWING,
    MCP10_INSUFFICIENT_AUDIT,
)
from .mcp_source_link import CONFIDENCE_HIGH
from .mcp_static_checks import owasp_ids_for_rule, redact
from .mcp_static_checks import rule_ids as static_rule_ids
from .mcp_trust_posture import (
    ORIGIN_DEPENDENCY,
    ORIGIN_METADATA,
    ORIGIN_SOURCE,
    REQUIRES_SOURCE,
    REQUIRES_SOURCE_LINK,
    REQUIRES_SURFACE,
    REQUIRES_VULNERABILITIES,
    PostureContext,
    PostureFinding,
    PostureRule,
    make_finding,
    posture_rule,
    register_rules,
)

# --- Rule ids ------------------------------------------------------------------------------------
# Stable, never renamed once shipped: hashed into finding ids and the report fingerprint.

RULE_POISONING_HIDDEN_INSTRUCTION = "metadata.hidden-instruction"
RULE_POISONING_INVISIBLE_TEXT = "metadata.invisible-characters"
RULE_POISONING_EXFILTRATION_HINT = "metadata.exfiltration-directive"
RULE_SECRET_IN_METADATA = "metadata.credential-in-description"
RULE_SCOPE_CREEP = "metadata.unconstrained-command-parameter"
RULE_SHADOWING = "metadata.tool-name-shadowing"
RULE_OVERSHARING_ROOT_TEMPLATE = "metadata.filesystem-root-template"
RULE_AUTH_UNDECLARED_WRITE = "metadata.unauthenticated-write-capability"
RULE_AUDIT_UNDECLARED_DESTRUCTIVE = "metadata.undeclared-destructive-tool"

RULE_DEPENDENCY_VULNERABILITY = "dependency.known-vulnerability"
RULE_UNPINNED_SOURCE = "source.unpinned-reference"


# --- Metadata pack: descriptors -------------------------------------------------------------------

_METADATA_RULES: Tuple[PostureRule, ...] = (
    PostureRule(
        rule_id=RULE_POISONING_HIDDEN_INSTRUCTION,
        origin=ORIGIN_METADATA,
        severity="error",
        owasp_ids=(MCP01_PROMPT_INJECTION, MCP02_TOOL_POISONING),
        rationale=(
            "A tool description that addresses the model as an instruction rather than describing "
            "the tool is a directive the operator never wrote and the user never sees."
        ),
    ),
    PostureRule(
        rule_id=RULE_POISONING_INVISIBLE_TEXT,
        origin=ORIGIN_METADATA,
        severity="error",
        owasp_ids=(MCP01_PROMPT_INJECTION, MCP02_TOOL_POISONING),
        rationale=(
            "Zero-width or bidirectional-override characters hide text from every human reviewer "
            "while leaving it fully legible to the model. There is no benign reason for them in a "
            "tool description."
        ),
    ),
    PostureRule(
        rule_id=RULE_POISONING_EXFILTRATION_HINT,
        origin=ORIGIN_METADATA,
        severity="error",
        owasp_ids=(MCP02_TOOL_POISONING, MCP08_CONTEXT_OVERSHARING),
        rationale=(
            "Metadata that directs the agent to send it conversation history, other tools' output, "
            "or credentials is asking the agent to exfiltrate the context it already holds."
        ),
    ),
    PostureRule(
        rule_id=RULE_SECRET_IN_METADATA,
        origin=ORIGIN_METADATA,
        severity="error",
        owasp_ids=(MCP06_SECRET_EXPOSURE,),
        rationale=(
            "A credential in a tool description is handed to every client that lists this server's "
            "tools, and to every model those clients talk to."
        ),
    ),
    PostureRule(
        rule_id=RULE_SCOPE_CREEP,
        origin=ORIGIN_METADATA,
        severity="warning",
        owasp_ids=(MCP03_EXCESSIVE_PERMISSIONS, MCP05_COMMAND_EXECUTION),
        rationale=(
            "A tool taking a free-form command, query, path, or script has the authority of "
            "whatever it passes that string to — which is far more than the tool's name implies."
        ),
    ),
    PostureRule(
        rule_id=RULE_SHADOWING,
        origin=ORIGIN_METADATA,
        severity="warning",
        owasp_ids=(MCP09_TOOL_SHADOWING,),
        rationale=(
            "A tool named like a well-known tool from another server can be resolved by an agent "
            "that meant the other one."
        ),
    ),
    PostureRule(
        rule_id=RULE_OVERSHARING_ROOT_TEMPLATE,
        origin=ORIGIN_METADATA,
        severity="warning",
        owasp_ids=(MCP03_EXCESSIVE_PERMISSIONS, MCP08_CONTEXT_OVERSHARING),
        rationale=(
            "A resource template rooted at the filesystem or at an arbitrary URL lets the agent "
            "read anything the server can reach, and put it in the model's context."
        ),
    ),
    PostureRule(
        rule_id=RULE_AUTH_UNDECLARED_WRITE,
        origin=ORIGIN_METADATA,
        severity="warning",
        owasp_ids=(MCP07_AUTH_FAILURE,),
        rationale=(
            "A server exposing state-changing tools while advertising no authentication is either "
            "unauthenticated or undocumented, and a reviewer cannot tell which."
        ),
    ),
    PostureRule(
        rule_id=RULE_AUDIT_UNDECLARED_DESTRUCTIVE,
        origin=ORIGIN_METADATA,
        severity="warning",
        owasp_ids=(MCP10_INSUFFICIENT_AUDIT, MCP03_EXCESSIVE_PERMISSIONS),
        rationale=(
            "A tool that deletes, drops, or overwrites without the destructiveHint annotation "
            "reads to a client exactly like one that does not — so no client can warn a user "
            "before it runs."
        ),
    ),
)

register_rules(_METADATA_RULES)


# --- Metadata pack: detection --------------------------------------------------------------------

#: Phrasing that addresses the *model* rather than describing the tool. Deliberately narrow: a rule
#: that fired on every imperative sentence ("Use this to search…") would be useless, so these target
#: the specific shape of an instruction that tries to override the agent's existing directives.
_HIDDEN_INSTRUCTION_RE = re.compile(
    r"""(?ix)
    (?: ignore \s+ (?:all \s+)? (?:previous|prior|above|earlier) \s+ (?:instruction|prompt|rule|direction)
      | disregard \s+ (?:previous|prior|the \s+ above|your) \s+ \w+
      | you \s+ (?:must|should|will) \s+ (?:always|never|first) \b
      | before \s+ (?:using|calling|running) \s+ any \s+ other \s+ tool
      | do \s+ not \s+ (?:tell|inform|mention \s+ (?:this|it) \s+ to) \s+ the \s+ user
      | \b system \s* (?:prompt|message) \s* :
      | < \s* (?:system|important|secret) \s* >
    )
    """
)

#: Directives that ask the agent to hand over what it is already holding.
_EXFILTRATION_RE = re.compile(
    r"""(?ix)
    (?: (?:send|forward|post|transmit|include|attach) \b [^.]{0,60}?
        \b (?:conversation|chat \s+ history|context|previous \s+ messages|system \s+ prompt
             | credential | api[_\s\-]?key | \.env | ssh \s+ key | token )
      | (?:read|fetch|load) \b [^.]{0,40}? \b (?: ~/\.ssh | /etc/passwd | \.env | id_rsa ) \b
    )
    """
)

#: Unicode categories/codepoints that hide text from humans but not from models. Cf = format
#: characters (zero-width space/joiner, and the bidirectional overrides used in "Trojan Source").
_INVISIBLE_CODEPOINTS = frozenset(
    {
        "​",  # zero-width space
        "‌",  # zero-width non-joiner
        "‍",  # zero-width joiner
        "⁠",  # word joiner
        "﻿",  # zero-width no-break space
        "‪",  # left-to-right embedding
        "‫",  # right-to-left embedding
        "‬",  # pop directional formatting
        "‭",  # left-to-right override
        "‮",  # right-to-left override
        "⁦",  # left-to-right isolate
        "⁧",  # right-to-left isolate
        "⁨",  # first strong isolate
        "⁩",  # pop directional isolate
    }
)

#: Credential shapes in advertised metadata. Reuses the provider formats the source scanner knows,
#: because a leaked key is a leaked key wherever it appears.
_METADATA_SECRET_RE = re.compile(
    r"""(?x)
    (?: \b AKIA[0-9A-Z]{16} \b
      | \b gh[pousr]_[A-Za-z0-9]{36,} \b
      | \b xox[baprs]-[A-Za-z0-9\-]{10,} \b
      | \b sk_live_[A-Za-z0-9]{16,} \b
      | \b sk-[A-Za-z0-9]{32,} \b
      | \b AIza[0-9A-Za-z_\-]{35} \b
      | -----BEGIN \s (?:[A-Z ]+ \s)? PRIVATE \s KEY-----
    )
    """
)

#: Parameter names whose value is passed to something that executes or resolves it. A tool taking one
#: of these as a free-form string has the authority of the thing it hands the string to.
_UNCONSTRAINED_PARAMS = frozenset(
    {"command", "cmd", "shell", "script", "exec", "eval", "code", "query", "sql", "path",
     "file", "filepath", "filename", "url", "uri", "endpoint", "expression"}
)

#: Tool names strongly associated with well-known servers. A server that names a tool this way is
#: either implementing the same well-known contract (fine, and common) or positioning itself to be
#: resolved in place of it (not fine). Static analysis cannot tell those apart, which is exactly why
#: this is a `warning` signal for a human rather than an assertion.
_WELL_KNOWN_TOOL_NAMES = frozenset(
    {
        "read_file", "write_file", "list_directory", "edit_file", "create_file",
        "execute_command", "run_command", "bash", "shell",
        "search", "web_search", "fetch", "browse",
        "send_email", "send_message", "create_issue", "create_pull_request",
        "query_database", "execute_sql",
    }
)

#: Verbs that mean a tool changes state. Used by both the auth rule and the destructive-annotation
#: rule, which ask different questions about the same set.
_WRITE_VERBS = ("create", "update", "delete", "remove", "write", "set", "put", "post",
                "insert", "modify", "patch", "send", "execute", "run", "drop", "purge")

#: The subset that is *irreversible*. Deleting is not the same as updating: a client can reasonably
#: auto-approve one and must not auto-approve the other, and the only way it knows the difference is
#: the destructiveHint annotation.
_DESTRUCTIVE_VERBS = ("delete", "remove", "drop", "purge", "destroy", "truncate", "wipe", "erase")

#: URI-template roots that expose the host filesystem or an arbitrary network target.
_BROAD_TEMPLATE_RE = re.compile(
    r"""(?ix)
    ^ (?: file:// (?: /? \{ | /(?!.*\}.*/) )      # file:///{path} — a template rooted at /
        | file:///? \{
        | https? :// \{                            # http://{host}/… — an arbitrary target
        | \{ )                                     # {anything} at the very root
    """
)


def _item_text(item: CapabilityItem) -> str:
    """All human-readable text an item contributes to the model's context.

    Title, description, and — crucially — every ``description`` inside the input schema. Schema
    property descriptions reach the model exactly like the tool description does, and a poisoning
    payload hidden in a parameter's description is a well-known way to evade a scanner that only
    reads the top-level text.
    """
    parts: List[str] = [item.title or "", item.description or ""]

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in ("description", "title") and isinstance(value, str):
                    parts.append(value)
                else:
                    walk(value)
        elif isinstance(node, (list, tuple)):
            for entry in node:
                walk(entry)

    walk(item.input_schema)
    walk(item.output_schema)
    return "\n".join(p for p in parts if p)


def _invisible_chars(text: str) -> List[str]:
    """The invisible/bidirectional codepoints present in ``text``, sorted and de-duplicated."""
    found = {ch for ch in text if ch in _INVISIBLE_CODEPOINTS or unicodedata.category(ch) == "Cf"}
    return sorted(found)


def _schema_properties(item: CapabilityItem) -> Dict[str, Mapping[str, Any]]:
    """The item's input-schema properties, or an empty map when it declares none."""
    schema = item.input_schema
    if not isinstance(schema, Mapping):
        return {}
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    return {
        str(name): value for name, value in properties.items() if isinstance(value, Mapping)
    }


def _is_constrained(schema: Mapping[str, Any]) -> bool:
    """True when a parameter's schema bounds what may be passed to it.

    An ``enum``, a ``pattern``, a ``maxLength``, or a non-string type all narrow the value. A bare
    ``{"type": "string"}`` narrows nothing — it accepts any command, any path, any URL.
    """
    if any(key in schema for key in ("enum", "const", "pattern", "maxLength", "format")):
        return True
    schema_type = schema.get("type")
    return bool(schema_type) and schema_type != "string"


def _declares_auth(surface: DiscoverySurface) -> bool:
    """True when the server advertises any authentication requirement.

    Reads the declared capabilities, the instructions text, and the raw server info — MCP has no
    single normative "auth" field, so a server may legitimately state it in any of them, and a rule
    that only checked one would flag well-behaved servers.
    """
    haystack = json_lower(surface.capabilities) + " " + (surface.instructions or "").lower()
    return any(
        marker in haystack
        for marker in ("auth", "oauth", "bearer", "token", "api key", "api_key", "credential")
    )


def json_lower(value: Any) -> str:
    """Flatten a nested structure into a lowercase string for coarse keyword presence checks."""
    if isinstance(value, Mapping):
        return " ".join(
            f"{str(k).lower()} {json_lower(v)}" for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return " ".join(json_lower(v) for v in value)
    return str(value).lower()


def _annotation(item: CapabilityItem, key: str) -> Optional[Any]:
    """Read one MCP annotation from an item, tolerating a server that omits the block entirely."""
    annotations = item.annotations
    if not isinstance(annotations, Mapping):
        return None
    return annotations.get(key)


@posture_rule(requires=REQUIRES_SURFACE)
def _rule_metadata_poisoning(
    context: PostureContext, findings: List[PostureFinding]
) -> None:
    """Detect tool-poisoning and prompt-injection shapes in advertised metadata.

    Three distinct abuses, reported separately because they call for different responses: text that
    *instructs* the model, text that is *invisible* to a reviewer, and text that asks the agent to
    *exfiltrate* what it holds.
    """
    surface = context.surface
    for item in surface.all_items():
        path = item_path(item)
        text = _item_text(item)
        if not text:
            continue

        if _HIDDEN_INSTRUCTION_RE.search(text):
            findings.append(
                make_finding(
                    path,
                    RULE_POISONING_HIDDEN_INSTRUCTION,
                    (
                        f"The {item.item_type}'s advertised text addresses the model as an "
                        f"instruction rather than describing the capability. A model reading this "
                        f"cannot distinguish it from a directive its operator wrote."
                    ),
                    remediation=(
                        "Rewrite the description to describe what the capability does. If the "
                        "server is not yours, treat this as a poisoning indicator and review "
                        "before enabling it."
                    ),
                )
            )

        invisible = _invisible_chars(text)
        if invisible:
            codepoints = ", ".join(f"U+{ord(ch):04X}" for ch in invisible[:6])
            findings.append(
                make_finding(
                    path,
                    RULE_POISONING_INVISIBLE_TEXT,
                    (
                        f"The {item.item_type}'s advertised text contains {len(invisible)} "
                        f"invisible or bidirectional-override character(s) ({codepoints}). They are "
                        f"hidden from every human reviewer and fully legible to the model."
                    ),
                    remediation=(
                        "Strip the characters and re-read the description as the model sees it. "
                        "There is no legitimate reason for them in a capability description."
                    ),
                )
            )

        if _EXFILTRATION_RE.search(text):
            findings.append(
                make_finding(
                    path,
                    RULE_POISONING_EXFILTRATION_HINT,
                    (
                        f"The {item.item_type}'s advertised text directs the agent toward "
                        f"conversation history, credentials, or sensitive local files. This asks "
                        f"the agent to hand over context it already holds."
                    ),
                    remediation=(
                        "Do not enable this capability until the server's operator explains why "
                        "its description references that material."
                    ),
                )
            )

        secret = _METADATA_SECRET_RE.search(text)
        if secret:
            findings.append(
                make_finding(
                    path,
                    RULE_SECRET_IN_METADATA,
                    (
                        f"The {item.item_type}'s advertised text contains what looks like a live "
                        f"credential ({redact(secret.group(0))}). Every client that lists this "
                        f"server's capabilities has already received it."
                    ),
                    remediation=(
                        "Treat the credential as compromised and rotate it now; then remove it "
                        "from the capability description."
                    ),
                )
            )


@posture_rule(requires=REQUIRES_SURFACE)
def _rule_scope_and_authority(
    context: PostureContext, findings: List[PostureFinding]
) -> None:
    """Flag unconstrained execution-shaped parameters, shadowed names, and broad resource roots."""
    surface = context.surface

    for item in surface.tools:
        path = item_path(item)

        for name, schema in _schema_properties(item).items():
            if name.lower() in _UNCONSTRAINED_PARAMS and not _is_constrained(schema):
                findings.append(
                    make_finding(
                        f"{path}.{name}",
                        RULE_SCOPE_CREEP,
                        (
                            f"Parameter '{name}' is an unconstrained string. Whatever this tool "
                            f"passes it to, an agent can supply any value — so the tool's real "
                            f"authority is that of its backend, not of its name."
                        ),
                        remediation=(
                            f"Constrain '{name}' with an enum, a pattern, or a narrower type, so "
                            f"the schema states what the tool actually accepts."
                        ),
                    )
                )

        if item.name and item.name.lower() in _WELL_KNOWN_TOOL_NAMES:
            findings.append(
                make_finding(
                    path,
                    RULE_SHADOWING,
                    (
                        f"Tool '{item.name}' takes the name of a well-known tool. An agent "
                        f"resolving tools by name may invoke this server's version instead of the "
                        f"one it meant."
                    ),
                    remediation=(
                        "Namespace the tool (e.g. 'acme_read_file') so an agent's choice between "
                        "two servers is explicit rather than incidental."
                    ),
                )
            )

    for item in (*surface.resource_templates, *surface.resources):
        template = item.uri_template or item.uri
        if template and _BROAD_TEMPLATE_RE.search(template):
            findings.append(
                make_finding(
                    item_path(item),
                    RULE_OVERSHARING_ROOT_TEMPLATE,
                    (
                        f"Resource template '{template}' is rooted at the filesystem or at an "
                        f"arbitrary target, so the agent can read anything the server can reach "
                        f"and place it in the model's context."
                    ),
                    remediation=(
                        "Root the template at a specific directory or host, so its scope is stated "
                        "in the template rather than left to the caller."
                    ),
                )
            )


@posture_rule(requires=REQUIRES_SURFACE)
def _rule_auth_and_audit(
    context: PostureContext, findings: List[PostureFinding]
) -> None:
    """Flag state-changing capability advertised without auth, and destructive tools left unannotated."""
    surface = context.surface
    declares_auth = _declares_auth(surface)

    for item in surface.tools:
        name = (item.name or "").lower()
        path = item_path(item)

        # read_only_hint=True is the server explicitly saying "this changes nothing". Take it at its
        # word here: if it is lying, that is a conformance problem, not a posture one, and
        # double-reporting it would just make both reports noisier.
        if _annotation(item, "readOnlyHint") is True:
            continue

        is_write = any(name.startswith(verb) or f"_{verb}" in name for verb in _WRITE_VERBS)
        is_destructive = any(
            name.startswith(verb) or f"_{verb}" in name for verb in _DESTRUCTIVE_VERBS
        )

        if is_write and not declares_auth:
            findings.append(
                make_finding(
                    path,
                    RULE_AUTH_UNDECLARED_WRITE,
                    (
                        f"Tool '{item.name}' changes state, but the server advertises no "
                        f"authentication requirement anywhere in its capabilities or instructions. "
                        f"A reviewer cannot tell whether it is unauthenticated or merely "
                        f"undocumented."
                    ),
                    remediation=(
                        "Declare the server's authentication requirement in its capabilities or "
                        "instructions — or, if there genuinely is none, do not expose "
                        "state-changing tools."
                    ),
                )
            )

        if is_destructive and _annotation(item, "destructiveHint") is not True:
            findings.append(
                make_finding(
                    path,
                    RULE_AUDIT_UNDECLARED_DESTRUCTIVE,
                    (
                        f"Tool '{item.name}' performs an irreversible operation but does not set "
                        f"the destructiveHint annotation, so a client cannot distinguish it from a "
                        f"reversible one and cannot warn the user before it runs."
                    ),
                    remediation=(
                        "Set annotations.destructiveHint = true so clients can require explicit "
                        "confirmation before invoking it."
                    ),
                )
            )


# --- Source pack ---------------------------------------------------------------------------------
# The static checks already produce well-formed, located, redacted findings. This pack's whole job is
# to register a descriptor for each of their rule ids and fold their output into the posture report —
# it re-implements nothing.

#: Severity per static rule. Executing remote scripts and committing live credentials are `error`;
#: the rest are `warning` signals a reviewer should confirm.
_STATIC_SEVERITY: Mapping[str, str] = {
    "source.hardcoded-provider-credential": "error",
    "source.committed-private-key": "error",
    "source.high-entropy-secret": "warning",
    "source.unsafe-command-execution": "warning",
    "source.dynamic-code-evaluation": "warning",
    "source.remote-script-execution": "error",
    "source.tls-verification-disabled": "error",
    "source.permissive-cors": "warning",
    "source.privileged-container": "error",
    "source.host-network-access": "warning",
    "source.broad-filesystem-mount": "warning",
    "source.unpinned-base-image": "warning",
    "source.broad-oauth-scope": "warning",
}

#: One-line rationale per static rule, for the rules catalog.
_STATIC_RATIONALE: Mapping[str, str] = {
    "source.hardcoded-provider-credential": (
        "A recognizable provider credential in source is readable by everyone with repository "
        "access, and by everyone who ever had it."
    ),
    "source.committed-private-key": (
        "A committed private key stays in git history after the file is deleted."
    ),
    "source.high-entropy-secret": (
        "A credential-shaped, high-entropy literal is more likely a live secret than a placeholder."
    ),
    "source.unsafe-command-execution": (
        "A shell reachable from tool arguments is a shell reachable from an untrusted prompt."
    ),
    "source.dynamic-code-evaluation": (
        "Runtime code evaluation turns any injection into arbitrary code execution."
    ),
    "source.remote-script-execution": (
        "Piping a downloaded script into a shell gives whoever controls that URL control of the build."
    ),
    "source.tls-verification-disabled": (
        "Unverified TLS is encrypted but unauthenticated, and defenceless against an active attacker."
    ),
    "source.permissive-cors": (
        "Wildcard CORS with credentials lets any page a user visits drive the server as that user."
    ),
    "source.privileged-container": (
        "A privileged container is not a boundary: compromising the server compromises the host."
    ),
    "source.host-network-access": (
        "Host networking reaches services that believe they are only reachable from localhost."
    ),
    "source.broad-filesystem-mount": (
        "A broad host mount lets the server read the host — and hand what it reads to the agent."
    ),
    "source.unpinned-base-image": (
        "An unpinned base image means the artifact reviewed and the artifact deployed may differ."
    ),
    "source.broad-oauth-scope": (
        "The blast radius of a compromise is the authority granted, not the authority used."
    ),
}

register_rules(
    tuple(
        PostureRule(
            rule_id=rule_id,
            origin=ORIGIN_SOURCE,
            severity=_STATIC_SEVERITY.get(rule_id, "warning"),
            owasp_ids=owasp_ids_for_rule(rule_id),
            rationale=_STATIC_RATIONALE.get(rule_id, "Static source/config posture check."),
            requires=REQUIRES_SOURCE,
        )
        for rule_id in static_rule_ids()
    )
)


@posture_rule(requires=REQUIRES_SOURCE)
def _rule_static_source(context: PostureContext, findings: List[PostureFinding]) -> None:
    """Fold the static source/config scan into the posture report.

    Confidence comes from the *source*, not the rule: the pattern match is equally certain either
    way, but a finding read from a floating branch describes whatever that branch pointed at when it
    was fetched, which may no longer be what the endpoint runs. That distinction belongs on the
    finding, and :func:`app.mcp_source_link.confidence_for_link` is where it is decided.
    """
    scan = context.static_scan
    if scan is None:  # pragma: no cover - the engine will not call us without REQUIRES_SOURCE
        return

    confidence = context.confidence
    for static in scan.findings:
        findings.append(
            make_finding(
                static.location(),
                static.rule,
                static.message,
                confidence=confidence,
                excerpt=static.excerpt,
            )
        )


# --- Dependency pack -----------------------------------------------------------------------------

register_rules(
    (
        PostureRule(
            rule_id=RULE_DEPENDENCY_VULNERABILITY,
            origin=ORIGIN_DEPENDENCY,
            severity="warning",  # per-finding severity is overridden from the advisory's own rating
            owasp_ids=(MCP04_SUPPLY_CHAIN,),
            rationale=(
                "A known vulnerability in a dependency is a vulnerability in the server, whether or "
                "not the server's own code is at fault."
            ),
            requires=REQUIRES_VULNERABILITIES,
        ),
        PostureRule(
            rule_id=RULE_UNPINNED_SOURCE,
            origin=ORIGIN_SOURCE,
            severity="warning",
            owasp_ids=(MCP04_SUPPLY_CHAIN,),
            rationale=(
                "A source linked by a moving reference cannot be re-scanned to the same bytes, so "
                "no finding about it — including a clean result — is reproducible."
            ),
            # Only the source *link* is needed to judge its pin state — not its fetched files — so
            # this rule runs the moment a source is linked, even on an offline recompute.
            requires=REQUIRES_SOURCE_LINK,
        ),
    )
)


@posture_rule(requires=REQUIRES_VULNERABILITIES)
def _rule_dependency_vulnerabilities(
    context: PostureContext, findings: List[PostureFinding]
) -> None:
    """Fold known dependency vulnerabilities into the posture report.

    Severity comes from the advisory's own published rating rather than the rule descriptor's, so a
    critical CVE and a low-severity one do not land in the report as equals. That is why these
    findings are built directly rather than through :func:`make_finding` — which is safe here
    precisely because the one field it exists to control, ``exploitability``, is left at its
    :data:`app.mcp_trust_posture.EXPLOITABILITY_SIGNAL` default: a published advisory says the
    *dependency* is vulnerable, not that this *server* is exploitable through it. Reachability is a
    dynamic question (CLX-3.3).
    """
    report = context.vulnerabilities
    if report is None or not report.ran:  # pragma: no cover - guarded by REQUIRES_VULNERABILITIES
        return

    for vuln in report.vulnerabilities:
        findings.append(
            PostureFinding(
                path=vuln.purl or vuln.component,
                category=ORIGIN_DEPENDENCY,
                rule=RULE_DEPENDENCY_VULNERABILITY,
                severity=vuln.severity,
                message=vuln.message(),
                origin=ORIGIN_DEPENDENCY,
                owasp_ids=(MCP04_SUPPLY_CHAIN,),
                confidence=CONFIDENCE_HIGH,
                remediation=(
                    f"Upgrade {vuln.component} to {vuln.fixed_version} or later."
                    if vuln.fixed_version
                    else f"No fixed version is published for {vuln.vuln_id}; assess whether the "
                    f"affected code path is reachable, or replace the dependency."
                ),
            )
        )


@posture_rule(requires=REQUIRES_SOURCE_LINK)
def _rule_unpinned_source(context: PostureContext, findings: List[PostureFinding]) -> None:
    """Flag a source linked by a moving reference rather than an immutable digest.

    This is the rule that makes the pin strength *visible in the report* rather than buried in the
    source record. Without it, a scan of a floating ``main`` branch produces findings that look
    exactly as authoritative as a scan of a pinned commit — and a reader has no way to know that
    re-running it tomorrow might scan something else entirely.
    """
    source = context.source
    if source is None or source.is_pinned:
        return

    findings.append(
        make_finding(
            source.locator,
            RULE_UNPINNED_SOURCE,
            (
                f"The linked {source.source_kind} source is not pinned to an immutable digest"
                f"{f' (revision: {source.revision})' if source.revision else ''}. Everything scanned "
                f"here describes whatever that reference resolved to at scan time, which is not "
                f"necessarily what this endpoint is running now."
            ),
            confidence=context.confidence,
            remediation=(
                "Re-link the source pinned to a commit sha, an exact package version, or an image "
                "digest, so its findings are reproducible."
            ),
        )
    )
