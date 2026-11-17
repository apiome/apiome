"""Store rules for API products — APX-1.1 (#6098).

:mod:`app.api_product_store` runs each write in one transaction through ``db._guarded_tx``. These
tests replace that transaction with a cursor that answers each statement from a small in-memory
tenant (products, members, Projects with versions, MCP servers, teams), so the rules are pinned
without a database:

* a write appends its ``api_product.*`` audit row and re-derives the graph's ``includes`` family on
  the transaction's own cursor;
* a ``project_latest`` member follows each new publish with no write;
* a ``portal`` product is refused while a member is unpublished — on create, on a visibility
  change and on a member add — with the blockers, and an unrelated edit is not;
* a member ref must name a live entity of its kind, and a selector belongs to ``project_version``;
* a unique violation becomes ``api-product-slug-taken`` or ``api-product-member-duplicate``.

The SQL itself ran against Postgres when the ticket was built; ``api-products.test.ts`` in
apiome-db pins the schema.
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional

import psycopg2
import pytest

from app import api_product_store as store
from app.api_products import (
    CODE_INVALID,
    CODE_MEMBER_DUPLICATE,
    CODE_MEMBER_NOT_FOUND,
    CODE_MEMBER_REF_NOT_FOUND,
    CODE_NOT_FOUND,
    CODE_PORTAL_UNPUBLISHED,
    CODE_SLUG_TAKEN,
    CODE_TEAM_NOT_FOUND,
    ApiProductInput,
    ApiProductMemberInput,
    ApiProductPatch,
    ApiProductValidationError,
)
from app.consumer_contract_store import ConsumerActor

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_TEAM = "22222222-2222-4222-8222-222222222222"
_PAYMENTS = "33333333-3333-4333-8333-333333333333"
_REFUNDS = "44444444-4444-4444-8444-444444444444"
_SPEC = "55555555-5555-4555-8555-555555555555"
_MCP = "66666666-6666-4666-8666-666666666666"
_ACTOR = ConsumerActor(user_id=_USER, label="lead@example.com")


class _Tenant:
    """The in-memory tenant the fake cursor answers from."""

    def __init__(self) -> None:
        ids = (f"{n:08x}-0000-4000-8000-000000000000" for n in itertools.count(1))
        self.next_id = lambda: next(ids)
        self.teams = {"payments": _TEAM}
        #: id → {slug, name, publishable}
        self.projects: Dict[str, Dict[str, Any]] = {
            _PAYMENTS: {"slug": "payments", "name": "Payments API", "publishable": True},
            _REFUNDS: {"slug": "refunds", "name": "Refunds API", "publishable": True},
            _SPEC: {"slug": "ledger-spec", "name": "Ledger spec", "publishable": False},
        }
        #: project id → versions, newest first
        self.versions: Dict[str, List[Dict[str, Any]]] = {
            _PAYMENTS: [{"id": "v-p-1", "label": "1.0.0", "published": True}],
            _REFUNDS: [{"id": "v-r-2", "label": "2.1.0", "published": False},
                       {"id": "v-r-1", "label": "1.0.0", "published": True}],
            _SPEC: [{"id": "v-s-1", "label": "1", "published": True}],
        }
        self.mcp = {_MCP: {"slug": "payments-mcp", "name": "Payments MCP", "published": False}}
        self.products: Dict[str, Dict[str, Any]] = {}
        self.members: List[Dict[str, Any]] = []
        self.audit: List[Dict[str, Any]] = []
        self.materialized: List[List[str]] = []
        self.statements: List[str] = []

    # -- answers -------------------------------------------------------------------------------

    def product_rows(self, slug: str) -> List[Dict[str, Any]]:
        for pid, p in self.products.items():
            if p["slug"] == slug and not p.get("deleted"):
                team_slug = next((s for s, t in self.teams.items() if t == p["owner_team_id"]), None)
                return [{
                    "id": pid, "slug": p["slug"], "name": p["name"], "summary": p["summary"],
                    "visibility": p["visibility"], "state": p["state"], "created_by": _USER,
                    "created_at": None, "updated_at": None,
                    "team_slug": team_slug, "team_name": team_slug.title() if team_slug else None,
                    "member_count": sum(1 for m in self.members if m["product_id"] == pid),
                }]
        return []

    def member_rows(self, product_id: str) -> List[Dict[str, Any]]:
        rows = []
        for m in self.members:
            if m["product_id"] != product_id:
                continue
            entity = self.mcp.get(m["ref"]) if m["kind"] == "mcp_server" else self.projects.get(m["ref"])
            rows.append({
                "id": m["id"], "kind": m["kind"], "ref": m["ref"], "version_selector": m["selector"],
                "environment": m["environment"], "created_at": None,
                "name": entity["name"] if entity else None, "slug": entity["slug"] if entity else None,
                "present": entity is not None,
                "mcp_published": bool(entity and entity.get("published")) if m["kind"] == "mcp_server" else False,
            })
        # The statement's ORDER BY: Project-like members first, then by name.
        return sorted(rows, key=lambda r: (r["kind"] == "mcp_server", (r["name"] or "").lower()))

    def ref_rows(self, sql: str, params: tuple) -> List[Dict[str, Any]]:
        value = params[1]
        if "apiome.mcp_endpoints" in sql:
            return [{"id": i} for i, e in self.mcp.items() if value in (i, e["slug"])]
        publishable = "AND NOT publishable" not in sql
        return [{"id": i} for i, p in self.projects.items()
                if value in (i, p["slug"]) and p["publishable"] is publishable]

    def insert_member(self, params: tuple) -> List[Dict[str, Any]]:
        _tenant, product_id, kind, ref, selector, environment, _by = params
        for m in self.members:
            if (m["product_id"], m["kind"], m["ref"], m["selector"], m["environment"]) == (
                product_id, kind, ref, selector, environment
            ):
                raise _unique_violation("api_product_members_identity_key")
        member_id = self.next_id()
        self.members.append({"id": member_id, "product_id": product_id, "kind": kind, "ref": ref,
                             "selector": selector, "environment": environment})
        return [{"id": member_id}]

    def insert_product(self, params: tuple) -> List[Dict[str, Any]]:
        _tenant, slug, name, summary, team_id, visibility, state, _by = params
        if self.product_rows(slug):
            raise _unique_violation("idx_api_products_tenant_slug")
        pid = self.next_id()
        self.products[pid] = {"slug": slug, "name": name, "summary": summary, "owner_team_id": team_id,
                              "visibility": visibility, "state": state}
        return [{"id": pid}]

    def update_product(self, sql: str, params: tuple) -> None:
        pid = params[-1]
        if "deleted_at = CURRENT_TIMESTAMP" in sql:
            self.products[pid]["deleted"] = True
            return
        assignments = sql.split(" SET ", 1)[1].split(", updated_at")[0]
        for column, value in zip([a.split(" = ")[0] for a in assignments.split(", ")], params[:-1]):
            self.products[pid][column] = value

    def delete_member(self, params: tuple) -> List[Dict[str, Any]]:
        member_id, product_id, _tenant = params
        for m in list(self.members):
            if m["id"] == member_id and m["product_id"] == product_id:
                self.members.remove(m)
                return [{"kind": m["kind"], "ref": m["ref"], "version_selector": m["selector"],
                         "environment": m["environment"]}]
        return []


def _unique_violation(constraint: str) -> psycopg2.errors.UniqueViolation:
    """A ``UniqueViolation`` whose ``diag.constraint_name`` is ``constraint``.

    psycopg2's ``diag`` is read-only on the C type, so a subclass shadows it with our own.
    """

    class _Diag:
        constraint_name = constraint

    class _Violation(psycopg2.errors.UniqueViolation):
        diag = _Diag()

    return _Violation()


class _Cursor:
    """A cursor answering every statement the store runs from :class:`_Tenant`."""

    def __init__(self, tenant: _Tenant) -> None:
        self.tenant = tenant
        self.result: List[Dict[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        flat = " ".join(sql.split())
        params = tuple(params or ())
        self.tenant.statements.append(flat)
        t = self.tenant
        if "FROM apiome.api_products ap" in flat and "ap.slug = %s" in flat:
            self.result = t.product_rows(params[1])
        elif "FROM apiome.teams WHERE" in flat:
            self.result = [{"id": t.teams[params[1]]}] if params[1] in t.teams else []
        elif flat.startswith("SELECT id::text AS id FROM apiome.projects") or flat.startswith(
            "SELECT id::text AS id FROM apiome.mcp_endpoints"
        ):
            self.result = t.ref_rows(flat, params)
        elif flat.startswith("INSERT INTO apiome.api_products"):
            self.result = t.insert_product(params)
        elif flat.startswith("INSERT INTO apiome.api_product_members"):
            self.result = t.insert_member(params)
        elif "FROM apiome.api_product_members m LEFT JOIN" in flat:
            self.result = t.member_rows(params[1])
        elif "FROM apiome.versions v" in flat:
            self.result = [{**v, "project_id": pid} for pid in params[0] for v in t.versions.get(pid, [])]
        elif flat.startswith("UPDATE apiome.api_products"):
            t.update_product(flat, params)
            self.result = []
        elif flat.startswith("DELETE FROM apiome.api_product_members"):
            self.result = t.delete_member(params)
        else:
            raise AssertionError(f"unexpected statement: {flat}")

    def fetchall(self) -> List[Dict[str, Any]]:
        return self.result

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.result[0] if self.result else None


@pytest.fixture
def tenant(monkeypatch) -> _Tenant:
    """An in-memory tenant wired in as the store's transaction, audit and graph materializer."""
    state = _Tenant()

    def guarded_tx(work):
        snapshot = (dict((k, dict(v)) for k, v in state.products.items()), [dict(m) for m in state.members],
                    len(state.audit), len(state.materialized))
        try:
            return work(_Cursor(state))
        except Exception:
            # Roll back like Postgres would.
            state.products, state.members = snapshot[0], snapshot[1]
            del state.audit[snapshot[2]:]
            del state.materialized[snapshot[3]:]
            raise

    monkeypatch.setattr(store.db, "_guarded_tx", guarded_tx)
    monkeypatch.setattr(store.db, "_append_access_audit", lambda cursor, **kw: state.audit.append(kw))
    monkeypatch.setattr(
        store.db, "_materialize_graph", lambda cursor, tenant_id, families: state.materialized.append(list(families))
    )
    return state


