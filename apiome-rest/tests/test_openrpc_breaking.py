"""Tests for the OpenRPC breaking-change classifier — MFI-19.1 (#3979)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from app.breaking_change import Severity, available_breaking_change_formats, classify_models
from app.openrpc_breaking import grade_params, grade_structure
from app.openrpc_normalizer import OpenRpcNormalizer
from app.openrpc_parser import parse_openrpc

_KEY = "Wallet.getBalance"
_REQUEST = f"{_KEY}#request"


def _param(name: str, *, required: bool = True, schema_type: str = "string") -> Dict[str, Any]:
    """One OpenRPC parameter (content descriptor)."""
    return {"name": name, "required": required, "schema": {"type": schema_type}}


def _api(params: List[Dict[str, Any]], *, structure: Optional[str] = None, result: str = "string"):
    """A one-method OpenRPC API, ``getBalance(params) -> result``."""
    method: Dict[str, Any] = {
        "name": "getBalance",
        "summary": "Balance.",
        "params": params,
        "result": {"name": "balance", "schema": {"type": result}},
    }
    if structure is not None:
        method["paramStructure"] = structure
    doc = {"openrpc": "1.2.6", "info": {"title": "Wallet", "version": "1"}, "methods": [method]}
    return OpenRpcNormalizer().normalize(parse_openrpc(json.dumps(doc)), include_raw=False)


def _grades(base, target) -> Dict[Tuple[str, str], Tuple[Severity, str]]:
    """``(kind, key)`` → ``(severity, rule_id)`` for the diff of two models."""
    result = classify_models(base, target)
    assert result.classifier == "openrpc-params"
    return {(c.kind.value, c.key): (c.severity, c.rule_id) for c in result.classifications}


def test_the_classifier_is_registered_for_openrpc():
    assert "openrpc" in available_breaking_change_formats()


def test_appending_an_optional_param_is_safe():
    base = _api([_param("account"), _param("tag")])
    target = _api([_param("account"), _param("tag"), _param("block", required=False)])
    assert _grades(base, target) == {("modified", _REQUEST): (Severity.SAFE, "openrpc.optional-param-added")}


def test_adding_a_required_param_is_breaking():
    base = _api([_param("account"), _param("tag")])
    target = _api([_param("account"), _param("tag"), _param("block")])
    assert _grades(base, target)[("modified", _REQUEST)] == (Severity.BREAKING, "openrpc.required-param-added")


def test_removing_a_param_is_breaking():
    base = _api([_param("account"), _param("tag"), _param("block", required=False)])
    target = _api([_param("account"), _param("tag")])
    assert _grades(base, target)[("modified", _REQUEST)] == (Severity.BREAKING, "openrpc.param-removed")


def test_a_reorder_breaks_positional_callers_but_not_by_name_methods():
    base_params = [_param("account"), _param("block", schema_type="integer")]
    moved = [_param("block", schema_type="integer"), _param("account")]
    assert _grades(_api(base_params), _api(moved))[("modified", _REQUEST)] == (
        Severity.BREAKING,
        "openrpc.param-moved",
    )
    assert _grades(_api(base_params, structure="by-name"), _api(moved, structure="by-name"))[
        ("modified", _REQUEST)
    ] == (Severity.SAFE, "openrpc.param-moved")


def test_a_rename_breaks_by_name_callers_but_not_by_position_methods():
    base = [_param("account"), _param("tag")]
    renamed = [_param("address"), _param("tag")]
    assert _grades(_api(base), _api(renamed))[("modified", _REQUEST)] == (
        Severity.BREAKING,
        "openrpc.param-renamed",
    )
    assert _grades(_api(base, structure="by-position"), _api(renamed, structure="by-position"))[
        ("modified", _REQUEST)
    ] == (Severity.SAFE, "openrpc.param-renamed")


def test_requiredness_flips():
    base = _api([_param("account"), _param("tag", required=False)])
    assert _grades(base, _api([_param("account"), _param("tag")]))[("modified", _REQUEST)] == (
        Severity.BREAKING,
        "openrpc.made-required",
    )
    assert _grades(_api([_param("account"), _param("tag")]), base)[("modified", _REQUEST)] == (
        Severity.SAFE,
        "openrpc.made-optional",
    )


def test_a_param_schema_change_is_dangerous():
    base = _api([_param("account"), _param("tag")])
    target = _api([_param("account"), _param("tag", schema_type="integer")])
    assert _grades(base, target)[("modified", _REQUEST)] == (Severity.DANGEROUS, "openrpc.param-schema-changed")


def test_first_params_added_to_a_parameterless_method():
    assert _grades(_api([]), _api([_param("account", required=False)])) == {
        ("added", _REQUEST): (Severity.SAFE, "openrpc.optional-param-added")
    }
    assert _grades(_api([]), _api([_param("account")])) == {
        ("added", _REQUEST): (Severity.BREAKING, "openrpc.required-param-added")
    }


def test_narrowing_param_structure_is_breaking_and_widening_is_safe():
    params = [_param("account")]
    assert _grades(_api(params), _api(params, structure="by-name")) == {
        ("modified", _KEY): (Severity.BREAKING, "openrpc.param-structure-narrowed")
    }
    assert _grades(_api(params, structure="by-position"), _api(params, structure="either")) == {
        ("modified", _KEY): (Severity.SAFE, "openrpc.param-structure-widened")
    }


def test_result_changes_keep_the_baseline_grade():
    params = [_param("account")]
    grades = _grades(_api(params), _api(params, result="integer"))
    assert all(not rule.startswith("openrpc.") for _, rule in grades.values())
    assert grades


def test_the_worst_of_several_param_changes_wins():
    before = [_param("a"), _param("b", required=False)]
    after = [_param("a", schema_type="integer"), _param("b", required=False), _param("c")]
    assert {rule for _, rule, _ in grade_params(before, after, structure="either")} == {
        "openrpc.required-param-added",
        "openrpc.param-schema-changed",
    }
    assert _grades(_api(before), _api(after))[("modified", _REQUEST)] == (
        Severity.BREAKING,
        "openrpc.required-param-added",
    )


def test_grade_structure_no_change():
    assert grade_structure(None, "either") is None
    assert grade_structure("by-name", "by-name") is None
