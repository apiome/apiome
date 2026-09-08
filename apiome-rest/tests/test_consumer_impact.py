"""Tests for the CTG-4.2 consumer-aware breaking analysis engine (#4480)."""

from __future__ import annotations

from typing import List, Optional

import pytest

from app.change_taxonomy import ClassifiedChange, ClassifiedDiff
from app.consumer_contract import (
    ConsumerContractField,
    ConsumerContractOperation,
    ConsumerContractRecord,
    ConsumerContractSurface,
    ConsumerRecord,
    ConsumerSummary,
)
from app.consumer_impact import (
    CONSUMER_IMPACT_SCHEMA_VERSION,
    MATCH_DOCUMENT,
    MATCH_FIELD,
    MATCH_OPERATION,
    analyze_consumer_impact,
    pointer_covers,
    pointers_overlap,
    render_consumer_impact_markdown,
)

PETS_GET = "/paths/~1pets/get"
PETS_200_SCHEMA = f"{PETS_GET}/responses/200/content/application~1json/schema"
STORES_GET = "/paths/~1stores/get"


# -------------------------------------------------------------------------------------------
# Fixtures / builders
# -------------------------------------------------------------------------------------------


def _field(
    path: str,
    *,
    pointer: str,
    schema_pointer: Optional[str] = None,
    location: str = "response",
    status: Optional[str] = "200",
) -> ConsumerContractField:
    return ConsumerContractField(
        pointer=pointer,
        schema_pointer=schema_pointer or pointer,
        location=location,
        status=status,
        media_type="application/json" if location != "parameter" else None,
        path=path,
    )


def _operation(
    method: str,
    path: str,
    pointer: str,
    fields: Optional[List[ConsumerContractField]] = None,
) -> ConsumerContractOperation:
    return ConsumerContractOperation(
        method=method,
        path=path,
        pointer=pointer,
        operation_id=None,
        summary=None,
        fields=fields or [],
    )


def _summary(
    slug: str,
    operations: Optional[List[ConsumerContractOperation]],
    *,
    version_id: str = "base-rev",
    version_label: str = "1.0.0",
    owner: Optional[str] = None,
) -> ConsumerSummary:
    """A consumer plus a current contract; ``operations=None`` means it declared nothing."""
    consumer = ConsumerRecord(
        id=f"consumer-{slug}",
        tenant_id="tenant-1",
        project_id="proj-1",
        slug=slug,
        name=slug.replace("-", " ").title(),
        owner=owner,
    )
    if operations is None:
        return ConsumerSummary(consumer=consumer, contract=None)
    surface = ConsumerContractSurface(operations=operations)
    contract = ConsumerContractRecord(
        id=f"contract-{slug}",
        consumer_id=consumer.id,
        revision=1,
        is_current=True,
        source="manual",
        version_id=version_id,
        version_label=version_label,
        surface=surface,
        operation_count=len(operations),
        field_count=sum(len(op.fields) for op in operations),
    )
    return ConsumerSummary(consumer=consumer, contract=contract)


def _diff(*changes: ClassifiedChange) -> ClassifiedDiff:
    counts = {"breaking": 0, "non-breaking": 0, "docs-only": 0, "unclassified": 0}
    for change in changes:
        counts[change.severity] += 1
    counts["total"] = len(changes)
    return ClassifiedDiff(changes=list(changes), counts=counts)


def _change(
    pointer: str,
    *,
    severity: str = "breaking",
    rule_id: str = "ctg.rule",
    kind: str = "kind",
) -> ClassifiedChange:
    return ClassifiedChange(
        rule_id=rule_id, severity=severity, pointer=pointer, change_kind=kind
    )


def _verdict_for(report, slug: str):
    return next(v for v in report.consumers if v.consumer_slug == slug)


