"""Tests for the installation sign-up policy (SGN-1.4, #5653).

Mirrors ``apiome-ui/tests/signup-policy.test.ts`` — both sides run the same matrix:

  1. the pure policy (:func:`app.signup_policy.signup_rejection_code`) and its normalizers;
  2. **each mode is enforced identically for email and every OAuth provider** — one table driven
     through :func:`resolve_account_decision` per provider and
     :func:`resolve_email_signup_decision` for the email form;
  3. the env fallback is unchanged when nothing is stored;
  4. the cached read: lifetime, invalidation, and failing closed.
"""

import pytest

from app import signup_policy as sp
from app.account_resolution import (
    ACTION_AUTO_LINK,
    ACTION_REJECT,
    ACTION_SIGN_IN,
    ACTION_SIGNUP,
    AUTO_LINK_TRUSTED_PROVIDERS,
    EMAIL_REQUIRED,
    ResolutionIdentity,
    ResolutionInput,
    ResolutionUser,
    resolve_account_decision,
    resolve_email_signup_decision,
)
from app.signup_policy import (
    MODE_CLOSED,
    MODE_INVITE_ONLY,
    MODE_OPEN,
    SIGNUP_DISABLED,
    SIGNUP_DOMAIN_NOT_ALLOWED,
    SIGNUP_INVITE_ONLY,
    SOURCE_DB,
    SOURCE_ENV,
    SignupPolicy,
    get_effective_signup_policy,
    invalidate_signup_policy_cache,
    normalize_allowed_email_domains,
    normalize_email_domain,
    signup_policy_cache_ttl_seconds,
    signup_policy_from_env,
    signup_policy_from_row,
    signup_rejection_code,
)

OK_USER = ResolutionUser(id="user-ok", enabled=True, verified=True)

#: The sign-up paths the policy must treat identically: the email form plus every provider whose
#: verified email can reach account creation.
EMAIL_PATH = "email"
SIGNUP_PATHS = (EMAIL_PATH, *sorted(AUTO_LINK_TRUSTED_PROVIDERS))

#: (case id, policy, address, expected rejection code or None when the account is created).
POLICY_MATRIX = (
    ("open", SignupPolicy(mode=MODE_OPEN), "ada@example.com", None),
    ("invite-only", SignupPolicy(mode=MODE_INVITE_ONLY), "ada@example.com", SIGNUP_INVITE_ONLY),
    ("closed", SignupPolicy(mode=MODE_CLOSED), "ada@example.com", SIGNUP_DISABLED),
    (
        "open, domain allowed",
        SignupPolicy(mode=MODE_OPEN, allowed_email_domains=("example.com",)),
        "ada@example.com",
        None,
    ),
    (
        "open, domain not allowed",
        SignupPolicy(mode=MODE_OPEN, allowed_email_domains=("example.com",)),
        "ada@elsewhere.test",
        SIGNUP_DOMAIN_NOT_ALLOWED,
    ),
    (
        "open, subdomain is not the listed domain",
        SignupPolicy(mode=MODE_OPEN, allowed_email_domains=("example.com",)),
        "ada@mail.example.com",
        SIGNUP_DOMAIN_NOT_ALLOWED,
    ),
    (
        "invite-only ignores the domain list",
        SignupPolicy(mode=MODE_INVITE_ONLY, allowed_email_domains=("example.com",)),
        "ada@example.com",
        SIGNUP_INVITE_ONLY,
    ),
    (
        "closed ignores the domain list",
        SignupPolicy(mode=MODE_CLOSED, allowed_email_domains=("example.com",)),
        "ada@example.com",
        SIGNUP_DISABLED,
    ),
)

MATRIX_PARAMS = [
    pytest.param(path, policy, email, expected, id=f"{path}: {case}")
    for case, policy, email, expected in POLICY_MATRIX
    for path in SIGNUP_PATHS
]


