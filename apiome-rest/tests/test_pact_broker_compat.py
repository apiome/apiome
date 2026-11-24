"""The Pact Broker compatibility catalog and its 501s — PFX-1.8 (#6921).

The catalog (:mod:`app.pact_broker_compat`) is what the compatibility page and every 501 say, so
these tests hold it to the app:

* every method it calls supported is a real route of the app, and every Pact Broker route of the
  app is in it — so a new route cannot ship undocumented, nor a documented one go missing;
* each catalogued method resolves, through the app's own router, to a real route when supported and
  to the documented 501 when not — including ``…/latest/badge``, which a real template would
  otherwise read as the tag ``badge``;
* a 501 names the endpoint, its status, the tracking issue, the Apiome alternative and the page,
  needs authentication, and a path that is no Pact Broker resource gets one too, never a 404.
"""

from __future__ import annotations

import re
from typing import Iterator, List, Optional, Tuple

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Match

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_broker_compat import (
    BROKER_PREFIX,
    ENDPOINTS,
    GROUPS,
    NOT_PLANNED,
    PACT_BROKER_VERSION,
    PARTIAL,
    PLANNED,
    SUPPORTED,
    BrokerEndpoint,
    compatibility_url,
    find_endpoint,
    normalise_path,
    status_counts,
)
from app.pact_broker_compat_routes import CODE_NOT_IMPLEMENTED, pact_broker_not_implemented

client = TestClient(app)

_BASE = "/v1/tenants/acme/pact-broker"
_AUTH = {"tenant_id": "11111111-1111-4111-8111-111111111111", "user_id": "u", "auth_method": "api_key"}


@pytest.fixture
def authenticated() -> Iterator[None]:
    """Every Pact Broker request authenticates as a member of the tenant."""
    app.dependency_overrides[validate_broker_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_broker_authentication, None)


def _broker_routes() -> List[APIRoute]:
    """The app's real Pact Broker routes — the 501 routes and the trailing-slash index aside."""
    prefix = BROKER_PREFIX
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and (route.path == prefix or route.path.startswith(prefix + "/"))
        and route.endpoint is not pact_broker_not_implemented
        and route.path != prefix + "/"
    ]


def _sample(path: str) -> str:
    """A concrete request path for a catalog template (each placeholder becomes one segment)."""
    return _BASE + re.sub(r"\{[^}]+\}", "x1", path)


def _resolve(method: str, path: str) -> Optional[APIRoute]:
    """The route the app's router hands a request to, as Starlette chooses it.

    Args:
        method: The request method.
        path: The request path.

    Returns:
        The first fully matching route, else the first path-only match, else ``None``.
    """
    scope = {"type": "http", "method": method, "path": path, "root_path": "", "headers": []}
    partial = None
    for route in app.router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return route  # type: ignore[return-value]
        if match == Match.PARTIAL and partial is None:
            partial = route
    return partial  # type: ignore[return-value]


def _catalogued_methods() -> Iterator[Tuple[BrokerEndpoint, str]]:
    for endpoint in ENDPOINTS:
        for method in endpoint.methods:
            yield endpoint, method


# ---------------------------------------------------------------------------------------------
# The catalog itself
# ---------------------------------------------------------------------------------------------


def test_each_endpoint_is_listed_once() -> None:
    paths = [normalise_path(endpoint.path) for endpoint in ENDPOINTS]
    duplicates = {path for path in paths if paths.count(path) > 1}
    assert duplicates == set()


def test_every_group_has_endpoints_and_the_statuses_add_up() -> None:
    assert {endpoint.group for endpoint in ENDPOINTS} == set(GROUPS)
    counts = status_counts()
    assert sum(counts.values()) == len(ENDPOINTS)
    assert all(counts[status] > 0 for status in (SUPPORTED, PARTIAL, PLANNED, NOT_PLANNED))


def test_status_follows_from_the_methods() -> None:
    full = BrokerEndpoint(group="Index", path="/a", title="a", methods=("GET",), supported=("GET",))
    part = BrokerEndpoint(group="Index", path="/b", title="b", methods=("GET", "PUT"), supported=("GET",))
    planned = BrokerEndpoint(group="Index", path="/c", title="c", methods=("GET",), tracking="#1")
    never = BrokerEndpoint(group="Index", path="/d", title="d", methods=("GET",), note="no")
    assert [full.status, part.status, planned.status, never.status] == [SUPPORTED, PARTIAL, PLANNED, NOT_PLANNED]
    assert part.unsupported == ("PUT",)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"methods": ("GET",), "supported": ("PUT",)}, "not within"),
        ({"methods": ("GET",), "group": "Nope", "note": "x"}, "unknown group"),
        ({"methods": ("GET",)}, "tracking issue or a note"),
    ],
)
def test_an_incoherent_entry_is_refused(kwargs: dict, message: str) -> None:
    fields = {"group": "Index", "path": "/x", "title": "x", **kwargs}
    with pytest.raises(ValueError, match=message):
        BrokerEndpoint(**fields)


def test_the_most_specific_entry_wins() -> None:
    badge = find_endpoint("/pacts/provider/p/consumer/c/latest/badge")
    tagged = find_endpoint("/pacts/provider/p/consumer/c/latest/prod")
    assert badge is not None and badge.path.endswith("/latest/badge")
    assert tagged is not None and tagged.path.endswith("/latest/{tag}")
    index = find_endpoint("")
    assert index is not None and index.path == "" and find_endpoint("/") is index
    assert find_endpoint("/no/such/thing") is None


