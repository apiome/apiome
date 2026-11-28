"""Provider test scaffolding, the generator — PFX-8.19 (#7316).

* each language's file carries the broker from the environment, the recommended selectors, pending
  on, one handler per state and the example parameters;
* a state not registered in Apiome is flagged, in the file and as a notice;
* untrusted names can never break out of a string literal (quotes, backslashes, newlines, comment
  closers, non-ASCII) — the Python file still compiles and reads the names back exactly;
* no secret is written; method names are unique and clear of keywords;
* too many states, a name too long, no pacts and an unknown language are each reported.
"""

from __future__ import annotations

import ast
import json
import re

import pytest

from app.pact_provider_scaffold import (
    CODE_LANGUAGE_UNSUPPORTED,
    LANGUAGES,
    MAX_STATE_NAME,
    MAX_STATES,
    NOTICE_NO_PACTS,
    NOTICE_STATE_LEFT_OUT,
    NOTICE_STATE_UNREGISTERED,
    ScaffoldError,
    ScaffoldState,
    _go_string,
    _identifiers,
    scaffold_provider_test,
)

_STATES = [
    ScaffoldState(
        name="an invoice exists", params=(("id", 1042),), registered=True, setup_kind="state_change", interactions=3
    ),
    ScaffoldState(name="a customer 7 exists", params=(), registered=False, interactions=1),
]

#: A state name a hostile consumer could publish.
_HOSTILE = 'x"); process.exit(1); //\n*/ \\ `${boom}`   é 😀'


@pytest.mark.parametrize("language", list(LANGUAGES))
def test_every_language_wires_the_broker_from_the_environment(language: str) -> None:
    scaffold = scaffold_provider_test("Billing Service", language, _STATES, pacts=2)
    text = scaffold.content
    assert "PACT_BROKER_BASE_URL" in text
    assert "PACT_BROKER_TOKEN" in text
    assert "PROVIDER_BASE_URL" in text
    assert re.search(r"main_?[Bb]ranch", text) or "MainBranch" in text
    assert re.search(r"deployed_?[Oo]r_?[Rr]eleased", text) or "DeployedOrReleased" in text
    assert re.search(r"[Pp]ending", text)
    assert "an invoice exists" in text and "a customer 7 exists" in text
    assert "EXAMPLE_PARAMETERS" in text
    assert text.count("Not registered in Apiome") == 1
    assert [state.name for state in scaffold.states] == ["a customer 7 exists", "an invoice exists"]


@pytest.mark.parametrize(
    "language, name",
    [
        ("typescript", "billing-service.pact.test.ts"),
        ("java", "BillingServicePactTest.java"),
        ("go", "billing_service_pact_test.go"),
        ("python", "test_billing_service_pact.py"),
    ],
)
def test_each_language_has_its_file_name(language: str, name: str) -> None:
    assert scaffold_provider_test("Billing Service", language, _STATES, pacts=1).file_name == name


def test_an_unregistered_state_is_a_notice() -> None:
    scaffold = scaffold_provider_test("Billing Service", "typescript", _STATES, pacts=1)
    assert [(n.code, n.state) for n in scaffold.notices] == [(NOTICE_STATE_UNREGISTERED, "a customer 7 exists")]


def test_the_example_parameters_are_written_as_json() -> None:
    text = scaffold_provider_test("Billing Service", "typescript", _STATES, pacts=1).content
    assert '"an invoice exists": "{\\"id\\":1042}"' in text


def test_the_python_file_compiles_and_reads_every_name_back_exactly() -> None:
    states = [*_STATES, ScaffoldState(name=_HOSTILE, params=(("q", 'a"b'),))]
    text = scaffold_provider_test(_HOSTILE, "python", states, pacts=1).content
    tree = ast.parse(text)
    assigned = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"PROVIDER", "EXAMPLE_PARAMETERS"}
    }
    assert assigned["PROVIDER"] == _HOSTILE
    assert assigned["EXAMPLE_PARAMETERS"][_HOSTILE] == {"q": 'a"b'}
    assert assigned["EXAMPLE_PARAMETERS"]["an invoice exists"] == {"id": 1042}


@pytest.mark.parametrize("language", ["typescript", "java"])
def test_a_hostile_name_stays_inside_a_json_string_literal(language: str) -> None:
    text = scaffold_provider_test("Billing", language, [ScaffoldState(name=_HOSTILE)], pacts=1).content
    literal = json.dumps(_HOSTILE, ensure_ascii=True)
    assert literal in text
    assert "process.exit(1); //\n" not in text
    assert _HOSTILE not in text  # never written raw
    assert all(ord(char) < 0x80 or char in "—" for char in text)


def test_a_hostile_name_stays_inside_a_go_string_literal() -> None:
    text = scaffold_provider_test("Billing", "go", [ScaffoldState(name=_HOSTILE)], pacts=1).content
    assert _go_string(_HOSTILE) in text
    assert _HOSTILE not in text
    assert "\\U0001f600" in _go_string("😀")
    assert _go_string('a"b\\c\n') == '"a\\"b\\\\c\\u000a"'


def test_no_secret_is_written() -> None:
    for language in LANGUAGES:
        text = scaffold_provider_test("Billing Service", language, _STATES, pacts=1).content
        assert not re.search(r"(token|password)\s*[:=]\s*['\"][^'\"$]", text, re.IGNORECASE), language


def test_method_names_are_unique_ascii_and_clear_of_keywords() -> None:
    names = ["class", "class", "1 thing", "é", "an invoice exists"]
    assert _identifiers(names, "camel") == [
        "givenClass",
        "givenClass2",
        "given1Thing",
        "givenState",
        "givenAnInvoiceExists",
    ]
    assert _identifiers(names, "snake") == [
        "given_class",
        "given_class_2",
        "given_1_thing",
        "given_state",
        "given_an_invoice_exists",
    ]


def test_too_many_states_and_a_name_too_long_are_left_out_with_a_reason() -> None:
    states = [ScaffoldState(name=f"state {index:04d}", registered=True) for index in range(MAX_STATES + 2)]
    states.append(ScaffoldState(name="y" * (MAX_STATE_NAME + 1), registered=True))
    scaffold = scaffold_provider_test("Billing", "go", states, pacts=1)
    left_out = [notice for notice in scaffold.notices if notice.code == NOTICE_STATE_LEFT_OUT]
    assert len(scaffold.states) == MAX_STATES
    assert len(left_out) == 3
    assert any("longer than" in notice.message for notice in left_out)


def test_no_pacts_still_writes_a_file_and_says_why_it_has_no_handlers() -> None:
    scaffold = scaffold_provider_test("Billing", "java", [], pacts=0)
    assert [notice.code for notice in scaffold.notices] == [NOTICE_NO_PACTS]
    assert "Map.of()" in scaffold.content
    assert "@State" not in scaffold.content


def test_an_unknown_language_is_refused() -> None:
    with pytest.raises(ScaffoldError) as raised:
        scaffold_provider_test("Billing", "cobol", [], pacts=1)
    assert raised.value.code == CODE_LANGUAGE_UNSUPPORTED
    assert "typescript, java, go, python" in str(raised.value)


def test_the_same_states_always_write_the_same_file() -> None:
    first = scaffold_provider_test("Billing", "typescript", _STATES, pacts=1).content
    second = scaffold_provider_test("Billing", "typescript", list(reversed(_STATES)), pacts=1).content
    assert first == second
