"""Secret scrubbing & environment mapping gate — MFI-32.5 (#4407).

The acceptance criteria, stated as tests over one seeded fixture per MFI-EPIC-32 format (Postman,
Insomnia, Bruno, HAR, ``.http``):

* **zero secret bytes persist** — not in the stored source (scanned after
  :func:`app.import_source_pipeline.scrub_intake_source`), not in the canonical model, not in the
  converted OpenAPI document — even when the tenant policy asks for warn-only with entropy off,
  because scrubbing is locked on for these formats;
* **auth appears as scheme stubs** — ``components.securitySchemes`` entries with a type and no
  material, and per-operation requirements only where the request declared auth;
* **environment names survive, values do not** — a secret variable keeps its name (and a
  ``baseUrl`` with no safe value becomes a ``{baseUrl}`` server variable);
* **the scrub report lists every redaction site** — line (and fileset member) per finding.

Every credential below is realistic in shape only and is assembled from fragments, so no
credential-shaped literal is committed.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import pytest
import yaml

from app.canonical_model import CanonicalApi
from app.client_collection import safe_named_value, variable_record
from app.emitter import get_emitter
from app.fileset import IntakeFileset
from app.import_source import get_import_source, load_builtin_import_sources
from app.import_source_pipeline import _ResolvedIntake, scrub_intake_source
from app.intake_scrub_policy import (
    LOCKED_FORMATS,
    MODE_WARN_ONLY,
    TIER_FORMAT_LOCKED,
    ScrubPolicy,
    resolve_scrub_mode,
)
from app.intake_secret_scrub import REDACTION_MARKER, ScrubFinding
from app.postman_normalizer import PostmanNormalizer
from app.postman_parser import parse_postman
from app.security_scheme_stubs import (
    SECURITY_SCHEMES_EXTRAS_KEY,
    STUB_DESCRIPTION,
    scheme_stub,
)

load_builtin_import_sources()

_JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiJhZGEifQ" + ".c2lnbmF0dXJl" + "LXNlZWRlZA"
_GITHUB = "gh" + "p_" + "Zq7Xw3Rt9Lp2Mn8Kv4Bc6Hd1Fs5Jg0Ae3Uy7"
_STRIPE = "sk" + "_live_" + "4eC39HqLyjWDarjtT1zdp7dc"
_SESSION = "s%3A" + "Qm9ndXMtc2Vzc2lvbi1zZWVkZWQ" + ".Xy9Kq2"

#: Every seeded credential: none of these may appear in anything persisted or emitted.
_SECRETS: Tuple[str, ...] = (_JWT, _GITHUB, _STRIPE, _SESSION)

_POSTMAN = json.dumps(
    {
        "info": {
            "name": "Seeded orders",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": _JWT, "type": "string"}]},
        "variable": [
            {"key": "baseUrl", "value": "https://api.example.com"},
            {"key": "apiKey", "value": _GITHUB},
        ],
        "item": [
            {
                "name": "List orders",
                "request": {
                    "method": "GET",
                    "header": [
                        {"key": "Authorization", "value": f"Bearer {_JWT}"},
                        {"key": "Cookie", "value": f"session={_SESSION}"},
                    ],
                    "url": {
                        "raw": f"{{{{baseUrl}}}}/orders?api_key={_STRIPE}",
                        "host": ["{{baseUrl}}"],
                        "path": ["orders"],
                        "query": [{"key": "api_key", "value": _STRIPE}],
                    },
                },
            },
            {
                "name": "Create order",
                "request": {
                    "method": "POST",
                    "auth": {"type": "apikey", "apikey": [
                        {"key": "key", "value": "X-Api-Key"},
                        {"key": "value", "value": _GITHUB},
                        {"key": "in", "value": "header"},
                    ]},
                    "header": [],
                    "url": {"raw": "{{baseUrl}}/orders", "host": ["{{baseUrl}}"], "path": ["orders"]},
                },
            },
        ],
    },
    indent=2,
)

_INSOMNIA = json.dumps(
    {
        "_type": "export",
        "__export_format": 4,
        "__export_date": "2026-10-25T09:00:00.000Z",
        "__export_source": "insomnia.desktop.app:v2023.5.8",
        "resources": [
            {"_id": "wrk_1", "parentId": None, "name": "Seeded", "_type": "workspace", "scope": "collection"},
            {
                "_id": "env_1",
                "parentId": "wrk_1",
                "name": "Base Environment",
                "_type": "environment",
                "data": {"baseUrl": "https://api.example.com", "accessToken": _JWT, "githubToken": _GITHUB},
            },
            {
                "_id": "req_1",
                "parentId": "wrk_1",
                "_type": "request",
                "name": "List orders",
                "method": "GET",
                "url": "{{ _.baseUrl }}/orders",
                "body": {},
                "parameters": [{"name": "api_key", "value": _STRIPE}],
                "headers": [{"name": "Cookie", "value": f"session={_SESSION}"}],
                "authentication": {"type": "bearer", "token": _JWT, "prefix": ""},
            },
        ],
    },
    indent=2,
)

_BRUNO = f"""meta {{
  name: List orders
  type: http
  seq: 1
}}