def _create(**overrides: Any):
    body = {"name": "Payments", "owner_team": "payments", **overrides}
    return store.create_product(_TENANT, ApiProductInput(**body), actor=_ACTOR)


# ---------------------------------------------------------------------------------------------
# Create and read
# ---------------------------------------------------------------------------------------------


def test_create_stores_members_audits_and_materializes_the_includes_family(tenant: _Tenant) -> None:
    product = _create(members=[
        {"kind": "project_latest", "ref": "payments"},
        {"kind": "project_version", "ref": _REFUNDS, "version": "1.x", "environment": "Production"},
        {"kind": "catalog_item", "ref": "ledger-spec"},
    ])

    assert product.slug == "payments" and product.owner_team.slug == "payments"
    assert product.visibility == "private" and product.state == "draft"
    assert [m.name for m in product.members] == ["Ledger spec", "Payments API", "Refunds API"]
    refunds = next(m for m in product.members if m.ref == _REFUNDS)
    assert refunds.version_selector == "1.x" and refunds.environment == "production"
    assert refunds.resolved_version.label == "1.0.0" and refunds.published
    assert product.portal_ready is True
    assert [a["action"] for a in tenant.audit] == ["api_product.create"]
    assert tenant.audit[0]["target"] == "api_product:payments"
    assert len(tenant.audit[0]["detail"]["members"]) == 3
    assert tenant.materialized == [["includes"]]