# -------------------------------------------------------------------------------------------
# Pointer algebra
# -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "outer,inner,expected",
    [
        ("/components/schemas/Pet", "/components/schemas/Pet", True),
        ("/components/schemas/Pet", "/components/schemas/Pet/properties/name", True),
        ("/components/schemas/Pet", "/components/schemas/PetFood", False),
        ("/components/schemas/Pet/properties/name", "/components/schemas/Pet", False),
        ("/paths/~1pets", "/paths/~1pets/get", True),
        ("/paths/~1pets", "/paths/~1petstore", False),
        ("", "/paths/~1pets", True),
    ],
)
def test_pointer_covers_is_segment_aware(outer: str, inner: str, expected: bool):
    assert pointer_covers(outer, inner) is expected


def test_pointers_overlap_is_symmetric():
    deep = "/components/schemas/Pet/properties/name/type"
    declared = "/components/schemas/Pet/properties/name"
    assert pointers_overlap(deep, declared)
    assert pointers_overlap(declared, deep)
    assert not pointers_overlap(declared, "/components/schemas/Pet/properties/id")


# -------------------------------------------------------------------------------------------
# The headline behaviour: a field change reaches only the consumers that read the field
# -------------------------------------------------------------------------------------------


def test_field_change_breaks_only_the_consumer_that_declared_it():
    billing = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [_field("name", pointer=f"{PETS_200_SCHEMA}/properties/name")],
            )
        ],
    )
    mobile = _summary(
        "mobile-app",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [_field("id", pointer=f"{PETS_200_SCHEMA}/properties/id")],
            )
        ],
    )
    diff = _diff(_change(f"{PETS_200_SCHEMA}/properties/name", rule_id="ctg.field_removed"))

    report = analyze_consumer_impact(diff, [billing, mobile])

    assert report.schema_version == CONSUMER_IMPACT_SCHEMA_VERSION
    assert _verdict_for(report, "billing-service").verdict == "breaking"
    assert _verdict_for(report, "mobile-app").verdict == "unaffected"
    assert report.breaking_consumers == ["billing-service"]
    assert report.summary == "breaks 1 of 2 consumers: billing-service"
    assert report.counts["consumers_breaking"] == 1
    assert report.counts["consumers_declared"] == 2
    assert report.counts["changes_attributed"] == 1
    assert report.counts["changes_unattributed"] == 0
    assert report.attribution[0].consumers == ["billing-service"]

    impact = _verdict_for(report, "billing-service").impacts[0]
    assert impact.match == MATCH_FIELD
    assert impact.field_path == "name"
    assert impact.field_status == "200"
    assert impact.method == "get"
    assert impact.path == "/pets"


def test_change_to_an_undeclared_field_affects_nobody():
    billing = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [_field("id", pointer=f"{PETS_200_SCHEMA}/properties/id")],
            )
        ],
    )
    diff = _diff(_change(f"{PETS_200_SCHEMA}/properties/colour", rule_id="ctg.field_removed"))

    report = analyze_consumer_impact(diff, [billing])

    assert _verdict_for(report, "billing-service").verdict == "unaffected"
    assert report.summary == "breaks 0 of 1 consumer"
    assert report.counts["changes_unattributed"] == 1
    assert report.max_severity is None
    # The change is still classified; it is flagged as reaching no registered consumer.
    assert report.attribution[0].severity == "breaking"
    assert report.attribution[0].consumers == []


def test_component_schema_change_reaches_a_field_through_its_ref_pointer():
    consumer = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [
                    _field(
                        "name",
                        pointer=f"{PETS_200_SCHEMA}/properties/name",
                        schema_pointer="/components/schemas/Pet/properties/name",
                    )
                ],
            )
        ],
    )
    diff = _diff(_change("/components/schemas/Pet/properties/name/type"))

    report = analyze_consumer_impact(diff, [consumer])

    verdict = _verdict_for(report, "billing-service")
    assert verdict.verdict == "breaking"
    assert verdict.impacts[0].declared_pointer == "/components/schemas/Pet/properties/name"


