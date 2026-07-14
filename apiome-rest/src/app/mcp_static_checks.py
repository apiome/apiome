"""Static inspection of an MCP server's source, manifests, and config (CLX-3.2, #4856).

The source-origin half of the trust-posture scan. Where :mod:`app.mcp_trust_posture_rules` reads
what a server *says about itself* over the wire, this module reads what its *artifact* actually
contains: the shell commands its entrypoint runs, the TLS verification its client disables, the
wildcard CORS its server sets, the AWS key someone committed to ``.env``.

Every finding keeps a **source location** (path + line + a redacted excerpt), because a supply-chain
finding a reviewer cannot navigate to is a finding they cannot act on.

Secrets are detected, never echoed
----------------------------------
The secret rules are the sharp edge here: a scanner that reports "found an AWS key" by *printing the
AWS key* into a database row, an API response, and a UI panel has not reduced the exposure — it has
widened it, and into a system with a different audience than the repository had.

So no detected secret ever leaves this module in the clear. :func:`redact` keeps a short,
non-reversible prefix and masks the rest; findings carry the mask, the match's Shannon entropy, and
its location. That is enough for a human to find it in their own repository — where they can already
read it — and not enough for Apiome's storage or its UI to become a second copy of the credential.

Pure and deterministic
----------------------
No network, no filesystem, no database. The caller passes text it has already fetched, and the same
text always produces the same findings in the same order. This module never fetches an artifact, so
scanning a hostile source cannot make Apiome connect anywhere on that source's behalf.

Ceilings, not silence
---------------------
Files longer than :data:`MAX_SCANNED_LINES` are scanned up to the cap and the shortfall is
*reported* (:attr:`StaticScanResult.truncated_files`), never quietly dropped. A partial scan that
looks complete is the failure mode this whole subsystem is built to avoid.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Pattern, Sequence, Tuple

from .mcp_owasp import (
    MCP03_EXCESSIVE_PERMISSIONS,
    MCP04_SUPPLY_CHAIN,
    MCP05_COMMAND_EXECUTION,
    MCP06_SECRET_EXPOSURE,
    MCP07_AUTH_FAILURE,
    MCP08_CONTEXT_OVERSHARING,
)

#: Longest a single scanned file may be, in lines. A pathological artifact must not be able to turn
#: one scan into an unbounded one; the shortfall is counted and reported, never silently ignored.
MAX_SCANNED_LINES = 20_000

#: Longest excerpt retained from a matching line, in characters. Excerpts exist to orient a reviewer,
#: not to reproduce the file.
MAX_EXCERPT = 160

#: Shannon-entropy floor (bits/char) for the generic secret rule. Below it, a long ``token = "..."``
#: assignment is far more likely to be a placeholder or a description than a live credential, and
#: reporting those trains people to ignore the rule.
ENTROPY_THRESHOLD = 3.4

#: Minimum length for a generic high-entropy secret candidate.
MIN_SECRET_LENGTH = 16


@dataclass(frozen=True)
class SourceDocument:
    """One file from a linked source, as text the caller has already read.

    Attributes:
        path: Repository-relative path. Retained on every finding so a reviewer can navigate to it.
        text: The file's content. Consumed here and never persisted — only findings survive, and a
            finding carries at most a redacted excerpt of one line.
    """

    path: str
    text: str

    @property
    def basename(self) -> str:
        """The file's name without its directories (selects which rules apply)."""
        return self.path.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class StaticFinding:
    """One static defect found in a source artifact.

    Attributes:
        rule: The dotted rule id (e.g. ``source.unsafe-command-execution``).
        path: The file the defect is in.
        line: 1-indexed line number.
        message: Human-readable description. Never contains secret material.
        excerpt: A redacted, length-bounded excerpt of the offending line, for orientation.
        owasp_ids: The OWASP MCP risks this defect is an instance of.
        entropy: Shannon entropy of the matched candidate, for the secret rules. ``None`` elsewhere.
    """

    rule: str
    path: str
    line: int
    message: str
    excerpt: str = ""
    owasp_ids: Tuple[str, ...] = ()
    entropy: Optional[float] = None

    def location(self) -> str:
        """The finding's ``path:line`` location, as the trust-posture finding path."""
        return f"{self.path}:{self.line}"

    def as_dict(self) -> Dict[str, Any]:
        """Return the finding as a JSON-ready dict."""
        return {
            "rule": self.rule,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "excerpt": self.excerpt,
            "owasp_ids": list(self.owasp_ids),
            "entropy": round(self.entropy, 2) if self.entropy is not None else None,
        }


