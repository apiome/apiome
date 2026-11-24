"""The contract-webhook contract — PFX-1.9 (#6922).

The pure half (:mod:`app.pact_webhook`): reading a webhook body, the ``${pactbroker.*}`` template
parameters, rendering a request, and keeping secrets out of what is shown or logged.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict

import pytest

from app.pact_publication import PactPublicationError
from app.pact_webhook import (
    CODE_WEBHOOK_INVALID,
    CODE_WEBHOOK_NOT_FOUND,
    DEFAULT_EVENT,
    EVENT_NAMES,
    REDACTED,
    TARGET_GITHUB,
    TEMPLATE_PARAMETERS,
    WebhookRecord,
    is_secret_header,
    parse_webhook_request,
    render_request,
    render_text,
    request_description,
    scope_description,
    scrub,
    template_parameters,
    validate_webhook_uuid,
)

_URL = "https://ci.example.com/hooks/verify"


def _body(**overrides: Any) -> bytes:
    body: Dict[str, Any] = {"request": {"method": "POST", "url": _URL}}
    body.update(overrides)
    return json.dumps(body).encode()


def _headers_body(headers: Dict[str, str]) -> bytes:
    return _body(request={"method": "POST", "url": _URL, "headers": headers})


def _parse(**overrides: Any):
    return parse_webhook_request(_body(**overrides), resolve=False)


def _refusal(raw: bytes, **kwargs: Any) -> PactPublicationError:
    with pytest.raises(PactPublicationError) as caught:
        parse_webhook_request(raw, resolve=False, **kwargs)
    assert caught.value.code == CODE_WEBHOOK_INVALID
    return caught.value


# --- Reading a body ------------------------------------------------------------------------------


def test_the_smallest_webhook_gets_the_brokers_defaults() -> None:
    webhook = _parse()
    assert webhook.method == "POST" and webhook.url == _URL
    assert webhook.events == [DEFAULT_EVENT] and webhook.enabled is True
    assert webhook.consumer_name is None and webhook.provider_name is None
    assert not webhook.has_secrets()


def test_what_the_cli_sends_is_read() -> None:
    webhook = _parse(
        description="Verify the provider",
        consumer={"name": "Billing Service"},
        provider={"name": "Ledger API"},
        enabled=False,
        events=[{"name": n} for n in ("contract_published", "contract_published", "provider_verification_failed")],
        teamUuid="ignored",
        request={
            "method": "put",
            "url": _URL + "?c=${pactbroker.consumerName}",
            "headers": {"Content-Type": "application/json", "X-Api-Key": "k-123456"},
            "body": {"pact": "${pactbroker.pactUrl}"},
            "username": "ci",
            "password": "hunter2-hunter2",
        },
    )
    assert webhook.description == "Verify the provider"
    assert (webhook.consumer_name, webhook.provider_name) == ("Billing Service", "Ledger API")
    assert webhook.enabled is False and webhook.method == "PUT"
    assert webhook.events == ["contract_published", "provider_verification_failed"]
    # Secret headers are kept apart from the ones stored in the clear.
    assert webhook.headers == {"Content-Type": "application/json"}
    assert webhook.secret_headers == {"X-Api-Key": "k-123456"}
    assert webhook.username == "ci" and webhook.password == "hunter2-hunter2"
    assert webhook.has_secrets()


@pytest.mark.parametrize("event", EVENT_NAMES)
def test_every_event_is_accepted(event: str) -> None:
    assert _parse(events=[{"name": event}]).events == [event]


@pytest.mark.parametrize(
    ("raw", "pointer"),
    [
        (b"not json", ""),
        (b"[]", ""),
        (b"{}", "/request"),
        (_body(request={"method": "GET", "url": _URL}), "/request/method"),
        (_body(request={"method": "POST"}), "/request/url"),
        (_body(request={"method": "POST", "url": "ftp://example.com/x"}), "/request/url"),
        (_body(request={"method": "POST", "url": "https://user:pw@example.com/x"}), "/request/url"),
        (_body(request={"method": "POST", "url": "https://${pactbroker.providerName}.example.com/x"}), "/request/url"),
        (_body(request={"method": "POST", "url": "https://example.com/a b"}), "/request/url"),
        (_body(request={"method": "POST", "url": _URL, "headers": ["a"]}), "/request/headers"),
        (_body(request={"method": "POST", "url": _URL, "headers": {"Bad Name": "x"}}), "/request/headers/Bad Name"),
        (_body(request={"method": "POST", "url": _URL, "headers": {"Host": "x"}}), "/request/headers/Host"),
        (_headers_body({"X-Apiome-Event": "x"}), "/request/headers/X-Apiome-Event"),
        (_headers_body({"x-apiome-signature": "x"}), "/request/headers/x-apiome-signature"),
        (_body(request={"method": "POST", "url": _URL, "headers": {"X-A": "a\r\nX-B: b"}}), "/request/headers/X-A"),
        (_body(request={"method": "POST", "url": _URL, "password": "pw"}), "/request/username"),
        (_body(events=[]), "/events"),
        (_body(events=[{"name": "pact_deleted"}]), "/events/0/name"),
        (_body(enabled="yes"), "/enabled"),
        (_body(consumer={"label": "mobile"}), "/consumer/label"),
        (_body(provider={}), "/provider/name"),
        (_body(signingSecret="too-short"), "/signingSecret"),
        (_body(target={"type": TARGET_GITHUB, "repository": "acme/api", "token": "t"}), "/target"),
    ],
)
def test_a_malformed_body_is_refused_with_a_pointer(raw: bytes, pointer: str) -> None:
    assert _refusal(raw).pointer == pointer


def test_a_username_and_an_authorization_header_do_not_mix() -> None:
    error = _refusal(
        _body(request={"method": "POST", "url": _URL, "username": "ci", "headers": {"Authorization": "Bearer abc"}})
    )
    assert error.pointer == "/request/headers/Authorization"


def test_a_refusal_never_repeats_a_secret() -> None:
    secret = "s3cr3t\nvalue"
    error = _refusal(_body(request={"method": "POST", "url": _URL, "username": "ci", "password": secret}))
    assert error.pointer == "/request/password" and "s3cr3t" not in str(error)


def test_the_host_is_resolved_against_the_ssrf_policy() -> None:
    for url in ("http://127.0.0.1/hook", "http://169.254.169.254/latest/meta-data", "http://[::1]/hook"):
        with pytest.raises(PactPublicationError) as caught:
            parse_webhook_request(_body(request={"method": "POST", "url": url}))
        assert caught.value.code == CODE_WEBHOOK_INVALID and caught.value.pointer == "/request/url"
        assert "public address" in str(caught.value)


def test_redacted_secrets_are_carried_through_to_keep_the_stored_ones() -> None:
    webhook = _parse(
        request={
            "method": "POST",
            "url": _URL,
            "username": "ci",
            "password": REDACTED,
            "headers": {"X-Token": REDACTED},
        },
        signingSecret=REDACTED,
    )
    assert webhook.password == REDACTED and webhook.signing_secret == REDACTED
    assert webhook.secret_headers == {"X-Token": REDACTED}


# --- GitHub Actions repository_dispatch ----------------------------------------------------------


def test_a_github_target_becomes_a_repository_dispatch_request() -> None:
    webhook = _parse(
        request=None,
        target={"type": TARGET_GITHUB, "repository": "acme/ledger-api", "token": "ghp_0123456789"},
    )
    assert webhook.target_kind == TARGET_GITHUB
    assert webhook.method == "POST" and webhook.url == "https://api.github.com/repos/acme/ledger-api/dispatches"
    assert webhook.headers == {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    assert webhook.secret_headers == {"Authorization": "Bearer ghp_0123456789"}
    assert webhook.body["event_type"] == "${pactbroker.eventName}"
    # GitHub accepts at most ten properties in client_payload.
    assert len(webhook.body["client_payload"]) == 10
    assert webhook.body["client_payload"]["pactUrl"] == "${pactbroker.pactUrl}"
    # What is stored about the target names no token.
    assert webhook.target_config == {"repository": "acme/ledger-api", "eventType": "${pactbroker.eventName}"}


def test_a_github_target_takes_its_own_event_type_payload_and_api_root() -> None:
    webhook = _parse(
        request=None,
        target={
            "type": TARGET_GITHUB,
            "repository": "acme/ledger-api",
            "eventType": "pact_changed",
            "clientPayload": {"pact": "${pactbroker.pactUrl}"},
            "apiUrl": "https://github.example.com/api/v3/",
            "token": REDACTED,
        },
    )
    assert webhook.url == "https://github.example.com/api/v3/repos/acme/ledger-api/dispatches"
    assert webhook.body == {"event_type": "pact_changed", "client_payload": {"pact": "${pactbroker.pactUrl}"}}
    assert webhook.secret_headers == {"Authorization": REDACTED}
    assert webhook.target_config["apiUrl"] == "https://github.example.com/api/v3"


@pytest.mark.parametrize(
    ("target", "pointer"),
    [
        ({"type": "slack"}, "/target/type"),
        ({"type": TARGET_GITHUB, "token": "t"}, "/target/repository"),
        ({"type": TARGET_GITHUB, "repository": "not a repo", "token": "t"}, "/target/repository"),
        ({"type": TARGET_GITHUB, "repository": "acme/api"}, "/target/token"),
        ({"type": TARGET_GITHUB, "repository": "acme/api", "token": "t", "ref": "main"}, "/target/ref"),
        (
            {"type": TARGET_GITHUB, "repository": "acme/api", "token": "t", "clientPayload": dict.fromkeys(range(11))},
            "/target/clientPayload",
        ),
    ],
)
def test_a_malformed_github_target_is_refused(target: Dict[str, Any], pointer: str) -> None:
    assert _refusal(json.dumps({"target": target}).encode()).pointer == pointer


# --- Template parameters ---------------------------------------------------------------------------


def _parameters(**overrides: Any) -> Dict[str, str]:
    values: Dict[str, Any] = {
        "event_name": "contract_requiring_verification_published",
        "consumer_name": "Billing Service",
        "provider_name": "Ledger API",
        "consumer_version_number": "1.0.0",
        "consumer_version_tags": ["dev", "feat-x"],
        "consumer_version_branch": "feat/x",
        "pact_url": "https://broker.example.com/pacts/1",
        "provider_version_number": "4f1e2d0",
        "provider_version_tags": ["main", "prod"],
        "provider_version_branch": "main",
        "provider_version_descriptions": ["latest from main branch", "deployed in production"],
        "verification_result_url": "https://broker.example.com/results/3",
        "verification_success": True,
        "build_url": "https://ci.example.com/builds/9",
        "consumer_labels": ["mobile"],
        "provider_labels": ["core", "billing"],
        "currently_deployed_provider_version_number": "4f1e2d0",
    }
    values.update(overrides)
    return template_parameters(**values)


def test_every_template_parameter_has_a_value() -> None:
    parameters = _parameters()
    assert set(parameters) == set(TEMPLATE_PARAMETERS)
    assert parameters == {
        "pactbroker.consumerName": "Billing Service",
        "pactbroker.providerName": "Ledger API",
        "pactbroker.consumerVersionNumber": "1.0.0",
        "pactbroker.providerVersionNumber": "4f1e2d0",
        "pactbroker.providerVersionTags": "main, prod",
        "pactbroker.providerVersionDescriptions": "latest from main branch, deployed in production",
        "pactbroker.providerVersionBranch": "main",
        "pactbroker.consumerVersionTags": "dev, feat-x",
        "pactbroker.consumerVersionBranch": "feat/x",
        "pactbroker.pactUrl": "https://broker.example.com/pacts/1",
        "pactbroker.verificationResultUrl": "https://broker.example.com/results/3",
        "pactbroker.githubVerificationStatus": "success",
        "pactbroker.bitbucketVerificationStatus": "SUCCESSFUL",
        "pactbroker.azureDevOpsVerificationStatus": "succeeded",
        "pactbroker.gitlabVerificationStatus": "success",
        "pactbroker.consumerLabels": "mobile",
        "pactbroker.providerLabels": "core, billing",
        "pactbroker.eventName": "contract_requiring_verification_published",
        "pactbroker.buildUrl": "https://ci.example.com/builds/9",
        "pactbroker.currentlyDeployedProviderVersionNumber": "4f1e2d0",
    }


@pytest.mark.parametrize(
    ("success", "github", "bitbucket", "azure", "gitlab"),
    [
        (True, "success", "SUCCESSFUL", "succeeded", "success"),
        (False, "failure", "FAILED", "failed", "failed"),
        (None, "pending", "INPROGRESS", "pending", "pending"),
    ],
)
def test_the_ci_status_parameters_follow_the_verification(
    success: Any, github: str, bitbucket: str, azure: str, gitlab: str
) -> None:
    parameters = _parameters(verification_success=success)
    assert parameters["pactbroker.githubVerificationStatus"] == github
    assert parameters["pactbroker.bitbucketVerificationStatus"] == bitbucket
    assert parameters["pactbroker.azureDevOpsVerificationStatus"] == azure
    assert parameters["pactbroker.gitlabVerificationStatus"] == gitlab


def test_an_unknown_value_is_the_empty_string() -> None:
    parameters = template_parameters(event_name="contract_published")
    assert parameters["pactbroker.eventName"] == "contract_published"
    assert all(value == "" for name, value in parameters.items() if "Status" not in name and "eventName" not in name)


@pytest.mark.parametrize("name", TEMPLATE_PARAMETERS)
def test_every_parameter_is_substituted_wherever_it_appears(name: str) -> None:
    parameters = _parameters()
    token = "${" + name + "}"
    rendered = render_request(
        method="POST",
        url=f"{_URL}?v={token}",
        headers={"X-Value": token},
        body={"value": token, "nested": [{"again": f"<{token}>"}]},
        parameters=parameters,
        username=token,
        password="pw-" + token,
        secret_headers={"X-Token": "T " + token},
    )
    value = parameters[name]
    body = json.loads(rendered.body)
    assert body == {"value": value, "nested": [{"again": f"<{value}>"}]}
    assert rendered.headers["X-Value"] == value
    assert rendered.headers["X-Token"] == ("T " + value).strip()
    assert "${" not in rendered.url
    assert base64.b64decode(rendered.headers["Authorization"].split()[1]).decode() == f"{value}:pw-{value}"


# --- Rendering -----------------------------------------------------------------------------------


def test_url_values_are_encoded_and_a_json_body_stays_json() -> None:
    parameters = _parameters(consumer_name='Billing "A&B" / Service')
    rendered = render_request(
        method="post",
        url=_URL + "?consumer=${pactbroker.consumerName}",
        headers={},
        body={"consumer": "${pactbroker.consumerName}"},
        parameters=parameters,
    )
    assert rendered.method == "POST"
    assert rendered.url == _URL + "?consumer=Billing+%22A%26B%22+%2F+Service"
    # A quote in a value cannot break the document.
    assert json.loads(rendered.body) == {"consumer": 'Billing "A&B" / Service'}
    assert rendered.headers["Content-Type"].startswith("application/json")


def test_a_text_body_is_substituted_as_text_and_keeps_its_content_type() -> None:
    rendered = render_request(
        method="POST",
        url=_URL,
        headers={"content-type": "text/plain"},
        body="pact ${pactbroker.pactUrl} changed",
        parameters=_parameters(),
    )
    assert rendered.body == b"pact https://broker.example.com/pacts/1 changed"
    assert rendered.headers == {"content-type": "text/plain"}


def test_no_body_sends_none_and_an_unknown_parameter_is_left_as_written() -> None:
    rendered = render_request(
        method="POST", url=_URL + "?x=${pactbroker.noSuchThing}", headers={}, body=None, parameters=_parameters()
    )
    assert rendered.body is None and "Content-Type" not in rendered.headers
    assert rendered.url.endswith("?x=${pactbroker.noSuchThing}")
    assert render_text(None, {}) is None


def test_a_parameter_cannot_add_a_header() -> None:
    rendered = render_request(
        method="POST",
        url=_URL,
        headers={"X-Consumer": "${pactbroker.consumerName}"},
        body=None,
        parameters=_parameters(consumer_name="web\r\nX-Injected: yes"),
    )
    assert rendered.headers == {"X-Consumer": "web  X-Injected: yes"}


def test_the_rendered_request_names_its_secrets() -> None:
    rendered = render_request(
        method="POST",
        url=_URL,
        headers={"X-Plain": "visible"},
        body=None,
        parameters=_parameters(),
        username="ci",
        password="hunter2-hunter2",
        secret_headers={"X-Api-Key": "Bearer k-1234567890"},
    )
    basic = base64.b64encode(b"ci:hunter2-hunter2").decode()
    assert rendered.headers["Authorization"] == f"Basic {basic}"
    assert {"hunter2-hunter2", basic, "Bearer k-1234567890", "k-1234567890"} <= set(rendered.secrets)
    assert "visible" not in rendered.secrets


# --- Redaction -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["Authorization", "authorization", "X-Api-Key", "X-Auth-Token", "Cookie", "X-Hub-Secret", "Proxy-Authorization"],
)
def test_credential_headers_are_secret(name: str) -> None:
    assert is_secret_header(name)


@pytest.mark.parametrize("name", ["Content-Type", "Accept", "X-GitHub-Api-Version", "User-Agent"])
def test_ordinary_headers_are_not(name: str) -> None:
    assert not is_secret_header(name)


def test_scrub_removes_every_secret_value() -> None:
    text = "sent Bearer abc123456 and got back {'echo': 'abc123456'}"
    assert scrub(text, ["Bearer abc123456", "abc123456"]) == f"sent {REDACTED} and got back {{'echo': '{REDACTED}'}}"
    assert scrub(None, ["x"]) is None and scrub("nothing here", []) == "nothing here"


def test_a_record_shows_secret_headers_redacted() -> None:
    record = WebhookRecord(
        id="1", headers={"Accept": "application/json"}, secret_fields=["password", "header:Authorization"]
    )
    assert record.secret_header_names() == ["Authorization"]
    assert record.shown_headers() == {"Accept": "application/json", "Authorization": REDACTED}


# --- Descriptions --------------------------------------------------------------------------------


def test_descriptions_read_as_the_brokers() -> None:
    assert request_description("post", "https://api.github.com/repos/${pactbroker.x}/y") == "POST api.github.com"
    assert scope_description("Web", "API") == "A webhook for the pact between Web and API"
    assert scope_description(None, "API") == "A webhook for all pacts with provider API"
    assert scope_description("Web", None) == "A webhook for all pacts with consumer Web"
    assert scope_description(None, None) == "A webhook for all pacts"


def test_a_uuid_in_a_url_is_canonical_or_not_found() -> None:
    assert validate_webhook_uuid(" 4F1E2D00-0000-4000-8000-000000000001 ") == "4f1e2d00-0000-4000-8000-000000000001"
    with pytest.raises(PactPublicationError) as caught:
        validate_webhook_uuid("execute")
    assert caught.value.code == CODE_WEBHOOK_NOT_FOUND
