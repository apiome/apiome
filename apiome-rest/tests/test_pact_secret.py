"""Workspace secrets, the pure half — PFX-6.5 (#6957).

:mod:`app.pact_secret` (names, references, bodies) and what :mod:`app.pact_webhook` does with a
``${user.<name>}`` reference: where it may be written, how it is rendered in one pass, and that its
value is scrubbed from every log.
"""

from __future__ import annotations

import json
from urllib.parse import quote_plus

import pytest

from app.pact_publication import PactPublicationError
from app.pact_secret import (
    CODE_SECRET_INVALID,
    PactSecretError,
    is_reference,
    malformed_references,
    parse_secret_create,
    parse_secret_update,
    references_in,
    secret_reference,
    validate_secret_name,
)
from app.pact_webhook import (
    CODE_WEBHOOK_INVALID,
    parse_webhook_request,
    reference_locations,
    render_request,
    resolve_signing_secret,
    scrub,
    template_parameters,
)

_VALUE = "s3cr3t-value-0123456789"


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """example.com hosts do not have to resolve for a webhook to be read."""
    monkeypatch.setattr("app.pact_webhook.validate_host", lambda _host: None)


def _webhook(**request: object) -> bytes:
    body = {"request": {"method": "POST", "url": "https://ci.example.com/hook", **request}}
    return json.dumps(body).encode()


# --- names and references ------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["ciToken", "A", "github_token_2", "x" * 64])
def test_a_well_formed_name_is_kept(name: str) -> None:
    assert validate_secret_name(name) == name


@pytest.mark.parametrize("name", ["", "1token", "_token", "ci-token", "ci token", "x" * 65, None, 7])
def test_a_malformed_name_is_refused_with_a_pointer(name: object) -> None:
    with pytest.raises(PactSecretError) as caught:
        validate_secret_name(name)
    assert caught.value.code == CODE_SECRET_INVALID and caught.value.pointer == "/name"


def test_a_reference_is_written_the_pactflow_way() -> None:
    assert secret_reference("ciToken") == "${user.ciToken}"
    assert is_reference("${user.ciToken}")
    assert not is_reference("Bearer ${user.ciToken}") and not is_reference("${user.ci-token}")
    assert not is_reference(None) and not is_reference("")


def test_references_are_found_in_strings_and_json_once_in_order() -> None:
    body = {"${user.keyName}": ["${user.b}", {"x": "${user.a} ${user.b}"}], "n": 3}
    assert references_in("${user.a}/${pactbroker.pactUrl}", body, None) == ["a", "keyName", "b"]


def test_a_malformed_reference_is_reported_as_written() -> None:
    assert malformed_references({"h": "${user.ok} ${user.bad-name}", "x": ["${user.open"]}) == [
        "${user.bad-name}",
        "${user.open",
    ]
    assert malformed_references("${pactbroker.pactUrl} ${user.fine}") == []


# --- bodies --------------------------------------------------------------------------------------


def test_a_create_body_is_read() -> None:
    secret = parse_secret_create(json.dumps({"name": "ciToken", "description": "  CI  ", "value": _VALUE}).encode())
    assert (secret.name, secret.description, secret.value) == ("ciToken", "CI", _VALUE)
    assert _VALUE not in repr(secret)


@pytest.mark.parametrize(
    ("body", "pointer"),
    [
        ({"name": "ciToken"}, "/value"),
        ({"name": "ciToken", "value": ""}, "/value"),
        ({"name": "ciToken", "value": 42}, "/value"),
        ({"name": "ciToken", "value": "line\nbreak" + _VALUE}, "/value"),
        ({"name": "ciToken", "value": "x" * 4097}, "/value"),
        ({"name": "ciToken", "value": "${user.other}"}, "/value"),
        ({"name": "ci-token", "value": _VALUE}, "/name"),
        ({"name": "ciToken", "value": _VALUE, "secret": _VALUE}, "/secret"),
        ({"name": "ciToken", "value": _VALUE, "description": "a\nb"}, "/description"),
        ({"name": "ciToken", "value": _VALUE, "description": "d" * 1001}, "/description"),
    ],
)
def test_a_bad_create_body_is_refused_without_repeating_the_value(body: dict, pointer: str) -> None:
    with pytest.raises(PactSecretError) as caught:
        parse_secret_create(json.dumps(body).encode())
    assert caught.value.code == CODE_SECRET_INVALID and caught.value.pointer == pointer
    assert _VALUE not in str(caught.value)


@pytest.mark.parametrize("raw", [b"", b"not json", b"[1]", b"\xff"])
def test_a_body_that_is_not_an_object_is_refused(raw: bytes) -> None:
    with pytest.raises(PactSecretError) as caught:
        parse_secret_create(raw)
    assert caught.value.pointer == ""


def test_an_update_body_keeps_the_value_unless_one_is_sent() -> None:
    kept = parse_secret_update(b'{"description": "CI"}')
    assert kept.value is None and kept.description == "CI" and kept.name is None
    rotated = parse_secret_update(json.dumps({"name": "ciToken", "value": _VALUE}).encode())
    assert rotated.value == _VALUE and rotated.name == "ciToken" and rotated.description is None
    with pytest.raises(PactSecretError):
        parse_secret_update(b'{"value": ""}')


# --- webhook templates ---------------------------------------------------------------------------


