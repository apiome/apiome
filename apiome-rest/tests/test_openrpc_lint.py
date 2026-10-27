"""Tests for the OpenRPC lint pack — MFI-19.1 (#3979)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from app.format_lint_capabilities import MODE_NATIVE, capability_for_format
from app.lint_engine import get_rule_pack, lint_canonical_model
from app.openrpc_normalizer import OpenRpcNormalizer
from app.openrpc_parser import parse_openrpc

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui/examples/openrpc"
_PATH = "services.Wallet.operations.Wallet"


def _findings(methods: List[Dict[str, Any]]) -> List[Tuple[str, str, str]]:
    """``(rule, severity, path)`` of every ``openrpc.*`` finding for a document."""
    doc = {"openrpc": "1.2.6", "info": {"title": "Wallet", "version": "1"}, "methods": methods}
    return _findings_for(json.dumps(doc))


def _findings_for(text: str) -> List[Tuple[str, str, str]]:
    api = OpenRpcNormalizer().normalize(parse_openrpc(text), include_raw=False)
    result = lint_canonical_model(api)
    return sorted((f.rule, f.severity, f.path) for f in result.findings if f.rule.startswith("openrpc."))


def _method(name: str, *params: Dict[str, Any], summary: str = "Does a thing.") -> Dict[str, Any]:
    return {"name": name, "summary": summary, "params": list(params), "result": {"name": "r", "schema": {}}}


def _param(name: str, required: bool = True) -> Dict[str, Any]:
    return {"name": name, "required": required, "schema": {"type": "string"}}


def test_the_pack_is_registered_and_native_for_openrpc():
    assert get_rule_pack("openrpc") is not None
    assert capability_for_format("openrpc").mode == MODE_NATIVE


def test_a_clean_document_has_no_openrpc_findings():
    assert _findings([_method("getBalance", _param("account"), _param("block", required=False))]) == []


@pytest.mark.parametrize("path", sorted(p.name for p in _EXAMPLES.glob("*.json")))
def test_the_corpus_documents_have_no_blocking_findings(path: str):
    findings = _findings_for((_EXAMPLES / path).read_text(encoding="utf-8"))
    assert [f for f in findings if f[1] == "error"] == []


def test_unique_method_names():
    assert _findings([_method("a"), _method("a")]) == [("openrpc.unique-method-names", "error", "services.Wallet")]


def test_unique_param_names():
    assert _findings([_method("a", _param("x"), _param("x"))]) == [
        ("openrpc.unique-param-names", "error", f"{_PATH}.a")
    ]


def test_required_params_first():
    assert _findings([_method("a", _param("x", required=False), _param("y"))]) == [
        ("openrpc.required-params-first", "error", f"{_PATH}.a")
    ]


def test_reserved_method_name_exempts_rpc_discover():
    assert _findings([_method("rpc.ping"), _method("rpc.discover")]) == [
        ("openrpc.reserved-method-name", "warning", f"{_PATH}.rpc.ping")
    ]


def test_method_described():
    assert _findings([{"name": "bare", "params": [], "result": {"name": "r", "schema": {}}}]) == [
        ("openrpc.method-described", "info", f"{_PATH}.bare")
    ]