def test_a_latest_member_follows_new_publishes_without_a_write(tenant: _Tenant) -> None:
    _create(members=[{"kind": "project_latest", "ref": "payments"}])
    assert store.get_product(_TENANT, "payments").members[0].resolved_version.label == "1.0.0"

    tenant.versions[_PAYMENTS].insert(0, {"id": "v-p-2", "label": "1.1.0", "published": True})
    statements = len(tenant.statements)
    member = store.get_product(_TENANT, "payments").members[0]

    assert member.resolved_version.label == "1.1.0" and member.published
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE")) for s in tenant.statements[statements:])


def test_an_unknown_team_or_member_ref_is_refused_and_nothing_is_stored(tenant: _Tenant) -> None:
    with pytest.raises(ApiProductValidationError) as caught:
        _create(owner_team="nobody")
    assert caught.value.code == CODE_TEAM_NOT_FOUND

    with pytest.raises(ApiProductValidationError) as caught:
        _create(members=[{"kind": "project_latest", "ref": "ledger-spec"}])  # a catalog item, not a Project
    assert caught.value.code == CODE_MEMBER_REF_NOT_FOUND
    assert tenant.products == {} and tenant.members == [] and tenant.audit == []


def test_a_selector_on_the_wrong_member_kind_is_refused(tenant: _Tenant) -> None:
    with pytest.raises(ApiProductValidationError) as caught:
        _create(members=[{"kind": "mcp_server", "ref": "payments-mcp", "version": "1.0.0"}])
    assert caught.value.code == CODE_INVALID


