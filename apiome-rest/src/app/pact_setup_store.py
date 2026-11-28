"""Reading and saving the Contracts guided set-up — PFX-8.20 (#7317).

:func:`read_state` builds ``GET …/pact-setup`` from a handful of tenant-scoped reads:

* the **facts** the sections are derived from (pacticipants, environments, pacts, provider-contract
  sources, verification results, webhooks, a completed migration). Counts that could grow without
  bound are capped at :data:`FACT_CAP`: a section needs to know *whether*, not exactly how many;
* the **candidates** — projects (with their owner team and the repository they are read from) and
  registered repositories, matched against the live pacticipants by :func:`app.pact_setup.detect_candidates`;
* the registered **GitHub repositories** and whether each can be written with a linked account;
* the workspace's ``pact_setup_progress`` row (apiome-db V460).

:func:`save_progress` merges a :class:`~app.pact_setup.PactSetupSave` into that row and
:func:`record_github` notes what a GitHub action did to a repository; each appends one
``access_audit`` row in its transaction. Every statement is filtered by the caller's tenant.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from .consumer_contract_store import ConsumerActor
from .pact_cleanup_store import audit_tx
from .pact_setup import (
    SECTION_IDS,
    WORKFLOW_PATH,
    PactSetupCiKey,
    PactSetupFacts,
    PactSetupGithub,
    PactSetupGithubRepository,
    PactSetupSave,
    PactSetupSaved,
    PactSetupState,
    derive_sections,
    detect_candidates,
)
from .revision_deprecation import is_uuid_string

__all__ = [
    "CANDIDATE_CAP",
    "FACT_CAP",
    "NO_GITHUB_REPOSITORY",
    "NO_LINKED_ACCOUNT",
    "get_repository",
    "is_writable",
    "read_progress_row",
    "read_state",
    "record_github",
    "save_progress",
]

#: Where an unbounded count stops: the page says "100 or more".
FACT_CAP = 100

#: How many projects and repositories detection reads; the rest are counted in ``candidates_omitted``.
CANDIDATE_CAP = 200

#: Why the secret and pull-request actions are snippets instead.
NO_GITHUB_REPOSITORY = (
    "No GitHub repository is registered in this workspace. Add the two secrets and the workflow by hand, "
    "or register a repository with a linked GitHub account."
)
NO_LINKED_ACCOUNT = (
    "No registered repository has a linked GitHub account, so Apiome cannot write to one. Add the two "
    "secrets and the workflow by hand, or register the repository again with a linked GitHub account."
)

_FACTS = f"""
    SELECT
      (SELECT count(*) FROM apiome.pacticipant WHERE tenant_id = %(t)s::uuid AND deleted_at IS NULL) AS pacticipants,
      (SELECT count(*) FROM (
          SELECT 1 FROM apiome.pacticipant c
          JOIN apiome.pact_publication pp ON pp.consumer_id = c.id
          WHERE c.tenant_id = %(t)s::uuid AND c.deleted_at IS NULL LIMIT {FACT_CAP}) capped) AS pacts,
      (SELECT count(*) FROM apiome.provider_contract_source
        WHERE tenant_id = %(t)s::uuid AND on_project_publish) AS contract_sources,
      (SELECT count(*) FROM (
          SELECT 1 FROM apiome.verification_result WHERE tenant_id = %(t)s::uuid LIMIT {FACT_CAP}) capped
      ) AS verification_results,
      (SELECT count(*) FROM (
          SELECT 1 FROM apiome.pact_webhook WHERE tenant_id = %(t)s::uuid LIMIT {FACT_CAP}) capped) AS webhooks,
      EXISTS (SELECT 1 FROM apiome.pact_migration_run
               WHERE tenant_id = %(t)s::uuid AND status = 'completed') AS migrated
"""

_ENVIRONMENTS = "SELECT name, production FROM apiome.pact_environment WHERE tenant_id = %s::uuid ORDER BY name, id"

_PACTICIPANTS = """
    SELECT p.slug, p.name, p.project_id::text AS project_id, p.repository_url,
           coalesce(s.on_project_publish, false) AS contract_source
    FROM apiome.pacticipant p
    LEFT JOIN apiome.provider_contract_source s ON s.pacticipant_id = p.id AND s.tenant_id = p.tenant_id
    WHERE p.tenant_id = %s::uuid AND p.deleted_at IS NULL ORDER BY p.slug
