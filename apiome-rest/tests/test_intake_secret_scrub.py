"""Intake secret-scrubbing tests — IXH-1.4 (#5090), completed by MFI-29.6 (#4393).

Pins the three properties the scrubber must have:

* **it redacts** every credential shape intake is likely to receive — by named
  pattern, and (MFI-29.6) by entropy when no pattern can name it;
* **it redacts values only** — the document's structure survives, so a scrubbed
  source still parses and still fingerprints on the same shape;
* **it does not redact what is not a secret** — the entropy heuristic is the half
  that can be wrong, so its false-positive behaviour is pinned as tightly as its
  true-positive behaviour.

Every credential below is realistic in *shape* only; none is functional (the AWS
pair is AWS's own published documentation example).
"""

from __future__ import annotations

import json

import pytest
import yaml

from app.intake_secret_scrub import (
    ENTROPY_MAX_LENGTH,
    ENTROPY_SECRET_TYPE,
    REDACTION_MARKER,
    scrub_document_text,
    scrub_message,
)

# Credential values are assembled from fragments rather than written as literals:
# a realistic-looking token committed verbatim trips secret-scanning push protection
# and leaves a credential-shaped string in the repository forever. None are
# functional; the AWS pair is AWS's own published documentation example.
_AWS_KEY_ID = "AKIA" + "IOSFODNN7" + "EXAMPLE"
_GITHUB_PAT = "ghp" + "_" + "16C7e42F292c6912E7710c838347Ae178B4a"
_SLACK_TOKEN = "xoxb" + "-3096502356789-3097461293841-" + "7Kd0pQmZnRt2VwXyAbCdEfGh"
_GOOGLE_KEY = "AIza" + "SyD-0a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P"
_STRIPE_KEY = "sk" + "_live_" + "4eC39HqLyjWDarjtT1zdp7dcQ8vB2nM1"
_JWT = "eyJhbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxIn0." + "4Xq8kK1nQmVQ0rZ9pL7wT2sYbN3"
_BASIC_PASSWORD = "S3cr3t-Staging-Pass"
_DB_PASSWORD = "Tr0ub4dor&3"
_PLAIN_PASSWORD = "hunter2-not-real"
_CLIENT_SECRET = "Rb8n2QkTvW7yZpL4mXs9CdEf"

#: (label, text containing a secret, the exact secret span, expected type).
SECRET_CASES = [
    ("aws-access-key", f'{{"accessKeyId": "{_AWS_KEY_ID}"}}', _AWS_KEY_ID, "aws-access-key-id"),
    ("github-pat", f"token: {_GITHUB_PAT}", _GITHUB_PAT, "github-token"),
    ("slack-bot-token", f'"value": "{_SLACK_TOKEN}"', _SLACK_TOKEN, "slack-token"),
    ("google-api-key", f"key={_GOOGLE_KEY}", _GOOGLE_KEY, "google-api-key"),
    ("stripe-live-key", f'"secret": "{_STRIPE_KEY}"', _STRIPE_KEY, "stripe-key"),
    ("jwt", f"Authorization: Bearer {_JWT}", _JWT, "jwt"),
    (
        "basic-auth-url",
        f"url: https://svc:{_BASIC_PASSWORD}@staging.example.com/v1",
        _BASIC_PASSWORD,
        "url-embedded-credential",
    ),
    (
        "postgres-connection-string",
        f"dsn: postgresql://report_user:{_DB_PASSWORD}@db.internal:5432/orders",
        _DB_PASSWORD,
        "url-embedded-credential",
    ),
    ("password-assignment", f'password: "{_PLAIN_PASSWORD}"', _PLAIN_PASSWORD, "secret-assignment"),
    (
        "client-secret-assignment",
        f'"client_secret": "{_CLIENT_SECRET}"',
        _CLIENT_SECRET,
        "secret-assignment",
    ),
]


