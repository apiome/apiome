"""Where an upstream credential may go, and how it is attached — AGX-2.2 (#4534).

:mod:`app.upstream_credential_binding` is the rule that decides whether a tenant's secret leaves
the process. These tests pin it from both sides: every shape a server URL may be registered in,
every way a request URL could try to reach outside the bound server (scheme downgrade, look-alike
host, port change, userinfo, path-prefix confusion, encoded traversal), and how an opened secret is
attached and kept out of ``repr``.
"""

from __future__ import annotations

import base64

import pytest

from app.upstream_credential_binding import (
    API_KEY_IN_HEADER,
    API_KEY_IN_QUERY,
    CODE_BINDING_INVALID,
    CODE_PLACEMENT_INVALID,
    CODE_SERVER_URL_INVALID,
    KIND_API_KEY,
    KIND_BASIC,
    KIND_BEARER,
    MAX_API_KEY_NAME_CHARS,
    MAX_SERVER_URL_CHARS,
    BindingError,
    CredentialInjection,
    binds,
    build_injection,
    normalize_server_url,
    validate_api_key_placement,
)

_SECRET = "sk_live_TOPSECRET_value_123"


# ============================================================================
# normalize_server_url
# ============================================================================
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://api.example.com", "https://api.example.com"),
        ("https://api.example.com/", "https://api.example.com"),
        ("  https://api.example.com/v1/  ", "https://api.example.com/v1"),
        ("HTTPS://API.Example.COM/V1", "https://api.example.com/V1"),
        ("https://api.example.com:443/v1", "https://api.example.com/v1"),
        ("https://api.example.com:8443/v1", "https://api.example.com:8443/v1"),
        ("https://api.example.com./v1", "https://api.example.com/v1"),
        ("https://[2001:db8::1]:8443/api", "https://[2001:db8::1]:8443/api"),
        ("https://api.example.com/v1//", "https://api.example.com/v1"),
        ("https://xn--bcher-kva.example/", "https://xn--bcher-kva.example"),
    ],
)
def test_normalize_server_url_accepts_an_https_origin_and_base_path(raw, expected):
    assert normalize_server_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (None, "is required"),
        ("", "is required"),
        ("   ", "is required"),
        ("http://api.example.com", "https://"),
        ("ftp://api.example.com", "https://"),
        ("file:///etc/passwd", "https://"),
        ("api.example.com/v1", "https://"),
        ("https://user:pass@api.example.com", "must not embed credentials"),
        ("https://user@api.example.com", "must not embed credentials"),
        ("https://api.example.com/v1?key=1", "query string"),
        ("https://api.example.com/v1?", "query string"),
        ("https://api.example.com/v1#frag", "query string"),
        ("https:///v1", "must name a host"),
        ("https://bücher.example/", "ASCII host"),
        ("https://api.example.com:99999/", "not a valid URL"),
        ("https://api.example.com:abc/", "not a valid URL"),
        ("https://api.example.com/v1/../admin", "path segments"),
        ("https://api.example.com/./v1", "path segments"),
        ("https://api.example.com/v1/%2e%2e/admin", "path segments"),
        ("https://api.example.com/v1\\admin", "path segments"),
        ("https://api.example.com/v 1", "whitespace or control"),
        ("https://api.example.com/v1\r\nX: y", "whitespace or control"),
        ("https://api.example.com/" + "a" * MAX_SERVER_URL_CHARS, "longer than"),
    ],
)
def test_normalize_server_url_refuses_anything_else(raw, reason):
    with pytest.raises(BindingError) as caught:
        normalize_server_url(raw)
    assert caught.value.code == CODE_SERVER_URL_INVALID
    assert reason in str(caught.value)


def test_two_spellings_of_one_server_normalize_identically():
    spellings = {
        normalize_server_url(raw)
        for raw in (
            "https://API.example.com/v1",
            "https://api.example.com:443/v1/",
            "https://api.example.com./v1",
        )
    }
    assert spellings == {"https://api.example.com/v1"}


