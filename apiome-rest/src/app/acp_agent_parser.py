"""ACP (Agent Communication Protocol) agent manifest parser — MFI-18.2 (#3975).

ACP is the REST-native agent protocol (IBM BeeAI, Linux Foundation): an ACP server lists the
agents it hosts at ``GET /agents`` as ``{"agents": [AgentManifest, …]}`` and describes one at
``GET /agents/{name}``. Agents are run with ``POST /runs`` (sync, async or stream), exchanging
MIME-typed multipart messages. This module reads the **agent manifest** — the descriptor a
catalog cares about — into a typed :class:`AcpDocument`.

Two document shapes are accepted:

* a single **agent manifest** (``{name, description, input_content_types,
  output_content_types, metadata}``) — one agent;
* an **agent list** (``{"agents": [manifest, …]}``, the ``GET /agents`` response) — every agent
  one server hosts.

A manifest's ``metadata`` carries what a reader browses by: ``capabilities`` (name +
description — ACP's counterpart of an A2A skill), ``tags``, ``domains``, ``framework``,
``programming_language``, ``natural_languages``, ``license``, ``author`` / ``contributors``,
``links``, ``dependencies`` and ``recommended_models``. Its ``status`` (average tokens, run time,
success rate) and the ``created_at`` / ``updated_at`` stamps are **runtime facts**, not part of the
contract: they are kept verbatim in :attr:`AcpAgent.raw` but never normalized, so a redeploy that
only moves those numbers does not read as a new version.

Like the A2A parser (:mod:`app.a2a_agent_card_parser`) this parser is JSON only — ACP is a JSON
REST protocol — and classifies failures with the same intake-taxonomy codes, reusing the shared
truncation scan (:func:`app.mcp_manifest_parser.is_unclosed_json`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

import yaml

from .intake_resource_guard import IntakeLimitError, guard_document_text, guard_parsed_document
from .mcp_manifest_parser import is_unclosed_json

__all__ = [
    "ACP_AGENT_NAME_PATTERN",
    "AcpAgent",
    "AcpCapability",
    "AcpDocument",
    "AcpParseError",
    "dumps_acp_for_raw",
    "is_acp_document",
    "is_acp_manifest",
    "is_acp_manifest_document",
    "parse_acp",
]

#: ACP agent names are RFC 1123 DNS labels (lower-case alphanumerics and ``-``); lint reports a
#: name that is not, since it cannot be used in ``/agents/{name}`` or ``agent_name``.
ACP_AGENT_NAME_PATTERN = r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"

#: Root keys that prove the document is a different format, so failures read ``FORMAT_MISMATCH``.
_FOREIGN_FORMAT_MARKERS: Tuple[str, ...] = (
    "openapi",
    "swagger",
    "asyncapi",
    "arazzo",
    "openrpc",
    "discoveryVersion",
    "mcpVersion",
    "skills",
)

#: Manifest keys only ACP uses. Detection needs a ``name`` plus one of these.
_MANIFEST_MARKERS: Tuple[str, ...] = ("input_content_types", "output_content_types")

#: ``metadata`` keys only ACP uses — a manifest that omits the content types still matches
#: when its metadata carries one of these.
_METADATA_MARKERS: Tuple[str, ...] = (
    "capabilities",
    "framework",
    "programming_language",
    "natural_languages",
    "recommended_models",
    "domains",
)

class AcpParseError(ValueError):
    """Raised when an ACP document cannot be parsed.

    Args:
        message: Human-readable description of the failure.
        code: Stable intake-taxonomy code (see :mod:`app.intake_error_taxonomy`).
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AcpCapability:
    """One declared capability of an agent (``metadata.capabilities[]``).

    Attributes:
        name: The capability's name — the key it is versioned and diffed by.
        description: What it does, when given.
    """

    name: str
    description: Optional[str]