def test_a_taken_slug_and_a_repeated_member_map_to_their_codes(tenant: _Tenant) -> None:
    _create()
    with pytest.raises(ApiProductValidationError) as caught:
        _create()
    assert caught.value.code == CODE_SLUG_TAKEN

    store.add_member(_TENANT, "payments", ApiProductMemberInput(kind="project_latest", ref="payments"), actor=_ACTOR)
    with pytest.raises(ApiProductValidationError) as caught:
        store.add_member(_TENANT, "payments", ApiProductMemberInput(kind="project_latest", ref=_PAYMENTS), actor=_ACTOR)
    assert caught.value.code == CODE_MEMBER_DUPLICATE


def test_an_unknown_product_is_not_found(tenant: _Tenant) -> None:
    with pytest.raises(ApiProductValidationError) as caught:
        store.get_product(_TENANT, "nope")
    assert caught.value.code == CODE_NOT_FOUND


# ---------------------------------------------------------------------------------------------
# The portal rule
# ---------------------------------------------------------------------------------------------


def test_a_portal_product_with_an_unpublished_member_is_refused_with_blockers(tenant: _Tenant) -> None:
    with pytest.raises(ApiProductValidationError) as caught:
        _create(visibility="portal", members=[
            {"kind": "project_latest", "ref": "payments"},
            {"kind": "mcp_server", "ref": "payments-mcp"},
            {"kind": "project_version", "ref": "refunds", "version": "2.x"},
        ])
    assert caught.value.code == CODE_PORTAL_UNPUBLISHED
    assert [b["name"] for b in caught.value.blockers] == ["Refunds API", "Payments MCP"]
    assert tenant.products == {} and tenant.audit == []


