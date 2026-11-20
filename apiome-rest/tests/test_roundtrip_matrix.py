"""Round-trip conformance matrix tests — IXH-1.7 (#5093).

Proves the product claim *import once, emit in every format with honest
fidelity* by running every ``(shipped source format × shipped emit target)``
cell: import → fidelity predict → emit → re-import → ``canonical_diff`` →
reconcile against ``DROP``/``APPROX``/``SYNTH``. Unexplained diffs and
over-claiming ``OK`` findings fail; unsupported cells are recorded explicitly.

What this suite proves, in acceptance-criteria order:

* the published matrix covers every format→emit pair (no silent holes);
* every canonical difference is matched to a fidelity finding;
* a fidelity report that over-claims preservation fails;
* matrix results are a machine-readable artifact (+ Markdown for IXH-1.8).

Regenerate the artifact with
``pytest tests/test_roundtrip_matrix.py --update-roundtrip-matrix`` (or
``UPDATE_ROUNDTRIP_MATRIX=1``).
"""

from __future__ import annotations

import json
import re
from typing import List

import pytest
from corpus_adapter_support import valid_entries
from corpus_loader import Rung
from corpus_roundtrip import (
    ARTIFACT_PATH,
    KNOWN_ROUNDTRIP_XFAILS,
    KNOWN_UNSUPPORTED_CELLS,
    _import_entry,
    build_and_run_matrix,
    pick_representative,
    representatives_by_format,
    updating_matrix,
    write_matrix_artifact,
)

from app.canonical_model import ApiParadigm
from app.emitter import (
    CapabilityProfile,
    EmitterDescriptor,
    EmitterTarget,
    load_builtin_emitters,
)
from app.import_source import (
    CanonicalDiff,
    CanonicalDiffEntry,
    DiffChangeKind,
    load_builtin_import_sources,
)
from app.lossiness import (
    LossItem,
    LossinessKind,
    LossinessReport,
    LossinessSeverity,
)
from app.roundtrip_matrix import (
    MATRIX_VERSION,
    SAMPLE_EMIT_KEYS,
    MatrixCellResult,
    MatrixCellStatus,
    RoundTripMatrix,
    classify_cell,
    import_adapter_for_emit,
    normalize_format_key,
    production_emit_targets,
    reconcile,
    run_roundtrip,
)
from app.toolchain_selfcheck import missing_required_tools

load_builtin_import_sources()
load_builtin_emitters()


# ---------------------------------------------------------------------------
# Unit: reconcile / classify / aliases / representative
# ---------------------------------------------------------------------------


def _diff(*entries: CanonicalDiffEntry) -> CanonicalDiff:
    return CanonicalDiff(entries=list(entries))


def _report(*items: LossItem) -> LossinessReport:
    return LossinessReport(items=list(items))


def _loss(
    construct: str,
    kind: LossinessKind,
    *,
    message: str = "test",
) -> LossItem:
    return LossItem(
        construct_key=construct,
        kind=kind,
        severity=LossinessSeverity.WARN,
        message=message,
    )


def test_reconcile_empty_diff_passes() -> None:
    result = reconcile(_diff(), _report(_loss("User", LossinessKind.OK)))
    assert result.ok
    assert result.unexplained == []
    assert result.overclaims == []


def test_reconcile_removed_explained_by_drop() -> None:
    result = reconcile(
        _diff(
            CanonicalDiffEntry(entity="type", key="User", change=DiffChangeKind.REMOVED)
        ),
        _report(_loss("User", LossinessKind.DROP, message="cannot carry User")),
    )
    assert result.ok
    assert len(result.matched) == 1


def test_reconcile_removed_unexplained_fails() -> None:
    result = reconcile(
        _diff(
            CanonicalDiffEntry(entity="type", key="User", change=DiffChangeKind.REMOVED)
        ),
        _report(_loss("User", LossinessKind.OK)),
    )
    assert not result.ok
    assert result.unexplained[0].key == "User"
    assert result.overclaims[0].construct_key == "User"


def test_reconcile_added_explained_by_synth() -> None:
    result = reconcile(
        _diff(
            CanonicalDiffEntry(entity="type", key="Synthetic", change=DiffChangeKind.ADDED)
        ),
        _report(_loss("Synthetic", LossinessKind.SYNTH)),
    )
    assert result.ok


def test_reconcile_changed_explained_by_nested_drop() -> None:
    result = reconcile(
        _diff(
            CanonicalDiffEntry(entity="type", key="User", change=DiffChangeKind.CHANGED)
        ),
        _report(_loss("User.email", LossinessKind.DROP, message="email dropped")),
    )
    assert result.ok
    assert result.matched[0].finding.construct_key == "User.email"