# ---------------------------------------------------------------------------------------------
# The catalog and the app agree
# ---------------------------------------------------------------------------------------------


def test_every_supported_method_is_a_route_of_the_app() -> None:
    served = {
        (method, normalise_path(route.path[len(BROKER_PREFIX) :]))
        for route in _broker_routes()
        for method in route.methods
    }
    claimed = {(method, normalise_path(endpoint.path)) for endpoint in ENDPOINTS for method in endpoint.supported}
    assert claimed - served == set(), "the catalog claims routes the app does not have"


def test_every_pact_broker_route_of_the_app_is_catalogued_as_supported() -> None:
    claimed = {(method, normalise_path(endpoint.path)) for endpoint in ENDPOINTS for method in endpoint.supported}
    served = {
        (method, normalise_path(route.path[len(BROKER_PREFIX) :]))
        for route in _broker_routes()
        for method in route.methods
    }
    assert served - claimed == set(), "a Pact Broker route is missing from app/pact_broker_compat.py"


@pytest.mark.parametrize(
    "endpoint, method",
    list(_catalogued_methods()),
    ids=[f"{method} {endpoint.path or '/'}" for endpoint, method in _catalogued_methods()],
)
def test_each_catalogued_method_reaches_the_route_its_status_promises(endpoint: BrokerEndpoint, method: str) -> None:
    route = _resolve(method, _sample(endpoint.path))
    assert route is not None
    if method in endpoint.supported:
        assert route.endpoint is not pact_broker_not_implemented, f"{method} {endpoint.path} is shadowed by a 501"
        assert method in route.methods
    else:
        assert route.endpoint is pact_broker_not_implemented, f"{method} {endpoint.path} reaches {route.path}"


def test_the_501_routes_stay_out_of_the_openapi_document() -> None:
    paths = app.openapi()["paths"]
    assert not any("{rest" in path or path.endswith("/badge") for path in paths)


# ---------------------------------------------------------------------------------------------
# The 501 itself
# ---------------------------------------------------------------------------------------------


def test_a_missing_method_on_a_partial_endpoint_is_a_documented_501(authenticated: None) -> None:
    response = client.delete(f"{_BASE}/pacticipants/web")
    assert response.status_code == 501
    assert response.headers["link"] == f'<{compatibility_url()}>; rel="help"'
    detail = response.json()["detail"]
    assert detail == {
        "code": CODE_NOT_IMPLEMENTED,
        "message": detail["message"],
        "pointer": f"{_BASE}/pacticipants/web",
        "endpoint": "/pacticipants/{pacticipant}",
        "status": PARTIAL,
        "supported_methods": ["GET"],
        "tracking": "https://github.com/apiome/apiome/issues/6924",
        "alternative": "/v1/tenants/{tenant}/pacticipants/{pacticipant}",
        "documentation": "https://docs.apiome.dev/ship/pact-broker/compatibility",
        "pact_broker_version": PACT_BROKER_VERSION,
    }
    assert detail["message"].startswith("DELETE is not supported on “A pacticipant” (partial). Supported: GET.")


def test_a_broker_badge_points_at_the_public_badges(authenticated: None) -> None:
    response = client.get(f"{_BASE}/pacts/provider/api/consumer/web/latest/badge")
    assert response.status_code == 501
    detail = response.json()["detail"]
    assert detail["status"] == "not planned" and detail["supported_methods"] == []
    assert detail["alternative"].endswith("/pact-badges") and "tracking" not in detail


def test_a_badge_is_not_read_as_a_tag(authenticated: None) -> None:
    response = client.get(f"{_BASE}/pacts/provider/api/consumer/web/latest/badge")
    assert response.status_code == 501
    assert response.json()["detail"]["endpoint"].endswith("/latest/badge")


def test_a_method_the_broker_has_but_the_route_lacks_is_501_not_405(authenticated: None) -> None:
    response = client.patch(f"{_BASE}/pacts/provider/api/consumer/web/version/1.0.0", json={})
    assert response.status_code == 501
    assert response.json()["detail"]["supported_methods"] == ["GET", "PUT"]


def test_a_path_that_is_no_broker_resource_is_501_not_404(authenticated: None) -> None:
    response = client.get(f"{_BASE}/no/such/resource")
    assert response.status_code == 501
    detail = response.json()["detail"]
    assert "endpoint" not in detail and "status" not in detail
    assert detail["documentation"] == compatibility_url()
    assert "not part of the Pact Broker API" in detail["message"]


def test_a_not_planned_endpoint_explains_itself(authenticated: None) -> None:
    detail = client.get(f"{_BASE}/metrics").json()["detail"]
    assert detail["status"] == NOT_PLANNED and "tracking" not in detail
    assert "/v1/ops" in detail["message"]


def test_a_501_still_needs_a_credential() -> None:
    response = client.get(f"{_BASE}/webhooks")
    assert response.status_code == 401


def test_supported_routes_still_answer_and_other_routes_are_untouched(authenticated: None) -> None:
    # The index is served by its real route (its permission check runs, so a 403/200 — never 501).
    assert client.get(_BASE).status_code != 501
    # A path outside …/pact-broker keeps the app's ordinary 404.
    assert client.get("/v1/tenants/acme/no-such-surface").status_code == 404
