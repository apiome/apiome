"""OpenAPI emitter validate + round-trip — MFX-9.3 (#3868).

Exercises :mod:`app.openapi_roundtrip`, which closes the emit loop opened by the
OpenAPI emitter (MFX-9.1) and its fidelity pack (MFX-9.2): emit → validate →
re-import through the matching MFI parser → diff the re-imported model against the
source. The acceptance criteria proven here:

* **Valid output passes; deliberately broken output is caught** (MFX-5.1) — a
  schema-invalid document is ``INVALID``; a non-OpenAPI document is
  ``UNPARSEABLE``; a real emission is ``valid``.
* **Same-format round-trip is lossless** — a model already in the normalizer's
  normal form round-trips to an *empty* entity diff (``LOSSLESS``).
* **Empirical loss corroborates the predicted loss; divergences are flagged**
  (MFX-2.6) — a cross-paradigm source with predicted losses round-trips to a
  non-empty diff (they agree), and a mismatch flips
  :attr:`RoundTripReport.diverges`.
* **Downgrades re-import cleanly** — the 3.0 and Swagger 2.0 dialects, which have
  no bundled meta-schema, are validated by their own normalizer on re-import.
"""

import json

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
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
from app.diff import ModelDiff
from app.emitter import EmitResult, Loss, LossKind
from app.openapi_emitter import OpenApiEmitOptions, OpenApiEmitter
from app.openapi_import_source import OpenApiImportSource
from app.openapi_roundtrip import RoundTripStatus, round_trip_openapi

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A small but non-trivial OpenAPI 3.1 document: two operations sharing one tag,
# a path parameter, a request body, and a component schema referenced by both.
_OPENAPI_DOC = {
    "openapi": "3.1.0",
    "info": {"title": "Pet Store", "version": "1.0.0"},
    "paths": {
        "/pets/{id}": {
            "get": {
                "operationId": "getPet",
                "tags": ["pets"],
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        # A numeric exclusive bound is a JSON-Schema-2020-12 spelling
                        # OpenAPI 3.1 carries natively but Swagger 2.0 can only
                        # approximate — a 3.1-only construct whose downgrade the
                        # round trip should surface as a predicted loss.
                        "schema": {"type": "integer", "exclusiveMinimum": 1},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "a pet",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        },
                    }
                },
            }
        },
        "/pets": {
            "post": {
                "operationId": "createPet",
                "tags": ["pets"],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Pet"}
                        }
                    }
                },
                "responses": {
                    "201": {
                        "description": "created",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        },
                    }
                },
            }
        },
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            }
        }
    },
}


def _normal_form_model() -> CanonicalApi:
    """A REST model already in the OpenAPI normalizer's normal form.

    Built by importing :data:`_OPENAPI_DOC` so its service grouping (by tag) and
    field-key convention match exactly what re-importing the emitted document
    produces — the precondition for a *lossless* same-format round trip.
    """
    source = OpenApiImportSource()
    return source.normalize(source.parse(json.dumps(_OPENAPI_DOC)), include_raw=False)


def _hand_authored_model() -> CanonicalApi:
    """A hand-authored REST model *not* in the normalizer's normal form.

    Its service is named ``pets`` and its fields use the ``Type#field`` key spelling;
    the normalizer regroups paths by tag and re-keys fields as ``Type.field``, so the
    round trip is non-empty even though the emitter predicts no loss — the divergence
    the report is designed to flag.
    """
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Pet Store"),
        version="1.0.0",
        title="Pet Store",
        services=[
            Service(
                key="pets",
                name="pets",
                operations=[
                    Operation(
                        key="GET /pets/{id}",
                        name="getPet",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="GET",
                        http_path="/pets/{id}",
                        parameters=[
                            Parameter(
                                key="GET /pets/{id}#path.id",
                                name="id",
                                location=ParameterLocation.PATH,
                                type=TypeRef(name="integer"),
                                required=True,
                            )
                        ],
                        messages=[
                            Message(
                                key="GET /pets/{id}#response.200",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="Pet"),
                                content_types=["application/json"],
                                status_code="200",
                                description="a pet",
                            )
                        ],
                    )
                ],
            )
        ],
        types=[
            Type(
                key="Pet",
                name="Pet",
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(key="Pet#id", name="id", type=TypeRef(name="integer")),
                    CanonicalField(key="Pet#name", name="name", type=TypeRef(name="string")),
                ],
            )
        ],
    )


