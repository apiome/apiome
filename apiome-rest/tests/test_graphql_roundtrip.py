"""GraphQL emitter validate + round-trip — MFX-13.4 (#3887).

Exercises :mod:`app.graphql_roundtrip`, which closes the emit loop opened by the
GraphQL emitter (MFX-13.1) and its fidelity pack (MFX-13.3): emit → ``build_schema``
validate → re-import through the matching MFI parser → diff the re-imported model
against the source. The acceptance criteria proven here:

* **Valid output passes; deliberately broken output is caught** (MFX-5.1) — an
  SDL-invalid document is ``INVALID``; a non-GraphQL document is ``INVALID``; a real
  emission is ``valid``.
* **Same-format round-trip is lossless** — a Graph-native model already in the
  normalizer's normal form round-trips to an *empty* entity diff (``LOSSLESS``).
* **Empirical loss corroborates the predicted loss; divergences are flagged**
  (MFX-2.6) — a cross-paradigm REST source with predicted losses round-trips to a
  non-empty diff (they agree), and a mismatch flips :attr:`RoundTripReport.diverges`.
"""

from __future__ import annotations

from unittest.mock import patch

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.diff import ModelDiff
from app.emitter import EmitResult, EmittedFile, Loss, LossKind
from app.graphql_normalizer import GraphQlNormalizer
from app.graphql_parser import build_graphql_schema
from app.graphql_roundtrip import RoundTripStatus, round_trip_graphql
from app.import_source import ImportSourceError
from app.openapi_normalizer import OpenApiNormalizer

# Simple schema without directives — a true fixed point of normalize ∘ emit (MFX-13.1).
_SIMPLE_SDL = """
type Query {
  ping: String!
  echo(msg: String = "hi"): String
  user: User
}

type User {
  id: ID!
  name: String
}
"""


def _graph_native_model() -> CanonicalApi:
    """A Graph-native model in the normalizer's normal form (no raw SDL attached)."""
    schema = build_graphql_schema(_SIMPLE_SDL)
    return GraphQlNormalizer().normalize(schema, include_raw=False)


def _petstore_openapi() -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Pet Store", "version": "1.0.0"},
        "paths": {
            "/pets/{id}": {
                "get": {
                    "operationId": "getPet",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
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
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        },
                    },
                    "responses": {"201": {"description": "created"}},
                }
            },
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                    },
                }
            }
        },
    }


def _rest_model() -> CanonicalApi:
    """A REST/OpenAPI source that the GraphQL emitter reframes with predicted losses."""
    return OpenApiNormalizer().normalize(_petstore_openapi(), include_raw=False)


def _hand_authored_graph_model() -> CanonicalApi:
    """A hand-authored Graph model *not* in the normalizer's normal form.

    Field keys use a ``Type#field`` spelling the normalizer re-keys as ``Type.field``,
    so the round trip is non-empty even though the emitter predicts no loss — the
    divergence the report is designed to flag.
    """
    return CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        identity=ApiIdentity(name="Simple"),
        services=[
            Service(
                key="Query",
                name="Query",
                operations=[
                    Operation(
                        key="Query.ping",
                        name="ping",
                        kind=OperationKind.QUERY,
                        messages=[
                            Message(
                                key="Query.ping#response",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="String"),
                            )
                        ],
                    )
                ],
            )
        ],
        types=[
            Type(
                key="Query",
                name="Query",
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(
                        key="Query#ping",
                        name="ping",
                        type=TypeRef(name="String", nullable=False),
                    )
                ],
            )
        ],
    )


def _broken_sdl_emit_result() -> EmitResult:
    return EmitResult(
        files=[
            EmittedFile(
                path="schema.graphql",
                content="type Query { broken: NoSuchType }",
                media_type="application/graphql",
            )
        ],
        media_type="application/graphql",
    )


def _not_graphql_emit_result() -> EmitResult:
    return EmitResult(
        files=[
            EmittedFile(
                path="schema.graphql",
                content="not graphql at all",
                media_type="application/graphql",
            )
        ],
        media_type="application/graphql",
    )


# ---------------------------------------------------------------------------
# Same-format round-trip is lossless
# ---------------------------------------------------------------------------