"""

_PROJECTS = """
    SELECT p.id::text AS id, p.slug, p.name, t.name AS owner,
           src.repository_id::text AS repository_id, src.branch AS repository_branch
    FROM apiome.projects p
    LEFT JOIN apiome.entity_owners eo
           ON eo.tenant_id = p.tenant_id AND eo.entity_kind = 'project' AND eo.entity_id = p.id
          AND eo.status = 'confirmed'
    LEFT JOIN apiome.teams t ON t.id = eo.team_id AND t.deleted_at IS NULL
    LEFT JOIN LATERAL (
        SELECT prs.repository_id, prs.branch
        FROM apiome.project_repository_sources prs
        WHERE prs.project_id = p.id
        ORDER BY prs.precedence, prs.created_at, prs.id LIMIT 1
    ) src ON TRUE
    WHERE p.tenant_id = %s::uuid AND p.deleted_at IS NULL
    ORDER BY lower(p.name), p.id
    LIMIT %s
"""

_REPOSITORIES = """
    SELECT id::text AS id, provider, clone_url, repository_full_name, default_branch,
           linked_account_id::text AS linked_account_id, created_by::text AS created_by
    FROM apiome.tenant_repositories
    WHERE tenant_id = %s::uuid AND deleted_at IS NULL
    ORDER BY lower(coalesce(repository_full_name, clone_url)), id
    LIMIT %s
"""

_COUNTS = """
    SELECT (SELECT count(*) FROM apiome.projects WHERE tenant_id = %(t)s::uuid AND deleted_at IS NULL) AS projects,
           (SELECT count(*) FROM apiome.tenant_repositories
             WHERE tenant_id = %(t)s::uuid AND deleted_at IS NULL) AS repositories
"""

_PROGRESS_COLUMNS = (
    "marked, first_pact_path, ci_key_id::text AS ci_key_id, ci_key_prefix, github, updated_by_label, updated_at"
)

_PROGRESS = f"SELECT {_PROGRESS_COLUMNS} FROM apiome.pact_setup_progress WHERE tenant_id = %s::uuid"

_KEY_LIVE = """
    SELECT 1 FROM apiome.api_keys
    WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL AND enabled
      AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
"""

_REPOSITORY = """
    SELECT id::text AS id, provider, clone_url, repository_full_name, default_branch,
           linked_account_id::text AS linked_account_id, created_by::text AS created_by
    FROM apiome.tenant_repositories
    WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL
"""


def _iso(value: Any) -> Optional[str]:
    """ISO-8601 text of a timestamp column, or ``None``."""
    return value.isoformat() if isinstance(value, datetime) else (str(value) if value is not None else None)


def _github_map(value: Any) -> Dict[str, Dict[str, Any]]:
    """The per-repository record as a dict of dicts, whatever the driver handed back."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    if not isinstance(value, dict):
        return {}
    return {str(key): dict(item) for key, item in value.items() if isinstance(item, dict)}


def read_progress_row(fetch: Any, tenant_id: str) -> Optional[Dict[str, Any]]:
    """The tenant's ``pact_setup_progress`` row, or ``None``.

    Args:
        fetch: The database's ``execute_query``.
        tenant_id: The tenant.

    Returns:
        The row as a dict, or ``None`` when the workspace saved nothing yet.
    """
    rows = fetch(_PROGRESS, (tenant_id,)) or []
    return dict(rows[0]) if rows else None


def _saved(fetch: Any, tenant_id: str, row: Optional[Mapping[str, Any]]) -> PactSetupSaved:
    """The saved marks and choices; a CI key that is gone, off or expired reads as none."""
    if not row:
        return PactSetupSaved()
    key: Optional[PactSetupCiKey] = None
    key_id, prefix = row.get("ci_key_id"), row.get("ci_key_prefix")
    if key_id and prefix and (fetch(_KEY_LIVE, (key_id, tenant_id)) or []):
        key = PactSetupCiKey(id=str(key_id), prefix=str(prefix))
    marked = [section for section in SECTION_IDS if section in (row.get("marked") or [])]
    return PactSetupSaved(marked=marked, first_pact_path=row.get("first_pact_path"), ci_key=key)  # type: ignore[arg-type]


def is_writable(repository: Mapping[str, Any]) -> bool:
    """Whether a registered repository is a GitHub one registered with a linked account.

    Args:
        repository: A ``tenant_repositories`` row.

    Returns:
        ``True`` when Apiome holds what it needs to try a write (the token itself is only read when
        an action runs).
    """
    return (
        str(repository.get("provider") or "").lower() == "github"
        and bool(str(repository.get("repository_full_name") or "").strip())
        and bool(repository.get("linked_account_id"))
        and bool(repository.get("created_by"))
    )