@pytest.mark.parametrize(
    ("label", "text", "secret", "expected_type"),
    SECRET_CASES,
    ids=[case[0] for case in SECRET_CASES],
)
def test_secret_shape_is_redacted(label, text, secret, expected_type):
    outcome = scrub_document_text(text)
    assert outcome.scrubbed, f"{label}: nothing redacted"
    assert secret not in outcome.text, f"{label}: secret survived scrubbing"
    assert REDACTION_MARKER in outcome.text
    assert expected_type in {finding.secret_type for finding in outcome.findings}, (
        f"{label}: reported {[f.secret_type for f in outcome.findings]}, "
        f"expected {expected_type}"
    )


def test_private_key_block_is_redacted():
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n"
        "KUpRKfFLfRYC9AIKjbJTWit+CqvjWYzvQwECAwEAAQ==\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    outcome = scrub_document_text(text)
    assert outcome.scrubbed
    assert "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX" not in outcome.text
    assert "private-key-block" in {finding.secret_type for finding in outcome.findings}
    # The fence survives, so a reader can see *what* was removed.
    assert "BEGIN RSA PRIVATE KEY" in outcome.text


def test_clean_document_is_returned_unchanged():
    text = json.dumps({"openapi": "3.1.0", "info": {"title": "Clean", "version": "1.0.0"}})
    outcome = scrub_document_text(text)
    assert outcome.text == text
    assert not outcome.scrubbed
    assert outcome.findings == []
    assert outcome.redaction_count == 0


def test_findings_never_contain_the_secret_value():
    text = f'api_key: "{_GOOGLE_KEY}"\npassword: "{_DB_PASSWORD}"\n'
    outcome = scrub_document_text(text)
    serialized = json.dumps(outcome.report())
    assert _GOOGLE_KEY not in serialized
    assert _DB_PASSWORD not in serialized
    # It does say what and where.
    assert outcome.report()["redactions"] >= 2
    assert all(finding.line >= 1 for finding in outcome.findings)


def test_report_lists_types_and_lines():
    text = "\n".join(
        [
            "info:",
            f"  token: {_GITHUB_PAT}",
            "  nested:",
            f"    accessKeyId: {_AWS_KEY_ID}",
        ]
    )
    report = scrub_document_text(text).report()
    assert report["scrubbed"] is True
    # The specific provider patterns run first and consume the value, so the generic
    # `secret-assignment` pattern does not double-report the same credential.
    assert set(report["secret_types"]) == {"github-token", "aws-access-key-id"}
    assert {finding["line"] for finding in report["findings"]} == {2, 4}


def test_json_structure_survives_scrubbing():
    document = {
        "openapi": "3.1.0",
        "servers": [{"url": "https://u:P4ssw0rd-Fake@example.com"}],
        "x-keys": {"api_key": _GOOGLE_KEY},
        "components": {"schemas": {"A": {"type": "object"}}},
    }
    text = json.dumps(document, indent=2)
    scrubbed = json.loads(scrub_document_text(text).text)
    assert set(scrubbed) == set(document)
    assert scrubbed["components"] == document["components"]
    assert scrubbed["openapi"] == "3.1.0"
    # The URL keeps its scheme, user, host and path; only the password is gone.
    url = scrubbed["servers"][0]["url"]
    assert url.startswith("https://u:") and url.endswith("@example.com")
    assert "P4ssw0rd-Fake" not in url


def test_yaml_structure_survives_scrubbing():
    text = (
        "openapi: 3.1.0\n"
        "info:\n"
        "  title: T\n"
        "  version: 1.0.0\n"
        "x-auth:\n"
        "  password: S3cr3t-Value-Here\n"
        "paths: {}\n"
    )
    outcome = scrub_document_text(text)
    parsed = yaml.safe_load(outcome.text)
    assert parsed["openapi"] == "3.1.0"
    assert parsed["info"] == {"title": "T", "version": "1.0.0"}
    assert parsed["paths"] == {}
    assert parsed["x-auth"]["password"] == REDACTION_MARKER
    assert "S3cr3t-Value-Here" not in outcome.text