def test_reconcile_changed_explained_by_approx() -> None:
    result = reconcile(
        _diff(
            CanonicalDiffEntry(entity="type", key="User", change=DiffChangeKind.CHANGED)
        ),
        _report(_loss("User", LossinessKind.APPROX)),
    )
    assert result.ok


def test_reconcile_ok_on_changed_is_overclaim() -> None:
    result = reconcile(
        _diff(
            CanonicalDiffEntry(entity="type", key="User", change=DiffChangeKind.CHANGED)
        ),
        _report(
            _loss("User", LossinessKind.OK),
            _loss("User.email", LossinessKind.DROP),
        ),
    )
    # Nested DROP explains CHANGED; OK on User itself is still an over-claim.
    assert result.matched
    assert any(o.construct_key == "User" for o in result.overclaims)
    assert not result.ok


def test_reconcile_nested_ok_under_removed_is_overclaim() -> None:
    result = reconcile(
        _diff(
            CanonicalDiffEntry(entity="type", key="User", change=DiffChangeKind.REMOVED)
        ),
        _report(
            _loss("User", LossinessKind.DROP),
            _loss("User.email", LossinessKind.OK),
        ),
    )
    assert result.matched
    assert any(o.construct_key == "User.email" for o in result.overclaims)
    assert not result.ok


def test_reconcile_matches_a_service_and_type_that_share_a_key() -> None:
    """A CHANGED service must not take the only DROP a REMOVED type of the same key needs (#7040).

    FHIR and OPC UA name a service and a type alike; a greedy first-fit join gave the service the
    type's DROP and left the type unexplained. The maximum matching seats each on its own finding.
    """
    result = reconcile(
        _diff(
            CanonicalDiffEntry(entity="service", key="Patient", change=DiffChangeKind.CHANGED),
            CanonicalDiffEntry(entity="type", key="Patient", change=DiffChangeKind.REMOVED),
        ),
        _report(
            _loss("Patient", LossinessKind.DROP),
            _loss("Patient", LossinessKind.APPROX),
        ),
    )
    assert result.ok
    by_entity = {m.entry.entity: m.finding.kind for m in result.matched}
    assert by_entity == {"service": LossinessKind.APPROX, "type": LossinessKind.DROP}


def test_reconcile_reseats_an_earlier_match_to_explain_a_later_entry() -> None:
    """An augmenting path moves an earlier entry to another finding when that frees one."""
    result = reconcile(
        _diff(
            # Sorted first, and both findings relate to it.
            CanonicalDiffEntry(entity="operation", key="A", change=DiffChangeKind.CHANGED),
            # Only the nested DROP relates to this one.
            CanonicalDiffEntry(entity="type", key="A.b", change=DiffChangeKind.REMOVED),
        ),
        _report(
            _loss("A.b", LossinessKind.DROP),
            _loss("A", LossinessKind.APPROX),
        ),
    )
    assert result.ok
    assert len(result.matched) == 2


def test_reconcile_uses_each_finding_once() -> None:
    """One DROP cannot explain two removals."""
    result = reconcile(
        _diff(
            CanonicalDiffEntry(entity="service", key="User", change=DiffChangeKind.REMOVED),
            CanonicalDiffEntry(entity="type", key="User", change=DiffChangeKind.REMOVED),
        ),
        _report(_loss("User", LossinessKind.DROP)),
    )
    assert not result.ok
    assert len(result.matched) == 1
    assert len(result.unexplained) == 1


def test_reconcile_root_matches_only_root_constructs() -> None:
    """The root ('') entry is explained by a '' or 'root' construct, never by an arbitrary key."""
    root_change = CanonicalDiffEntry(entity="root", key="", change=DiffChangeKind.CHANGED)
    assert not reconcile(_diff(root_change), _report(_loss("User", LossinessKind.APPROX))).ok
    assert reconcile(_diff(root_change), _report(_loss("root", LossinessKind.APPROX))).ok
    assert reconcile(_diff(root_change), _report(_loss("", LossinessKind.APPROX))).ok


def test_reconcile_prefix_lookup_does_not_match_a_sibling_key() -> None:
    """``Users`` is not nested under ``User``: only an exact key or a ``key.`` prefix relates."""
    result = reconcile(
        _diff(CanonicalDiffEntry(entity="type", key="User", change=DiffChangeKind.REMOVED)),
        _report(_loss("Users", LossinessKind.DROP), _loss("User-x", LossinessKind.DROP)),
    )
    assert not result.ok