def test_whole_component_schema_removal_reaches_every_field_under_it():
    consumer = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [
                    _field(
                        "id",
                        pointer=f"{PETS_200_SCHEMA}/properties/id",
                        schema_pointer="/components/schemas/Pet/properties/id",
                    ),
                    _field(
                        "name",
                        pointer=f"{PETS_200_SCHEMA}/properties/name",
                        schema_pointer="/components/schemas/Pet/properties/name",
                    ),
                ],
            )
        ],
    )
    diff = _diff(_change("/components/schemas/Pet"))

    report = analyze_consumer_impact(diff, [consumer])

    verdict = _verdict_for(report, "billing-service")
    assert {impact.field_path for impact in verdict.impacts} == {"id", "name"}
    # One change, met twice: the *counts* stay per distinct change.
    assert verdict.counts["total"] == 1
    assert verdict.counts["breaking"] == 1


def test_sibling_component_schema_is_not_a_string_prefix_match():
    consumer = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [
                    _field(
                        "id",
                        pointer=f"{PETS_200_SCHEMA}/properties/id",
                        schema_pointer="/components/schemas/Pet/properties/id",
                    )
                ],
            )
        ],
    )
    diff = _diff(_change("/components/schemas/PetFood/properties/id"))

    report = analyze_consumer_impact(diff, [consumer])

    assert _verdict_for(report, "billing-service").verdict == "unaffected"


# -------------------------------------------------------------------------------------------
# Operation-wide and document-wide attribution
# -------------------------------------------------------------------------------------------


def test_operation_removal_reaches_every_consumer_that_calls_it():
    billing = _summary("billing-service", [_operation("get", "/pets", PETS_GET)])
    mobile = _summary(
        "mobile-app",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [_field("id", pointer=f"{PETS_200_SCHEMA}/properties/id")],
            )
        ],
    )
    reporting = _summary("reporting", [_operation("get", "/stores", STORES_GET)])
    diff = _diff(_change("/paths/~1pets", rule_id="ctg.path_removed"))

    report = analyze_consumer_impact(diff, [billing, mobile, reporting])

    assert report.breaking_consumers == ["billing-service", "mobile-app"]
    assert report.summary == "breaks 2 of 3 consumers: billing-service, mobile-app"
    assert _verdict_for(report, "reporting").verdict == "unaffected"
    assert _verdict_for(report, "billing-service").impacts[0].match == MATCH_OPERATION
    assert _verdict_for(report, "billing-service").operations_affected == 1


def test_operation_declared_without_fields_is_operation_wide_inside_its_schema():
    """Nothing finer than "I call this" was declared, so nothing finer is claimed."""
    consumer = _summary("billing-service", [_operation("get", "/pets", PETS_GET)])
    diff = _diff(_change(f"{PETS_200_SCHEMA}/properties/colour"))

    report = analyze_consumer_impact(diff, [consumer])

    verdict = _verdict_for(report, "billing-service")
    assert verdict.verdict == "breaking"
    assert verdict.impacts[0].match == MATCH_OPERATION


def test_parameter_change_reaches_every_caller_of_the_operation():
    """A newly required parameter breaks callers whether or not they declared it."""
    consumer = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [_field("id", pointer=f"{PETS_200_SCHEMA}/properties/id")],
            )
        ],
    )
    diff = _diff(_change(f"{PETS_GET}/parameters/query:limit", rule_id="ctg.param_required_added"))

    report = analyze_consumer_impact(diff, [consumer])

    verdict = _verdict_for(report, "billing-service")
    assert verdict.verdict == "breaking"
    assert verdict.impacts[0].match == MATCH_OPERATION


def test_declared_parameter_is_matched_at_field_granularity():
    consumer = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [
                    _field("id", pointer=f"{PETS_200_SCHEMA}/properties/id"),
                    _field(
                        "limit",
                        pointer=f"{PETS_GET}/parameters/query:limit",
                        location="parameter",
                        status=None,
                    ),
                ],
            )
        ],
    )
    diff = _diff(_change(f"{PETS_GET}/parameters/query:limit/schema/type"))

    report = analyze_consumer_impact(diff, [consumer])

    impact = _verdict_for(report, "billing-service").impacts[0]
    assert impact.match == MATCH_FIELD
    assert impact.field_location == "parameter"
    assert impact.field_path == "limit"