@dataclass(frozen=True)
class AcpAgent:
    """One parsed ACP agent manifest.

    Attributes:
        name: The agent's name (its ``agent_name`` in ``POST /runs``).
        description: The agent's description, when given.
        input_content_types: MIME types the agent accepts (``*/*`` when the manifest omits them,
            the ACP default).
        output_content_types: MIME types the agent produces (``*/*`` by default).
        content_types_declared: Whether the manifest stated its content types at all, so lint
            can tell an explicit ``*/*`` from the default.
        capabilities: Declared capabilities, in source order.
        tags: Discovery tags.
        domains: Business domains (``finance``, ``healthcare`` …).
        framework: The framework the agent is built with (``BeeAI``, ``LangGraph`` …).
        programming_language: Implementation language.
        natural_languages: Human languages the agent speaks.
        license: SPDX license identifier, when given.
        documentation: Markdown documentation, when given.
        author: ``{name, email, url}`` of the author, when given.
        contributors: The contributors, verbatim.
        links: ``{type, url}`` links (source code, container image, homepage, documentation).
        dependencies: ``{type, name}`` dependencies (agents, tools, models).
        recommended_models: Models the agent is meant to run on.
        raw: The manifest verbatim — including ``status`` and timestamps.
    """

    name: str
    description: Optional[str]
    input_content_types: Tuple[str, ...]
    output_content_types: Tuple[str, ...]
    content_types_declared: bool
    capabilities: Tuple[AcpCapability, ...]
    tags: Tuple[str, ...]
    domains: Tuple[str, ...]
    framework: Optional[str]
    programming_language: Optional[str]
    natural_languages: Tuple[str, ...]
    license: Optional[str]
    documentation: Optional[str]
    author: Optional[Dict[str, str]]
    contributors: Tuple[Dict[str, Any], ...]
    links: Tuple[Dict[str, str], ...]
    dependencies: Tuple[Dict[str, str], ...]
    recommended_models: Tuple[str, ...]
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AcpDocument:
    """A parsed ACP document — one manifest or a ``GET /agents`` list.

    Attributes:
        agents: The agents, in source order.
        shape: ``"manifest"`` for a single manifest, ``"agent-list"`` for ``{"agents": […]}``.
        title: Display title: the agent's name for a manifest, else derived from the label.
        raw: The document text verbatim.
        source_label: Filename / URL the document came from, when known.
    """

    agents: Tuple[AcpAgent, ...]
    shape: str
    title: str
    raw: str
    source_label: Optional[str] = None


# ===========================================================================
# Detection
# ===========================================================================


def is_acp_manifest_document(document: Any) -> bool:
    """Return ``True`` when a parsed value looks like one ACP agent manifest.

    Args:
        document: Any parsed JSON value.

    Returns:
        Whether it carries a ``name`` string plus an ACP-only manifest or metadata key, and no
        other format's root marker (an A2A card's ``skills``, an OpenAPI ``openapi`` …).
    """
    if not isinstance(document, Mapping):
        return False
    if any(marker in document for marker in _FOREIGN_FORMAT_MARKERS):
        return False
    if not isinstance(document.get("name"), str):
        return False
    if any(marker in document for marker in _MANIFEST_MARKERS):
        return True
    metadata = document.get("metadata")
    return isinstance(metadata, Mapping) and any(m in metadata for m in _METADATA_MARKERS)


def is_acp_document(document: Any) -> bool:
    """Return ``True`` for an ACP manifest or a non-empty ``{"agents": [manifest, …]}`` list.

    Args:
        document: Any parsed JSON value.

    Returns:
        Whether the value is an ACP document this parser accepts.
    """
    if is_acp_manifest_document(document):
        return True
    if not isinstance(document, Mapping) or set(document) - {"agents"}:
        return False
    agents = document.get("agents")
    return (
        isinstance(agents, list)
        and bool(agents)
        and all(is_acp_manifest_document(agent) for agent in agents)
    )


def is_acp_manifest(content: str) -> bool:
    """Return ``True`` when ``content`` is JSON text holding an ACP document. Never raises.

    Args:
        content: Raw document text.

    Returns:
        Whether the text is an ACP manifest or agent list.
    """
    if not content or not isinstance(content, str) or not content.strip():
        return False
    if "\x00" in content[:256]:
        return False
    try:
        document = json.loads(content)
    except (json.JSONDecodeError, RecursionError, ValueError):
        return False
    return is_acp_document(document)


# ===========================================================================
# Parsing
# ===========================================================================


