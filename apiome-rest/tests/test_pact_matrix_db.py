"""The matrix and can-i-deploy against a live Postgres — PFX-1.6 (#6919).

Golden verdicts for the Pact Broker's documented can-i-deploy scenarios, asked exactly as the
``pact-broker`` CLI asks them (``GET <base>/matrix?q[][pacticipant]=…&q[][version]=…&latestby=cvpv
&environment=…``). The CLI exits ``0`` when ``summary.deployable`` is true and ``1`` otherwise, and
``--retry-while-unknown`` keeps asking while ``summary.unknown`` is above zero — so each scenario
pins ``deployable``, the counts and the reason text:

* **pass** — every required result is published and successful;
* **fail** — the provider version in the environment failed the pact;
* **unknown** — no result yet from the provider version in the environment (``Retry-After``);
* **pending** — a failed result of a pending pact still says no, and the row says why;
* **ignored pacticipant** — the failing row is set aside and counted as ignored;
* **environment with no deployments** — a consumer cannot go first, a provider can;

plus a version that does not exist, a destination tag, two selectors, an environment that requires
a contract, the ``/can-i-deploy`` form, and tenant isolation.

Runs inside one always-rolled-back transaction (the ``stack`` fixture of
``test_pact_publication_db``). Skipped when no database is reachable or V435 is not applied.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator
from unittest.mock import patch
from urllib.parse import quote, urlencode

import pytest

from app.pact_publication import prepare_pact
from app.pact_publication_store import publish_pacts
from tests import test_pact_environment_db as environment_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

BASE = publication_db.BASE
PAIR = publication_db.PAIR

_NO_ENVIRONMENT = (
    "a version of Ledger API currently in production "
    "(no version is currently recorded as deployed/released in this environment)"
)


@pytest.fixture
def broker(stack: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The publication stack with the verification, environment and matrix routes on its transaction."""
    stack["cursor"].execute("SELECT to_regclass('apiome.deployed_version') AS t")
    if not stack["cursor"].fetchone()["t"]:
        pytest.skip("V435 not applied")
    modules = ("pact_broker_verification_routes", "pact_broker_environment_routes", "pact_broker_matrix_routes")
    patches = [patch(f"app.{module}.db", stack["db"]) for module in modules]
    patches += [patch(f"app.{module}.enforce_permission", return_value=None) for module in modules]
    for item in patches:
        item.start()
    try:
        yield stack
    finally:
        for item in patches:
            item.stop()


def _publish(stack: Dict[str, Any], version: str, total: int = 1999, **extra: Any) -> str:
    """Billing Service ``version`` publishes its pact for Ledger API; returns the pact's sha."""
    document = publication_db._pact(total=total)
    response = stack["client"].post(f"{BASE}/contracts/publish", json=publication_db._bulk(version, document, **extra))
    assert response.status_code == 200, response.text
    return response.json()["_links"]["pb:contracts"][0]["pactVersionSha"]


def _provider_version(stack: Dict[str, Any], version: str, branch: str = "main") -> None:
    """Record a Ledger API version on a branch, as a verifier does before publishing."""
    response = stack["client"].put(f"{BASE}/pacticipants/ledger-api/branches/{branch}/versions/{version}", json={})
    assert response.status_code in (200, 201), response.text


def _verify(stack: Dict[str, Any], sha: str, version: str, success: bool, metadata: str = "") -> None:
    """Ledger API ``version`` publishes a verification result for the pact with ``sha``."""
    response = stack["client"].post(
        f"{PAIR}/pact-version/{sha}{metadata}/verification-results",
        json={"success": success, "providerApplicationVersion": version},
    )
    assert response.status_code == 201, response.text


def _deploy(stack: Dict[str, Any], pacticipant: str, version: str, environment: str = "production") -> None:
    response = environment_db._record(stack, "pb:record-deployment", pacticipant, version, environment)
    assert response.status_code in (200, 201), response.text


def _get(stack: Dict[str, Any], path: str, pairs: Any) -> Any:
    """GET with the query parameters in exactly this order, as a Pact client sends them.

    (The test client groups repeated keys, which would tear ``q[][pacticipant]`` / ``q[][version]``
    pairs apart.)
    """
    return stack["client"].get(f"{BASE}/{path}?{urlencode(list(pairs))}")


def _cli(stack: Dict[str, Any], pacticipant: str, version: str, **options: Any) -> Any:
    """``pact-broker can-i-deploy --pacticipant … --version … --to-environment production``."""
    params = [("q[][pacticipant]", pacticipant), ("q[][version]", version), ("latestby", "cvpv")]
    params += list(options.pop("extra", []))
    params += [(key, value) for key, value in {"environment": "production", **options}.items() if value is not None]
    response = _get(stack, "matrix", params)
    assert response.status_code == 200, response.text
    return response