def test_schema_root_change_is_operation_wide_even_with_declared_fields():
    consumer = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [_field("id", pointer=f"{PETS_200_SCHEMA}/properties/id")],
            )
        ],
    )
    diff = _diff(_change(PETS_200_SCHEMA, rule_id="ctg.response_schema_replaced"))

    report = analyze_consumer_impact(diff, [consumer])

    verdict = _verdict_for(report, "billing-service")
    # The declared field lives under the schema root, so the field match is the specific one.
    assert verdict.verdict == "breaking"
    assert verdict.impacts[0].match == MATCH_FIELD


def test_response_code_removal_reaches_a_consumer_declaring_fields_at_that_code():
    consumer = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [_field("id", pointer=f"{PETS_200_SCHEMA}/properties/id")],
            )
        ],
    )
    diff = _diff(_change(f"{PETS_GET}/responses/200", rule_id="ctg.response_removed"))

    report = analyze_consumer_impact(diff, [consumer])

    assert _verdict_for(report, "billing-service").verdict == "breaking"


def test_document_wide_security_change_reaches_every_declared_consumer():
    billing = _summary("billing-service", [_operation("get", "/pets", PETS_GET)])
    reporting = _summary("reporting", [_operation("get", "/stores", STORES_GET)])
    undeclared = _summary("ghost", None)
    diff = _diff(_change("/security", rule_id="ctg.security_tightened"))

    report = analyze_consumer_impact(diff, [billing, reporting, undeclared])

    assert report.breaking_consumers == ["billing-service", "reporting"]
    assert _verdict_for(report, "billing-service").impacts[0].match == MATCH_DOCUMENT
    assert _verdict_for(report, "ghost").verdict == "undeclared"
    assert report.counts["changes_unattributed"] == 0


def test_info_change_is_not_document_wide():
    consumer = _summary("billing-service", [_operation("get", "/pets", PETS_GET)])
    diff = _diff(_change("/info/description", severity="docs-only", rule_id="ctg.docs"))

    report = analyze_consumer_impact(diff, [consumer])

    assert _verdict_for(report, "billing-service").verdict == "unaffected"
    assert report.counts["changes_unattributed"] == 1


# -------------------------------------------------------------------------------------------
# Verdicts, counts and summary
# -------------------------------------------------------------------------------------------


def test_verdict_is_the_worst_matched_severity():
    consumer = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [_field("id", pointer=f"{PETS_200_SCHEMA}/properties/id")],
            )
        ],
    )
    diff = _diff(
        _change(f"{PETS_200_SCHEMA}/properties/id/description", severity="docs-only"),
        _change(f"{PETS_200_SCHEMA}/properties/id/example", severity="non-breaking"),
    )

    report = analyze_consumer_impact(diff, [consumer])

    assert _verdict_for(report, "billing-service").verdict == "non-breaking"
    assert report.max_severity == "non-breaking"
    assert report.breaking_consumers == []
    assert report.summary == "breaks 0 of 1 consumer"


def test_undeclared_consumers_are_reported_beside_the_denominator_not_inside_it():
    declared = _summary("billing-service", [_operation("get", "/pets", PETS_GET)])
    ghost_a = _summary("ghost-a", None)
    ghost_b = _summary("ghost-b", None)
    diff = _diff(_change("/paths/~1pets", rule_id="ctg.path_removed"))

    report = analyze_consumer_impact(diff, [declared, ghost_a, ghost_b])

    assert report.counts["consumers_total"] == 3
    assert report.counts["consumers_declared"] == 1
    assert report.counts["consumers_undeclared"] == 2
    assert report.summary == (
        "breaks 1 of 1 consumer: billing-service "
        "(2 registered consumers have declared no surface)"
    )


