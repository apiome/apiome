"""Generation settings & branding — SDK-3.4 (#4494).

An organisation wants the code Apiome hands its consumers to carry the organisation's identity:
packages named under its own npm scope / PyPI naming pattern, its licence header on the source, and
its own user-agent on the traffic those clients generate. This module is the vocabulary and the
rules for that, as pure functions — it knows nothing about the database, HTTP, or which surface is
asking.

Three decisions shape the whole thing.

**The merge is per key, not per row.** A project that wants only its own user-agent must still
inherit its tenant's package pattern and licence header, so the two scopes are combined key by key
(and, for ``packageNamePatterns``, ecosystem by ecosystem) rather than one row replacing the other.
This is the one place SDK-3.4 deliberately departs from CTG-4.5's ``deploy_gate_policy``, whose
project override replaces the whole threshold body.

**"Unset" and "set to nothing" are different answers.** A project whose body omits
``licenseHeader`` inherits its tenant's; a project whose body carries ``"licenseHeader": null`` has
asked for *none*, and must not have the tenant's re-applied. Stored bodies therefore carry only the
keys their author actually named (:func:`parse_settings_body` preserves that distinction, and an
explicit ``null`` survives into the merge as a blocking ``None``).

**A pattern is validated by being resolved.** ``@acme/{project}-sdk`` is not itself a legal npm
name — the braces are not in npm's character set — so a pattern is checked by substituting probe
values and validating the *result* against the ecosystem's naming rules. That is also what makes
the error message useful: it can show the caller the name their pattern would actually produce.

The settings are addressed as ``sdk.generation-settings.v1``. Every response that applies them
carries the fingerprint of the *merged* result (:func:`settings_content_fingerprint`), so identical
settings demonstrably produce identical artifacts and a changed artifact can be attributed to
changed branding rather than to a changed API.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

__all__ = [
    "DEFAULT_SETTINGS",
    "ECOSYSTEMS",
    "LICENSE_HEADER_MAX_CHARS",
    "PATTERN_TOKENS",
    "SDK_GENERATION_SETTINGS_SCHEMA_VERSION",
    "SETTINGS_SOURCES",
    "SETTINGS_SOURCE_DEFAULT",
    "SETTINGS_SOURCE_MERGED",
    "SETTINGS_SOURCE_PROJECT",
    "SETTINGS_SOURCE_TENANT",
    "USER_AGENT_MAX_CHARS",
    "PatternContext",
    "ResolvedBranding",
    "SdkGenerationSettings",
    "SdkGenerationSettingsOut",
    "SdkSettingsError",
    "canonical_settings_body",
    "merge_settings_bodies",
    "parse_settings_body",
    "render_pattern",
    "resolve_branding",
    "resolve_package_names",
    "settings_content_fingerprint",
    "settings_from_body",
]

#: The addressable shape of a stored settings body.
SDK_GENERATION_SETTINGS_SCHEMA_VERSION = "sdk.generation-settings.v1"

#: Package ecosystems a name pattern can be declared for.
#:
#: Deliberately only the two the platform can actually name today (the MVP language targets were
#: TypeScript and Python). Adding a third is one entry here plus one validator below — an unknown
#: ecosystem is refused with the accepted list rather than stored and silently ignored.
ECOSYSTEMS: Tuple[str, ...] = ("npm", "pypi")

#: Substitution tokens accepted in any pattern (package names, the licence header, the user-agent).
#:
#: One vocabulary for all three fields: a caller who learns it once can use it everywhere, and an
#: unknown token is a validation error rather than a literal brace surviving into a package name.
PATTERN_TOKENS: Tuple[str, ...] = ("tenant", "project", "version", "year")

#: Ceilings. The licence header is prepended to every rendered snippet, and the user-agent travels
#: in a header — both are bounded so a pathological value cannot make responses unusable.
LICENSE_HEADER_MAX_CHARS = 4_000
USER_AGENT_MAX_CHARS = 200

#: Where the settings in force came from.
SETTINGS_SOURCE_DEFAULT = "default"
SETTINGS_SOURCE_TENANT = "tenant"
SETTINGS_SOURCE_PROJECT = "project"
SETTINGS_SOURCE_MERGED = "merged"
SETTINGS_SOURCES: Tuple[str, ...] = (
    SETTINGS_SOURCE_DEFAULT,
    SETTINGS_SOURCE_TENANT,
    SETTINGS_SOURCE_PROJECT,
    SETTINGS_SOURCE_MERGED,
)

#: Probe values a pattern is validated against. Chosen to look like real coordinates so the
#: rendered example in an error message reads as the name the caller would actually get.
_PROBE_CONTEXT_VALUES = {
    "tenant": "acme",
    "project": "petstore",
    "version": "1.0.0",
    "year": "2026",
}

#: npm package name: an optional ``@scope/`` followed by the name, no upper case, no leading dot or
#: underscore, 214 characters or fewer (npm's own published rules).
_NPM_NAME = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
_NPM_MAX_CHARS = 214

#: PyPI distribution name (PEP 508): alphanumeric at both ends, ``.``/``-``/``_`` inside.
_PYPI_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_PYPI_MAX_CHARS = 128

#: Any ``{token}`` occurrence, used both to substitute and to spot unknown tokens.
_TOKEN_PATTERN = re.compile(r"\{([A-Za-z0-9_]*)\}")

#: RFC 7230 field-value: visible ASCII plus space and horizontal tab. Anything else — a CR, an LF, a
#: control character — is refused, because a user-agent is written into a request header and a
#: newline there is header injection.
_HEADER_SAFE = re.compile(r"^[\x20-\x7e\t]*$")


class SdkSettingsError(ValueError):
    """A submitted settings body is not valid.

    Attributes:
        errors: One message per problem, so a caller fixes everything in one round trip rather
            than discovering the next mistake after correcting the first.
    """

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class _CamelModel(BaseModel):
    """Base for every wire model here: camelCase out, either spelling in."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


