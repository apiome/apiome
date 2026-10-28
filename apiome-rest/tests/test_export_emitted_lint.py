"""Emitted-artifact lint — MFX-5.2 (#3853).

Pins :func:`app.export_emitted_lint.lint_emitted_artifact`: the emitted artifact is read back
through its format's import adapter and linted by the MFI rule packs (the format's own pack, or
its paradigm pack, plus the unconditional ones), with the same score/grade formula an import uses.
A target that cannot be read back — or a fault anywhere — reports ``applicable: false`` with a
reason instead of failing the verify.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.export_dispatch import dispatch_from_source
from app.export_emitted_lint import COMMON_PACK, EmittedArtifactLint, lint_emitted_artifact
from app.import_source import ImportSourceError
from app.lint_engine import lint_canonical_model
from tests.test_export_multi_target import _source


def _emit(target: str):
    """Emit the REST fixture source to ``target`` (read-only, as the verify route does)."""
    dispatch = dispatch_from_source(_source(), target, dry_run=False, confirm=True, persistence=None)
    descriptor = dispatch.fidelity.target
    return descriptor.key, dispatch.target, dispatch.emit, bool(descriptor.multi_file)


def _lint(target: str) -> EmittedArtifactLint:
    key, fmt, emit, multi = _emit(target)
    return lint_emitted_artifact(key, fmt, emit, multi_file=multi)


@pytest.mark.parametrize(
    ("target", "pack"),
    [("graphql", "graphql"), ("protobuf", "protobuf"), ("avro", "avro"), ("asyncapi", "asyncapi")],
)
def test_the_targets_own_rule_pack_lints_the_artifact(target, pack):
    report = _lint(target)
    assert report.applicable is True and report.reason is None
    assert report.pack == pack
    assert 0 <= report.score <= 100 and report.grade in {"A", "B", "C", "D", "F"}


def test_findings_carry_the_lens_shape():
    report = _lint("protobuf")
    assert report.findings, "the protobuf pack flags the REST fixture's emitted .proto"
    for finding in report.findings:
        assert set(finding) == {"severity", "rule", "message", "category", "path"}
        assert finding["severity"] in {"error", "warning", "info"}
        assert finding["rule"] and finding["message"]


def test_a_format_without_its_own_pack_falls_back_to_its_paradigm_or_common():
    assert _lint("openapi").pack == "rest-conventions"
    assert _lint("xmlrpc").pack == COMMON_PACK


def test_the_lint_is_deterministic():
    assert _lint("graphql") == _lint("graphql")


def test_the_lint_reads_the_artifact_not_the_source():
    key, fmt, emit, multi = _emit("graphql")
    with patch("app.export_emitted_lint.lint_canonical_model", wraps=lint_canonical_model) as spy:
        lint_emitted_artifact(key, fmt, emit, multi_file=multi)
    (linted,), _ = spy.call_args
    assert linted.format == "graphql"


def test_the_sample_target_is_not_linted():
    key, fmt, emit, multi = _emit("sample")
    report = lint_emitted_artifact(key, fmt, emit, multi_file=multi)
    assert report.applicable is False and report.findings == []
    assert "sample" in report.reason


def test_a_format_no_adapter_reads_back_is_not_linted():
    key, fmt, emit, multi = _emit("graphql")
    with patch("app.export_emitted_lint.import_adapter_for_emit", return_value=None):
        report = lint_emitted_artifact(key, fmt, emit, multi_file=multi)
    assert report.applicable is False and report.score is None
    assert "No import adapter reads" in report.reason


def test_an_artifact_the_adapter_refuses_is_not_linted():
    key, fmt, emit, multi = _emit("graphql")
    with patch("app.export_emitted_lint.reimport_emitted", side_effect=ImportSourceError("bad SDL")):
        report = lint_emitted_artifact(key, fmt, emit, multi_file=multi)
    assert report.applicable is False
    assert report.reason.endswith("bad SDL")


@pytest.mark.parametrize("seam", ["reimport_emitted", "lint_canonical_model"])
def test_an_unexpected_fault_degrades_to_not_linted(seam):
    key, fmt, emit, multi = _emit("graphql")
    with patch(f"app.export_emitted_lint.{seam}", side_effect=RuntimeError("boom")):
        report = lint_emitted_artifact(key, fmt, emit, multi_file=multi)
    assert report.applicable is False and report.reason
    assert "boom" not in report.reason
