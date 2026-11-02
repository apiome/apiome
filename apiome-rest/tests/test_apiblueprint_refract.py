"""API Blueprint parse via drafter → API Elements / Refract — MFI-16.1 (#3804).

One ``drafter -f json`` run gives both the annotations (MFI-16.3 lint) and the Refract tree. The
tree's contract — without prose, examples, annotations and source maps — is hashed into the catalog
item's format hash; it stays out of the version fingerprint, so a server without drafter mints the
same version. drafter is replayed from the MFI-16.3 recordings (real drafter 4.0.0 output).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

from app import apiblueprint_drafter
from app import apiblueprint_import_source as import_source_module
from app.apiblueprint_drafter import read_drafter_parse_result, run_drafter, run_drafter_parse
from app.apiblueprint_import_source import ApiblueprintImportSource
from app.apiblueprint_refract import (
    DRAFTER_VERSION,
    REFRACT_ALGORITHM,
    ApiBlueprintRefractHasher,
    refract_contract,
    refract_sha256,
)
from app.fingerprint import fingerprint, get_fingerprint_hasher
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError, ToolRunResult

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "apiblueprint_drafter"
_SOURCE = ApiblueprintImportSource()


def _text(name: str) -> str:
    return (_FIXTURES / f"{name}.apib").read_text(encoding="utf-8")


def _recording(name: str) -> Dict[str, Any]:
    return json.loads((_FIXTURES / "recordings" / f"{name}.json").read_text(encoding="utf-8"))


def _tree(name: str = "warnings") -> Dict[str, Any]:
    return json.loads(_recording(name)["stdout"])


def _replay(monkeypatch: pytest.MonkeyPatch, name: str, *, stdout: str | None = None) -> List[Dict[str, Any]]:
    """Make ``run_tool_blocking`` replay a recording (raising for a non-zero exit, as the runner does)."""
    calls: List[Dict[str, Any]] = []
    recorded = _recording(name)
    out = recorded["stdout"] if stdout is None else stdout

    def _fake(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        calls.append({"key": key, "args": list(args)})
        if recorded["exit_code"]:
            raise ToolExecutionError(key, recorded["exit_code"], out, recorded["stderr"])
        return ToolRunResult(key=key, argv=[key, *args], exit_code=0, stdout=out, stderr="", duration_ms=1)

    monkeypatch.setattr(apiblueprint_drafter, "run_tool_blocking", _fake)
    monkeypatch.setattr(import_source_module, "drafter_available", lambda: True)
    return calls


def _first(node: Any, predicate: Callable[[Dict[str, Any]], bool]) -> Dict[str, Any]:
    """The first element in ``node`` (depth first) that ``predicate`` accepts."""
    if isinstance(node, dict):
        if predicate(node):
            return node
        for value in node.values():
            try:
                return _first(value, predicate)
            except LookupError:
                pass
    elif isinstance(node, list):
        for value in node:
            try:
                return _first(value, predicate)
            except LookupError:
                pass
    raise LookupError("no such element")


def _element(name: str) -> Callable[[Dict[str, Any]], bool]:
    return lambda node: node.get("element") == name


def _edited(edit: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    tree = copy.deepcopy(_tree())
    edit(tree)
    return tree


# --- drafter's parse result --------------------------------------------------------------------


def test_run_drafter_parse_returns_the_parse_result(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _replay(monkeypatch, "warnings")
    result = run_drafter_parse(_text("warnings"))
    assert result is not None and result["element"] == "parseResult"
    assert calls == [{"key": "drafter", "args": ["-f", "json"]}]


def test_a_non_zero_exit_still_yields_the_parse_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "error")
    result = run_drafter_parse(_text("error"))
    assert result is not None and result["element"] == "parseResult"


def test_without_drafter_there_is_no_parse_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing(*_args: Any, **_kwargs: Any) -> ToolRunResult:
        raise ToolNotAvailableError("drafter", "missing")

    monkeypatch.setattr(apiblueprint_drafter, "run_tool_blocking", _missing)
    assert run_drafter_parse("FORMAT: 1A\n# A\n") is None
    with pytest.raises(ToolNotAvailableError):
        run_drafter_parse("FORMAT: 1A\n# A\n", strict=True)


@pytest.mark.parametrize("stdout", ["", "not json", '{"element": "category"}', "[]"])
def test_output_that_is_not_a_parse_result_is_ignored(stdout: str) -> None:
    assert read_drafter_parse_result(stdout) is None


def test_run_drafter_still_returns_the_annotations(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "warnings")
    annotations = run_drafter(_text("warnings"))
    assert annotations and all(a["severity"] in {"warning", "error"} for a in annotations)


# --- the contract and its hash -----------------------------------------------------------------


def test_the_contract_drops_prose_examples_annotations_and_source_maps() -> None:
    blob = json.dumps(refract_contract(_tree()))
    for dropped in ('"copy"', '"annotation"', '"sourceMap"', '"messageBody"', '"description"'):
        assert dropped not in blob
    assert '"httpTransaction"' in blob and '"hrefVariables"' in blob


def test_a_parameter_type_title_is_kept() -> None:
    # On an hrefVariables member, meta.title is the parameter's type, not a heading.
    contract = refract_contract(_tree())
    member = _first(contract, lambda n: n.get("element") == "member" and "title" in (n.get("meta") or {}))
    assert member["meta"]["title"]["content"]


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(lambda t: _first(t, _element("copy")).update(content="Reworded prose."), id="copy"),
        pytest.param(
            lambda t: _first(t, _element("resource"))["meta"]["title"].update(content="Renamed"), id="resource-title"
        ),
        pytest.param(
            lambda t: _first(t, lambda n: "description" in (n.get("meta") or {}))["meta"]["description"].update(
                content="Another description."
            ),
            id="description",
        ),
        pytest.param(
            lambda t: _first(t, lambda n: n.get("element") == "asset").update(content='{"other": "example"}'),
            id="example-body",
        ),
        pytest.param(lambda t: t["content"].pop(), id="an-annotation"),
    ],
)
def test_prose_and_example_edits_keep_the_hash(edit: Callable[[Dict[str, Any]], None]) -> None:
    assert refract_sha256(_edited(edit)) == refract_sha256(_tree())


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(
            lambda t: _first(t, _element("resource"))["attributes"]["href"].update(content="/animals"), id="href"
        ),
        pytest.param(
            lambda t: _first(t, _element("httpRequest"))["attributes"]["method"].update(content="DELETE"),
            id="method",
        ),
        pytest.param(
            lambda t: _first(t, _element("httpResponse"))["attributes"]["statusCode"].update(content="418"),
            id="status-code",
        ),
        pytest.param(lambda t: _first(t, _element("resource"))["content"].clear(), id="actions-removed"),
    ],
)
def test_contract_edits_move_the_hash(edit: Callable[[Dict[str, Any]], None]) -> None:
    assert refract_sha256(_edited(edit)) != refract_sha256(_tree())


def test_the_hash_ignores_key_order() -> None:
    def _reverse(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: _reverse(node[k]) for k in reversed(list(node))}
        if isinstance(node, list):
            return [_reverse(v) for v in node]
        return node

    assert refract_sha256(_reverse(_tree())) == refract_sha256(_tree())


@pytest.mark.parametrize("value", [None, {}, {"element": "category"}, []])
def test_no_parse_result_has_no_hash(value: Any) -> None:
    assert refract_sha256(value) is None


# --- through the import ------------------------------------------------------------------------


def test_one_drafter_run_gives_the_annotations_and_the_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _replay(monkeypatch, "warnings")
    document = _SOURCE.parse(_text("warnings"))
    assert len(calls) == 1
    assert document.refract is not None and document.drafter_annotations

    api = _SOURCE.normalize(document)
    assert api.extras["apib_refract_sha256"] == refract_sha256(_tree())
    assert api.extras["apib_refract_algorithm"] == REFRACT_ALGORITHM
    assert api.extras["apib_drafter_version"] == DRAFTER_VERSION == "4.0.0"
    assert api.raw["refract"] == _tree()
    assert "refract" not in (_SOURCE.normalize(document, include_raw=False).raw or {})


def test_the_hash_is_the_format_hash_and_stays_out_of_the_version(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "warnings")
    with_drafter = _SOURCE.normalize(_SOURCE.parse(_text("warnings")))
    monkeypatch.setattr(import_source_module, "drafter_available", lambda: False)
    without_drafter = _SOURCE.normalize(_SOURCE.parse(_text("warnings")))

    assert get_fingerprint_hasher("apiblueprint") is ApiBlueprintRefractHasher
    assert fingerprint(with_drafter).format_hash == with_drafter.extras["apib_refract_sha256"]
    assert fingerprint(without_drafter).format_hash is None
    # The annotations differ (they are lint and stay in the model); strip them to compare the rest.
    strip = {"apib_drafter_annotations", "apib_drafter_annotation_count"}

    def _without_lint(api: Any) -> Any:
        return api.model_copy(update={"extras": {k: v for k, v in api.extras.items() if k not in strip}})

    version_with = fingerprint(_without_lint(with_drafter)).fingerprint
    assert version_with == fingerprint(_without_lint(without_drafter)).fingerprint


def test_without_drafter_the_item_records_no_refract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(import_source_module, "drafter_available", lambda: False)
    api = _SOURCE.normalize(_SOURCE.parse(_text("warnings")))
    assert not {"apib_refract_sha256", "apib_refract_algorithm", "apib_drafter_version"} & set(api.extras)
    assert "refract" not in api.raw


def test_drafter_printing_nothing_leaves_the_import_as_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "warnings", stdout="")
    document = _SOURCE.parse(_text("warnings"))
    assert document.refract is None and document.drafter_annotations == ()