def _event_model() -> CanonicalApi:
    """An AsyncAPI-shaped source: a channel plus a publish and a subscribe op.

    OpenAPI cannot natively carry pub/sub actions or channel bindings, so the emitter
    records ``NA`` losses for them — a source that *should* round-trip lossy.
    """
    channel = Channel(
        key="user/signedup",
        address="user/signedup",
        protocol="kafka",
        bindings={"kafka": {"partitions": 3}},
    )
    publish = Operation(
        key="user/signedup#publish",
        name="onUserSignedUp",
        kind=OperationKind.PUBLISH,
        channel_ref="user/signedup",
    )
    subscribe = Operation(
        key="user/signedup#subscribe",
        name="receiveUserSignedUp",
        kind=OperationKind.SUBSCRIBE,
        channel_ref="user/signedup",
    )
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3.0",
        identity=ApiIdentity(name="Events API"),
        services=[Service(key="Events", name="Events", operations=[publish, subscribe])],
        channels=[channel],
    )


# ---------------------------------------------------------------------------
# Lossless same-format round trip
# ---------------------------------------------------------------------------


def test_normal_form_model_round_trips_losslessly() -> None:
    report = round_trip_openapi(_normal_form_model())

    assert report.status is RoundTripStatus.LOSSLESS
    assert report.valid
    assert report.reimported
    assert report.empirically_lossless
    assert report.predicted_lossless
    assert not report.diverges
    assert report.diff is not None and report.diff.is_empty()
    assert report.import_error is None


def test_lossless_round_trip_is_schema_checked_and_clean() -> None:
    report = round_trip_openapi(_normal_form_model())

    # The native 3.1 target ships a meta-schema, so it is validated — and passes.
    assert report.schema_checked
    assert report.schema_errors == []
    assert report.openapi_version == "3.1.0"


def test_round_trip_is_deterministic() -> None:
    first = round_trip_openapi(_normal_form_model())
    second = round_trip_openapi(_normal_form_model())
    assert first.model_dump() == second.model_dump()


# ---------------------------------------------------------------------------
# Broken output is caught (MFX-5.1)
# ---------------------------------------------------------------------------


def test_schema_invalid_document_is_reported_invalid() -> None:
    # A 3.1 document missing the OAS-required ``info`` object fails the meta-schema.
    broken = EmitResult.from_document({"openapi": "3.1.0", "paths": {}})
    report = round_trip_openapi(_normal_form_model(), emit_result=broken)

    assert report.status is RoundTripStatus.INVALID
    assert not report.valid
    assert report.schema_errors  # at least one meta-schema error surfaced


def test_non_openapi_document_is_reported_unparseable() -> None:
    # A document with no ``openapi``/``swagger`` marker is not legal input; the MFI
    # parser rejects it, so the artifact cannot round-trip.
    not_a_spec = EmitResult.from_document({"foo": "bar"})
    report = round_trip_openapi(_normal_form_model(), emit_result=not_a_spec)

    assert report.status is RoundTripStatus.UNPARSEABLE
    assert not report.valid
    assert not report.reimported
    assert report.import_error
    # No re-imported model means nothing to diff against.
    assert report.diff is None
    assert not report.diverges


def test_a_real_emission_is_valid() -> None:
    # The positive half of "valid output passes" for every dialect.
    for version in ("3.1", "3.0", "2.0"):
        report = round_trip_openapi(
            _normal_form_model(), opts=OpenApiEmitOptions(openapi_version=version)
        )
        assert report.valid, version
        assert report.reimported, version


# ---------------------------------------------------------------------------
# Predicted vs. empirical loss (MFX-2.6)
# ---------------------------------------------------------------------------


