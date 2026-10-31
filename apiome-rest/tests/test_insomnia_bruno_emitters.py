"""Tests for the Insomnia and Bruno output modes — MFX-31.3 (#4291).

Exercises the ticket's acceptance criteria and the export → import round trip MFI-32.3 / MFI-32.4 owed:

* **Insomnia v4 export imports cleanly** — the document is an ``_type: export`` /
  ``__export_format: 4`` resource list (workspace, request groups, requests, base environment) whose
  every ``parentId`` resolves, that format detection claims firmly, and that the Insomnia import
  adapter reads back to the same call surface;
* **Bruno delivers a zip with ``bruno.json`` + per-request ``.bru`` files** — through the MFX-4.2
  bundle the export job serves, and the Bruno import adapter reads it back;
* **one implementation** — the ``insomnia`` / ``bruno`` targets and the Postman target's ``flavor``
  option write the same files and predict the same report;
* the client-collection guarantees: no credential value is written (each is a declared, empty
  variable), auth schemes re-import as the scheme written, and what the collection cannot carry is
  recorded — including declared responses, which neither client saves;
* the ``.bru`` writer: quoted keys, disabled entries, multi-line values, names the reader reserves;
* the round-trip matrix cells for the native and cross-client sources pass.
"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from typing import Any, Dict, List, Optional

import pytest
from corpus_adapter_support import valid_entries
from corpus_roundtrip import _import_entry
from test_client_collection_emitters import (
    AUTH_CASES,
    PLANTED,
    json_body,
    model,
    operation,
    param,
    surface,
)

from app.bru_lang import parse_bru
from app.bruno_emitter import BrunoEmitter, bru_dictionary, validate_bruno_export
from app.canonical_model import (
    Channel,
    Message,
    MessageRole,
    OperationKind,
    ParameterLocation,
    Server,
    Type,
    TypeKind,
)
from app.client_collection_emit import ClientCollectionFidelityRulePack
from app.emitter import (
    EmitOptionsError,
    EmitPreconditionError,
    coerce_emit_options,
    describe_emit_targets,
    get_emitter,
    load_builtin_emitters,
)
from app.export_job_engine import build_export_zip
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.hoppscotch_emitter import HoppscotchEmitter
from app.import_source import get_import_source, load_builtin_import_sources
from app.insomnia_emitter import InsomniaEmitter, validate_insomnia_export
from app.insomnia_parser import detect_insomnia
from app.lossiness import LossinessKind
from app.postman_emitter import PostmanEmitter
from app.roundtrip_matrix import production_emit_targets, reimport_emitted, run_roundtrip

TARGETS = ("insomnia", "bruno")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_import_sources()
    load_builtin_emitters()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def emit(api: Any, target: str, **options: Any) -> Any:
    """Emit ``api`` through the registered ``target`` emitter."""
    emitter = get_emitter(target)
    return emitter().emit(api, opts=coerce_emit_options(emitter, options) if options else None)


def reimport(result: Any, target: str) -> Any:
    """Re-import an emitted export through ``target``'s import adapter."""
    return reimport_emitted(
        get_import_source(target), result, multi_file=len(result.files) > 1, source_label="emitted"
    )


def members(result: Any) -> Dict[str, str]:
    """The emitted files' text, keyed by path."""
    return {emitted.path: emitted.content for emitted in result.files}


def insomnia_document(result: Any) -> Dict[str, Any]:
    """The one emitted Insomnia export, parsed."""
    (emitted,) = result.files
    return json.loads(emitted.content)


def resources(result: Any, kind: str) -> List[Dict[str, Any]]:
    """The Insomnia resources of one ``_type``."""
    return [resource for resource in insomnia_document(result)["resources"] if resource["_type"] == kind]


def all_text(result: Any) -> str:
    """Every emitted byte, joined."""
    return "\n".join(str(emitted.content) for emitted in result.files)


def client_entries() -> List[Any]:
    """Every valid Insomnia and Bruno corpus entry."""
    return [entry for entry in valid_entries() if entry.format in TARGETS]


def leaky() -> Any:
    """A model whose defaults, samples, body example and server all carry credentials."""
    key = "POST /login"
    return model(
        [
            operation(
                key,
                parameters=[
                    param(key, "X-API-Key", ParameterLocation.HEADER, default=PLANTED[0]),
                    param(key, "access_token", ParameterLocation.QUERY, extras={"samples": [PLANTED[2]]}),
                ],
                messages=[
                    json_body(
                        {
                            "type": "object",
                            "required": ["user", "password"],
                            "properties": {
                                "user": {"type": "string", "example": "ada"},
                                "password": {"type": "string", "example": PLANTED[1]},
                            },
                        }
                    )
                ],
                extras={"security": ["bearer"]},
            )
        ],
        servers=[Server(url=f"https://admin:{PLANTED[3]}@api.example.com")],
    )


