"""Pending and work-in-progress pacts against a live Postgres — PFX-1.7 (#6920).

What only the real schema proves: the history read (:func:`load_pending_evidence`) sees the
results a verifier really publishes, so a pact's ``pending`` flag flips after its first success
on the verifying branch (and only for builds that should inherit it); a feature-branch pact
comes back as a WIP pact until the provider branch has verified it; and no result of another
tenant is ever evidence.

Runs inside one always-rolled-back transaction (the ``broker`` fixture of
``test_verification_result_db``). Skipped when no database is reachable or V434 is not applied.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

import pytest

from app.pact_pending_store import load_pending_evidence
from app.pacticipant_store import get_pacticipant
from tests import test_pact_publication_db as publication_db
from tests import test_verification_result_db as verification_db

tx = publication_db.tx
stack = publication_db.stack
broker = verification_db.broker

pytestmark = pytest.mark.requires_db

BASE = publication_db.BASE
PROVIDER = f"{BASE}/pacts/provider/ledger-api"
_path = verification_db._path


def _publish(stack: Dict[str, Any], version: str, total: int, branch: str) -> None:
    """Publish Billing Service's pact (content varies with ``total``) from ``branch``."""
    response = stack["client"].post(
        f"{BASE}/contracts/publish", json=publication_db._bulk(version, publication_db._pact(total), branch=branch)
    )
    assert response.status_code == 200, response.text


def _for_verification(stack: Dict[str, Any], branch: Optional[str], **extra: Any) -> List[Dict[str, Any]]:
    """The pacts a provider build on ``branch`` gets for ``mainBranch`` (and any extras)."""
    body: Dict[str, Any] = {"consumerVersionSelectors": [{"mainBranch": True}], "includePendingStatus": True}
    if branch is not None:
        body["providerVersionBranch"] = branch
    body.update(extra)
    response = stack["client"].post(f"{PROVIDER}/for-verification", json=body)
    assert response.status_code == 200, response.text
    return response.json()["_embedded"]["pacts"]


def _record_branch(stack: Dict[str, Any], branch: str, version: str) -> None:
    """Record a provider version on a branch (what a verifier does before it publishes)."""
    response = stack["client"].put(f"{BASE}/pacticipants/ledger-api/branches/{branch}/versions/{version}", json={})
    assert response.status_code in (200, 201), response.text


def _verify(stack: Dict[str, Any], pact: Dict[str, Any], branch: str, version: str, success: bool = True) -> None:
    """Verify one for-verification pact: follow its link, record the branch, publish a result."""
    client = stack["client"]
    read = client.get(_path(pact["_links"]["self"]["href"]))
    assert read.status_code == 200, read.text
    _record_branch(stack, branch, version)
    body = {"success": success, "providerApplicationVersion": version, "testResults": []}
    published = client.post(_path(read.json()["_links"]["pb:publish-verification-results"]["href"]), json=body)
    assert published.status_code == 201, published.text


@pytest.fixture
def published(broker: Dict[str, Any]) -> Dict[str, Any]:
    """Billing Service 1.0.0 on main (its main branch) published its pact for Ledger API."""
    _publish(broker, "1.0.0", 1, "main")
    patched = broker["client"].patch("/v1/tenants/t/pacticipants/billing-service", json={"main_branch": "main"})
    assert patched.status_code == 200, patched.text
    return broker


def test_the_pending_flag_flips_after_the_first_success(published: Dict[str, Any]) -> None:
    # A provider branch that already existed before main verified the pact.
    _record_branch(published, "feat-old", "p-0")
    published["cursor"].execute(
        "UPDATE apiome.pacticipant_branch SET created_at = created_at - interval '1 hour' WHERE name = 'feat-old'"
    )
    (pact,) = _for_verification(published, "main")
    assert pact["verificationProperties"]["pending"] is True

    # A failure does not end the pending state.
    _verify(published, pact, "main", "p-1", success=False)
    assert _for_verification(published, "main")[0]["verificationProperties"]["pending"] is True

    _verify(published, pact, "main", "p-2")
    assert _for_verification(published, "main")[0]["verificationProperties"]["pending"] is False
    # A branch that did not exist yet inherits main's success; one that already existed does not.
    assert _for_verification(published, "feat-new")[0]["verificationProperties"]["pending"] is False
    assert _for_verification(published, "feat-old")[0]["verificationProperties"]["pending"] is True
    # Without a branch, any success counts.
    assert _for_verification(published, None)[0]["verificationProperties"]["pending"] is False

    # New content from the consumer starts pending again.
    _publish(published, "1.1.0", 2, "main")
    assert _for_verification(published, "main")[0]["verificationProperties"]["pending"] is True


def test_a_feature_branch_pact_is_wip_until_the_provider_branch_verifies_it(published: Dict[str, Any]) -> None:
    _publish(published, "2.0.0", 7, "feat/invoice")
    since = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    pacts = _for_verification(published, "main", includeWipPactsSince=since)
    assert [p["_links"]["self"]["name"] for p in pacts] == [
        "Pact between Billing Service (1.0.0) and Ledger API",
        "Pact between Billing Service (2.0.0) and Ledger API",
    ]
    wip = pacts[1]
    assert wip["verificationProperties"]["wip"] is True
    assert wip["verificationProperties"]["pending"] is True

    # Not WIP when published before the date.
    later = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    assert len(_for_verification(published, "main", includeWipPactsSince=later)) == 1

    # A result published through the WIP link is recorded as WIP and pending.
    _verify(published, wip, "main", "p-3")
    published["cursor"].execute(
        "SELECT pact_pending, wip, success FROM apiome.verification_result WHERE tenant_id = %s::uuid",
        (published["seed"]["tenant"],),
    )
    assert published["cursor"].fetchone() == {"pact_pending": True, "wip": True, "success": True}
    # Verified on main: no longer WIP for main.
    assert len(_for_verification(published, "main", includeWipPactsSince=since)) == 1


def test_another_tenants_results_are_never_evidence(published: Dict[str, Any]) -> None:
    (pact,) = _for_verification(published, "main")
    _verify(published, pact, "main", "p-1")
    provider = get_pacticipant(published["db"], published["seed"]["tenant"], "ledger-api")
    mine = load_pending_evidence(published["db"], published["seed"]["tenant"], provider.id, "main")
    assert len(mine.successes) == 1
    (successes,) = mine.successes.values()
    assert successes.branches == frozenset({"main"})
    assert mine.branch_created_at is not None
    theirs = load_pending_evidence(published["db"], published["other"]["tenant"], provider.id, "main")
    assert theirs.successes == {}
