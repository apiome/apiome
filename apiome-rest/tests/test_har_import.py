"""HAR capture import — MFI-32.2 (#4404).

Covers the noise filter (:mod:`app.har_filters`), the reader (:mod:`app.har_parser`), the
normalizer (:mod:`app.har_normalizer`) and the adapter (:mod:`app.har_import_source`) against the
acceptance criteria:

* a devtools HAR of a REST app imports as a catalog item with **inferred operations and schemas**
  (through the shared MFI-32.1 engine: repeated calls cluster into ``{param}`` paths);
* **assets are excluded** — documents, scripts, stylesheets, fonts, images, analytics beacons, CORS
  preflights and non-HTTP URLs — and the filter is user-tunable (``har_keep_noise``,
  ``har_include``, ``har_exclude``);
* **one artifact per host**: the host with the most API calls by default, or ``har_hosts``;
* **no header or cookie secret survives to storage** — not in the canonical model, the coverage
  manifest, or the stored source (the scrub gate's cookie-jar rule);
* the format pill reads ``HAR (inferred)``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app import import_source_pipeline
from app.canonical_model import CanonicalApi, MessageRole, ParameterLocation
from app.canonical_security import declared_security_schemes
from app.fileset import IntakeFileset
from app.har_filters import (
    ANALYTICS,
    CORS_PREFLIGHT,
    NON_HTTP,
    STATIC_ASSET,
    HarOptions,
    HarOptionsError,
    classify_entry,
    is_browser_header,
)
from app.har_normalizer import AUTH_EXTRAS_KEY, HAR_EXTRAS_KEY, LIMIT_LOCATION_CAP
from app.har_parser import HarParseError, is_har, parse_har_fileset, parse_har_text
from app.import_preview_manifest import build_import_preview_manifest
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    detect_import_source,
    get_import_source,
    load_builtin_import_sources,
)
from app.import_source_pipeline import ImportRunArtifacts, _ResolvedIntake, scrub_intake_source
from app.inference_provenance import INFERRED, provenance_of
from app.intake_secret_scrub import COOKIE_JAR_SECRET_TYPE, REDACTION_MARKER, scrub_document_text

load_builtin_import_sources()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "har"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _adapter(options: Optional[Dict[str, Any]] = None):
    adapter = get_import_source("har")
    return adapter.configure(options) if options else adapter


def _example(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


def _import(text: str, options: Optional[Dict[str, Any]] = None) -> CanonicalApi:
    adapter = _adapter(options)
    return adapter.normalize(adapter.parse(text, source_label="capture.har"))


def _operations(api: CanonicalApi) -> Dict[str, Any]:
    return {op.key: op for service in api.services for op in service.operations}


def _entry(
    method: str,
    url: str,
    *,
    status: int = 200,
    body: Any = None,
    mime: str = "application/json",
    resource: Optional[str] = "fetch",
    headers: Optional[List[Dict[str, str]]] = None,
    cookies: Optional[List[Dict[str, str]]] = None,
    post: Optional[Dict[str, Any]] = None,
    query: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """One HAR 1.2 entry with only the fields the reader looks at (plus the required ones)."""
    text = body if isinstance(body, str) or body is None else json.dumps(body)
    entry: Dict[str, Any] = {
        "startedDateTime": "2026-10-25T09:00:00.000Z",
        "time": 10,
        "request": {
            "method": method,
            "url": url,
            "httpVersion": "h2",
            "headers": headers or [],
            "queryString": query if query is not None else [],
            "cookies": cookies or [],
            "headersSize": -1,
            "bodySize": 0,
        },
        "response": {
            "status": status,
            "statusText": "",
            "httpVersion": "h2",
            "headers": [],
            "cookies": [],
            "content": {"size": len(text or ""), "mimeType": mime, **({"text": text} if text is not None else {})},
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": -1,
        },
        "cache": {},
        "timings": {"send": 0, "wait": 10, "receive": 0},
    }
    if resource is not None:
        entry["_resourceType"] = resource
    if post is not None:
        entry["request"]["postData"] = post
    return entry


def _har(entries: List[Dict[str, Any]], *, version: Optional[str] = "1.2") -> str:
    log: Dict[str, Any] = {"creator": {"name": "WebInspector", "version": "537.36"}, "entries": entries}
    if version is not None:
        log["version"] = version
    return json.dumps({"log": log}, indent=2)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detect_claims_a_har_1_2_capture_with_confidence() -> None:
    result = _adapter().detect(DetectionInput(text=_example("02-typical-devtools-crud.har")))
    assert result.matched and result.format == "har" and result.confidence >= 0.95


def test_detect_claims_har_1_1_and_unversioned_captures() -> None:
    assert _adapter().detect(DetectionInput(text=_example("07-firefox-har-1.1-todos.har"))).confidence >= 0.95
    unversioned = _adapter().detect(DetectionInput(text=_har([], version=None)))
    assert unversioned.matched and 0.8 <= unversioned.confidence < 0.95


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[1, 2]",
        json.dumps({"log": "text"}),
        json.dumps({"log": {"entries": {}}}),
        _example("negative/04-wrong-format-postman.json"),
    ],
)
def test_detect_ignores_what_is_not_a_capture(text: str) -> None:
    assert not _adapter().detect(DetectionInput(text=text)).matched


def test_registry_detection_picks_har_for_every_valid_fixture() -> None:
    for path in sorted(_EXAMPLES.glob("0*.har")):
        adapter, result = detect_import_source(DetectionInput(text=path.read_text(encoding="utf-8")))
        assert adapter is not None and adapter.key == "har", path.name
        assert result.confidence >= 0.9


def test_shape_predicate() -> None:
    assert is_har({"log": {"entries": []}})
    assert not is_har({"log": {}})
    assert not is_har({"info": {}, "item": []})


def test_descriptor_is_the_inferred_format_pill() -> None:
    descriptor = _adapter().descriptor()
    assert descriptor.label == "HAR (inferred)"
    assert ".har" in descriptor.file_extensions


# ---------------------------------------------------------------------------
# Noise filter
# ---------------------------------------------------------------------------


def _classify(method: str = "GET", url: str = "https://api.example.com/v1/x", **kw: Any) -> Optional[str]:
    scheme, rest = url.split("://", 1)
    host, _, path = rest.partition("/")
    return classify_entry(
        method=method,
        scheme=scheme,
        host=host,
        path="/" + path,
        resource_type=kw.get("resource_type"),
        response_media_type=kw.get("media_type"),
    )


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"url": "data://image/png"}, NON_HTTP),
        ({"url": "wss://api.example.com/live"}, NON_HTTP),
        ({"url": "chrome-extension://abc/content.js"}, NON_HTTP),
        ({"method": "OPTIONS"}, CORS_PREFLIGHT),
        ({"url": "https://www.google-analytics.com/g/collect"}, ANALYTICS),
        ({"url": "https://o0.ingest.sentry.io/api/1/envelope/"}, ANALYTICS),
        ({"resource_type": "script"}, STATIC_ASSET),
        ({"resource_type": "image"}, STATIC_ASSET),
        ({"url": "https://app.example.com/assets/main.4f2a.js"}, STATIC_ASSET),
        ({"url": "https://app.example.com/app.js.map"}, STATIC_ASSET),
        ({"url": "https://app.example.com/fonts/Inter.WOFF2"}, STATIC_ASSET),
        ({"media_type": "text/html; charset=utf-8"}, STATIC_ASSET),
        ({"media_type": "image/svg+xml"}, STATIC_ASSET),
        ({"media_type": "font/woff2"}, STATIC_ASSET),
    ],
)
def test_classify_names_the_noise(kwargs: Dict[str, Any], reason: str) -> None:
    assert _classify(**kwargs) == reason


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"resource_type": "fetch", "media_type": "application/json"},
        {"resource_type": "xhr", "media_type": "application/problem+json"},
        {"resource_type": "eventsource", "media_type": "text/event-stream"},
        {"url": "https://api.example.com/v1/report.csv", "media_type": "text/csv"},
        {"url": "https://api.example.com/v1.2/users", "media_type": "application/json"},
        {"url": "https://analytics.example.com/v1/reports"},
    ],
)
def test_classify_keeps_api_calls(kwargs: Dict[str, Any]) -> None:
    assert _classify(**kwargs) is None


@pytest.mark.parametrize("name", [":authority", "User-Agent", "sec-fetch-mode", "Accept-Language", "referer"])
def test_browser_headers_are_recognized(name: str) -> None:
    assert is_browser_header(name)


@pytest.mark.parametrize("name", ["Authorization", "X-Api-Key", "Content-Type", "X-Request-Id", "Cookie"])
def test_client_headers_are_not_browser_headers(name: str) -> None:
    assert not is_browser_header(name)


def test_typical_capture_excludes_assets_analytics_and_preflights() -> None:
    api = _import(_example("02-typical-devtools-crud.har"))
    record = api.extras[HAR_EXTRAS_KEY]
    assert record["excluded"] == {ANALYTICS: 1, CORS_PREFLIGHT: 1, STATIC_ASSET: 5}
    assert record["entries"] == 16 and record["api_calls"] == 9
    paths = {op.http_path for op in _operations(api).values()}
    assert not any(path.endswith((".js", ".css", ".ico", ".woff2")) or path == "/" for path in paths)


def test_keep_noise_keeps_assets_but_never_non_http() -> None:
    api = _import(_example("04-stress-mixed-capture.har"), {"har_keep_noise": True})
    record = api.extras[HAR_EXTRAS_KEY]
    # The Sentry and Segment calls are no longer noise — they are now API calls to other hosts.
    assert record["excluded"] == {NON_HTTP: 3, "unselected-host": 2}
    assert "GET /v1/app.js.map" in _operations(api)


def test_include_pattern_overrides_the_builtin_filter() -> None:
    text = _har(
        [
            _entry("GET", "https://api.example.com/v1/users/1", body={"id": 1}),
            _entry("GET", "https://api.example.com/v1/config.js", mime="text/javascript", body="x", resource="script"),
        ]
    )
    assert "GET /v1/config.js" not in _operations(_import(text))
    assert "GET /v1/config.js" in _operations(_import(text, {"har_include": ["api.example.com/v1/config.js"]}))


def test_exclude_pattern_drops_matches_and_beats_include() -> None:
    text = _har(
        [
            _entry("GET", "https://api.example.com/v1/users/1", body={"id": 1}),
            _entry("GET", "https://api.example.com/internal/metrics", body={"up": 1}),
        ]
    )
    options = {"har_exclude": ["*/internal/*"], "har_include": ["*/internal/*"]}
    api = _import(text, options)
    assert set(_operations(api)) == {"GET /v1/users/{id}"}
    assert api.extras[HAR_EXTRAS_KEY]["excluded"] == {"excluded-by-pattern": 1}
    assert api.extras[HAR_EXTRAS_KEY]["options"]["exclude"] == ["*/internal/*"]


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def test_options_accept_lists_and_comma_strings() -> None:
    options = HarOptions.from_mapping(
        {"har_hosts": "API.example.com, auth.example.com,", "har_include": ["*/v1/*"], "unrelated": 1}
    )
    assert options.hosts == ("api.example.com", "auth.example.com")
    assert options.include == ("*/v1/*",)
    assert not options.keep_noise


@pytest.mark.parametrize(
    "options",
    [{"har_hosts": 3}, {"har_include": [1]}, {"har_keep_noise": "yes"}, {"har_exclude": {"a": 1}}],
)
def test_options_with_the_wrong_shape_are_refused(options: Dict[str, Any]) -> None:
    with pytest.raises(HarOptionsError):
        HarOptions.from_mapping(options)
    with pytest.raises(ImportSourceError) as excinfo:
        _adapter().configure(options)
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"


def test_configure_returns_self_without_har_options_and_a_copy_with_them() -> None:
    adapter = get_import_source("har")
    assert adapter.configure({"dry_run": True}) is adapter
    configured = adapter.configure({"har_hosts": ["auth.example.io"]})
    assert configured is not adapter
    # The registry instance is untouched: a second import reads the default host again.
    assert adapter.parse(_example("05-real-world-dashboard.har")).title == "api.example.io"


# ---------------------------------------------------------------------------
# One artifact per host
# ---------------------------------------------------------------------------


def test_the_host_with_most_api_calls_is_imported_by_default() -> None:
    api = _import(_example("05-real-world-dashboard.har"))
    record = api.extras[HAR_EXTRAS_KEY]
    assert api.title == "api.example.io"
    assert [server.url for server in api.servers] == ["https://api.example.io"]
    assert {(host["host"], host["selected"]) for host in record["hosts"]} == {
        ("api.example.io", True),
        ("auth.example.io", False),
    }
    assert record["excluded"]["unselected-host"] == 2
    [limit] = [item for item in record["capability_limits"] if item["construct"] == "har.unselected_host"]
    assert limit["locations"] == ["auth.example.io/oauth/token", "auth.example.io/userinfo"]


def test_har_hosts_selects_another_host() -> None:
    api = _import(_example("05-real-world-dashboard.har"), {"har_hosts": ["auth.example.io"]})
    assert api.title == "auth.example.io"
    assert set(_operations(api)) == {"POST /oauth/token", "GET /userinfo"}


def test_har_hosts_can_combine_hosts() -> None:
    api = _import(_example("05-real-world-dashboard.har"), {"har_hosts": "api.example.io,auth.example.io"})
    assert api.title == "api.example.io, auth.example.io"
    assert {server.url for server in api.servers} == {"https://api.example.io", "https://auth.example.io"}
    assert "unselected-host" not in api.extras[HAR_EXTRAS_KEY]["excluded"]


def test_an_unknown_host_is_refused_with_the_hosts_available() -> None:
    with pytest.raises(ImportSourceError) as excinfo:
        _import(_example("05-real-world-dashboard.har"), {"har_hosts": ["cdn.example-static.net"]})
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"
    assert "api.example.io, auth.example.io" in str(excinfo.value)


def test_host_ties_go_to_the_alphabetically_first() -> None:
    text = _har(
        [
            _entry("GET", "https://b.example.com/v1/x", body={}),
            _entry("GET", "https://a.example.com/v1/y", body={}),
        ]
    )
    assert _import(text).title == "a.example.com"


def test_a_custom_port_is_part_of_the_host() -> None:
    api = _import(_example("07-firefox-har-1.1-todos.har"))
    assert api.title == "localhost:8080"
    assert [server.url for server in api.servers] == ["http://localhost:8080"]


# ---------------------------------------------------------------------------
# Inference (the shared engine)
# ---------------------------------------------------------------------------


def test_devtools_capture_imports_inferred_operations_and_schemas() -> None:
    api = _import(_example("02-typical-devtools-crud.har"))
    operations = _operations(api)
    assert set(operations) == {
        "GET /v1/users",
        "POST /v1/users",
        "GET /v1/users/{id}",
        "PATCH /v1/users/{id}",
        "DELETE /v1/users/{id}",
    }
    get_one = operations["GET /v1/users/{id}"]
    assert get_one.extras["sample_count"] == 4
    assert sorted(m.status_code for m in get_one.messages if m.role is MessageRole.RESPONSE) == ["200", "404"]
    listing = operations["GET /v1/users"]
    query = {p.name: p.required for p in listing.parameters if p.location is ParameterLocation.QUERY}
    assert query == {"limit": True, "page": True}
    create = operations["POST /v1/users"]
    [request] = [m for m in create.messages if m.role is MessageRole.REQUEST]
    assert request.content_types == ["application/json"]
    assert {t.name for t in api.types} >= {"PostUserRequest", "GetUserResponse200", "PostUserResponse201"}


def test_every_construct_is_stamped_inferred() -> None:
    api = _import(_example("02-typical-devtools-crud.har"))
    assert provenance_of(api.extras) == INFERRED
    for operation in _operations(api).values():
        assert provenance_of(operation.extras) == INFERRED
        for parameter in operation.parameters:
            assert provenance_of(parameter.extras) == INFERRED
    for typ in api.types:
        assert provenance_of(typ.extras) == INFERRED


def test_browser_headers_never_become_parameters() -> None:
    api = _import(_example("02-typical-devtools-crud.har"))
    headers = {
        p.name
        for op in _operations(api).values()
        for p in op.parameters
        if p.location is ParameterLocation.HEADER
    }
    assert headers <= {"authorization", "content-type"}
    assert not any(name.startswith((":", "sec-")) for name in headers)


def test_schemas_widen_across_samples() -> None:
    api = _import(_example("06-composition-sample-widening.har"))
    revisions = _operations(api)["GET /v1/articles/{id}/revisions/{id2}"]
    assert revisions.extras["sample_count"] == 3
    [typ] = [t for t in api.types if t.name == "GetRevisionResponse200"]
    fields = {f.name: f for f in typ.fields}
    assert {"id", "title", "author", "tags", "rating", "draft"} <= set(fields)
    assert fields["rating"].type.name == "number"
    comments = _operations(api)["GET /v1/articles/{id}/comments"]
    [cursor] = [p for p in comments.parameters if p.name == "cursor"]
    assert cursor.required is False


def test_stress_capture_reads_every_entry_shape() -> None:
    api = _import(_example("04-stress-mixed-capture.har"))
    operations = _operations(api)
    assert "GET /v1/files/{id}" in operations
    assert operations["GET /v1/files/{id}"].extras["sample_count"] == 2
    assert "GET /v1/users/{id}/orders/{id2}" in operations
    # A base64 response body is decoded before its schema is inferred.
    blob = operations["GET /v1/blobs/{id}"]
    assert any(m.payload is not None for m in blob.messages if m.role is MessageRole.RESPONSE)
    # Form and multipart bodies keep their media type (no JSON schema to infer).
    assert operations["POST /v1/forms/contact"].extras.get("har_auth") is None
    # A blocked request (status 0) has no response; a 304 has no body.
    assert not [m for m in operations["GET /v1/notifications"].messages if m.role is MessageRole.RESPONSE]
    record = api.extras[HAR_EXTRAS_KEY]
    assert record["excluded"] == {ANALYTICS: 2, NON_HTTP: 3, STATIC_ASSET: 1}


def test_a_fileset_of_sessions_imports_as_one_api() -> None:
    folder = _EXAMPLES / "03-multi-session"
    members = {path.name: path.read_text(encoding="utf-8") for path in folder.glob("*.har")}
    members["README.md"] = "# notes"
    adapter = _adapter()
    api = adapter.normalize(
        adapter.parse_fileset(IntakeFileset.from_members(members, root="session-1-browse.har"))
    )
    assert set(_operations(api)) == {
        "GET /v2/orders",
        "GET /v2/orders/ord_1001",
        "POST /v2/orders/ord_1001/checkout",
    }
    files = {f for op in _operations(api).values() for f in op.extras["source_files"]}
    assert files == {"session-1-browse.har", "session-2-checkout.har"}


def test_a_fileset_without_a_capture_is_a_format_mismatch() -> None:
    with pytest.raises(HarParseError) as excinfo:
        parse_har_fileset({"notes.md": "# x"}, root="notes.md")
    assert excinfo.value.code == "FORMAT_MISMATCH"


def test_auth_schemes_are_recorded_per_operation() -> None:
    api = _import(_example("05-real-world-dashboard.har"))
    operation = _operations(api)["GET /v3/projects"]
    assert operation.extras["security"] == ["bearer"]
    assert operation.extras[AUTH_EXTRAS_KEY] == [{"scheme": "bearer"}]
    assert "bearer" in declared_security_schemes(api)
    todos = _import(_example("07-firefox-har-1.1-todos.har"))
    assert _operations(todos)["GET /api/todos"].extras["security"] == ["apiKey"]


def test_import_is_deterministic() -> None:
    text = _example("05-real-world-dashboard.har")
    assert _import(text).model_dump_json() == _import(text).model_dump_json()


def test_limit_locations_are_capped_but_every_entry_counted() -> None:
    assets = [
        _entry("GET", f"https://app.example.com/img/{n}.png", mime="image/png", resource="image")
        for n in range(LIMIT_LOCATION_CAP + 5)
    ]
    api = _import(_har([*assets, _entry("GET", "https://api.example.com/v1/x", body={})]))
    limits = api.extras[HAR_EXTRAS_KEY]["capability_limits"]
    [limit] = [item for item in limits if item["construct"] == "har.static_asset"]
    assert limit["count"] == LIMIT_LOCATION_CAP + 5
    assert len(limit["locations"]) == LIMIT_LOCATION_CAP


def test_declared_limits_reach_the_coverage_ledger() -> None:
    api = _import(_example("05-real-world-dashboard.har"))
    manifest = build_import_preview_manifest(api, adapter_key="har")
    rows = {row.source_construct: row for row in manifest.document_coverage}
    assert rows["har.auth_credential"].coverage.value == "partially-mapped"
    assert rows["har.cookie"].coverage.value == "partially-mapped"
    assert rows["har.static_asset"].coverage.value == "not-parsed-by-adapter"
    assert rows["har.unselected_host"].detail.startswith("API calls to another host were left out")


# ---------------------------------------------------------------------------
# Acceptance: no header / cookie secret survives to storage
# ---------------------------------------------------------------------------

_BEARER = "hb-" + "bearer-0a1b2c3d4e5f60718293"
_API_KEY = "hk-" + "apikey-a1b2c3d4e5f6a7b8"
_SESSION = "hs-" + "sess-77aa"
_QUERY_TOKEN = "hq-" + "query-1234567890abcdef"
_FORM_PASSWORD = "hp-" + "pass-9988"
_BODY_PASSWORD = "hj-" + "json-pass-5566"
_USERINFO = "hu-" + "userinfo-3344"
_PLANTED = [_BEARER, _API_KEY, _SESSION, _QUERY_TOKEN, _FORM_PASSWORD, _BODY_PASSWORD, _USERINFO]


def _credential_capture() -> Dict[str, Any]:
    headers = [
        {"name": ":authority", "value": "api.example.com"},
        {"name": "authorization", "value": f"Bearer {_BEARER}"},
        {"name": "x-api-key", "value": _API_KEY},
        {"name": "cookie", "value": f"sid={_SESSION}; theme=dark"},
    ]
    login = _entry(
        "POST",
        f"https://svc:{_USERINFO}@api.example.com/v1/login",
        headers=headers,
        cookies=[{"name": "sid", "value": _SESSION}],
        post={"mimeType": "application/x-www-form-urlencoded", "text": f"user=ada&password={_FORM_PASSWORD}",
              "params": [{"name": "user", "value": "ada"}, {"name": "password", "value": _FORM_PASSWORD}]},
        body={"ok": True},
    )
    login["response"]["headers"] = [{"name": "set-cookie", "value": f"sid={_SESSION}; HttpOnly"}]
    login["response"]["cookies"] = [{"name": "sid", "value": _SESSION, "httpOnly": True}]
    search = _entry(
        "GET",
        f"https://api.example.com/v1/search?q=shoes&access_token={_QUERY_TOKEN}",
        headers=headers,
        query=[{"name": "q", "value": "shoes"}, {"name": "access_token", "value": _QUERY_TOKEN}],
        body={"hits": []},
    )
    profile = _entry(
        "PUT",
        "https://api.example.com/v1/profile",
        headers=headers,
        post={"mimeType": "application/json", "text": json.dumps({"name": "Ada", "password": _BODY_PASSWORD})},
        body={"name": "Ada"},
    )
    return {"log": {"version": "1.2", "creator": {"name": "WebInspector", "version": "537.36"},
                    "entries": [login, search, profile]}}


def test_no_secret_reaches_the_canonical_model() -> None:
    api = _import(json.dumps(_credential_capture()))
    stored = api.model_dump_json()
    for secret in _PLANTED:
        assert secret not in stored, f"{secret[:6]}… reached the canonical model"
    operations = _operations(api)
    # What is not a credential survives: the auth scheme, the header and parameter names.
    assert operations["GET /v1/search"].extras["security"] == ["bearer"]
    names = {p.name for p in operations["GET /v1/search"].parameters}
    assert {"q", "access_token", "authorization", "x-api-key", "cookie"} <= names
    assert [server.url for server in api.servers] == ["https://api.example.com"]
    record = api.extras[HAR_EXTRAS_KEY]
    constructs = {limit["construct"] for limit in record["capability_limits"]}
    assert {"har.auth_credential", "har.cookie"} <= constructs


def test_no_secret_reaches_the_coverage_manifest() -> None:
    api = _import(json.dumps(_credential_capture()))
    manifest = build_import_preview_manifest(api, adapter_key="har")
    rendered = repr(manifest.document_coverage) + repr(manifest.entity_rows) + repr(manifest.document_nodes)
    for secret in _PLANTED:
        assert secret not in rendered, f"{secret[:6]}… reached the coverage manifest"


@pytest.mark.parametrize("indent", [None, 2])
def test_no_secret_reaches_the_stored_source(indent: Optional[int]) -> None:
    """The shared scrub gate redacts the stored capture, cookie jars included."""
    text = json.dumps(_credential_capture(), indent=indent)
    intake = _ResolvedIntake(raw_bytes=text.encode("utf-8"), text=text, fileset=None, archive_root=None)
    fields, report = scrub_intake_source(intake)
    stored = fields["sourceContent"]
    assert report["scrubbed"] is True
    for secret in _PLANTED:
        assert secret not in stored, f"{secret[:6]}… persisted in the source"
        assert secret not in str(report)
    # The capture stays a readable HAR after redaction.
    assert is_har(json.loads(stored))
    assert "shoes" in stored


def test_the_gate_redacts_every_cookie_jar_value_whatever_its_name() -> None:
    jar = [{"name": "sid", "value": "abc]def"}, {"name": "theme", "value": "dark"}]
    text = json.dumps({"cookies": jar, "other": {"value": "kept"}})
    outcome = scrub_document_text(text, entropy_detection=False)
    document = json.loads(outcome.text)
    assert [cookie["value"] for cookie in document["cookies"]] == [REDACTION_MARKER, REDACTION_MARKER]
    assert document["other"]["value"] == "kept"
    assert {finding.secret_type for finding in outcome.findings} == {COOKIE_JAR_SECRET_TYPE}


def test_an_unterminated_cookie_jar_is_redacted_to_the_end() -> None:
    text = '{"cookies": [{"name": "sid", "value": "abcd"'
    assert "abcd" not in scrub_document_text(text, entropy_detection=False).text


def test_rest_import_options_carry_the_har_fields_to_the_adapter() -> None:
    """``SpecImportOptions`` declares the ``har_*`` fields, and its dump configures the adapter."""
    from app.models import SpecImportOptions

    defaults = json.loads(SpecImportOptions().model_dump_json())
    adapter = get_import_source("har")
    assert adapter.configure(defaults) is adapter
    assert HarOptions.from_mapping(defaults).is_default
    requested = SpecImportOptions(har_hosts=["auth.example.io"], har_exclude=["*/userinfo"], har_keep_noise=True)
    dumped = json.loads(requested.model_dump_json())
    options = HarOptions.from_mapping(dumped)
    assert options == HarOptions(hosts=("auth.example.io",), exclude=("*/userinfo",), keep_noise=True)


async def test_pipeline_dry_run_honours_har_hosts() -> None:
    """The import options reach the adapter through the pipeline's configure hook."""
    raw = _example("05-real-world-dashboard.har").encode("utf-8")
    payload = {
        "rest_job_id": "har-dry-run",
        "metadata": {
            "source_kind": "har",
            "project": {"name": "Dashboard", "slug": "dashboard"},
            "version": {"version_id": "0.0.1"},
            "options": {"dry_run": True, "har_hosts": ["auth.example.io"]},
        },
        "document_base64": base64.standard_b64encode(raw).decode("ascii"),
        "filename": "dashboard.har",
    }
    artifacts = ImportRunArtifacts()
    final = await import_source_pipeline.run_adapter_import_job(get_import_source("har"), payload, artifacts=artifacts)
    assert final.state == "completed", final.error
    assert artifacts.model is not None and artifacts.model.title == "auth.example.io"