@dataclass(frozen=True)
class StaticScanResult:
    """The result of scanning one linked source's documents.

    Attributes:
        findings: Ordered, deterministic findings (sorted by ``(path, line, rule)``).
        scanned_paths: The files actually scanned — **paths only**, never their content.
        truncated_files: Files that exceeded :data:`MAX_SCANNED_LINES`, mapped to the number of
            lines that were NOT scanned. Reported so a partial scan is visibly partial.
    """

    findings: Tuple[StaticFinding, ...] = ()
    scanned_paths: Tuple[str, ...] = ()
    truncated_files: Mapping[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        """Return the scan result as a JSON-ready dict."""
        return {
            "findings": [f.as_dict() for f in self.findings],
            "scanned_paths": list(self.scanned_paths),
            "truncated_files": dict(self.truncated_files),
        }


# --- Redaction ----------------------------------------------------------------------------------


def shannon_entropy(value: str) -> float:
    """Shannon entropy of ``value`` in bits per character.

    Used to separate a real credential from a placeholder: ``token = "REPLACE_ME_WITH_YOUR_TOKEN"``
    is long but low-entropy, while a live key is dense. A rule that fired on both would be ignored
    within a week, and an ignored security rule protects nobody.

    Args:
        value: The candidate string.

    Returns:
        Entropy in bits/char; ``0.0`` for an empty string.
    """
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def redact(secret: str, *, keep: int = 4) -> str:
    """Mask a detected secret, keeping only a short leading fragment.

    The fragment exists so a human can tell *which* of their credentials was found; it is short
    enough not to meaningfully reduce the search space for anyone who only has the mask. Short
    matches are masked entirely — keeping 4 of 6 characters would not be redaction.

    This is the only way a matched secret is ever rendered. Nothing in this module returns a match
    in the clear.

    Args:
        secret: The matched credential material.
        keep: How many leading characters to keep.

    Returns:
        e.g. ``"AKIA…[redacted, 20 chars]"``.
    """
    stripped = secret.strip()
    if len(stripped) <= keep * 2:
        return f"[redacted, {len(stripped)} chars]"
    return f"{stripped[:keep]}…[redacted, {len(stripped)} chars]"


def _excerpt(line: str, *, secret: Optional[str] = None) -> str:
    """Build a bounded, secret-free excerpt of a matching line.

    Args:
        line: The raw source line.
        secret: Matched credential material to redact out of it, when the rule found one.

    Returns:
        The excerpt, truncated to :data:`MAX_EXCERPT` characters and with any secret masked.
    """
    text = line.strip()
    if secret:
        text = text.replace(secret, redact(secret))
    if len(text) > MAX_EXCERPT:
        text = f"{text[:MAX_EXCERPT]}…"
    return text


# --- Secret rules --------------------------------------------------------------------------------
# Provider-specific patterns first: they are precise, so a match is worth an `error`. The generic
# high-entropy assignment rule is last and deliberately fires at a lower severity — it is the one
# that can be wrong.

RULE_SECRET_PROVIDER = "source.hardcoded-provider-credential"
RULE_SECRET_PRIVATE_KEY = "source.committed-private-key"
RULE_SECRET_GENERIC = "source.high-entropy-secret"

#: Provider credential formats with distinctive, low-false-positive shapes. Each entry is
#: ``(label, pattern)``; the pattern's group 0 is the credential and is never emitted unredacted.
_PROVIDER_SECRETS: Tuple[Tuple[str, Pattern[str]], ...] = (
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("Stripe live secret key", re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("npm access token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
)

#: A PEM private-key header. The key body is never read, matched, or retained — the header alone is
#: proof enough, and touching the body would mean holding it.
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")

#: A credential-shaped assignment: ``api_key = "…"`` / ``"secret": "…"`` / ``PASSWORD=…``.
_GENERIC_SECRET_RE = re.compile(
    r"""(?ix)
    \b (?: api[_\-]?key | secret | token | password | passwd | credential | auth )
    \b [\"']? \s* [:=] \s* [\"']? ([A-Za-z0-9_\-+/.=]{%d,}) [\"']?
    """
    % MIN_SECRET_LENGTH
)

#: Placeholder values that match the credential-shaped-assignment pattern but are not credentials.
#: Entropy alone does not exclude all of them (a UUID-shaped example is dense), so they are named.
_PLACEHOLDERS = frozenset(
    {
        "changeme",
        "your_api_key_here",
        "xxxxxxxxxxxxxxxx",
        "none",
        "null",
        "example",
        "placeholder",
        "redacted",
        "dummy",
        "test",
    }
)


def _is_placeholder(value: str) -> bool:
    """True when a credential-shaped value is obviously an example rather than a live secret."""
    lowered = value.strip().strip("\"'").lower()
    if lowered in _PLACEHOLDERS:
        return True
    # Env-var interpolation (${FOO}, $FOO, {{ foo }}) is a *reference* to a secret, not a secret.
    # Flagging it would be flagging the correct pattern, which trains people to ignore the rule.
    if lowered.startswith(("${", "$", "{{", "<")):
        return True
    return any(marker in lowered for marker in ("your_", "_here", "replace", "todo"))


def _scan_secrets(document: SourceDocument, line_no: int, line: str) -> List[StaticFinding]:
    """Find credential material on one line, emitting only redacted evidence of it."""
    findings: List[StaticFinding] = []

    for label, pattern in _PROVIDER_SECRETS:
        match = pattern.search(line)
        if match:
            secret = match.group(0)
            findings.append(
                StaticFinding(
                    rule=RULE_SECRET_PROVIDER,
                    path=document.path,
                    line=line_no,
                    message=(
                        f"{label} appears in source ({redact(secret)}). Anyone who can read this "
                        f"artifact holds this credential; rotate it and move it to a secret store."
                    ),
                    excerpt=_excerpt(line, secret=secret),
                    owasp_ids=(MCP06_SECRET_EXPOSURE,),
                    entropy=shannon_entropy(secret),
                )
            )

    if _PRIVATE_KEY_RE.search(line):
        findings.append(
            StaticFinding(
                rule=RULE_SECRET_PRIVATE_KEY,
                path=document.path,
                line=line_no,
                message=(
                    "A PEM private key is committed to source. Rotate the key pair and remove it "
                    "from history — deleting the file does not remove it from prior commits."
                ),
                # The header only. The key body is never captured, so it cannot be stored or shown.
                excerpt="-----BEGIN … PRIVATE KEY----- [key body not captured]",
                owasp_ids=(MCP06_SECRET_EXPOSURE,),
            )
        )

    if not findings:
        # Only run the fuzzy rule when no precise rule matched: a line holding an AWS key would
        # otherwise be reported twice, once precisely and once vaguely.
        match = _GENERIC_SECRET_RE.search(line)
        if match:
            candidate = match.group(1)
            entropy = shannon_entropy(candidate)
            if not _is_placeholder(candidate) and entropy >= ENTROPY_THRESHOLD:
                findings.append(
                    StaticFinding(
                        rule=RULE_SECRET_GENERIC,
                        path=document.path,
                        line=line_no,
                        message=(
                            f"A credential-shaped, high-entropy value is assigned in source "
                            f"({redact(candidate)}, {entropy:.1f} bits/char). If it is a live "
                            f"secret, rotate it and load it from the environment instead."
                        ),
                        excerpt=_excerpt(line, secret=candidate),
                        owasp_ids=(MCP06_SECRET_EXPOSURE,),
                        entropy=entropy,
                    )
                )

    return findings


# --- Config / code pattern rules -----------------------------------------------------------------
# Each rule is (rule_id, pattern, message, owasp_ids). They are line-oriented and language-agnostic
# on purpose: the goal is a high-signal, explainable signal a reviewer can confirm in seconds by
# opening the cited line, not a full dataflow analysis. Nothing here claims to prove exploitability —
# that is structurally impossible for a static rule, and the engine enforces it (see
# `app.mcp_trust_posture.EXPLOITABILITY_SIGNAL`).

RULE_UNSAFE_COMMAND = "source.unsafe-command-execution"
RULE_DYNAMIC_EVAL = "source.dynamic-code-evaluation"
RULE_INSECURE_TLS = "source.tls-verification-disabled"
RULE_PERMISSIVE_CORS = "source.permissive-cors"
RULE_PRIVILEGED_CONTAINER = "source.privileged-container"
RULE_HOST_NETWORK = "source.host-network-access"
RULE_BROAD_MOUNT = "source.broad-filesystem-mount"
RULE_UNPINNED_IMAGE = "source.unpinned-base-image"
RULE_BROAD_OAUTH_SCOPE = "source.broad-oauth-scope"
RULE_CURL_PIPE_SHELL = "source.remote-script-execution"

_PATTERN_RULES: Tuple[Tuple[str, Pattern[str], str, Tuple[str, ...]], ...] = (
    (
        RULE_UNSAFE_COMMAND,
        re.compile(
            r"(?i)\b(?:os\.system|subprocess\.(?:run|call|Popen|check_output)[^)]*shell\s*=\s*True"
            r"|child_process\.exec(?!File)|\.execSync\s*\(|shell_exec|passthru\s*\()"
        ),
        "Reaches a shell. If any part of the command is influenced by tool arguments, an agent — "
        "and transitively an untrusted prompt — can influence what is executed.",
        (MCP05_COMMAND_EXECUTION,),
    ),
    (
        RULE_DYNAMIC_EVAL,
        re.compile(r"(?i)(?:\beval\s*\(|\bexec\s*\(|new\s+Function\s*\(|\bFunction\s*\(\s*[\"'])"),
        "Evaluates code at runtime. Any path from a tool argument to this call is arbitrary code "
        "execution in the server's process.",
        (MCP05_COMMAND_EXECUTION,),
    ),
    (
        RULE_CURL_PIPE_SHELL,
        re.compile(r"(?i)(?:curl|wget)\s[^|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b"),
        "Downloads and executes a remote script during build or start. Whoever controls that URL "
        "controls what runs in the server's image.",
        (MCP04_SUPPLY_CHAIN, MCP05_COMMAND_EXECUTION),
    ),
    (
        RULE_INSECURE_TLS,
        re.compile(
            r"(?i)(?:rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED\s*[:=]\s*[\"']?0"
            r"|verify\s*=\s*False|InsecureSkipVerify\s*:\s*true|curl\s[^\n]*(?:\s-k\b|--insecure))"
        ),
        "Disables TLS certificate verification. The connection is encrypted but unauthenticated, "
        "so it is defenceless against an active network attacker.",
        (MCP07_AUTH_FAILURE,),
    ),
    (
        RULE_PERMISSIVE_CORS,
        re.compile(
            r"(?i)(?:Access-Control-Allow-Origin[\"']?\s*[:,]\s*[\"']\*"
            r"|allow_origins\s*=\s*\[\s*[\"']\*"
            r"|origin\s*:\s*[\"']\*[\"'])"
        ),
        "Allows any origin. Combined with credentialed requests, any web page a user visits can "
        "drive this server as that user.",
        (MCP07_AUTH_FAILURE,),
    ),
    (
        RULE_PRIVILEGED_CONTAINER,
        re.compile(r"(?i)(?:privileged\s*:\s*true|--privileged\b|cap_add\s*:\s*\[?\s*[\"']?ALL)"),
        "Runs privileged. A privileged container is not a security boundary — a compromise of the "
        "server is a compromise of the host.",
        (MCP03_EXCESSIVE_PERMISSIONS,),
    ),
    (
        RULE_HOST_NETWORK,
        re.compile(r"(?i)(?:network_mode\s*:\s*[\"']?host|--network(?:=|\s+)host\b|hostNetwork\s*:\s*true)"),
        "Shares the host network namespace, so the server can reach anything the host can — "
        "including services that believe they are only reachable from localhost.",
        (MCP03_EXCESSIVE_PERMISSIONS,),
    ),
    (
        RULE_BROAD_MOUNT,
        re.compile(r"""(?ix) (?:^|\s|["'\-]) (?: / | /root | /home | \$HOME | ~ ) : /"""),
        "Mounts a broad host path into the container. Whatever the server can be made to read, it "
        "can read from the host — and hand to the agent.",
        (MCP03_EXCESSIVE_PERMISSIONS, MCP08_CONTEXT_OVERSHARING),
    ),
    (
        RULE_UNPINNED_IMAGE,
        re.compile(r"(?im)^\s*FROM\s+(?!scratch\b)(?:[^\s@]+(?::latest)?)\s*(?:AS\s+\w+)?\s*$"),
        "Base image is not pinned to a digest, so the image built today and the image built "
        "tomorrow may not be the same image — and only one of them was reviewed.",
        (MCP04_SUPPLY_CHAIN,),
    ),
    (
        RULE_BROAD_OAUTH_SCOPE,
        re.compile(
            r"""(?ix) \b scopes? \b [^\n]{0,40}? [\"'\[\s]
            (?: \* | admin(?::[\w*]+)? | repo | write:org | offline_access | full_access )
            \b"""
        ),
        "Requests a broad OAuth scope. The blast radius of a compromised server is the authority "
        "it was granted, not the authority it happened to use.",
        (MCP03_EXCESSIVE_PERMISSIONS, MCP07_AUTH_FAILURE),
    ),
)

#: Files the pattern rules are worth running against. Scanning a whole repository line-by-line with
#: these patterns would drown a reviewer in matches from test fixtures and vendored code; the config,
#: manifest, and entrypoint files are where a *deployed* server's actual posture is decided.
_CONFIG_BASENAMES = frozenset(
    {
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "package.json",
        "mcp.json",
        "server.json",
        ".env",
        ".env.example",
        "makefile",
        "entrypoint.sh",
        "start.sh",
        "run.sh",
    }
)

#: Extensions whose files are scanned for the code-shaped rules (unsafe command, eval, TLS, CORS).
_CODE_EXTENSIONS = frozenset(
    {".py", ".js", ".ts", ".mjs", ".cjs", ".go", ".rb", ".sh", ".yaml", ".yml", ".json", ".toml"}
)


def _is_scannable(document: SourceDocument) -> bool:
    """True when a document is one of the config/code files the pattern rules apply to."""
    basename = document.basename.lower()
    if basename in _CONFIG_BASENAMES or basename.startswith("dockerfile"):
        return True
    return any(basename.endswith(ext) for ext in _CODE_EXTENSIONS)


def scan_documents(documents: Sequence[SourceDocument]) -> StaticScanResult:
    """Run every static rule over ``documents`` and return ordered, deterministic findings.

    Args:
        documents: Files from the linked source, already fetched by the caller. Their text is read
            here and never persisted: only findings survive, each carrying at most a redacted,
            length-bounded excerpt of one line.

    Returns:
        The :class:`StaticScanResult`, with findings sorted by ``(path, line, rule)`` so the same
        artifact always produces the same report in the same order.
    """
    findings: List[StaticFinding] = []
    scanned: List[str] = []
    truncated: Dict[str, int] = {}

    for document in documents:
        # Secrets are scanned in *every* file: a committed credential is a leak wherever it lives,
        # including a README or a stray key file. The config/code pattern rules (unsafe command,
        # TLS, CORS, container authority) run only on the config/code files where a *deployed*
        # server's posture is actually decided — running them over test fixtures and vendored code
        # would drown a reviewer in matches.
        scannable = _is_scannable(document)
        if not document.text:
            continue
        scanned.append(document.path)

        lines = document.text.splitlines()
        if len(lines) > MAX_SCANNED_LINES:
            truncated[document.path] = len(lines) - MAX_SCANNED_LINES
            lines = lines[:MAX_SCANNED_LINES]

        for index, line in enumerate(lines, start=1):
            findings.extend(_scan_secrets(document, index, line))
            if scannable:
                findings.extend(_scan_patterns(document, index, line))

    findings.sort(key=lambda f: (f.path, f.line, f.rule))
    return StaticScanResult(
        findings=tuple(findings),
        scanned_paths=tuple(sorted(scanned)),
        truncated_files=dict(sorted(truncated.items())),
    )


def _scan_patterns(
    document: SourceDocument, line_no: int, line: str
) -> List[StaticFinding]:
    """Run the config/code pattern rules over one line."""
    # A commented-out line describes what the author decided NOT to do. Flagging it is noise, and
    # noise is what makes a security rule get switched off.
    stripped = line.strip()
    if stripped.startswith("#") and not _looks_like_dockerfile_directive(stripped):
        return []
    if stripped.startswith("//") or stripped.startswith("*"):
        return []

    findings: List[StaticFinding] = []
    for rule, pattern, message, owasp_ids in _PATTERN_RULES:
        # The unpinned-image rule is Dockerfile-only: a bare `FROM x` line elsewhere is not an image.
        if rule == RULE_UNPINNED_IMAGE and not document.basename.lower().startswith("dockerfile"):
            continue
        if pattern.search(line):
            findings.append(
                StaticFinding(
                    rule=rule,
                    path=document.path,
                    line=line_no,
                    message=message,
                    excerpt=_excerpt(line),
                    owasp_ids=owasp_ids,
                )
            )
    return findings


def _looks_like_dockerfile_directive(line: str) -> bool:
    """True for a Dockerfile parser directive (``# syntax=…``), which is not a comment."""
    return line.lower().startswith("# syntax") or line.lower().startswith("# escape")


def rule_ids() -> Tuple[str, ...]:
    """Every static rule id this module can emit, sorted.

    The trust-posture engine registers a descriptor for each of these, so the two can never drift:
    a rule that fires here but has no descriptor there would produce an unattributable finding.
    """
    return tuple(
        sorted(
            {
                RULE_SECRET_PROVIDER,
                RULE_SECRET_PRIVATE_KEY,
                RULE_SECRET_GENERIC,
                *(rule for rule, _, _, _ in _PATTERN_RULES),
            }
        )
    )


def owasp_ids_for_rule(rule: str) -> Tuple[str, ...]:
    """The OWASP MCP risks a given static rule maps to.

    Args:
        rule: A rule id from :func:`rule_ids`.

    Returns:
        The risk ids, or an empty tuple for an unknown rule.
    """
    if rule in (RULE_SECRET_PROVIDER, RULE_SECRET_PRIVATE_KEY, RULE_SECRET_GENERIC):
        return (MCP06_SECRET_EXPOSURE,)
    for rule_id, _, _, owasp_ids in _PATTERN_RULES:
        if rule_id == rule:
            return owasp_ids
    return ()


def documents_from_mapping(files: Mapping[str, str]) -> List[SourceDocument]:
    """Build :class:`SourceDocument` objects from a ``{path: text}`` mapping, in stable path order.

    Args:
        files: The fetched files.

    Returns:
        The documents, sorted by path so a scan over the same file set is order-independent.
    """
    return [SourceDocument(path=path, text=text) for path, text in sorted(files.items())]


def iter_findings(result: StaticScanResult) -> Iterable[StaticFinding]:
    """Iterate a scan result's findings (convenience for rule packs folding them in)."""
    return iter(result.findings)