# -------------------------------------------------------------------------------------------
# The settings
# -------------------------------------------------------------------------------------------


class SdkGenerationSettings(_CamelModel):
    """The complete ``sdk.generation-settings.v1`` body, after merging.

    Every field is optional and defaults to ``None`` — "nothing configured" is the documented
    default at every scope, because there is no sensible platform-wide package scope or licence to
    invent on a tenant's behalf.

    Attributes:
        package_name_patterns: Package name pattern per ecosystem (see :data:`ECOSYSTEMS`), e.g.
            ``{"npm": "@acme/{project}-sdk"}``. Ecosystems are merged individually.
        license_header: Text prepended, as a comment, to generated source. May span lines.
        user_agent: User-agent string generated clients send, for API-side traffic attribution.
        public_sdk_enabled: Whether the public browse portal may serve this project's SDK — the
            client-kit download and the anonymous per-operation snippets (SDK-3.3). Unlike the
            other three this is a *gate*, not branding, so it defaults to ``False`` rather than
            ``None``: "not configured" and "not allowed" are the same answer for an access
            control, and the safe one.
    """

    package_name_patterns: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Package name pattern per ecosystem (`npm`, `pypi`), e.g. "
            "`{\"npm\": \"@acme/{project}-sdk\"}`."
        ),
    )
    license_header: Optional[str] = Field(
        default=None,
        description="Text prepended as a comment to generated source (may span lines).",
    )
    user_agent: Optional[str] = Field(
        default=None,
        description="User-agent generated clients send, for API-side traffic attribution.",
    )
    public_sdk_enabled: bool = Field(
        default=False,
        description=(
            "Whether anonymous browse visitors may take the SDK for this project: the "
            "`Get SDK` client-kit download and the public per-operation snippets "
            "(SDK-3.3). Off unless a workspace or project owner opts in."
        ),
    )


#: What a tenant that has configured nothing gets: no patterns, no header, no user-agent, and —
#: deliberately — no public SDK exposure. Opting a project's consumers in is always an explicit act.
DEFAULT_SETTINGS = SdkGenerationSettings()