def test_reconcile_handles_a_long_augmenting_chain() -> None:
    """A chain far longer than the interpreter's recursion limit still matches fully."""
    size = 3000
    # Entry i relates to findings i and i+1 (via the nested key); the greedy choice takes finding i
    # for every entry, and the last one needs the whole chain re-seated by one augmenting path.
    entries = [
        CanonicalDiffEntry(entity="type", key=f"K{i:05d}", change=DiffChangeKind.CHANGED) for i in range(size)
    ]
    items = [_loss(f"K{i:05d}.x", LossinessKind.APPROX) for i in range(size)]
    result = reconcile(_diff(*entries), _report(*items))
    assert result.ok
    assert len(result.matched) == size


def test_import_adapter_for_emit_aliases() -> None:
    assert import_adapter_for_emit("openapi", "openapi-3.1") == "openapi"
    assert import_adapter_for_emit("protobuf", "proto3") == "grpc"
    assert import_adapter_for_emit("asyncapi", "asyncapi-3") == "asyncapi"
    assert import_adapter_for_emit("apiblueprint", "apiblueprint") == "apiblueprint"
    assert import_adapter_for_emit("sample", "sample-noop") is None
    assert normalize_format_key(" API-Blueprint ") == "api-blueprint"


def test_production_emit_targets_exclude_sample() -> None:
    targets = production_emit_targets()
    keys = {t.descriptor.key for t in targets}
    formats = {t.descriptor.format for t in targets}
    assert not (keys & SAMPLE_EMIT_KEYS)
    assert not (formats & SAMPLE_EMIT_KEYS)
    assert "openapi" in keys
    assert len(targets) >= 30


def test_classify_cell_unsupported_without_reimport_adapter() -> None:
    fake = EmitterTarget(
        descriptor=EmitterDescriptor(
            key="no-reimport",
            format="no-reimport-format-zzz",
            label="Fake",
            description="no adapter",
            icon="file",
            paradigm=ApiParadigm.REST,
            multi_file=False,
            needs_toolchain=False,
            available=True,
            unavailable_reason=None,
        ),
        capability_profile=CapabilityProfile(),
        options_schema={},
        default_options={},
    )
    cell = classify_cell("openapi", fake)
    assert cell is not None
    assert cell.status is MatrixCellStatus.UNSUPPORTED
    assert "No import adapter" in (cell.reason or "")


def test_pick_representative_prefers_typical() -> None:
    by_fmt = representatives_by_format()
    openapi_entries = [e for e in valid_entries() if e.format == "openapi"]
    typical = [e for e in openapi_entries if e.rung is Rung.TYPICAL]
    if typical:
        rep = pick_representative(openapi_entries)
        assert rep is not None
        assert rep.rung is Rung.TYPICAL
    assert "openapi" in by_fmt
    assert by_fmt["openapi"] is not None


def test_matrix_to_markdown_and_json_roundtrip() -> None:
    matrix = RoundTripMatrix(
        matrix_version=MATRIX_VERSION,
        source_formats=["openapi", "avro"],
        emit_keys=["openapi", "avro"],
        cells=[
            MatrixCellResult(
                source_format="openapi",
                emit_key="openapi",
                emit_format="openapi-3.1",
                status=MatrixCellStatus.PASS,
            ),
            MatrixCellResult(
                source_format="openapi",
                emit_key="avro",
                emit_format="avro",
                status=MatrixCellStatus.FAIL,
                reason="unexplained",
            ),
            MatrixCellResult(
                source_format="avro",
                emit_key="openapi",
                emit_format="openapi-3.1",
                status=MatrixCellStatus.UNSUPPORTED,
                reason="demo",
            ),
            MatrixCellResult(
                source_format="avro",
                emit_key="avro",
                emit_format="avro",
                status=MatrixCellStatus.SKIPPED,
                reason="tools",
            ),
        ],
    )
    md = matrix.to_markdown()
    assert "openapi" in md and "avro" in md
    assert "P" in md and "F" in md
    payload = json.loads(matrix.to_json())
    assert payload["matrix_version"] == MATRIX_VERSION
    assert len(payload["cells"]) == 4


# ---------------------------------------------------------------------------
# Full matrix: completeness + reconcile gate + artifact
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def roundtrip_matrix() -> RoundTripMatrix:
    """Run the full matrix once per module (expensive; shared across tests)."""
    return build_and_run_matrix()