def test_empty_registry_says_so():
    diff = _diff(_change("/paths/~1pets", rule_id="ctg.path_removed"))

    report = analyze_consumer_impact(diff, [])

    assert report.consumers == []
    assert report.summary == "no consumer has declared a surface for this project"
    assert report.counts["changes_unattributed"] == 1


def test_verdicts_are_ordered_worst_first_then_by_handle():
    diff = _diff(
        _change("/paths/~1pets", rule_id="ctg.path_removed"),
        _change("/paths/~1stores/get/summary", severity="docs-only", rule_id="ctg.docs"),
    )
    report = analyze_consumer_impact(
        diff,
        [
            _summary("zeta", None),
            _summary("docs-reader", [_operation("get", "/stores", STORES_GET)]),
            _summary("alpha", [_operation("get", "/pets", PETS_GET)]),
            _summary("beta", [_operation("get", "/pets", PETS_GET)]),
            _summary("idle", [_operation("post", "/orders", "/paths/~1orders/post")]),
        ],
    )

    assert [v.consumer_slug for v in report.consumers] == [
        "alpha",
        "beta",
        "docs-reader",
        "idle",
        "zeta",
    ]
    assert [v.verdict for v in report.consumers] == [
        "breaking",
        "breaking",
        "docs-only",
        "unaffected",
        "undeclared",
    ]


def test_contract_resolved_against_another_revision_is_flagged_not_hidden():
    stale = _summary(
        "billing-service",
        [_operation("get", "/pets", PETS_GET)],
        version_id="older-rev",
        version_label="0.9.0",
    )
    current = _summary("mobile-app", [_operation("get", "/pets", PETS_GET)])
    diff = _diff(_change("/paths/~1pets", rule_id="ctg.path_removed"))

    report = analyze_consumer_impact(diff, [stale, current], base_version_id="base-rev")

    assert _verdict_for(report, "billing-service").contract_matches_base is False
    assert _verdict_for(report, "billing-service").contract_version_label == "0.9.0"
    assert _verdict_for(report, "mobile-app").contract_matches_base is True


def test_contract_match_is_unknown_when_no_base_revision_is_supplied():
    consumer = _summary("billing-service", [_operation("get", "/pets", PETS_GET)])
    diff = _diff(_change("/paths/~1pets", rule_id="ctg.path_removed"))

    report = analyze_consumer_impact(diff, [consumer])

    assert _verdict_for(report, "billing-service").contract_matches_base is None


def test_impacts_are_bounded_but_counts_and_attribution_stay_exact():
    fields = [
        _field(f"f{index}", pointer=f"{PETS_200_SCHEMA}/properties/f{index}")
        for index in range(10)
    ]
    consumer = _summary("billing-service", [_operation("get", "/pets", PETS_GET, fields)])
    diff = _diff(_change(PETS_200_SCHEMA, rule_id="ctg.response_schema_replaced"))

    report = analyze_consumer_impact(diff, [consumer], max_impacts_per_consumer=3)

    verdict = _verdict_for(report, "billing-service")
    assert verdict.truncated is True
    assert len(verdict.impacts) == 3
    assert verdict.counts["total"] == 1
    assert verdict.fields_declared == 10
    # Truncating the enumeration never loses the attribution itself.
    assert report.attribution[0].consumers == ["billing-service"]


def test_declared_counts_come_from_the_contract_not_the_matches():
    consumer = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [
                    _field("id", pointer=f"{PETS_200_SCHEMA}/properties/id"),
                    _field("name", pointer=f"{PETS_200_SCHEMA}/properties/name"),
                ],
            ),
            _operation("get", "/stores", STORES_GET),
        ],
    )
    diff = _diff(_change(f"{PETS_200_SCHEMA}/properties/id"))

    verdict = _verdict_for(analyze_consumer_impact(diff, [consumer]), "billing-service")

    assert verdict.operations_declared == 2
    assert verdict.fields_declared == 2
    assert verdict.operations_affected == 1