class SdkGenerationSettingsOut(_CamelModel):
    """The settings in force for a scope, and where each part of them came from.

    Attributes:
        schema_version: The body shape these settings were read as.
        source: ``default`` (nothing saved anywhere), ``tenant``, ``project``, or ``merged`` when
            both scopes contributed.
        content_fingerprint: ``sha256:`` digest of the merged body — identical settings produce
            identical artifacts, and this is the value that proves it.
        settings: The merged settings themselves.
        resolved: The settings with their tokens substituted for this scope, ready to apply.
        scope: The scope this request addressed (``tenant`` or ``project``).
        scope_body: The body saved at *exactly* that scope, verbatim, or ``None`` when nothing is
            saved there. An editor needs this and not just ``settings``: only the raw body says
            whether a key is absent (inherit) or present as ``null`` (deliberately none), and the
            merged view cannot tell those apart.
        tenant_settings_id: The contributing tenant-scope row, when there is one.
        project_settings_id: The contributing project-scope row, when there is one.
        updated_at: When the most specific contributing row was last written.
        updated_by: Who wrote it.
        degraded: True when a stored row could not be read and was skipped.
    """

    schema_version: str = Field(
        default=SDK_GENERATION_SETTINGS_SCHEMA_VERSION,
        description="The settings body shape.",
    )
    source: str = Field(description="default | tenant | project | merged.")
    content_fingerprint: str = Field(
        description="sha256 digest of the merged settings body."
    )
    settings: SdkGenerationSettings = Field(default_factory=SdkGenerationSettings)
    resolved: "ResolvedBrandingOut" = Field(
        description="The settings with tokens substituted for this scope."
    )
    scope: str = Field(
        default=SETTINGS_SOURCE_TENANT,
        description="The scope this request addressed: tenant | project.",
    )
    scope_body: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "The body saved at exactly this scope, verbatim, or null when nothing is saved "
            "here. Only this distinguishes an absent key (inherit) from an explicit null "
            "(deliberately none)."
        ),
    )
    tenant_settings_id: Optional[str] = Field(default=None)
    project_settings_id: Optional[str] = Field(default=None)
    updated_at: Optional[datetime] = Field(default=None)
    updated_by: Optional[str] = Field(default=None)
    degraded: bool = Field(
        default=False,
        description="True when a stored row could not be read and was skipped.",
    )


class ResolvedBrandingOut(_CamelModel):
    """Token-substituted settings, ready for a generator or a snippet to apply.

    Attributes:
        package_names: Resolved package name per ecosystem. An ecosystem whose pattern resolved to
            an illegal name for that registry is omitted rather than emitted broken.
        license_header: The resolved licence text (still uncommented — the consumer knows its own
            comment syntax).
        user_agent: The resolved user-agent string.
    """

    package_names: Dict[str, str] = Field(default_factory=dict)
    license_header: Optional[str] = Field(default=None)
    user_agent: Optional[str] = Field(default=None)


SdkGenerationSettingsOut.model_rebuild()


@dataclass(frozen=True)
class PatternContext:
    """The coordinates a pattern's tokens are substituted from.

    Attributes:
        tenant: The tenant slug (``{tenant}``).
        project: The project slug (``{project}``).
        version: The version label being generated for (``{version}``), when one is in play.
        year: Four-digit year for ``{year}``; defaults to the current UTC year at construction.
    """

    tenant: str = ""
    project: str = ""
    version: str = ""
    year: str = ""

    @staticmethod
    def probe() -> "PatternContext":
        """Return the fixed context a pattern is validated against.

        Returns:
            A context of realistic-looking probe values, so a validation message can show the
            caller the name their pattern would actually produce.
        """
        return PatternContext(**_PROBE_CONTEXT_VALUES)

    def values(self) -> Dict[str, str]:
        """Return the substitution map, filling ``year`` from the clock when it was not given.

        Returns:
            Token name → replacement string. Tokens with nothing behind them map to ``""``, which
            is what makes a ``{version}`` in a tenant-wide pattern degrade quietly rather than
            leaving a literal brace in a package name.
        """
        year = self.year or str(datetime.now(timezone.utc).year)
        return {
            "tenant": self.tenant or "",
            "project": self.project or "",
            "version": self.version or "",
            "year": year,
        }