@pytest.fixture
def production(broker: Dict[str, Any]) -> Dict[str, Any]:
    """Billing Service 1.0.0 published its pact; Ledger API p-1 runs in production."""
    environment_db._create_environment(broker, "production", production=True)
    broker["sha"] = _publish(broker, "1.0.0", branch="main")
    _provider_version(broker, "p-1")
    _deploy(broker, "Ledger API", "p-1")
    return broker


def test_pass_every_required_result_is_published_and_successful(production: Dict[str, Any]) -> None:
    _verify(production, production["sha"], "p-1", True)
    response = _cli(production, "Billing Service", "1.0.0")
    body = response.json()
    assert body["summary"] == {
        "deployable": True,
        "reason": "All required verification results are published and successful",
        "success": 1,
        "failed": 0,
        "unknown": 0,
    }
    assert body["notices"] == [
        {
            "type": "success",
            "code": "verified",
            "text": "All required verification results are published and successful",
        }
    ]
    assert "retry-after" not in response.headers
    assert response.headers["content-type"].startswith("application/hal+json")
    (row,) = body["matrix"]
    assert (row["consumer"]["name"], row["consumer"]["version"]["number"]) == ("Billing Service", "1.0.0")
    assert (row["provider"]["name"], row["provider"]["version"]["number"]) == ("Ledger API", "p-1")
    assert row["consumer"]["version"]["branch"] == "main"
    assert [branch["name"] for branch in row["consumer"]["version"]["branchVersions"]] == ["main"]
    assert [e["name"] for e in row["provider"]["version"]["environments"]] == ["production"]
    assert row["consumer"]["version"]["environments"] == []
    assert row["verificationResult"]["success"] is True
    assert row["verificationResult"]["_links"]["self"]["href"].endswith(
        f"/pact-version/{production['sha']}/verification-results/1"
    )
    assert row["pact"]["_links"]["self"]["href"].endswith(f"{PAIR}/version/1.0.0")
    assert row["reason"] == {"code": "verified", "text": "verified"}
    # Every link in a row leads somewhere.
    for href in (
        row["pact"]["_links"]["self"]["href"],
        row["verificationResult"]["_links"]["self"]["href"],
        row["consumer"]["version"]["_links"]["self"]["href"],
        row["provider"]["_links"]["self"]["href"],
    ):
        assert production["client"].get(environment_db._path(href)).status_code == 200, href


def test_fail_the_provider_in_the_environment_failed_the_pact(production: Dict[str, Any]) -> None:
    _verify(production, production["sha"], "p-1", False)
    body = _cli(production, "Billing Service", "1.0.0").json()
    reason = (
        "The verification for the pact between version 1.0.0 of Billing Service and "
        "the version of Ledger API currently in production (p-1) failed"
    )
    assert body["summary"] == {"deployable": False, "reason": reason, "success": 0, "failed": 1, "unknown": 0}
    assert body["notices"] == [{"type": "error", "code": "verification-failed", "text": reason}]
    assert body["matrix"][0]["reason"] == {"code": "verification-failed", "text": "verification failed"}
    # The latest result of that provider version decides: a later success turns it around.
    _verify(production, production["sha"], "p-1", True)
    assert _cli(production, "Billing Service", "1.0.0").json()["summary"]["deployable"] is True


def test_unknown_no_result_from_the_provider_version_in_the_environment(production: Dict[str, Any]) -> None:
    # Another provider version verified the pact; the one in production has not.
    _verify(production, production["sha"], "p-0", True)
    response = _cli(production, "Billing Service", "1.0.0")
    body = response.json()
    reason = (
        "There is no verified pact between version 1.0.0 of Billing Service and "
        "the version of Ledger API currently in production (p-1)"
    )
    assert body["summary"] == {"deployable": None, "reason": reason, "success": 0, "failed": 0, "unknown": 1}
    assert body["notices"] == [{"type": "error", "code": "no-verification-result", "text": reason}]
    assert response.headers["retry-after"] == "10"
    (row,) = body["matrix"]
    assert row["provider"]["version"] is None
    assert row["verificationResult"] is None
    assert row["reason"] == {"code": "no-verification-result", "text": "no verification result"}
    # --retry-while-unknown: once the result arrives the same query answers.
    _verify(production, production["sha"], "p-1", True)
    retried = _cli(production, "Billing Service", "1.0.0")
    assert retried.json()["summary"]["unknown"] == 0
    assert retried.json()["summary"]["deployable"] is True
    assert "retry-after" not in retried.headers


