"""Tests for version-on-change + date/time tagging of canonical artifacts (MFI-3.4, #3745).

The acceptance criterion is precise: *re-importing with no change creates no version;
a change creates one dated version + diff.* These tests pin that across paradigms
(REST, event, graph), plus the supporting machinery generalized from the MCP tagger:

* the minute-precision UTC date/time tag and its ``-N`` same-minute collision suffix;
* the version-on-change decision — initial import always creates (no diff); an
  unchanged re-import skips and leaves ``current_version`` put; a changed re-import
  creates a freshly tagged version carrying the before→after diff;
* fingerprint-only deciding (no previous model) still detects change/no-change;
* the ``current_version`` pointer advances only on a change;
* determinism and JSON round-trip of the decision.

Everything here is pure (no DB/network/clock), mirroring the module itself.
"""

import copy
from datetime import datetime, timedelta, timezone

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
from app.diff import ChangeKind, EntityCategory
from app.fingerprint import fingerprint
from app.versioning import (
    VERSION_TAG_FORMAT,
    PreviousVersion,
    VersionAction,
    VersionDecision,
    decide_version,
    format_version_tag,
    mint_version_tag,
)

# ===========================================================================
# Fixtures
# ===========================================================================

# A fixed import time so the date/time tag is deterministic in tests.
_WHEN = datetime(2026, 6, 26, 14, 3, 0, tzinfo=timezone.utc)


def _rest_api() -> CanonicalApi:
    """A small REST artifact touching services, operations, messages, types, fields."""
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
        types=[pet_type],
        raw={"openapi": "3.1.0"},
    )