@dataclass(frozen=True)
class ResolvedBranding:
    """Token-substituted settings for one scope (the domain twin of :class:`ResolvedBrandingOut`).

    Attributes:
        package_names: Resolved, validated package name per ecosystem.
        license_header: Resolved licence text, or ``None``.
        user_agent: Resolved user-agent string, or ``None``.
    """

    package_names: Dict[str, str]
    license_header: Optional[str] = None
    user_agent: Optional[str] = None

    def is_empty(self) -> bool:
        """True when nothing is configured, so a caller can skip applying branding entirely."""
        return not self.package_names and not self.license_header and not self.user_agent


# -------------------------------------------------------------------------------------------
# Patterns
# -------------------------------------------------------------------------------------------


def render_pattern(pattern: str, context: PatternContext) -> str:
    """Substitute ``{token}`` occurrences in a pattern.

    Unknown tokens are left untouched — :func:`parse_settings_body` refuses them at save time, so
    reaching one here means a body written by a newer release, and mangling it would be worse than
    passing it through.

    Args:
        pattern: The raw pattern text.
        context: The coordinates to substitute from.

    Returns:
        The substituted text.
    """
    values = context.values()

    def _replace(match: "re.Match[str]") -> str:
        token = match.group(1)
        return values[token] if token in values else match.group(0)

    return _TOKEN_PATTERN.sub(_replace, pattern or "")


def _unknown_tokens(pattern: str) -> List[str]:
    """Return every ``{token}`` in a pattern that is not part of :data:`PATTERN_TOKENS`."""
    return [
        token
        for token in _TOKEN_PATTERN.findall(pattern or "")
        if token not in PATTERN_TOKENS
    ]


def _package_name_problem(ecosystem: str, name: str) -> Optional[str]:
    """Return why a resolved package name is illegal for its ecosystem, or ``None``.

    Args:
        ecosystem: One of :data:`ECOSYSTEMS`.
        name: The already-substituted name.

    Returns:
        A human-readable problem, or ``None`` when the name is legal.
    """
    if not name:
        return "resolves to an empty name"
    if ecosystem == "npm":
        if len(name) > _NPM_MAX_CHARS:
            return f"resolves to {len(name)} characters (npm allows {_NPM_MAX_CHARS})"
        if not _NPM_NAME.match(name):
            return (
                f"resolves to {name!r}, which is not a legal npm package name "
                "(lower-case, optional `@scope/`, letters/digits/`.`/`-`/`_`)"
            )
        return None
    if ecosystem == "pypi":
        if len(name) > _PYPI_MAX_CHARS:
            return f"resolves to {len(name)} characters (PyPI allows {_PYPI_MAX_CHARS})"
        if not _PYPI_NAME.match(name):
            return (
                f"resolves to {name!r}, which is not a legal PyPI distribution name "
                "(letters/digits at both ends, `.`/`-`/`_` inside)"
            )
        return None
    # Unreachable while parse_settings_body gates the ecosystem, and deliberately permissive if a
    # newer release stores one this code does not know.
    return None


def _has_unresolvable_token(pattern: str, context: PatternContext) -> bool:
    """True when a pattern names a token this context has nothing to put behind it."""
    values = context.values()
    return any(not values.get(token) for token in _TOKEN_PATTERN.findall(pattern or ""))