# ============================================================================
# validate_api_key_placement
# ============================================================================
@pytest.mark.parametrize(
    ("location", "name", "expected"),
    [
        ("header", "X-Api-Key", ("header", "X-Api-Key")),
        ("header", "  X-Api-Key  ", ("header", "X-Api-Key")),
        ("header", "Authorization", ("header", "Authorization")),
        ("header", "x_key!#$%&'*+.^`|~", ("header", "x_key!#$%&'*+.^`|~")),
        ("query", "api_key", ("query", "api_key")),
        ("query", "key.v2~x-y", ("query", "key.v2~x-y")),
    ],
)
def test_placement_accepts_header_tokens_and_unreserved_query_names(location, name, expected):
    assert validate_api_key_placement(location, name) == expected


@pytest.mark.parametrize(
    ("location", "name", "reason"),
    [
        (None, "X-Api-Key", "`in`"),
        ("cookie", "session", "`in`"),
        ("header", None, "needs a `name`"),
        ("header", "   ", "needs a `name`"),
        ("header", "X Api Key", "RFC 9110"),
        ("header", "X-Api-Key\r\nInjected", "RFC 9110"),
        ("header", "X:Key", "RFC 9110"),
        ("header", "Host", "managed by the HTTP client"),
        ("header", "content-length", "managed by the HTTP client"),
        ("header", "Transfer-Encoding", "managed by the HTTP client"),
        ("header", "Cookie", "managed by the HTTP client"),
        ("header", "Proxy-Authorization", "managed by the HTTP client"),
        ("query", "api key", "letters, digits"),
        ("query", "a&b", "letters, digits"),
        ("query", "a=b", "letters, digits"),
        ("header", "X" * (MAX_API_KEY_NAME_CHARS + 1), "longer than"),
    ],
)
def test_placement_refuses_names_that_could_split_or_reroute_a_request(location, name, reason):
    with pytest.raises(BindingError) as caught:
        validate_api_key_placement(location, name)
    assert caught.value.code == CODE_PLACEMENT_INVALID
    assert reason in str(caught.value)


# ============================================================================
# binds — the only test applied before a secret is handed to the proxy
# ============================================================================
_BOUND = "https://api.example.com/v1"


@pytest.mark.parametrize(
    "request_url",
    [
        "https://api.example.com/v1",
        "https://api.example.com/v1/",
        "https://api.example.com/v1/pets",
        "https://api.example.com/v1/pets/42?limit=10#top",
        "https://API.EXAMPLE.COM/v1/pets",
        "https://api.example.com:443/v1/pets",
        "https://api.example.com./v1/pets",
        "https://api.example.com/v1/files/a%2Fb",
        "https://api.example.com/v1/pets?next=../x",
    ],
)
def test_requests_under_the_bound_server_are_bound(request_url):
    assert binds(_BOUND, request_url) is True


@pytest.mark.parametrize(
    "request_url",
    [
        # Scheme downgrade.
        "http://api.example.com/v1/pets",
        # Other hosts, including look-alikes built around the bound host.
        "https://evil.example.com/v1/pets",
        "https://api.example.com.evil.com/v1/pets",
        "https://evilapi.example.com/v1/pets",
        "https://example.com/v1/pets",
        "https://evil.com/https://api.example.com/v1",
        # Userinfo that makes a different host the authority.
        "https://api.example.com@evil.com/v1/pets",
        "https://user:pass@api.example.com/v1/pets",
        # Another port on the same host.
        "https://api.example.com:8443/v1/pets",
        # Outside the base path, or a sibling that merely shares its prefix.
        "https://api.example.com/",
        "https://api.example.com/admin",
        "https://api.example.com/v10/pets",
        "https://api.example.com/v1evil",
        "https://api.example.com/V1/pets",
        # Traversal back out of the base path, raw, encoded, double-encoded, or via backslash.
        "https://api.example.com/v1/../admin",
        "https://api.example.com/v1/./pets",
        "https://api.example.com/v1/%2e%2e/admin",
        "https://api.example.com/v1/%2E%2E/admin",
        "https://api.example.com/v1/%252e%252e/admin",
        "https://api.example.com/v1/..%2fadmin",
        "https://api.example.com/v1\\..\\admin",
        "https://api.example.com/v1%2f..%2fadmin",
        # Segments a lenient server reads as "..": matrix params, full-width dots, and a path
        # still decoding after every round the check makes.
        "https://api.example.com/v1/..;/admin",
        "https://api.example.com/v1/..;jsessionid=x/admin",
        "https://api.example.com/v1/\uff0e\uff0e/admin",
        "https://api.example.com/v1/%25252525252e%25252525252e/admin",
        # Not a URL at all.
        "",
        "not a url",
        "https://api.example.com:notaport/v1",
    ],
)
def test_requests_outside_the_bound_server_are_not_bound(request_url):
    assert binds(_BOUND, request_url) is False