# ---------------------------------------------------------------------------
# Registration and the Export Studio card
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", TARGETS)
def test_emitter_is_registered_under_the_import_adapter_key(target: str) -> None:
    emitter = get_emitter(target)
    assert emitter is not None and emitter.key == target and emitter.format == target
    assert get_import_source(target) is not None, "the round-trip matrix joins emit and import by key"
    assert target in {item.descriptor.key for item in production_emit_targets()}


@pytest.mark.parametrize("target,multi_file,options", [
    ("insomnia", False, {"indent", "folder_strategy", "example_depth"}),
    ("bruno", True, {"folder_strategy", "example_depth"}),
])
def test_target_is_enumerated_for_the_export_studio(target: str, multi_file: bool, options: set) -> None:
    card = {item.descriptor.key: item for item in describe_emit_targets()}[target]
    assert card.descriptor.multi_file is multi_file and card.descriptor.needs_toolchain is False
    assert set(card.options_schema["properties"]) == options
    profile = card.capability_profile
    assert (profile.operations, profile.events, profile.unions, profile.constraints) == (True, False, False, False)


@pytest.mark.parametrize("target", TARGETS)
def test_invalid_options_are_an_emit_options_error(target: str) -> None:
    with pytest.raises(EmitOptionsError):
        coerce_emit_options(get_emitter(target), {"folder_strategy": "by-color"})


@pytest.mark.parametrize("target", TARGETS)
def test_a_model_with_no_http_operation_refuses_to_emit(target: str) -> None:
    rpc = model([operation("GET /a")]).model_copy(update={"services": []})
    with pytest.raises(EmitPreconditionError):
        emit(rpc, target)


@pytest.mark.parametrize("target", TARGETS)
def test_output_is_deterministic(target: str) -> None:
    api = model([operation("GET /widgets", tags=["Widgets"]), operation("POST /widgets")])
    assert members(emit(api, target)) == members(emit(api, target))


# ---------------------------------------------------------------------------
# Insomnia v4 export
# ---------------------------------------------------------------------------


def test_insomnia_export_is_a_v4_resource_tree_that_detection_claims() -> None:
    api = model([operation("GET /widgets/{id}", tags=["Admin / Reports"], parameters=[
        param("GET /widgets/{id}", "id", ParameterLocation.PATH),
        param("GET /widgets/{id}", "q", ParameterLocation.QUERY, required=False),
    ])])
    result = emit(api, "insomnia")
    assert result.files[0].path == "Widgets_API.insomnia.json"
    document = insomnia_document(result)
    assert (document["_type"], document["__export_format"]) == ("export", 4)
    by_id = {resource["_id"]: resource for resource in document["resources"]}
    for resource in document["resources"]:
        assert resource["parentId"] is None or resource["parentId"] in by_id, "every parent resolves"
    (workspace,) = resources(result, "workspace")
    assert (workspace["name"], workspace["scope"]) == ("Widgets API", "collection")
    folders = {folder["name"]: folder for folder in resources(result, "request_group")}
    assert folders["Admin"]["parentId"] == workspace["_id"]
    assert folders["Reports"]["parentId"] == folders["Admin"]["_id"]
    (request,) = resources(result, "request")
    assert request["parentId"] == folders["Reports"]["_id"]
    assert request["url"] == "{{ _.baseUrl }}/widgets/:id"
    assert request["parameters"] == [{"name": "q", "value": "", "disabled": True}]
    (environment,) = resources(result, "environment")
    assert environment["data"] == {"baseUrl": "https://api.example.com/v1"}
    reason, confidence = detect_insomnia(result.files[0].content)
    assert confidence >= 0.97, reason


def test_insomnia_writes_auth_on_each_request_and_json_bodies() -> None:
    api = model([
        operation("POST /widgets", extras={"security": ["bearer"]}, messages=[json_body(
            {"type": "object", "required": ["name"], "properties": {"name": {"type": "string", "example": "w"}}}
        )]),
        operation("GET /widgets", extras={"security": ["bearer"]}),
    ])
    requests = {request["method"]: request for request in resources(emit(api, "insomnia"), "request")}
    for request in requests.values():
        assert request["authentication"] == {"type": "bearer", "token": "{{ _.accessToken }}", "prefix": ""}
    assert requests["POST"]["body"]["mimeType"] == "application/json"
    assert json.loads(requests["POST"]["body"]["text"]) == {"name": "w"}
    assert requests["GET"]["body"] == {}


