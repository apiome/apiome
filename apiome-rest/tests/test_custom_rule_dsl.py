"""Tests for the Spectral-compatible custom rule DSL (GOV-1.3, #4429).

Covers: strict YAML parsing/validation with pointers, every core function's evaluation
semantics, the 10-rule sample guide on the Petstore fixture (acceptance), the JSONPath
node-budget sandbox (including a fuzz test), and the regex match timeout.
"""

import random
from pathlib import Path

import pytest
import yaml

from app.custom_rule_dsl import (
    MAX_GIVEN_PER_RULE,
    MAX_RULES_PER_GUIDE,
    MAX_THEN_PER_RULE,
    CustomRuleValidationError,
    evaluate_custom_rules,
    parse_style_guide_yaml,
    validate_custom_definition,
)

PETSTORE = Path(__file__).parent / "fixtures" / "openapi_family" / "openapi-3.1-petstore.yaml"


def _guide(rules_yaml: str) -> str:
    """Indent a rules body under the top-level `rules:` key."""
    indented = "\n".join(f"  {line}" if line.strip() else line for line in rules_yaml.splitlines())
    return f"rules:\n{indented}\n"


def _one_rule(body: str) -> str:
    """A guide with a single rule `r` whose definition is `body`."""
    return _guide("r:\n" + "\n".join(f"  {line}" for line in body.splitlines()))


def _eval_yaml(guide_yaml: str, document, **kwargs):
    return evaluate_custom_rules(parse_style_guide_yaml(guide_yaml), document, **kwargs)


def _pointer_of(guide_yaml: str) -> str:
    with pytest.raises(CustomRuleValidationError) as err:
        parse_style_guide_yaml(guide_yaml)
    return err.value.pointer


# --- Parsing and strict validation ------------------------------------------------------------


def test_valid_guide_parses_in_author_order():
    ruleset = parse_style_guide_yaml(
        _guide(
            "b-rule:\n"
            "  description: second alphabetically, first by author\n"
            "  severity: error\n"
            "  given: $.info\n"
            "  then: {field: title, function: truthy}\n"
            "a-rule:\n"
            "  description: first alphabetically\n"
            "  given: [$.info, $.servers]\n"
            "  then:\n"
            "    - {function: defined}\n"
            "    - {field: description, function: truthy}\n"
        )
    )
    assert ruleset.rule_ids() == ["b-rule", "a-rule"]
    b_rule, a_rule = ruleset.rules
    assert b_rule.severity == "error"
    assert a_rule.severity == "warning"  # default
    assert a_rule.given == ("$.info", "$.servers")
    assert len(a_rule.then) == 2 and a_rule.then[0].field is None


def test_rule_as_dict_round_trips_through_validate_custom_definition():
    # as_dict() is the custom_def jsonb shape (GOV-1.1); it must re-validate unchanged.
    rule = parse_style_guide_yaml(
        _one_rule(
            "description: d\n"
            "severity: info\n"
            "given: $.info\n"
            "then: {field: title, function: pattern, functionOptions: {match: '^A'}}\n"
        )
    ).rules[0]
    again = validate_custom_definition(rule.rule_id, rule.as_dict())
    assert again == rule


def test_empty_or_non_mapping_documents_rejected():
    for text in ("", "   \n", "- a\n- b\n", "just a string\n"):
        with pytest.raises(CustomRuleValidationError):
            parse_style_guide_yaml(text)


def test_unparseable_yaml_reports_line():
    with pytest.raises(CustomRuleValidationError) as err:
        parse_style_guide_yaml("rules:\n  bad: [unclosed\n")
    assert "invalid YAML" in err.value.message


def test_duplicate_mapping_keys_rejected():
    text = (
        "rules:\n"
        "  dup:\n"
        "    description: first\n"
        "    given: $.info\n"
        "    then: {function: defined}\n"
        "  dup:\n"
        "    description: second silently wins without strict loading\n"
        "    given: $.info\n"
        "    then: {function: defined}\n"
    )
    with pytest.raises(CustomRuleValidationError) as err:
        parse_style_guide_yaml(text)
    assert "duplicate" in err.value.message


def test_unknown_top_level_key_rejected_with_pointer():
    assert _pointer_of("extends: spectral:oas\nrules:\n  r:\n    description: d\n") == "extends"


