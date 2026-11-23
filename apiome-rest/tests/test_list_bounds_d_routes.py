"""Tenant-configuration lists page by ``limit`` + ``cursor`` (DBP-1.13, #7196).

One parametrized walk over the lists this slice bounded: roles, members, push-webhook
subscriptions and dead letters, change-report templates, repositories, MCP keys / manifests /
saved searches / notes / categories / collections, schema-registry subjects and versions, draft
branches, Slate sites and git connections, and the SSO provider lists. Each case patches the list's
accessor with a stand-in that pages like the SQL does and checks the four facts every converted
list must show (:func:`tests.keyset_paging_fakes.check_list_paging`).
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, NamedTuple, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import merge_request_store, schema_registry_store, sso_provider_store
from app.auth import validate_authentication
from app.keyset_lists import ListOrder
from app.main import app
from app.merge_requests import DraftBranchRecord
from app.slate_auth import validate_slate_authentication
from app.slate_deployment_store import SITES_ORDER
from app.slate_git_preview_store import CONNECTIONS_ORDER
from app.sso_provider_routes import require_internal_service, require_super_admin
from app.tenant_list_orders import (
    CHANGE_REPORT_TEMPLATE_VERSIONS_ORDER,
    MCP_API_KEYS_ORDER,
    MCP_CATEGORIES_ORDER,
    MCP_COLLECTIONS_ORDER,
    MCP_ENDPOINT_MANIFESTS_ORDER,
    MCP_ENDPOINT_NOTES_ORDER,
    MCP_SAVED_SEARCHES_ORDER,
    MEMBERS_ORDER,
    PUSH_WEBHOOK_DEAD_LETTER_ORDER,
    PUSH_WEBHOOK_SUBSCRIPTIONS_ORDER,
    ROLES_ORDER,
    TENANT_REPOSITORIES_ORDER,
)
from tests.keyset_paging_fakes import check_list_paging, ordered_rows
from tests.test_mcp_collection_routes import _ROW as _COLLECTION_ROW
from tests.test_mcp_endpoint_note_routes import _ROW as _NOTE_ROW
from tests.test_mcp_key_routes import _key_row
from tests.test_mcp_manifest_routes import _manifest_row
from tests.test_mcp_saved_search_routes import _ROW as _SAVED_SEARCH_ROW
from tests.test_slate_git_preview_routes import connection_public as connection_row
from tests.test_tenant_repositories_api import _LIST_ROW as _REPOSITORY_ROW

client = TestClient(app)
TENANT = "11111111-1111-4111-8111-111111111111"
USER = "22222222-2222-4222-8222-222222222222"
ENDPOINT = "33333333-3333-4333-8333-333333333333"
T0 = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)
_AUTH = {"tenant_id": TENANT, "user_id": USER, "auth_method": "jwt", "permissions": ["*"]}
COUNT = 5


def _uuid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _stamp(n: int) -> datetime:
    return T0 - timedelta(minutes=n)


@pytest.fixture(autouse=True)
def _signed_in():
    overrides = {
        validate_authentication: lambda: _AUTH,
        validate_slate_authentication: lambda: dict(_AUTH),
        require_super_admin: lambda: None,
        require_internal_service: lambda: None,
    }
    app.dependency_overrides.update(overrides)
    yield
    for dependency in overrides:
        app.dependency_overrides.pop(dependency, None)


class Case(NamedTuple):
    """One converted list endpoint and how to stand in for its accessor.

    Attributes:
        name: The test id.
        url: The list's URL.
        target: The patched accessor (``module.attribute`` path).
        order: The list's ordering.
        rows: Every row, in list order.
        items_key: The body key of the rows; ``None`` for a bare array.
        maximum: The documented maximum ``limit``.
        id_of: Reads the id of a served row.
        camel: Whether the envelope names its paging fields in camelCase.
        extra: Further ``patch`` targets and their replacements.
        ids: The served ids, when they differ from the rows' ``id``.
    """

    name: str
    url: str
    target: str
    order: ListOrder
    rows: List[Any]
    items_key: Optional[str]
    maximum: int
    id_of: Callable[[Any], Any] = lambda item: item["id"]
    camel: bool = False
    extra: Dict[str, Any] = {}
    ids: Optional[List[Any]] = None


def _allow(*_: Any, **__: Any) -> str:
    return USER


def _subject_rows() -> List[Dict[str, Any]]:
    return [
        {
            "id": _uuid(n),
            "name": f"orders-{n}-value",
            "strategy": "TopicNameStrategy",
            "compatibility_level": None,
            "mode": "READWRITE",
            "project_id": None,
            "created_at": T0,
            "updated_at": T0,
        }
        for n in range(COUNT)
    ]


def _subject_version_rows() -> List[Dict[str, Any]]:
    return [
        {
            "id": _uuid(n),
            "version": n + 1,
            "schema_id": 100 + n,
            "schema_type": "AVRO",
            "fingerprint": f"f{n}",
            "project_id": _uuid(900),
            "version_record_id": _uuid(950 + n),
            "created_at": T0,
        }
        for n in range(COUNT)
    ]


def _sso_rows() -> List[Dict[str, Any]]:
    return [
        {
            "id": _uuid(n),
            "slug": f"acme-{n}",
            "protocol": "oidc",
            "display_name": f"Acme {n}",
            "issuer": "https://idp.example.com",
            "tenant_id": TENANT,
            "tenant_name": "Acme",
            "oidc_config": {"client_id": "abc"},
            "saml_config": None,
            "has_client_secret": True,
            "has_sp_private_key": False,
            "enabled": True,
            "preset": None,
            "default_role_slug": "viewer",
            "created_at": _stamp(n),
            "updated_at": _stamp(n),
            "domains": [],
            "client_secret_encrypted": None,
            "client_secret_key_id": None,
            "sp_private_key_encrypted": None,
            "sp_private_key_key_id": None,
        }
        for n in range(COUNT)
    ]


def _site_rows() -> List[Dict[str, Any]]:
    return [
        {
            "id": _uuid(n),
            "project_id": _uuid(800),
            "name": f"Docs {n}",
            "slug": f"docs-{n}",
            "created_at": _stamp(n),
            "environments": [],
        }
        for n in range(COUNT)
    ]


def _cases() -> List[Case]:
    registry_store = MagicMock()
    registry_store.get_config.return_value = {"compatibility_level": "BACKWARD", "mode": "READWRITE"}
    registry_store.get_subject.return_value = {"id": _uuid(700), "name": "orders-value"}
    registry_db = "app.schema_registry_routes.enforce_permission"
    return [
        Case(
            "roles",
            "/v1/access/acme/roles",
            "app.access_routes.db.list_roles",
            ROLES_ORDER,
            [
                {
                    "id": _uuid(n),
                    "slug": f"custom-{n}",
                    "name": f"Custom {n}",
                    "is_builtin": False,
                    "builtin_rank": 4,
                    "member_count": n,
                }
                for n in range(COUNT)
            ],
            None,
            1000,
            extra={
                "app.access_routes.enforce_permission": _allow,
                "app.access_routes.db.ensure_builtin_roles": MagicMock(),
                "app.access_routes.db.get_role_permissions": MagicMock(return_value=[]),
            },
        ),
        Case(
            "members",
            "/v1/access/acme/members",
            "app.access_routes.db.list_members",
            MEMBERS_ORDER,
            [{"user_id": _uuid(n), "name": f"Member {n}", "email": f"m{n}@acme.io"} for n in range(COUNT)],
            None,
            1000,
            id_of=lambda item: item["user_id"],
            extra={
                "app.access_routes.enforce_permission": _allow,
                "app.access_routes.db.ensure_builtin_roles": MagicMock(),
            },
            ids=[_uuid(n) for n in range(COUNT)],
        ),
        Case(
            "push-webhook-subscriptions",
            "/v1/push-webhook-subscriptions/acme",
            "app.push_webhook_subscriptions_routes.db.list_push_webhook_subscriptions",
            PUSH_WEBHOOK_SUBSCRIPTIONS_ORDER,
            [
                {
                    "id": _uuid(n),
                    "url": f"https://hooks.example.com/{n}",
                    "active": True,
                    "signing_secret_ref": "ref",
                    "min_severity": None,
                    "created_at": _stamp(n),
                    "updated_at": _stamp(n),
                }
                for n in range(COUNT)
            ],
            None,
            1000,
        ),
        Case(
            "push-webhook-dead-letter",
            "/v1/push-webhook-subscriptions/acme/deliveries/dead-letter",
            "app.push_webhook_subscriptions_routes.db.list_push_webhook_dead_letter_events",
            PUSH_WEBHOOK_DEAD_LETTER_ORDER,
            [
                {
                    "id": _uuid(n),
                    "subscription_id": _uuid(600),
                    "event_type": "version.published",
                    "payload": {},
                    "attempt_count": 5,
                    "last_error": "timeout",
                    "created_at": _stamp(n),
                    "updated_at": _stamp(n),
                }
                for n in range(COUNT)
            ],
            None,
            200,
        ),
        Case(
            "change-report-template-versions",
            "/v1/tenants/acme/change-report-template-versions",
            "app.change_report_template_routes.db.list_change_report_template_version_summaries",
            CHANGE_REPORT_TEMPLATE_VERSIONS_ORDER,
            [
                {
                    "id": _uuid(n),
                    "owner_tenant_id": None if n < 2 else TENANT,
                    "semver": f"1.{n}.0",
                    "created_at": T0,
                }
                for n in range(COUNT)
            ],
            None,
            1000,
        ),
        Case(
            "repositories",
            "/v1/tenants/acme/repositories",
            "app.tenant_repositories_routes.db.list_tenant_repositories",
            TENANT_REPOSITORIES_ORDER,
            [{**_REPOSITORY_ROW, "id": _uuid(n), "created_at": _stamp(n)} for n in range(COUNT)],
            "repositories",
            1000,
            extra={"app.tenant_repositories_routes._repository_health_by_id": lambda _tenant: {}},
        ),
        Case(
            "mcp-keys",
            "/v1/tenants/acme/mcp-keys",
            "app.mcp_key_routes.db.list_mcp_api_keys",
            MCP_API_KEYS_ORDER,
            [_key_row(id=_uuid(n), created_at=_stamp(n)) for n in range(COUNT)],
            "keys",
            1000,
            extra={"app.mcp_key_routes.db.is_user_tenant_admin": MagicMock(return_value=True)},
        ),
        Case(
            "mcp-endpoint-manifests",
            f"/v1/mcp/acme/endpoints/{ENDPOINT}/manifests",
            "app.mcp_manifest_routes.db.list_mcp_endpoint_manifests",
            MCP_ENDPOINT_MANIFESTS_ORDER,
            [_manifest_row(id=_uuid(n), created_at=_stamp(n)) for n in range(COUNT)],
            "manifests",
            200,
            extra={
                "app.mcp_manifest_routes._require_tenant_endpoint": lambda *_a, **_k: {"id": ENDPOINT}
            },
        ),
        Case(
            "mcp-saved-searches",
            "/v1/mcp/acme/saved-searches",
            "app.mcp_saved_search_routes.db.list_mcp_saved_searches",
            MCP_SAVED_SEARCHES_ORDER,
            [
                {
                    **_SAVED_SEARCH_ROW,
                    "id": _uuid(n),
                    "name": f"Search {n}",
                    "is_pinned": n < 2,
                    "updated_at": _stamp(n),
                }
                for n in range(COUNT)
            ],
            "searches",
            1000,
        ),
        Case(
            "mcp-endpoint-notes",
            f"/v1/mcp/acme/endpoints/{ENDPOINT}/notes",
            "app.mcp_endpoint_note_routes.db.list_mcp_endpoint_notes",
            MCP_ENDPOINT_NOTES_ORDER,
            [{**_NOTE_ROW, "id": _uuid(n), "created_at": _stamp(n)} for n in range(COUNT)],
            "notes",
            200,
            extra={"app.mcp_endpoint_note_routes._require_tenant_endpoint": lambda *_a, **_k: None},
        ),
        Case(
            "mcp-categories",
            "/v1/mcp/acme/categories",
            "app.mcp_categorization_routes.db.list_mcp_categories",
            MCP_CATEGORIES_ORDER,
            [
                {
                    "id": _uuid(n),
                    "slug": f"cat-{n}",
                    "label": f"Cat {n}",
                    "label_key": f"cat {n}",
                    "sort_order": n,
                    "builtin": False,
                }
                for n in range(COUNT)
            ],
            "categories",
            1000,
            id_of=lambda item: item["slug"],
            ids=[f"cat-{n}" for n in range(COUNT)],
        ),
        Case(
            "mcp-collections",
            "/v1/mcp/acme/collections",
            "app.mcp_collection_routes.db.list_mcp_collections",
            MCP_COLLECTIONS_ORDER,
            [
                {**_COLLECTION_ROW, "id": _uuid(n), "name": f"Set {n}", "updated_at": _stamp(n)}
                for n in range(COUNT)
            ],
            "collections",
            1000,
        ),
        Case(
            "schema-subjects",
            "/v1/tenants/acme/schema-registry/subjects",
            "app.schema_registry_routes.store.list_subjects",
            schema_registry_store.SUBJECTS_ORDER,
            _subject_rows(),
            "subjects",
            1000,
            id_of=lambda item: item["name"],
            camel=True,
            extra={registry_db: _allow, "app.schema_registry_routes.store": registry_store},
            ids=[f"orders-{n}-value" for n in range(COUNT)],
        ),
        Case(
            "schema-subject-versions",
            "/v1/tenants/acme/schema-registry/subjects/orders-value/versions",
            "app.schema_registry_routes.store.list_versions",
            schema_registry_store.SUBJECT_VERSIONS_ORDER,
            _subject_version_rows(),
            "versions",
            1000,
            id_of=lambda item: item["version"],
            camel=True,
            extra={registry_db: _allow, "app.schema_registry_routes.store": registry_store},
            ids=[n + 1 for n in range(COUNT)],
        ),
        Case(
            "draft-branches",
            "/v1/tenants/acme/projects/petstore/draft-branches",
            "app.merge_request_routes.merge_request_store.list_draft_branches",
            merge_request_store.DRAFT_BRANCHES_ORDER,
            [
                DraftBranchRecord(
                    id=_uuid(n),
                    project_id=_uuid(500),
                    name=f"draft/{n}",
                    tip_revision_id=_uuid(400 + n),
                    created_at=_stamp(n),
                )
                for n in range(COUNT)
            ],
            "branches",
            1000,
            extra={"app.merge_request_routes.enforce_permission": _allow},
            ids=[_uuid(n) for n in range(COUNT)],
        ),
        Case(
            "slate-sites",
            "/v1/slate/sites",
            "app.slate_routes.list_sites",
            SITES_ORDER,
            _site_rows(),
            "sites",
            1000,
            camel=True,
            extra={"app.slate_routes.enforce_permission": _allow},
        ),
        Case(
            "slate-git-connections",
            "/v1/slate/git/connections",
            "app.slate_git_preview_routes.list_connections",
            CONNECTIONS_ORDER,
            [connection_row(id=_uuid(n), created_at=_stamp(n)) for n in range(COUNT)],
            "connections",
            1000,
            camel=True,
            extra={"app.slate_git_preview_routes.enforce_permission": _allow},
        ),
        Case(
            "admin-sso-providers",
            "/v1/admin/sso/providers",
            "app.sso_provider_routes.store.list_providers",
            sso_provider_store.PROVIDERS_ORDER,
            _sso_rows(),
            "providers",
            1000,
        ),
        Case(
            "tenant-sso-providers",
            "/v1/tenants/acme/sso/providers",
            "app.tenant_sso_routes.store.list_providers",
            sso_provider_store.PROVIDERS_ORDER,
            _sso_rows(),
            "providers",
            1000,
            extra={
                "app.tenant_sso_routes.require_tenant_admin_session": lambda *_a, **_k: TENANT,
                "app.tenant_sso_routes.store.count_linked_members": lambda *_a, **_k: 0,
            },
        ),
        Case(
            "resolved-sso-providers",
            "/v1/internal/sso/providers/resolved",
            "app.sso_provider_routes.store.list_routable_with_secrets",
            sso_provider_store.ROUTABLE_PROVIDERS_ORDER,
            [{**row, "protocol": "saml"} for row in _sso_rows()],
            "providers",
            1000,
        ),
    ]


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case.name)
def test_a_converted_list_pages_by_cursor(case: Case) -> None:
    with ExitStack() as stack:
        for target, replacement in case.extra.items():
            stack.enter_context(patch(target, replacement))
        accessor = stack.enter_context(patch(case.target))
        accessor.side_effect = ordered_rows(case.order, case.rows)
        expected = case.ids or [
            row["id"] if isinstance(row, dict) else row.id for row in case.rows
        ]
        check_list_paging(
            lambda params: client.get(case.url, params=params),
            case.items_key,
            expected,
            maximum=case.maximum,
            id_of=case.id_of,
            has_more_key="hasMore" if case.camel else "has_more",
            next_cursor_key="nextCursor" if case.camel else "next_cursor",
        )
        # The route reads one row more than the page, and nothing when the cursor is refused.
        first_call = accessor.call_args_list[0]
        asked = first_call.kwargs.get("limit", first_call.args[-1] if first_call.args else None)
        assert asked == 3


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case.name)
def test_a_converted_list_serves_its_maximum_by_default(case: Case) -> None:
    with ExitStack() as stack:
        for target, replacement in case.extra.items():
            stack.enter_context(patch(target, replacement))
        accessor = stack.enter_context(patch(case.target))
        accessor.side_effect = ordered_rows(case.order, case.rows)
        response = client.get(case.url)
    assert response.status_code == 200, response.text
    call = accessor.call_args_list[0]
    assert call.kwargs.get("limit", call.args[-1] if call.args else None) == case.maximum + 1
    if case.items_key is None:
        assert response.headers["X-Has-More"] == "false"
        assert "X-Next-Cursor" not in response.headers
        assert len(response.json()) == COUNT
    else:
        assert len(response.json()[case.items_key]) == COUNT


# --- lists that cannot page by keyset --------------------------------------------------------


def test_the_tag_vocabulary_pages_by_limit_and_offset() -> None:
    rows = [{"tag": f"tag-{n}", "endpoint_count": 9 - n} for n in range(3)]
    with patch("app.mcp_categorization_routes.db") as db:
        db.list_mcp_tag_vocabulary.return_value = rows
        first = client.get("/v1/mcp/acme/tags", params={"limit": 2, "offset": 4})
        over = client.get("/v1/mcp/acme/tags", params={"limit": 1001})
        deep = client.get("/v1/mcp/acme/tags", params={"offset": 10_001})
    assert [tag["tag"] for tag in first.json()["tags"]] == ["tag-0", "tag-1"]
    assert first.json()["has_more"] is True
    db.list_mcp_tag_vocabulary.assert_called_once_with(TENANT, limit=3, offset=4)
    assert over.status_code == 422 and deep.status_code == 422


@pytest.mark.parametrize("url", ["/v1/admin/document-store"])
def test_the_document_store_status_lists_a_bounded_number_of_tenant_buckets(url: str) -> None:
    seen: Dict[str, Any] = {}

    def describe(_db: Any, *, tenant_bucket_limit: Optional[int] = None) -> Dict[str, Any]:
        seen["limit"] = tenant_bucket_limit
        return {"tenantBuckets": [], "tenantBucketsTruncated": False}

    with patch("app.document_store_routes.describe_store", describe):
        assert client.get(url, params={"limit": 3}).status_code == 200
        assert seen["limit"] == 3
        assert client.get(url).status_code == 200
        assert seen["limit"] == 1000
        assert client.get(url, params={"limit": 1001}).status_code == 422
