"""Push an Avro export to a Confluent Schema Registry — MFX-19.4 (#3912).

Pinned here, against a fake registry speaking the Confluent API:

* the plan: one unit per ``.avsc`` subject, referenced schemas first with their full names, and a
  refusal for two schemas on one subject (``topic_name``);
* the push: register (with Confluent ``references``), already registered, incompatible (refused by the
  compatibility check, or by a ``409`` on register), failed, and skipped dependents; a dry run sends
  no write; credentials ride on every call and never come back in a message; the SSRF guard holds;
* the route ``POST /v1/export/{tenant}/avro/push``: the connector's kind, permission, credential and
  options are checked before any export runs, an invalid export pushes nothing, and a push that
  registered something is audited.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Mapping, Optional, Set
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.avro_registry_push import AvroPushError, AvroPushUnit, plan_avro_push, push_avro_subjects
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from app.config import settings
from app.emitter import EmitResult, coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_source import ExportSource
from app.export_validation import EmittedArtifactValidation
from app.main import app
from app.schema_registry_connector_source import SchemaRegistrySource

_TENANT = "550e8400-e29b-41d4-a716-446655440000"
_ACTOR = "11111111-1111-4111-8111-111111111111"
_CONNECTOR = "22222222-2222-4222-8222-222222222222"
_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_URL = "https://sr.example.test"
_CREDS = {"username": "svc-apiome", "password": "s3cret-pass"}
_ROUTE = "/v1/export/acme/avro/push"

_WIDGET = "acme.Widget-value"
_OWNER = "acme.Owner-value"
_COLOUR = "acme.Colour-value"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


@pytest.fixture(autouse=True)
def _ssrf(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ssrf_allow_private", True)


# ---------------------------------------------------------------------------
# A fake registry that accepts writes
# ---------------------------------------------------------------------------


class PushRegistry:
    """An in-memory Confluent registry: lookup, compatibility check and register.

    Args:
        subjects: ``{subject: [schema text, …]}`` already registered (version = index + 1).
        incompatible: Subjects whose compatibility check answers ``is_compatible: false``.
        conflict: Subjects whose register answers ``409`` (Confluent's incompatible-schema error).
        refuse: Subjects whose register answers ``422`` (invalid schema).
        basic: ``(username, password)`` every call must carry.
        version_on_register: Include ``version`` in the register answer (newer registries do).
    """

    def __init__(
        self,
        subjects: Optional[Dict[str, List[str]]] = None,
        *,
        incompatible: Set[str] = frozenset(),
        conflict: Set[str] = frozenset(),
        refuse: Set[str] = frozenset(),
        basic: Optional[tuple] = (_CREDS["username"], _CREDS["password"]),
        version_on_register: bool = False,
    ) -> None:
        self.subjects: Dict[str, List[Dict[str, Any]]] = {
            s: [{"schema": text, "references": []} for text in texts] for s, texts in (subjects or {}).items()
        }
        self.ids: Dict[str, int] = {}
        self.incompatible = set(incompatible)
        self.conflict = set(conflict)
        self.refuse = set(refuse)
        self.basic = basic
        self.version_on_register = version_on_register
        self.requests: List[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def calls(self) -> List[str]:
        """``METHOD path`` of every request, decoded."""
        return [f"{r.method} {unquote(r.url.raw_path.decode().split('?', 1)[0])}" for r in self.requests]

    def writes(self) -> List[str]:
        return [c for c in self.calls() if c.endswith("/versions")]

    def _id(self, text: str) -> int:
        return self.ids.setdefault(text, 100 + len(self.ids))

    @staticmethod
    def _error(status: int, code: int, message: str) -> httpx.Response:
        return httpx.Response(status, json={"error_code": code, "message": message})

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.basic is not None:
            expected = base64.b64encode(f"{self.basic[0]}:{self.basic[1]}".encode()).decode()
            if request.headers.get("authorization") != f"Basic {expected}":
                return self._error(401, 40101, f"Unauthorized: bad password {self.basic[1]}")
        parts = [unquote(p) for p in request.url.raw_path.decode().split("?", 1)[0].strip("/").split("/")]
        body = json.loads(request.content or b"{}")
        text, references = body.get("schema"), body.get("references") or []
        if request.method != "POST":
            return self._error(405, 405, "Method not allowed")
        if parts[0] == "compatibility" and parts[1] == "subjects":
            subject = parts[2]
            if subject not in self.subjects:
                return self._error(404, 40401, f"Subject '{subject}' not found.")
            if subject in self.incompatible:
                return httpx.Response(200, json={"is_compatible": False,
                                                 "messages": ["READER_FIELD_MISSING_DEFAULT_VALUE: id"]})
            return httpx.Response(200, json={"is_compatible": True})
        if parts[0] == "subjects" and len(parts) == 2:
            versions = self.subjects.get(parts[1])
            if versions is None:
                return self._error(404, 40401, f"Subject '{parts[1]}' not found.")
            for index, entry in enumerate(versions):
                if entry["schema"] == text and entry["references"] == references:
                    return httpx.Response(200, json={"subject": parts[1], "id": self._id(text),
                                                     "version": index + 1, "schema": text})
            return self._error(404, 40403, "Schema not found")
        if parts[0] == "subjects" and len(parts) == 3 and parts[2] == "versions":
            subject = parts[1]
            if subject in self.conflict:
                return self._error(409, 409, "Schema being registered is incompatible with an earlier schema")
            if subject in self.refuse:
                return self._error(422, 42201, "Invalid schema")
            for ref in references:
                held = self.subjects.get(ref["subject"]) or []
                if not 1 <= ref["version"] <= len(held):
                    return self._error(422, 42201, f"Invalid reference {ref}")
            self.subjects.setdefault(subject, []).append({"schema": text, "references": references})
            answer: Dict[str, Any] = {"id": self._id(text)}
            if self.version_on_register:
                answer["version"] = len(self.subjects[subject])
            return httpx.Response(200, json=answer)
        return self._error(404, 404, "HTTP 404 Not Found")


def _connector(base_url: str = _URL, kind: str = "schema-registry") -> Dict[str, Any]:
    return {"id": _CONNECTOR, "tenant_id": _TENANT, "kind": kind, "name": "Prod registry",
            "base_url": base_url, "scope": {}, "status": "active"}


def _client(fake: PushRegistry, base_url: str = _URL, credentials: Optional[Dict[str, str]] = _CREDS):
    return SchemaRegistrySource(_connector(base_url), credentials, transport=fake.transport()).http_client()


# ---------------------------------------------------------------------------
# The model and its export
# ---------------------------------------------------------------------------


def _widgets() -> CanonicalApi:
    """``Widget`` (its ``owner`` an ``Owner``, its ``colour`` a ``Colour``), ``Owner`` and ``Colour``."""
    owner = Type(key="Owner", name="Owner", kind=TypeKind.RECORD,
                 fields=[CanonicalField(key="Owner.team", name="team", type=TypeRef(name="string"))])
    colour = Type(key="Colour", name="Colour", kind=TypeKind.ENUM,
                  enum_values=[EnumValue(key=f"Colour.{v}", name=v) for v in ("RED", "GREEN")])
    widget = Type(key="Widget", name="Widget", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string", nullable=False)),
        CanonicalField(key="Widget.owner", name="owner", type=TypeRef(name="Owner")),
        CanonicalField(key="Widget.colour", name="colour", type=TypeRef(name="Colour", nullable=False)),
    ])
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema",
                        identity=ApiIdentity(name="Widgets", namespace="acme"), types=[widget, owner, colour])


def _emit(**options: Any) -> EmitResult:
    emitter = get_emitter("avro")
    return emitter().emit(_widgets(), opts=coerce_emit_options(emitter, options))


def _units(**options: Any) -> List[AvroPushUnit]:
    return plan_avro_push(_emit(**options))


def _push(fake: PushRegistry, *, dry_run: bool = False, units: Optional[List[AvroPushUnit]] = None):
    with _client(fake) as client:
        return push_avro_subjects(client, _URL, units or _units(), dry_run=dry_run, credentials=_CREDS)


def _by_subject(results) -> Dict[str, Any]:
    return {r.subject: r for r in results}


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def test_the_plan_puts_referenced_schemas_first() -> None:
    units = _units()
    assert [u.subject for u in units] == [_COLOUR, _OWNER, _WIDGET]
    widget = units[-1]
    assert widget.record == "acme.Widget"
    assert list(widget.depends_on) == ["acme.Colour", "acme.Owner"]
    assert json.loads(widget.schema)["name"] == "Widget"
    assert units[0].depends_on == () and units[1].depends_on == ()


def test_the_plan_follows_the_subject_naming_strategy() -> None:
    units = _units(subject_naming="topic_record_name", topic="widgets", subject_role="key")
    assert [u.subject for u in units] == ["widgets-acme.Colour-key", "widgets-acme.Owner-key",
                                         "widgets-acme.Widget-key"]


def test_two_schemas_on_one_subject_are_refused() -> None:
    with pytest.raises(AvroPushError) as caught:
        _units(subject_naming="topic_name", topic="widgets")
    assert caught.value.code == "AVRO_PUSH_DUPLICATE_SUBJECT"
    assert "widgets-value" in caught.value.message


def test_an_export_with_no_schema_is_refused() -> None:
    with pytest.raises(AvroPushError) as caught:
        plan_avro_push(_emit().model_copy(update={"files": []}))
    assert caught.value.code == "AVRO_PUSH_EMPTY"


def test_a_file_with_no_subject_is_refused() -> None:
    result = _emit()
    files = [result.files[0].model_copy(update={"subject": None}), *result.files[1:]]
    with pytest.raises(AvroPushError) as caught:
        plan_avro_push(result.model_copy(update={"files": files}))
    assert caught.value.code == "AVRO_PUSH_NO_SUBJECT"


def test_relative_and_nested_names_resolve_in_their_namespace() -> None:
    """A relative name resolves in the enclosing namespace; a type defined inline is not a reference."""
    emit = _emit()
    widget = {"type": "record", "name": "Widget", "namespace": "acme", "fields": [
        {"name": "owner", "type": ["null", "Owner"]},
        {"name": "tags", "type": {"type": "array", "items": {"type": "map", "values": "acme.Colour"}}},
        {"name": "inline", "type": {"type": "record", "name": "Inline", "fields": [
            {"name": "self", "type": ["null", "Inline"]}]}},
    ]}
    files = [f.model_copy(update={"content": widget}) if f.subject == _WIDGET else f for f in emit.files]
    units = plan_avro_push(emit.model_copy(update={"files": files}))
    assert list(units[-1].depends_on) == ["acme.Colour", "acme.Owner"]


def test_a_reference_cycle_is_refused() -> None:
    emit = _emit()
    owner = {"type": "record", "name": "Owner", "namespace": "acme",
             "fields": [{"name": "widget", "type": "Widget"}]}
    files = [f.model_copy(update={"content": owner}) if f.subject == _OWNER else f for f in emit.files]
    with pytest.raises(AvroPushError) as caught:
        plan_avro_push(emit.model_copy(update={"files": files}))
    assert caught.value.code == "AVRO_PUSH_REFERENCE_CYCLE"


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------


def test_a_push_registers_every_subject_with_references() -> None:
    fake = PushRegistry()
    results = _by_subject(_push(fake))

    assert {s: r.status for s, r in results.items()} == {_COLOUR: "registered", _OWNER: "registered",
                                                        _WIDGET: "registered"}
    widget = results[_WIDGET]
    assert widget.compatibility == "new_subject" and widget.version == 1 and widget.schema_id is not None
    assert [r.model_dump() for r in widget.references] == [
        {"name": "acme.Colour", "subject": _COLOUR, "version": 1},
        {"name": "acme.Owner", "subject": _OWNER, "version": 1},
    ]
    assert fake.subjects[_WIDGET][0]["references"] == [r.model_dump() for r in widget.references]
    assert fake.writes() == [f"POST /subjects/{s}/versions" for s in (_COLOUR, _OWNER, _WIDGET)]


def test_the_version_from_the_register_answer_saves_a_lookup() -> None:
    fake = PushRegistry(version_on_register=True)
    results = _push(fake)
    assert all(r.version == 1 for r in results)
    assert fake.calls().count(f"POST /subjects/{_WIDGET}") == 1


def test_a_second_push_of_the_same_export_writes_nothing() -> None:
    fake = PushRegistry()
    first = _push(fake)
    writes = len(fake.writes())
    second = _push(fake)

    assert [r.status for r in second] == ["already_registered"] * 3
    assert [(r.schema_id, r.version) for r in second] == [(r.schema_id, r.version) for r in first]
    assert len(fake.writes()) == writes


def test_a_new_version_of_a_subject_is_checked_then_registered() -> None:
    fake = PushRegistry({_OWNER: ['{"type":"record","name":"Owner","namespace":"acme","fields":[]}']})
    owner = _by_subject(_push(fake))[_OWNER]
    assert owner.status == "registered" and owner.compatibility == "compatible" and owner.version == 2
    assert f"POST /compatibility/subjects/{_OWNER}/versions/latest" in fake.calls()
    assert fake.requests[fake.calls().index(f"POST /compatibility/subjects/{_OWNER}/versions/latest")].url.params[
        "verbose"] == "true"


def test_an_incompatible_schema_is_not_registered_and_its_dependents_are_skipped() -> None:
    fake = PushRegistry({_OWNER: ["{}"]}, incompatible={_OWNER})
    results = _by_subject(_push(fake))

    assert results[_OWNER].status == "incompatible"
    assert results[_OWNER].messages == ["READER_FIELD_MISSING_DEFAULT_VALUE: id"]
    assert results[_COLOUR].status == "registered"
    assert results[_WIDGET].status == "skipped"
    assert results[_WIDGET].messages == [f"Not pushed: referenced subject {_OWNER!r} did not register."]
    assert f"POST /subjects/{_OWNER}/versions" not in fake.writes()
    assert not any(c.startswith(f"POST /subjects/{_WIDGET}") for c in fake.calls())


def test_a_409_on_register_is_incompatible() -> None:
    results = _by_subject(_push(PushRegistry(conflict={_COLOUR})))
    assert results[_COLOUR].status == "incompatible" and results[_COLOUR].compatibility is None
    assert "409" in results[_COLOUR].messages[0]
    assert results[_WIDGET].status == "skipped"


def test_a_refused_schema_is_failed_with_the_registry_message() -> None:
    results = _by_subject(_push(PushRegistry(refuse={_OWNER})))
    assert results[_OWNER].status == "failed"
    assert results[_OWNER].messages == [
        f"The schema registry answered 422 to POST /subjects/{_OWNER}/versions: error_code 42201: Invalid schema"
    ]


def test_a_dry_run_checks_but_writes_nothing() -> None:
    fake = PushRegistry({_OWNER: ["{}"]})
    results = _by_subject(_push(fake, dry_run=True))

    assert fake.writes() == []
    assert results[_COLOUR].status == "would_register" and results[_COLOUR].compatibility == "new_subject"
    assert results[_OWNER].status == "would_register" and results[_OWNER].compatibility == "compatible"
    # Widget references schemas that are not registered yet: nothing the registry can check.
    widget = results[_WIDGET]
    assert widget.status == "would_register" and widget.compatibility == "unchecked"
    assert [r.version for r in widget.references] == [None, None]
    assert not any(c.startswith(f"POST /subjects/{_WIDGET}") for c in fake.calls())


def test_a_dry_run_after_a_push_reports_already_registered() -> None:
    fake = PushRegistry()
    _push(fake)
    assert [r.status for r in _push(fake, dry_run=True)] == ["already_registered"] * 3


def test_a_dry_run_reports_an_incompatible_schema() -> None:
    fake = PushRegistry({_COLOUR: ["{}"]}, incompatible={_COLOUR})
    results = _by_subject(_push(fake, dry_run=True))
    assert results[_COLOUR].status == "incompatible"
    assert results[_WIDGET].status == "skipped"


def test_every_call_carries_the_credentials_and_none_comes_back_in_a_message() -> None:
    fake = PushRegistry(basic=("svc-apiome", "other-password"))
    results = _push(fake)
    assert all(r.status == "failed" for r in results[:2])
    assert all("s3cret-pass" not in m and "other-password" in m for r in results[:2] for m in r.messages)

    fake = PushRegistry()
    _push(fake)
    expected = "Basic " + base64.b64encode(b"svc-apiome:s3cret-pass").decode()
    assert {r.headers["authorization"] for r in fake.requests} == {expected}


def test_a_registry_message_never_echoes_the_stored_password() -> None:
    fake = PushRegistry(basic=("svc-apiome", "s3cret-pass"))
    with _client(fake, credentials={"username": "svc-apiome", "password": "wrong"}) as client:
        results = push_avro_subjects(client, _URL, _units(), credentials={"password": "s3cret-pass"})
    assert results[0].status == "failed"
    assert "s3cret-pass" not in results[0].messages[0] and "[redacted]" in results[0].messages[0]


def test_the_ssrf_guard_refuses_a_private_registry(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ssrf_allow_private", False)
    fake = PushRegistry()
    with _client(fake, base_url="http://127.0.0.1:8081") as client:
        results = push_avro_subjects(client, "http://127.0.0.1:8081", _units())
    assert fake.requests == []
    assert results[0].status == "failed" and "refused" in results[0].messages[0]
    assert [r.status for r in results] == ["failed", "failed", "skipped"]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def _source() -> ExportSource:
    return ExportSource(api=_widgets(), artifact_id="artifact-1", version_record_id="rev-1", version_label="1.0.0")


class _Route:
    """The route's collaborators, faked: the connector, its credentials, the source and the database."""

    def __init__(self, fake: PushRegistry, connector: Optional[Mapping[str, Any]] = None,
                 unreadable: bool = False) -> None:
        self.fake = fake
        self.connector = dict(connector or _connector())
        self.unreadable = unreadable
        self.db = MagicMock()
        self.permission = MagicMock(return_value=_ACTOR)
        self.load = MagicMock(return_value=_source())

    def __enter__(self) -> TestClient:
        module = "app.avro_registry_push_routes"
        fake = self.fake
        self._patches = [
            patch(f"{module}.enforce_permission", self.permission),
            patch(f"{module}.db", self.db),
            patch(f"{module}.store.get_connector",
                  lambda db, tenant, cid: self.connector if cid == _CONNECTOR else None),
            patch(f"{module}.unseal_connector_credentials",
                  lambda db, cid: (None, True) if self.unreadable else (dict(_CREDS), False)),
            patch(f"{module}.load_export_source", self.load),
            patch(f"{module}.SchemaRegistrySource",
                  lambda c, creds: SchemaRegistrySource(c, creds, transport=fake.transport())),
        ]
        for p in self._patches:
            p.start()
        app.dependency_overrides[validate_authentication] = lambda: _AUTH
        return TestClient(app)

    def __exit__(self, *exc: Any) -> None:
        app.dependency_overrides.clear()
        for p in reversed(self._patches):
            p.stop()


def _body(**overrides: Any) -> Dict[str, Any]:
    return {"artifact": "artifact-1", "version": "1.0.0", "connector_id": _CONNECTOR, **overrides}


def test_the_route_pushes_and_audits() -> None:
    route = _Route(PushRegistry())
    with route as client:
        response = client.post(_ROUTE, json=_body())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["registry_url"] == _URL and body["connector_id"] == _CONNECTOR and body["dry_run"] is False
    assert body["version_record_id"] == "rev-1" and body["version_label"] == "1.0.0"
    assert body["summary"] == {"registered": 3, "already_registered": 0, "would_register": 0,
                               "incompatible": 0, "failed": 0, "skipped": 0}
    assert [s["subject"] for s in body["subjects"]] == [_COLOUR, _OWNER, _WIDGET]
    route.permission.assert_called_once()
    assert route.permission.call_args.args[2:] == ("imports", "edit")
    route.load.assert_called_once_with(_TENANT, "artifact-1", "1.0.0")
    audit = route.db.insert_workflow_audit.call_args.args
    assert audit[3] == "export.avro.pushed" and audit[5] == _ACTOR
    assert audit[6]["subjects"] == [_COLOUR, _OWNER, _WIDGET] and audit[6]["connectorId"] == _CONNECTOR


def test_the_route_dry_run_writes_nothing_and_is_not_audited() -> None:
    route = _Route(PushRegistry())
    with route as client:
        body = client.post(_ROUTE, json=_body(dry_run=True)).json()
    assert body["dry_run"] is True and body["summary"]["would_register"] == 3
    assert route.fake.writes() == []
    route.db.insert_workflow_audit.assert_not_called()


def test_the_route_passes_the_avro_options() -> None:
    route = _Route(PushRegistry())
    with route as client:
        body = client.post(_ROUTE, json=_body(
            options={"subject_naming": "topic_record_name", "topic": "widgets"})).json()
    assert [s["subject"] for s in body["subjects"]][0] == "widgets-acme.Colour-value"


@pytest.mark.parametrize(("options", "code"), [
    ({"subject_naming": "topic_name", "topic": "widgets"}, "AVRO_PUSH_DUPLICATE_SUBJECT"),
    ({"output_syntax": "avdl"}, "AVRO_PUSH_NOT_AVSC"),
])
def test_the_route_refuses_options_a_registry_cannot_take(options: Dict[str, Any], code: str) -> None:
    route = _Route(PushRegistry())
    with route as client:
        response = client.post(_ROUTE, json=_body(options=options))
    assert response.status_code == 422 and response.json()["detail"]["code"] == code
    assert route.fake.requests == []


def test_the_route_refuses_another_kind_of_connector() -> None:
    route = _Route(PushRegistry(), connector=_connector(kind="kong"))
    with route as client:
        response = client.post(_ROUTE, json=_body())
    assert response.status_code == 422 and response.json()["detail"]["code"] == "AVRO_PUSH_CONNECTOR_KIND"
    route.load.assert_not_called()


def test_the_route_answers_404_for_an_unknown_connector() -> None:
    route = _Route(PushRegistry())
    with route as client:
        response = client.post(_ROUTE, json=_body(connector_id="33333333-3333-4333-8333-333333333333"))
    assert response.status_code == 404 and response.json()["detail"]["code"] == "AVRO_PUSH_CONNECTOR_NOT_FOUND"


def test_the_route_refuses_an_unreadable_credential() -> None:
    route = _Route(PushRegistry(), unreadable=True)
    with route as client:
        response = client.post(_ROUTE, json=_body())
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "AVRO_PUSH_CREDENTIALS_UNREADABLE"
    route.load.assert_not_called()


def test_the_route_refuses_without_permission() -> None:
    route = _Route(PushRegistry())
    route.permission.side_effect = HTTPException(status_code=403, detail="Forbidden")
    with route as client:
        response = client.post(_ROUTE, json=_body())
    assert response.status_code == 403
    assert route.fake.requests == []


def test_an_export_that_fails_its_check_pushes_nothing() -> None:
    async def failing(*args: Any, **kwargs: Any) -> EmittedArtifactValidation:
        return EmittedArtifactValidation(target="avro", applicable=True, validated=True, valid=False,
                                         errors=["acme/Widget.avsc: Invalid Avro schema"])

    route = _Route(PushRegistry())
    with route as client, patch("app.avro_registry_push_routes.validate_emitted_artifact", failing):
        response = client.post(_ROUTE, json=_body())
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "EMITTED_ARTIFACT_INVALID"
    assert route.fake.requests == []
