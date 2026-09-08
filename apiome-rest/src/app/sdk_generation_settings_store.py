"""Persistence for SDK generation settings — SDK-3.4 (#4494).

:mod:`app.sdk_generation_settings` decides what a setting *means*; this module is the only place
one is read or written, so V255's rules are applied once rather than at each call site.

**Two scopes, merged key by key.** The store reads both rows in one query and folds them
tenant-first, so a project that overrides only its user-agent still inherits its tenant's package
pattern. This is the one place SDK-3.4 departs from CTG-4.5's whole-body override, and the reason
the stored bodies carry only the keys their author named.

**Unreadable settings still answer.** Branding is applied on read paths that must not fail because
a settings row could not be parsed — a snippet is more useful unbranded than not at all. Every
loader falls back to "nothing configured" and marks the result ``degraded``, so a caller can tell
"this tenant has set nothing" from "I could not read what it set".
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .database import db
from .sdk_generation_settings import (
    SETTINGS_SOURCE_DEFAULT,
    SETTINGS_SOURCE_MERGED,
    SETTINGS_SOURCE_PROJECT,
    SETTINGS_SOURCE_TENANT,
    PatternContext,
    ResolvedBranding,
    ResolvedBrandingOut,
    SdkGenerationSettings,
    SdkGenerationSettingsOut,
    SdkSettingsError,
    canonical_settings_body,
    merge_settings_bodies,
    parse_settings_body,
    resolve_branding,
    settings_content_fingerprint,
    settings_from_body,
)

logger = logging.getLogger(__name__)

__all__ = [
    # Re-exported so a caller of the store needs one import for the error it must handle.
    "SdkSettingsError",
    "audit_detail",
    "clear_settings",
    "load_branding",
    "load_settings",
    "save_settings",
]


def _scope_name(project_id: Optional[str]) -> str:
    """Return the scope label a project id addresses."""
    return SETTINGS_SOURCE_PROJECT if project_id else SETTINGS_SOURCE_TENANT


def _split_rows(
    rows: Sequence[Mapping[str, Any]],
) -> Tuple[Optional[Mapping[str, Any]], Optional[Mapping[str, Any]]]:
    """Separate the contributing rows into ``(tenant_row, project_row)``.

    The query orders tenant-first, but splitting on ``project_id`` rather than on position means a
    change to that ordering cannot silently invert the precedence.

    Args:
        rows: The rows returned for a scope.

    Returns:
        The tenant-wide row and the project override, either of which may be ``None``.
    """
    tenant_row: Optional[Mapping[str, Any]] = None
    project_row: Optional[Mapping[str, Any]] = None
    for row in rows:
        if row.get("project_id"):
            project_row = row
        else:
            tenant_row = row
    return tenant_row, project_row


def _body_of(row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a row's stored settings body, or ``None`` when it is missing or unusable."""
    if row is None:
        return None
    body = row.get("settings")
    if isinstance(body, Mapping):
        return dict(body)
    return None


def _source_for(
    tenant_row: Optional[Mapping[str, Any]], project_row: Optional[Mapping[str, Any]]
) -> str:
    """Say which scopes contributed to the settings in force."""
    if tenant_row is not None and project_row is not None:
        return SETTINGS_SOURCE_MERGED
    if project_row is not None:
        return SETTINGS_SOURCE_PROJECT
    if tenant_row is not None:
        return SETTINGS_SOURCE_TENANT
    return SETTINGS_SOURCE_DEFAULT