def resolve_package_names(
    settings: SdkGenerationSettings, context: PatternContext
) -> Dict[str, str]:
    """Resolve every declared package pattern for one set of coordinates.

    An ecosystem is **omitted** rather than resolved approximately in two cases, both for the same
    reason — a package name is an exact identifier, and a nearly-right one is worse than none:

    * the pattern names a token this context cannot fill (``@acme/{project}-sdk`` asked for at
      *tenant* scope would otherwise become ``@acme/-sdk``);
    * the resolved name is one the registry would reject. Patterns are validated against probe
      values at save time, but a real project slug is not a probe.

    The licence header and user-agent take the opposite rule (:func:`resolve_branding` renders
    their unfillable tokens away), because a partially-rendered sentence is still useful and
    neither is an identifier anything is looked up by.

    Args:
        settings: The merged settings.
        context: The coordinates to substitute.

    Returns:
        Ecosystem → resolved package name, in :data:`ECOSYSTEMS` order.
    """
    resolved: Dict[str, str] = {}
    for ecosystem in ECOSYSTEMS:
        pattern = settings.package_name_patterns.get(ecosystem)
        if not pattern or _has_unresolvable_token(pattern, context):
            continue
        name = render_pattern(pattern, context).strip()
        if _package_name_problem(ecosystem, name) is None:
            resolved[ecosystem] = name
    return resolved


def resolve_branding(
    settings: SdkGenerationSettings, context: PatternContext
) -> ResolvedBranding:
    """Substitute every pattern in a settings body for one set of coordinates.

    Args:
        settings: The merged settings.
        context: The coordinates to substitute.

    Returns:
        The :class:`ResolvedBranding` a generator or snippet renderer applies.
    """
    header = settings.license_header
    agent = settings.user_agent
    return ResolvedBranding(
        package_names=resolve_package_names(settings, context),
        license_header=render_pattern(header, context) if header else None,
        user_agent=render_pattern(agent, context).strip() if agent else None,
    )


# -------------------------------------------------------------------------------------------
# Bodies: parse, merge, fingerprint
# -------------------------------------------------------------------------------------------


def _validate_pattern_tokens(field: str, pattern: str, errors: List[str]) -> None:
    """Append an error for each unknown ``{token}`` in ``pattern``."""
    unknown = _unknown_tokens(pattern)
    if unknown:
        errors.append(
            f"{field}: unknown token(s) {', '.join(sorted(set(unknown)))}; "
            f"expected one of {', '.join(PATTERN_TOKENS)}"
        )


def _parse_package_patterns(raw: Any, errors: List[str]) -> Optional[Dict[str, Any]]:
    """Validate the ``packageNamePatterns`` key, returning the canonical sub-body.

    Args:
        raw: The submitted value (an object, or ``None`` to clear every pattern).
        errors: Collector appended to on each problem.

    Returns:
        Ecosystem → pattern (or ``None`` for an ecosystem explicitly cleared), or ``None`` when
        the whole key was explicitly nulled. Returns ``{}`` on error so parsing continues.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        errors.append("packageNamePatterns: expected an object keyed by ecosystem")
        return {}

    parsed: Dict[str, Any] = {}
    for ecosystem, value in raw.items():
        key = str(ecosystem)
        if key not in ECOSYSTEMS:
            errors.append(
                f"packageNamePatterns.{key}: unknown ecosystem; "
                f"expected one of {', '.join(ECOSYSTEMS)}"
            )
            continue
        if value is None:
            # An explicit null clears this ecosystem and blocks inheritance from the tenant.
            parsed[key] = None
            continue
        if not isinstance(value, str):
            errors.append(f"packageNamePatterns.{key}: expected a string pattern or null")
            continue
        pattern = value.strip()
        if not pattern:
            errors.append(
                f"packageNamePatterns.{key}: is empty; use null to clear it instead"
            )
            continue
        field = f"packageNamePatterns.{key}"
        _validate_pattern_tokens(field, pattern, errors)
        problem = _package_name_problem(
            key, render_pattern(pattern, PatternContext.probe()).strip()
        )
        if problem:
            errors.append(f"{field}: {problem}")
            continue
        parsed[key] = pattern
    return parsed


def _parse_license_header(raw: Any, errors: List[str]) -> Optional[str]:
    """Validate the ``licenseHeader`` key, returning the canonical value."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        errors.append("licenseHeader: expected a string or null")
        return None
    text = raw.strip()
    if not text:
        errors.append("licenseHeader: is empty; use null to clear it instead")
        return None
    if len(text) > LICENSE_HEADER_MAX_CHARS:
        errors.append(
            f"licenseHeader: is {len(text)} characters (the maximum is "
            f"{LICENSE_HEADER_MAX_CHARS})"
        )
        return None
    _validate_pattern_tokens("licenseHeader", text, errors)
    return text