def _decide(path, policy, email, email_user=None):
    """Run one sign-up attempt down the named path and return the decision."""
    if path == EMAIL_PATH:
        return resolve_email_signup_decision(email, policy, email_user)
    return resolve_account_decision(
        ResolutionInput(
            provider=path,
            provider_user_id="prov-123",
            email=email,
            email_verified=True,
            identity=ResolutionIdentity(),
            email_user=email_user,
            signup_policy=policy,
        )
    )


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Each test starts and ends with an empty policy cache."""
    invalidate_signup_policy_cache()
    yield
    invalidate_signup_policy_cache()


# --- 1. Pure policy -----------------------------------------------------------


@pytest.mark.parametrize("case,policy,email,expected", POLICY_MATRIX, ids=[c[0] for c in POLICY_MATRIX])
def test_rejection_code_matrix(case, policy, email, expected):
    assert signup_rejection_code(policy, email) == expected


def test_domain_list_refuses_an_address_without_a_domain():
    policy = SignupPolicy(mode=MODE_OPEN, allowed_email_domains=("example.com",))
    assert signup_rejection_code(policy, None) == SIGNUP_DOMAIN_NOT_ALLOWED
    assert signup_rejection_code(policy, "not-an-address") == SIGNUP_DOMAIN_NOT_ALLOWED


def test_domain_match_ignores_case():
    policy = SignupPolicy(mode=MODE_OPEN, allowed_email_domains=("example.com",))
    assert signup_rejection_code(policy, "Ada@EXAMPLE.com") is None


def test_unrecognized_mode_fails_closed():
    assert signup_rejection_code(SignupPolicy(mode="whatever"), "ada@example.com") == SIGNUP_DISABLED


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("example.com", "example.com"),
        ("  Example.COM ", "example.com"),
        ("@example.com", "example.com"),
        ("mail.example.co.uk", "mail.example.co.uk"),
    ],
)
def test_normalize_email_domain_accepts(raw, expected):
    assert normalize_email_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "localhost", "ada@example.com", "*.example.com", "https://example.com", "exa mple.com",
     "-bad.example.com", "example..com", 42, None],
)
def test_normalize_email_domain_rejects(raw):
    with pytest.raises(ValueError):
        normalize_email_domain(raw)


def test_normalize_allowed_email_domains_dedupes_and_keeps_order():
    assert normalize_allowed_email_domains(["B.example", "a.example", "@b.example"]) == (
        "b.example",
        "a.example",
    )
    assert normalize_allowed_email_domains(None) == ()


def test_normalize_allowed_email_domains_rejects_a_bare_string_and_overlong_lists():
    with pytest.raises(ValueError):
        normalize_allowed_email_domains("example.com")
    with pytest.raises(ValueError):
        normalize_allowed_email_domains(
            [f"d{i}.example" for i in range(sp.MAX_ALLOWED_EMAIL_DOMAINS + 1)]
        )


# --- 2. Identical enforcement for email and every OAuth provider ---------------


@pytest.mark.parametrize("path,policy,email,expected", MATRIX_PARAMS)
def test_every_path_enforces_the_policy_identically(path, policy, email, expected):
    decision = _decide(path, policy, email)
    if expected is None:
        assert (decision.action, decision.email) == (ACTION_SIGNUP, email)
    else:
        assert (decision.action, decision.code) == (ACTION_REJECT, expected)


@pytest.mark.parametrize("path", SIGNUP_PATHS)
@pytest.mark.parametrize("mode", sp.SIGNUP_MODES)
def test_no_mode_ever_blocks_an_existing_account(path, mode):
    """The policy gates creating an account only — an existing user is never refused by it."""
    policy = SignupPolicy(mode=mode, allowed_email_domains=("other.test",))
    decision = _decide(path, policy, "ada@example.com", email_user=OK_USER)
    assert decision.action == (ACTION_SIGN_IN if path == EMAIL_PATH else ACTION_AUTO_LINK)
    assert decision.user_id == OK_USER.id


def test_email_signup_requires_an_address():
    decision = resolve_email_signup_decision("  ", SignupPolicy(mode=MODE_OPEN))
    assert (decision.action, decision.code) == (ACTION_REJECT, EMAIL_REQUIRED)


def test_policy_supersedes_the_legacy_signup_disabled_fact():
    facts = ResolutionInput(
        provider="github",
        provider_user_id="prov-123",
        email="ada@example.com",
        email_verified=True,
        signup_disabled=True,
        signup_policy=SignupPolicy(mode=MODE_OPEN),
    )
    assert resolve_account_decision(facts).action == ACTION_SIGNUP


# --- 3. Env fallback ----------------------------------------------------------


@pytest.mark.parametrize(
    "value,mode",
    [("true", MODE_CLOSED), (" TRUE ", MODE_CLOSED), ("1", MODE_CLOSED), ("false", MODE_OPEN),
     ("0", MODE_OPEN), ("yes", MODE_OPEN), (None, MODE_OPEN)],
)
def test_env_fallback_reads_auth_signup_disabled(value, mode):
    env = {} if value is None else {"AUTH_SIGNUP_DISABLED": value}
    policy = signup_policy_from_env(env)
    assert (policy.mode, policy.allowed_email_domains, policy.source) == (mode, (), SOURCE_ENV)


def test_row_parsing():
    assert signup_policy_from_row(None) is None
    assert signup_policy_from_row({"mode": "nonsense"}) is None
    policy = signup_policy_from_row(
        {"mode": "open", "allowed_email_domains": ["Example.com", "not a domain", "example.com"]}
    )
    assert policy == SignupPolicy(MODE_OPEN, ("example.com",), SOURCE_DB)


@pytest.mark.parametrize("env_value,mode", [("true", MODE_CLOSED), (None, MODE_OPEN)])
def test_unset_in_db_leaves_env_behaviour_unchanged(env_value, mode):
    env = {} if env_value is None else {"AUTH_SIGNUP_DISABLED": env_value}
    policy = get_effective_signup_policy(read_row=lambda: None, env=env)
    assert (policy.mode, policy.source) == (mode, SOURCE_ENV)


def test_stored_policy_wins_over_env():
    policy = get_effective_signup_policy(
        read_row=lambda: {"mode": "invite_only", "allowed_email_domains": []},
        env={"AUTH_SIGNUP_DISABLED": "true"},
    )
    assert (policy.mode, policy.source) == (MODE_INVITE_ONLY, SOURCE_DB)


# --- 4. Cached read -----------------------------------------------------------


class _Clock:
    """A hand-advanced monotonic clock."""

    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_change_takes_effect_after_the_cache_lifetime_without_a_restart():
    clock = _Clock()
    stored = {"mode": "open", "allowed_email_domains": []}
    reads = []

    def read_row():
        reads.append(1)
        return dict(stored)

    def effective():
        return get_effective_signup_policy(read_row=read_row, env={}, now=clock)

    assert effective().mode == MODE_OPEN
    stored["mode"] = "closed"
    clock.t += sp.DEFAULT_CACHE_TTL_SECONDS - 1
    assert effective().mode == MODE_OPEN  # still cached
    assert len(reads) == 1
    clock.t += 2
    assert effective().mode == MODE_CLOSED  # lifetime elapsed → re-read
    assert len(reads) == 2


def test_invalidation_applies_a_change_at_once():
    clock = _Clock()
    stored = {"mode": "open", "allowed_email_domains": []}

    def effective():
        return get_effective_signup_policy(read_row=lambda: dict(stored), env={}, now=clock)

    assert effective().mode == MODE_OPEN
    stored["mode"] = "closed"
    invalidate_signup_policy_cache()
    assert effective().mode == MODE_CLOSED


def test_unreadable_database_fails_closed_then_recovers():
    def broken():
        raise RuntimeError("db down")

    policy = get_effective_signup_policy(read_row=broken, env={})
    assert policy.mode == MODE_CLOSED
    # The failure is not cached: the next read succeeds and is served.
    assert get_effective_signup_policy(read_row=lambda: None, env={}).mode == MODE_OPEN


def test_unreadable_database_serves_the_last_known_policy():
    clock = _Clock()
    get_effective_signup_policy(
        read_row=lambda: {"mode": "invite_only", "allowed_email_domains": []}, env={}, now=clock
    )
    clock.t += sp.MAX_CACHE_TTL_SECONDS + 1

    def broken():
        raise RuntimeError("db down")

    assert get_effective_signup_policy(read_row=broken, env={}, now=clock).mode == MODE_INVITE_ONLY


@pytest.mark.parametrize(
    "raw,expected",
    [(None, sp.DEFAULT_CACHE_TTL_SECONDS), ("", sp.DEFAULT_CACHE_TTL_SECONDS),
     ("abc", sp.DEFAULT_CACHE_TTL_SECONDS), ("nan", sp.DEFAULT_CACHE_TTL_SECONDS),
     ("10", 10.0), ("0", sp.MIN_CACHE_TTL_SECONDS), ("99999", sp.MAX_CACHE_TTL_SECONDS)],
)
def test_cache_lifetime_is_configurable_and_bounded(raw, expected):
    env = {} if raw is None else {"SIGNUP_POLICY_CACHE_TTL_SECONDS": raw}
    assert signup_policy_cache_ttl_seconds(env) == expected
