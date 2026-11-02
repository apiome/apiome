"""Tests for the FIX Orchestra lint pack — MFI-20.4 (#3988)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pytest

from app.fix_orchestra_import_source import FixOrchestraImportSource
from app.fix_orchestra_lint import FixOrchestraRulePack
from app.format_lint_capabilities import MODE_NATIVE, capability_for_format
from app.lint_engine import get_rule_pack, lint_canonical_model

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "fix-orchestra"
_NS = "http://fixprotocol.io/2020/orchestra/repository"


def _findings(text: str) -> List[Tuple[str, str, str]]:
    """``(rule, severity, path)`` of every ``fix-orchestra.*`` finding for a repository."""
    adapter = FixOrchestraImportSource()
    api = adapter.normalize(adapter.parse(text, source_label="repo.xml"), include_raw=False)
    result = lint_canonical_model(api)
    return sorted((f.rule, f.severity, f.path) for f in result.findings if f.rule.startswith("fix-orchestra."))


def _repository(body: str, *, attrs: str = 'name="T" version="FIX.4.4"') -> str:
    return f'<fixr:repository xmlns:fixr="{_NS}" {attrs}>{body}</fixr:repository>'


_FIELDS = (
    '<fixr:fields><fixr:field id="11" name="ClOrdID" type="String"/>'
    '<fixr:field id="54" name="Side" type="SideCodeSet"/></fixr:fields>'
)
_SIDE = (
    '<fixr:codeSets><fixr:codeSet name="SideCodeSet" id="54" type="char">'
    '<fixr:code name="Buy" id="1" value="1"/><fixr:code name="Sell" id="2" value="2"/>'
    "</fixr:codeSet></fixr:codeSets>"
)


def _message(structure: str, attrs: str = 'name="NewOrderSingle" id="14" msgType="D"') -> str:
    return f"<fixr:message {attrs}><fixr:structure>{structure}</fixr:structure></fixr:message>"


def _messages(*messages: str) -> str:
    return "<fixr:messages>" + "".join(messages) + "</fixr:messages>"


def test_the_pack_is_registered_for_fix_orchestra():
    assert get_rule_pack("fix-orchestra") is not None
    assert capability_for_format("fix-orchestra").mode == MODE_NATIVE
    ids = [rule.rule_id for rule in FixOrchestraRulePack().rules()]
    assert len(ids) == len(set(ids)) and all(i.startswith("fix-orchestra.") for i in ids)


@pytest.mark.parametrize(
    "name",
    [
        "01-minimal-repository.xml",
        "02-typical-order-repository.xml",
        "03-composition-components-and-groups.xml",
        "04-stress-presence-and-rules.xml",
        "05-real-world-execution-flow.xml",
        "06-typical-actors-and-state-machine.xml",
        "08-typical-order-repository-venue-dialect.xml",
    ],
)
def test_every_example_is_clean(name: str):
    assert _findings((_EXAMPLES / name).read_text(encoding="utf-8")) == []


def test_message_msgtype_declared():
    text = _repository(_SIDE + _FIELDS + _messages(_message('<fixr:fieldRef id="11"/>', 'name="Odd" id="99"')))
    assert ("fix-orchestra.message-msgtype-declared", "error", "types.Odd") in _findings(text)


def test_msgtype_unique():
    text = _repository(
        _SIDE + _FIELDS + _messages(
            _message('<fixr:fieldRef id="11"/>'),
            _message('<fixr:fieldRef id="54"/>', 'name="Other" id="15" msgType="D"'),
        )
    )
    assert ("fix-orchestra.msgtype-unique", "error", "messages.D") in _findings(text)


def test_message_not_empty():
    text = _repository(_SIDE + _FIELDS + _messages(_message("")))
    assert ("fix-orchestra.message-not-empty", "warning", "types.NewOrderSingle") in _findings(text)


def test_codeset_rules():
    empty = '<fixr:codeSets><fixr:codeSet name="SideCodeSet" id="54" type="char"/></fixr:codeSets>'
    text = _repository(empty + _FIELDS + _messages(_message('<fixr:fieldRef id="54"/>')))
    assert ("fix-orchestra.codeset-not-empty", "warning", "types.SideCodeSet") in _findings(text)
    dupes = (
        '<fixr:codeSets><fixr:codeSet name="SideCodeSet" id="54" type="char">'
        '<fixr:code name="Buy" id="1" value="1"/><fixr:code name="Sell" id="2" value="1"/>'
        "</fixr:codeSet></fixr:codeSets>"
    )
    text = _repository(dupes + _FIELDS + _messages(_message('<fixr:fieldRef id="54"/>')))
    assert ("fix-orchestra.code-values-unique", "error", "types.SideCodeSet") in _findings(text)


def test_conditional_rule_declared():
    text = _repository(_SIDE + _FIELDS + _messages(_message('<fixr:fieldRef id="11" presence="conditional"/>')))
    assert (
        "fix-orchestra.conditional-rule-declared",
        "warning",
        "types.NewOrderSingle.fields.NewOrderSingle.ClOrdID",
    ) in _findings(text)


def test_repository_version_declared():
    text = _repository(_SIDE + _FIELDS + _messages(_message('<fixr:fieldRef id="11"/>')), attrs='name="T"')
    assert ("fix-orchestra.repository-version-declared", "info", "repository.version") in _findings(text)
