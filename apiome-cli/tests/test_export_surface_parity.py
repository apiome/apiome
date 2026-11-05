"""Export surface parity for the CLI — MFX-40.3 (#4341).

The CLI leg of the four-surface parity contract (UI, browse, CLI, MCP): fed the very previews apiome-rest
answers for each fixture source, ``apiome export`` must

* print the server's advisory **verbatim** — headline and message, the wording the Export dialog, the
  browse page and the MCP ``version.export`` ``advisory`` carry — and nothing for a lossless export;
* read the report shape: every non-OK construct of the report reaches the loss table (or its overflow);
* gate exactly the exports MCP blocks without ``allow_lossy``: ``--force`` is needed iff the tier is not
  ``lossless``.

The fixture (``fixtures/export-surface-parity.json``) is a checked-in copy of apiome-rest's golden
``tests/fixtures/export_surface_parity.json``; apiome-rest fails CI when the copy is stale. Regenerate
every copy together in apiome-rest with ``pytest tests/test_export_surface_parity.py --update-golden``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer

from apiome_cli import export_output
from apiome_cli.export_output import enforce_export_fidelity_gate, format_export_fidelity_summary, is_lossy

_GOLDEN = json.loads((Path(__file__).resolve().parent / "fixtures" / "export-surface-parity.json").read_text())
_CASES = [(source, target, preview) for source, entry in sorted(_GOLDEN["sources"].items())
          for target, preview in sorted(entry["previews"].items())]
_IDS = [f"{source}-{target}" for source, target, _ in _CASES]


def test_the_golden_covers_every_tier() -> None:
    assert {preview["summary"]["tier"] for _, _, preview in _CASES} >= {"lossless", "lossy", "types-only"}


@pytest.mark.parametrize("source, target, preview", _CASES, ids=_IDS)
def test_the_cli_prints_the_server_advisory_verbatim(source: str, target: str, preview: dict[str, Any]) -> None:
    lines = format_export_fidelity_summary(preview, target=target)
    advisory = preview["advisory"]
    if advisory["show"]:
        assert advisory["headline"].strip() in lines
        assert advisory["message"].strip() in lines
    else:
        assert advisory["message"].strip() not in lines
    assert any(preview["target"]["label"] in line for line in lines)


@pytest.mark.parametrize("source, target, preview", _CASES, ids=_IDS)
def test_the_cli_reads_every_lossy_construct_of_the_report(source: str, target: str, preview: dict[str, Any]) -> None:
    lossy = export_output.sort_report_items_worst_first(
        [item for item in preview["report"]["items"] if item["kind"] != "ok"])
    lines = export_output.format_loss_table_lines(preview, max_rows=len(lossy) or 1)
    if not lossy:
        assert lines == []
        return
    assert lines[0] == "Per-construct losses:" and len(lines) == len(lossy) + 1
    for line, item in zip(lines[1:], lossy):
        assert item["construct"] in line and export_output.kind_label(item["kind"]) in line


@pytest.mark.parametrize("source, target, preview", _CASES, ids=_IDS)
def test_force_is_needed_exactly_where_mcp_needs_allow_lossy(
    source: str, target: str, preview: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(export_output, "interactive_enabled", lambda: False)
    lossless = preview["summary"]["tier"] == "lossless"
    assert is_lossy(preview) is (not lossless)
    enforce_export_fidelity_gate(preview, force=True)
    if lossless:
        enforce_export_fidelity_gate(preview, force=False)
    else:
        with pytest.raises(typer.Exit):
            enforce_export_fidelity_gate(preview, force=False)
