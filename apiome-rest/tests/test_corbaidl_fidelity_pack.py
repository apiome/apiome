"""OMG IDL fidelity pack: profile-dependent losses — MFX-28.2 (#4169).

:class:`app.corbaidl_emitter.CorbaIdlFidelityRulePack` lays the model out with the IDL writer for the
export's ``profile`` and reports, on the construct each concerns:

* **constraints** — a string ``max_length`` is written ``string<N>`` and a list ``max_items``
  ``sequence<T, N>`` (represented: nothing reported); the rest is a ``// constraints: …`` comment
  (``APPROX``) — and the IDL reader reads the bounds back;
* **HTTP semantics** — ``corba``: the operation is an ``APPROX`` and its binding a ``DROP``; ``dds``: no
  interface is written, every operation is a ``DROP``;
* **event channels** — ``dds``: a DDS topic (``APPROX``, its name written as a comment); ``corba``: ``DROP``;
* **maps** — a sequence of key/value entry structs (``APPROX``);
* **unions** — a synthesized discriminator enum (``SYNTH``);
* the capability profile no longer claims unions are dropped, nullability is lost the wrong way round,
  or that IDL synthesizes field ids.

Acceptance: profile-dependent rules verified on fixtures (plain vs DDS) —
``fixtures/corbaidl_fidelity/profiles.json`` pins both profiles' reports for a rich REST source and an
AsyncAPI corpus source (regenerate with ``APIOME_REGEN_CORBAIDL_FIDELITY=1``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.corbaidl_emitter import CorbaIdlEmitOptions, CorbaIdlEmitter
from app.corbaidl_import_source import CorbaIdlImportSource
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind, LossItem
from app.roundtrip_matrix import reimport_emitted

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "corbaidl_fidelity" / "profiles.json"
PROFILES = ("corba", "dds")


def _field(owner: str, name: str, ref: str = "string", *, nullable: bool = False, **kw) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=TypeRef(name=ref, nullable=nullable), **kw)


def _rich_rest_api() -> CanonicalApi:
    """Constraints (bounded and not), a nullable field, a union, a map, an HTTP operation and a channel."""
    pet = Type(
        key="Pet", name="Pet", kind=TypeKind.RECORD,
        fields=[
            _field("Pet", "id", "integer", constraints=Constraints(minimum=1)),
            _field("Pet", "name", constraints=Constraints(min_length=1, max_length=40)),
            CanonicalField(key="Pet.tags", name="tags", type=TypeRef(item=TypeRef(name="string"), nullable=False),
                           constraints=Constraints(max_items=5)),
            _field("Pet", "nickname", nullable=True),
        ],
    )
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION, union_members=["Pet"])
    attrs = Type(key="Attrs", name="Attrs", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
                 value_type=TypeRef(name="string"))
    get_pet = Operation(
        key="GET /pets/{id}", name="getPet", kind=OperationKind.REQUEST_RESPONSE, http_method="GET",
        http_path="/pets/{id}",
        parameters=[Parameter(key="GET /pets/{id}#path.id", name="id", location=ParameterLocation.PATH,
                              type=TypeRef(name="integer"), required=True, constraints=Constraints(minimum=1))],
        messages=[Message(key="GET /pets/{id}#response.200", role=MessageRole.RESPONSE, status_code="200",
                          payload=TypeRef(name="Pet"))],
    )
    adopted = Operation(
        key="publishAdopted", name="publishAdopted", kind=OperationKind.PUBLISH, channel_ref="pets.adopted",
        messages=[Message(key="publishAdopted#event", role=MessageRole.EVENT, payload=TypeRef(name="Pet"))],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="Pets"), title="Pets",
        services=[Service(key="pets", name="PetService", operations=[get_pet, adopted])],
        types=[pet, shape, attrs], channels=[Channel(key="pets.adopted", address="pets.adopted")],
    )


def _corpus_api(path: Path, fmt: str) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _items(api: CanonicalApi, profile: str) -> Dict[str, List[LossItem]]:
    out: Dict[str, List[LossItem]] = {}
    for item in compute_lossiness_for_emitter(api, CorbaIdlEmitter, options={"profile": profile}).items:
        out.setdefault(item.construct_key, []).append(item)
    return out


def _mappings(items: Dict[str, List[LossItem]], key: str) -> Dict[str, LossinessKind]:
    return {str(item.target_mapping): item.kind for item in items.get(key, [])}


def _emit(api: CanonicalApi, profile: str) -> str:
    return CorbaIdlEmitter().emit(api, opts=CorbaIdlEmitOptions(profile=profile)).files[0].content


# ===========================================================================
# Acceptance: both profiles pinned on fixtures
# ===========================================================================


def _summary(api: CanonicalApi, profile: str) -> List[List[str]]:
    report = compute_lossiness_for_emitter(api, CorbaIdlEmitter, options={"profile": profile})
    return sorted([item.construct_key, item.kind.value, str(item.target_mapping)] for item in report.items)


def test_both_profiles_match_the_fixture() -> None:
    measured = {
        "rich-rest": {profile: _summary(_rich_rest_api(), profile) for profile in PROFILES},
        "asyncapi/02-order-events-3.0.yaml": {
            profile: _summary(_corpus_api(_EXAMPLES / "asyncapi" / "02-order-events-3.0.yaml", "asyncapi"), profile)
            for profile in PROFILES
        },
    }
    if os.environ.get("APIOME_REGEN_CORBAIDL_FIDELITY"):
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")
    assert measured == json.loads(_GOLDEN.read_text(encoding="utf-8"))


def test_an_event_source_s_channels_are_topics_under_dds_and_dropped_under_corba() -> None:
    api = _corpus_api(_EXAMPLES / "asyncapi" / "02-order-events-3.0.yaml", "asyncapi")
    assert api.channels
    corba, dds = _items(api, "corba"), _items(api, "dds")
    for channel in api.channels:
        assert _mappings(corba, channel.key) == {"channel → dropped": LossinessKind.DROP}
        assert _mappings(dds, channel.key) == {"channel → DDS topic": LossinessKind.APPROX}
    assert "// DDS topic" in _emit(api, "dds")
    assert "// DDS topic" not in _emit(api, "corba")


# ===========================================================================
# The rules
# ===========================================================================


@pytest.mark.parametrize("profile", PROFILES)
def test_bounds_are_written_and_the_rest_is_a_comment(profile: str) -> None:
    api = _rich_rest_api()
    text = _emit(api, profile)
    assert "string<40> name;" in text and "sequence<string, 5> tags;" in text
    assert "// constraints: min length 1\n" in text  # max length 40 is the bound, not the comment
    assert "// constraints: >= 1\n" in text
    items = _items(api, profile)
    assert _mappings(items, "Pet.name") == {"constraints → comment": LossinessKind.APPROX}
    assert "max_length is written as an IDL bound" in items["Pet.name"][0].message
    assert "Pet.tags" not in items, "a bound alone is represented: nothing to report"


def test_the_reader_reads_the_bounds_back() -> None:
    api = _rich_rest_api()
    result = CorbaIdlEmitter().emit(api)
    back = reimport_emitted(CorbaIdlImportSource(), result, multi_file=False)
    pet = next(t for t in back.types if t.name == "Pet")
    fields = {f.name: f for f in pet.fields}
    assert fields["name"].type.name == "string" and fields["name"].constraints.max_length == 40
    assert fields["tags"].type.item is not None and fields["tags"].constraints.max_items == 5
    assert fields["id"].constraints is None


def test_an_http_operation_under_corba_is_an_operation_and_a_dropped_binding() -> None:
    items = _items(_rich_rest_api(), "corba")
    assert _mappings(items, "GET /pets/{id}") == {
        "HTTP operation → IDL operation": LossinessKind.APPROX,
        "HTTP binding → dropped": LossinessKind.DROP,
        "constraints → comment": LossinessKind.APPROX,
        # It reads back keyed by its module and interface; the new key is synthesized.
        "operation → Pets.PetService.getPet": LossinessKind.DROP,
    }
    assert _mappings(items, "Pets.PetService.getPet") == {"operation → IDL operation": LossinessKind.SYNTH}
    assert "// id constraints: >= 1" in _emit(_rich_rest_api(), "corba")


def test_under_dds_every_operation_is_dropped() -> None:
    items = _items(_rich_rest_api(), "dds")
    assert _mappings(items, "GET /pets/{id}") == {"operation → dropped (DDS profile)": LossinessKind.DROP}
    assert _mappings(items, "publishAdopted") == {"event operation → dropped": LossinessKind.DROP}
    assert "interface" not in _emit(_rich_rest_api(), "dds")


def test_the_dds_topic_names_its_payload_type() -> None:
    text = _emit(_rich_rest_api(), "dds")
    assert '// DDS topic "pets.adopted": ::Pets::Pet' in text
    (item,) = _items(_rich_rest_api(), "dds")["pets.adopted"]
    assert "::Pets::Pet" in item.message


@pytest.mark.parametrize("profile", PROFILES)
def test_maps_are_approximated_and_union_discriminators_synthesized(profile: str) -> None:
    items = _items(_rich_rest_api(), profile)
    assert _mappings(items, "Attrs") == {
        "map → sequence<Entry>": LossinessKind.APPROX,
        "map declaration → typedef": LossinessKind.DROP,
    }
    assert _mappings(items, "Pets.AttrsEntry") == {"map → entry struct": LossinessKind.SYNTH}
    assert _mappings(items, "Pets.ShapeKind") == {"union → discriminator": LossinessKind.SYNTH}
    shape = _mappings(items, "Shape")
    assert shape["union → discriminated union"] is LossinessKind.SYNTH
    assert LossinessKind.DROP not in shape.values(), "unions are written, not dropped"
    assert "enum ShapeKind" in _emit(_rich_rest_api(), profile)


@pytest.mark.parametrize("profile", PROFILES)
def test_no_false_nullability_or_field_id_verdicts(profile: str) -> None:
    items = _items(_rich_rest_api(), profile)
    for key in ("Pet.id", "Pet.nickname"):
        assert not [i for i in items.get(key, []) if i.kind is LossinessKind.SYNTH]
        assert not [i for i in items.get(key, []) if "optional" in (i.message or "").lower()
                    and "non-null" in (i.message or "")]
    assert "@optional string nickname;" in _emit(_rich_rest_api(), profile)


def test_a_source_s_field_numbers_are_reported_dropped() -> None:
    numbered = _rich_rest_api()
    numbered.types[0].fields[0].field_number = 7
    (item,) = [i for i in _items(numbered, "corba")["Pet.id"] if i.kind is LossinessKind.DROP]
    assert "field number" in item.message


def test_invalid_options_fall_back_to_the_corba_profile() -> None:
    report = compute_lossiness_for_emitter(_rich_rest_api(), CorbaIdlEmitter, options={"profile": "orb"})
    assert any(item.target_mapping == "channel → dropped" for item in report.items)


@pytest.mark.parametrize("name", ["01-bank.idl", "02-inventory.idl", "05-trading-stress.idl"])
def test_a_corba_source_reports_no_comment_or_binding_loss(name: str) -> None:
    api = _corpus_api(_EXAMPLES / "corba-idl" / name, "corbaidl")
    mappings = {item.target_mapping for item in compute_lossiness_for_emitter(api, CorbaIdlEmitter).items}
    assert not mappings & {"constraints → comment", "HTTP binding → dropped", "union → discriminated union"}
    assert "// constraints" not in CorbaIdlEmitter().emit(api).files[0].content


@pytest.mark.parametrize("profile", PROFILES)
def test_the_keys_a_re_import_gives_back_are_named(profile: str) -> None:
    items = _items(_rich_rest_api(), profile)
    assert _mappings(items, "Pet")["type → Pets.Pet"] is LossinessKind.DROP
    assert _mappings(items, "Pets.Pet") == {"type": LossinessKind.SYNTH}
    (root,) = items[""]
    assert root.kind is LossinessKind.DROP and "module 'Pets'" in root.message
    service = _mappings(items, "pets")
    if profile == "dds":
        assert service == {"service → dropped (DDS profile)": LossinessKind.DROP}
        assert "Pets.PetService" not in items
    else:
        assert service == {"interface → Pets.PetService": LossinessKind.DROP}
        assert _mappings(items, "Pets.PetService") == {"service → interface": LossinessKind.SYNTH}