def test_predicted_lossless_but_altered_round_trip_diverges() -> None:
    # The emitter predicts no loss for this REST model, yet the normalizer's normal
    # form differs from its hand-authored keys, so the diff is non-empty — exactly
    # the "flagged where they diverge" case.
    report = round_trip_openapi(_hand_authored_model())

    assert report.reimported
    assert report.predicted_lossless
    assert not report.empirically_lossless
    assert report.diverges
    assert report.status is RoundTripStatus.LOSSY


def test_cross_paradigm_source_round_trips_lossy_without_divergence() -> None:
    # An event source: the emitter *predicts* losses (pub/sub actions, channel
    # bindings) and the round-trip diff is non-empty — the two agree, so this is an
    # expected loss, not a divergence.
    report = round_trip_openapi(_event_model())

    assert report.reimported
    assert not report.predicted_lossless
    assert not report.empirically_lossless
    assert not report.diverges
    assert report.status is RoundTripStatus.LOSSY
    # The predicted losses are the projection's NA drops, carried straight through.
    subjects = {loss.subject for loss in report.predicted_losses}
    assert "event-pubsub-action" in subjects
    assert all(isinstance(loss, Loss) for loss in report.predicted_losses)


# ---------------------------------------------------------------------------
# Downgrades (3.0 / Swagger 2.0)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version,expected_marker",
    [("3.0", "3.0.3"), ("2.0", "2.0")],
)
def test_downgrade_reimports_without_meta_schema_check(version, expected_marker) -> None:
    report = round_trip_openapi(
        _normal_form_model(), opts=OpenApiEmitOptions(openapi_version=version)
    )

    # Neither dialect has a bundled meta-schema, so meta-schema validation is skipped
    # and the re-import through the dialect's own normalizer is the validation.
    assert not report.schema_checked
    assert report.schema_errors == []
    assert report.reimported
    assert report.valid
    assert report.openapi_version == expected_marker


def test_downgrade_records_predicted_losses() -> None:
    # The Swagger 2.0 downgrade drops 3.1-only constructs; those ride back as losses.
    report = round_trip_openapi(
        _normal_form_model(), opts=OpenApiEmitOptions(openapi_version="2.0")
    )
    assert report.predicted_losses
    assert not report.predicted_lossless


# ---------------------------------------------------------------------------
# Emission passthrough & report shape
# ---------------------------------------------------------------------------


def test_supplied_emit_result_is_not_re_emitted() -> None:
    # A caller that already emitted can hand the result in; its losses are carried
    # verbatim rather than recomputed.
    emit_result = OpenApiEmitter().emit(_event_model())
    report = round_trip_openapi(_event_model(), emit_result=emit_result)
    assert report.predicted_losses == emit_result.losses


def test_report_diff_is_a_model_diff() -> None:
    report = round_trip_openapi(_normal_form_model())
    assert isinstance(report.diff, ModelDiff)
    # Both fingerprints are populated even for an empty (identical) diff.
    assert report.diff.base_fingerprint
    assert report.diff.target_fingerprint


def test_status_ordering_covers_every_outcome() -> None:
    # One representative report per status keeps the enum wired to real behaviour.
    lossless = round_trip_openapi(_normal_form_model())
    lossy = round_trip_openapi(_event_model())
    invalid = round_trip_openapi(
        _normal_form_model(),
        emit_result=EmitResult.from_document({"openapi": "3.1.0", "paths": {}}),
    )
    unparseable = round_trip_openapi(
        _normal_form_model(), emit_result=EmitResult.from_document({"foo": "bar"})
    )

    assert lossless.status is RoundTripStatus.LOSSLESS
    assert lossy.status is RoundTripStatus.LOSSY
    assert invalid.status is RoundTripStatus.INVALID
    assert unparseable.status is RoundTripStatus.UNPARSEABLE


def test_loss_kind_na_constructs_are_the_predicted_drops() -> None:
    # Sanity-tie the predicted losses to the LossKind vocabulary the emitter uses.
    report = round_trip_openapi(_event_model())
    assert any(loss.kind is LossKind.NA for loss in report.predicted_losses)
