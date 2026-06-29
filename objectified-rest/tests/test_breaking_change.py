"""Tests for the breaking-change classifier SPI (MFI-3.3, #3744).

The acceptance criterion is that a classifier grades *a known breaking and a known
safe change* over the canonical diff, with the severities available to surface on the
diff view. These tests pin that for the format-agnostic built-in ruleset across
paradigms (REST, event, graph), exercise every rule branch (removed = breaking, added
optional = safe, added mandatory = dangerous, the per-attribute modification grades),
and verify the SPI plumbing: registry register/lookup/duplicate-guard, dispatch by
``target.format`` to a registered classifier, the worst-of aggregation and per-severity
tally, alignment of grades to the diff's changes, determinism, and JSON round-trip.
Everything here is pure (no DB/network), mirroring the module itself.
"""

import copy

import pytest

from app.breaking_change import (
    BreakingChangeClassifier,
    BuiltinBreakingChangeClassifier,
    ChangeClassification,
    ClassificationResult,
    Severity,
    available_breaking_change_formats,
    classify,
    classify_models,
    get_breaking_change_classifier,
    register_breaking_change_classifier,
)
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
from app.diff import ChangeKind, EntityCategory, diff

# ===========================================================================
# Fixtures
# ===========================================================================


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


def _classify(base: CanonicalApi, target: CanonicalApi) -> ClassificationResult:
    """Diff and classify, asserting grades line up 1:1 with the diff's changes."""
    model_diff = diff(base, target)
    result = classify(model_diff, base, target)
    assert len(result.classifications) == len(model_diff.changes)
    for change, grade in zip(model_diff.changes, result.classifications):
        assert (grade.category, grade.kind, grade.key) == (
            change.category,
            change.kind,
            change.key,
        )
    return result


def _grade_for(result: ClassificationResult, key: str) -> ChangeClassification:
    """Return the single classification for ``key`` (asserting exactly one)."""
    matches = [c for c in result.classifications if c.key == key]
    assert len(matches) == 1, f"expected exactly one grade for {key!r}, got {matches}"
    return matches[0]


# ===========================================================================
# Acceptance: a known breaking and a known safe change, per paradigm
# ===========================================================================


@pytest.mark.parametrize("factory", [_rest_api, _event_api, _graph_api])
def test_identical_models_classify_safe(factory):
    """No changes → no grades and an overall ``SAFE`` verdict, every paradigm."""
    result = _classify(factory(), factory())
    assert result.classifications == []
    assert result.overall_severity is Severity.SAFE
    assert result.breaking is False
    assert result.counts_by_severity == {}


def test_known_breaking_change_field_removed():
    """Removing a field is graded BREAKING — the headline acceptance case."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields = [target.types[0].fields[0]]  # drop Pet.name
    result = _classify(base, target)
    grade = _grade_for(result, "Pet.name")
    assert grade.kind is ChangeKind.REMOVED
    assert grade.severity is Severity.BREAKING
    assert grade.rule_id == "removed-entity"
    assert result.overall_severity is Severity.BREAKING
    assert result.breaking is True


def test_known_safe_change_optional_field_added():
    """Adding an optional (nullable) field is graded SAFE — the safe acceptance case."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields.append(
        CanonicalField(key="Pet.tag", name="tag", type=TypeRef(name="string"))
    )
    result = _classify(base, target)
    grade = _grade_for(result, "Pet.tag")
    assert grade.kind is ChangeKind.ADDED
    assert grade.severity is Severity.SAFE
    assert grade.rule_id == "added-entity"
    assert result.overall_severity is Severity.SAFE
    assert result.breaking is False


# ===========================================================================
# Built-in ruleset: additions
# ===========================================================================