def _out(
    *,
    settings: SdkGenerationSettings,
    source: str,
    scope: str,
    scope_body: Optional[Dict[str, Any]],
    context: PatternContext,
    tenant_row: Optional[Mapping[str, Any]] = None,
    project_row: Optional[Mapping[str, Any]] = None,
    degraded: bool = False,
) -> SdkGenerationSettingsOut:
    """Assemble the wire model for a resolved scope.

    Args:
        settings: The merged settings.
        source: Which scopes contributed.
        scope: The scope the caller addressed.
        scope_body: The body saved at exactly that scope.
        context: Coordinates the patterns are resolved against.
        tenant_row: The contributing tenant row, when there is one.
        project_row: The contributing project row, when there is one.
        degraded: True when a row could not be read and was skipped.

    Returns:
        The response.
    """
    resolved: ResolvedBranding = resolve_branding(settings, context)
    most_specific = project_row or tenant_row
    updated_at = most_specific.get("updated_at") if most_specific else None
    updated_by = most_specific.get("updated_by") if most_specific else None
    return SdkGenerationSettingsOut(
        source=source,
        content_fingerprint=settings_content_fingerprint(settings),
        settings=settings,
        resolved=ResolvedBrandingOut(
            package_names=resolved.package_names,
            license_header=resolved.license_header,
            user_agent=resolved.user_agent,
        ),
        scope=scope,
        scope_body=scope_body,
        tenant_settings_id=str(tenant_row["id"]) if tenant_row and tenant_row.get("id") else None,
        project_settings_id=(
            str(project_row["id"]) if project_row and project_row.get("id") else None
        ),
        updated_at=updated_at if isinstance(updated_at, datetime) else None,
        updated_by=str(updated_by) if updated_by else None,
        degraded=degraded,
    )


def _default_out(
    scope: str, context: PatternContext, *, degraded: bool = False
) -> SdkGenerationSettingsOut:
    """The response for a scope with nothing configured (or nothing readable)."""
    return _out(
        settings=SdkGenerationSettings(),
        source=SETTINGS_SOURCE_DEFAULT,
        scope=scope,
        scope_body=None,
        context=context,
        degraded=degraded,
    )


def load_settings(
    tenant_id: str,
    project_id: Optional[str] = None,
    context: Optional[PatternContext] = None,
) -> SdkGenerationSettingsOut:
    """Return the generation settings in force for a scope.

    Never raises. A store failure degrades to "nothing configured" rather than failing the caller:
    every surface that brands an artifact reads this, and an infrastructure fault must not stop
    them all.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project to resolve for; ``None`` reads only the tenant-wide settings.
        context: Coordinates the patterns resolve against. Defaults to an empty context, which
            renders ``{project}``-style tokens away rather than leaving literal braces behind.

    Returns:
        The resolved settings, with ``source`` saying which scopes supplied them.
    """
    ctx = context or PatternContext()
    scope = _scope_name(project_id)
    if not tenant_id:
        return _default_out(scope, ctx)
    try:
        rows: List[Dict[str, Any]] = db.get_sdk_generation_settings_rows(
            tenant_id, project_id
        )
    except Exception:  # noqa: BLE001 - branding must never take a read path down with it
        logger.warning(
            "Could not load SDK generation settings for tenant %s; using none",
            tenant_id,
            exc_info=True,
        )
        return _default_out(scope, ctx, degraded=True)

    tenant_row, project_row = _split_rows(rows)
    tenant_body = _body_of(tenant_row)
    project_body = _body_of(project_row)
    # A row whose body is not an object was written by something this release cannot read. It is
    # skipped rather than raising — but the caller is told, so the substitution is visible.
    degraded = (tenant_row is not None and tenant_body is None) or (
        project_row is not None and project_body is None
    )
    if project_id:
        merged = merge_settings_bodies(tenant_body, project_body)
        scope_body = project_body
    else:
        merged = merge_settings_bodies(tenant_body)
        scope_body = tenant_body

    return _out(
        settings=settings_from_body(merged),
        source=_source_for(tenant_row, project_row if project_id else None),
        scope=scope,
        scope_body=scope_body,
        context=ctx,
        tenant_row=tenant_row,
        project_row=project_row if project_id else None,
        degraded=degraded,
    )