# ---------------------------------------------------------------------------
# Bruno collection
# ---------------------------------------------------------------------------


def test_bruno_is_bruno_json_plus_one_bru_per_request_in_folders() -> None:
    api = model([
        operation("GET /widgets", tags=["Widgets"], parameters=[param("GET /widgets", "q", ParameterLocation.QUERY)]),
        operation(
            "GET /widgets/{id}", tags=["Widgets"], parameters=[param("GET /widgets/{id}", "id", ParameterLocation.PATH)]
        ),
        operation("GET /health"),
    ])
    files = members(emit(api, "bruno"))
    assert list(files)[0] == "bruno.json"
    assert json.loads(files["bruno.json"])["name"] == "Widgets API"
    assert set(files) == {
        "bruno.json",
        "Widgets/folder.bru",
        "Widgets/GET -widgets.bru",
        "Widgets/GET -widgets-id.bru",
        "GET -health.bru",
        "environments/Default.bru",
    }
    blocks = {block.name: block for block in parse_bru(files["Widgets/GET -widgets-id.bru"])}
    assert blocks["get"].values()["url"] == "{{baseUrl}}/widgets/:id"
    assert blocks["get"].values()["auth"] == "none"
    assert "id" in blocks["params:path"].values()
    assert parse_bru(files["Widgets/folder.bru"])[0].values()["name"] == "Widgets"
    environment = {block.name: block for block in parse_bru(files["environments/Default.bru"])}
    assert environment["vars"].values() == {"baseUrl": "https://api.example.com/v1"}


def test_bruno_is_delivered_as_a_zip_the_bruno_importer_reads() -> None:
    api = model([operation("GET /widgets", extras={"security": ["basic"]})])
    result = emit(api, "bruno")
    with zipfile.ZipFile(io.BytesIO(build_export_zip(result, "bruno"))) as bundle:
        names = set(bundle.namelist())
        unpacked = {name: bundle.read(name).decode("utf-8") for name in names if name != "manifest.json"}
    assert {"bruno.json", "collection.bru", "GET -widgets.bru", "environments/Default.bru"} <= names
    validate_bruno_export(unpacked)
    back = reimport(result, "bruno")
    assert [op.key for service in back.services for op in service.operations] == ["GET /widgets"]


def test_shared_auth_is_written_once_in_collection_bru() -> None:
    bearer = {"security": ["bearer"]}
    api = model([operation("GET /a", extras=bearer), operation("GET /b", extras=bearer)])
    files = members(emit(api, "bruno"))
    collection = {block.name: block for block in parse_bru(files["collection.bru"])}
    assert collection["auth"].values() == {"mode": "bearer"}
    assert collection["auth:bearer"].values() == {"token": "{{accessToken}}"}
    for path in ("GET -a.bru", "GET -b.bru"):
        assert {b.name: b for b in parse_bru(files[path])}["get"].values()["auth"] == "inherit"


def test_bru_dictionary_quotes_keys_disables_entries_and_spans_lines() -> None:
    text = bru_dictionary("headers", [("X-Plain", "1", True), ("a: b", "2", True), ("~odd", "3", True),
                                     ("X-Off", "4", False), ("X-Multi", "one\ntwo", True), ("X-Empty", "", True)])
    (block,) = parse_bru(text)
    assert block.values() == {"X-Plain": "1", "a: b": "2", "~odd": "3", "X-Multi": "one\ntwo", "X-Empty": ""}
    assert block.values(enabled_only=False)["X-Off"] == "4"


def test_names_the_reader_reserves_are_never_taken() -> None:
    api = model([
        operation("GET /a", tags=["environments"]),
        operation("GET /b").model_copy(update={"name": "collection"}),
    ])
    files = members(emit(api, "bruno"))
    assert "collection.bru" not in files and "collection-2.bru" in files
    assert "environments-2/folder.bru" in files
    back = reimport(emit(api, "bruno"), "bruno")
    assert sorted(op.key for service in back.services for op in service.operations) == ["GET /a", "GET /b"]


def test_a_method_bruno_has_no_block_for_is_a_loss() -> None:
    result = emit(model([operation("GET /a"), operation("QUERY /search")]), "bruno")
    assert any(loss.subject == "method-not-supported" and loss.pointer == "QUERY /search" for loss in result.losses)
    assert not any("query {" in content for content in members(result).values())


