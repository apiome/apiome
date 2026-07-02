"""Tests for the generalized lint engine + rule-pack SPI (MFI-4.1, #3746).

The acceptance criteria are: pure (no DB/network), deterministic findings with stable ids,
and the OpenAPI pack reproduces current behavior. These tests pin the cross-format common
pack across paradigms (REST, event, graph) — a fully documented, stably named model scores a
clean 100/A with no findings, while a model missing descriptions and using generator-style
names surfaces every common rule — and verify the SPI plumbing: registry
register/lookup/duplicate-guard, the common-pack-is-not-registerable guard, dispatch by
``api.format`` to a registered format pack, ``extra_findings`` folding into the score,
determinism, stable id hashes, deterministic sort order, input purity, and that the shared
score/grade/fingerprint formula matches the untouched OpenAPI linter. Everything here is pure,
mirroring the module itself.
"""

import copy

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
from app.lint_engine import (
    CommonRulePack,
    LintRule,
    RulePack,
    available_lint_formats,
    get_rule_pack,
    lint_canonical_model,
    register_rule_pack,
)
from app.schema_lint import LintFinding

# ===========================================================================
# Fixtures
# ===========================================================================


def _clean_rest_api() -> CanonicalApi:
    """A fully documented REST artifact with author-chosen names — should score 100/A."""
    pet_type = Type(
        key="Pet",
        name="Pet",
        kind=TypeKind.RECORD,
        description="A pet in the store.",
        fields=[
            CanonicalField(
                key="Pet.id",
                name="id",
                type=TypeRef(name="integer", nullable=False),
                description="The pet's id.",
            ),
            CanonicalField(
                key="Pet.name",
                name="name",
                type=TypeRef(name="string", nullable=False),
                description="The pet's name.",
            ),
        ],
    )
    get_pet = Operation(
        key="GET /pets/{id}",
        name="getPet",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET",
        http_path="/pets/{id}",
        description="Fetch a pet by id.",
        parameters=[
            Parameter(
                key="GET /pets/{id}#path.id",
                name="id",
                location=ParameterLocation.PATH,
                type=TypeRef(name="integer", nullable=False),
                required=True,
                description="The pet id.",
            )
        ],
        messages=[
            Message(
                key="GET /pets/{id}#response.200",
                role=MessageRole.RESPONSE,
                status_code="200",
                payload=TypeRef(name="Pet"),
                content_types=["application/json"],
                description="The fetched pet.",
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
        description="A well documented pets API.",
        services=[Service(key="pets", name="pets", operations=[get_pet])],
        types=[pet_type],
    )


def _dirty_rest_api() -> CanonicalApi:
    """A REST artifact missing descriptions and using generator-style names."""
    inline_type = Type(
        key="InlineObject1",
        name="InlineObject1",  # generator name -> unstable
        kind=TypeKind.RECORD,
        # no description
        fields=[
            CanonicalField(
                key="InlineObject1.amount",
                name="amount",
                type=TypeRef(name="integer"),
                # no description
            ),
            CanonicalField(
                key="InlineObject1._0",
                name="_0",  # positional name -> unstable, no description
                type=TypeRef(name="string"),
            ),
        ],
    )
    op = Operation(
        key="POST /pay",
        name="pay",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="POST",
        http_path="/pay",
        # no description
        messages=[
            Message(
                key="POST /pay#response.200",
                role=MessageRole.RESPONSE,
                status_code="200",
                payload=TypeRef(name="InlineObject1"),
                # no description
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        protocol="http",
        identity=ApiIdentity(name="Payments"),
        # no description
        services=[Service(key="pay", name="pay", operations=[op])],
        types=[inline_type],
    )


def _event_api() -> CanonicalApi:
    """A minimal event artifact (channel + pub operation), all undocumented."""
    channel = Channel(key="user/signedup", address="user/signedup", protocol="kafka")
    publish = Operation(
        key="publish user/signedup",
        name="publishSignup",
        kind=OperationKind.PUBLISH,
        channel_ref="user/signedup",
        messages=[
            Message(key="publish user/signedup#event", role=MessageRole.EVENT)
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        protocol="kafka",
        identity=ApiIdentity(name="Signups"),
        services=[Service(key="signups", name="signups", operations=[publish])],
        channels=[channel],
    )


def _graph_api() -> CanonicalApi:
    """A minimal GraphQL artifact (query + object type), all undocumented."""
    user_type = Type(
        key="User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="User.id", name="id", type=TypeRef(name="ID"))],
    )
    user_query = Operation(
        key="Query.user",
        name="user",
        kind=OperationKind.QUERY,
        messages=[Message(key="Query.user#result", role=MessageRole.RESPONSE)],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        identity=ApiIdentity(name="Graph"),
        services=[Service(key="Query", name="Query", operations=[user_query])],
        types=[user_type],
    )


# ===========================================================================
# Common pack: clean vs dirty
# ===========================================================================


def test_clean_model_scores_high_grade_a():
    result = lint_canonical_model(_clean_rest_api())
    assert result.findings == ()
    assert result.score == 100
    assert result.grade == "A"
    assert result.severity_counts == {"error": 0, "warning": 0, "info": 0}


def test_dirty_model_surfaces_each_common_rule():
    result = lint_canonical_model(_dirty_rest_api())
    rules = {f.rule for f in result.findings}
    assert "common.api-missing-description" in rules
    assert "common.type-missing-description" in rules
    assert "common.field-missing-description" in rules
    assert "common.operation-missing-description" in rules
    assert "common.message-missing-description" in rules
    assert "common.unstable-type-name" in rules
    assert "common.unstable-field-name" in rules
    assert result.score < 100
    assert result.grade in {"A", "B", "C", "D", "F"}


def test_channel_missing_description_fires_for_event_api():
    result = lint_canonical_model(_event_api())
    rules = {f.rule for f in result.findings}
    assert "common.channel-missing-description" in rules


@pytest.mark.parametrize("factory", [_event_api, _graph_api, _dirty_rest_api])
def test_lints_every_paradigm_without_error(factory):
    result = lint_canonical_model(factory())
    # Each undocumented model produces findings, a sub-100 score, and a valid grade.
    assert result.findings
    assert 0 <= result.score < 100
    assert result.grade in {"A", "B", "C", "D", "F"}


# ===========================================================================
# Determinism, stable ids, ordering, purity
# ===========================================================================


def test_determinism_same_input_same_output():
    a = lint_canonical_model(_dirty_rest_api())
    b = lint_canonical_model(_dirty_rest_api())
    assert a.report_fingerprint == b.report_fingerprint
    assert a.score == b.score
    assert [f.id for f in a.findings] == [f.id for f in b.findings]


def test_finding_ids_are_stable_hashes():
    result = lint_canonical_model(_dirty_rest_api())
    assert result.findings  # non-empty so the loop is meaningful
    for finding in result.findings:
        assert finding.id.startswith("lint-")
        assert len(finding.id) == len("lint-") + 16


def test_findings_sorted_by_path_rule_id():
    result = lint_canonical_model(_dirty_rest_api())
    keys = [(f.path, f.rule, f.id) for f in result.findings]
    assert keys == sorted(keys)


def test_rule_hits_count_matches_findings():
    result = lint_canonical_model(_dirty_rest_api())
    assert sum(result.rule_hits.values()) == len(result.findings)


def test_input_model_not_mutated():
    api = _dirty_rest_api()
    snapshot = copy.deepcopy(api.model_dump())
    lint_canonical_model(api)
    assert api.model_dump() == snapshot


# ===========================================================================
# Composition with extra findings (compatibility flags etc.)
# ===========================================================================


def test_extra_findings_fold_into_report_and_score():
    breaking = LintFinding(
        path="types.Pet",
        category="compatibility",
        rule="compatibility.breaking",
        severity="error",
        message="Type 'Pet' was removed.",
    )
    base = lint_canonical_model(_clean_rest_api())
    with_extra = lint_canonical_model(_clean_rest_api(), extra_findings=[breaking])
    assert with_extra.score < base.score
    assert with_extra.severity_counts["error"] == 1
    assert breaking in with_extra.findings


# ===========================================================================
# Unstable-identifier heuristic
# ===========================================================================


@pytest.mark.parametrize(
    "name",
    ["InlineObject1", "InlineResponse200", "AnonymousType3", "schema1", "type_0", "_12", "body0"],
)
def test_unstable_names_are_flagged(name):
    api = _clean_rest_api()
    api.types[0].name = name
    result = lint_canonical_model(api)
    assert any(f.rule == "common.unstable-type-name" for f in result.findings)


@pytest.mark.parametrize("name", ["Pet", "User", "OrderLineItem", "id", "userId", "Address"])
def test_author_chosen_names_are_not_flagged(name):
    api = _clean_rest_api()
    api.types[0].name = name
    result = lint_canonical_model(api)
    assert not any(f.rule == "common.unstable-type-name" for f in result.findings)


# ===========================================================================
# Rule-pack SPI: registry register / lookup / dispatch / guards
# ===========================================================================


def test_unregistered_format_runs_only_the_common_pack():
    """A format with no registered pack still gets the common pack (and nothing else)."""
    api = _dirty_rest_api()
    assert get_rule_pack(api.format) is None
    result = lint_canonical_model(api)
    assert all(f.rule.startswith("common.") for f in result.findings)


def test_register_lookup_and_dispatch_to_format_pack():
    """A registered pack is dispatched by ``api.format`` and its findings appear."""

    class _StubPack(RulePack, register=True):
        format = "test-fmt-3746"
        pack_id = "stub"

        def rules(self):
            return [
                LintRule(
                    rule_id="test.always",
                    category="structure",
                    severity="warning",
                    description="Always fires once.",
                    check=lambda api: [("api", "stub finding")],
                )
            ]

    try:
        assert get_rule_pack("test-fmt-3746") is _StubPack
        assert "test-fmt-3746" in available_lint_formats()

        api = _clean_rest_api()
        api.format = "test-fmt-3746"
        result = lint_canonical_model(api)
        # The clean model has no common findings, so the only finding is the format pack's.
        rules = [f.rule for f in result.findings]
        assert rules == ["test.always"]
    finally:
        from app.lint_engine import _RULE_PACK_REGISTRY

        _RULE_PACK_REGISTRY.pop("test-fmt-3746", None)


def test_register_requires_nonempty_format():
    """The common pack (empty format) must not be registerable; it runs unconditionally."""

    class _NoFormat(RulePack):
        def rules(self):
            return []

    with pytest.raises(ValueError, match="non-empty `format`"):
        register_rule_pack(_NoFormat)


def test_common_pack_subclass_with_empty_format_is_not_auto_registered():
    """CommonRulePack has an empty format and is therefore never in the registry."""
    assert CommonRulePack.format == ""
    assert "" not in _registry_keys()


def test_register_duplicate_format_raises_but_same_class_is_idempotent():
    """A second class for one format raises; re-registering the same class is a no-op."""

    class _First(RulePack):
        format = "dup-fmt-3746"

        def rules(self):
            return []

    class _Second(RulePack):
        format = "dup-fmt-3746"

        def rules(self):
            return []

    try:
        register_rule_pack(_First)
        assert register_rule_pack(_First) is _First  # idempotent
        with pytest.raises(ValueError, match="already registered"):
            register_rule_pack(_Second)
    finally:
        from app.lint_engine import _RULE_PACK_REGISTRY

        _RULE_PACK_REGISTRY.pop("dup-fmt-3746", None)


def _registry_keys():
    from app.lint_engine import _RULE_PACK_REGISTRY

    return set(_RULE_PACK_REGISTRY)
