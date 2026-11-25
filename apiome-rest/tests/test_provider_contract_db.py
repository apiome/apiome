"""Provider contract publication against a live Postgres — PFX-2.1 (#6925).

The acceptance criteria only the real schema and the real routes can prove (apiome-db V438):

* publishing inline (OpenAPI 3.0 YAML, 3.1 JSON) registers the provider, records the version with
  its branch and tags, and stores the contract;
* publishing by reference renders the Apiome version — by ``project@version``, by ``latest``, and
  through the provider's project binding;
* the hash dedupes: one document published for several provider versions (and as JSON and as
  YAML) is one ``provider_contract`` row;
* write-once: the same contract again is a no-op, a different one is a 409 that stores nothing;
* non-OpenAPI input is refused with its location, storing nothing;
* nothing crosses a tenant, a contract goes with its provider, and deleting the source version
  only clears the link.

Everything runs inside one always-rolled-back transaction (the ``tx`` fixture of
``test_usage_index_db``). Skipped when no database is reachable or V438 is not applied.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from app.consumer_contract_store import ConsumerActor
from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.provider_contract import ProviderContractError, prepare_contract
from app.provider_contract_store import get_provider_contract, publish_provider_contract
from tests import test_usage_index_db as index_db

tx = index_db.tx

pytestmark = pytest.mark.requires_db

ACTOR = ConsumerActor(user_id=None, label="ci@example.com", kind="api_key")
BASE = "/v1/tenants/t/pact-broker/contracts/provider"
FIXTURES = Path(__file__).parent / "fixtures" / "provider_contracts"


def _oas31() -> Dict[str, Any]:
    return json.loads((FIXTURES / "ledger-api-3.1.json").read_bytes())


def _inline(raw: bytes, **extra: Any) -> Dict[str, Any]:
    return {"content": base64.b64encode(raw).decode(), **extra}


@pytest.fixture
def stack(tx: Tuple[Any, Any]) -> Iterator[Dict[str, Any]]:
    """Two tenants (each with a project) and a client whose routes run on ``tx`` as the first."""
    db, cursor = tx
    cursor.execute("SELECT to_regclass('apiome.provider_contract_publication') AS t")
    if not cursor.fetchone()["t"]:
        pytest.skip("V438 not applied")
    seed = index_db._tenant(cursor)
    other = index_db._tenant(cursor)
    auth = {"tenant_id": seed["tenant"], "user_id": None, "auth_method": "jwt"}
    app.dependency_overrides[validate_broker_authentication] = lambda: auth
    with (
        patch("app.provider_contract_routes.db", db),
        patch("app.provider_contract_routes.enforce_permission", return_value=None),
    ):
        yield {"db": db, "cursor": cursor, "seed": seed, "other": other, "client": TestClient(app)}
    app.dependency_overrides.clear()


def _count(stack: Dict[str, Any], table: str) -> int:
    """Rows of ``table`` owned by the test's two tenants."""
    stack["cursor"].execute(
        f"SELECT count(*) AS n FROM apiome.{table} WHERE tenant_id = ANY(%s::uuid[])",
        ([stack["seed"]["tenant"], stack["other"]["tenant"]],),
    )
    return int(stack["cursor"].fetchone()["n"])


def _version(stack: Dict[str, Any], label: str, project: str = "") -> str:
    """A version of the seed project (or ``project``), returning its id."""
    cursor = stack["cursor"]
    cursor.execute(
        """INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at, created_at)
           SELECT p.id, p.creator_id, %s, true, now(), clock_timestamp() FROM apiome.projects p WHERE p.id = %s::uuid
           RETURNING id::text AS id""",
        (label, project or stack["seed"]["project"]),
    )
    return cursor.fetchone()["id"]


def _project_slug(stack: Dict[str, Any]) -> str:
    stack["cursor"].execute("SELECT slug FROM apiome.projects WHERE id = %s::uuid", (stack["seed"]["project"],))
    return stack["cursor"].fetchone()["slug"]


def _rendered(document: Dict[str, Any]) -> Any:
    """Patch the renderer to return ``document`` (the document store is not part of this test)."""
    return patch(
        "app.provider_contract_source.rendered_document", return_value=MagicMock(**{"json.return_value": document})
    )