def _parse_user_agent(raw: Any, errors: List[str]) -> Optional[str]:
    """Validate the ``userAgent`` key, returning the canonical value."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        errors.append("userAgent: expected a string or null")
        return None
    agent = raw.strip()
    if not agent:
        errors.append("userAgent: is empty; use null to clear it instead")
        return None
    if len(agent) > USER_AGENT_MAX_CHARS:
        errors.append(
            f"userAgent: is {len(agent)} characters (the maximum is {USER_AGENT_MAX_CHARS})"
        )
        return None
    if not _HEADER_SAFE.match(agent):
        errors.append(
            "userAgent: contains a character that cannot appear in an HTTP header "
            "(control characters and line breaks are not allowed)"
        )
        return None
    _validate_pattern_tokens("userAgent", agent, errors)
    return agent


def _parse_public_sdk_enabled(raw: Any, errors: List[str]) -> Optional[bool]:
    """Validate the ``publicSdkEnabled`` key, returning the canonical value.

    Args:
        raw: The submitted value — ``True``/``False``, or ``None`` to say "deliberately not
            inherited, and off".
        errors: Collector appended to on each problem.

    Returns:
        The boolean to store, or ``None`` for an explicit clear.
    """
    if raw is None:
        return None
    # `isinstance(True, int)` is True in Python, so an int would pass a naive numeric check and a
    # `1` would silently become a permission grant. Only a real bool is accepted.
    if not isinstance(raw, bool):
        errors.append("publicSdkEnabled: expected a boolean or null")
        return None
    return raw


def parse_settings_body(body: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate a submitted settings body into the canonical form that is stored.

    The result carries **only the keys the author actually named**. That is the whole point: an
    absent key inherits the next scope up, while a key present with ``null`` deliberately clears
    it and blocks that inheritance. A pydantic model cannot express the difference, which is why
    parsing returns a dict rather than :class:`SdkGenerationSettings`.

    Every problem is collected before raising, so a caller fixes them all in one round trip.

    Args:
        body: The submitted ``sdk.generation-settings.v1`` body, or ``None`` for an empty one.

    Returns:
        The canonical body to store: the named keys, normalised, plus ``schemaVersion``.

    Raises:
        SdkSettingsError: When the body is not valid.
    """
    if body is None:
        return {"schemaVersion": SDK_GENERATION_SETTINGS_SCHEMA_VERSION}
    if not isinstance(body, Mapping):
        raise SdkSettingsError(["expected a settings object"])

    errors: List[str] = []
    known = {
        "packageNamePatterns",
        "licenseHeader",
        "userAgent",
        "publicSdkEnabled",
        "schemaVersion",
    }
    unknown = sorted(str(key) for key in body.keys() if str(key) not in known)
    if unknown:
        errors.append(
            f"unknown setting(s) {', '.join(unknown)}; expected any of "
            "packageNamePatterns, licenseHeader, userAgent, publicSdkEnabled"
        )

    parsed: Dict[str, Any] = {"schemaVersion": SDK_GENERATION_SETTINGS_SCHEMA_VERSION}
    if "packageNamePatterns" in body:
        parsed["packageNamePatterns"] = _parse_package_patterns(
            body["packageNamePatterns"], errors
        )
    if "licenseHeader" in body:
        parsed["licenseHeader"] = _parse_license_header(body["licenseHeader"], errors)
    if "userAgent" in body:
        parsed["userAgent"] = _parse_user_agent(body["userAgent"], errors)
    if "publicSdkEnabled" in body:
        parsed["publicSdkEnabled"] = _parse_public_sdk_enabled(body["publicSdkEnabled"], errors)

    if errors:
        raise SdkSettingsError(errors)
    return parsed