def parse_acp(content: str, *, source_label: Optional[str] = None) -> AcpDocument:
    """Parse an ACP agent manifest or ``GET /agents`` list.

    Args:
        content: The raw document text (JSON).
        source_label: Optional filename / URL used in messages and for a list's title.

    Returns:
        The parsed document.

    Raises:
        AcpParseError: With a taxonomy ``code`` — ``INPUT_EMPTY``, ``INPUT_ENCODING_INVALID``,
            ``INPUT_TRUNCATED``, ``INPUT_MALFORMED``, ``FORMAT_MISMATCH`` for another format, and
            ``INPUT_SEMANTIC_INVALID`` for an empty agent list or an agent with no ``name``.
    """
    where = f" ({source_label})" if source_label else ""
    document = _load(content, where=where, source_label=source_label)

    if "agents" in document and "name" not in document:
        entries = document.get("agents")
        if not isinstance(entries, list) or not entries:
            raise AcpParseError(
                f"ACP agent list{where} has no agents", code="INPUT_SEMANTIC_INVALID"
            )
        agents = tuple(
            _parse_agent(entry, where=f"{where} agent at index {index}")
            for index, entry in enumerate(entries)
        )
        return AcpDocument(
            agents=agents,
            shape="agent-list",
            title=_title_from_label(source_label, agents),
            raw=content,
            source_label=source_label,
        )

    agent = _parse_agent(document, where=where)
    return AcpDocument(
        agents=(agent,),
        shape="manifest",
        title=agent.name,
        raw=content,
        source_label=source_label,
    )


def dumps_acp_for_raw(document: AcpDocument) -> Any:
    """Return the document as a JSON value for the canonical model's ``raw`` fidelity bag.

    Args:
        document: The parsed document.

    Returns:
        The decoded JSON (its text was validated as JSON when it was parsed).
    """
    return json.loads(document.raw)


# ===========================================================================
# Internals
# ===========================================================================


def _load(content: str, *, where: str, source_label: Optional[str]) -> Mapping[str, Any]:
    """Decode the text to a JSON object, classifying every way that can fail.

    Args:
        content: The raw text.
        where: Pre-formatted ``" (label)"`` suffix for messages.
        source_label: Label passed to the intake resource guards.

    Returns:
        The parsed top-level object.

    Raises:
        AcpParseError: With the taxonomy code for the specific failure.
    """
    if not content or not content.strip():
        raise AcpParseError(f"ACP document is empty{where}", code="INPUT_EMPTY")
    if "\x00" in content or "�" in content[:64]:
        raise AcpParseError(
            f"ACP document is not UTF-8 text{where} — it looks like UTF-16 or binary content",
            code="INPUT_ENCODING_INVALID",
        )
    try:
        guard_document_text(content, source_label=source_label)
    except IntakeLimitError as exc:
        raise AcpParseError(str(exc), code=getattr(exc, "code", None)) from exc

    try:
        document: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise _classify_json_failure(content, exc, where=where) from exc

    try:
        guard_parsed_document(document, source_label=source_label)
    except IntakeLimitError as exc:
        raise AcpParseError(str(exc), code=getattr(exc, "code", None)) from exc

    if not isinstance(document, Mapping):
        raise AcpParseError(
            f"ACP document must be a JSON object{where}, not a {type(document).__name__}",
            code="FORMAT_MISMATCH",
        )
    if any(marker in document for marker in _FOREIGN_FORMAT_MARKERS):
        raise AcpParseError(
            f"Content looks like another format (OpenAPI/A2A/MCP/…){where}, not an ACP "
            "agent manifest",
            code="FORMAT_MISMATCH",
        )
    if "name" not in document and "agents" not in document:
        raise AcpParseError(
            f"Content is not an ACP agent manifest{where}: it has no `name` or `agents`",
            code="FORMAT_MISMATCH",
        )
    return document


def _classify_json_failure(
    content: str, exc: json.JSONDecodeError, *, where: str
) -> AcpParseError:
    """Turn a JSON decode failure into the right taxonomy code.

    Text that parses as YAML into a mapping with neither ``name`` nor ``agents`` (or with another
    format's marker) is a different format; text left open mid-value is truncated; anything else
    is malformed.

    Args:
        content: The text that failed to decode.
        exc: The decode error.
        where: Pre-formatted ``" (label)"`` suffix for messages.

    Returns:
        The error to raise.
    """
    try:
        loose = yaml.safe_load(content)
    except Exception:  # noqa: BLE001 - a YAML failure only means "no second opinion"
        loose = None
    if isinstance(loose, Mapping) and (
        not ({"name", "agents"} & set(loose))
        or any(marker in loose for marker in _FOREIGN_FORMAT_MARKERS)
    ):
        return AcpParseError(
            f"Content is not an ACP agent manifest{where}: {exc.msg}", code="FORMAT_MISMATCH"
        )
    if is_unclosed_json(content):
        return AcpParseError(
            f"ACP document is truncated{where}: {exc.msg} at line {exc.lineno}",
            code="INPUT_TRUNCATED",
        )
    return AcpParseError(
        f"ACP document is not valid JSON{where}: {exc.msg} at line {exc.lineno} "
        f"column {exc.colno}",
        code="INPUT_MALFORMED",
    )