def test_setting_portal_is_refused_until_every_member_is_published(tenant: _Tenant) -> None:
    _create(members=[{"kind": "mcp_server", "ref": "payments-mcp"}])
    with pytest.raises(ApiProductValidationError) as caught:
        store.update_product(_TENANT, "payments", ApiProductPatch(visibility="portal"), actor=_ACTOR)
    assert caught.value.code == CODE_PORTAL_UNPUBLISHED
    assert store.get_product(_TENANT, "payments").visibility == "private"

    tenant.mcp[_MCP]["published"] = True
    updated = store.update_product(_TENANT, "payments", ApiProductPatch(visibility="portal"), actor=_ACTOR)
    assert updated.visibility == "portal" and updated.portal_ready is True


def test_adding_an_unpublished_member_to_a_portal_product_is_refused(tenant: _Tenant) -> None:
    _create(visibility="portal", members=[{"kind": "project_latest", "ref": "payments"}])
    with pytest.raises(ApiProductValidationError) as caught:
        store.add_member(
            _TENANT, "payments", ApiProductMemberInput(kind="project_version", ref="refunds", version="2.1.0"),
            actor=_ACTOR,
        )
    assert caught.value.code == CODE_PORTAL_UNPUBLISHED
    assert len(tenant.members) == 1


def test_an_unrelated_edit_of_a_portal_product_is_not_refused_but_reports_not_ready(tenant: _Tenant) -> None:
    _create(visibility="portal", members=[{"kind": "project_latest", "ref": "payments"}])
    tenant.versions[_PAYMENTS][0]["published"] = False  # unpublished elsewhere since

    updated = store.update_product(_TENANT, "payments", ApiProductPatch(name="Payments platform"), actor=_ACTOR)
    assert updated.name == "Payments platform" and updated.portal_ready is False


# ---------------------------------------------------------------------------------------------
# Update, members and delete
# ---------------------------------------------------------------------------------------------


def test_update_changes_and_clears_fields_and_audits_what_changed(tenant: _Tenant) -> None:
    _create(summary="Card payments")
    updated = store.update_product(
        _TENANT, "payments", ApiProductPatch(summary=None, owner_team=None, state="published"), actor=_ACTOR
    )
    assert updated.summary is None and updated.owner_team is None and updated.state == "published"
    detail = tenant.audit[-1]["detail"]
    assert tenant.audit[-1]["action"] == "api_product.update"
    assert detail["state"] == "published" and detail["owner_team"] is None and "owner_team_id" not in detail


def test_remove_member_removes_one_and_refuses_an_unknown_one(tenant: _Tenant) -> None:
    product = _create(members=[{"kind": "project_latest", "ref": "payments"}, {"kind": "mcp_server", "ref": _MCP}])
    mcp_member = next(m for m in product.members if m.kind == "mcp_server")

    after = store.remove_member(_TENANT, "payments", mcp_member.id, actor=_ACTOR)
    assert [m.kind for m in after.members] == ["project_latest"]
    assert tenant.audit[-1]["action"] == "api_product.member.remove"
    assert tenant.materialized[-1] == ["includes"]

    for bad in (mcp_member.id, "not-a-uuid"):
        with pytest.raises(ApiProductValidationError) as caught:
            store.remove_member(_TENANT, "payments", bad, actor=_ACTOR)
        assert caught.value.code == CODE_MEMBER_NOT_FOUND


def test_a_deleted_member_entity_is_reported_missing_and_unpublished(tenant: _Tenant) -> None:
    _create(members=[{"kind": "project_latest", "ref": "refunds"}])
    del tenant.projects[_REFUNDS]
    member = store.get_product(_TENANT, "payments").members[0]
    assert member.missing and not member.published and member.name is None


def test_delete_is_soft_frees_the_slug_and_materializes(tenant: _Tenant) -> None:
    _create()
    assert store.delete_product(_TENANT, "payments", actor=_ACTOR) == "payments"
    assert tenant.audit[-1]["action"] == "api_product.delete"
    assert tenant.materialized[-1] == ["includes"]
    with pytest.raises(ApiProductValidationError):
        store.get_product(_TENANT, "payments")
    assert _create().slug == "payments"