def test_matrix_covers_every_format_emit_pair(roundtrip_matrix: RoundTripMatrix) -> None:
    """Every (corpus format × production emit target) cell is present — no holes."""
    reps = representatives_by_format()
    targets = production_emit_targets()
    expected = {(fmt, t.descriptor.key) for fmt in reps for t in targets}
    actual = {(c.source_format, c.emit_key) for c in roundtrip_matrix.cells}
    assert actual == expected, (
        f"matrix holes or extras: missing={sorted(expected - actual)[:10]} "
        f"extra={sorted(actual - expected)[:10]}"
    )
    assert SAMPLE_EMIT_KEYS.isdisjoint(set(roundtrip_matrix.emit_keys))
    assert len(roundtrip_matrix.cells) == len(reps) * len(targets)


def test_matrix_cells_are_not_silent_failures(roundtrip_matrix: RoundTripMatrix) -> None:
    """Failing cells must be xfail-listed; pass/unsupported/skipped/xfail are fine."""
    bad: List[str] = []
    for cell in roundtrip_matrix.cells:
        if cell.status is MatrixCellStatus.FAIL:
            bad.append(
                f"{cell.cell_id}: {cell.reason} "
                f"(unexplained={len(cell.unexplained)} overclaims={len(cell.overclaims)})"
            )
    if bad:
        preview = "\n".join(bad[:40])
        more = f"\n... and {len(bad) - 40} more" if len(bad) > 40 else ""
        pytest.fail(
            f"{len(bad)} matrix cell(s) failed reconcile. Add to "
            f"KNOWN_ROUNDTRIP_XFAILS with a reason, or fix the fidelity/emitter:\n"
            f"{preview}{more}"
        )


#: Both the committed matrix artifact and the golden corpus describe a runtime that has the
#: hard-required bundled toolchain (FMT-1.3, #5414) — the container image and CI both install it.
#: On a machine that never ran ``scripts/install_dev_toolchain.sh`` the AsyncAPI rows come back
#: ``skipped`` instead: an environment difference, not artifact drift. Say so and skip, rather
#: than failing with advice ("regenerate with UPDATE_ROUNDTRIP_MATRIX=1") that would overwrite
#: the artifact with the developer's own missing toolchain.
_MISSING_REQUIRED_TOOLS = missing_required_tools()
_TOOLCHAIN_SKIP_REASON = (
    "the required bundled toolchain is not installed here ("
    + ", ".join(_MISSING_REQUIRED_TOOLS)
    + "); run apiome-rest/scripts/install_dev_toolchain.sh. The committed artifact describes a "
    "runtime that has it, so comparing against it here would report an environment difference "
    "as drift."
)


@pytest.mark.skipif(bool(_MISSING_REQUIRED_TOOLS), reason=_TOOLCHAIN_SKIP_REASON)
def test_matrix_artifact_complete_and_stable(
    roundtrip_matrix: RoundTripMatrix,
    request: pytest.FixtureRequest,
) -> None:
    """Machine-readable artifact covers the grid; regenerate with the update flag."""
    if updating_matrix(request):
        write_matrix_artifact(roundtrip_matrix)
        assert ARTIFACT_PATH.is_file()
        return

    assert ARTIFACT_PATH.is_file(), (
        f"Missing {ARTIFACT_PATH}; regenerate with "
        "`UPDATE_ROUNDTRIP_MATRIX=1 pytest tests/test_roundtrip_matrix.py`"
    )
    stored = RoundTripMatrix.model_validate_json(ARTIFACT_PATH.read_text(encoding="utf-8"))
    assert stored.matrix_version == MATRIX_VERSION
    assert set(stored.source_formats) == set(roundtrip_matrix.source_formats)
    assert set(stored.emit_keys) == set(roundtrip_matrix.emit_keys)
    assert len(stored.cells) == len(roundtrip_matrix.cells)

    live = {(c.source_format, c.emit_key): c.status for c in roundtrip_matrix.cells}
    gold = {(c.source_format, c.emit_key): c.status for c in stored.cells}
    drift = {
        key: (gold[key], live[key])
        for key in live
        if gold.get(key) != live[key]
    }
    if drift:
        sample = "\n".join(
            f"  {src}->{emit}: artifact={old.value} live={new.value}"
            for (src, emit), (old, new) in list(drift.items())[:20]
        )
        pytest.fail(
            f"{len(drift)} cell status(es) drifted from {ARTIFACT_PATH}. "
            f"If intentional, regenerate with UPDATE_ROUNDTRIP_MATRIX=1.\n{sample}"
        )