def _parse_agent(entry: Any, *, where: str) -> AcpAgent:
    """Parse one agent manifest object.

    Args:
        entry: The raw manifest.
        where: Location suffix for messages.

    Returns:
        The parsed agent.

    Raises:
        AcpParseError: ``INPUT_SEMANTIC_INVALID`` when the entry is not an object or has no
            non-empty ``name``.
    """
    if not isinstance(entry, Mapping):
        raise AcpParseError(f"ACP manifest{where} is not an object", code="INPUT_SEMANTIC_INVALID")
    name = _optional_str(entry.get("name"))
    if name is None:
        raise AcpParseError(
            f"ACP manifest{where} has no `name`", code="INPUT_SEMANTIC_INVALID"
        )
    metadata = entry.get("metadata")
    meta: Mapping[str, Any] = metadata if isinstance(metadata, Mapping) else {}
    declared = "input_content_types" in entry or "output_content_types" in entry
    return AcpAgent(
        name=name,
        description=_optional_str(entry.get("description")),
        input_content_types=_str_tuple(entry.get("input_content_types")) or ("*/*",),
        output_content_types=_str_tuple(entry.get("output_content_types")) or ("*/*",),
        content_types_declared=declared,
        capabilities=_parse_capabilities(meta.get("capabilities")),
        tags=_str_tuple(meta.get("tags")),
        domains=_str_tuple(meta.get("domains")),
        framework=_optional_str(meta.get("framework")),
        programming_language=_optional_str(meta.get("programming_language")),
        natural_languages=_str_tuple(meta.get("natural_languages")),
        license=_optional_str(meta.get("license")),
        documentation=_optional_str(meta.get("documentation")),
        author=_string_record(meta.get("author"), ("name", "email", "url")),
        contributors=tuple(
            dict(item) for item in meta.get("contributors") or [] if isinstance(item, Mapping)
        )
        if isinstance(meta.get("contributors"), list)
        else (),
        links=_record_tuple(meta.get("links"), ("type", "url")),
        dependencies=_record_tuple(meta.get("dependencies"), ("type", "name")),
        recommended_models=_str_tuple(meta.get("recommended_models")),
        raw=dict(entry),
    )


def _parse_capabilities(value: Any) -> Tuple[AcpCapability, ...]:
    """Parse ``metadata.capabilities``, skipping entries with no ``name``."""
    if not isinstance(value, list):
        return ()
    out: List[AcpCapability] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        name = _optional_str(item.get("name"))
        if name is None:
            continue
        out.append(AcpCapability(name=name, description=_optional_str(item.get("description"))))
    return tuple(out)


def _string_record(value: Any, keys: Tuple[str, ...]) -> Optional[Dict[str, str]]:
    """Return the non-empty string fields ``keys`` of an object, or ``None`` when there are none."""
    if not isinstance(value, Mapping):
        return None
    record = {key: text for key in keys if (text := _optional_str(value.get(key)))}
    return record or None


def _record_tuple(value: Any, keys: Tuple[str, ...]) -> Tuple[Dict[str, str], ...]:
    """Parse a list of small string records (links, dependencies), dropping empty ones."""
    if not isinstance(value, list):
        return ()
    records = (_string_record(item, keys) for item in value)
    return tuple(record for record in records if record)


def _title_from_label(source_label: Optional[str], agents: Tuple[AcpAgent, ...]) -> str:
    """A list's title, from the label: a file's base name, or for a ``…/agents`` URL the server's
    host. Falls back to the single agent's name, else ``acp-agents``."""
    if source_label:
        parts = urlsplit(source_label)
        base = source_label.rstrip("/").rsplit("/", 1)[-1]
        if base.lower().endswith(".json"):
            base = base[: -len(".json")]
        if parts.netloc and base.lower() == "agents":
            base = parts.netloc
        if base.strip():
            return base.strip()
    return agents[0].name if len(agents) == 1 else "acp-agents"


def _optional_str(value: Any) -> Optional[str]:
    """Return a stripped non-empty string, else ``None``."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _str_tuple(value: Any) -> Tuple[str, ...]:
    """Return the non-empty strings of a list, stripped and deduplicated in order."""
    if not isinstance(value, list):
        return ()
    out: List[str] = []
    for item in value:
        text = _optional_str(item)
        if text is not None and text not in out:
            out.append(text)
    return tuple(out)
