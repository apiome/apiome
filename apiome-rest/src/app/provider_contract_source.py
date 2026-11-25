"""Render a provider contract from an Apiome version — PFX-2.1 (#6925).

A provider described in Apiome does not need to export and upload its OpenAPI document: a publish
request may name the version instead (``apiomeVersion: "ledger-api@1.4.0"``), and the document is
rendered by the exporter ``GET /v1/schema/{tenant}/{project}/{version}`` serves (the canonical
model emitted as OpenAPI 3.1, :data:`app.rendered_documents.KIND_OPENAPI`), then validated and
stored like an uploaded one.

* **The project may come from the provider.** A provider pacticipant bound to an Apiome project
  (``PATCH …/pacticipants/{p}`` with ``project``) may name just the version: ``1.4.0``, or
  ``latest`` for the project's newest version.
* **The version may be** a label (``1.4.0``), a revision id, or ``latest``. Drafts are accepted:
  the caller is a workspace member with ``versions:view``, and what is stored is a snapshot.
* **Everything is resolved inside the caller's tenant**; another workspace's project is
  "not found".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from .pacticipant_store import get_pacticipant
from .provider_contract import (
    CODE_SOURCE_NOT_FOUND,
    JSON_CONTENT_TYPE,
    SOURCE_APIOME,
    ApiomeReference,
    ProviderContractError,
    ProviderContractToStore,
    prepare_contract,
)
from .rendered_documents import KIND_OPENAPI, rendered_document
from .revision_deprecation import is_uuid_string

__all__ = ["ResolvedSource", "render_apiome_contract", "resolve_apiome_source"]

_POINTER = "/apiomeVersion"


@dataclass(frozen=True)
class ResolvedSource:
    """The Apiome project and version a contract is rendered from.

    Attributes:
        project_id: The project's id.
        project_slug: Its slug.
        version_id: The revision's id (``versions.id``).
        version_label: The version's label (``versions.version_id``).
    """

    project_id: str
    project_slug: str
    version_id: str
    version_label: str


def _not_found(message: str) -> ProviderContractError:
    """A ``provider-contract-source-not-found`` refusal located at ``/apiomeVersion``."""
    return ProviderContractError(CODE_SOURCE_NOT_FOUND, message, pointer=_POINTER)


def _bound_project_id(db: Any, tenant_id: str, provider_name: str) -> str:
    """The project the provider pacticipant is bound to.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_name: The provider in the URL.

    Returns:
        The bound project's id.

    Raises:
        ProviderContractError: ``provider-contract-source-not-found`` when the provider is not
            registered yet or is not bound to a project.
    """
    try:
        provider = get_pacticipant(db, tenant_id, provider_name)
    except PacticipantValidationError as exc:
        if exc.code != CODE_NOT_FOUND:
            raise
        provider = None
    if provider is None or not provider.project_id:
        raise _not_found(
            f"apiomeVersion names no project and the provider '{provider_name}' is not bound to one; "
            f"send '<project>@<version>', or bind the provider to its project first"
        )
    return provider.project_id


def _project(db: Any, tenant_id: str, ref: str) -> Dict[str, Any]:
    """A live project of the tenant by slug or id, or a ``source-not-found`` refusal."""
    row = db.get_project_core(ref, tenant_id) if is_uuid_string(ref) else db.get_project_by_slug(ref, tenant_id)
    if not row or row.get("deleted_at"):
        raise _not_found(f"no project '{ref}' in this workspace")
    return row


def _version(db: Any, tenant_id: str, project: Dict[str, Any], ref: str) -> Dict[str, Any]:
    """A live version of the project by label, revision id or ``latest``.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        project: The project row.
        ref: The version reference.

    Returns:
        The version row.

    Raises:
        ProviderContractError: ``provider-contract-source-not-found`` when nothing matches.
    """
    project_id = str(project["id"])
    row: Optional[Dict[str, Any]]
    if ref.lower() == "latest":
        latest = db.get_latest_revision_id_for_project(project_id, tenant_id)
        if not latest:
            raise _not_found(f"project '{project.get('slug')}' has no versions")
        row = db.get_version_core(str(latest), tenant_id)
    elif is_uuid_string(ref):
        row = db.get_version_core(ref, tenant_id)
        if row is not None and str(row.get("project_id")) != project_id:
            row = None
    else:
        row = db.get_version_by_version_id(project_id, ref, tenant_id)
    if not row:
        raise _not_found(f"no version '{ref}' in project '{project.get('slug')}'")
    return row


def resolve_apiome_source(db: Any, tenant_id: str, provider_name: str, reference: ApiomeReference) -> ResolvedSource:
    """Resolve ``apiomeVersion`` to a project and version of the caller's tenant.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_name: The provider in the URL (its binding supplies a missing project).
        reference: The parsed ``apiomeVersion``.

    Returns:
        The project and version.

    Raises:
        ProviderContractError: ``provider-contract-source-not-found`` (pointer
            ``/apiomeVersion``) for an unknown project or version, or a missing project with no
            binding to fall back on.
    """
    project_ref = reference.project or _bound_project_id(db, tenant_id, provider_name)
    project = _project(db, tenant_id, project_ref)
    version = _version(db, tenant_id, project, reference.version)
    return ResolvedSource(
        project_id=str(project["id"]),
        project_slug=str(project.get("slug") or project_ref),
        version_id=str(version["id"]),
        version_label=str(version.get("version_id") or reference.version),
    )


def render_apiome_contract(
    db: Any,
    tenant_id: str,
    source: ResolvedSource,
    *,
    verification_results: Optional[Dict[str, Any]] = None,
) -> ProviderContractToStore:
    """Render a resolved version's OpenAPI document and validate it as a provider contract.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        source: The resolved project and version.
        verification_results: The self-verification results as stored.

    Returns:
        The contract, with its source recorded.

    Raises:
        ProviderContractError: ``provider-contract-source-not-found`` when the revision cannot be
            rendered in the tenant; ``provider-contract-invalid`` when the rendered document does
            not validate.
    """
    document = rendered_document(source.version_id, KIND_OPENAPI, tenant_id=tenant_id, database=db)
    if document is None:
        raise _not_found(f"version '{source.version_label}' of project '{source.project_slug}' cannot be rendered")
    return prepare_contract(
        document.json(),
        content_type=JSON_CONTENT_TYPE,
        verification_results=verification_results,
        source=SOURCE_APIOME,
        source_project_id=source.project_id,
        source_version_id=source.version_id,
        source_project_slug=source.project_slug,
        source_version_label=source.version_label,
    )
