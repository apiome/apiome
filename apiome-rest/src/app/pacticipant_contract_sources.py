"""Standing sources of a provider contract — PFX-8.7 (#7304).

A provider pacticipant may say, once, where its provider contract comes from, so nobody has to
remember to publish it for every version:

* **On every project publish** (``onProjectPublish``): each time a version of the project the
  pacticipant is bound to (``PATCH …/pacticipants/{p}`` with ``project``) is published, that
  version is rendered and published as the contract of provider version ``<version label>``.
  Drafts are never published.
* **On every push** (``repository``): on every push to ``branch`` of a registered repository, the
  file at ``path`` is published with the pushed commit as the provider version.

This module validates a setting and reads and writes the ``provider_contract_source`` row (apiome-db
V453). The publishing itself is :mod:`app.provider_contract_auto_publish`; the routes are
:mod:`app.pacticipant_contract_source_routes`.

**Nothing is silently dropped.** A setting that could never fire is refused with a reason: turning
on project publishes for a pacticipant bound to no project, a repository of another workspace, a
repository whose files cannot be read on a push (only GitHub's can), and a path that is not a
repository-relative ``.yaml`` / ``.yml`` / ``.json`` file. A repository without a push webhook is
accepted with a warning, since the webhook can be set up afterwards.

**Turning a source off stops new publishes only**: contracts already published stay as they are.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .pacticipant import PacticipantRecord, PacticipantValidationError, validate_branch
from .revision_deprecation import is_uuid_string

__all__ = [
    "CODE_NO_PROJECT",
    "CODE_REPOSITORY_NOT_FOUND",
    "CODE_REPOSITORY_UNSUPPORTED",
    "CODE_INVALID_PATH",
    "CONTRACT_FILE_SUFFIXES",
    "SUPPORTED_REPOSITORY_PROVIDERS",
    "ContractSourcesInput",
    "ContractSourcesRecord",
    "RepositorySourceInput",
    "get_contract_sources",
    "put_contract_sources",
    "validate_contract_path",
]

#: ``onProjectPublish`` for a pacticipant bound to no project: it would never fire.
CODE_NO_PROJECT = "contract-source-no-project"
#: The repository is not registered in the caller's workspace.
CODE_REPOSITORY_NOT_FOUND = "contract-source-repository-not-found"
#: The repository's files cannot be read on a push.
CODE_REPOSITORY_UNSUPPORTED = "contract-source-repository-unsupported"
#: The path is not a repository-relative OpenAPI / AsyncAPI file.
CODE_INVALID_PATH = "contract-source-invalid-path"

#: The repository providers whose files a push can be read from (the contents API Apiome speaks).
SUPPORTED_REPOSITORY_PROVIDERS = ("github",)

#: The file names a provider contract may be read from.
CONTRACT_FILE_SUFFIXES = (".yaml", ".yml", ".json")

_MAX_PATH = 1024


class RepositorySourceInput(BaseModel):
    """Publish a repository file on every push to a branch.

    Attributes:
        repository_id: A repository registered in the workspace (``GET /v1/tenants/{t}/repositories``).
        path: The OpenAPI or AsyncAPI document, relative to the repository root.
        branch: The branch whose pushes publish the file; the pushed commit is the provider version.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    repository_id: str = Field(alias="repositoryId", description="A repository registered in this workspace.")
    path: str = Field(description="The OpenAPI or AsyncAPI document, relative to the repository root.")
    branch: str = Field(
        description="The branch whose pushes publish the file; the pushed commit is the provider version."
    )


class ContractSourcesInput(BaseModel):
    """The standing sources of a provider contract, replaced as a whole.

    Attributes:
        on_project_publish: Publish each published version of the bound project.
        repository: Publish a repository file on every push, or ``None`` for no repository source.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    on_project_publish: bool = Field(
        default=False,
        alias="onProjectPublish",
        description="Publish each published version of the bound project as the provider contract.",
    )
    repository: Optional[RepositorySourceInput] = Field(
        default=None, description="Publish a repository file on every push; `null` for none."
    )


class ProjectSourceRecord(BaseModel):
    """The project whose published versions become the provider contract."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    slug: Optional[str] = None
    name: Optional[str] = None


class RepositorySourceRecord(BaseModel):
    """The repository file published on every push."""

    model_config = ConfigDict(populate_by_name=True)

    repository_id: Optional[str] = Field(default=None, serialization_alias="repositoryId")
    full_name: Optional[str] = Field(default=None, serialization_alias="fullName")
    provider: Optional[str] = None
    path: str
    branch: str
    webhook: bool = Field(
        default=False, description="Whether the repository has a push webhook; without one no push arrives."
    )