def test_an_origin_only_binding_covers_every_path_on_that_origin():
    assert binds("https://api.example.com", "https://api.example.com/") is True
    assert binds("https://api.example.com", "https://api.example.com") is True
    assert binds("https://api.example.com", "https://api.example.com/any/path") is True
    assert binds("https://api.example.com", "https://api.example.com/a/../b") is False
    assert binds("https://api.example.com", "https://other.example.com/") is False


def test_a_non_default_port_must_match_exactly():
    bound = "https://api.example.com:8443"
    assert binds(bound, "https://api.example.com:8443/x") is True
    assert binds(bound, "https://api.example.com/x") is False
    assert binds(bound, "https://api.example.com:443/x") is False


def test_ipv6_literal_bindings_compare_on_the_address():
    bound = "https://[2001:db8::1]:8443/api"
    assert binds(bound, "https://[2001:DB8::1]:8443/api/x") is True
    assert binds(bound, "https://[2001:db8::2]:8443/api/x") is False


def test_an_unparseable_stored_binding_binds_nothing():
    assert binds("", "https://api.example.com/") is False
    assert binds("https://api.example.com:notaport", "https://api.example.com/") is False


# ============================================================================
# build_injection
# ============================================================================
def test_bearer_is_sent_as_an_authorization_bearer_header():
    injection = build_injection(
        credential_id="c1",
        kind=KIND_BEARER,
        api_key_in=None,
        api_key_name=None,
        secret={"token": _SECRET},
    )
    assert injection.headers == (("Authorization", f"Bearer {_SECRET}"),)
    assert injection.query == ()


def test_basic_is_sent_as_rfc_7617_utf8_basic_auth():
    injection = build_injection(
        credential_id="c1",
        kind=KIND_BASIC,
        api_key_in=None,
        api_key_name=None,
        secret={"username": "ÿser", "password": "pa:ss"},
    )
    (name, value), = injection.headers
    assert name == "Authorization"
    assert value.startswith("Basic ")
    assert base64.b64decode(value[len("Basic "):]).decode("utf-8") == "ÿser:pa:ss"


def test_basic_accepts_an_empty_password():
    injection = build_injection(
        credential_id="c1",
        kind=KIND_BASIC,
        api_key_in=None,
        api_key_name=None,
        secret={"username": "sk_key", "password": ""},
    )
    assert base64.b64decode(injection.headers[0][1][6:]) == b"sk_key:"


def test_api_key_header_and_query_placements():
    header = build_injection(
        credential_id="c1",
        kind=KIND_API_KEY,
        api_key_in=API_KEY_IN_HEADER,
        api_key_name="X-Api-Key",
        secret={"value": _SECRET},
    )
    assert header.headers == (("X-Api-Key", _SECRET),)
    assert header.query == ()

    query = build_injection(
        credential_id="c1",
        kind=KIND_API_KEY,
        api_key_in=API_KEY_IN_QUERY,
        api_key_name="api_key",
        secret={"value": _SECRET},
    )
    assert query.query == (("api_key", _SECRET),)
    assert query.headers == ()


@pytest.mark.parametrize(
    ("kind", "secret", "api_key_in", "api_key_name"),
    [
        (KIND_BEARER, {}, None, None),
        (KIND_BEARER, {"value": _SECRET}, None, None),
        (KIND_BASIC, {"username": "u"}, None, None),
        (KIND_BASIC, {"username": 1, "password": "p"}, None, None),
        (KIND_API_KEY, {"token": _SECRET}, "header", "X-Key"),
        ("oauth2", {"token": _SECRET}, None, None),
    ],
)
def test_a_payload_that_does_not_fit_its_kind_is_refused_without_quoting_it(
    kind, secret, api_key_in, api_key_name
):
    with pytest.raises(BindingError) as caught:
        build_injection(
            credential_id="c1",
            kind=kind,
            api_key_in=api_key_in,
            api_key_name=api_key_name,
            secret=secret,
        )
    assert caught.value.code == CODE_BINDING_INVALID
    assert _SECRET not in str(caught.value)