def test_marker_is_not_re_redacted():
    """Scrubbing an already-scrubbed document is a no-op, not a cascade."""
    once = scrub_document_text('password: "Tr0ub4dor-3-fake"')
    twice = scrub_document_text(once.text)
    assert twice.text == once.text
    assert not twice.scrubbed


def test_scrub_message_redacts_quoted_source_spans():
    """A parser error quoting a secret-bearing line is scrubbed before it is kept."""
    message = (
        "Source document is not valid JSON or YAML (creds.yaml): mapping values are not "
        'allowed here\n  in "<unicode string>", line 3, column 12:\n'
        f'        api_key: "{_GOOGLE_KEY}"\n'
    )
    scrubbed = scrub_message(message)
    assert _GOOGLE_KEY not in scrubbed
    # The diagnostic itself survives, so the error stays actionable.
    assert "line 3, column 12" in scrubbed
    assert "mapping values are not allowed here" in scrubbed


def test_scrub_message_passes_through_none_and_clean_text():
    assert scrub_message(None) is None
    assert scrub_message("Parsed 3 operations") == "Parsed 3 operations"


# --- MFI-29.6: entropy detection ------------------------------------------------------

#: Opaque tokens no named pattern recognizes — a bespoke gateway key under a neutral key
#: name is exactly the case entropy detection exists for. Assembled from fragments for the
#: same reason as the values above.
_OPAQUE_TOKENS = [
    ("mixed-alphanumeric", "f4Kd9Lm2Qp7" + "Rt3Vw8Yz1Ab" + "5Cd6Ef0Gh"),
    ("base64url", "ZmFrZS10b2tlbi1" + "mb3ItdGVzdGluZzEy" + "MzQ1Ng=="),
    ("vendor-opaque", "Rb8n2QkTvW7y" + "ZpL4mXs9CdEf" + "GhJkLmNo"),
]

#: Long, mixed, and *not* secrets. Every one of these appears in real API descriptions, and
#: redacting any of them would corrupt a legitimate document.
_NON_SECRETS = [
    ("operation-id", "getUserSubscriptionByAccountId2"),
    ("schema-name", "ListPaymentMethodsRequest_v2Beta1"),
    ("header-name", "X-Amz-Content-Sha256-Unsigned-Payload2"),
    ("urn", "urn.example.schema.OrderLine.v2.2024"),
    ("uuid", "550e8400-e29b-41d4-a716-446655440000"),
    ("sha256-digest", "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"),
    ("iso-timestamp", "2026-07-26T20:22:21.000000+00:00"),
    ("lowercase-slug", "the-quick-brown-fox-jumps-over-the-lazy-dog"),
    ("repeated-character", "A" * 40 + "1a"),
]


@pytest.mark.parametrize(
    ("label", "token"), _OPAQUE_TOKENS, ids=[case[0] for case in _OPAQUE_TOKENS]
)
def test_high_entropy_value_is_redacted(label, token):
    """A credential no pattern can name is caught by its randomness."""
    outcome = scrub_document_text(f'{{"value": "{token}"}}')
    assert outcome.scrubbed, f"{label}: nothing redacted"
    assert token not in outcome.text
    assert ENTROPY_SECRET_TYPE in {finding.secret_type for finding in outcome.findings}


@pytest.mark.parametrize(
    ("label", "value"), _NON_SECRETS, ids=[case[0] for case in _NON_SECRETS]
)
def test_identifier_shaped_value_is_not_redacted(label, value):
    """The heuristic must leave the long non-secrets a real document is full of alone."""
    outcome = scrub_document_text(f'{{"name": "{value}"}}')
    assert not outcome.scrubbed, f"{label}: falsely redacted as a secret"
    assert value in outcome.text


