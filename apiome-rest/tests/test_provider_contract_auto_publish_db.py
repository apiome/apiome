"""Standing contract sources and automatic publishes against a live Postgres — PFX-8.7 (#7304).

What only the real schema proves:

* the ``provider_contract_source`` row is written, replaced and removed by the real SQL, and a
  repository of another workspace is refused;
* **the verdict an automatic publish records is the one the pre-publish check previewed** — for
  a push (the commit is the provider version) and for a project publish;
* publishing again is idempotent (nothing new recorded), a draft is never published, and each
  attempt leaves an ``access_audit`` row;
* another workspace's push or project publish publishes nothing for this provider.

Runs inside one always-rolled-back transaction (the ``bdct`` fixture of ``test_bidirectional_db``).
Skipped when no database is reachable or V453 is not applied.
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest

from app import provider_contract_auto_publish as auto
from app.pacticipant import PacticipantValidationError
from app.pacticipant_contract_sources import (
    CODE_REPOSITORY_NOT_FOUND,
    ContractSourcesInput,
    get_contract_sources,
    put_contract_sources,
)
from app.pacticipant_store import get_pacticipant
from app.provider_contract import prepare_contract
from tests import test_bidirectional_db as bidirectional_db
from tests import test_pact_matrix_db as matrix_db
from tests import test_pact_publication_db as publication_db
from tests import test_provider_contract_check_db as check_db

tx = publication_db.tx
stack = publication_db.stack
broker = matrix_db.broker
bdct = bidirectional_db.bdct
checking = check_db.checking

pytestmark = pytest.mark.requires_db

_SHA = "9f31c20aa1b2c3d4e5f60718293a4b5c6d7e8f90"


@pytest.fixture
def sources(checking: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The check stack, with a GitHub repository registered in the first workspace."""
    cursor = checking["cursor"]
    cursor.execute("SELECT to_regclass('apiome.provider_contract_source') AS t")
    if not cursor.fetchone()["t"]:
        pytest.skip("V453 not applied")
    suffix = uuid.uuid4().hex[:10]
    cursor.execute(
        """INSERT INTO apiome.tenant_repositories
               (tenant_id, source, provider, clone_url, clone_url_normalized, repository_full_name, visibility)
           VALUES (%s, 'public_url', 'github', %s, %s, %s, 'public') RETURNING id::text AS id""",
        (
            checking["seed"]["tenant"],
            f"https://github.com/acme/ledger-{suffix}.git",
            f"github.com/acme/ledger-{suffix}",
            f"acme/ledger-{suffix}",
        ),
    )
    checking["repository"] = cursor.fetchone()["id"]
    yield checking


def _provider(stack: Dict[str, Any]) -> Any:
    return get_pacticipant(stack["db"], stack["seed"]["tenant"], "Ledger API")


def _follow_file(stack: Dict[str, Any]) -> None:
    body = ContractSourcesInput.model_validate(
        {"repository": {"repositoryId": stack["repository"], "path": "openapi/ledger.json", "branch": "main"}}
    )
    put_contract_sources(stack["db"], stack["seed"]["tenant"], _provider(stack), body, user_id=None)


def _reader() -> MagicMock:
    return MagicMock(return_value=(json.dumps(bidirectional_db._oas()), False))


def _audits(stack: Dict[str, Any]) -> list:
    stack["cursor"].execute(
        "SELECT detail FROM apiome.access_audit WHERE tenant_id = %s::uuid AND action = %s",
        (stack["seed"]["tenant"], auto.AUDIT_ACTION),
    )
    return [row["detail"] for row in stack["cursor"].fetchall()]


def test_the_setting_is_written_replaced_and_removed(sources: Dict[str, Any]) -> None:
    bidirectional_db._publish(sources, "1.0.0")
    _follow_file(sources)
    record = get_contract_sources(sources["db"], sources["seed"]["tenant"], _provider(sources))
    assert record.repository is not None
    assert (record.repository.repository_id, record.repository.path) == (sources["repository"], "openapi/ledger.json")
    assert record.repository.webhook is False and record.warnings

    put_contract_sources(
        sources["db"], sources["seed"]["tenant"], _provider(sources), ContractSourcesInput(), user_id=None
    )
    sources["cursor"].execute(
        "SELECT count(*) AS n FROM apiome.provider_contract_source WHERE tenant_id = %s::uuid",
        (sources["seed"]["tenant"],),
    )
    assert sources["cursor"].fetchone()["n"] == 0