# ---------------------------------------------------------------------------
# One implementation: the Postman target's flavor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flavor", TARGETS)
def test_the_postman_flavor_writes_what_the_target_writes(flavor: str) -> None:
    api = model([operation("GET /widgets", tags=["Widgets"], extras={"security": ["apiKey"]})])
    assert members(emit(api, "postman", flavor=flavor)) == members(emit(api, flavor))
    by_flavor = compute_lossiness_for_emitter(api, PostmanEmitter, options={"flavor": flavor})
    by_target = compute_lossiness_for_emitter(api, get_emitter(flavor))
    assert by_flavor == by_target


def test_the_postman_flavor_passes_its_folder_and_example_options() -> None:
    api = model([operation("GET /widgets")]).model_copy(update={
        "services": [model([operation("GET /widgets")]).services[0],
                     model([operation("GET /other")]).services[0].model_copy(update={"key": "o", "name": "Other"})],
    })
    files = members(emit(api, "postman", flavor="bruno", folder_strategy="service"))
    assert "Other/GET -other.bru" in files


def test_an_unknown_flavor_is_an_emit_options_error() -> None:
    with pytest.raises(EmitOptionsError):
        coerce_emit_options(PostmanEmitter, {"flavor": "paw"})


# ---------------------------------------------------------------------------
# Credentials and auth
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", TARGETS)
def test_no_planted_credential_reaches_any_file(target: str) -> None:
    text = all_text(emit(leaky(), target))
    for planted in PLANTED:
        assert planted not in text
    assert "admin" not in text, "userinfo is a credential and is stripped from the base URL"


def test_insomnia_declares_every_credential_empty_in_the_base_environment() -> None:
    result = emit(leaky(), "insomnia")
    (environment,) = resources(result, "environment")
    secrets = {name for name in environment["data"] if name != "baseUrl"}
    assert {"accessToken", "xApiKey", "access_token", "password"} <= secrets
    assert all(environment["data"][name] == "" for name in secrets)
    for name in secrets:
        assert "{{ _." + name + " }}" in all_text(result), f"{name} is declared but never referenced"


def test_bruno_lists_every_credential_as_a_secret_variable() -> None:
    result = emit(leaky(), "bruno")
    environment = {b.name: b for b in parse_bru(members(result)["environments/Default.bru"])}
    secrets = {entry.key for entry in environment["vars:secret"].entries}
    assert {"accessToken", "xApiKey", "access_token", "password"} <= secrets
    assert not secrets & set(environment["vars"].values()), "a secret's value is never written"
    for name in secrets:
        assert "{{" + name + "}}" in all_text(result), f"{name} is declared but never referenced"


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("scheme,record,expected", AUTH_CASES)
def test_each_scheme_re_imports_to_the_scheme_it_was_written_as(
    target: str, scheme: str, record: Dict[str, Any], expected: Optional[str]
) -> None:
    api = model([operation("GET /secure", extras={"security": [scheme]}), operation("GET /open")])
    back = reimport(emit(api, target), target)
    operations = {op.key: op for service in back.services for op in service.operations}
    assert operations["GET /open"].extras.get("security") is None
    if expected is None:
        assert scheme in (back.extras.get("inferred_auth_schemes") or [])
    else:
        assert operations["GET /secure"].extras.get("security") == [expected]


@pytest.mark.parametrize("target,record_key", [("insomnia", "insomnia_auth"), ("bruno", "bruno_auth")])
def test_an_api_key_keeps_the_name_and_location_its_import_recorded(target: str, record_key: str) -> None:
    location = "queryParams" if target == "insomnia" else "queryparams"
    record = {"type": "apikey", "scheme": "apiKey", "declared_at": "request", "key_name": "api_key",
              "key_location": location}
    api = model([operation("GET /keyed", extras={"security": ["apiKey"], record_key: [record]})])
    back = reimport(emit(api, target), target)
    (op,) = [op for service in back.services for op in service.operations]
    (read,) = op.extras[record_key]
    assert (read["key_name"], read["key_location"]) == ("api_key", location)


# ---------------------------------------------------------------------------
# Losses and fidelity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", TARGETS)
def test_what_the_collection_cannot_carry_is_recorded(target: str) -> None:
    api = model(
        [
            operation("GET /a", tags=["One", "Two"]),
            operation(
                "GET /b", messages=[Message(key="ok", role=MessageRole.RESPONSE, content_types=["application/json"])]
            ),
            operation("POST /events", kind=OperationKind.PUBLISH),
        ],
        servers=[Server(url="https://one.example.com"), Server(url="https://two.example.com")],
        types=[Type(key="Widget", name="Widget", kind=TypeKind.RECORD)],
        channels=[Channel(key="widget-events", name="widget-events", address="widget-events")],
    )
    subjects = {loss.subject for loss in emit(api, target).losses}
    assert {"additional-tags", "responses-not-carried", "event-operation", "additional-servers",
            "types-not-declared", "channels-dropped", "api-description"} <= subjects