def test_entropy_detection_can_be_disabled():
    """The heuristic is switchable; the named patterns are not."""
    token = "f4Kd9Lm2Qp7" + "Rt3Vw8Yz1Ab" + "5Cd6Ef0Gh"
    text = f'{{"value": "{token}", "password": "{_PLAIN_PASSWORD}"}}'

    off = scrub_document_text(text, entropy_detection=False)
    assert token in off.text, "entropy_detection=False still redacted an unnamed token"
    assert _PLAIN_PASSWORD not in off.text, "a named pattern was skipped"
    assert {finding.secret_type for finding in off.findings} == {"secret-assignment"}

    on = scrub_document_text(text, entropy_detection=True)
    assert token not in on.text


def test_embedded_payload_is_too_long_for_the_entropy_heuristic():
    """A base64 blob is an example, not a credential — redacting it destroys the example."""
    blob = ("QUJDRGVmZ2hpams" + "xMjM0NTY3ODkw") * 8
    assert len(blob) > ENTROPY_MAX_LENGTH
    outcome = scrub_document_text(f'{{"thumbnail": "{blob}"}}')
    assert not outcome.scrubbed
    assert blob in outcome.text


def test_named_pattern_wins_over_entropy_for_the_same_value():
    """A provider-shaped key is reported as that provider, not as an anonymous blob."""
    outcome = scrub_document_text(f'{{"key": "{_GOOGLE_KEY}"}}')
    types = {finding.secret_type for finding in outcome.findings}
    assert types == {"google-api-key"}, f"expected the named type only, got {types}"
    assert outcome.redaction_count == 1


def test_line_numbers_survive_a_multi_line_redaction():
    """A PEM block collapses to one marker; findings after it must still report true lines.

    Detection runs against the original text precisely so this holds — a report that
    mislocates a finding is worse than no location at all.
    """
    text = "\n".join(
        [
            "-----BEGIN RSA PRIVATE KEY-----",  # 1
            "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu",  # 2
            "KUpRKfFLfRYC9AIKjbJTWit+CqvjWYzvQwECAwEAAQ==",  # 3
            "-----END RSA PRIVATE KEY-----",  # 4
            "info:",  # 5
            f'  api_key: "{_GOOGLE_KEY}"',  # 6
        ]
    )
    findings = {finding.secret_type: finding.line for finding in scrub_document_text(text).findings}
    assert findings["private-key-block"] == 1
    assert findings["google-api-key"] == 6, (
        "the line number shifted with the collapsed PEM body"
    )


def test_a_token_dense_document_scrubs_in_reasonable_time():
    """A capture full of credentials must not make detection quadratic.

    HAR and Postman exports — the formats MFI-29.6 exists to protect — routinely carry
    thousands of cookies and tokens. Overlap resolution is neighbour-checked rather than
    scanned, so this stays near-linear; the assertion is a generous ceiling that a
    quadratic implementation blows through rather than a performance benchmark.
    """
    import time

    entries = "\n".join(
        f'  {{"name": "sid{index}", "value": "Bearer sessioncookie{index}abcdefghijklmnop"}},'
        for index in range(4000)
    )
    text = "[\n" + entries + "\n]"

    started = time.monotonic()
    outcome = scrub_document_text(text)
    elapsed = time.monotonic() - started

    assert outcome.redaction_count >= 4000, "the dense fixture did not actually redact"
    assert elapsed < 10.0, f"scrubbing 4000 credentials took {elapsed:.1f}s"


def test_overlapping_patterns_claim_a_span_once():
    """Two patterns matching the same value must not double-report or nest markers."""
    outcome = scrub_document_text(f'Authorization: Bearer {_JWT}')
    assert outcome.redaction_count == 1
    assert outcome.text.count(REDACTION_MARKER) == 1
    assert _JWT not in outcome.text