def test_added_service_operation_message_type_are_safe():
    """Additive surface (service/operation/message/type) grades SAFE."""
    base = _graph_api()
    target = _graph_api()
    target.types.append(
        Type(
            key="Account",
            name="Account",
            kind=TypeKind.RECORD,
            fields=[
                CanonicalField(key="Account.id", name="id", type=TypeRef(name="ID")),
            ],
        )
    )
    target.services[0].operations.append(
        Operation(
            key="Query.account",
            name="account",
            kind=OperationKind.QUERY,
            messages=[
                Message(
                    key="Query.account#response",
                    role=MessageRole.RESPONSE,
                    payload=TypeRef(name="Account"),
                )
            ],
        )
    )
    result = _classify(base, target)
    for key in ("Account", "Query.account", "Query.account#response", "Account.id"):
        assert _grade_for(result, key).severity is Severity.SAFE
    assert result.overall_severity is Severity.SAFE


def test_added_mandatory_field_is_dangerous():
    """Adding a non-nullable field with no default grades DANGEROUS (breaks producers)."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields.append(
        CanonicalField(
            key="Pet.species",
            name="species",
            type=TypeRef(name="string", nullable=False),
        )
    )
    result = _classify(base, target)
    grade = _grade_for(result, "Pet.species")
    assert grade.severity is Severity.DANGEROUS
    assert grade.rule_id == "added-mandatory-field"
    assert result.overall_severity is Severity.DANGEROUS


def test_added_non_null_field_with_default_is_safe():
    """A non-nullable added field that carries a default is omittable, hence SAFE."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields.append(
        CanonicalField(
            key="Pet.species",
            name="species",
            type=TypeRef(name="string", nullable=False),
            default="unknown",
        )
    )
    result = _classify(base, target)
    assert _grade_for(result, "Pet.species").severity is Severity.SAFE


# ===========================================================================
# Built-in ruleset: modifications graded per moved attribute
# ===========================================================================


def test_field_type_narrowed_to_non_null_is_breaking():
    """A nullable field type narrowed to non-null grades BREAKING."""
    base = _graph_api()
    target = _graph_api()
    target.types[0].fields[1].type = TypeRef(name="String", nullable=False)  # User.email
    result = _classify(base, target)
    grade = _grade_for(result, "User.email")
    assert grade.kind is ChangeKind.MODIFIED
    assert grade.severity is Severity.BREAKING
    assert grade.rule_id == "modified-breaking"


def test_field_type_widened_to_nullable_is_safe():
    """A non-null field type widened to nullable (same underlying type) grades SAFE."""
    base = _graph_api()
    target = _graph_api()
    target.types[0].fields[0].type = TypeRef(name="ID", nullable=True)  # User.id ID! -> ID
    result = _classify(base, target)
    grade = _grade_for(result, "User.id")
    assert grade.kind is ChangeKind.MODIFIED
    assert grade.severity is Severity.SAFE


def test_field_retyped_is_breaking():
    """Changing the referenced named type grades BREAKING even keeping nullability."""
    base = _graph_api()
    target = _graph_api()
    target.types[0].fields[1].type = TypeRef(name="Int")  # email String -> Int
    result = _classify(base, target)
    assert _grade_for(result, "User.email").severity is Severity.BREAKING


def test_parameter_set_change_is_dangerous():
    """A change inside an operation's folded ``parameters`` list grades DANGEROUS.

    Parameters are not their own diff category — they fold into the operation's
    self-projection — so the baseline cannot tell an added-optional-parameter (safe)
    from a made-required-parameter (breaking) and conservatively flags the whole move
    for review, leaving the sharp call to a per-format classifier.
    """
    base = _rest_api()
    base.services[0].operations[0].parameters[0].required = False
    target = _rest_api()  # required=True
    result = _classify(base, target)
    grade = _grade_for(result, "GET /pets/{id}")
    assert grade.kind is ChangeKind.MODIFIED
    assert grade.severity is Severity.DANGEROUS
    assert grade.rule_id == "modified-dangerous"


def test_constraint_change_is_dangerous():
    """A constraint move grades DANGEROUS (compatible by the letter, review-worthy)."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields[0].constraints = Constraints(minimum=5)  # was minimum=1
    result = _classify(base, target)
    grade = _grade_for(result, "Pet.id")
    assert grade.severity is Severity.DANGEROUS
    assert grade.rule_id == "modified-dangerous"


def test_default_change_is_dangerous():
    """A default value move grades DANGEROUS."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields[1].default = "anon"  # Pet.name default unknown -> anon
    result = _classify(base, target)
    assert _grade_for(result, "Pet.name").severity is Severity.DANGEROUS


