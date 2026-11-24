"""Environment and deployment bodies — PFX-1.5 (#6918).

The pure part of :mod:`app.pact_environment`:

* an environment body is the Pact Broker's (``name`` without spaces, single-line display name and
  contact names), with Apiome's ``contractRequired``; refusals carry a JSON Pointer;
* fields a client read back and sends again (``uuid``, ``_links`` …) are ignored;
* a deployment body's application instance is read from ``applicationInstance`` or the deprecated
  ``target``; blank means the unnamed instance;
* an undeployment or support-ended patch only ever sets its flag to ``false``;
* rows adapt into records, the environment of a joined row included.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.pact_environment import (
    CODE_DEPLOYMENT_INVALID,
    CODE_ENVIRONMENT_INVALID,
    MAX_CONTACTS,
    deployed_version_from_row,
    environment_from_row,
    parse_application_instance,
    parse_environment_request,
    parse_flag_patch,
    released_version_from_row,
)
from app.pact_publication import PactPublicationError


def _body(value: Any) -> bytes:
    return json.dumps(value).encode()


# --- environments ------------------------------------------------------------------------------


def test_the_create_environment_body_is_read_as_the_broker_takes_it() -> None:
    checked = parse_environment_request(
        _body(
            {
                "name": "production",
                "displayName": "  Production  ",
                "production": True,
                "contacts": [{"name": "Team Ledger", "details": {"emailAddress": "ledger@example.com"}}],
            }
        )
    )
    assert checked.name == "production"
    assert checked.display_name == "Production"
    assert checked.production is True
    assert checked.contract_required is False
    assert checked.contacts == [{"name": "Team Ledger", "details": {"emailAddress": "ledger@example.com"}}]


def test_defaults_display_name_from_name_and_production_to_false() -> None:
    checked = parse_environment_request(_body({"name": "test"}))
    assert (checked.display_name, checked.production, checked.contacts) == ("test", False, [])


def test_contract_required_is_an_apiome_flag() -> None:
    assert parse_environment_request(_body({"name": "prod", "contractRequired": True})).contract_required is True


def test_what_a_client_read_back_is_ignored() -> None:
    checked = parse_environment_request(
        _body({"name": "test", "uuid": "x", "createdAt": "2026-11-24", "_links": {}, "production": False})
    )
    assert checked.name == "test"


@pytest.mark.parametrize(
    ("body", "pointer", "message"),
    [
        (b"", "", "must be a JSON object"),
        (b"{nope", "", "not JSON"),
        (_body([]), "", "must be a JSON object"),
        (_body({}), "/name", "is required"),
        (_body({"name": "  "}), "/name", "cannot be blank"),
        (_body({"name": 7}), "/name", "must be a string"),
        (_body({"name": "pro duction"}), "/name", "cannot contain spaces"),
        (_body({"name": "x" * 256}), "/name", "at most 255"),
        (_body({"name": "prod", "displayName": "a\nb"}), "/displayName", "single line"),
        (_body({"name": "prod", "production": "yes"}), "/production", "true or false"),
        (_body({"name": "prod", "contractRequired": 1}), "/contractRequired", "true or false"),
        (_body({"name": "prod", "contacts": {}}), "/contacts", "must be an array"),
        (_body({"name": "prod", "contacts": ["x"]}), "/contacts/0", "must be an object"),
        (_body({"name": "prod", "contacts": [{}]}), "/contacts/0/name", "is required"),
        (_body({"name": "prod", "contacts": [{"name": "a", "details": []}]}), "/contacts/0/details", "object"),
        (_body({"name": "prod", "contacts": [{"name": "a"}] * (MAX_CONTACTS + 1)}), "/contacts", "at most"),
    ],
)
def test_a_malformed_environment_is_refused_with_a_pointer(body: bytes, pointer: str, message: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        parse_environment_request(body)
    assert caught.value.code == CODE_ENVIRONMENT_INVALID
    assert caught.value.pointer == pointer
    assert message in str(caught.value)


# --- deployments -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "instance"),
    [
        (b"", None),
        (_body({}), None),
        (_body({"applicationInstance": "eu-1", "target": "eu-1"}), "eu-1"),
        (_body({"target": "blue"}), "blue"),
        (_body({"applicationInstance": "  "}), None),
        (_body({"applicationInstance": None, "target": None}), None),
    ],
)
def test_the_application_instance_is_read_as_the_cli_sends_it(body: bytes, instance: Any) -> None:
    assert parse_application_instance(body) == instance


@pytest.mark.parametrize(
    ("body", "pointer"),
    [
        (_body([1]), ""),
        (_body({"applicationInstance": 3}), "/applicationInstance"),
        (_body({"target": "a\nb"}), "/target"),
        (_body({"applicationInstance": "x" * 256}), "/applicationInstance"),
    ],
)
def test_a_malformed_deployment_is_refused(body: bytes, pointer: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        parse_application_instance(body)
    assert (caught.value.code, caught.value.pointer) == (CODE_DEPLOYMENT_INVALID, pointer)


def test_a_patch_ends_the_deployment_only_with_false() -> None:
    assert parse_flag_patch(_body({"currentlyDeployed": False}), "currentlyDeployed") is True
    assert parse_flag_patch(_body({}), "currentlyDeployed") is False
    assert parse_flag_patch(b"", "currentlySupported") is False
    assert parse_flag_patch(_body({"currentlySupported": None}), "currentlySupported") is False


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (_body({"currentlyDeployed": True}), "record the deployment again"),
        (_body({"currentlyDeployed": "false"}), "must be false"),
        (_body("x"), "must be a JSON object"),
    ],
)
def test_a_patch_cannot_revive_a_deployment(body: bytes, message: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        parse_flag_patch(body, "currentlyDeployed")
    assert caught.value.code == CODE_DEPLOYMENT_INVALID
    assert message in str(caught.value)


def test_reviving_a_release_names_the_release() -> None:
    with pytest.raises(PactPublicationError, match="record the release again"):
        parse_flag_patch(_body({"currentlySupported": True}), "currentlySupported")


# --- rows --------------------------------------------------------------------------------------

_ENVIRONMENT_ROW = {
    "environment_id": "e-1",
    "environment_name": "production",
    "environment_display_name": "Production",
    "environment_production": True,
    "environment_contract_required": False,
    "environment_contacts": '[{"name": "Team"}]',
    "environment_created_at": "2026-11-24T10:00:00+00:00",
    "environment_updated_at": "2026-11-24T10:00:00+00:00",
}


def test_rows_adapt_into_records() -> None:
    environment = environment_from_row({"id": "e-2", "name": "test", "display_name": None, "contacts": None})
    assert (environment.display_name, environment.contacts, environment.production) == ("test", [], False)

    deployed = deployed_version_from_row(
        {
            "id": "d-1",
            "pacticipant_slug": "ledger-api",
            "pacticipant_name": "Ledger API",
            "version_number": "4f1e2d0",
            "application_instance": None,
            "currently_deployed": True,
            "undeployed_at": None,
            "created_at": "2026-11-24T10:00:00+00:00",
            **_ENVIRONMENT_ROW,
        }
    )
    assert deployed.environment.name == "production"
    assert deployed.environment.contacts == [{"name": "Team"}]
    assert (deployed.currently_deployed, deployed.application_instance) == (True, None)

    released = released_version_from_row(
        {
            "id": "r-1",
            "pacticipant_slug": "app",
            "pacticipant_name": "App",
            "version_number": "2.0",
            "currently_supported": False,
            "support_ended_at": "2026-11-25T10:00:00+00:00",
            **_ENVIRONMENT_ROW,
        }
    )
    assert (released.currently_supported, released.support_ended_at) == (False, "2026-11-25T10:00:00+00:00")