def test_entropy_redaction_keeps_the_document_parseable():
    """Values only, still — the MFI-29.6 structural contract covers the heuristic too."""
    document = {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "1.0.0"},
        "x-gateway": {"credential": "f4Kd9Lm2Qp7" + "Rt3Vw8Yz1Ab" + "5Cd6Ef0Gh"},
        "paths": {},
    }
    text = json.dumps(document, indent=2)
    outcome = scrub_document_text(text)
    scrubbed = json.loads(outcome.text)
    assert scrubbed["openapi"] == "3.1.0"
    assert scrubbed["info"] == document["info"]
    assert scrubbed["paths"] == {}
    assert scrubbed["x-gateway"]["credential"] == REDACTION_MARKER


@pytest.mark.parametrize(
    "text",
    ['"allowCredentials": true', "allowCredentials: false\n", "credentials: null\n", '{"withCredentials": true}'],
)
def test_an_unquoted_boolean_or_null_under_a_secret_named_key_is_kept(text):
    """CDG-1.3: CORS ``allowCredentials: true`` in an API Gateway export is a boolean, not a secret."""
    outcome = scrub_document_text(text)
    assert outcome.text == text and not outcome.scrubbed


def test_a_quoted_literal_under_a_secret_named_key_is_still_redacted():
    assert scrub_document_text('password: "true"').text == f'password: "{REDACTION_MARKER}"'


@pytest.mark.parametrize(
    "text",
    ['<cors allow-credentials="true">', "<cors allow-credentials='false' />", '<x use-credential = "true"/>'],
)
def test_a_boolean_xml_attribute_under_a_secret_named_name_is_kept(text):
    """CDG-1.4: ``<cors allow-credentials="true">`` in an APIM policy is a boolean, not a secret."""
    outcome = scrub_document_text(text)
    assert outcome.text == text and not outcome.scrubbed


@pytest.mark.parametrize(
    "text",
    ['{"password": "true"}', '<authentication-basic password="hunter22" />', "client_secret='true-ish'"],
)
def test_strings_and_real_attribute_secrets_are_still_redacted(text):
    assert scrub_document_text(text).scrubbed


# --- FMT-10.1: client-export shapes (Hoppscotch / Postman) ---------------------


def test_a_key_named_exactly_token_is_redacted():
    """A Hoppscotch bearer / OAuth 2 auth block keeps its credential under ``token``."""
    text = json.dumps({"authType": "bearer", "token": "plain-bearer-value-123"})
    outcome = scrub_document_text(text)
    assert "plain-bearer-value-123" not in outcome.text
    assert json.loads(outcome.text)["token"] == REDACTION_MARKER


@pytest.mark.parametrize("key", ["tokenUrl", "nextPageToken", "tokenEndpoint"])
def test_a_key_merely_containing_token_is_not_caught_by_the_exact_rule(key):
    text = json.dumps({key: "https://auth.example.com/oauth/token"})
    assert scrub_document_text(text, entropy_detection=False).text == text


@pytest.mark.parametrize("member", ["value", "initialValue", "currentValue"])
def test_a_secret_named_key_value_pair_has_its_value_redacted(member):
    """``{"key": "apiKey", "value": …}`` — the secret's *name* is itself a value."""
    text = json.dumps({"variables": [{"key": "apiKey", "secret": True, member: "pair-value-0042"}]})
    outcome = scrub_document_text(text)
    assert "pair-value-0042" not in outcome.text
    assert json.loads(outcome.text)["variables"][0][member] == REDACTION_MARKER
    assert {finding.secret_type for finding in outcome.findings} == {"secret-key-value-pair"}


def test_both_values_of_an_environment_variable_are_redacted():
    text = json.dumps({"key": "client_secret", "initialValue": "initial-0042", "currentValue": "current-0042"})
    outcome = scrub_document_text(text)
    assert "initial-0042" not in outcome.text and "current-0042" not in outcome.text


def test_a_postman_bearer_parameter_is_redacted():
    bearer = [{"key": "token", "value": "pm-bearer-0042", "type": "string"}]
    text = json.dumps({"auth": {"type": "bearer", "bearer": bearer}})
    assert "pm-bearer-0042" not in scrub_document_text(text).text


