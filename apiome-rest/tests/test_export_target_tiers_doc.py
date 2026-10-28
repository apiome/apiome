"""Tests for the generated target × fidelity-tier table on *Export catalog items* (X7, #6228).

The first test is the drift gate: it regenerates the table in memory and compares the committed
page with it, so a registry or fidelity-engine change that is not followed by
``scripts/generate_export_target_tiers_doc.py`` turns CI red.

The rest check that the table says true things: every target ``GET /export/targets`` offers has a
row, each cell is the tier the engine computes (or *not offered* with the emitter's own reason),
and the region is replaced without touching the hand-written prose around it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.emitter import describe_emit_targets, get_emitter, load_builtin_emitters
from app.export_fidelity import ExportFidelityTier, build_target_fidelity
from app.export_target_tiers_doc import (
    BEGIN_MARKER,
    END_MARKER,
    EXPORT_TARGET_TIERS_PAGE,
    REGENERATE_COMMAND,
    apply_target_tier_table,
    collect_target_tier_rows,
    reference_sources,
    render_target_tier_table,
)
from app.format_matrix import INTERNAL_FORMAT_KEYS

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE_PATH = REPO_ROOT / EXPORT_TARGET_TIERS_PAGE

#: Every value a tier cell may hold.
_CELL_VALUES = {tier.value for tier in ExportFidelityTier} | {"not offered"}


@pytest.fixture(scope="module")
def page() -> str:
    """The committed page's text."""
    assert PAGE_PATH.is_file(), f"missing guide page: {PAGE_PATH}"
    return PAGE_PATH.read_text(encoding="utf-8")


def _offered_labels() -> set[str]:
    """Labels of the targets the export dialog offers (internal targets excluded)."""
    load_builtin_emitters()
    return {
        target.descriptor.label
        for target in describe_emit_targets()
        if target.descriptor.key not in INTERNAL_FORMAT_KEYS
    }


# ===========================================================================
# The drift gate
# ===========================================================================


def test_committed_table_matches_a_fresh_generation(page: str) -> None:
    """The committed region is exactly what the generator writes today."""
    assert apply_target_tier_table(page) == page, (
        f"The target tier table in {EXPORT_TARGET_TIERS_PAGE} is stale. Regenerate with: {REGENERATE_COMMAND}"
    )


def test_page_holds_the_markers_once(page: str) -> None:
    """One begin marker, then one end marker — the shape :func:`apply_target_tier_table` needs."""
    assert page.count(BEGIN_MARKER) == 1
    assert page.count(END_MARKER) == 1
    assert page.index(BEGIN_MARKER) < page.index(END_MARKER)


# ===========================================================================
# What the table says
# ===========================================================================


def test_every_offered_target_has_exactly_one_row() -> None:
    """The rows are the targets ``GET /export/targets`` offers, once each, sorted by label."""
    rows = collect_target_tier_rows()
    labels = [row.label for row in rows]
    assert set(labels) == _offered_labels()
    assert len(labels) == len(set(labels))
    assert labels == sorted(labels, key=str.casefold)


def test_every_row_has_one_known_cell_per_source() -> None:
    """Each row has a cell per reference source, and each cell is a tier or *not offered*."""
    columns = len(reference_sources())
    for row in collect_target_tier_rows():
        assert len(row.tiers) == columns, row.label
        assert set(row.tiers) <= _CELL_VALUES, row.label
        # A refusal always comes with its reason, and a reason only with a refusal.
        assert bool(row.reasons) == ("not offered" in row.tiers), row.label


def test_cells_are_the_engines_tiers() -> None:
    """Each tier cell is what :func:`build_target_fidelity` returns for that source."""
    load_builtin_emitters()
    sources = reference_sources()
    by_label = {row.label: row for row in collect_target_tier_rows(sources)}
    for target in describe_emit_targets():
        if target.descriptor.key in INTERNAL_FORMAT_KEYS:
            continue
        emitter_cls = get_emitter(target.descriptor.format)
        row = by_label[target.descriptor.label]
        for source, cell in zip(sources, row.tiers):
            refusal = emitter_cls.source_unsupported_reason(source.api)
            if refusal:
                assert cell == "not offered"
                assert refusal in row.reasons
            else:
                assert cell == build_target_fidelity(source.api, emitter_cls).tier.value


def test_known_answers() -> None:
    """Spot checks a reader would notice if they went wrong."""
    by_label = {row.label: row for row in collect_target_tier_rows()}
    # OpenAPI carries the REST source and the types cleanly.
    assert by_label["OpenAPI 3.1"].tiers[0] == "lossless"
    assert by_label["OpenAPI 3.1"].tiers[3] == "lossless"
    # AsyncAPI carries the event source cleanly.
    assert by_label["AsyncAPI 3.1"].tiers[2] == "lossless"
    # A schema-only target keeps only the types of an API with operations.
    assert by_label["Apache Avro"].tiers[0] == "types-only"
    # A gateway needs an HTTP operation; a source-bound format needs its own source.
    assert by_label["Kong Declarative Config"].tiers == ("lossy", "not offered", "not offered", "not offered")
    assert set(by_label["EDI X12"].tiers) == {"not offered"}
    # XML-RPC needs an operation with no HTTP method or path — only the RPC source has one.
    assert by_label["XML-RPC"].tiers[1] != "not offered"


def test_rendering_is_deterministic() -> None:
    """Two renderings are byte-identical, or the drift gate could not hold."""
    assert render_target_tier_table() == render_target_tier_table()


def test_rendered_table_names_every_source_and_target() -> None:
    """The header names each source, and each target has a table row."""
    rendered = render_target_tier_table()
    assert rendered.startswith(BEGIN_MARKER)
    assert rendered.endswith(END_MARKER)
    for source in reference_sources():
        assert source.heading in rendered
    for label in _offered_labels():
        assert f"| {label.replace('|', chr(92) + '|')} |" in rendered


# ===========================================================================
# Applying the region
# ===========================================================================


def test_apply_keeps_the_prose_around_the_region() -> None:
    """Only the marked region changes; the text before and after it is kept byte for byte."""
    text = f"# Before\n\n{BEGIN_MARKER}\nstale\n{END_MARKER}\n\nAfter.\n"
    updated = apply_target_tier_table(text)
    assert updated.startswith("# Before\n\n")
    assert updated.endswith("\n\nAfter.\n")
    assert "stale" not in updated
    assert apply_target_tier_table(updated) == updated


@pytest.mark.parametrize(
    "text",
    [
        "no markers at all",
        f"{END_MARKER} then {BEGIN_MARKER}",
        f"{BEGIN_MARKER} {BEGIN_MARKER} {END_MARKER}",
        f"{BEGIN_MARKER} {END_MARKER} {END_MARKER}",
    ],
)
def test_apply_refuses_a_page_without_one_ordered_region(text: str) -> None:
    """A missing, reversed or doubled marker is an error, never a silent partial rewrite."""
    with pytest.raises(ValueError):
        apply_target_tier_table(text)