def test_graph_native_source_round_trips_lossless() -> None:
    report = round_trip_graphql(_graph_native_model())

    assert report.status is RoundTripStatus.LOSSLESS
    assert report.valid
    assert report.reimported
    assert report.empirically_lossless
    assert report.predicted_lossless
    assert not report.diverges
    assert report.validation_errors == []
    assert report.diff is not None
    assert report.diff.is_empty()


def test_round_trip_is_deterministic() -> None:
    first = round_trip_graphql(_graph_native_model())
    second = round_trip_graphql(_graph_native_model())
    assert first.model_dump() == second.model_dump()


def test_round_trip_emits_internally_when_no_emit_result() -> None:
    report = round_trip_graphql(_graph_native_model())
    assert report.valid
    assert report.reimported


# ---------------------------------------------------------------------------
# Broken output is caught (MFX-5.1)
# ---------------------------------------------------------------------------


def test_schema_invalid_sdl_is_reported_invalid() -> None:
    report = round_trip_graphql(
        _graph_native_model(), emit_result=_broken_sdl_emit_result()
    )

    assert report.status is RoundTripStatus.INVALID
    assert not report.valid
    assert not report.reimported
    assert report.validation_errors
    assert report.diff is None
    assert not report.diverges


def test_non_graphql_text_is_reported_invalid() -> None:
    report = round_trip_graphql(
        _graph_native_model(), emit_result=_not_graphql_emit_result()
    )

    assert report.status is RoundTripStatus.INVALID
    assert not report.valid
    assert not report.reimported
    assert report.validation_errors
    assert report.diff is None


def test_a_real_emission_is_valid() -> None:
    for model in (_graph_native_model(), _rest_model()):
        report = round_trip_graphql(model)
        assert report.valid, model.paradigm
        assert report.reimported, model.paradigm


def test_valid_sdl_that_fails_normalization_is_unparseable() -> None:
    """UNPARSEABLE: SDL passes build_schema but the normalizer raises, so re-import fails."""
    with patch(
        "app.graphql_roundtrip.GraphQlImportSource.normalize",
        side_effect=ImportSourceError("normalizer failure"),
    ):
        report = round_trip_graphql(_graph_native_model())

    assert report.status is RoundTripStatus.UNPARSEABLE
    assert not report.valid
    assert not report.reimported
    assert report.import_error == "normalizer failure"
    assert report.diff is None
    assert not report.diverges


# ---------------------------------------------------------------------------
# Predicted vs. empirical loss (MFX-2.6)
# ---------------------------------------------------------------------------


def test_predicted_lossless_but_altered_round_trip_diverges() -> None:
    report = round_trip_graphql(_hand_authored_graph_model())

    assert report.reimported
    assert report.predicted_lossless
    assert not report.empirically_lossless
    assert report.diverges
    assert report.status is RoundTripStatus.LOSSY


def test_cross_paradigm_rest_source_round_trips_lossy_without_divergence() -> None:
    report = round_trip_graphql(_rest_model())

    assert report.reimported
    assert not report.predicted_lossless
    assert not report.empirically_lossless
    assert not report.diverges
    assert report.status is RoundTripStatus.LOSSY
    assert report.predicted_losses


# ---------------------------------------------------------------------------
# RoundTripReport derived properties
# ---------------------------------------------------------------------------


class TestRoundTripReportProperties:
    @staticmethod
    def _loss() -> Loss:
        return Loss(
            kind=LossKind.INFERRED,
            subject="synthesized-input",
            detail="synthesized input type PetInput from output record Pet",
            pointer="Pet",
        )

    def test_lossless(self) -> None:
        report = round_trip_graphql(_graph_native_model())
        assert report.valid is True
        assert report.empirically_lossless is True
        assert report.predicted_lossless is True
        assert report.diverges is False
        assert report.status is RoundTripStatus.LOSSLESS

    def test_lossy_corroborated(self) -> None:
        report = round_trip_graphql(_rest_model())
        assert report.valid is True
        assert report.diverges is False
        assert report.status is RoundTripStatus.LOSSY

    def test_invalid_has_no_divergence(self) -> None:
        report = round_trip_graphql(
            _graph_native_model(), emit_result=_broken_sdl_emit_result()
        )
        assert report.valid is False
        assert report.diverges is False
        assert report.status is RoundTripStatus.INVALID