def test_a_non_secret_key_value_pair_is_kept():
    text = json.dumps({"variables": [{"key": "baseUrl", "value": "https://api.example.com"}]})
    outcome = scrub_document_text(text)
    assert outcome.text == text and not outcome.scrubbed


# --- FMT-10.2: Thunder Client shapes -------------------------------------------


def test_a_key_named_exactly_bearer_is_redacted():
    """A Thunder Client bearer auth block keeps its credential under ``bearer``."""
    text = json.dumps({"type": "bearer", "bearer": "tc-bearer-value-123"})
    outcome = scrub_document_text(text)
    assert json.loads(outcome.text) == {"type": "bearer", "bearer": REDACTION_MARKER}


def test_an_auth_type_named_bearer_is_kept():
    text = json.dumps({"auth": {"type": "bearer"}})
    assert scrub_document_text(text, entropy_detection=False).text == text


@pytest.mark.parametrize("name", ["apiKey", "client_secret", "Authorization", "Cookie", "X-Api-Key"])
def test_a_secret_named_name_value_pair_has_its_value_redacted(name):
    """``{"name": "apiKey", "value": …}`` — Thunder Client spells the pair's name member ``name``."""
    text = json.dumps({"data": [{"name": name, "value": "pair-value-0042"}]})
    outcome = scrub_document_text(text)
    assert json.loads(outcome.text)["data"][0]["value"] == REDACTION_MARKER


def test_a_non_secret_name_value_pair_is_kept():
    text = json.dumps({"data": [{"name": "baseUrl", "value": "https://api.example.com"}]})
    outcome = scrub_document_text(text)
    assert outcome.text == text and not outcome.scrubbed


# --- MFI-32.2: HAR shapes ------------------------------------------------------


def test_every_cookie_jar_value_is_redacted_whatever_the_cookie_is_called():
    """A HAR ``cookies`` list holds session material under names like ``sid``."""
    document = {
        "request": {"cookies": [{"name": "sid", "value": "jar-value-0001"}, {"name": "theme", "value": "dark"}]},
        "response": {"cookies": [{"name": "connect.sid", "value": "jar-value-0002", "httpOnly": True}]},
    }
    outcome = scrub_document_text(json.dumps(document, indent=2), entropy_detection=False)
    scrubbed = json.loads(outcome.text)
    assert [c["value"] for c in scrubbed["request"]["cookies"]] == [REDACTION_MARKER, REDACTION_MARKER]
    assert scrubbed["response"]["cookies"][0] == {"name": "connect.sid", "value": REDACTION_MARKER, "httpOnly": True}


def test_a_value_outside_a_cookie_jar_is_kept():
    text = json.dumps({"headers": [{"name": "accept", "value": "application/json"}], "cookies": []})
    assert scrub_document_text(text, entropy_detection=False).text == text


def test_a_secret_in_a_json_escaped_body_is_redacted_and_the_string_stays_valid():
    """HAR and Postman keep bodies as JSON *strings*, so their quotes arrive escaped."""
    body = json.dumps({"user": "ada", "password": "escaped-pass-0042", "path": "C:\\dir"})
    text = json.dumps({"postData": {"text": body}})
    outcome = scrub_document_text(text, entropy_detection=False)
    inner = json.loads(json.loads(outcome.text)["postData"]["text"])
    assert inner == {"user": "ada", "password": REDACTION_MARKER, "path": "C:\\dir"}


def test_a_capture_with_thousands_of_cookie_values_scrubs_in_linear_time():
    """Line numbers are counted incrementally; counting from the top per span was quadratic."""
    import time

    entry = {"request": {"cookies": [{"name": "sid", "value": f"jar-{n:05d}"} for n in range(4)]}}
    text = json.dumps({"log": {"entries": [entry] * 10_000}}, indent=2)
    started = time.perf_counter()
    outcome = scrub_document_text(text, entropy_detection=False)
    assert time.perf_counter() - started < 10
    assert sum(finding.occurrences for finding in outcome.findings) == 40_000
    assert outcome.findings[-1].line == text.count("\n", 0, text.rindex("jar-00003")) + 1