# ---------------------------------------------------------------------------------------------
# Inline
# ---------------------------------------------------------------------------------------------


def test_an_openapi_30_yaml_contract_is_published_with_its_version(stack: Dict[str, Any]) -> None:
    raw = (FIXTURES / "ledger-api-3.0.yaml").read_bytes()
    response = stack["client"].put(
        f"{BASE}/Ledger API/version/1.4.0",
        json=_inline(
            raw, contentType="application/yaml", branch="main", tags=["rc"], buildUrl="https://ci.example.com/1"
        ),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["oasVersion"], body["operationCount"], body["contentType"]) == ("3.0.3", 2, "application/yaml")
    assert set(body["content"]["paths"]["/invoices/{id}"]["get"]["responses"]) == {"200", "404"}

    cursor = stack["cursor"]
    cursor.execute(
        """SELECT pr.slug, pr.main_branch, v.build_url,
                  (SELECT array_agg(t.name) FROM apiome.pacticipant_version_tag t WHERE t.version_id = v.id) AS tags
           FROM apiome.pacticipant pr JOIN apiome.pacticipant_version v ON v.pacticipant_id = pr.id
           WHERE pr.tenant_id = %s::uuid""",
        (stack["seed"]["tenant"],),
    )
    row = cursor.fetchone()
    assert (row["slug"], row["main_branch"], row["build_url"], row["tags"]) == (
        "ledger-api",
        "main",
        "https://ci.example.com/1",
        ["rc"],
    )


def test_an_openapi_31_json_contract_reads_back(stack: Dict[str, Any]) -> None:
    raw = (FIXTURES / "ledger-api-3.1.json").read_bytes()
    assert stack["client"].put(f"{BASE}/ledger-api/version/2.0.0", json=_inline(raw)).status_code == 201
    response = stack["client"].get(f"{BASE}/ledger-api/version/2.0.0")
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == _oas31()
    assert (body["oasVersion"], body["source"]) == ("3.1.0", {"kind": "inline"})


def test_the_hash_dedupes_across_versions_and_formats(stack: Dict[str, Any]) -> None:
    document = _oas31()
    client = stack["client"]
    as_json = client.put(f"{BASE}/ledger-api/version/1", json=_inline(json.dumps(document).encode()))
    as_yaml = client.put(
        f"{BASE}/ledger-api/version/2", json=_inline(yaml.safe_dump(document).encode(), contentType="application/yaml")
    )
    assert as_json.status_code == as_yaml.status_code == 201
    assert as_json.json()["contentSha"] == as_yaml.json()["contentSha"]
    assert _count(stack, "provider_contract") == 1
    assert _count(stack, "provider_contract_publication") == 2


def test_republishing_the_same_contract_is_a_no_op(stack: Dict[str, Any]) -> None:
    body = _inline(json.dumps(_oas31()).encode(), verificationResults={"success": True, "verifier": "dredd"})
    client = stack["client"]
    assert client.put(f"{BASE}/ledger-api/version/1", json=body).status_code == 201
    again = client.put(f"{BASE}/ledger-api/version/1", json=body)
    assert again.status_code == 200
    assert again.json()["verificationResults"]["verifier"] == "dredd"
    assert _count(stack, "provider_contract_publication") == 1


@pytest.mark.parametrize(
    "change",
    ["document", "results"],
)
def test_a_different_contract_for_a_published_version_is_409_and_stores_nothing(
    stack: Dict[str, Any], change: str
) -> None:
    client = stack["client"]
    first = _inline(json.dumps(_oas31()).encode(), verificationResults={"success": True})
    assert client.put(f"{BASE}/ledger-api/version/1", json=first).status_code == 201
    changed = _oas31()
    if change == "document":
        changed["info"]["version"] = "9.9.9"
    second = _inline(json.dumps(changed).encode(), verificationResults={"success": change == "document"})
    response = client.put(f"{BASE}/ledger-api/version/1", json=second)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "provider-contract-conflict"
    assert _count(stack, "provider_contract") == 1
    assert client.get(f"{BASE}/ledger-api/version/1").json()["content"]["info"]["version"] == "1.4.0"