def test_pending_a_failed_pending_pact_still_says_no_and_the_row_says_why(production: Dict[str, Any]) -> None:
    listed = production["client"].post(
        f"{BASE}/pacts/provider/ledger-api/for-verification",
        json={"consumerVersionSelectors": [{"latest": True}], "includePendingStatus": True},
    )
    (pact,) = listed.json()["_embedded"]["pacts"]
    assert pact["verificationProperties"]["pending"] is True
    document = production["client"].get(environment_db._path(pact["_links"]["self"]["href"])).json()
    published = production["client"].post(
        environment_db._path(document["_links"]["pb:publish-verification-results"]["href"]),
        json={"success": False, "providerApplicationVersion": "p-1"},
    )
    assert published.status_code == 201, published.text
    body = _cli(production, "Billing Service", "1.0.0").json()
    assert body["summary"]["deployable"] is False
    assert body["summary"]["failed"] == 1
    assert body["notices"][0]["code"] == "pact-pending"
    assert body["notices"][0]["text"].endswith("currently in production (p-1) failed")
    assert body["matrix"][0]["reason"] == {"code": "pact-pending", "text": "pact is pending"}


def test_an_ignored_pacticipant_does_not_count(production: Dict[str, Any]) -> None:
    _verify(production, production["sha"], "p-1", False)
    ignore = [("ignore[][pacticipant]", "Ledger API")]
    body = _cli(production, "Billing Service", "1.0.0", extra=ignore).json()
    assert body["summary"] == {
        "deployable": True,
        "reason": "There are no missing dependencies",
        "success": 0,
        "failed": 0,
        "unknown": 0,
        "ignored": 1,
    }
    assert [row.get("ignored") for row in body["matrix"]] == [True]
    # Ignoring another version of the provider ignores nothing; an unknown name is a warning.
    other = [("ignore[][pacticipant]", "Ledger API"), ("ignore[][version]", "p-0"), ("ignore[][pacticipant]", "Nope")]
    body = _cli(production, "Billing Service", "1.0.0", extra=other).json()
    assert (body["summary"]["deployable"], body["summary"]["ignored"]) == (False, 0)
    assert [notice["text"] for notice in body["notices"] if notice["type"] == "warning"] == [
        "WARN: Cannot ignore version p-0 of Ledger API (no such version exists)",
        "WARN: Cannot ignore any version of Nope (no such pacticipant exists)",
    ]


def test_environment_with_no_deployments(broker: Dict[str, Any]) -> None:
    environment_db._create_environment(broker, "production", production=True)
    sha = _publish(broker, "1.0.0", branch="main")
    _verify(broker, sha, "p-1", True)
    # The consumer needs its provider to be there first.
    consumer = _cli(broker, "Billing Service", "1.0.0").json()
    reason = f"There is no verified pact between version 1.0.0 of Billing Service and {_NO_ENVIRONMENT}"
    assert consumer["summary"] == {"deployable": None, "reason": reason, "success": 0, "failed": 0, "unknown": 1}
    # The provider does not need its consumers: it can go first.
    provider = _cli(broker, "Ledger API", "p-1").json()
    assert provider["summary"] == {
        "deployable": True,
        "reason": "There are no missing dependencies",
        "success": 0,
        "failed": 0,
        "unknown": 0,
    }
    assert provider["matrix"] == []
    # With the provider deployed, the consumer may follow.
    _deploy(broker, "Ledger API", "p-1")
    assert _cli(broker, "Billing Service", "1.0.0").json()["summary"]["deployable"] is True


def test_every_version_live_in_the_environment_is_checked(production: Dict[str, Any]) -> None:
    # p-1 runs on eu-1 and verified the pact; p-2 runs on us-1 and has not.
    _verify(production, production["sha"], "p-1", True)
    _provider_version(production, "p-2")
    deployed = environment_db._record(production, "pb:record-deployment", "Ledger API", "p-2", "production", "us-1")
    assert deployed.status_code == 201, deployed.text
    body = _cli(production, "Billing Service", "1.0.0").json()
    assert body["summary"] == {
        "deployable": None,
        "reason": (
            "There is no verified pact between version 1.0.0 of Billing Service and "
            "one of the versions of Ledger API currently in production (p-2)"
        ),
        "success": 1,
        "failed": 0,
        "unknown": 1,
    }
    rows = {row["provider"]["version"]["number"]: row["verificationResult"] for row in body["matrix"]}
    assert rows["p-2"] is None and rows["p-1"]["success"] is True
    _verify(production, production["sha"], "p-2", True)
    assert _cli(production, "Billing Service", "1.0.0").json()["summary"]["deployable"] is True


