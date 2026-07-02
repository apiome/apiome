"""Tests for the canonical fingerprint SPI (MFI-3.1, #3742).

The acceptance criteria are:

* identical artifacts produce an identical fingerprint across runs;
* a single field change flips it;
* (and, around those) doc-only edits and source declaration-order differences do
  *not* flip it — that is the whole point of a *canonical* fingerprint;
* the per-format hash hook dispatches to a registered hasher and is documented as
  distinct from the semantic hash.

Everything here is pure (no DB/network), mirroring the fingerprint module itself.
"""

import copy

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
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
from app.fingerprint import (
    FINGERPRINT_ALGORITHM,
    FingerprintHasher,
    FingerprintResult,
    available_fingerprint_formats,
    canonical_fingerprint,
    canonical_payload,
    fingerprint,
    get_fingerprint_hasher,
    register_fingerprint_hasher,
)


def _sample_api() -> CanonicalApi:
    """A small but representative REST artifact touching every load-bearing axis.

    It deliberately carries descriptions (to prove they are ignored), constraints,
    defaults, a parameter, request/response messages, and a record + enum type.
    """
    pet_type = Type(
        key="Pet",
        name="Pet",
        kind=TypeKind.RECORD,
        description="A pet.",
        fields=[
            CanonicalField(
                key="Pet.id",
                name="id",
                type=TypeRef(name="integer", nullable=False),
                constraints=Constraints(minimum=1),
                description="The id.",
            ),
            CanonicalField(
                key="Pet.name",
                name="name",
                type=TypeRef(name="string", nullable=False),
                default="unknown",
            ),
            CanonicalField(
                key="Pet.status",
                name="status",
                type=TypeRef(name="Status"),
            ),
        ],
    )
    status_type = Type(
        key="Status",
        name="Status",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="Status.ACTIVE", name="ACTIVE", value=0),
            EnumValue(key="Status.RETIRED", name="RETIRED", value=1),
        ],
    )
    get_pet = Operation(
        key="GET /pets/{id}",
        name="getPet",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET",
        http_path="/pets/{id}",
        description="Fetch a pet.",
        parameters=[
            Parameter(
                key="GET /pets/{id}#path.id",
                name="id",
                location=ParameterLocation.PATH,
                type=TypeRef(name="integer", nullable=False),
                required=True,
            )
        ],
        messages=[
            Message(
                key="GET /pets/{id}#response.200",
                role=MessageRole.RESPONSE,
                status_code="200",
                payload=TypeRef(name="Pet"),
                content_types=["application/json"],
                description="OK.",
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        protocol="http",
        identity=ApiIdentity(name="Pets", namespace="com.acme.pets"),
        version="1.0.0",
        title="Pets API",
        description="A pets API.",
        services=[Service(key="pets", name="pets", operations=[get_pet])],
        types=[pet_type, status_type],
        raw={"openapi": "3.1.0", "x-comment": "irrelevant to identity"},
    )


def test_fingerprint_is_stable_across_runs():
    """Identical artifacts → identical fingerprint, recomputed independently."""
    assert canonical_fingerprint(_sample_api()) == canonical_fingerprint(_sample_api())


def test_fingerprint_is_a_sha256_hex():
    """The digest is a 64-char lowercase hex string."""
    digest = canonical_fingerprint(_sample_api())
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_descriptions_titles_and_raw_do_not_affect_fingerprint():
    """Doc-only edits (descriptions/titles) and the native ``raw`` AST are ignored."""
    base = _sample_api()
    edited = _sample_api()
    edited.description = "Completely different prose."
    edited.title = "Renamed for the brochure"
    edited.types[0].description = "A different description."
    edited.types[0].fields[0].description = "Edited."
    edited.services[0].operations[0].description = "Edited too."
    edited.services[0].operations[0].messages[0].description = "Edited again."
    edited.raw = {"openapi": "3.1.0", "x-comment": "totally rewritten"}

    assert canonical_fingerprint(edited) == canonical_fingerprint(base)


def test_declaration_order_does_not_affect_fingerprint():
    """Reordering identity-keyed collections leaves the fingerprint unchanged."""
    base = _sample_api()
    reordered = _sample_api()
    reordered.types.reverse()
    reordered.types[0].fields.reverse()  # Pet/Status order swapped, then fields
    reordered.services[0].operations[0].parameters.reverse()

    assert canonical_fingerprint(reordered) == canonical_fingerprint(base)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda api: api.types[0].fields.append(
                CanonicalField(
                    key="Pet.tag", name="tag", type=TypeRef(name="string")
                )
            ),
            id="add-field",
        ),
        pytest.param(
            lambda api: api.types[0].fields.pop(),
            id="remove-field",
        ),
        pytest.param(
            lambda api: setattr(
                api.types[0].fields[0], "type", TypeRef(name="string")
            ),
            id="retype-field",
        ),
        pytest.param(
            lambda api: setattr(api.types[0].fields[1], "default", "changed"),
            id="change-default",
        ),
        pytest.param(
            lambda api: setattr(
                api.types[0].fields[0], "constraints", Constraints(minimum=5)
            ),
            id="change-constraint",
        ),
        pytest.param(
            lambda api: setattr(
                api.services[0].operations[0], "http_method", "POST"
            ),
            id="change-verb",
        ),
        pytest.param(
            lambda api: api.types[1].enum_values.append(
                EnumValue(key="Status.LOST", name="LOST", value=2)
            ),
            id="add-enum-value",
        ),
        pytest.param(
            lambda api: setattr(api.types[0].fields[2], "deprecated", True),
            id="deprecate-field",
        ),
        pytest.param(
            lambda api: api.types[0].fields[0].extras.__setitem__("x-fmt", "u64"),
            id="change-extras",
        ),
    ],
)
def test_single_change_flips_fingerprint(mutate):
    """Any single structural change flips the fingerprint."""
    base = _sample_api()
    changed = _sample_api()
    mutate(changed)
    assert canonical_fingerprint(changed) != canonical_fingerprint(base)


