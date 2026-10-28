"""Export conformance matrix — X1 (#6222).

Every catalog **source family** with a corpus fixture × every **production export target**,
through the same path a catalog export takes (:func:`app.export_dispatch.dispatch_from_source`,
real emit, severe conversions confirmed). Each cell lands in exactly one status:

* ``ok`` — exported, the fidelity report records no loss, and (where the target can be read back)
  re-importing the artifact shows no drift;
* ``lossy`` — exported with a fidelity report that names what was dropped / approximated /
  synthesized (``loss_counts``);
* ``refused`` — refused with a reason (HTTP 4xx ``ExportError``: a source-bound target, a source
  with nothing the target writes, an unavailable toolchain…);
* ``silent-loss`` — exported with an **empty** fidelity report while the round trip shows the
  artifact drifted from the source: data lost without saying so;
* ``crash`` — anything else raised: an emitter bug;
* ``skipped`` — the cell cannot run here (no runnable corpus fixture, or a tool missing).

The gate (``tests/test_export_conformance_matrix.py``): zero ``crash`` cells; every
``silent-loss`` cell is in the tracked ledger (:mod:`export_conformance_ledger`) and every ledger
entry still reproduces; the checked-in matrix (``tests/golden/export_conformance/``) matches.

Regenerate the matrix and the ledger with one command::

    UPDATE_EXPORT_CONFORMANCE=1 pytest tests/test_export_conformance_matrix.py

(or ``--update-export-conformance``).
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from corpus_adapter_support import missing_tools
from corpus_roundtrip import _import_entry, representatives_by_format

from app.emitter import EmitterTarget, get_emitter, load_builtin_emitters
from app.export_dispatch import dispatch_from_source
from app.export_service import ExportError
from app.export_source import ExportSource
from app.import_source import canonical_diff, get_import_source, load_builtin_import_sources
from app.roundtrip_matrix import import_adapter_for_emit, production_emit_targets, reimport_emitted
from app.toolchain_runner import is_tool_available

__all__ = [
    "ARTIFACT_DIR",
    "LEDGER_PATH",
    "MATRIX_VERSION",
    "STATUSES",
    "build_export_conformance_matrix",
    "matrix_markdown",
    "updating_export_conformance",
    "write_artifacts",
]

#: Bump only when the artifact's own shape changes.
MATRIX_VERSION = 1
STATUSES = ("ok", "lossy", "refused", "silent-loss", "crash", "skipped")
UPDATE_ENV = "UPDATE_EXPORT_CONFORMANCE"
ARTIFACT_DIR = Path(__file__).resolve().parent / "golden" / "export_conformance"
LEDGER_PATH = Path(__file__).resolve().parent / "export_conformance_ledger.py"

#: How many drift entries a silent-loss cell keeps as evidence.
_DRIFT_SAMPLE = 6
_LOSS_KINDS = ("drop", "approx", "synth")


def updating_export_conformance(request: object | None = None) -> bool:
    """Whether this run rewrites the checked-in matrix and ledger."""
    if os.environ.get(UPDATE_ENV, "").strip() in {"1", "true", "yes"}:
        return True
    getoption = getattr(getattr(request, "config", None), "getoption", None)
    return bool(getoption("--update-export-conformance", default=False)) if getoption else False


def _cell(family: str, target: str, status: str, reason: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    return {"family": family, "target": target, "status": status, "reason": reason, **extra}


def _emit_tools_missing(target: EmitterTarget) -> List[str]:
    emitter_cls = get_emitter(target.descriptor.format)
    return [t for t in getattr(emitter_cls, "required_tools", ()) if not is_tool_available(t)]


def _classify(family: str, source: ExportSource, target: EmitterTarget) -> Dict[str, Any]:
    """Run one family × target cell (see the module docstring for the statuses)."""
    descriptor = target.descriptor
    key = descriptor.key
    missing = _emit_tools_missing(target)
    if missing:
        return _cell(family, key, "skipped", "Emit tools unavailable: " + ", ".join(missing))
    try:
        dispatch = dispatch_from_source(source, key, dry_run=False, confirm=True, persistence=None)
    except ExportError as exc:
        return _cell(family, key, "refused", str(exc))
    except Exception as exc:  # noqa: BLE001 - a crash is exactly what this matrix records
        return _cell(family, key, "crash", f"{type(exc).__name__}: {exc}")

    counts = {kind: int(dispatch.fidelity.report.kind_counts.get(kind, 0)) for kind in _LOSS_KINDS}
    if any(counts.values()):
        return _cell(family, key, "lossy", None, loss_counts=counts, tier=dispatch.fidelity.summary.tier.value)

    adapter_key = import_adapter_for_emit(descriptor.key, descriptor.format)
    adapter = get_import_source(adapter_key) if adapter_key else None
    if adapter is None or dispatch.emit is None:
        return _cell(family, key, "ok", "No import adapter reads this target back; fidelity report only.")
    try:
        reimported = reimport_emitted(adapter, dispatch.emit, multi_file=descriptor.multi_file)
    except Exception as exc:  # noqa: BLE001 - an unreadable artifact is noted, not a drift
        reason = f"Round trip skipped: the artifact could not be read back ({type(exc).__name__})."
        return _cell(family, key, "ok", reason)
    drift = canonical_diff(source.api, reimported).entries
    if drift:
        sample = [f"{entry.change.value} {entry.entity} {entry.key}".strip() for entry in drift[:_DRIFT_SAMPLE]]
        return _cell(
            family, key, "silent-loss",
            f"Fidelity report is empty but the round trip shows {len(drift)} difference(s).",
            drift=sample,
        )
    return _cell(family, key, "ok")


def build_export_conformance_matrix(
    *, families: Optional[Sequence[str]] = None, targets: Optional[Sequence[EmitterTarget]] = None
) -> Dict[str, Any]:
    """Run the full matrix.

    Args:
        families: Limit to these corpus source families (tests); every family by default.
        targets: Limit to these targets (tests); every production target by default.

    Returns:
        ``{matrix_version, families, targets, counts, cells}`` with cells sorted by family, target.
    """
    load_builtin_import_sources()
    load_builtin_emitters()
    reps = representatives_by_format()
    if families is not None:
        reps = {family: reps.get(family) for family in families}
    target_list = list(targets) if targets is not None else production_emit_targets()
    cells: List[Dict[str, Any]] = []
    for family, entry in sorted(reps.items()):
        skip_reason: Optional[str] = None
        source: Optional[ExportSource] = None
        if entry is None:
            skip_reason = "No runnable representative corpus fixture for this family."
        elif entry.adapter_key and missing_tools(entry.adapter_key):
            skip_reason = "Source import tools unavailable: " + ", ".join(missing_tools(entry.adapter_key))
        else:
            try:
                api = _import_entry(entry)
                source = ExportSource(api=api, artifact_id=f"corpus:{family}", version_record_id="corpus")
            except Exception as exc:  # noqa: BLE001 - an import failure is the import matrix's to own
                skip_reason = f"Corpus fixture did not import: {type(exc).__name__}"
        for target in target_list:
            if source is None:
                cells.append(_cell(family, target.descriptor.key, "skipped", skip_reason))
            else:
                cells.append(_classify(family, source, target))
    counts = Counter(cell["status"] for cell in cells)
    return {
        "matrix_version": MATRIX_VERSION,
        "families": sorted(reps),
        "targets": [t.descriptor.key for t in target_list],
        "counts": {status: counts.get(status, 0) for status in STATUSES},
        "cells": cells,
    }


def matrix_markdown(matrix: Dict[str, Any]) -> str:
    """A human-readable rendering: totals, then the grid (one row per family)."""
    abbrev = {"ok": "ok", "lossy": "L", "refused": "R", "silent-loss": "S", "crash": "X", "skipped": "-"}
    lines = [
        "# Export conformance matrix (X1, #6222)",
        "",
        "Generated — do not edit. Regenerate with "
        "`UPDATE_EXPORT_CONFORMANCE=1 pytest tests/test_export_conformance_matrix.py`.",
        "",
        "Every corpus source family exported to every production target through the catalog export "
        "path. `ok` exported with no loss · `L` lossy, with a fidelity report · `R` refused with a "
        "reason · `S` silent loss (empty report, round-trip drift; tracked in "
        "`tests/export_conformance_ledger.py`) · `X` crash · `-` skipped.",
        "",
        "| Status | Cells |",
        "| --- | --- |",
    ]
    lines += [f"| {status} | {count} |" for status, count in matrix["counts"].items()]
    targets = matrix["targets"]
    by_cell = {(c["family"], c["target"]): c["status"] for c in matrix["cells"]}
    lines += ["", "| Family | " + " | ".join(targets) + " |", "| --- |" + " --- |" * len(targets)]
    for family in matrix["families"]:
        row = [abbrev.get(by_cell.get((family, t), "-"), "?") for t in targets]
        lines.append(f"| {family} | " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def silent_loss_cells(matrix: Dict[str, Any]) -> Dict[Tuple[str, str], str]:
    """The ``(family, target) -> evidence`` map of the matrix's silent-loss cells."""
    return {
        (c["family"], c["target"]): "; ".join(c.get("drift") or [])
        for c in matrix["cells"]
        if c["status"] == "silent-loss"
    }