def test_deploying_a_provider_checks_the_consumers_in_the_environment(production: Dict[str, Any]) -> None:
    _verify(production, production["sha"], "p-1", True)
    _deploy(production, "Billing Service", "1.0.0")
    # 2.0.0 of the consumer asks for something p-2 does not do, but 2.0.0 is not in production.
    changed = _publish(production, "2.0.0", total=5, branch="main")
    _verify(production, changed, "p-2", False)
    _verify(production, production["sha"], "p-2", True)
    body = _cli(production, "Ledger API", "p-2").json()
    assert body["summary"]["deployable"] is True
    assert [(r["consumer"]["version"]["number"], r["provider"]["version"]["number"]) for r in body["matrix"]] == [
        ("1.0.0", "p-2")
    ]
    # Once 2.0.0 is what runs there, p-2 cannot follow.
    _deploy(production, "Billing Service", "2.0.0")
    body = _cli(production, "Ledger API", "p-2").json()
    assert body["summary"]["deployable"] is False
    assert body["summary"]["reason"] == (
        "The verification for the pact between the version of Billing Service currently in production (2.0.0) "
        "and version p-2 of Ledger API failed"
    )


def test_a_version_that_does_not_exist_cannot_be_deployed(production: Dict[str, Any]) -> None:
    body = _cli(production, "Billing Service", "9.9.9").json()
    reason = "No pacts or verifications have been published for version 9.9.9 of Billing Service"
    assert body["summary"] == {"deployable": False, "reason": reason, "success": 0, "failed": 0, "unknown": 0}
    assert body["notices"] == [{"type": "error", "code": "version-not-found", "text": reason}]


def test_unknown_names_are_refused(production: Dict[str, Any]) -> None:
    missing = _get(production, "matrix", [("q[][pacticipant]", "Nope"), ("q[][version]", "1")])
    assert missing.status_code == 400
    assert missing.json()["detail"] == {
        "code": "pact-matrix-invalid",
        "message": "Pacticipant Nope not found",
        "pointer": "/q/0/pacticipant",
    }
    environment = _get(
        production,
        "matrix",
        [("q[][pacticipant]", "Billing Service"), ("q[][version]", "1.0.0"), ("environment", "qa")],
    )
    assert environment.status_code == 400
    assert environment.json()["detail"]["message"] == "Environment with name 'qa' does not exist"


def test_to_a_tag_checks_the_latest_version_with_that_tag(broker: Dict[str, Any]) -> None:
    sha = _publish(broker, "1.0.0", branch="main")
    for version, success in (("p-1", True), ("p-2", False)):
        _verify(broker, sha, version, success)
        tagged = broker["client"].put(f"{BASE}/pacticipants/ledger-api/versions/{version}/tags/prod", json={})
        assert tagged.status_code in (200, 201), tagged.text
    # pact-broker can-i-deploy --pacticipant "Billing Service" --version 1.0.0 --to prod
    response = _get(
        broker,
        "matrix",
        [
            ("q[][pacticipant]", "Billing Service"),
            ("q[][version]", "1.0.0"),
            ("latestby", "cvp"),
            ("latest", "true"),
            ("tag", "prod"),
        ],
    )
    body = response.json()
    assert body["summary"]["deployable"] is False
    assert body["summary"]["reason"] == (
        "The verification for the pact between version 1.0.0 of Billing Service and "
        "the latest version of Ledger API with tag prod (p-2) failed"
    )
    (row,) = body["matrix"]
    assert row["provider"]["version"]["tags"][0]["name"] == "prod"
    assert row["provider"]["version"]["tags"][0]["latest"] is True


