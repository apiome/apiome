"""Tracked silent-loss pairs of the export conformance matrix — X1 (#6222). GENERATED.

Each entry is a (source family, target) pair whose export reports no loss while the round trip
shows drift. The gate fails on a silent-loss pair NOT listed here, and on a listed pair that no
longer reproduces (fixed: regenerate to drop it). Drive this list to zero by making the target's
fidelity report name the loss, fixing the emitter, or refusing the pair with a reason.

Regenerate with `UPDATE_EXPORT_CONFORMANCE=1 pytest tests/test_export_conformance_matrix.py`.
"""

from typing import Dict, Tuple

KNOWN_SILENT_LOSS: Dict[Tuple[str, str], str] = {
}