def write_artifacts(matrix: Dict[str, Any]) -> None:
    """Write the matrix (JSON + Markdown) and regenerate the silent-loss ledger."""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "matrix.json").write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ARTIFACT_DIR / "matrix.md").write_text(matrix_markdown(matrix), encoding="utf-8")
    silent = silent_loss_cells(matrix)
    by_target: Dict[str, List[Tuple[str, str]]] = {}
    for (family, target), evidence in sorted(silent.items(), key=lambda item: (item[0][1], item[0][0])):
        by_target.setdefault(target, []).append((family, evidence))
    out = [
        '"""Tracked silent-loss pairs of the export conformance matrix — X1 (#6222). GENERATED.',
        "",
        "Each entry is a (source family, target) pair whose export reports no loss while the round trip",
        "shows drift. The gate fails on a silent-loss pair NOT listed here, and on a listed pair that no",
        "longer reproduces (fixed: regenerate to drop it). Drive this list to zero by making the target's",
        "fidelity report name the loss, fixing the emitter, or refusing the pair with a reason.",
        "",
        "Regenerate with `UPDATE_EXPORT_CONFORMANCE=1 pytest tests/test_export_conformance_matrix.py`.",
        '"""',
        "",
        "from typing import Dict, Tuple",
        "",
        "KNOWN_SILENT_LOSS: Dict[Tuple[str, str], str] = {",
    ]
    for target, pairs in by_target.items():
        out.append(f"    # --- {target} ({len(pairs)}) ---")
        for family, evidence in pairs:
            out.append(f"    ({family!r}, {target!r}):")
            out.append(f"        {evidence[:100]!r},")
    out.append("}")
    LEDGER_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