def test_missing_and_empty_rules_rejected():
    assert _pointer_of("rules: {}\n") == "rules"
    assert _pointer_of("rules: 3\n") == "rules"


@pytest.mark.parametrize(
    ("body", "pointer"),
    [
        ("severity: warning\ngiven: $.info\nthen: {function: defined}\n", "rules.r.description"),
        ("description: d\nseverity: fatal\ngiven: $.info\nthen: {function: defined}\n", "rules.r.severity"),
        ("description: d\nthen: {function: defined}\n", "rules.r.given"),
        ("description: d\ngiven: []\nthen: {function: defined}\n", "rules.r.given"),
        ("description: d\ngiven: 7\nthen: {function: defined}\n", "rules.r.given"),
        ("description: d\ngiven: ['$.a', 'nope']\nthen: {function: defined}\n", "rules.r.given[1]"),
        ("description: d\ngiven: $.info\n", "rules.r.then"),
        ("description: d\ngiven: $.info\nthen: []\n", "rules.r.then"),
        ("description: d\ngiven: $.info\nthen: {function: js}\n", "rules.r.then.function"),
        ("description: d\ngiven: $.info\nthen: {field: 3, function: defined}\n", "rules.r.then.field"),
        (
            "description: d\ngiven: $.info\nthen: [{function: defined}, {function: nope}]\n",
            "rules.r.then[1].function",
        ),
        (
            "description: d\ngiven: $.info\nthen: {function: defined, extra: 1}\n",
            "rules.r.then.extra",
        ),
        ("description: d\nowner: me\ngiven: $.info\nthen: {function: defined}\n", "rules.r.owner"),
    ],
)
def test_malformed_rule_pointers(body, pointer):
    assert _pointer_of(_one_rule(body)) == pointer


@pytest.mark.parametrize(
    ("then", "pointer"),
    [
        # pattern: options required, must be valid regexes, unknown keys rejected
        ("{function: pattern}", "rules.r.then.functionOptions"),
        ("{function: pattern, functionOptions: {match: '('}}", "rules.r.then.functionOptions.match"),
        ("{function: pattern, functionOptions: {match: '^a', x: 1}}", "rules.r.then.functionOptions.x"),
        ("{function: pattern, functionOptions: {notMatch: 9}}", "rules.r.then.functionOptions.notMatch"),
        # casing: type required and constrained
        ("{function: casing}", "rules.r.then.functionOptions.type"),
        ("{function: casing, functionOptions: {type: shouty}}", "rules.r.then.functionOptions.type"),
        (
            "{function: casing, functionOptions: {type: camel, disallowDigits: 3}}",
            "rules.r.then.functionOptions.disallowDigits",
        ),
        # enumeration: non-empty scalar list
        ("{function: enumeration}", "rules.r.then.functionOptions.values"),
        ("{function: enumeration, functionOptions: {values: []}}", "rules.r.then.functionOptions.values"),
        (
            "{function: enumeration, functionOptions: {values: [{a: 1}]}}",
            "rules.r.then.functionOptions.values[0]",
        ),
        # length: at least one numeric bound, min <= max
        ("{function: length}", "rules.r.then.functionOptions"),
        ("{function: length, functionOptions: {min: two}}", "rules.r.then.functionOptions.min"),
        ("{function: length, functionOptions: {min: true}}", "rules.r.then.functionOptions.min"),
        ("{function: length, functionOptions: {min: 5, max: 2}}", "rules.r.then.functionOptions.min"),
        # truthy/defined/undefined take no options
        ("{function: truthy, functionOptions: {x: 1}}", "rules.r.then.functionOptions"),
    ],
)
def test_function_option_pointers(then, pointer):
    body = f"description: d\ngiven: $.info\nthen: {then}\n"
    assert _pointer_of(_one_rule(body)) == pointer


@pytest.mark.parametrize(
    "given",
    [
        "info.title",  # must start at $
        "$.." + "a..b" * 3 + "..c..d",  # too many recursive descents
        "$.a[?(@.x =~ /re/)]",  # =~ bypasses the regex sandbox
        "$.a[",  # unparseable
        "$." + "a" * 600,  # too long
    ],
)
def test_given_expressions_rejected(given):
    body = f"description: d\ngiven: {given!r}\nthen: {{function: defined}}\n"
    assert _pointer_of(_one_rule(body)) == "rules.r.given"


