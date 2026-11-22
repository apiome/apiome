"""Segment ID allocation in the EDI guide planner (:class:`app.edi_guide._SegmentIds`).

The allocator scans its long, name-independent fallbacks from a cursor instead of rebuilding and
re-walking them for every segment (a 1 800-record spec spent seconds there). These tests hold the
new allocator to the IDs the original full scan picked, for every option combination the X12,
EDIFACT and HL7 v2 guides use, and pin that a large guide plans quickly.
"""

from __future__ import annotations

import itertools
import random
import re
import time
from typing import List, Optional, Set

import pytest

from app.edi_guide import _SegmentIds
from app.edifact_guide_emitter import EDIFACT_SEGMENT_TAG_RULE
from app.hl7v2_guide_emitter import _SEGMENT_ID_RULE as HL7V2_SEGMENT_ID_RULE


class _ReferenceSegmentIds:
    """The allocator as it was before the cursor: every candidate rebuilt and walked per call."""

    def __init__(self, reserved: frozenset, rule: Optional[str] = None, prefix: str = "") -> None:
        self._used: Set[str] = set(reserved)
        self._rule = re.compile(rule) if rule else None
        self._prefix = prefix

    def claim(self, segment_id: str) -> bool:
        if segment_id in self._used or (self._rule is not None and not self._rule.match(segment_id)):
            return False
        self._used.add(segment_id)
        return True

    def allocate(self, name: str) -> str:
        letters = re.sub(r"[^A-Za-z0-9]", "", name).upper() or "SEG"
        if not letters[0].isalpha():
            letters = f"S{letters}"
        words = [w for w in re.split(r"(?<=[a-z0-9])(?=[A-Z])|[^A-Za-z0-9]+", name) if w]
        initials = "".join(w[0] for w in words).upper()
        consonants = letters[0] + re.sub(r"[AEIOU]", "", letters[1:])
        candidates = [letters[:3], (initials + letters[1:])[:3], consonants[:3]]
        candidates += [letters[0] + a + b for a in letters[1:] for b in letters[2:]]
        candidates += [letters[:2] + str(d) for d in range(1, 10)]
        candidates += [letters[0] + str(d) + str(e) for d in range(10) for e in range(10)]
        if self._rule is not None:
            alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            first = letters[0] if letters[0].isalpha() else "S"
            candidates += [first + a + b for a in alphabet for b in alphabet]
            candidates += [a + b + c for a in alphabet for b in alphabet for c in alphabet]
        if self._prefix:
            width = 3 - len(self._prefix)
            alnum = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            stems = [letters[:width], initials[:width], consonants[:width], *(c[:width] for c in candidates)]
            pairs = ["".join(p) for p in itertools.product(alnum, repeat=width)]
            candidates = [self._prefix + stem for stem in [*stems, *pairs] if len(stem) == width]
        for candidate in candidates:
            if len(candidate) >= 2 and self.claim(candidate):
                return candidate
        raise ValueError(f"No free segment ID left for {name!r}")


#: (reserved IDs, ID rule, prefix) as the X12, EDIFACT and HL7 v2 guides configure the allocator.
_CONFIGS = {
    "x12": (frozenset({"ST", "SE"}), None, ""),
    "edifact": (frozenset({"UNH", "UNT"}), EDIFACT_SEGMENT_TAG_RULE, ""),
    "hl7v2": (frozenset({"MSH"}), HL7V2_SEGMENT_ID_RULE, "Z"),
}


def _names(count: int, seed: int) -> List[str]:
    """Record names in the shapes real specs have: CamelCase, snake_case, digits, repeats."""
    rng = random.Random(seed)
    stems = ["Order", "OrderLine", "Model", "Search", "Hit", "Address", "Customer", "Item", "Tenant", "Job",
             "Export", "Delivery", "Repository", "Version", "Class", "Property", "Event", "Webhook"]
    names: List[str] = []
    for i in range(count):
        shape = rng.randrange(5)
        a, b = rng.choice(stems), rng.choice(stems)
        if shape == 0:
            names.append(a)
        elif shape == 1:
            names.append(a + b)
        elif shape == 2:
            names.append(f"{a.lower()}_{b.lower()}")
        elif shape == 3:
            names.append(f"{a}{b}{i}")
        else:
            names.append(f"9{a}")
    return names


def _allocations(allocator, names: List[str], claims: List[str]) -> List[str]:
    """IDs handed out for ``names``, with an imported ID claimed every seventh step; ``!`` marks exhaustion."""
    out: List[str] = []
    for i, name in enumerate(names):
        if i % 7 == 3 and claims:
            out.append(f"claim:{claims[i % len(claims)]}:{allocator.claim(claims[i % len(claims)])}")
        try:
            out.append(allocator.allocate(name))
        except ValueError:
            out.append("!")
    return out


@pytest.mark.parametrize("config", sorted(_CONFIGS))
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_allocations_match_the_full_scan(config: str, seed: int) -> None:
    """Every ID — and every exhaustion — is the one the original full scan produced."""
    reserved, rule, prefix = _CONFIGS[config]
    # HL7 v2 runs out at 1 296 IDs, so its run crosses exhaustion; the others stay below it.
    names = _names(1500 if config == "hl7v2" else 900, seed)
    claims = ["ZAB", "ORD", "NAD", "PID", "Z12", "ORL"]
    expected = _allocations(_ReferenceSegmentIds(reserved, rule, prefix), names, claims)
    assert _allocations(_SegmentIds(reserved, rule, prefix), names, claims) == expected


def test_hl7v2_prefix_runs_out_after_every_two_character_suffix() -> None:
    """``Z`` plus two letters or digits is 1 296 IDs (``MSH`` reserved is outside them); the next one fails."""
    reserved, rule, prefix = _CONFIGS["hl7v2"]
    allocator = _SegmentIds(reserved, rule, prefix)
    ids = {allocator.allocate(f"Record{i}") for i in range(36 * 36)}
    assert len(ids) == 36 * 36 and all(i.startswith("Z") and len(i) == 3 for i in ids)
    with pytest.raises(ValueError, match="No free segment ID left"):
        allocator.allocate("OneTooMany")


@pytest.mark.parametrize("config", sorted(_CONFIGS))
def test_thousands_of_segments_allocate_quickly(config: str) -> None:
    """6 000 allocations finish in well under a second (the full scan took several)."""
    reserved, rule, prefix = _CONFIGS[config]
    allocator = _SegmentIds(reserved, rule, prefix)
    started = time.perf_counter()
    for name in _names(6000, 7):
        try:
            allocator.allocate(name)
        except ValueError:
            pass
    assert time.perf_counter() - started < 1.5