def test_enum_value_order_is_load_bearing():
    """Reordering enum values (ordinal-meaningful) *does* change the fingerprint."""
    base = _sample_api()
    swapped = _sample_api()
    swapped.types[1].enum_values.reverse()
    assert canonical_fingerprint(swapped) != canonical_fingerprint(base)


def test_canonical_payload_drops_descriptive_keys_but_keeps_extras():
    """The hashed projection omits descriptions/raw yet preserves semantic bags."""
    api = _sample_api()
    api.types[0].fields[0].extras["x-fmt"] = "int64"
    payload = canonical_payload(api)

    assert "raw" not in payload
    assert "title" not in payload
    assert "description" not in payload
    # extras carried through verbatim, even though it is a nested dict
    pet = next(t for t in payload["types"] if t["key"] == "Pet")
    id_field = next(f for f in pet["fields"] if f["key"] == "Pet.id")
    assert id_field["extras"] == {"x-fmt": "int64"}


def test_canonical_payload_does_not_mutate_input():
    """Computing the payload must not disturb the caller's model."""
    api = _sample_api()
    before = copy.deepcopy(api.model_dump())
    canonical_payload(api)
    assert api.model_dump() == before


def test_fingerprint_result_has_semantic_hash_and_no_format_hash_by_default():
    """With no registered hasher, only the semantic fingerprint is populated."""
    result = fingerprint(_sample_api())
    assert isinstance(result, FingerprintResult)
    assert result.fingerprint == canonical_fingerprint(_sample_api())
    assert result.algorithm == FINGERPRINT_ALGORITHM
    assert result.format == "openapi-3.1"
    assert result.format_hash is None
    assert result.format_algorithm is None


def test_per_format_hasher_dispatch(monkeypatch):
    """A registered hasher is invoked for its format and surfaced on the result."""
    import app.fingerprint as fp

    # Isolate the registry so the test never leaks a hasher into other tests.
    monkeypatch.setattr(fp, "_HASHER_REGISTRY", {}, raising=True)

    class _StubHasher(FingerprintHasher):
        format = "avro"
        algorithm = "avro-parsing-canonical-form-sha256"

        def hash(self, api):  # noqa: D401 - test stub
            return "deadbeef"

    register_fingerprint_hasher(_StubHasher)
    assert get_fingerprint_hasher("avro") is _StubHasher
    assert available_fingerprint_formats() == ["avro"]

    avro_api = _sample_api()
    avro_api.format = "avro"
    result = fp.fingerprint(avro_api)

    assert result.format == "avro"
    assert result.format_hash == "deadbeef"
    assert result.format_algorithm == "avro-parsing-canonical-form-sha256"
    # The semantic fingerprint is still computed independently of the hook.
    assert result.fingerprint == canonical_fingerprint(avro_api)


def test_register_rejects_missing_format_or_algorithm():
    """A hasher must declare both a format key and an algorithm label."""

    class _NoFormat(FingerprintHasher):
        algorithm = "x"

        def hash(self, api):
            return ""

    class _NoAlgorithm(FingerprintHasher):
        format = "x"

        def hash(self, api):
            return ""

    with pytest.raises(ValueError):
        register_fingerprint_hasher(_NoFormat)
    with pytest.raises(ValueError):
        register_fingerprint_hasher(_NoAlgorithm)


def test_register_rejects_conflicting_format(monkeypatch):
    """Two different classes cannot claim the same format key."""
    import app.fingerprint as fp

    monkeypatch.setattr(fp, "_HASHER_REGISTRY", {}, raising=True)

    class _A(FingerprintHasher):
        format = "dup"
        algorithm = "a"

        def hash(self, api):
            return ""

    class _B(FingerprintHasher):
        format = "dup"
        algorithm = "b"

        def hash(self, api):
            return ""

    fp.register_fingerprint_hasher(_A)
    fp.register_fingerprint_hasher(_A)  # same class re-register is a no-op
    with pytest.raises(ValueError):
        fp.register_fingerprint_hasher(_B)


def test_self_registration_flag(monkeypatch):
    """``register=True`` on the subclass adds it to the registry on definition."""
    import app.fingerprint as fp

    monkeypatch.setattr(fp, "_HASHER_REGISTRY", {}, raising=True)

    class _SelfReg(FingerprintHasher, register=True):
        format = "selfreg"
        algorithm = "selfreg-sha256"

        def hash(self, api):
            return "cafe"

    assert fp.get_fingerprint_hasher("selfreg") is _SelfReg
