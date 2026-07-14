"""Static source/config inspection and secret redaction (CLX-3.2, #4856).

The load-bearing property: a detected secret never leaves this module in the clear. Every finding
that reports a credential reports a *redacted* form of it — the mask, not the material. A scanner
that widened the exposure it was built to detect would be worse than none.
"""

from __future__ import annotations

from app.mcp_static_checks import (
    RULE_PRIVILEGED_CONTAINER,
    RULE_SECRET_PROVIDER,
    RULE_UNSAFE_COMMAND,
    documents_from_mapping,
    redact,
    rule_ids,
    scan_documents,
    shannon_entropy,
)

_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"


def _scan(files):
    return scan_documents(documents_from_mapping(files))


def test_provider_secret_detected_and_redacted():
    result = _scan({".env": f"AWS_ACCESS_KEY_ID={_AWS_KEY}\n"})
    finding = next(f for f in result.findings if f.rule == RULE_SECRET_PROVIDER)
    # The raw key appears in NEITHER the message NOR the excerpt.
    assert _AWS_KEY not in finding.message
    assert _AWS_KEY not in finding.excerpt
    assert "AKIA" in finding.message  # a short, non-reversible prefix is fine
    assert finding.line == 1


def test_private_key_body_never_captured():
    result = _scan({"id_rsa": "-----BEGIN RSA PRIVATE KEY-----\nMIIsecret\n-----END-----\n"})
    finding = next(f for f in result.findings if f.rule.endswith("committed-private-key"))
    assert "MIIsecret" not in finding.excerpt
    assert "key body not captured" in finding.excerpt


def test_placeholder_not_flagged_as_secret():
    result = _scan({"config.py": 'api_key = "YOUR_API_KEY_HERE"\n'})
    assert not any("secret" in f.rule for f in result.findings)


def test_env_interpolation_not_flagged():
    # ${FOO} is a reference to a secret, not a secret. Flagging it trains people to ignore the rule.
    result = _scan({".env": "PASSWORD=${DB_PASSWORD}\n"})
    assert not any("secret" in f.rule for f in result.findings)


def test_unsafe_command_and_privileged_container():
    result = _scan(
        {
            "entrypoint.sh": "os.system(user_input)\n",
            "docker-compose.yml": "services:\n  x:\n    privileged: true\n",
        }
    )
    rules = {f.rule for f in result.findings}
    assert RULE_UNSAFE_COMMAND in rules
    assert RULE_PRIVILEGED_CONTAINER in rules


def test_findings_carry_location_and_owasp():
    result = _scan({"Dockerfile": "FROM node:20\nRUN curl https://x/i.sh | sh\n"})
    remote = next(f for f in result.findings if f.rule.endswith("remote-script-execution"))
    assert remote.line == 2
    assert remote.owasp_ids  # mapped to at least one OWASP risk


def test_commented_line_not_flagged():
    result = _scan({"config.py": "# os.system(danger)\n"})
    assert not result.findings


def test_config_pattern_rules_skip_docs_but_secrets_are_caught_everywhere():
    # A committed credential is a leak wherever it lives — even a README.
    leaked = _scan({"README.md": f"example key: {_AWS_KEY}\n"})
    assert any(f.rule == RULE_SECRET_PROVIDER for f in leaked.findings)

    # But the config/code pattern rules do not run over a doc file: an `os.system(` inside a
    # markdown code block is documentation, not a deployed sink.
    doc_only = _scan({"README.md": "```\nos.system(danger)\n```\n"})
    assert not any(f.rule == RULE_UNSAFE_COMMAND for f in doc_only.findings)


def test_scan_is_deterministic():
    files = {"Dockerfile": "FROM x\nRUN eval(y)\n", ".env": f"K={_AWS_KEY}\n"}
    a = _scan(files)
    b = _scan(files)
    assert [f.as_dict() for f in a.findings] == [f.as_dict() for f in b.findings]


def test_redact_short_value_masked_entirely():
    assert redact("abcd") == "[redacted, 4 chars]"
    assert "…[redacted" in redact("A" * 40)


def test_entropy_separates_placeholder_from_key():
    assert shannon_entropy("aaaaaaaa") < shannon_entropy(_AWS_KEY)


def test_rule_ids_are_stable_and_nonempty():
    ids = rule_ids()
    assert ids == tuple(sorted(ids))
    assert RULE_SECRET_PROVIDER in ids