# ---------------------------------------------------------------------------
# Taxonomy codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("negative/01-syntactic-missing-comma.har", "INPUT_MALFORMED"),
        ("negative/02-semantic-no-entries.har", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-entry.har", "INPUT_TRUNCATED"),
        ("negative/04-wrong-format-postman.json", "FORMAT_MISMATCH"),
        ("negative/06-semantic-assets-only.har", "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_negative_corpus_codes(name: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as excinfo:
        _import(_example(name))
    assert excinfo.value.code == code


def test_utf16_upload_is_an_encoding_fault() -> None:
    text = (_EXAMPLES / "negative/05-encoding-utf16.har").read_bytes().decode("utf-8", errors="replace")
    with pytest.raises(HarParseError) as excinfo:
        parse_har_text(text)
    assert excinfo.value.code == "INPUT_ENCODING_INVALID"


def test_an_all_noise_capture_says_how_to_keep_it() -> None:
    with pytest.raises(HarParseError) as excinfo:
        parse_har_text(_example("negative/06-semantic-assets-only.har"))
    assert "har_keep_noise" in str(excinfo.value) and "har_include" in str(excinfo.value)


@pytest.mark.parametrize(
    "document",
    [
        {"log": {"version": "1.2", "entries": {}}},
        {"log": {"version": "1.2", "entries": ["x"]}},
        {"log": {"version": "1.2", "entries": [{"request": {"method": "GET"}}]}},
        {"log": {"version": "1.2", "entries": [{"request": {"url": "https://a.example.com/"}}]}},
        {"log": {"version": "1.2", "entries": [{"request": {"method": "GET", "url": "http://[::1/x"}}]}},
    ],
)
def test_structural_faults_are_malformed(document: Dict[str, Any]) -> None:
    with pytest.raises(HarParseError) as excinfo:
        parse_har_text(json.dumps(document))
    assert excinfo.value.code == "INPUT_MALFORMED"


def test_normalize_rejects_a_foreign_ast() -> None:
    with pytest.raises(ImportSourceError):
        _adapter().normalize({"log": {}})
