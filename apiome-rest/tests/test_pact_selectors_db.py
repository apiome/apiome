"""Consumer-version selectors and latest queries against a live Postgres — PFX-1.3 (#6916).

What only the real schema proves: the candidate read (:func:`list_pact_candidates`) returns each
publication with its version's branches and tags, so selectors over real publishes pick the right
pacts; the tag and branch latest reads filter in SQL (a branch with ``/`` included); and nothing of
another tenant is ever a candidate.

Runs inside one always-rolled-back transaction (the ``stack`` fixture of
``test_pact_publication_db``). Skipped when no database is reachable or V433 is not applied.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.pact_publication_store import list_pact_candidates
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

BASE = publication_db.BASE
PROVIDER = f"{BASE}/pacts/provider/ledger-api"
PAIR = publication_db.PAIR


def _publish(stack: Dict[str, Any], version: str, total: int, **extra: Any) -> None:
    """Publish Billing Service's pact (whose content varies with ``total``) for ``version``."""
    response = stack["client"].post(
        f"{BASE}/contracts/publish", json=publication_db._bulk(version, publication_db._pact(total), **extra)
    )
    assert response.status_code == 200, response.text


def _pacts(stack: Dict[str, Any], body: Dict[str, Any]) -> List[Dict[str, Any]]:
    response = stack["client"].post(f"{PROVIDER}/for-verification", json=body)
    assert response.status_code == 200, response.text
    return response.json()["_embedded"]["pacts"]


def _names(pacts: List[Dict[str, Any]]) -> List[str]:
    return [pact["_links"]["self"]["name"] for pact in pacts]


@pytest.fixture
def published(stack: Dict[str, Any]) -> Dict[str, Any]:
    """Four Billing Service versions: two on main (one tagged prod), one on a feature branch."""
    _publish(stack, "1.0.0", 1, branch="main", tags=["prod"])
    _publish(stack, "1.1.0", 2, branch="main")
    _publish(stack, "1.2.0", 3, branch="feat/new-invoice")
    _publish(stack, "1.3.0", 3, branch="feat/new-invoice")  # same content as 1.2.0
    patched = stack["client"].patch("/v1/tenants/t/pacticipants/billing-service", json={"main_branch": "main"})
    assert patched.status_code == 200, patched.text
    return stack


def test_candidates_carry_branches_and_tags(published: Dict[str, Any]) -> None:
    provider, candidates = list_pact_candidates(published["db"], published["seed"]["tenant"], "ledger-api")
    assert provider.slug == "ledger-api"
    assert [(c.version_number, c.branches, c.tags) for c in candidates] == [
        ("1.0.0", ("main",), ("prod",)),
        ("1.1.0", ("main",), ()),
        ("1.2.0", ("feat/new-invoice",), ()),
        ("1.3.0", ("feat/new-invoice",), ()),
    ]
    assert candidates[0].consumer_main_branch == "main"
    assert candidates[2].sha == candidates[3].sha


def test_selectors_choose_from_real_publications(published: Dict[str, Any]) -> None:
    assert _names(_pacts(published, {"consumerVersionSelectors": [{"mainBranch": True}]})) == [
        "Pact between Billing Service (1.1.0) and Ledger API"
    ]
    assert _names(_pacts(published, {"consumerVersionSelectors": [{"tag": "prod", "latest": True}]})) == [
        "Pact between Billing Service (1.0.0) and Ledger API"
    ]
    # 1.2.0 and 1.3.0 published the same pact: one entry, named after the later version.
    on_branch = _pacts(published, {"consumerVersionSelectors": [{"branch": "feat/new-invoice"}]})
    assert _names(on_branch) == ["Pact between Billing Service (1.3.0) and Ledger API"]
    assert _names(
        _pacts(
            published,
            {"consumerVersionSelectors": [{"matchingBranch": True}], "providerVersionBranch": "feat/new-invoice"},
        )
    ) == ["Pact between Billing Service (1.3.0) and Ledger API"]
    fallback = _pacts(published, {"consumerVersionSelectors": [{"branch": "feat/missing", "fallbackBranch": "main"}]})
    assert _names(fallback) == ["Pact between Billing Service (1.1.0) and Ledger API"]
    assert _pacts(published, {"consumerVersionSelectors": [{"deployedOrReleased": True}]}) == []


def test_a_selected_pact_link_reads_the_pact(published: Dict[str, Any]) -> None:
    pact = _pacts(published, {"consumerVersionSelectors": [{"mainBranch": True}]})[0]
    href = pact["_links"]["self"]["href"]
    path = href[href.index("/v1/") :]
    read = published["client"].get(path)
    assert read.status_code == 200, read.text
    assert read.json()["interactions"][0]["response"]["body"]["total"] == 2


def test_latest_by_tag_and_by_branch(published: Dict[str, Any]) -> None:
    client = published["client"]
    assert client.get(f"{PAIR}/latest/prod").json()["_links"]["self"]["href"].endswith("/version/1.0.0")
    assert client.get(f"{PAIR}/branch/main/latest").json()["_links"]["self"]["href"].endswith("/version/1.1.0")
    branch = client.get(f"{PAIR}/branch/feat%2Fnew-invoice/latest")
    assert branch.status_code == 200, branch.text
    assert branch.json()["_links"]["self"]["href"].endswith("/version/1.3.0")
    missing = client.get(f"{PAIR}/latest/nope")
    assert missing.status_code == 404
    assert "with tag 'nope'" in missing.json()["detail"]["message"]
    assert client.get(f"{PAIR}/branch/nope/latest").status_code == 404


def test_latest_pacts_of_the_provider(published: Dict[str, Any]) -> None:
    links = published["client"].get(f"{PROVIDER}/latest").json()["_links"]["pb:pacts"]
    assert [link["href"].rsplit("/", 1)[1] for link in links] == ["1.3.0"]
    tagged = published["client"].get(f"{PROVIDER}/latest/prod").json()["_links"]["pb:pacts"]
    assert [link["href"].rsplit("/", 1)[1] for link in tagged] == ["1.0.0"]


def test_another_tenants_publications_are_never_candidates(published: Dict[str, Any]) -> None:
    from app.pacticipant import PacticipantValidationError

    with pytest.raises(PacticipantValidationError):
        list_pact_candidates(published["db"], published["other"]["tenant"], "ledger-api")