def load_branding(
    tenant_id: Optional[str],
    project_id: Optional[str] = None,
    context: Optional[PatternContext] = None,
) -> ResolvedBranding:
    """Return just the token-substituted branding in force, for a rendering surface.

    The convenience entry point for consumers that only need "what do I stamp on this artifact?"
    — currently the SDK-2.3 snippet routes. Never raises, and returns empty branding for a caller
    with no tenant context at all.

    Args:
        tenant_id: The owning tenant, or ``None`` when there is none to read.
        project_id: The project being rendered for, when known.
        context: Coordinates the patterns resolve against.

    Returns:
        The :class:`~app.sdk_generation_settings.ResolvedBranding` to apply.
    """
    if not tenant_id:
        return ResolvedBranding(package_names={})
    out = load_settings(tenant_id, project_id, context)
    return ResolvedBranding(
        package_names=dict(out.resolved.package_names),
        license_header=out.resolved.license_header,
        user_agent=out.resolved.user_agent,
    )


def save_settings(
    tenant_id: str,
    *,
    project_id: Optional[str] = None,
    body: Optional[Mapping[str, Any]],
    actor_id: Optional[str] = None,
    context: Optional[PatternContext] = None,
) -> SdkGenerationSettingsOut:
    """Save the settings for one scope, replacing whatever it held.

    Args:
        tenant_id: Owning tenant.
        project_id: The project these settings govern, or ``None`` for the tenant-wide row.
        body: The ``sdk.generation-settings.v1`` body. Only the keys it names are stored, so a
            body naming one setting configures exactly that one and leaves the rest inheriting.
        actor_id: The user making the change.
        context: Coordinates the response's resolved values are rendered against.

    Returns:
        The settings now in force for that scope (the saved row merged with what it inherits).

    Raises:
        SdkSettingsError: When the body is not valid.
        RuntimeError: When the write returned no row (a malformed tenant id).
    """
    parsed = parse_settings_body(body)
    # The stored row is fingerprinted on its own body; the response carries the fingerprint of the
    # merged result, which is the value that actually governs an artifact.
    row_fingerprint = settings_content_fingerprint(
        settings_from_body(merge_settings_bodies(parsed))
    )
    row = db.upsert_sdk_generation_settings(
        tenant_id=tenant_id,
        project_id=project_id,
        settings=parsed,
        content_fingerprint=row_fingerprint,
        actor_id=actor_id,
    )
    if not row:
        raise RuntimeError(
            "The SDK generation settings could not be stored for this tenant."
        )
    return load_settings(tenant_id, project_id, context)


def clear_settings(tenant_id: str, *, project_id: Optional[str] = None) -> bool:
    """Remove the settings saved for one scope, falling back to the next one up.

    A project override is dropped in favour of the tenant settings; the tenant settings are dropped
    in favour of nothing. Nothing cascades: clearing a tenant's settings leaves its projects'
    overrides in place, because those were configured deliberately.

    Args:
        tenant_id: Owning tenant.
        project_id: The project override to drop, or ``None`` for the tenant-wide row.

    Returns:
        True when settings were saved for that exact scope and have now been removed.
    """
    return db.delete_sdk_generation_settings(tenant_id, project_id) > 0


def audit_detail(settings: SdkGenerationSettingsOut) -> Dict[str, Any]:
    """Build the audit payload for a settings change.

    Records the *merged* body and its fingerprint, so a later reader can see the branding that was
    actually in force without joining back to rows that may since have changed again. The licence
    header is recorded by length rather than verbatim: it can be four thousand characters, and the
    audit ledger is not a document store.

    Args:
        settings: The settings that were saved.

    Returns:
        The payload to record.
    """
    body = canonical_settings_body(settings.settings)
    header = body.get("licenseHeader")
    body["licenseHeader"] = (
        f"<{len(header)} characters>" if isinstance(header, str) else None
    )
    return {
        "source": settings.source,
        "scope": settings.scope,
        "contentFingerprint": settings.content_fingerprint,
        "settings": body,
    }