@pytest.mark.parametrize("rule_id", ["Bad Id", "-leading", "UPPER", "a..b", ""])
def test_bad_rule_ids_rejected(rule_id):
    with pytest.raises(CustomRuleValidationError):
        validate_custom_definition(
            rule_id, {"description": "d", "given": "$.info", "then": {"function": "defined"}}
        )


def test_rule_id_may_not_shadow_builtin_or_reserved_ids():
    definition = {"description": "d", "given": "$.info", "then": {"function": "defined"}}
    with pytest.raises(CustomRuleValidationError) as err:
        validate_custom_definition(
            "common.type-missing-description",
            definition,
            reserved_rule_ids=frozenset({"common.type-missing-description"}),
        )
    assert "shadows a built-in rule" in err.value.message
    # Without the reservation the (well-formed) id is accepted.
    assert validate_custom_definition("common.type-missing-description", definition)


def test_guide_and_rule_cardinality_caps():
    too_many_rules = "rules:\n" + "".join(
        f"  r{i}:\n    description: d\n    given: $.a\n    then: {{function: defined}}\n"
        for i in range(MAX_RULES_PER_GUIDE + 1)
    )
    assert _pointer_of(too_many_rules) == "rules"

    givens = ", ".join(["'$.a'"] * (MAX_GIVEN_PER_RULE + 1))
    assert (
        _pointer_of(_one_rule(f"description: d\ngiven: [{givens}]\nthen: {{function: defined}}\n"))
        == "rules.r.given"
    )

    thens = ", ".join(["{function: defined}"] * (MAX_THEN_PER_RULE + 1))
    assert (
        _pointer_of(_one_rule(f"description: d\ngiven: $.a\nthen: [{thens}]\n"))
        == "rules.r.then"
    )


def test_oversized_document_rejected():
    padding = "rules:\n  r:\n    description: " + "x" * 300_000
    with pytest.raises(CustomRuleValidationError) as err:
        parse_style_guide_yaml(padding)
    assert "exceeds" in err.value.message


# --- Core function evaluation semantics --------------------------------------------------------


DOC = {
    "info": {"title": "Pet Store", "version": "1.4.0", "x-count": 3},
    "servers": [{"url": "https://api.example.com"}, {"url": "http://insecure.example.com"}],
    "tags": [],
    "flags": {"beta": False},
}


def _rule_findings(then: str, given: str = "$.info", doc=DOC):
    guide = _one_rule(f"description: d\ngiven: {given!r}\nthen: {then}\n")
    evaluation = _eval_yaml(guide, doc)
    assert evaluation.rule_errors == {}
    return evaluation.findings


def test_truthy_flags_falsy_and_missing_values():
    assert _rule_findings("{field: title, function: truthy}") == ()
    # Missing field -> flagged as undefined.
    findings = _rule_findings("{field: description, function: truthy}")
    assert [f.path for f in findings] == ["info"]
    # Present but falsy -> flagged as not truthy.
    findings = _rule_findings("{field: beta, function: truthy}", given="$.flags")
    assert [f.path for f in findings] == ["flags.beta"]
    assert "truthy" in findings[0].message
    # A matched empty array is falsy too.
    assert len(_rule_findings("{function: truthy}", given="$.tags")) == 1


def test_defined_and_undefined_are_complements():
    assert _rule_findings("{field: title, function: defined}") == ()
    assert len(_rule_findings("{field: missing, function: defined}")) == 1
    assert _rule_findings("{field: missing, function: undefined}") == ()
    findings = _rule_findings("{field: title, function: undefined}")
    assert len(findings) == 1 and "undefined" in findings[0].message


def test_pattern_match_and_not_match():
    assert _rule_findings(
        "{field: url, function: pattern, functionOptions: {match: '^https://'}}",
        given="$.servers[*]",
    )[0].path == "servers[1].url"
    findings = _rule_findings(
        "{field: url, function: pattern, functionOptions: {notMatch: 'insecure'}}",
        given="$.servers[*]",
    )
    assert [f.path for f in findings] == ["servers[1].url"]
    # Non-string and absent targets are ignored (use truthy/defined to require presence).
    assert _rule_findings("{field: x-count, function: pattern, functionOptions: {match: 'x'}}") == ()
    assert _rule_findings("{field: missing, function: pattern, functionOptions: {match: 'x'}}") == ()