class ContractSourcesRecord(BaseModel):
    """A provider pacticipant's standing contract sources, as stored.

    Attributes:
        pacticipant: The pacticipant's handle.
        on_project_publish: Whether each published version of the bound project is published.
        project: The bound project (``None`` when the pacticipant is bound to none).
        repository: The repository source, or ``None``.
        warnings: Why a stored source will not fire right now (no project, repository deleted,
            no push webhook).
        updated_at: When the setting last changed; ``None`` when it was never set.
    """

    model_config = ConfigDict(populate_by_name=True)

    pacticipant: str
    on_project_publish: bool = Field(default=False, serialization_alias="onProjectPublish")
    project: Optional[ProjectSourceRecord] = None
    repository: Optional[RepositorySourceRecord] = None
    warnings: List[str] = Field(default_factory=list)
    updated_at: Optional[str] = Field(default=None, serialization_alias="updatedAt")


def validate_contract_path(path: str) -> str:
    """Return a repository-relative contract path, normalised, or refuse it.

    Args:
        path: The path as sent.

    Returns:
        The path with forward slashes and no leading ``./`` or ``/``.

    Raises:
        PacticipantValidationError: ``contract-source-invalid-path`` for an empty, absolute,
            ``..``-climbing, over-long or non-``.yaml`` / ``.yml`` / ``.json`` path.
    """
    text = str(path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if not text:
        raise PacticipantValidationError(CODE_INVALID_PATH, "the contract path is empty")
    if text.startswith("/"):
        raise PacticipantValidationError(
            CODE_INVALID_PATH, f"'{text}' is absolute; give the path relative to the repository root"
        )
    if any(part in ("", ".", "..") for part in text.split("/")):
        raise PacticipantValidationError(CODE_INVALID_PATH, f"'{text}' is not a plain repository path")
    if len(text) > _MAX_PATH:
        raise PacticipantValidationError(CODE_INVALID_PATH, f"the contract path is over {_MAX_PATH} characters")
    if not text.lower().endswith(CONTRACT_FILE_SUFFIXES):
        raise PacticipantValidationError(
            CODE_INVALID_PATH,
            f"'{text}' is not an OpenAPI or AsyncAPI document: the file must end in .yaml, .yml or .json",
        )
    return text


_SELECT = """
    SELECT s.on_project_publish, s.repository_id::text AS repository_id, s.repository_path,
           s.repository_branch, s.updated_at,
           r.repository_full_name, r.provider AS repository_provider
    FROM apiome.provider_contract_source s
    LEFT JOIN apiome.tenant_repositories r
           ON r.id = s.repository_id AND r.tenant_id = s.tenant_id AND r.deleted_at IS NULL
    WHERE s.pacticipant_id = %s::uuid AND s.tenant_id = %s::uuid
"""


def _project(db: Any, tenant_id: str, pacticipant: PacticipantRecord) -> Optional[ProjectSourceRecord]:
    """The pacticipant's bound project, when it still exists."""
    if not pacticipant.project_id:
        return None
    row = db.get_project_core(pacticipant.project_id, tenant_id)
    if not row:
        return None
    return ProjectSourceRecord(id=str(row["id"]), slug=row.get("slug"), name=row.get("name"))


def _has_webhook(db: Any, tenant_id: str, repository_id: str) -> bool:
    """Whether the repository has a push webhook subscription (best-effort; ``False`` on error)."""
    try:
        return db.get_repository_webhook_subscription(tenant_id, repository_id) is not None
    except Exception:  # noqa: BLE001 - only a warning depends on it
        return False


def get_contract_sources(db: Any, tenant_id: str, pacticipant: PacticipantRecord) -> ContractSourcesRecord:
    """Read a pacticipant's standing contract sources.

    Args:
        db: The database.
        tenant_id: The caller's tenant (the pacticipant was resolved in it).
        pacticipant: The pacticipant.

    Returns:
        The sources, with a warning for each one that will not fire right now. A pacticipant that
        never set any has both off.
    """
    rows = db.execute_query(_SELECT, (pacticipant.id, tenant_id)) or []
    project = _project(db, tenant_id, pacticipant)
    record = ContractSourcesRecord(pacticipant=pacticipant.slug, project=project)
    if not rows:
        return record
    row = dict(rows[0])
    record.on_project_publish = bool(row.get("on_project_publish"))
    updated = row.get("updated_at")
    record.updated_at = updated.isoformat() if hasattr(updated, "isoformat") else (str(updated) if updated else None)
    if record.on_project_publish and project is None:
        record.warnings.append(
            "Publishing on every project publish is on, but the pacticipant is not bound to a project, "
            "so nothing is published."
        )
    if row.get("repository_path") and row.get("repository_branch"):
        repository_id = row.get("repository_id")
        record.repository = RepositorySourceRecord(
            repository_id=repository_id,
            full_name=row.get("repository_full_name"),
            provider=row.get("repository_provider"),
            path=row["repository_path"],
            branch=row["repository_branch"],
            webhook=bool(repository_id) and _has_webhook(db, tenant_id, repository_id),
        )
        if not repository_id or not row.get("repository_full_name"):
            record.warnings.append(
                f"The repository that {row['repository_path']} was read from was deleted, so pushes publish nothing."
            )
        elif not record.repository.webhook:
            record.warnings.append(
                f"{row['repository_full_name']} has no push webhook, so no push reaches Apiome; set one up "
                "on the repository's page."
            )
    return record


def _checked_repository(db: Any, tenant_id: str, source: RepositorySourceInput) -> Dict[str, Any]:
    """The registered repository a source names, refused unless its pushes can publish.

    Raises:
        PacticipantValidationError: ``contract-source-repository-not-found`` for a repository of
            another workspace (or none); ``contract-source-repository-unsupported`` for a provider
            whose files cannot be read; ``contract-source-invalid-path`` / ``pacticipant-invalid-branch``.
    """
    repository_id = str(source.repository_id or "").strip()
    row = db.get_tenant_repository(tenant_id, repository_id) if is_uuid_string(repository_id) else None
    if not row:
        raise PacticipantValidationError(
            CODE_REPOSITORY_NOT_FOUND, f"no repository '{repository_id}' is registered in this workspace"
        )
    provider = str(row.get("provider") or "").lower()
    if provider not in SUPPORTED_REPOSITORY_PROVIDERS:
        raise PacticipantValidationError(
            CODE_REPOSITORY_UNSUPPORTED,
            f"{row.get('repository_full_name') or repository_id} is a {provider or 'unknown'} repository; publishing "
            "a file on every push reads it through GitHub's contents API, so only GitHub repositories are "
            "supported. Publish from your pipeline with `apiome pact publish-provider-contract` instead.",
        )
    return dict(row)


def put_contract_sources(
    db: Any,
    tenant_id: str,
    pacticipant: PacticipantRecord,
    body: ContractSourcesInput,
    *,
    user_id: Optional[str],
) -> ContractSourcesRecord:
    """Replace a pacticipant's standing contract sources.

    Args:
        db: The database.
        tenant_id: The caller's tenant (the pacticipant was resolved in it).
        pacticipant: The provider pacticipant.
        body: The new sources; both off removes the setting.
        user_id: Who changed it (stored when it is a UUID).

    Returns:
        The sources as stored.

    Raises:
        PacticipantValidationError: ``contract-source-no-project`` when ``onProjectPublish`` is on
            for a pacticipant bound to no project, and the refusals of the repository source.
    """
    if body.on_project_publish and not pacticipant.project_id:
        raise PacticipantValidationError(
            CODE_NO_PROJECT,
            f"{pacticipant.name} is not bound to an Apiome project, so no project publish could publish its "
            "contract; bind it to its project first (PATCH …/pacticipants/{p} with project)",
        )
    repository_id: Optional[str] = None
    path: Optional[str] = None
    branch: Optional[str] = None
    if body.repository is not None:
        path = validate_contract_path(body.repository.path)
        branch = validate_branch(body.repository.branch)
        repository_id = str(_checked_repository(db, tenant_id, body.repository)["id"])
    if not body.on_project_publish and repository_id is None:
        db.execute_query(
            "DELETE FROM apiome.provider_contract_source WHERE pacticipant_id = %s::uuid AND tenant_id = %s::uuid "
            "RETURNING pacticipant_id",
            (pacticipant.id, tenant_id),
        )
        return get_contract_sources(db, tenant_id, pacticipant)
    db.execute_query(
        """
        INSERT INTO apiome.provider_contract_source (
            pacticipant_id, tenant_id, on_project_publish, repository_id, repository_path, repository_branch,
            updated_by
        )
        VALUES (%s::uuid, %s::uuid, %s, %s::uuid, %s, %s, %s::uuid)
        ON CONFLICT (pacticipant_id, tenant_id) DO UPDATE SET
            on_project_publish = EXCLUDED.on_project_publish,
            repository_id = EXCLUDED.repository_id,
            repository_path = EXCLUDED.repository_path,
            repository_branch = EXCLUDED.repository_branch,
            updated_by = EXCLUDED.updated_by,
            updated_at = CURRENT_TIMESTAMP
        RETURNING pacticipant_id
        """,
        (
            pacticipant.id,
            tenant_id,
            body.on_project_publish,
            repository_id,
            path,
            branch,
            user_id if user_id and is_uuid_string(str(user_id)) else None,
        ),
    )
    return get_contract_sources(db, tenant_id, pacticipant)