def test_route_move_is_breaking():
    """Changing an operation's http_path grades BREAKING."""
    base = _rest_api()
    target = _rest_api()
    target.services[0].operations[0].http_path = "/pets/{id}/details"
    result = _classify(base, target)
    assert _grade_for(result, "GET /pets/{id}").severity is Severity.BREAKING


def test_deprecation_is_dangerous_undeprecation_is_safe():
    """Deprecating a field grades DANGEROUS; un-deprecating grades SAFE."""
    base = _graph_api()
    target = _graph_api()
    target.types[0].fields[1].deprecated = True
    assert _grade_for(_classify(base, target), "User.email").severity is Severity.DANGEROUS

    base2 = _graph_api()
    base2.types[0].fields[1].deprecated = True
    target2 = _graph_api()  # deprecated=False
    assert _grade_for(_classify(base2, target2), "User.email").severity is Severity.SAFE


def test_channel_address_change_is_breaking():
    """Changing a channel's wire address grades BREAKING."""
    base = _event_api()
    target = _event_api()
    target.channels[0].address = "user/registered"
    result = _classify(base, target)
    assert _grade_for(result, "user/signedup").severity is Severity.BREAKING


def test_modified_grades_by_worst_attribute():
    """A modification touching a safe and a breaking attribute grades BREAKING."""
    base = _rest_api()
    target = _rest_api()
    op = target.services[0].operations[0]
    op.http_path = "/pets/{id}/v2"  # breaking
    op.tags = ["pets"]  # dangerous-ish/cosmetic
    result = _classify(base, target)
    grade = _grade_for(result, "GET /pets/{id}")
    assert grade.severity is Severity.BREAKING  # worst-of wins


# ===========================================================================
# Aggregation, counts, removal cascade
# ===========================================================================


def test_removing_a_service_cascades_to_breaking_grades():
    """Removing a whole service grades the service and each child BREAKING."""
    base = _rest_api()
    target = _rest_api()
    target.services = []
    result = _classify(base, target)
    for key in ("pets", "GET /pets/{id}", "GET /pets/{id}#response.200"):
        assert _grade_for(result, key).severity is Severity.BREAKING
    assert result.overall_severity is Severity.BREAKING
    # every itemized change here is a removal → breaking.
    assert set(result.counts_by_severity) == {"breaking"}


def test_counts_by_severity_tally():
    """The per-severity tally counts each grade exactly once."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields = [target.types[0].fields[0]]  # remove Pet.name -> breaking
    target.types[0].fields.append(  # add optional -> safe
        CanonicalField(key="Pet.tag", name="tag", type=TypeRef(name="string"))
    )
    target.types[0].fields[0].constraints = Constraints(minimum=9)  # Pet.id -> dangerous
    result = _classify(base, target)
    assert result.counts_by_severity == {"breaking": 1, "safe": 1, "dangerous": 1}
    assert sum(result.counts_by_severity.values()) == len(result.classifications)
    assert result.overall_severity is Severity.BREAKING


# ===========================================================================
# Dispatch, registry, and the SPI
# ===========================================================================


def test_classify_uses_builtin_when_no_format_pack_registered():
    """With no registered classifier, ``classify`` uses the built-in ruleset."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields = [target.types[0].fields[0]]
    result = classify(diff(base, target), base, target)
    assert result.classifier == "builtin"
    assert result.format == "openapi-3.1"


