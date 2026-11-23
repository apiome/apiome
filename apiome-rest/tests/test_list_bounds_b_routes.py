"""The authoring lists page by ``limit`` + ``cursor`` (DBP-1.13, #7196).

One parametrized walk over the lists converted from unbounded reads: unresolved primitives, type
namespaces, classes-with-parts, project conversions, lint decisions and their events, style guides
and their revisions and policy versions, version branches, project properties, class tags, version
tags, custom palette actions, library components, component usage pins and component deprecations.
Each must report has-more and a cursor on a short page, walk to the end in order, refuse a
``limit`` over its documented maximum (422) and a malformed cursor (400).

The two lists that are bounded without a cursor are checked separately: the sunset timeline (its
order is computed from metadata, so it pages by offset over a capped read) and a revision's lint
evidence (the newest ``limit`` runs).
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import authoring_list_orders as orders
from app.auth import validate_authentication
from app.main import app
from tests.keyset_paging_fakes import check_list_paging, ordered_rows
from tests.test_conversion_evidence_routes import _row as _conversion_row
from tests.test_style_guide_routes import GUIDE_ID, _custom_row, _revision_row
from tests.test_type_namespaces_routes import _SYSTEM_NS_ROW
from tests.test_workspace_custom_action_routes import action_row

client = TestClient(app)
TENANT = "11111111-1111-4111-8111-111111111111"
T0 = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)
_AUTH = {"tenant_id": TENANT, "user_id": "u1", "auth_method": "jwt", "permissions": ["*"]}
COUNT = 5


def _uuid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


@pytest.fixture(autouse=True)
def _signed_in():
    app.dependency_overrides[validate_authentication] = lambda: dict(_AUTH)
    yield
    app.dependency_overrides.pop(validate_authentication, None)


class Case:
    """One converted list: where it lives, how to stand in for its accessor, how to read it."""

    def __init__(
        self,
        name: str,
        url: str,
        module: str,
        accessor: str,
        order: Any,
        rows: List[Dict[str, Any]],
        *,
        maximum: int,
        items_key: Optional[str],
        camel: bool = True,
        id_of: Callable[[Any], Any] = lambda item: item["id"],
        row_id: Callable[[Dict[str, Any]], Any] = lambda row: row["id"],
        setup: Callable[[MagicMock], None] = lambda db: None,
        target: str = "db",
        extra_patches: tuple = (),
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.name = name
        self.url = url
        self.module = module
        self.accessor = accessor
        self.order = order
        self.rows = rows
        self.maximum = maximum
        self.items_key = items_key
        self.camel = camel
        self.id_of = id_of
        self.row_id = row_id
        self.setup = setup
        self.target = target
        self.extra_patches = extra_patches
        self.params = params or {}

    @contextmanager
    def patched(self) -> Iterator[MagicMock]:
        with ExitStack() as stack:
            double = stack.enter_context(patch(f"app.{self.module}.{self.target}"))
            for extra in self.extra_patches:
                stack.enter_context(patch(extra))
            double.user_has_permission.return_value = True
            self.setup(double)
            getattr(double, self.accessor).side_effect = ordered_rows(self.order, self.rows)
            yield double


def _namespaces() -> List[Dict[str, Any]]:
    return [
        {**_SYSTEM_NS_ROW, "id": _uuid(n), "is_system": n < 2, "namespace": f"acme/v{n}/types"}
        for n in range(COUNT)
    ]


def _decision(n: int) -> Dict[str, Any]:
    return {
        "id": _uuid(n),
        "tenant_id": TENANT,
        "project_id": None,
        "source_fingerprint": f"fp-{n}",
        "rule_id": "r1",
        "state": "open",
        "created_at": T0,
        "updated_at": T0 - timedelta(minutes=n // 2),
    }


def _event(n: int) -> Dict[str, Any]:
    return {
        "id": _uuid(n),
        "decision_id": _uuid(900),
        "after_state": "open",
        "created_at": T0 + timedelta(minutes=n // 2),
    }


def _policy_version(n: int) -> Dict[str, Any]:
    return {
        "id": _uuid(n),
        "guide_id": GUIDE_ID,
        "tenant_id": TENANT,
        "version_number": COUNT - n,
        "content_fingerprint": "f" * 64,
        "rules_snapshot": [],
        "axis_gates": {},
        "required_coverage": {},
        "ci_outcomes": {},
        "ladder": None,
        "required_publish_level": None,
        "created_at": T0,
    }


def _pin(n: int) -> Dict[str, Any]:
    return {
        "id": _uuid(n),
        "local_name": None,
        "revision_id": _uuid(700),
        "revision": "1.0.0",
        "payload_digest": "sha256:x",
        "component_id": _uuid(800),
        "component_name": "PageParam",
        "kind": "parameter",
        "version_id": _uuid(600 + n // 2),
        "project_id": _uuid(500),
    }


def _deprecation(n: int) -> Dict[str, Any]:
    return {
        "id": _uuid(n),
        "component_id": _uuid(800),
        "component_name": "PageParam",
        "kind": "parameter",
        "revision_id": _uuid(700 + n),
        "revision": f"1.{n}.0",
        "replacement_revision_id": None,
        "replacement_revision": None,
        "sunset_at": T0 + timedelta(days=n // 2),
        "migration_guide": None,
    }


def _project(db: MagicMock) -> None:
    db.get_project_core.return_value = {"id": "p1", "tenant_id": TENANT}


def _version(db: MagicMock) -> None:
    db.get_version_for_tenant.return_value = {"id": "v1"}


def _unresolved(db: MagicMock) -> None:
    db.count_unresolved_refs.return_value = {
        "unresolved_ref_count": COUNT,
        "affected_primitive_count": COUNT,
    }


def _guide(db: MagicMock) -> None:
    db.get_style_guide_by_id.return_value = _custom_row()
    db.list_style_guide_project_assignments.return_value = []


def _component(db: MagicMock) -> None:
    db.get_operational_component.return_value = {"id": _uuid(800), "name": "PageParam", "kind": "parameter"}
    db.get_component_graph_rows.return_value = ([], [])
    db.get_component_consumers.return_value = []


CASES = [
    Case(
        "unresolved-primitives",
        "/v1/primitives/acme/unresolved",
        "primitives_routes",
        "get_primitives_with_unresolved_refs",
        orders.UNRESOLVED_PRIMITIVES_ORDER,
        [
            {
                "id": _uuid(n),
                "name": f"Type{n}",
                "schema_id": None,
                "namespace": None if n < 2 else "acme/v1",
                "base_uri": None,
                "refs": [{"status": "unresolved", "relative_ref": "./x"}],
            }
            for n in range(COUNT)
        ],
        maximum=1000,
        items_key="primitives",
        camel=False,
        setup=_unresolved,
    ),
    Case(
        "type-namespaces",
        "/v1/types/acme/namespaces",
        "type_namespaces_routes",
        "list_type_namespaces",
        orders.TYPE_NAMESPACES_ORDER,
        _namespaces(),
        maximum=1000,
        items_key=None,
    ),
    Case(
        "classes-with-parts",
        "/v1/classes/acme/version/v1/with-properties-tags",
        "classes_routes",
        "get_classes_with_properties_and_tags_for_version",
        orders.CLASSES_WITH_PARTS_ORDER,
        [{"id": _uuid(n), "name": f"Class{n // 2}", "properties": [], "tags": []} for n in range(COUNT)],
        maximum=1000,
        items_key=None,
        setup=_version,
    ),
    Case(
        "project-conversions",
        "/v1/projects/acme/p1/conversions",
        "projects_routes",
        "get_conversions_for_project",
        orders.PROJECT_CONVERSIONS_ORDER,
        [_conversion_row(id=_uuid(n), created_at=T0 - timedelta(minutes=n // 2)) for n in range(COUNT)],
        maximum=200,
        items_key="conversions",
        id_of=lambda item: item["provenanceId"],
        setup=_project,
    ),
    Case(
        "lint-decisions",
        "/v1/lint/decisions",
        "lint_routes",
        "list_lint_finding_decisions",
        orders.LINT_DECISIONS_ORDER,
        [_decision(n) for n in range(COUNT)],
        maximum=1000,
        items_key="decisions",
    ),
    Case(
        "lint-decision-events",
        f"/v1/lint/decisions/{_uuid(900)}/events",
        "lint_routes",
        "list_lint_finding_decision_events",
        orders.LINT_DECISION_EVENTS_ORDER,
        [_event(n) for n in range(COUNT)],
        maximum=200,
        items_key=None,
        setup=lambda db: setattr(db.get_lint_finding_decision, "return_value", {"id": _uuid(900)}),
    ),
    Case(
        "style-guides",
        "/v1/style-guides/acme",
        "style_guide_routes",
        "list_style_guides",
        orders.STYLE_GUIDES_ORDER,
        [
            _custom_row(id=_uuid(n), name=f"Guide {n // 2}", is_builtin=n == 0)
            for n in range(COUNT)
        ],
        maximum=1000,
        items_key="guides",
        setup=_guide,
    ),
    Case(
        "style-guide-revisions",
        f"/v1/style-guides/acme/{GUIDE_ID}/revisions",
        "style_guide_routes",
        "list_style_guide_revisions",
        orders.STYLE_GUIDE_REVISIONS_ORDER,
        [_revision_row(id=_uuid(n), revision_number=COUNT - n) for n in range(COUNT)],
        maximum=500,
        items_key="revisions",
        setup=_guide,
        extra_patches=("app.style_guide_routes.ensure_guide_revision",),
    ),
    Case(
        "style-guide-policy-versions",
        f"/v1/style-guides/acme/{GUIDE_ID}/policy-versions",
        "style_guide_routes",
        "list_style_guide_policy_versions",
        orders.STYLE_GUIDE_POLICY_VERSIONS_ORDER,
        [_policy_version(n) for n in range(COUNT)],
        maximum=200,
        items_key="versions",
        setup=_guide,
    ),
    Case(
        "version-branches",
        "/v1/versions/acme/p1/version-branches",
        "version_merge_routes",
        "list_version_branches_detailed_for_project",
        orders.VERSION_BRANCHES_ORDER,
        [{"id": _uuid(n), "name": f"branch-{n}"} for n in range(COUNT)],
        maximum=1000,
        items_key=None,
        setup=_project,
    ),
    Case(
        "project-properties",
        "/v1/properties/acme/p1",
        "properties_routes",
        "get_properties_for_project",
        orders.PROJECT_PROPERTIES_ORDER,
        [
            {
                "id": _uuid(n),
                "project_id": "p1",
                "name": f"prop{n // 2}",
                "description": None,
                "data": {},
                "enabled": True,
                "created_at": T0,
                "updated_at": T0,
                "used_by": [],
                "used_by_count": 0,
            }
            for n in range(COUNT)
        ],
        maximum=1000,
        items_key=None,
        setup=_project,
    ),
    Case(
        "project-tags",
        "/v1/project-tags/acme/p1",
        "project_tags_routes",
        "get_tags_for_project",
        orders.PROJECT_TAGS_ORDER,
        [
            {
                "id": _uuid(n),
                "project_id": "p1",
                "name": f"tag{n}",
                "color": "#000000",
                "description": None,
                "created_at": T0.isoformat(),
                "updated_at": T0.isoformat(),
            }
            for n in range(COUNT)
        ],
        maximum=1000,
        items_key=None,
        setup=_project,
    ),
    Case(
        "version-tags",
        "/v1/version-tags/acme/p1",
        "version_tags_routes",
        "list_version_tags_for_project",
        orders.VERSION_TAGS_ORDER,
        [
            {
                "id": _uuid(n),
                "project_id": "p1",
                "version_id": _uuid(600),
                "name": f"v1.{n}",
                "message": None,
                "channel": None,
                "immutable": False,
                "protected": False,
                "created_by": None,
                "created_at": T0,
                "updated_at": T0,
                "target_version_string": "1.0.0",
                "created_by_email": None,
            }
            for n in range(COUNT)
        ],
        maximum=1000,
        items_key=None,
        setup=_project,
    ),
    Case(
        "custom-actions",
        "/v1/workspace/acme/custom-actions",
        "workspace_custom_action_routes",
        "list_actions",
        orders.CUSTOM_ACTIONS_ORDER,
        [action_row(id=_uuid(n), name=f"Action {n // 2}", name_sort=f"action {n // 2}") for n in range(COUNT)],
        maximum=1000,
        items_key="actions",
        target="store",
    ),
    Case(
        "components",
        "/v1/component-library/acme/components",
        "component_library_routes",
        "list_operational_components",
        orders.COMPONENTS_ORDER,
        [
            {
                "id": _uuid(n),
                "name": f"Component{n}",
                "kind": "header" if n < 2 else "parameter",
                "description": None,
                "owner_id": None,
                "revision_count": 1,
                "published_count": 1,
                "head_revision": "1.0.0",
            }
            for n in range(COUNT)
        ],
        maximum=1000,
        items_key="components",
    ),
    Case(
        "component-usage-pins",
        f"/v1/component-library/acme/components/{_uuid(800)}/usage",
        "component_library_routes",
        "get_component_usage_pins",
        orders.COMPONENT_USAGE_PINS_ORDER,
        [_pin(n) for n in range(COUNT)],
        maximum=1000,
        items_key="pins",
        setup=_component,
    ),
    Case(
        "component-deprecations",
        "/v1/component-library/acme/deprecations",
        "component_governance_routes",
        "list_component_deprecations",
        orders.COMPONENT_DEPRECATIONS_ORDER,
        [_deprecation(n) for n in range(COUNT)],
        maximum=200,
        items_key="deprecations",
        setup=_component,
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_the_list_pages_by_cursor_and_refuses_bad_input(case: Case):
    with case.patched() as double:
        check_list_paging(
            lambda params: client.get(case.url, params={**case.params, **params}),
            case.items_key,
            [case.row_id(row) for row in case.rows],
            maximum=case.maximum,
            id_of=case.id_of,
            has_more_key="hasMore" if case.camel else "has_more",
            next_cursor_key="nextCursor" if case.camel else "next_cursor",
        )
        first_call = getattr(double, case.accessor).call_args_list[0]
    # The route reads one row more than the page to learn whether another page exists.
    assert first_call.kwargs["limit"] == 3
    assert first_call.kwargs["cursor"] is None


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_an_unpaged_request_reads_one_maximum_page(case: Case):
    with case.patched() as double:
        response = client.get(case.url, params=case.params)
        call = getattr(double, case.accessor).call_args
    assert response.status_code == 200, response.text
    default = 100 if case.name == "style-guide-revisions" else case.maximum
    assert call.kwargs["limit"] == default + 1
    body = response.json()
    if case.items_key is None:
        assert len(body) == COUNT
        assert response.headers["X-Has-More"] == "false"
    else:
        assert len(body[case.items_key]) == COUNT
        assert body["hasMore" if case.camel else "has_more"] is False


# --- the sunset timeline pages by offset over a capped read -----------------------------------


def _sunset_rows(count: int) -> List[Dict[str, Any]]:
    return [
        {
            "id": _uuid(n),
            "project_id": "p1",
            "version_id": f"1.{n}.0",
            "metadata": {"deprecated": True, "sunsetDate": f"2027-01-{count - n:02d}"},
            "published": True,
            "project_name": "Orders",
            "project_slug": "orders",
        }
        for n in range(count)
    ]


def test_the_sunset_timeline_pages_by_offset_and_says_when_it_continues():
    with patch("app.versions_routes.db") as db, patch(
        "app.versions_routes._sunset_readiness", return_value={}
    ), patch("app.versions_routes._product_timeline", return_value=[]):
        db.list_sunset_timeline_entries.return_value = _sunset_rows(5)
        first = client.get("/v1/versions/acme/sunset-timeline", params={"limit": 2})
        second = client.get("/v1/versions/acme/sunset-timeline", params={"limit": 2, "offset": 4})
        over = client.get("/v1/versions/acme/sunset-timeline", params={"limit": 1001})
        deep = client.get("/v1/versions/acme/sunset-timeline", params={"offset": 10_001})
        scan_limit = db.list_sunset_timeline_entries.call_args.kwargs["limit"]
    # Soonest sunset first: the rows were seeded latest-first, so the order is reversed.
    assert [entry["revisionId"] for entry in first.json()["entries"]] == [_uuid(4), _uuid(3)]
    assert first.json()["hasMore"] is True
    assert [entry["revisionId"] for entry in second.json()["entries"]] == [_uuid(0)]
    assert second.json()["hasMore"] is False
    assert over.status_code == 422 and deep.status_code == 422
    assert scan_limit == 10_000


# --- a revision's lint evidence is the newest `limit` runs ------------------------------------


def test_revision_lint_evidence_reads_at_most_the_requested_runs():
    with patch("app.lint_routes.db") as db, patch(
        "app.format_adapter_evidence.capture_format_adapters_for_revision"
    ):
        db.get_project_core.return_value = {"id": "p1"}
        db.get_version_core.return_value = {"id": "v1", "project_id": "p1"}
        db.get_version_source_projection.return_value = {"source_format": "openapi"}
        db.list_lint_evidence_runs_for_version.return_value = []
        default = client.get("/v1/versions/acme/p1/v1/lint/evidence")
        narrow = client.get("/v1/versions/acme/p1/v1/lint/evidence", params={"limit": 5})
        calls = db.list_lint_evidence_runs_for_version.call_args_list
        over = client.get("/v1/versions/acme/p1/v1/lint/evidence", params={"limit": 201})
    assert default.status_code == 200 and narrow.status_code == 200
    assert [call.kwargs["limit"] for call in calls] == [200, 5]
    assert over.status_code == 422
