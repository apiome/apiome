"""Export conformance matrix gate — X1 (#6222).

Every corpus source family × every production export target, through the catalog export path
(see :mod:`export_conformance`). This suite fails on:

* any **crash** — an emitter that raised instead of exporting or refusing with a reason;
* a **silent-loss** pair (empty fidelity report, round-trip drift) not in the tracked ledger
  :data:`export_conformance_ledger.KNOWN_SILENT_LOSS`, and a ledger entry that no longer
  reproduces (so the ledger only ever shrinks);
* a cell whose status drifted from the checked-in matrix (``tests/golden/export_conformance/``).

Regenerate the matrix and the ledger with
``UPDATE_EXPORT_CONFORMANCE=1 pytest tests/test_export_conformance_matrix.py``.
"""

from __future__ import annotations

import json

import pytest
from export_conformance import (
    ARTIFACT_DIR,
    MATRIX_VERSION,
    STATUSES,
    build_export_conformance_matrix,
    matrix_markdown,
    silent_loss_cells,
    updating_export_conformance,
    write_artifacts,
)
from export_conformance_ledger import KNOWN_SILENT_LOSS

from app.roundtrip_matrix import production_emit_targets


@pytest.fixture(scope="module")
def matrix():
    return build_export_conformance_matrix()


def test_the_matrix_covers_every_family_and_target(matrix):
    targets = {t.descriptor.key for t in production_emit_targets()}
    assert set(matrix["targets"]) == targets
    cells = {(c["family"], c["target"]) for c in matrix["cells"]}
    assert len(cells) == len(matrix["cells"]) == len(matrix["families"]) * len(targets)
    assert all(c["status"] in STATUSES for c in matrix["cells"])


def test_no_pair_crashes(matrix):
    crashes = [f"{c['family']} -> {c['target']}: {c['reason']}" for c in matrix["cells"] if c["status"] == "crash"]
    assert not crashes, f"{len(crashes)} export crash(es):\n" + "\n".join(crashes[:30])


def test_every_refusal_and_loss_says_why(matrix):
    for cell in matrix["cells"]:
        if cell["status"] == "refused":
            assert cell["reason"], cell
        if cell["status"] == "lossy":
            assert sum(cell["loss_counts"].values()) > 0, cell


def test_silent_loss_is_tracked_and_the_ledger_only_shrinks(matrix, request):
    if updating_export_conformance(request):
        pytest.skip("regenerating the ledger")
    live = silent_loss_cells(matrix)
    new = sorted(set(live) - set(KNOWN_SILENT_LOSS))
    assert not new, (
        f"{len(new)} new silent-loss pair(s) — an export that loses data without saying so. Make the "
        "fidelity report name the loss, fix the emitter, or refuse the pair with a reason:\n"
        + "\n".join(f"  {f} -> {t}: {live[(f, t)]}" for f, t in new[:30])
    )
    skipped = {(c["family"], c["target"]) for c in matrix["cells"] if c["status"] == "skipped"}
    stale = sorted(set(KNOWN_SILENT_LOSS) - set(live) - skipped)
    assert not stale, (
        f"{len(stale)} ledger entr(ies) no longer lose data silently — regenerate the ledger "
        "(UPDATE_EXPORT_CONFORMANCE=1) to drop them:\n" + "\n".join(f"  {f} -> {t}" for f, t in stale[:30])
    )


def test_the_checked_in_matrix_is_current(matrix, request):
    if updating_export_conformance(request):
        write_artifacts(matrix)
        return
    stored_path = ARTIFACT_DIR / "matrix.json"
    assert stored_path.is_file(), (
        "Missing matrix; run UPDATE_EXPORT_CONFORMANCE=1 pytest tests/test_export_conformance_matrix.py"
    )
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    assert stored["matrix_version"] == MATRIX_VERSION
    gold = {(c["family"], c["target"]): c["status"] for c in stored["cells"]}
    drift = [
        f"  {c['family']} -> {c['target']}: matrix={gold.get((c['family'], c['target']))} live={c['status']}"
        for c in matrix["cells"]
        # A cell skipped here for a tool this runner lacks is not drift.
        if gold.get((c["family"], c["target"])) != c["status"] and c["status"] != "skipped"
    ]
    assert not drift, (
        f"{len(drift)} cell(s) drifted from the checked-in matrix; if intended, regenerate with "
        "UPDATE_EXPORT_CONFORMANCE=1.\n" + "\n".join(drift[:30])
    )
    assert (ARTIFACT_DIR / "matrix.md").read_text(encoding="utf-8").startswith("# Export conformance matrix")


def test_markdown_renders_counts_and_grid():
    tiny = {
        "matrix_version": MATRIX_VERSION,
        "families": ["graphql"],
        "targets": ["openapi", "kong"],
        "counts": {s: 0 for s in STATUSES} | {"ok": 1, "refused": 1},
        "cells": [
            {"family": "graphql", "target": "openapi", "status": "ok", "reason": None},
            {"family": "graphql", "target": "kong", "status": "refused", "reason": "no HTTP operation"},
        ],
    }
    md = matrix_markdown(tiny)
    assert "| ok | 1 |" in md and "| graphql | ok | R |" in md