def test_a_swagger_document_is_refused_with_its_location_and_nothing_is_stored(stack: Dict[str, Any]) -> None:
    raw = (FIXTURES / "swagger-2.0.json").read_bytes()
    response = stack["client"].put(f"{BASE}/ledger-api/version/1", json=_inline(raw))
    assert response.status_code == 422
    assert response.json()["detail"]["pointer"] == "/swagger"
    assert _count(stack, "pacticipant") == 0
    assert _count(stack, "provider_contract") == 0


def test_a_nul_character_is_refused_not_a_500(stack: Dict[str, Any]) -> None:
    document = _oas31()
    document["info"]["description"] = "nul \u0000 here"
    contract = prepare_contract(document, content_type="application/json")
    with pytest.raises(ProviderContractError) as caught:
        publish_provider_contract(
            stack["db"],
            stack["seed"]["tenant"],
            provider_name="ledger-api",
            version_number="1",
            contract=contract,
            actor=ACTOR,
        )
    assert caught.value.code == "provider-contract-invalid"
    assert _count(stack, "pacticipant") == 0


def test_a_version_without_a_contract_is_404(stack: Dict[str, Any]) -> None:
    client = stack["client"]
    assert client.get(f"{BASE}/ledger-api/version/1").status_code == 404
    client.put(f"{BASE}/ledger-api/version/1", json=_inline(json.dumps(_oas31()).encode()))
    missing = client.get(f"{BASE}/ledger-api/version/2")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "provider-contract-not-found"


# ---------------------------------------------------------------------------------------------
# By reference
# ---------------------------------------------------------------------------------------------


def test_publishing_by_project_at_version_renders_that_version(stack: Dict[str, Any]) -> None:
    version_id = _version(stack, "1.4.0")
    slug = _project_slug(stack)
    with _rendered(_oas31()) as render:
        response = stack["client"].put(f"{BASE}/ledger-api/version/9f2c1d0", json={"apiomeVersion": f"{slug}@1.4.0"})
    assert response.status_code == 201, response.text
    assert render.call_args.args[0] == version_id
    assert response.json()["source"] == {
        "kind": "apiome",
        "project": slug,
        "version": "1.4.0",
        "projectId": stack["seed"]["project"],
        "versionId": version_id,
    }


def test_a_bound_provider_resolves_latest_without_naming_the_project(stack: Dict[str, Any]) -> None:
    _version(stack, "1.0.0")
    newest = _version(stack, "1.1.0")
    cursor = stack["cursor"]
    cursor.execute(
        "INSERT INTO apiome.pacticipant (tenant_id, slug, name, project_id) "
        "VALUES (%s, 'ledger-api', 'Ledger API', %s)",
        (stack["seed"]["tenant"], stack["seed"]["project"]),
    )
    with _rendered(_oas31()) as render:
        response = stack["client"].put(f"{BASE}/ledger-api/version/abc123", json={"apiomeVersion": "latest"})
    assert response.status_code == 201, response.text
    assert render.call_args.args[0] == newest
    assert response.json()["source"]["version"] == "1.1.0"