@pytest.mark.parametrize(
    ("casing_type", "good", "bad"),
    [
        ("flat", "flatcase1", "flatCase"),
        ("camel", "camelCase1", "PascalCase"),
        ("pascal", "PascalCase1", "camelCase"),
        ("kebab", "kebab-case-1", "kebab_case"),
        ("cobol", "COBOL-CASE-1", "cobol-case"),
        ("snake", "snake_case_1", "snake-case"),
        ("macro", "MACRO_CASE_1", "macro_case"),
    ],
)
def test_casing_types(casing_type, good, bad):
    doc = {"values": {"good": good, "bad": bad}}
    then = f"{{function: casing, functionOptions: {{type: {casing_type}}}}}"
    findings = _rule_findings(then, given="$.values[*]", doc=doc)
    assert [f.path for f in findings] == ["values.bad"]
    assert f"not {casing_type} case" in findings[0].message


def test_casing_disallow_digits():
    doc = {"values": {"digits": "camelCase1"}}
    then = "{function: casing, functionOptions: {type: camel, disallowDigits: true}}"
    assert len(_rule_findings(then, given="$.values[*]", doc=doc)) == 1


def test_casing_applies_to_object_keys_via_at_key():
    doc = {"components": {"schemas": {"Pet": {}, "petTag": {}}}}
    findings = _rule_findings(
        "{field: '@key', function: casing, functionOptions: {type: pascal}}",
        given="$.components.schemas",
        doc=doc,
    )
    assert [f.path for f in findings] == ["components.schemas.petTag"]


def test_enumeration():
    doc = {"params": [{"in": "path"}, {"in": "query"}]}
    findings = _rule_findings(
        "{field: in, function: enumeration, functionOptions: {values: [query, header]}}",
        given="$.params[*]",
        doc=doc,
    )
    assert [f.path for f in findings] == ["params[0].in"]
    assert "'path'" in findings[0].message


def test_length_on_strings_collections_and_numbers():
    doc = {"a": "abc", "b": [1, 2], "c": {"k": 1}, "n": 5}
    assert _rule_findings("{function: length, functionOptions: {min: 3}}", given="$.a", doc=doc) == ()
    assert len(_rule_findings("{function: length, functionOptions: {min: 3}}", given="$.b", doc=doc)) == 1
    assert len(_rule_findings("{function: length, functionOptions: {max: 0}}", given="$.c", doc=doc)) == 1
    # Numbers compare by value (Spectral semantics).
    assert _rule_findings("{function: length, functionOptions: {max: 5}}", given="$.n", doc=doc) == ()
    assert len(_rule_findings("{function: length, functionOptions: {max: 4}}", given="$.n", doc=doc)) == 1


def test_findings_carry_rule_identity_severity_and_custom_category():
    guide = _one_rule(
        "description: Servers must use https.\n"
        "severity: error\n"
        "given: '$.servers[*].url'\n"
        "then: {function: pattern, functionOptions: {match: '^https://'}}\n"
    )
    findings = _eval_yaml(guide, DOC).findings
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule == "r"
    assert finding.severity == "error"
    assert finding.category == "custom"
    assert finding.message.startswith("Servers must use https.")
    assert finding.id.startswith("lint-")


def test_evaluation_is_deterministic_and_pure():
    guide = _one_rule(
        "description: d\ngiven: '$..url'\nthen: {function: pattern, functionOptions: {match: '^https'}}\n"
    )
    import copy

    doc = copy.deepcopy(DOC)
    first = _eval_yaml(guide, doc)
    second = _eval_yaml(guide, doc)
    assert first == second
    assert doc == DOC  # the document is never mutated


def test_wildcard_iterates_object_properties_like_spectral():
    # jsonpath-ng natively collapses `[*]` on a dict to a values list; the DSL restores
    # Spectral semantics: object keys appear in match paths.
    doc = {"paths": {"/pets/{id}": {"get": {"responses": {}}}}}
    findings = _rule_findings("{field: summary, function: truthy}", given="$.paths[*][*]", doc=doc)
    assert [f.path for f in findings] == ["paths./pets/{id}.get"]


def test_filter_expressions_select_matching_items():
    doc = {"params": [{"in": "path"}, {"in": "query", "required": True}]}
    findings = _rule_findings(
        "{field: required, function: truthy}",
        given="$.params[?(@.in == 'path')]",
        doc=doc,
    )
    assert len(findings) == 1


# --- Acceptance: a 10-rule sample guide on Petstore --------------------------------------------