def test_same_format_openapi_cell_is_not_unsupported(
    roundtrip_matrix: RoundTripMatrix,
) -> None:
    """OpenAPI → OpenAPI must be runnable (pass/fail/xfail/skipped), never unsupported."""
    cell = roundtrip_matrix.cell_map().get(("openapi", "openapi"))
    assert cell is not None
    assert cell.status is not MatrixCellStatus.UNSUPPORTED


def test_xfail_map_entries_refer_to_real_cells(roundtrip_matrix: RoundTripMatrix) -> None:
    """KNOWN_ROUNDTRIP_XFAILS must not rot into references to missing cells."""
    index = roundtrip_matrix.cell_map()
    orphan = [key for key in KNOWN_ROUNDTRIP_XFAILS if key not in index]
    assert not orphan, f"xfail entries with no cell: {orphan}"


# ---------------------------------------------------------------------------
# COA-1.4 (#7040): the Arazzo cells — deliberate refusals and the xfail ratchet
# ---------------------------------------------------------------------------

#: How many strict xfails involve Arazzo after COA-1.4. The number only goes down: a fix deletes
#: its entry and lowers this, and a new Arazzo xfail fails here (the issue's "none is added").
ARAZZO_XFAIL_CEILING = 29


def _arazzo_cells(cells) -> List[tuple]:
    return sorted(key for key in cells if "arazzo" in key)


def test_arazzo_xfails_only_shrink() -> None:
    """The Arazzo row and column hold at most :data:`ARAZZO_XFAIL_CEILING` strict xfails."""
    arazzo = _arazzo_cells(KNOWN_ROUNDTRIP_XFAILS)
    assert len(arazzo) <= ARAZZO_XFAIL_CEILING, (
        f"{len(arazzo)} Arazzo xfails exceed the COA-1.4 ceiling of {ARAZZO_XFAIL_CEILING}: fix the cell "
        "or explain the loss in the fidelity report instead of listing it"
    )


def test_every_arazzo_xfail_names_a_ticket() -> None:
    """Each remaining Arazzo xfail says which ticket owns it (``#<number>``)."""
    unnamed = [
        key for key in _arazzo_cells(KNOWN_ROUNDTRIP_XFAILS) if not re.search(r"#\d+", KNOWN_ROUNDTRIP_XFAILS[key])
    ]
    assert not unnamed, f"Arazzo xfails without a ticket: {unnamed}"


def test_deliberate_unsupported_cells_are_not_also_xfails() -> None:
    """A cell is either a deliberate refusal or a strict xfail, never both."""
    assert not set(KNOWN_UNSUPPORTED_CELLS) & set(KNOWN_ROUNDTRIP_XFAILS)
    assert all(re.search(r"#\d+", reason) for reason in KNOWN_UNSUPPORTED_CELLS.values())


def test_deliberate_unsupported_cells_appear_unsupported(roundtrip_matrix: RoundTripMatrix) -> None:
    """The matrix records each deliberate refusal as ``unsupported`` with its documented reason."""
    index = roundtrip_matrix.cell_map()
    for key, reason in KNOWN_UNSUPPORTED_CELLS.items():
        cell = index.get(key)
        assert cell is not None, f"deliberate cell {key} is not in the matrix"
        assert cell.status is MatrixCellStatus.UNSUPPORTED
        assert cell.reason == reason


@pytest.mark.parametrize(
    "source_format,emit_key",
    sorted(KNOWN_UNSUPPORTED_CELLS),
    ids=[f"{src}->{emit}" for src, emit in sorted(KNOWN_UNSUPPORTED_CELLS)],
)
def test_deliberate_unsupported_cell_is_still_refused(source_format: str, emit_key: str) -> None:
    """Each deliberate cell's export really is refused, so the list cannot hide a runnable cell.

    The cell is run outside the matrix's unsupported short-circuit: it must fail at the emit step
    (the emitter's precondition), not pass and not fail later. A target that learns to export the
    source fails here until its entry leaves :mod:`roundtrip_unsupported`.
    """
    entry = representatives_by_format(
        [e for e in valid_entries() if e.format == source_format]
    ).get(source_format)
    if entry is None:
        pytest.skip(f"no runnable {source_format} representative here (known bugs or missing tools)")
    target = next(t for t in production_emit_targets() if t.descriptor.key == emit_key)
    model = _import_entry(entry)
    cell = run_roundtrip(model, target, source_format=source_format, corpus_path=entry.path)
    assert cell.status is MatrixCellStatus.FAIL, f"{source_format}->{emit_key} now {cell.status.value}"
    assert (cell.reason or "").startswith("Emit failed:"), cell.reason