@pytest.mark.parametrize("target", TARGETS)
def test_the_report_drops_declared_responses(target: str) -> None:
    api = model([operation("GET /b", messages=[Message(key="ok", role=MessageRole.RESPONSE, status_code="200",
                                                      content_types=["application/json"])])])
    items = [i for i in compute_lossiness_for_emitter(api, get_emitter(target)).items if i.construct_key == "GET /b"]
    drops = [i for i in items if i.kind is LossinessKind.DROP]
    assert drops and "not carried" in drops[0].message
    assert not any("saved example responses" in i.message for i in items)


@pytest.mark.parametrize("emitter", [InsomniaEmitter, BrunoEmitter])
def test_a_model_from_the_same_client_is_reported_as_rewritten(emitter: type) -> None:
    pack = emitter.fidelity_rule_pack()(emitter.capability_profile(), emitter.label)
    assert isinstance(pack, ClientCollectionFidelityRulePack)
    native = model([operation("GET /a")]).model_copy(update={"format": emitter.key})
    (verdict,) = pack.root_verdicts(native)
    assert verdict.kind is LossinessKind.APPROX and "written anew" in verdict.message


def test_hoppscotch_models_are_still_written_back_as_read() -> None:
    pack = HoppscotchEmitter.fidelity_rule_pack()(HoppscotchEmitter.capability_profile())
    native = model([operation("GET /a")]).model_copy(update={"format": "hoppscotch"})
    assert pack.root_verdicts(native) == []


# ---------------------------------------------------------------------------
# Round trip and the export gate
# ---------------------------------------------------------------------------


def test_the_corpus_has_fixtures_for_both_clients() -> None:
    assert {entry.format for entry in client_entries()} == set(TARGETS)


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("entry", client_entries(), ids=lambda entry: entry.path)
def test_every_client_fixture_re_imports_to_the_same_call_surface(entry: Any, target: str) -> None:
    source = _import_entry(entry)
    result = emit(source, target)
    expected, actual = surface(source), surface(reimport(result, target))
    reported = {loss.pointer for loss in result.losses if loss.subject == "auth-as-parameter"}
    for key, details in expected["operations"].items():
        if details["security"] == ["authorization"]:
            # A signing auth type (Hawk, AWS IAM, NTLM …) is read as a generic `authorization`
            # requirement, which no client writes as an auth block: it is saved as the header holding
            # a reference and re-imported as that header. The one inherent difference — reported.
            assert key in reported
            details["security"] = None
            details["parameters"] = sorted(details["parameters"] + [("header", "authorization", True)])
    assert actual["operations"] == expected["operations"]
    assert actual["title"] == expected["title"]
    urls = [url for url, _ in actual["servers"]]
    if urls != [url for url, _ in expected["servers"]]:
        # A collection holds one base URL and the origins its requests were saved against; the
        # other servers are not carried, and the export says so.
        assert set(urls) < {url for url, _ in expected["servers"]}
        assert any(loss.subject == "additional-servers" for loss in result.losses)


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("source_format", ["insomnia", "bruno", "postman", "hoppscotch", "thunder-client"])
def test_native_and_cross_client_matrix_cells_pass(source_format: str, target: str) -> None:
    entry = sorted((e for e in valid_entries() if e.format == source_format), key=lambda e: e.path)[0]
    targets = {item.descriptor.key: item for item in production_emit_targets()}
    cell = run_roundtrip(_import_entry(entry), targets[target], source_format=source_format, corpus_path=entry.path)
    assert cell.status.value == "pass", cell.reason


@pytest.mark.parametrize("target", TARGETS)
def test_the_export_gate_re_imports_the_export(target: str) -> None:
    api = model([operation("GET /widgets")])
    verdict = asyncio.run(validate_emitted_artifact(target, emit(api, target), api=api))
    assert verdict.applicable and verdict.validated and verdict.valid and not verdict.failed


def test_the_gates_reject_a_broken_export() -> None:
    text = emit(model([operation("GET /widgets")]), "insomnia").files[0].content
    with pytest.raises(ValueError):
        validate_insomnia_export(text[: len(text) // 2])
    with pytest.raises(ValueError):
        validate_insomnia_export(json.dumps({"_type": "export", "__export_format": 5, "resources": []}))
    files = members(emit(model([operation("GET /widgets")]), "bruno"))
    files["GET -widgets.bru"] = "meta {\n  name: broken\n"
    with pytest.raises(ValueError):
        validate_bruno_export(files)