def test_two_selectors_ask_whether_two_versions_work_together(production: Dict[str, Any]) -> None:
    _verify(production, production["sha"], "p-1", True)
    _publish(production, "1.0.1", branch="main")  # the same pact content, a new consumer version

    def ask(*pairs: Any) -> Dict[str, Any]:
        response = _get(production, "matrix", list(pairs) + [("latestby", "cvpv")])
        assert response.status_code == 200, response.text
        return response.json()

    body = ask(
        ("q[][pacticipant]", "Billing Service"),
        ("q[][version]", "1.0.1"),
        ("q[][pacticipant]", "Ledger API"),
        ("q[][version]", "p-1"),
    )
    # 1.0.1 published the pact p-1 already verified: content is shared, so is the result.
    assert body["summary"]["deployable"] is True
    assert body["summary"]["success"] == 1
    # Name-only selectors list the pair's history, newest consumer version first.
    history = ask(("q[][pacticipant]", "Billing Service"), ("q[][pacticipant]", "Ledger API"))
    assert [row["consumer"]["version"]["number"] for row in history["matrix"]] == ["1.0.1", "1.0.0"]
    assert history["notices"][0]["type"] == "success"
    # One selector, no destination: everything about that version, and a warning.
    alone = ask(("q[][pacticipant]", "Ledger API"), ("q[][version]", "p-1"))
    assert len(alone["matrix"]) == 2
    assert alone["notices"][0]["code"] == "no-environment-specified"
    limited = _get(production, "matrix", [("q[][pacticipant]", "Ledger API"), ("q[][version]", "p-1"), ("limit", "1")])
    assert len(limited.json()["matrix"]) == 1


def test_an_environment_that_requires_a_contract_refuses_a_version_without_one(broker: Dict[str, Any]) -> None:
    client = broker["client"]
    created = client.post(f"{BASE}/environments", json={"name": "production", "contractRequired": True})
    assert created.status_code == 201, created.text
    registered = client.put(f"{BASE}/pacticipants/Search%20API/branches/main/versions/s-1", json={})
    assert registered.status_code in (200, 201), registered.text
    body = _cli(broker, "Search API", "s-1").json()
    reason = "No pact has been published for version s-1 of Search API, and environment production requires a contract"
    assert body["summary"] == {"deployable": False, "reason": reason, "success": 0, "failed": 0, "unknown": 0}
    assert body["notices"] == [{"type": "error", "code": "no-pact", "text": reason}]
    # A provider that a pact names has a contract, even before any consumer is deployed.
    sha = _publish(broker, "1.0.0", branch="main")
    _verify(broker, sha, "p-1", True)
    assert _cli(broker, "Ledger API", "p-1").json()["summary"]["deployable"] is True
    # Without the flag the same version passes: nothing depends on it.
    client.post(f"{BASE}/environments", json={"name": "staging"})
    assert _cli(broker, "Search API", "s-1", environment="staging").json()["summary"]["deployable"] is True


def test_can_i_deploy_answers_like_the_matrix(production: Dict[str, Any]) -> None:
    _verify(production, production["sha"], "p-1", False)
    client = production["client"]
    index = client.get(BASE).json()["_links"]
    template = index["pb:can-i-deploy-pacticipant-version-to-environment"]["href"]
    href = (
        template.replace("{pacticipant}", quote("Billing Service"))
        .replace("{version}", "1.0.0")
        .replace("{environment}", "production")
    )
    linked = client.get(environment_db._path(href))
    assert linked.status_code == 200, linked.text
    named = client.get(
        f"{BASE}/can-i-deploy",
        params={"pacticipant": "billing-service", "version": "1.0.0", "toEnvironment": "production"},
    )
    assert named.json() == linked.json() == _cli(production, "Billing Service", "1.0.0").json()
    assert named.json()["summary"]["deployable"] is False
    ignored = client.get(
        f"{BASE}/can-i-deploy",
        params={
            "pacticipant": "Billing Service",
            "version": "1.0.0",
            "toEnvironment": "production",
            "ignore": "Ledger API",
        },
    )
    assert (ignored.json()["summary"]["deployable"], ignored.json()["summary"]["ignored"]) == (True, 1)
    assert "{tag}" in index["pb:can-i-deploy-pacticipant-version-to-tag"]["href"]


def test_nothing_of_another_tenant_is_read(production: Dict[str, Any]) -> None:
    document = publication_db._pact()
    document["consumer"]["name"] = "Foreign App"
    pact = prepare_pact(
        json.dumps(document).encode(), consumer_name="Foreign App", provider_name="Ledger API", max_bytes=10_000
    )
    publish_pacts(
        production["db"],
        production["other"]["tenant"],
        consumer_name="Foreign App",
        version_number="1.0.0",
        pacts=[pact],
        actor=publication_db.ACTOR,
    )
    foreign = _get(production, "matrix", [("q[][pacticipant]", "Foreign App")])
    assert foreign.status_code == 400
    # The other tenant's consumer of its own "Ledger API" is no integration of ours.
    _verify(production, production["sha"], "p-1", True)
    body = _cli(production, "Ledger API", "p-1").json()
    assert body["summary"]["deployable"] is True
    names = {row["consumer"]["name"] for row in body["matrix"]}
    assert "Foreign App" not in names