PETSTORE_GUIDE = """
rules:
  info-has-description:
    description: The API carries a top-level description.
    severity: warning
    given: $.info
    then: {field: description, function: truthy}
  version-is-semver:
    description: info.version is semantic (MAJOR.MINOR.PATCH).
    severity: error
    given: $.info.version
    then: {function: pattern, functionOptions: {match: '^\\d+\\.\\d+\\.\\d+$'}}
  servers-use-https:
    description: Every server URL uses https.
    severity: error
    given: "$.servers[*].url"
    then: {function: pattern, functionOptions: {match: '^https://'}}
  operations-have-summary:
    description: Every operation carries a summary.
    severity: warning
    given: "$.paths[*][*]"
    then: {field: summary, function: truthy}
  operations-have-tags:
    description: Every operation is tagged.
    severity: info
    given: "$.paths[*][*]"
    then: {field: tags, function: defined}
  operation-ids-camel:
    description: operationId is camelCase.
    severity: warning
    given: "$.paths[*][*].operationId"
    then: {function: casing, functionOptions: {type: camel}}
  parameters-in-known-locations:
    description: Parameters live in path, query or header.
    severity: error
    given: "$.paths[*][*].parameters[*].in"
    then: {function: enumeration, functionOptions: {values: [path, query, header]}}
  schema-names-pascal:
    description: Component schema names are PascalCase.
    severity: warning
    given: $.components.schemas
    then: {field: '@key', function: casing, functionOptions: {type: pascal}}
  responses-not-empty:
    description: Every operation declares at least one response.
    severity: error
    given: "$.paths[*][*].responses"
    then: {function: length, functionOptions: {min: 1}}
  no-internal-hosts:
    description: Server URLs never point at internal hosts.
    severity: error
    given: "$.servers[*].url"
    then: {function: pattern, functionOptions: {notMatch: '(localhost|127\\.0\\.0\\.1)'}}
"""


def test_ten_rule_sample_guide_validates_and_evaluates_on_petstore():
    ruleset = parse_style_guide_yaml(PETSTORE_GUIDE)
    assert len(ruleset.rules) == 10

    spec = yaml.safe_load(PETSTORE.read_text())
    evaluation = evaluate_custom_rules(ruleset, spec)
    assert evaluation.rule_errors == {}
    # The fixture is a compliant spec: every rule passes.
    assert evaluation.findings == ()


def test_ten_rule_sample_guide_flags_a_degraded_petstore():
    spec = yaml.safe_load(PETSTORE.read_text())
    del spec["info"]["description"]
    spec["info"]["version"] = "not-semver"
    spec["servers"].append({"url": "http://localhost:8080"})
    operation = spec["paths"]["/pets/{id}"]["get"]
    del operation["summary"]
    operation["operationId"] = "GetPet"
    operation["parameters"][0]["in"] = "cookie"
    spec["components"]["schemas"]["pet_record"] = {"type": "object"}

    evaluation = evaluate_custom_rules(parse_style_guide_yaml(PETSTORE_GUIDE), spec)
    assert evaluation.rule_errors == {}
    by_rule = {}
    for finding in evaluation.findings:
        by_rule.setdefault(finding.rule, []).append(finding.path)

    assert by_rule["info-has-description"] == ["info"]
    assert by_rule["version-is-semver"] == ["info.version"]
    assert by_rule["servers-use-https"] == ["servers[1].url"]
    assert by_rule["no-internal-hosts"] == ["servers[1].url"]
    assert by_rule["operations-have-summary"] == ["paths./pets/{id}.get"]
    assert by_rule["operation-ids-camel"] == ["paths./pets/{id}.get.operationId"]
    assert by_rule["parameters-in-known-locations"] == ["paths./pets/{id}.get.parameters[0].in"]
    assert by_rule["schema-names-pascal"] == ["components.schemas.pet_record"]
    # Findings are sorted (path, rule, id) — deterministic order.
    keys = [(f.path, f.rule, f.id) for f in evaluation.findings]
    assert keys == sorted(keys)


# --- Sandbox: JSONPath evaluation budget --------------------------------------------------------


def _adversarial_guide() -> str:
    return _one_rule("description: d\ngiven: '$..*..*..*'\nthen: {function: defined}\n")