def _github(
    repositories: List[Dict[str, Any]], pacticipants: List[Dict[str, Any]], record: Dict[str, Dict[str, Any]]
) -> PactSetupGithub:
    """The GitHub repositories and whether the write actions can run."""
    by_url = {
        str(row.get("repository_url") or "").strip().lower().rstrip("/").removesuffix(".git"): row
        for row in pacticipants
        if row.get("repository_url")
    }
    listed: List[PactSetupGithubRepository] = []
    for repository in repositories:
        full_name = str(repository.get("repository_full_name") or "").strip()
        if str(repository.get("provider") or "").lower() != "github" or not full_name:
            continue
        done = record.get(str(repository["id"]), {})
        owner = by_url.get(f"https://github.com/{full_name}".lower())
        listed.append(
            PactSetupGithubRepository(
                id=str(repository["id"]),
                full_name=full_name,
                default_branch=str(repository.get("default_branch") or "") or None,
                linked=is_writable(repository),
                pacticipant=str(owner["slug"]) if owner else None,
                pacticipant_name=str(owner.get("name") or "") or None if owner else None,
                secrets_written_at=done.get("secrets_at"),
                pull_request_url=done.get("pull_request_url"),
            )
        )
    linked = any(item.linked for item in listed)
    reason = None if linked else (NO_LINKED_ACCOUNT if listed else NO_GITHUB_REPOSITORY)
    return PactSetupGithub(linked=linked, reason=reason, repositories=listed)


def read_state(fetch: Any, tenant_id: str, *, can_edit: bool = False) -> PactSetupState:
    """Everything the set-up page and ``apiome pact setup`` read.

    Args:
        fetch: The database's ``execute_query``.
        tenant_id: The caller's tenant.
        can_edit: Whether the caller may act on the page; copied to the answer.

    Returns:
        The state. A malformed tenant id reads as an empty workspace.
    """
    if not is_uuid_string(str(tenant_id or "")):
        facts, saved = PactSetupFacts(), PactSetupSaved()
        return PactSetupState(
            sections=derive_sections(facts, saved),
            done=0,
            total=len(SECTION_IDS),
            complete=False,
            facts=facts,
            saved=saved,
            github=PactSetupGithub(linked=False, reason=NO_GITHUB_REPOSITORY),
            workflow_path=WORKFLOW_PATH,
            can_edit=can_edit,
        )
    counted = dict((fetch(_FACTS, {"t": tenant_id}) or [{}])[0])
    environments = [dict(row) for row in fetch(_ENVIRONMENTS, (tenant_id,)) or []]
    facts = PactSetupFacts(
        pacticipants=int(counted.get("pacticipants") or 0),
        environments=[str(row["name"]) for row in environments],
        production_environment=any(bool(row.get("production")) for row in environments),
        pacts=int(counted.get("pacts") or 0),
        contract_sources=int(counted.get("contract_sources") or 0),
        verification_results=int(counted.get("verification_results") or 0),
        webhooks=int(counted.get("webhooks") or 0),
        migrated=bool(counted.get("migrated")),
    )
    row = read_progress_row(fetch, tenant_id)
    saved = _saved(fetch, tenant_id, row)
    pacticipants = [dict(item) for item in fetch(_PACTICIPANTS, (tenant_id,)) or []]
    projects = [dict(item) for item in fetch(_PROJECTS, (tenant_id, CANDIDATE_CAP)) or []]
    repositories = [dict(item) for item in fetch(_REPOSITORIES, (tenant_id, CANDIDATE_CAP)) or []]
    totals = dict((fetch(_COUNTS, {"t": tenant_id}) or [{}])[0])
    omitted = max(0, int(totals.get("projects") or 0) - len(projects)) + max(
        0, int(totals.get("repositories") or 0) - len(repositories)
    )
    sections = derive_sections(facts, saved)
    done = sum(1 for section in sections if section.state == "done")
    return PactSetupState(
        sections=sections,
        done=done,
        total=len(sections),
        complete=done == len(sections),
        facts=facts,
        saved=saved,
        candidates=detect_candidates(projects, repositories, pacticipants),
        candidates_omitted=omitted,
        github=_github(repositories, pacticipants, _github_map((row or {}).get("github"))),
        workflow_path=WORKFLOW_PATH,
        can_edit=can_edit,
        updated_at=_iso((row or {}).get("updated_at")),
        updated_by=(row or {}).get("updated_by_label"),
    )


def get_repository(fetch: Any, tenant_id: str, repository_id: str) -> Optional[Dict[str, Any]]:
    """One registered repository of the tenant, or ``None``.

    Args:
        fetch: The database's ``execute_query``.
        tenant_id: The caller's tenant.
        repository_id: The repository's id; anything that is not a UUID reads as not found.

    Returns:
        The row, or ``None`` when it is not this tenant's (or is deleted).
    """
    if not is_uuid_string(str(repository_id or "")) or not is_uuid_string(str(tenant_id or "")):
        return None
    rows = fetch(_REPOSITORY, (repository_id, tenant_id)) or []
    return dict(rows[0]) if rows else None


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a storable UUID, else ``None``."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