def test_many_unterminated_cookie_jars_do_not_rescan_the_tail():
    import time

    text = '"cookies": [ {"value": "x" ' * 50_000
    started = time.perf_counter()
    scrub_document_text(text, entropy_detection=False)
    assert time.perf_counter() - started < 10


# --- MFI-32.3: Insomnia shapes (YAML pairs, YAML jars, secret-typed variables) ---


@pytest.mark.parametrize("name", ["password", "X-API-Key", "client_secret", "Authorization"])
def test_a_secret_named_yaml_pair_has_its_value_redacted(name):
    text = yaml.safe_dump({"params": [{"name": name, "disabled": False, "value": "yaml-pair-0042"}]}, sort_keys=False)
    scrubbed = yaml.safe_load(scrub_document_text(text).text)
    assert scrubbed["params"][0]["value"] == REDACTION_MARKER
    assert scrubbed["params"][0]["disabled"] is False


def test_a_yaml_api_key_auth_block_has_its_value_redacted():
    auth = {"type": "apikey", "key": "X-API-Key", "value": "yaml-key-0042", "addTo": "header"}
    text = yaml.safe_dump({"authentication": auth}, sort_keys=False)
    scrubbed = yaml.safe_load(scrub_document_text(text).text)["authentication"]
    assert scrubbed == {"type": "apikey", "key": "X-API-Key", "value": REDACTION_MARKER, "addTo": "header"}


def test_a_non_secret_yaml_pair_and_the_next_list_item_are_kept():
    text = yaml.safe_dump(
        {"headers": [{"name": "Accept", "value": "application/json"}, {"name": "X-Trace", "value": "trace-0042"}]},
        sort_keys=False,
    )
    assert scrub_document_text(text, entropy_detection=False).text == text


def test_an_unquoted_yaml_token_is_redacted():
    text = "authentication:\n  type: bearer\n  token: yaml-bearer-0042\n  prefix: ''\n"
    scrubbed = yaml.safe_load(scrub_document_text(text).text)["authentication"]
    assert scrubbed == {"type": "bearer", "token": REDACTION_MARKER, "prefix": ""}


def test_every_yaml_cookie_jar_value_is_redacted():
    document = {
        "cookieJar": {
            "name": "Default Jar",
            "cookies": [
                {"key": "sid", "value": "jar-y-0001", "domain": "a.example.com"},
                {"key": "theme", "value": "dark"},
            ],
        },
        "after": {"value": "kept-value"},
    }
    text = yaml.safe_dump(document, sort_keys=False)
    scrubbed = yaml.safe_load(scrub_document_text(text, entropy_detection=False).text)
    assert [c["value"] for c in scrubbed["cookieJar"]["cookies"]] == [REDACTION_MARKER, REDACTION_MARKER]
    assert scrubbed["after"]["value"] == "kept-value"


@pytest.mark.parametrize("dump", ["json", "yaml"])
def test_a_secret_typed_variable_is_redacted_whatever_it_is_called(dump):
    pairs = [
        {"id": "1", "name": "stripe", "value": "typed-secret-0042", "type": "secret", "enabled": True},
        {"id": "2", "type": "secret", "name": "vault", "value": "typed-secret-0043"},
        {"id": "3", "name": "region", "value": "us-east", "type": "str"},
    ]
    if dump == "json":
        text = json.dumps({"kvPairData": pairs})
        scrubbed = json.loads(scrub_document_text(text, entropy_detection=False).text)
    else:
        text = yaml.safe_dump({"kvPairData": pairs}, sort_keys=False)
        scrubbed = yaml.safe_load(scrub_document_text(text, entropy_detection=False).text)
    values = [pair["value"] for pair in scrubbed["kvPairData"]]
    assert values[0] == REDACTION_MARKER
    assert values[2] == "us-east"
    if dump == "json":
        assert values[1] == REDACTION_MARKER