def test_a_repository_of_another_workspace_is_refused(sources: Dict[str, Any]) -> None:
    bidirectional_db._publish(sources, "1.0.0")
    other = sources["other"]["tenant"]
    sources["cursor"].execute(
        "INSERT INTO apiome.pacticipant (tenant_id, slug, name) VALUES (%s, 'ledger-api', 'Ledger API')", (other,)
    )
    body = ContractSourcesInput.model_validate(
        {"repository": {"repositoryId": sources["repository"], "path": "openapi.json", "branch": "main"}}
    )
    with pytest.raises(PacticipantValidationError) as caught:
        put_contract_sources(
            sources["db"], other, get_pacticipant(sources["db"], other, "ledger-api"), body, user_id=None
        )
    assert caught.value.code == CODE_REPOSITORY_NOT_FOUND


@pytest.mark.parametrize("total, success", [(1999, True), ("not a number", False)])
def test_a_push_records_the_verdict_the_check_previewed(sources: Dict[str, Any], total: Any, success: bool) -> None:
    sha = bidirectional_db._sha(bidirectional_db._publish(sources, "1.0.0", total=total))
    _follow_file(sources)
    # The preview of exactly what the push will publish: the same document, no evidence, on main.
    preview = sources["client"].post(
        f"{check_db.BASE}/contracts/provider/Ledger API/version/{_SHA}/check",
        json={
            "content": base64.b64encode(json.dumps(bidirectional_db._oas()).encode()).decode(),
            "contentType": "application/json",
            "branch": "main",
        },
    )
    assert preview.status_code == 200, preview.text
    [previewed] = preview.json()["results"]

    [outcome] = auto.publish_on_push(
        sources["db"], sources["seed"]["tenant"], sources["repository"], "main", _SHA, read=_reader()
    )
    assert outcome.outcome == "published", outcome
    [stored] = [row for row in bidirectional_db._rows(sources) if row["provider_version"] == _SHA]
    assert (stored["success"], stored["verdict"], stored["sha"]) == (previewed["success"], previewed["verdict"], sha)
    assert stored["success"] is success
    assert stored["provider_branch"] == "main"

    # Idempotent: the same push again records nothing new.
    before = len(bidirectional_db._rows(sources))
    [again] = auto.publish_on_push(
        sources["db"], sources["seed"]["tenant"], sources["repository"], "main", _SHA, read=_reader()
    )
    assert again.outcome == "unchanged"
    assert len(bidirectional_db._rows(sources)) == before
    # One transaction stamps every row with one time, so the rows are compared as a set.
    assert sorted(detail["outcome"] for detail in _audits(sources)) == ["published", "unchanged"]


def test_a_push_to_another_branch_or_workspace_publishes_nothing(sources: Dict[str, Any]) -> None:
    bidirectional_db._publish(sources, "1.0.0")
    _follow_file(sources)
    read = _reader()
    assert (
        auto.publish_on_push(sources["db"], sources["seed"]["tenant"], sources["repository"], "dev", _SHA, read=read)
        == []
    )
    assert (
        auto.publish_on_push(sources["db"], sources["other"]["tenant"], sources["repository"], "main", _SHA, read=read)
        == []
    )
    read.assert_not_called()


def _version(stack: Dict[str, Any], label: str, published: bool) -> str:
    stack["cursor"].execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = stack["cursor"].fetchone()["id"]
    stack["cursor"].execute(
        """INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at)
           VALUES (%s, %s, %s, %s, CASE WHEN %s THEN now() END) RETURNING id::text AS id""",
        (stack["seed"]["project"], user, label, published, published),
    )
    return stack["cursor"].fetchone()["id"]


def test_a_project_publish_records_the_contract_and_never_a_draft(sources: Dict[str, Any]) -> None:
    bidirectional_db._publish(sources, "1.0.0")
    tenant = sources["seed"]["tenant"]
    sources["cursor"].execute(
        "UPDATE apiome.pacticipant SET project_id = %s::uuid, main_branch = 'main' WHERE tenant_id = %s::uuid "
        "AND slug = 'ledger-api'",
        (sources["seed"]["project"], tenant),
    )
    put_contract_sources(
        sources["db"], tenant, _provider(sources), ContractSourcesInput(on_project_publish=True), user_id=None
    )
    rendered = prepare_contract(bidirectional_db._oas(), content_type="application/json")
    draft = _version(sources, "2.0.0-draft", published=False)
    released = _version(sources, "2.0.0", published=True)
    with patch.object(auto, "render_apiome_contract", return_value=rendered):
        [skipped] = auto.publish_on_project_version(sources["db"], tenant, sources["seed"]["project"], draft)
        [published] = auto.publish_on_project_version(sources["db"], tenant, sources["seed"]["project"], released)
        nothing = auto.publish_on_project_version(
            sources["db"], sources["other"]["tenant"], sources["seed"]["project"], released
        )
    assert skipped.outcome == "skipped"
    assert published.outcome == "published", published
    assert nothing == []
    versions = {row["provider_version"] for row in bidirectional_db._rows(sources)}
    assert "2.0.0" in versions and "2.0.0-draft" not in versions
    assert sorted(detail["outcome"] for detail in _audits(sources)) == ["published", "skipped"]