_UPSERT = """
    INSERT INTO apiome.pact_setup_progress
        (tenant_id, marked, first_pact_path, ci_key_id, ci_key_prefix, github, updated_by, updated_by_label,
         updated_at)
    VALUES (%s::uuid, %s::text[], %s, %s::uuid, %s, %s::jsonb, %s::uuid, %s, CURRENT_TIMESTAMP)
    ON CONFLICT (tenant_id) DO UPDATE SET
        marked = EXCLUDED.marked, first_pact_path = EXCLUDED.first_pact_path,
        ci_key_id = EXCLUDED.ci_key_id, ci_key_prefix = EXCLUDED.ci_key_prefix, github = EXCLUDED.github,
        updated_by = EXCLUDED.updated_by, updated_by_label = EXCLUDED.updated_by_label,
        updated_at = CURRENT_TIMESTAMP
"""

_LOCK = f"SELECT {_PROGRESS_COLUMNS} FROM apiome.pact_setup_progress WHERE tenant_id = %s::uuid FOR UPDATE"


def _merge_tx(
    db: Any,
    cursor: Any,
    tenant_id: str,
    actor: ConsumerActor,
    change: Any,
    *,
    action: str,
    target: str,
    detail: Dict[str, Any],
) -> None:
    """Lock the tenant's row, apply ``change`` to its values, write it back and audit it."""
    cursor.execute(_LOCK, (tenant_id,))
    found = cursor.fetchone()
    row = dict(found) if found else {}
    values: Dict[str, Any] = {
        "marked": [section for section in SECTION_IDS if section in (row.get("marked") or [])],
        "first_pact_path": row.get("first_pact_path"),
        "ci_key_id": row.get("ci_key_id"),
        "ci_key_prefix": row.get("ci_key_prefix"),
        "github": _github_map(row.get("github")),
    }
    change(values)
    cursor.execute(
        _UPSERT,
        (
            tenant_id,
            values["marked"],
            values["first_pact_path"],
            values["ci_key_id"],
            values["ci_key_prefix"],
            json.dumps(values["github"], sort_keys=True),
            _user_id(actor),
            actor.label,
        ),
    )
    audit_tx(db, cursor, tenant_id, action, actor, target, detail)


def save_progress(db: Any, tenant_id: str, body: PactSetupSave, *, actor: ConsumerActor) -> None:
    """Merge a save into the workspace's progress, audited as ``pacts.setup.update``.

    Only what the body sends changes: a mark is set or cleared per section, the first-pact path and
    the CI key are replaced when given, and ``forget_ci_key`` clears the key.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        body: The change.
        actor: Who is saving it.

    Raises:
        ValueError: When the CI key's id is not a UUID, or a key is both given and forgotten.
    """
    if body.ci_key is not None and body.forget_ci_key:
        raise ValueError("send ci_key or forget_ci_key, not both")
    if body.ci_key is not None and not is_uuid_string(body.ci_key.id):
        raise ValueError("ci_key.id must be the key's id (a UUID)")

    def change(values: Dict[str, Any]) -> None:
        """Apply the body to the row's values."""
        if body.mark:
            marked = set(values["marked"])
            for section, on in body.mark.items():
                (marked.add if on else marked.discard)(section)
            values["marked"] = [section for section in SECTION_IDS if section in marked]
        if body.first_pact_path is not None:
            values["first_pact_path"] = body.first_pact_path
        if body.ci_key is not None:
            values["ci_key_id"], values["ci_key_prefix"] = body.ci_key.id, body.ci_key.prefix
        if body.forget_ci_key:
            values["ci_key_id"], values["ci_key_prefix"] = None, None

    detail = body.model_dump(exclude_none=True)
    db._guarded_tx(
        lambda cursor: _merge_tx(
            db, cursor, tenant_id, actor, change, action="pacts.setup.update", target="pact-setup", detail=detail
        )
    )


def record_github(
    db: Any,
    tenant_id: str,
    *,
    actor: ConsumerActor,
    action: str,
    updates: Mapping[str, Mapping[str, Any]],
    detail: Dict[str, Any],
) -> None:
    """Note what a GitHub action did to each repository, and audit the action.

    The audit row is written even when ``updates`` is empty (every repository was skipped), so an
    attempt leaves a trace.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        actor: Who ran the action.
        action: ``pacts.setup.github.secrets`` or ``pacts.setup.github.pull_requests``.
        updates: Per repository id, the keys to set (``secrets_at``, ``pull_request_url``,
            ``pull_request_number``). Never a token or a secret value.
        detail: The audit row's detail: the repositories and each outcome.
    """

    def change(values: Dict[str, Any]) -> None:
        """Merge the updates into the per-repository record."""
        for repository_id, keys in updates.items():
            values["github"].setdefault(str(repository_id), {}).update(dict(keys))

    db._guarded_tx(
        lambda cursor: _merge_tx(
            db, cursor, tenant_id, actor, change, action=action, target="pact-setup/github", detail=detail
        )
    )
