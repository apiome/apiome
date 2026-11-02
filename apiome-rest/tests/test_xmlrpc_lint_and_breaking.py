"""Tests for the XML-RPC method description: the migrate note, lint and breaking changes —
MFI-21.6 (#3996)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from app.breaking_change import Severity, available_breaking_change_formats, classify_models
from app.format_lint_capabilities import MODE_NATIVE, capability_for_format
from app.lint_engine import get_rule_pack, lint_canonical_model
from app.xmlrpc_breaking import XmlRpcBreakingChangeClassifier
from app.xmlrpc_import_source import XmlRpcImportSource
from app.xmlrpc_lint import JSON_SCHEMA_FOR_VALUE, SYSTEM_METHODS, XmlRpcRulePack

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "xml-rpc"
_VALID = [
    "01-method-call.xml",
    "02-method-response.xml",
    "03-minimal-call.xml",
    "04-system-multicall.xml",
    "05-all-types-response.xml",
    "06-wordpress-get-post.xml",
]


def _fixture(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


def _call(method: str = "inventory.reserveStock", params: str = "") -> str:
    return f'<?xml version="1.0"?><methodCall><methodName>{method}</methodName><params>{params}</params></methodCall>'


def _param(inner: str) -> str:
    return f"<param><value>{inner}</value></param>"


def _response(inner: str) -> str:
    return (
        f'<?xml version="1.0"?><methodResponse><params><param><value>{inner}</value></param></params></methodResponse>'
    )


def _fault(code: str, text: str) -> str:
    return (
        '<?xml version="1.0"?><methodResponse><fault><value><struct>'
        f"<member><name>faultCode</name><value><int>{code}</int></value></member>"
        f"<member><name>faultString</name><value><string>{text}</string></value></member>"
        "</struct></value></fault></methodResponse>"
    )


_STRUCT = (
    "<struct><member><name>customerId</name><value><string>c-1</string></value></member>"
    "<member><name>priority</name><value><boolean>1</boolean></value></member></struct>"
)
_CALL = _call(params=_param("<string>WIDGET-001</string>") + _param("<int>5</int>") + _param(_STRUCT))


def _api(text: str):
    adapter = XmlRpcImportSource()
    return adapter.normalize(adapter.parse(text, source_label="call.xml"), include_raw=False)


def _findings(text: str) -> List[Tuple[str, str, str]]:
    result = lint_canonical_model(_api(text))
    return sorted((f.rule, f.severity, f.path) for f in result.findings if f.rule.startswith("xmlrpc."))


def _grades(base: str, target: str) -> Dict[Tuple[str, str], Tuple[Severity, str]]:
    """``(kind, key)`` → ``(severity, rule_id)`` for the diff of two descriptions."""
    result = classify_models(_api(base), _api(target))
    assert result.classifier == "xmlrpc-signature"
    return {(c.kind.value, c.key): (c.severity, c.rule_id) for c in result.classifications}


# --- the migrate-to-JSON-RPC note ---------------------------------------------------------


def test_the_migration_note_rewrites_a_call_as_json_rpc():
    note = _api(_CALL).extras["xmlrpc_migration"]
    assert note["target"] == "openrpc"
    assert note["request"]["jsonrpc"] == "2.0" and note["request"]["method"] == "inventory.reserveStock"
    assert note["request"]["params"][0] == {"type": "string"}
    assert note["request"]["params"][1] == {"type": "integer"}
    assert note["request"]["params"][2]["type"] == "object"
    assert note["request"]["params"][2]["properties"]["priority"] == {"type": "boolean"}
    assert set(note["value_types"]) == {"string", "int", "struct", "boolean"}
    assert JSON_SCHEMA_FOR_VALUE["base64"]["contentEncoding"] == "base64"


def test_the_migration_note_rewrites_a_response_and_a_fault():
    response = _api(_fixture("02-method-response.xml")).extras["xmlrpc_migration"]
    assert response["response"]["result"]["type"] == "object"
    assert response["response"]["result"]["properties"]["remaining"] == {"type": "integer"}
    fault = _api(_fault("-32601", "method not found")).extras["xmlrpc_migration"]
    assert fault["response"]["error"] == {"code": -32601, "message": "method not found"}


# --- lint ---------------------------------------------------------------------------------


def test_the_lint_pack_is_registered():
    assert get_rule_pack("xmlrpc") is not None
    assert capability_for_format("xmlrpc").mode == MODE_NATIVE
    ids = [rule.rule_id for rule in XmlRpcRulePack().rules()]
    assert len(ids) == len(set(ids)) and all(i.startswith("xmlrpc.") for i in ids)
    assert "system.multicall" in SYSTEM_METHODS


@pytest.mark.parametrize("name", [n for n in _VALID if n not in {"03-minimal-call.xml", "05-all-types-response.xml"}])
def test_every_full_example_is_clean(name: str):
    assert _findings(_fixture(name)) == []


def test_the_minimal_call_uses_an_unknown_system_method():
    assert _findings(_fixture("03-minimal-call.xml")) == [("xmlrpc.system-method-known", "warning", "methodName")]


def test_the_all_types_response_notes_the_nil_extension():
    assert _findings(_fixture("05-all-types-response.xml")) == [
        ("xmlrpc.nil-extension", "info", "params.0.deprecatedField"),
    ]


def test_method_name_rules():
    assert ("xmlrpc.method-name-namespaced", "info", "methodName") in _findings(_call(method="reserveStock"))
    assert not [f for f in _findings(_CALL) if f[0] == "xmlrpc.method-name-namespaced"]
    assert not [f for f in _findings(_call(method="system.listMethods")) if f[0] == "xmlrpc.system-method-known"]


def test_response_and_fault_rules():
    empty = '<?xml version="1.0"?><methodResponse><params></params></methodResponse>'
    assert ("xmlrpc.response-has-value", "warning", "params") in _findings(empty)
    assert ("xmlrpc.fault-described", "warning", "fault.faultCode") in _findings(_fault("0", "boom"))
    assert ("xmlrpc.fault-described", "warning", "fault.faultString") in _findings(_fault("4", " "))
    assert not [f for f in _findings(_fault("4", "boom")) if f[0] == "xmlrpc.fault-described"]


def test_value_rules():
    assert ("xmlrpc.nil-extension", "info", "params.1") in _findings(
        _call(params=_param("<string>a</string>") + _param("<nil/>"))
    )
    empty_array = _call(params=_param("<array><data></data></array>"))
    assert ("xmlrpc.array-item-type-known", "info", "params.0") in _findings(empty_array)
    nested_empty = _response(
        "<struct><member><name>items</name><value><array><data></data></array></value></member></struct>"
    )
    assert ("xmlrpc.array-item-type-known", "info", "params.0.items") in _findings(nested_empty)


def test_multicall_rule():
    bad = _call(
        method="system.multicall",
        params=_param(
            "<array><data><value><struct><member><name>methodName</name><value><string>a.b</string></value></member></struct></value></data></array>"
        ),
    )
    assert ("xmlrpc.multicall-calls-wellformed", "warning", "params.0[0]") in _findings(bad)
    not_an_array = _call(method="system.multicall", params=_param("<string>a.b</string>"))
    assert ("xmlrpc.multicall-calls-wellformed", "warning", "params.0") in _findings(not_an_array)


# --- breaking changes ---------------------------------------------------------------------


def test_the_classifier_is_registered_for_xmlrpc():
    assert "xmlrpc" in available_breaking_change_formats()
    assert XmlRpcBreakingChangeClassifier.classifier_id == "xmlrpc-signature"


def test_the_method_call_fixture_is_graded_by_signature():
    base = _fixture("01-method-call.xml")
    target = base.replace("<value><int>5</int></value>", "<value><string>5</string></value>").replace(
        "<name>priority</name>", "<name>urgent</name>"
    )
    grades = _grades(base, target)
    assert grades[("modified", "inventory.reserveStock.inventory.reserveStock#request")] == (
        Severity.BREAKING,
        "xmlrpc.param-type-changed",
    )
    assert grades[("removed", "InventoryReserveStockParam3.priority")] == (Severity.BREAKING, "xmlrpc.member-removed")
    assert grades[("added", "InventoryReserveStockParam3.urgent")] == (
        Severity.DANGEROUS,
        "xmlrpc.member-added-to-call",
    )


def test_param_grades():
    request = ("modified", "inventory.reserveStock.inventory.reserveStock#request")
    fewer = _call(params=_param("<string>WIDGET-001</string>") + _param("<int>5</int>"))
    assert _grades(_CALL, fewer)[request] == (Severity.BREAKING, "xmlrpc.param-removed")
    assert _grades(fewer, _CALL)[request] == (Severity.BREAKING, "xmlrpc.param-added")
    other_sample = _CALL.replace("<int>5</int>", "<int>7</int>")
    assert _grades(_CALL, other_sample)[request] == (Severity.SAFE, "xmlrpc.sample-changed")


def test_response_grades():
    response = ("modified", "XML-RPC Response.response#response")
    other_sample = _fixture("02-method-response.xml").replace("<int>120</int>", "<int>121</int>")
    grades = _grades(_fixture("02-method-response.xml"), other_sample)
    assert grades[response] == (Severity.SAFE, "xmlrpc.sample-changed")
    assert grades[("modified", "ResponseResponse")] == (Severity.SAFE, "xmlrpc.sample-changed")
    retyped = _grades(_response("<int>1</int>"), _response("<string>one</string>"))
    assert retyped[response] == (Severity.DANGEROUS, "xmlrpc.result-type-changed")
    added = _grades(
        _response("<struct><member><name>a</name><value><int>1</int></value></member></struct>"),
        _response(
            "<struct><member><name>a</name><value><int>1</int></value></member><member><name>b</name><value><int>2</int></value></member></struct>"
        ),
    )
    assert added[("added", "ResponseResponse.b")] == (Severity.SAFE, "xmlrpc.member-added-to-response")


def test_member_type_and_fault_grades():
    retyped = _CALL.replace("<value><boolean>1</boolean></value>", "<value><string>yes</string></value>")
    assert _grades(_CALL, retyped)[("modified", "InventoryReserveStockParam3.priority")] == (
        Severity.BREAKING,
        "xmlrpc.member-type-changed",
    )
    assert _grades(_fault("4", "boom"), _fault("5", "bang"))[("modified", "XML-RPC Fault.fault")] == (
        Severity.SAFE,
        "xmlrpc.fault-changed",
    )


def test_what_the_rules_do_not_cover_falls_back_to_the_baseline():
    grades = _grades(_call(method="a.b"), _call(method="a.c"))
    assert grades[("removed", "a.b.a.b")] == (Severity.BREAKING, "removed-entity")