get {{
  url: https://api.example.com/orders?api_key={_STRIPE}
  body: none
  auth: bearer
}}

params:query {{
  api_key: {_STRIPE}
}}

headers {{
  Cookie: session={_SESSION}
  X-Github-Token: {_GITHUB}
}}

auth:bearer {{
  token: {_JWT}
}}
"""

_HAR = json.dumps(
    {
        "log": {
            "version": "1.2",
            "creator": {"name": "WebInspector", "version": "537.36"},
            "entries": [
                {
                    "startedDateTime": "2026-10-25T09:00:00.000Z",
                    "time": 12.0,
                    "request": {
                        "method": "GET",
                        "url": f"https://api.example.com/v1/orders?api_key={_STRIPE}",
                        "httpVersion": "HTTP/1.1",
                        "headers": [
                            {"name": "Authorization", "value": f"Bearer {_JWT}"},
                            {"name": "Cookie", "value": f"session={_SESSION}"},
                            {"name": "X-Github-Token", "value": _GITHUB},
                        ],
                        "queryString": [{"name": "api_key", "value": _STRIPE}],
                        "cookies": [{"name": "session", "value": _SESSION}],
                        "headersSize": -1,
                        "bodySize": 0,
                    },
                    "response": {
                        "status": 200,
                        "statusText": "OK",
                        "httpVersion": "HTTP/1.1",
                        "headers": [
                            {"name": "content-type", "value": "application/json"},
                            {"name": "Set-Cookie", "value": f"session={_SESSION}; Path=/; HttpOnly"},
                        ],
                        "cookies": [],
                        "content": {"size": 13, "mimeType": "application/json", "text": "{\"orders\":[]}"},
                        "redirectURL": "",
                        "headersSize": -1,
                        "bodySize": 13,
                    },
                    "cache": {},
                    "timings": {"send": 0, "wait": 11.5, "receive": 0.5},
                }
            ],
        }
    },
    indent=2,
)

_HTTP_FILE = f"""@host = https://api.example.com
@token = {_JWT}
@githubToken = {_GITHUB}

### List orders
GET {{{{host}}}}/orders?api_key={_STRIPE}
Authorization: Bearer {{{{token}}}}
Cookie: session={_SESSION}

### Create order
POST {{{{host}}}}/orders
Authorization: Bearer {_JWT}
Content-Type: application/json