def _event_api() -> CanonicalApi:
    """A small event artifact touching a channel and a pub operation."""
    signup_channel = Channel(
        key="user/signedup",
        address="user/signedup",
        protocol="kafka",
        parameters=[
            CanonicalField(
                key="user/signedup#userId", name="userId", type=TypeRef(name="string")
            ),
        ],
        bindings={"kafka": {"partitions": 3}},
    )
    publish = Operation(
        key="publish user/signedup",
        name="publishSignup",
        kind=OperationKind.PUBLISH,
        channel_ref="user/signedup",
        messages=[
            Message(
                key="publish user/signedup#event",
                role=MessageRole.EVENT,
                payload=TypeRef(name="SignupEvent"),
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        protocol="kafka",
        identity=ApiIdentity(name="Signups"),
        services=[Service(key="signups", name="signups", operations=[publish])],
        channels=[signup_channel],
    )


def _graph_api() -> CanonicalApi:
    """A small GraphQL artifact touching a query operation and an object type."""
    user_type = Type(
        key="User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="User.id", name="id", type=TypeRef(name="ID", nullable=False)),
            CanonicalField(key="User.email", name="email", type=TypeRef(name="String")),
        ],
    )
    user_query = Operation(
        key="Query.user",
        name="user",
        kind=OperationKind.QUERY,
        messages=[
            Message(
                key="Query.user#response",
                role=MessageRole.RESPONSE,
                payload=TypeRef(name="User"),
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        protocol="graphql-over-http",
        identity=ApiIdentity(name="Graph"),
        services=[Service(key="Query", name="Query", operations=[user_query])],
        types=[user_type],
    )


def _fp(api: CanonicalApi) -> str:
    """The semantic fingerprint string of a model (what a version stores)."""
    return fingerprint(api).fingerprint


def _previous(api: CanonicalApi, *, tag: str = "2026-06-25T09:00Z", with_model: bool = True):
    """A :class:`PreviousVersion` describing ``api`` as the current version."""
    return PreviousVersion(
        version_tag=tag,
        fingerprint=_fp(api),
        model=api if with_model else None,
    )


_PARADIGMS = pytest.mark.parametrize(
    "make_api", [_rest_api, _event_api, _graph_api], ids=["rest", "event", "graph"]
)


# ===========================================================================
# Date/time tagging
# ===========================================================================


def test_format_version_tag_is_minute_precision_utc():
    assert format_version_tag(_WHEN) == "2026-06-26T14:03Z"
    # The pattern constant and the function agree.
    assert _WHEN.strftime(VERSION_TAG_FORMAT) == "2026-06-26T14:03Z"


def test_format_version_tag_normalizes_timezone():
    # Same instant expressed in a +02:00 zone yields the same UTC tag.
    aware = datetime(2026, 6, 26, 16, 3, 0, tzinfo=timezone(timedelta(hours=2)))
    assert format_version_tag(aware) == "2026-06-26T14:03Z"


def test_format_version_tag_treats_naive_as_utc():
    naive = datetime(2026, 6, 26, 14, 3, 0)
    assert format_version_tag(naive) == "2026-06-26T14:03Z"


def test_mint_version_tag_uses_base_when_free():
    assert mint_version_tag(_WHEN, []) == "2026-06-26T14:03Z"
    assert mint_version_tag(_WHEN, ["2020-01-01T00:00Z"]) == "2026-06-26T14:03Z"


def test_mint_version_tag_suffixes_same_minute_collisions():
    base = "2026-06-26T14:03Z"
    assert mint_version_tag(_WHEN, [base]) == f"{base}-2"
    assert mint_version_tag(_WHEN, [base, f"{base}-2"]) == f"{base}-3"
    # Gaps are filled with the lowest free ordinal, not blindly appended.
    assert mint_version_tag(_WHEN, [base, f"{base}-3"]) == f"{base}-2"


# ===========================================================================
# Version-on-change decision
# ===========================================================================


@_PARADIGMS
def test_initial_import_always_creates_without_diff(make_api):
    api = make_api()
    decision = decide_version(api, previous=None, when=_WHEN)

    assert decision.action is VersionAction.CREATE
    assert decision.created is True
    assert decision.changed is True
    assert decision.is_initial is True
    assert decision.version_tag == "2026-06-26T14:03Z"
    assert decision.current_version_tag == decision.version_tag
    assert decision.previous_fingerprint is None
    # First version has nothing to diff against.
    assert decision.diff is None
    assert decision.fingerprint.fingerprint == _fp(api)


@_PARADIGMS
def test_reimport_no_change_skips_and_holds_current(make_api):
    api = make_api()
    previous = _previous(api, tag="2026-06-25T09:00Z")

    # Re-import a byte-identical model.
    decision = decide_version(make_api(), previous=previous, when=_WHEN)

    assert decision.action is VersionAction.SKIP
    assert decision.created is False
    assert decision.changed is False
    assert decision.is_initial is False
    assert decision.version_tag is None
    # current_version is left pointing at the previous version.
    assert decision.current_version_tag == "2026-06-25T09:00Z"
    assert decision.diff is None
    assert decision.previous_fingerprint == previous.fingerprint


@_PARADIGMS
def test_reimport_doc_only_edit_skips(make_api):
    # A description-only edit is invisible to the semantic fingerprint, so it must not
    # mint a new version (the fingerprint is doc-insensitive by MFI-3.1 design).
    api = make_api()
    previous = _previous(api)

    edited = make_api()
    edited.description = "A completely reworded description that changes no contract."

    decision = decide_version(edited, previous=previous, when=_WHEN)
    assert decision.action is VersionAction.SKIP
    assert decision.changed is False


@_PARADIGMS
def test_changed_reimport_creates_dated_version_with_diff(make_api):
    api = make_api()
    previous = _previous(api, tag="2026-06-25T09:00Z")

    # A structural change: add a new service/operation present in no paradigm fixture.
    changed = make_api()
    changed.services.append(
        Service(
            key="admin",
            name="admin",
            operations=[
                Operation(key="admin.purge", name="purge", kind=OperationKind.REQUEST_RESPONSE)
            ],
        )
    )

    decision = decide_version(changed, previous=previous, when=_WHEN)

    assert decision.action is VersionAction.CREATE
    assert decision.changed is True
    assert decision.is_initial is False
    # One dated version, tagged from the import time.
    assert decision.version_tag == "2026-06-26T14:03Z"
    assert decision.current_version_tag == decision.version_tag
    assert decision.previous_fingerprint == previous.fingerprint
    assert decision.fingerprint.fingerprint == _fp(changed)
    # ... and a diff that explains the change.
    assert decision.diff is not None
    assert decision.diff.identical is False
    assert decision.diff.counts.added >= 1
    added_services = [
        c
        for c in decision.diff.changes
        if c.category is EntityCategory.SERVICE and c.kind is ChangeKind.ADDED
    ]
    assert any(c.key == "admin" for c in added_services)
    # The diff is oriented previous -> new.
    assert decision.diff.base_fingerprint == previous.fingerprint
    assert decision.diff.target_fingerprint == decision.fingerprint.fingerprint


def test_changed_reimport_diff_orientation_and_removal():
    # Dropping a type from the model reads as a removal in the previous -> new diff.
    api = _rest_api()
    previous = _previous(api)

    changed = _rest_api()
    changed.types = []  # remove the Pet type

    decision = decide_version(changed, previous=previous, when=_WHEN)
    assert decision.action is VersionAction.CREATE
    assert decision.diff is not None
    removed_types = [
        c
        for c in decision.diff.changes
        if c.category is EntityCategory.TYPE and c.kind is ChangeKind.REMOVED
    ]
    assert any(c.key == "Pet" for c in removed_types)


def test_changed_reimport_without_previous_model_decides_but_has_no_diff():
    # Fingerprint-only deciding: the previous model was not loaded, so we still detect
    # the change (and create a version), but cannot compute the before->after diff.
    api = _rest_api()
    previous = _previous(api, with_model=False)
    assert previous.model is None

    changed = _rest_api()
    changed.types[0].fields[0].constraints = Constraints(minimum=5)  # a real change

    decision = decide_version(changed, previous=previous, when=_WHEN)
    assert decision.action is VersionAction.CREATE
    assert decision.changed is True
    assert decision.diff is None  # no previous model to diff against
    assert decision.version_tag == "2026-06-26T14:03Z"


def test_unchanged_reimport_without_previous_model_still_skips():
    api = _rest_api()
    previous = _previous(api, with_model=False)
    decision = decide_version(_rest_api(), previous=previous, when=_WHEN)
    assert decision.action is VersionAction.SKIP
    assert decision.diff is None


def test_changed_version_tag_never_collides_with_previous_same_minute():
    # A change that lands in the same minute as the previous version's tag must get a
    # distinct, suffixed tag rather than reusing the previous one.
    api = _rest_api()
    previous = _previous(api, tag="2026-06-26T14:03Z")  # same minute as _WHEN

    changed = _rest_api()
    changed.types = []

    decision = decide_version(changed, previous=previous, when=_WHEN)
    assert decision.version_tag == "2026-06-26T14:03Z-2"
    assert decision.current_version_tag == "2026-06-26T14:03Z-2"


def test_changed_version_tag_avoids_supplied_existing_tags():
    api = _rest_api()
    previous = _previous(api, tag="2026-06-25T09:00Z")
    changed = _rest_api()
    changed.types = []

    decision = decide_version(
        changed,
        previous=previous,
        when=_WHEN,
        existing_tags=["2026-06-26T14:03Z", "2026-06-26T14:03Z-2"],
    )
    assert decision.version_tag == "2026-06-26T14:03Z-3"


# ===========================================================================
# Determinism & serialization
# ===========================================================================


@_PARADIGMS
def test_decision_is_deterministic(make_api):
    api = make_api()
    previous = _previous(api)

    def _changed() -> CanonicalApi:
        # An artifact-level contract change (source version) that flips the fingerprint —
        # unlike title/description, which are scrubbed and never affect it.
        c = make_api()
        c.version = "9.9.9"
        return c

    first = decide_version(_changed(), previous=previous, when=_WHEN)
    second = decide_version(_changed(), previous=previous, when=_WHEN)
    assert first.action is VersionAction.CREATE  # the change is a real one
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_decision_round_trips_through_json():
    api = _rest_api()
    previous = _previous(api)
    changed = _rest_api()
    changed.types = []

    decision = decide_version(changed, previous=previous, when=_WHEN)
    dumped = decision.model_dump(mode="json")
    restored = VersionDecision.model_validate(dumped)
    assert restored.model_dump(mode="json") == dumped
    assert restored.action is VersionAction.CREATE
    assert restored.diff is not None


def test_input_models_are_not_mutated_by_decision():
    api = _rest_api()
    previous = _previous(api)
    before = copy.deepcopy(previous.model_dump(mode="json"))

    changed = _rest_api()
    changed.types = []
    decide_version(changed, previous=previous, when=_WHEN)

    assert previous.model_dump(mode="json") == before