def test_a_webhook_may_refer_to_secrets_everywhere_but_the_host() -> None:
    webhook = parse_webhook_request(
        json.dumps(
            {
                "request": {
                    "method": "POST",
                    "url": "https://ci.example.com/hook/${user.pathKey}?k=${user.queryKey}",
                    "headers": {"X-Api-Key": "${user.ciToken}", "X-Team": "${user.team}"},
                    "body": {"key": "${user.bodyKey}"},
                    "username": "${user.user}",
                    "password": "${user.password}",
                },
                "signingSecret": "${user.signing}",
            }
        ).encode()
    )
    assert webhook.signing_secret == "${user.signing}"  # short as written; checked when resolved
    secrets = {
        "password": webhook.password,
        "signingSecret": webhook.signing_secret,
        "headers": webhook.secret_headers,
    }
    located = reference_locations(
        url=webhook.url, headers=webhook.headers, body=webhook.body, username=webhook.username, secrets=secrets
    )
    assert located == [
        ("pathKey", "/request/url"),
        ("queryKey", "/request/url"),
        ("team", "/request/headers/X-Team"),
        ("bodyKey", "/request/body"),
        ("user", "/request/username"),
        ("password", "/request/password"),
        ("ciToken", "/request/headers/X-Api-Key"),
        ("signing", "/signingSecret"),
    ]


def test_a_github_token_may_be_a_reference() -> None:
    webhook = parse_webhook_request(
        json.dumps(
            {"target": {"type": "github_repository_dispatch", "repository": "acme/ledger", "token": "${user.gh}"}}
        ).encode()
    )
    assert webhook.secret_headers == {"Authorization": "Bearer ${user.gh}"}
    located = reference_locations(
        url=webhook.url,
        headers=webhook.headers,
        body=webhook.body,
        username=None,
        secrets={"headers": webhook.secret_headers},
        github=True,
    )
    assert located == [("gh", "/target/token")]


@pytest.mark.parametrize(
    "url", ["https://${user.host}/hook", "https://ci.${user.zone}.example.com/hook", "https://${user.h}.example.com"]
)
def test_a_reference_cannot_choose_the_host(url: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        parse_webhook_request(_webhook(url=url))
    assert caught.value.code == CODE_WEBHOOK_INVALID and caught.value.pointer == "/request/url"


def test_a_reference_cannot_be_the_github_api_root() -> None:
    body = {
        "target": {
            "type": "github_repository_dispatch",
            "repository": "acme/ledger",
            "token": "t0ken",
            "apiUrl": "https://${user.ghe}/api/v3",
        }
    }
    with pytest.raises(PactPublicationError) as caught:
        parse_webhook_request(json.dumps(body).encode())
    assert caught.value.pointer == "/target/apiUrl"


@pytest.mark.parametrize(
    ("fields", "pointer"),
    [
        ({"headers": {"Authorization": "Bearer ${user.ci-token}"}}, "/request"),
        ({"body": {"k": "${user.unclosed"}}, "/request"),
        ({"url": "https://ci.example.com/hook?k=${user.}"}, "/request"),
    ],
)
def test_a_malformed_reference_is_refused_rather_than_sent_as_written(fields: dict, pointer: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        parse_webhook_request(_webhook(**fields))
    assert caught.value.code == CODE_WEBHOOK_INVALID and caught.value.pointer == pointer
    assert "is not a secret reference" in str(caught.value)


def test_a_malformed_signing_secret_reference_is_refused() -> None:
    body = json.loads(_webhook())
    body["signingSecret"] = "${user.bad-name}"
    with pytest.raises(PactPublicationError) as caught:
        parse_webhook_request(json.dumps(body).encode())
    assert caught.value.pointer == "/signingSecret"


# --- rendering -----------------------------------------------------------------------------------


def test_references_are_substituted_and_every_form_of_the_value_is_scrubbed() -> None:
    value = 'tok&"en/1234567'
    rendered = render_request(
        method="POST",
        url="https://ci.example.com/hook?key=${user.k}&p=${pactbroker.providerName}",
        headers={"X-Key": "${user.k}"},
        body={"key": "${user.k}", "pact": "${pactbroker.pactUrl}"},
        parameters=template_parameters(event_name="test", provider_name="Ledger API", pact_url="https://p"),
        secret_headers={"Authorization": "Bearer ${user.k}"},
        secret_values={"k": value},
    )
    assert rendered.url == f"https://ci.example.com/hook?key={quote_plus(value)}&p=Ledger+API"
    assert rendered.headers["X-Key"] == value and rendered.headers["Authorization"] == f"Bearer {value}"
    assert json.loads(rendered.body) == {"key": value, "pact": "https://p"}
    shown = scrub(f"{rendered.url} {rendered.body.decode()} {rendered.headers}", rendered.secrets)
    assert value not in shown and quote_plus(value) not in shown and 'tok&\\"en' not in shown


def test_a_parameter_value_cannot_smuggle_in_a_reference() -> None:
    rendered = render_request(
        method="POST",
        url="https://ci.example.com/hook",
        headers={"X-Consumer": "${pactbroker.consumerName}"},
        body="${pactbroker.consumerName}",
        parameters=template_parameters(event_name="test", consumer_name="${user.k}"),
        secret_values={"k": _VALUE},
    )
    assert rendered.headers["X-Consumer"] == "${user.k}" and rendered.body == b"${user.k}"


def test_a_signing_secret_reference_resolves_and_must_be_long_enough() -> None:
    assert resolve_signing_secret(None, {}) is None
    assert resolve_signing_secret("literal-signing-secret", {}) == "literal-signing-secret"
    assert resolve_signing_secret("${user.s}", {"s": _VALUE}) == _VALUE
    with pytest.raises(ValueError) as caught:
        resolve_signing_secret("${user.s}", {"s": "short"})
    assert "${user.s}" in str(caught.value) and "short" not in str(caught.value)
    with pytest.raises(ValueError):
        resolve_signing_secret("${user.s}", {})