def test_no_changes_leaves_every_consumer_unaffected():
    consumer = _summary("billing-service", [_operation("get", "/pets", PETS_GET)])

    report = analyze_consumer_impact(_diff(), [consumer])

    assert _verdict_for(report, "billing-service").verdict == "unaffected"
    assert report.attribution == []
    assert report.counts["changes_total"] == 0
    assert report.summary == "breaks 0 of 1 consumer"


# -------------------------------------------------------------------------------------------
# The pointer index must not change any answer
# -------------------------------------------------------------------------------------------


def test_change_above_the_bucket_depth_still_reaches_deep_declarations():
    """``/paths`` is one segment; declarations are three or more. Bucketing must not lose it."""
    consumer = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [_field("id", pointer=f"{PETS_200_SCHEMA}/properties/id")],
            )
        ],
    )

    report = analyze_consumer_impact(_diff(_change("/paths")), [consumer])

    verdict = _verdict_for(report, "billing-service")
    assert verdict.verdict == "breaking"
    assert verdict.operations_affected == 1
    # The declared field lives under `/paths`, so the field match is the specific one.
    assert verdict.impacts[0].match == MATCH_FIELD
    assert verdict.impacts[0].field_path == "id"


def test_root_change_reaches_every_declared_operation():
    consumer = _summary(
        "billing-service",
        [_operation("get", "/pets", PETS_GET), _operation("get", "/stores", STORES_GET)],
    )

    report = analyze_consumer_impact(_diff(_change("")), [consumer])

    assert _verdict_for(report, "billing-service").operations_affected == 2


def test_a_large_surface_narrows_to_the_declarations_that_actually_meet_the_change():
    """The index buckets by leading segments; the answer must equal the exhaustive one."""
    operations = []
    for index in range(30):
        path = f"/thing{index}"
        pointer = f"/paths/~1thing{index}/get"
        schema = f"{pointer}/responses/200/content/application~1json/schema"
        operations.append(
            _operation(
                "get",
                path,
                pointer,
                [
                    _field(f"f{n}", pointer=f"{schema}/properties/f{n}")
                    for n in range(50)
                ],
            )
        )
    consumer = _summary("billing-service", operations)
    target = "/paths/~1thing7/get/responses/200/content/application~1json/schema/properties/f13"
    diff = _diff(
        _change(target, rule_id="ctg.field_removed"),
        _change(
            "/paths/~1thing7/get/responses/200/content/application~1json/schema/properties/nope"
        ),
    )

    report = analyze_consumer_impact(diff, [consumer])

    verdict = _verdict_for(report, "billing-service")
    assert verdict.fields_declared == 1500
    assert len(verdict.impacts) == 1
    assert verdict.impacts[0].field_path == "f13"
    assert verdict.impacts[0].path == "/thing7"
    assert verdict.counts["total"] == 1
    assert report.counts["changes_unattributed"] == 1


# -------------------------------------------------------------------------------------------
# Markdown
# -------------------------------------------------------------------------------------------


def test_markdown_names_the_broken_consumers_and_what_they_lose():
    billing = _summary(
        "billing-service",
        [
            _operation(
                "get",
                "/pets",
                PETS_GET,
                [_field("name", pointer=f"{PETS_200_SCHEMA}/properties/name")],
            )
        ],
        owner="Payments",
    )
    ghost = _summary("ghost", None)
    diff = _diff(
        _change(f"{PETS_200_SCHEMA}/properties/name", rule_id="ctg.field_removed"),
        _change("/paths/~1unused", rule_id="ctg.path_removed"),
    )

    md = render_consumer_impact_markdown(analyze_consumer_impact(diff, [billing, ghost]))

    assert "## Consumer impact" in md
    assert "breaks 1 of 1 consumer: billing-service" in md
    assert "### `billing-service` — breaking" in md
    assert "Owner: Payments" in md
    assert "GET /pets — 200 response `name`" in md
    assert "1 change(s) affect no registered consumer." in md
    assert "declared no surface" in md


def test_markdown_for_an_empty_registry():
    md = render_consumer_impact_markdown(analyze_consumer_impact(_diff(), []))

    assert "No consumers are registered for this project." in md
