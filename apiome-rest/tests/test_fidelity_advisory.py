"""Unit tests for the user-facing fidelity advisory — MFX-2.4 (#3841).

Pins the ticket's acceptance criteria:

* the message **reflects real counts** (dropped / approximated / synthesized are
  read from the report, and the count woven into the sentence is their sum);
* it is **shown when the export is lossy** and **hidden when lossless**;
* the ``min_severity`` **threshold** can relax the advisory to warn-and-above;
* the copy is **deterministic and derived purely** from the report + target label,
  and its wording is pinned so any drift from the canonical string source is caught
  (the TypeScript consumers render this same wording verbatim).
"""

from app.fidelity_advisory import (
    ADVISORY_HEADLINE_TEMPLATE,
    ADVISORY_MESSAGE_TEMPLATE,
    LOSSLESS_HEADLINE_TEMPLATE,
    LOSSLESS_MESSAGE_TEMPLATE,
    ExportAdvisory,
    build_export_advisory,
)
from app.lossiness import (
    LossinessKind,
    LossinessReport,
    LossinessReportBuilder,
    LossinessSeverity,
)


def _lossy_report() -> LossinessReport:
    """A report with a critical DROP, a warn APPROX, an info APPROX, and a SYNTH."""
    b = LossinessReportBuilder()
    b.add(
        "Payment.oneOf",
        LossinessKind.DROP,
        LossinessSeverity.CRITICAL,
        "discriminated union cannot be represented",
    )
    b.add(
        "User.email",
        LossinessKind.APPROX,
        LossinessSeverity.WARN,
        "pattern constraint moved to a comment",
        target_mapping="constraint → doc comment",
    )
    b.add(
        "User.nickname",
        LossinessKind.APPROX,
        LossinessSeverity.INFO,
        "minLength moved to a comment",
    )
    b.add(
        "Order.id",
        LossinessKind.SYNTH,
        LossinessSeverity.INFO,
        "field number auto-assigned",
        target_mapping="field number 3",
    )
    b.ok("Order.total")
    return b.build()


def _lossless_report() -> LossinessReport:
    """A report where every construct carried faithfully (all OK)."""
    b = LossinessReportBuilder()
    b.ok("User.email")
    b.ok("User.name")
    return b.build()


# ---------------------------------------------------------------------------
# Shown-when-lossy + real counts
# ---------------------------------------------------------------------------


def test_lossy_export_shows_advisory_with_real_counts() -> None:
    advisory = build_export_advisory(_lossy_report(), "Protobuf")

    assert advisory.show is True
    assert advisory.target_format == "Protobuf"
    # 1 DROP + 2 APPROX + 1 SYNTH = 4 affected; counts read straight off the report.
    assert advisory.dropped == 1
    assert advisory.approximated == 2
    assert advisory.synthesized == 1
    assert advisory.affected == 4
    # Worst non-OK severity is CRITICAL → dismiss-to-proceed.
    assert advisory.severity is LossinessSeverity.CRITICAL
    assert advisory.requires_ack is True


def test_message_wording_is_canonical_and_pins_the_count() -> None:
    advisory = build_export_advisory(_lossy_report(), "Protobuf")

    expected_message = (
        "Exporting to Protobuf may lose some fidelity. The destination format "
        "can't represent everything in this API, so 4 constructs will be dropped "
        "or approximated — review the fidelity report before downloading."
    )
    assert advisory.message == expected_message
    assert advisory.message == ADVISORY_MESSAGE_TEMPLATE.format(
        format="Protobuf", constructs="4 constructs"
    )
    assert advisory.headline == "Fidelity notice — exporting to Protobuf may lose detail."
    assert advisory.headline == ADVISORY_HEADLINE_TEMPLATE.format(format="Protobuf")


def test_single_construct_is_singular() -> None:
    b = LossinessReportBuilder()
    b.add("Payment.oneOf", LossinessKind.DROP, LossinessSeverity.WARN, "dropped")
    advisory = build_export_advisory(b.build(), "Avro")

    assert advisory.affected == 1
    assert "so 1 construct will be dropped" in advisory.message
    assert "1 constructs" not in advisory.message


# ---------------------------------------------------------------------------
# Hidden-when-lossless
# ---------------------------------------------------------------------------


def test_lossless_export_suppresses_advisory() -> None:
    advisory = build_export_advisory(_lossless_report(), "OpenAPI 3.1")

    assert advisory.show is False
    assert advisory.severity is None
    assert advisory.requires_ack is False
    assert advisory.affected == 0
    # Reassurance copy is still carried for a surface that wants to affirm the clean
    # round-trip, but the surface gates on ``show``.
    assert advisory.message == LOSSLESS_MESSAGE_TEMPLATE.format(format="OpenAPI 3.1")
    assert advisory.headline == LOSSLESS_HEADLINE_TEMPLATE.format(format="OpenAPI 3.1")


def test_empty_report_is_lossless() -> None:
    advisory = build_export_advisory(LossinessReport(), "OpenAPI 3.1")
    assert advisory.show is False
    assert advisory.affected == 0


# ---------------------------------------------------------------------------
# Severity threshold
# ---------------------------------------------------------------------------


def test_info_only_loss_shows_by_default_but_hides_at_warn_threshold() -> None:
    b = LossinessReportBuilder()
    b.add("User.desc", LossinessKind.APPROX, LossinessSeverity.INFO, "cosmetic")
    report = b.build()

    # Default threshold (INFO): any real loss shows.
    shown = build_export_advisory(report, "GraphQL")
    assert shown.show is True
    assert shown.severity is LossinessSeverity.INFO
    assert shown.requires_ack is False

    # Raised threshold (WARN): the cosmetic info-only loss is suppressed, but the
    # counts still reflect it.
    hidden = build_export_advisory(
        report, "GraphQL", min_severity=LossinessSeverity.WARN
    )
    assert hidden.show is False
    assert hidden.approximated == 1
    assert hidden.affected == 1


def test_warn_threshold_still_shows_when_a_warn_loss_is_present() -> None:
    b = LossinessReportBuilder()
    b.add("User.desc", LossinessKind.APPROX, LossinessSeverity.INFO, "cosmetic")
    b.add("User.role", LossinessKind.DROP, LossinessSeverity.WARN, "dropped")
    advisory = build_export_advisory(
        b.build(), "GraphQL", min_severity=LossinessSeverity.WARN
    )
    assert advisory.show is True
    assert advisory.severity is LossinessSeverity.WARN
    assert advisory.requires_ack is False


# ---------------------------------------------------------------------------
# Purity / determinism
# ---------------------------------------------------------------------------


def test_advisory_is_deterministic() -> None:
    report = _lossy_report()
    first = build_export_advisory(report, "Protobuf")
    second = build_export_advisory(report, "Protobuf")
    assert first.model_dump() == second.model_dump()
    # Round-trips through JSON losslessly for the REST surfacing (MFX-2.5).
    assert ExportAdvisory.model_validate_json(first.model_dump_json()) == first
