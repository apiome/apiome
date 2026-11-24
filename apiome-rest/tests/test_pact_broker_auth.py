"""Authentication on the Pact Broker surface — PFX-1.2 (#6915).

Pact tooling sends its credential as ``Authorization: Bearer <token>``. On these routes a bearer
token that is not session-shaped is validated as a workspace API key; everything else goes through
:func:`app.auth.validate_authentication` unchanged.
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.pact_broker_auth import _bearer_api_key, validate_broker_authentication

_KEY = "sk_devseed0000000000000000000000000000000000"
_JWT = "aaaa.bbbb.cccc"


@pytest.mark.parametrize(
    ("header", "key"),
    [
        (f"Bearer {_KEY}", _KEY),
        (f"bearer   {_KEY} ", _KEY),
        (f"Bearer {_JWT}", None),
        ("Basic dXNlcjpwdw==", None),
        ("Bearer ", None),
        (_KEY, None),
        (None, None),
    ],
)
def test_only_a_bearer_token_that_is_not_a_session_is_a_key(header: Optional[str], key: Optional[str]) -> None:
    assert _bearer_api_key(header) == key


def _call(authorization: Optional[str], x_api_key: Optional[str]) -> Any:
    request = MagicMock()
    with patch("app.pact_broker_auth.validate_authentication", return_value={"ok": True}) as validate:
        assert validate_broker_authentication(request, "acme", authorization, x_api_key) == {"ok": True}
    return validate.call_args.args[1:]


def test_a_bearer_api_key_is_validated_as_an_api_key() -> None:
    assert _call(f"Bearer {_KEY}", None) == ("acme", None, _KEY)


def test_a_session_token_is_left_to_the_session_check() -> None:
    assert _call(f"Bearer {_JWT}", None) == ("acme", f"Bearer {_JWT}", None)


def test_an_explicit_api_key_header_wins() -> None:
    assert _call(f"Bearer {_KEY}", "sk_other") == ("acme", f"Bearer {_KEY}", "sk_other")


def test_no_credential_is_still_refused_by_the_shared_check() -> None:
    assert _call(None, None) == ("acme", None, None)
