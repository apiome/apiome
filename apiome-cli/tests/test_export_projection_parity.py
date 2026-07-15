"""Projection-evidence parity for the CLI's machine-readable export output — EFP-1.3 (#4812).

The export commands' ``--json`` evidence passes the server's fidelity envelope through
verbatim, so the CLI leg of the cross-surface parity contract is: given that envelope,
``projection_parity_issues`` must accept a consistent one and flag every disagreement —
report counts vs projection status counts, coarse summary counts, unknown reason codes,
and an ``is_lossless`` claim that contradicts the evidence.

The clean fixture (``fixtures/export-projection-parity.json``) is a checked-in copy of the
apiome-rest corpus golden ``parity_envelope_graphql.json`` (rich source → GraphQL SDL), so
this checker is exercised over the exact envelope shape the REST corpus produced.
Regenerate both together when the contract changes (``UPDATE_PROJECTION_GOLDENS=1`` in
apiome-rest, then re-copy).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from apiome_cli.export_output import (
    PROJECTION_REASON_CODES,
    format_projection_snapshot_lines,
    projection_parity_issues,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_PARITY = json.loads((_FIXTURES / "export-projection-parity.json").read_text())


def _envelope() -> dict[str, Any]:
    """A deep copy of the shared parity fixture, safe to tamper per-test."""
    return copy.deepcopy(_PARITY)


def test_reason_codes_mirror_the_canonical_taxonomy() -> None:
    """The CLI's reason-code set is the eight-member taxonomy, exactly."""
    assert PROJECTION_REASON_CODES == frozenset(
        {
            "destination_unsupported",
            "emitter_unsupported",
            "source_incomplete",
            "source_parse_limit",
            "option_excluded",
            "security_redacted",
            "target_tool_unavailable",
            "not_applicable",
        }
    )


def test_shared_fixture_passes_the_parity_checker() -> None:
    """The REST corpus's own golden envelope is internally consistent, byte-for-byte."""
    assert projection_parity_issues(_envelope()) == []


def test_shared_fixture_reason_codes_are_all_canonical() -> None:
    """Every reason key the shared fixture carries is a canonical code."""
    for code in _envelope()["projection"]["reason_counts"]:
        assert code in PROJECTION_REASON_CODES, code


def test_missing_envelope_and_missing_blocks_are_reported() -> None:
    assert projection_parity_issues(None) == ["fidelity envelope is missing"]
    assert projection_parity_issues({}) == ["envelope is missing its report/summary blocks"]
    pre_projection = _envelope()
    del pre_projection["projection"]
    issues = projection_parity_issues(pre_projection)
    assert issues == ["envelope is missing its projection summary block (EFP-1.1)"]


@pytest.mark.parametrize(
    "tamper, expected_fragment",
    [
        (lambda e: e["report"]["kind_counts"].__setitem__("drop", 99), "kind_counts['drop']"),
        (lambda e: e["summary"].__setitem__("dropped", 99), "summary dropped=99"),
        (lambda e: e["summary"].__setitem__("total", 99), "summary total=99"),
        (
            lambda e: e["projection"]["status_counts"].__setitem__("retained", 99),
            "disagrees with projection",
        ),
        (
            lambda e: e["projection"]["reason_counts"].__setitem__("destination_broken", 1),
            "unknown reason code",
        ),
        (lambda e: e["projection"].__setitem__("is_lossless", True), "is_lossless"),
        (lambda e: e["projection"].__setitem__("manifest_hash", ""), "manifest_hash"),
    ],
)
def test_each_tampering_is_detected(tamper, expected_fragment: str) -> None:
    """Every single-field disagreement is flagged with a pointed description."""
    envelope = _envelope()
    tamper(envelope)
    issues = projection_parity_issues(envelope)
    assert issues, "tampered envelope must not pass"
    assert any(expected_fragment in issue for issue in issues), issues


def test_snapshot_line_renders_from_the_shared_fixture() -> None:
    """The human snapshot line and the machine evidence describe the same snapshot."""
    envelope = _envelope()
    lines = format_projection_snapshot_lines(envelope)
    assert len(lines) == 1
    short_hash = envelope["projection"]["manifest_hash"][:12]
    assert short_hash in lines[0]
    assert f"{envelope['projection']['total_constructs']} constructs" in lines[0]
    assert f"{envelope['projection']['evidence_count']} evidence rows" in lines[0]