def test_an_api_key_with_a_corrupt_placement_is_refused():
    with pytest.raises(BindingError) as caught:
        build_injection(
            credential_id="c1",
            kind=KIND_API_KEY,
            api_key_in="header",
            api_key_name="Host",
            secret={"value": _SECRET},
        )
    assert caught.value.code == CODE_PLACEMENT_INVALID


# ============================================================================
# CredentialInjection — apply, and never reveal
# ============================================================================
def test_repr_and_str_name_what_is_set_but_never_the_value():
    injection = CredentialInjection(
        credential_id="c1",
        headers=(("Authorization", f"Bearer {_SECRET}"),),
        query=(("api_key", _SECRET),),
    )
    for rendered in (repr(injection), str(injection), f"{injection}", f"{[injection]}"):
        assert _SECRET not in rendered
        assert "Authorization" in rendered
        assert "api_key" in rendered
        assert "c1" in rendered


def test_apply_replaces_a_same_named_header_case_insensitively():
    injection = CredentialInjection(
        credential_id="c1", headers=(("Authorization", f"Bearer {_SECRET}"),)
    )
    original = {"authorization": "Bearer agent-supplied", "Accept": "application/json"}
    url, headers = injection.apply("https://api.example.com/v1/pets", original)
    assert url == "https://api.example.com/v1/pets"
    assert headers == {"Authorization": f"Bearer {_SECRET}", "Accept": "application/json"}
    # The caller's mapping is left untouched.
    assert original["authorization"] == "Bearer agent-supplied"


def test_apply_replaces_a_same_named_query_parameter_and_keeps_the_rest_byte_for_byte():
    injection = CredentialInjection(credential_id="c1", query=(("api_key", "s3cr3t/+&="),))
    url, headers = injection.apply(
        "https://api.example.com/v1/pets?api_key=agent&q=a+b%20c&api%5Fkey=again&flag#frag",
        {},
    )
    assert headers == {}
    assert url == (
        "https://api.example.com/v1/pets?q=a+b%20c&flag&api_key=s3cr3t%2F%2B%26%3D#frag"
    )


def test_apply_adds_a_query_string_when_there_is_none():
    injection = CredentialInjection(credential_id="c1", query=(("key", "v"),))
    url, _ = injection.apply("https://api.example.com/v1/pets", {})
    assert url == "https://api.example.com/v1/pets?key=v"


def test_a_header_only_injection_leaves_the_url_alone():
    injection = CredentialInjection(credential_id="c1", headers=(("X-Api-Key", "v"),))
    url, _ = injection.apply("https://api.example.com/v1/pets?a=1&api_key=x", {})
    assert url == "https://api.example.com/v1/pets?a=1&api_key=x"


def test_apply_puts_the_query_before_a_fragment():
    injection = CredentialInjection(credential_id="c1", query=(("key", "v"),))
    url, _ = injection.apply("https://api.example.com/v1/pets#frag", {})
    assert url == "https://api.example.com/v1/pets?key=v#frag"
    # A '?' inside the fragment is part of the fragment, not a query string.
    url, _ = injection.apply("https://api.example.com/v1/pets#frag?key=agent", {})
    assert url == "https://api.example.com/v1/pets?key=v#frag?key=agent"


def test_apply_drops_a_same_named_pair_hidden_behind_a_semicolon():
    injection = CredentialInjection(credential_id="c1", query=(("api_key", "v"),))
    url, _ = injection.apply("https://api.example.com/v1?x=1;api_key=agent&y=2;z=3", {})
    assert url == "https://api.example.com/v1?x=1&y=2;z=3&api_key=v"


def test_matrix_parameters_on_ordinary_segments_still_bind():
    assert binds(_BOUND, "https://api.example.com/v1/pets;v=2/42") is True