def test_an_unbound_provider_must_name_the_project(stack: Dict[str, Any]) -> None:
    response = stack["client"].put(f"{BASE}/ledger-api/version/1", json={"apiomeVersion": "latest"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "provider-contract-source-not-found"
    assert _count(stack, "pacticipant") == 0


def test_another_tenants_project_is_not_found(stack: Dict[str, Any]) -> None:
    other_version = _version(stack, "1.0.0", project=stack["other"]["project"])
    response = stack["client"].put(
        f"{BASE}/ledger-api/version/1", json={"apiomeVersion": f"{stack['other']['project']}@{other_version}"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["pointer"] == "/apiomeVersion"


def test_an_unknown_version_is_not_found(stack: Dict[str, Any]) -> None:
    response = stack["client"].put(
        f"{BASE}/ledger-api/version/1", json={"apiomeVersion": f"{_project_slug(stack)}@7.7.7"}
    )
    assert response.status_code == 422
    assert "no version '7.7.7'" in response.json()["detail"]["message"]


def test_a_real_render_of_an_apiome_version_is_a_valid_contract(stack: Dict[str, Any]) -> None:
    """No patching: the exporter's OpenAPI 3.1 for a version is accepted as a provider contract."""
    _version(stack, "3.0.0")
    response = stack["client"].put(
        f"{BASE}/ledger-api/version/1", json={"apiomeVersion": f"{_project_slug(stack)}@3.0.0"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["oasVersion"].startswith("3.1")


def test_deleting_the_source_version_keeps_the_contract_and_its_labels(stack: Dict[str, Any]) -> None:
    version_id = _version(stack, "1.4.0")
    with _rendered(_oas31()):
        stack["client"].put(f"{BASE}/ledger-api/version/1", json={"apiomeVersion": f"{_project_slug(stack)}@1.4.0"})
    stack["cursor"].execute("DELETE FROM apiome.versions WHERE id = %s::uuid", (version_id,))
    source = stack["client"].get(f"{BASE}/ledger-api/version/1").json()["source"]
    assert (source["versionId"], source["version"], source["projectId"]) == (None, "1.4.0", stack["seed"]["project"])


# ---------------------------------------------------------------------------------------------
# Tenancy and lifecycle
# ---------------------------------------------------------------------------------------------


def test_another_tenant_cannot_read_the_contract(stack: Dict[str, Any]) -> None:
    contract = prepare_contract(_oas31(), content_type="application/json")
    publish_provider_contract(
        stack["db"],
        stack["other"]["tenant"],
        provider_name="ledger-api",
        version_number="1",
        contract=contract,
        actor=ACTOR,
    )
    response = stack["client"].get(f"{BASE}/ledger-api/version/1")
    assert response.status_code == 404
    assert get_provider_contract(stack["db"], stack["other"]["tenant"], "ledger-api", "1").sha == contract.sha


def test_a_contract_cannot_join_another_providers_version(stack: Dict[str, Any]) -> None:
    import psycopg2

    client = stack["client"]
    client.put(f"{BASE}/ledger-api/version/1", json=_inline(json.dumps(_oas31()).encode()))
    client.put(
        f"{BASE}/billing/version/1",
        json=_inline(json.dumps({**_oas31(), "info": {"title": "B", "version": "1"}}).encode()),
    )
    cursor = stack["cursor"]
    cursor.execute("SAVEPOINT cross_provider")
    with pytest.raises(psycopg2.Error):
        cursor.execute(
            """UPDATE apiome.provider_contract_publication p
               SET provider_contract_id = (SELECT c.id FROM apiome.provider_contract c
                                           JOIN apiome.pacticipant pr ON pr.id = c.provider_id WHERE pr.slug = 'billing'
                                             AND pr.tenant_id = p.tenant_id)
               WHERE p.tenant_id = %s::uuid
                 AND p.provider_id = (SELECT id FROM apiome.pacticipant
                                      WHERE slug = 'ledger-api' AND tenant_id = %s::uuid)""",
            (stack["seed"]["tenant"], stack["seed"]["tenant"]),
        )
    cursor.execute("ROLLBACK TO SAVEPOINT cross_provider")


def test_a_contract_goes_with_its_provider(stack: Dict[str, Any]) -> None:
    stack["client"].put(f"{BASE}/ledger-api/version/1", json=_inline(json.dumps(_oas31()).encode()))
    stack["cursor"].execute("DELETE FROM apiome.pacticipant WHERE tenant_id = %s::uuid", (stack["seed"]["tenant"],))
    assert _count(stack, "provider_contract") == 0
    assert _count(stack, "provider_contract_publication") == 0


def test_a_deleted_provider_version_has_no_contract_to_read(stack: Dict[str, Any]) -> None:
    stack["client"].put(f"{BASE}/ledger-api/version/1", json=_inline(json.dumps(_oas31()).encode()))
    stack["cursor"].execute(
        "UPDATE apiome.pacticipant_version SET deleted_at = now(), delete_cause = 'version' WHERE pacticipant_id IN "
        "(SELECT id FROM apiome.pacticipant WHERE tenant_id = %s::uuid)",
        (stack["seed"]["tenant"],),
    )
    assert stack["client"].get(f"{BASE}/ledger-api/version/1").status_code == 404