def merge_settings_bodies(*bodies: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Combine stored bodies least-specific first, key by key.

    ``packageNamePatterns`` merges one ecosystem at a time, so a project overriding only ``npm``
    keeps its tenant's ``pypi`` pattern. Everywhere else the most specific body that *names* a key
    wins — including when it names it as ``null``, which is how a project asks for no licence
    header at all.

    Args:
        *bodies: Stored bodies in precedence order, least specific first (tenant, then project).

    Returns:
        The merged body, with ``None`` values preserved (they mean "deliberately none").
    """
    merged: Dict[str, Any] = {}
    patterns: Dict[str, Any] = {}
    for body in bodies:
        if not body:
            continue
        for key, value in body.items():
            if key == "schemaVersion":
                continue
            if key == "packageNamePatterns":
                if value is None:
                    # The whole map was explicitly cleared: drop what earlier scopes contributed.
                    patterns = {}
                elif isinstance(value, Mapping):
                    patterns.update({str(k): v for k, v in value.items()})
                continue
            merged[key] = value
    merged["packageNamePatterns"] = patterns
    return merged


def settings_from_body(body: Optional[Mapping[str, Any]]) -> SdkGenerationSettings:
    """Read a merged body into the settings model, dropping deliberately-cleared keys.

    A ``None`` value did its job during the merge — it stopped a less specific scope from
    contributing — and beyond that point "cleared" and "never set" are the same thing.

    Args:
        body: A merged body (from :func:`merge_settings_bodies`), or ``None``.

    Returns:
        The settings. Values this release does not understand are ignored rather than raising:
        a body written by a newer release must still resolve.
    """
    if not body:
        return SdkGenerationSettings()

    raw_patterns = body.get("packageNamePatterns") or {}
    patterns: Dict[str, str] = {}
    if isinstance(raw_patterns, Mapping):
        for ecosystem in ECOSYSTEMS:
            value = raw_patterns.get(ecosystem)
            if isinstance(value, str) and value.strip():
                patterns[ecosystem] = value.strip()

    header = body.get("licenseHeader")
    agent = body.get("userAgent")
    # An explicit `null` (or anything that is not a real bool) collapses to "off" here, the same
    # way a cleared licence header collapses to None: the merge already used the null to block
    # inheritance, and past that point "cleared" and "never set" mean the same thing.
    public_sdk = body.get("publicSdkEnabled")
    return SdkGenerationSettings(
        package_name_patterns=patterns,
        license_header=header.strip() if isinstance(header, str) and header.strip() else None,
        user_agent=agent.strip() if isinstance(agent, str) and agent.strip() else None,
        public_sdk_enabled=public_sdk if isinstance(public_sdk, bool) else False,
    )


def canonical_settings_body(settings: SdkGenerationSettings) -> Dict[str, Any]:
    """Render merged settings as the stable dict that is fingerprinted.

    Always the full body with every key present, even the unset ones: a fingerprint must keep
    meaning the same thing after a later release adds a setting.

    Args:
        settings: The merged settings.

    Returns:
        A JSON-ready dict with camelCase keys and a ``schemaVersion``.
    """
    body = settings.model_dump(by_alias=True, mode="json")
    body["schemaVersion"] = SDK_GENERATION_SETTINGS_SCHEMA_VERSION
    return body


def settings_content_fingerprint(settings: SdkGenerationSettings) -> str:
    """Return a stable ``sha256:`` digest of merged settings.

    This is SDK-3.4's determinism guarantee: two projects whose merged settings fingerprint the
    same get byte-identical branding applied to their artifacts, and a changed artifact can be
    attributed to changed branding rather than to a changed API.

    Args:
        settings: The merged settings to digest.

    Returns:
        ``"sha256:<hex>"``.
    """
    blob = json.dumps(
        canonical_settings_body(settings),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"sha256:{hashlib.sha256(blob.encode('utf-8')).hexdigest()}"