{{"note": "seeded"}}
"""

#: format key → (seeded text, source label).
_FIXTURES: Dict[str, Tuple[str, str]] = {
    "postman": (_POSTMAN, "orders.postman_collection.json"),
    "insomnia": (_INSOMNIA, "insomnia-export.json"),
    "bruno": (_BRUNO, "list-orders.bru"),
    "har": (_HAR, "capture.har"),
    "http-file": (_HTTP_FILE, "orders.http"),
}

#: A tenant policy that asks for everything to be weakened — the locked formats must ignore it.
_WEAK_POLICY = ScrubPolicy(
    policy_version_id="55555555-5555-4555-8555-555555555555",
    version_number=3,
    content_fingerprint="fp-weak",
    mode=MODE_WARN_ONLY,
    entropy_detection=False,
    format_overrides={key: {"mode": MODE_WARN_ONLY} for key in sorted(LOCKED_FORMATS)},
)


def _normalize(format_key: str) -> CanonicalApi:
    text, label = _FIXTURES[format_key]
    adapter = get_import_source(format_key)
    return adapter.normalize(adapter.parse(text, source_label=label))


def _emit(format_key: str, api: CanonicalApi) -> Dict[str, Any]:
    emitter = get_emitter(format_key)
    assert emitter is not None
    content = emitter().emit(api).files[0].content
    return content if isinstance(content, dict) else yaml.safe_load(content)


def _leaked(blob: str) -> List[str]:
    return [secret for secret in _SECRETS if secret in blob]


def test_every_locked_format_has_a_seeded_fixture():
    assert set(_FIXTURES) == set(LOCKED_FORMATS)


# ---------------------------------------------------------------------------
# Stored source: zero secret bytes, every site reported
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("format_key", sorted(_FIXTURES))
def test_stored_source_holds_zero_secret_bytes_under_a_weakened_policy(format_key):
    text, _label = _FIXTURES[format_key]
    assert _leaked(text), "the fixture must actually carry the seeded secrets"
    resolution = resolve_scrub_mode(_WEAK_POLICY, format_key=format_key)

    fields, report = scrub_intake_source(
        _ResolvedIntake(raw_bytes=text.encode("utf-8"), text=text, fileset=None, archive_root=None),
        resolution,
    )

    assert _leaked(fields["sourceContent"]) == []
    assert REDACTION_MARKER in fields["sourceContent"]
    assert report["policy_tier"] == TIER_FORMAT_LOCKED
    assert report["applied"] is True


@pytest.mark.parametrize("format_key", sorted(_FIXTURES))
def test_scrub_report_lists_every_redaction_site(format_key):
    text, _label = _FIXTURES[format_key]
    fields, report = scrub_intake_source(
        _ResolvedIntake(raw_bytes=text.encode("utf-8"), text=text, fileset=None, archive_root=None),
        resolve_scrub_mode(_WEAK_POLICY, format_key=format_key),
    )

    lines = text.splitlines()
    seeded_lines = {index + 1 for index, line in enumerate(lines) if _leaked(line)}
    reported_lines = {finding["line"] for finding in report["findings"]}
    assert seeded_lines <= reported_lines
    assert report["redactions"] == sum(finding["occurrences"] for finding in report["findings"])
    # The report names types and sites, never a value.
    assert _leaked(json.dumps(report)) == []
    assert _leaked(json.dumps(fields)) == []


def test_archive_findings_name_their_member():
    members = {"orders/list-orders.bru": _BRUNO, "orders/bruno.json": json.dumps({"version": "1", "name": "o"})}
    intake = _ResolvedIntake(
        raw_bytes=b"zip-bytes-not-read",
        text=None,
        fileset=IntakeFileset.from_members(members, root="orders/bruno.json"),
        archive_root="orders/bruno.json",
    )

    fields, report = scrub_intake_source(intake, resolve_scrub_mode(_WEAK_POLICY, format_key="bruno"))

    assert fields["sourceContent"] is None
    assert report["source_withheld"] is True
    assert report["findings"]
    assert {finding["member"] for finding in report["findings"]} == {"orders/list-orders.bru"}


def test_a_finding_without_a_member_omits_the_key():
    assert ScrubFinding(secret_type="jwt", line=3).as_dict() == {"secret_type": "jwt", "line": 3, "occurrences": 1}
    assert ScrubFinding(secret_type="jwt", line=3, member="a.bru").as_dict()["member"] == "a.bru"


# ---------------------------------------------------------------------------
# Model and converted document: zero secret bytes, auth as stubs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("format_key", sorted(_FIXTURES))
def test_canonical_model_holds_zero_secret_bytes(format_key):
    api = _normalize(format_key)
    assert _leaked(api.model_dump_json()) == []


@pytest.mark.parametrize("format_key", sorted(_FIXTURES))
def test_auth_becomes_security_scheme_stubs(format_key):
    api = _normalize(format_key)
    stubs = api.extras.get(SECURITY_SCHEMES_EXTRAS_KEY)
    assert stubs, f"{format_key}: the seeded auth must produce at least one stub"
    assert "bearer" in stubs
    for stub in stubs.values():
        assert stub["description"] == STUB_DESCRIPTION
        assert set(stub) <= {"type", "scheme", "in", "name", "flows", "description"}


@pytest.mark.parametrize("format_key", sorted(_FIXTURES))
def test_converted_openapi_carries_stubs_and_no_secret(format_key):
    document = _emit("openapi-3.1", _normalize(format_key))
    blob = json.dumps(document)

    assert _leaked(blob) == []
    schemes = document["components"]["securitySchemes"]
    assert schemes["bearer"] == {"type": "http", "scheme": "bearer", "description": STUB_DESCRIPTION}
    for path_item in document["paths"].values():
        for operation in path_item.values():
            for requirement in operation.get("security", []):
                assert set(requirement) <= set(schemes)


def test_postman_operation_requirements_follow_the_request_auth():
    document = _emit("openapi-3.1", _normalize("postman"))
    schemes = document["components"]["securitySchemes"]
    assert schemes["apiKey"] == {"type": "apiKey", "in": "header", "name": "X-Api-Key", "description": STUB_DESCRIPTION}
    orders = document["paths"]["/orders"]
    assert orders["post"]["security"] == [{"apiKey": []}]
    # Collection-level auth is an observation (a stub), never a claim about one call.
    assert "security" not in orders["get"]


# ---------------------------------------------------------------------------
# Environment mapping: names survive, values do not
# ---------------------------------------------------------------------------


def test_postman_secret_variable_keeps_its_name_only():
    api = _normalize("postman")
    variables = {record["key"]: record for record in api.extras["postman_variables"]}
    assert variables["apiKey"] == {"key": "apiKey", "secret": True}
    assert variables["baseUrl"] == {"key": "baseUrl", "secret": False, "value": "https://api.example.com"}


def test_postman_export_writes_a_secret_variable_as_an_empty_placeholder():
    exported = _emit("postman", _normalize("postman"))
    variables = {record["key"]: record for record in exported["variable"]}
    assert variables["apiKey"] == {"key": "apiKey", "value": ""}
    assert "secret" not in json.dumps(exported["variable"])


def test_postman_base_url_without_a_safe_value_becomes_a_server_variable():
    collection = json.loads(_POSTMAN)
    collection["variable"][0]["value"] = f"https://svc:{_STRIPE}@api.example.com"
    api = PostmanNormalizer().normalize(parse_postman(json.dumps(collection)))

    assert [server.url for server in api.servers] == ["{baseUrl}"]
    assert [variable.name for variable in api.servers[0].variables] == ["baseUrl"]
    assert api.servers[0].variables[0].default is None
    assert _leaked(api.model_dump_json()) == []


def test_http_file_secret_variable_keeps_its_name_only():
    api = _normalize("http-file")
    variables = {record["key"]: record for record in api.extras["http_file_variables"]}
    assert variables["token"] == {"key": "token", "secret": True}
    assert variables["githubToken"] == {"key": "githubToken", "secret": True}
    assert variables["host"] == {"key": "host", "secret": False, "value": "https://api.example.com"}


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("Authorization", f"Bearer {_JWT}", f"Bearer {REDACTION_MARKER}"),
        ("Authorization", "Bearer {{token}}", "Bearer {{token}}"),
        ("apiKey", "{{apiKey}}", "{{apiKey}}"),
        ("apiKey", "plain-but-secret-named", REDACTION_MARKER),
        ("Accept", "application/json", "application/json"),
        ("X-Anything", None, None),
    ],
)
def test_safe_named_value(name, value, expected):
    assert safe_named_value(name, value) == expected


def test_variable_record_withholds_a_credential_found_by_value():
    record = variable_record("note", f"token is {_GITHUB}")
    assert record == {"key": "note", "secret": True}


# ---------------------------------------------------------------------------
# Stub shapes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scheme", "kwargs", "expected"),
    [
        ("bearer", {}, {"type": "http", "scheme": "bearer"}),
        ("basic", {}, {"type": "http", "scheme": "basic"}),
        ("digest", {}, {"type": "http", "scheme": "digest"}),
        ("oauth2", {}, {"type": "oauth2", "flows": {}}),
        ("apiKey", {}, {"type": "apiKey", "in": "header", "name": "X-API-Key"}),
        (
            "apiKey",
            {"key_name": "key", "key_location": "queryParams"},
            {"type": "apiKey", "in": "query", "name": "key"},
        ),
        ("cookie", {}, {"type": "apiKey", "in": "cookie", "name": "session"}),
        ("aws-sigv4", {}, {"type": "apiKey", "in": "header", "name": "Authorization"}),
    ],
)
def test_scheme_stub_shapes(scheme, kwargs, expected):
    assert scheme_stub(scheme, **kwargs) == {**expected, "description": STUB_DESCRIPTION}