def test_classify_models_convenience_matches_diff_then_classify():
    """``classify_models`` equals ``classify(diff(...))``."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields = [target.types[0].fields[0]]
    assert classify_models(base, target) == classify(diff(base, target), base, target)


def test_register_lookup_and_available():
    """A registered classifier is dispatched by ``target.format`` and listed."""

    class _PassThroughClassifier(BreakingChangeClassifier, register=True):
        format = "test-fmt-3744"
        classifier_id = "test-passthrough"

        def classify_change(self, change, base, target):
            # Grade everything SAFE to prove dispatch reached this class, not builtin.
            return ChangeClassification(
                category=change.category,
                kind=change.kind,
                key=change.key,
                severity=Severity.SAFE,
                rule_id="test-allow",
                rationale="test classifier allows everything",
            )

    try:
        assert get_breaking_change_classifier("test-fmt-3744") is _PassThroughClassifier
        assert "test-fmt-3744" in available_breaking_change_formats()

        base = _rest_api()
        target = _rest_api()
        target.format = "test-fmt-3744"
        target.types[0].fields = [target.types[0].fields[0]]  # a removal
        result = classify(diff(base, target), base, target)
        assert result.classifier == "test-passthrough"
        # The custom classifier overrides the builtin: the removal grades SAFE.
        assert result.overall_severity is Severity.SAFE
        assert all(c.rule_id == "test-allow" for c in result.classifications)
    finally:
        from app.breaking_change import _CLASSIFIER_REGISTRY

        _CLASSIFIER_REGISTRY.pop("test-fmt-3744", None)


def test_register_requires_format():
    """Registering a classifier with an empty ``format`` raises."""

    class _NoFormat(BreakingChangeClassifier):
        def classify_change(self, change, base, target):  # pragma: no cover - not called
            raise NotImplementedError

    with pytest.raises(ValueError, match="non-empty `format`"):
        register_breaking_change_classifier(_NoFormat)


def test_register_duplicate_format_raises_but_same_class_is_idempotent():
    """A second class for one format raises; re-registering the same class is a no-op."""

    class _First(BreakingChangeClassifier):
        format = "dup-fmt-3744"

        def classify_change(self, change, base, target):  # pragma: no cover - not called
            raise NotImplementedError

    class _Second(BreakingChangeClassifier):
        format = "dup-fmt-3744"

        def classify_change(self, change, base, target):  # pragma: no cover - not called
            raise NotImplementedError

    try:
        register_breaking_change_classifier(_First)
        assert register_breaking_change_classifier(_First) is _First  # idempotent
        with pytest.raises(ValueError, match="already registered"):
            register_breaking_change_classifier(_Second)
    finally:
        from app.breaking_change import _CLASSIFIER_REGISTRY

        _CLASSIFIER_REGISTRY.pop("dup-fmt-3744", None)


def test_subclassing_builtin_inherits_baseline_and_overrides_one_rule():
    """A format pack can subclass the builtin, sharpening only what it needs."""

    class _SharperClassifier(BuiltinBreakingChangeClassifier):
        classifier_id = "sharper"

        def classify_change(self, change, base, target):
            grade = super().classify_change(change, base, target)
            # This format treats an added optional field as DANGEROUS, not SAFE.
            if change.kind is ChangeKind.ADDED and change.category is EntityCategory.FIELD:
                grade.severity = Severity.DANGEROUS
                grade.rule_id = "sharper-added-field"
            return grade

    base = _rest_api()
    target = _rest_api()
    target.types[0].fields.append(
        CanonicalField(key="Pet.tag", name="tag", type=TypeRef(name="string"))
    )
    classifier = _SharperClassifier()
    result = classifier.classify(diff(base, target), base, target)
    assert result.classifier == "sharper"
    grade = _grade_for(result, "Pet.tag")
    assert grade.severity is Severity.DANGEROUS  # overridden
    assert grade.rule_id == "sharper-added-field"


# ===========================================================================
# Determinism and serialization
# ===========================================================================


def test_classification_is_deterministic():
    """The same pair of models always yields identical grades."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields = [target.types[0].fields[0]]
    first = classify_models(base, copy.deepcopy(target))
    second = classify_models(base, copy.deepcopy(target))
    assert first.model_dump() == second.model_dump()


def test_result_round_trips_through_json():
    """ClassificationResult serializes and reloads losslessly (for JSONB persistence)."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields = [target.types[0].fields[0]]
    result = classify_models(base, target)
    reloaded = ClassificationResult.model_validate_json(result.model_dump_json())
    assert reloaded == result
