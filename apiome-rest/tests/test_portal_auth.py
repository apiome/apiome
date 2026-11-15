"""Pure helpers of PCX-1.1 (#5889): tokens, input guards, user-agent family, the sign-in email."""

from __future__ import annotations

import pytest

from app.portal_auth import (
    CODE_INVALID_EMAIL,
    CODE_INVALID_RETURN_TO,
    MAGIC_LINK_PREFIX,
    SESSION_TOKEN_PREFIX,
    PortalAuthError,
    hash_session_token,
    mint_magic_link_token,
    mint_session_token,
    normalize_email,
    reader_token_from_header,
    safe_return_to,
    split_magic_link_token,
    user_agent_family,
    verify_magic_link_token,
)
from app.portal_mail import magic_link_url, render_magic_link_email


def test_a_magic_link_token_round_trips_and_is_stored_hashed():
    token, prefix, token_hash = mint_magic_link_token()
    assert token.startswith(MAGIC_LINK_PREFIX)
    assert split_magic_link_token(token) == prefix
    assert token not in token_hash and prefix in token
    assert verify_magic_link_token(token, token_hash)
    assert not verify_magic_link_token(token[:-1] + ("0" if token[-1] != "0" else "1"), token_hash)


def test_every_byte_of_the_token_is_inside_bcrypts_72_byte_window():
    token, _, _ = mint_magic_link_token()
    assert len(token.encode("utf-8")) <= 72


def test_every_magic_link_token_is_unique():
    assert len({mint_magic_link_token()[1] for _ in range(5)}) == 5


@pytest.mark.parametrize(
    "token",
    ["", "pml_zz", "prs_abc", "pml_0123456789abcdef", "pml_0123456789abcdef.short", "x" * 100],
)
def test_malformed_magic_link_tokens_have_no_prefix(token):
    assert split_magic_link_token(token) is None


def test_an_unreadable_hash_never_verifies():
    token, _, _ = mint_magic_link_token()
    assert verify_magic_link_token(token, "not-a-bcrypt-hash") is False


def test_a_session_token_is_hashed_with_sha256():
    token, token_hash = mint_session_token()
    assert token.startswith(SESSION_TOKEN_PREFIX)
    assert len(token_hash) == 64 and token_hash == hash_session_token(token)
    assert mint_session_token()[0] != token


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Reader prs_abc", "prs_abc"),
        ("reader   prs_abc  ", "prs_abc"),
        ("Bearer prs_abc", None),
        ("Reader sk_live_key", None),
        ("Reader", None),
        (None, None),
        ("Reader prs_" + "a" * 200, None),
    ],
)
def test_the_reader_header_is_parsed_strictly(header, expected):
    assert reader_token_from_header(header) == expected


def test_emails_are_normalized():
    assert normalize_email("  Ada@Example.COM ") == "ada@example.com"


@pytest.mark.parametrize("raw", ["", "ada", "ada@", "@example.com", "a b@example.com", "ada@example", "a" * 250 + "@x.io"])
def test_malformed_emails_are_refused(raw):
    with pytest.raises(PortalAuthError) as exc:
        normalize_email(raw)
    assert exc.value.code == CODE_INVALID_EMAIL


@pytest.mark.parametrize("path", [None, "", "/", "/tenant/acme", "/tenant/acme/pets/1.0.0?tab=try#op"])
def test_same_site_paths_are_accepted(path):
    assert safe_return_to(path) == (path or None)


@pytest.mark.parametrize(
    "path",
    ["https://evil.example", "//evil.example", "/\\evil.example", "tenant/acme", "/a\nb", "/a\x7f", "/" + "a" * 1100],
)
def test_anything_that_could_leave_the_site_is_refused(path):
    with pytest.raises(PortalAuthError) as exc:
        safe_return_to(path)
    assert exc.value.code == CODE_INVALID_RETURN_TO


@pytest.mark.parametrize(
    ("ua", "family"),
    [
        ("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/130.0 Safari/537.36 Edg/130.0", "Edge"),
        ("Mozilla/5.0 (Macintosh) AppleWebKit/537.36 (KHTML) Chrome/130.0 Safari/537.36", "Chrome"),
        ("Mozilla/5.0 (iPhone) AppleWebKit/605.1 CriOS/130.0 Mobile Safari/604.1", "Chrome"),
        ("Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0", "Firefox"),
        ("Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 (KHTML) Version/18.0 Safari/605.1.15", "Safari"),
        ("curl/8.0", "Other"),
        (None, "Other"),
    ],
)
def test_only_the_browser_family_is_kept(ua, family):
    assert user_agent_family(ua) == family


def test_the_link_points_at_the_browse_exchange_route():
    link = magic_link_url("https://docs.acme.example/browse/", "acme", "pml_abc.def")
    assert link == "https://docs.acme.example/browse/portal/auth/exchange?tenant=acme&token=pml_abc.def"


def test_the_email_escapes_the_tenant_name_and_states_the_expiry():
    subject, text, html = render_magic_link_email("<Acme>", "https://b.example/x?a=1&b=2")
    assert subject == "Sign in to <Acme> API docs"
    assert "15 minutes" in text and "https://b.example/x?a=1&b=2" in text
    assert "&lt;Acme&gt;" in html and "<Acme>" not in html
    assert 'href="https://b.example/x?a=1&amp;b=2"' in html