def test_adversarial_descent_aborts_within_budget():
    deep = {"a": [{"b": [{"c": i} for i in range(60)]} for _ in range(60)]}
    evaluation = _eval_yaml(_adversarial_guide(), deep, node_budget=5_000)
    assert evaluation.findings == ()
    assert "budget" in evaluation.rule_errors["r"]


def test_budget_is_per_rule_so_one_bad_rule_cannot_starve_others():
    deep = {"a": [{"b": [{"c": i} for i in range(60)]} for _ in range(60)], "top": "x"}
    guide = _guide(
        "boom:\n"
        "  description: adversarial\n"
        "  given: '$..*..*..*'\n"
        "  then: {function: defined}\n"
        "fine:\n"
        "  description: requires top\n"
        "  given: $\n"
        "  then: {field: top, function: truthy}\n"
        "missing:\n"
        "  description: flags absent field\n"
        "  given: $\n"
        "  then: {field: nope, function: truthy}\n"
    )
    evaluation = _eval_yaml(guide, deep, node_budget=5_000)
    assert set(evaluation.rule_errors) == {"boom"}
    assert [f.rule for f in evaluation.findings] == ["missing"]


def test_reasonable_rules_fit_the_default_budget_on_a_large_document():
    large = {
        "paths": {
            f"/resource-{i}": {
                "get": {"summary": f"s{i}", "responses": {"200": {"description": "ok"}}}
            }
            for i in range(500)
        }
    }
    guide = _one_rule("description: d\ngiven: '$.paths[*][*]'\nthen: {field: summary, function: truthy}\n")
    evaluation = _eval_yaml(guide, large)
    assert evaluation.rule_errors == {}
    assert evaluation.findings == ()


def _random_document(rng: random.Random, depth: int = 0):
    """A small random JSON document; nesting shrinks with depth."""
    roll = rng.random() + depth * 0.25
    if roll < 0.35:
        return {f"k{i}": _random_document(rng, depth + 1) for i in range(rng.randint(1, 5))}
    if roll < 0.7:
        return [_random_document(rng, depth + 1) for _ in range(rng.randint(1, 5))]
    return rng.choice(["value", 0, 1.5, True, False, None, "x" * rng.randint(0, 30)])


_FUZZ_GIVENS = [
    "$",
    "$.*",
    "$[*]",
    "$..*",
    "$..k0",
    "$[*][*]",
    "$..*[*]",
    "$..*..*",
    "$..*..*..*",
    "$..*..*..*..*",
    "$.k0..k1[*].k2",
    "$..k1[?(@.k2 == 'value')]",
]


def test_fuzz_jsonpath_budget_never_hangs_and_always_terminates():
    """Acceptance: fuzz the evaluation budget — random docs x adversarial paths.

    Every combination must either finish normally or abort with a budget error; with a small
    budget nothing may spend meaningfully past it (the counter aborts mid-traversal).
    """
    rng = random.Random(4429)
    budget = 2_000
    for round_index in range(40):
        document = {"k0": _random_document(rng), "k1": [_random_document(rng) for _ in range(3)]}
        for given in _FUZZ_GIVENS:
            guide = _one_rule(
                f"description: fuzz {round_index}\ngiven: {given!r}\nthen: {{function: defined}}\n"
            )
            evaluation = _eval_yaml(guide, document, node_budget=budget)
            if evaluation.rule_errors:
                assert "budget" in evaluation.rule_errors["r"]
                assert evaluation.findings == ()


def test_fuzz_budget_abort_is_deterministic():
    rng = random.Random(99)
    document = {"k0": [_random_document(rng) for _ in range(20)]}
    guide = _adversarial_guide()
    first = _eval_yaml(guide, document, node_budget=3_000)
    second = _eval_yaml(guide, document, node_budget=3_000)
    assert first == second


# --- Sandbox: regex timeouts --------------------------------------------------------------------


def test_catastrophic_regex_times_out_instead_of_hanging():
    doc = {"info": {"title": "a" * 64 + "b"}}
    guide = _one_rule(
        "description: redos\n"
        "given: $.info.title\n"
        "then: {function: pattern, functionOptions: {match: '(a|aa)+$'}}\n"
    )
    import time

    start = time.monotonic()
    evaluation = _eval_yaml(guide, doc)
    elapsed = time.monotonic() - start
    assert "regex" in evaluation.rule_errors["r"]
    assert evaluation.findings == ()
    assert elapsed < 5.0  # the 0.1s timeout aborted matching (generous CI margin)
