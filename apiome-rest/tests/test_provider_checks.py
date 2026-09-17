"""The normalized check vocabulary — GNC-2.2 (#4738).

:mod:`app.provider_checks` is data and pure functions, so the whole surface is exercised against
literals. What matters here is not that the tables have entries but that each entry says the right
thing: the one mistake a status adapter can make that nobody forgives is reporting a check as
passing when it did not pass, and every mapping below is checked against that.
"""

from __future__ import annotations

import pytest

from app.provider_checks import (
    CHECK_ORIGINS,
    CHECK_STATES,
    CODE_INVALID_COMMIT,
    CODE_INVALID_DETAILS_URL,
    CODE_INVALID_NAME,
    DEFAULT_CHECK_NAME,
    MAX_DETAILS_URL_LENGTH,
    MAX_NAME_LENGTH,
    PUBLISH_OUTCOMES,
    STATE_FAIL,
    STATE_PASS,
    STATE_PENDING,
    STATE_SKIPPED,
    TERMINAL_STATES,
    CheckRunUpsert,
    ProviderCheckValidationError,
    bitbucket_state,
    github_conclusion,
    github_status,
    gitlab_state,
    is_terminal,
    normalize_check_name,
    normalize_commit_sha,
    normalize_details_url,
    normalize_state,
    request_fingerprint,
    summarize_states,
)

# ---------------------------------------------------------------------------------------------
# The four states
# ---------------------------------------------------------------------------------------------


def test_there_are_exactly_the_four_states_the_ticket_names():
    assert CHECK_STATES == ("pending", "pass", "fail", "skipped")


def test_terminal_states_are_exactly_the_complement_of_pending():
    assert set(TERMINAL_STATES) == set(CHECK_STATES) - {STATE_PENDING}
    assert is_terminal(STATE_PENDING) is False
    assert all(is_terminal(state) for state in TERMINAL_STATES)


def test_the_origins_and_outcomes_mirror_the_migration():
    assert CHECK_ORIGINS == ("webhook", "api", "sweep")
    assert PUBLISH_OUTCOMES == ("dispatched", "suppressed", "failed")


@pytest.mark.parametrize("state", CHECK_STATES)
def test_every_state_normalizes_to_itself(state):
    assert normalize_state(state) == state


@pytest.mark.parametrize(
    "spelling,expected",
    [
        ("passed", STATE_PASS),
        ("SUCCESS", STATE_PASS),
        ("successful", STATE_PASS),
        ("failed", STATE_FAIL),
        ("Failure", STATE_FAIL),
        ("skip", STATE_SKIPPED),
        ("in_progress", STATE_PENDING),
        ("running", STATE_PENDING),
        ("queued", STATE_PENDING),
        ("  pending  ", STATE_PENDING),
    ],
)
def test_a_providers_own_spelling_normalizes_to_the_state_it_means(spelling, expected):
    assert normalize_state(spelling) == expected


@pytest.mark.parametrize("unknown", ["", None, "green", "unstable", "error", "cancelled"])
def test_an_unrecognised_state_is_never_guessed_at(unknown):
    # Guessing between pass and fail is the one mistake that matters, so nothing is guessed.
    assert normalize_state(unknown) is None


# ---------------------------------------------------------------------------------------------
# Provider spellings
# ---------------------------------------------------------------------------------------------


def test_github_reports_a_pending_run_as_in_progress_with_no_conclusion():
    # GitHub refuses a conclusion on a run that has not completed.
    assert github_status(STATE_PENDING) == "in_progress"
    assert github_conclusion(STATE_PENDING) is None


@pytest.mark.parametrize(
    "state,conclusion",
    [(STATE_PASS, "success"), (STATE_FAIL, "failure"), (STATE_SKIPPED, "skipped")],
)
def test_github_completes_every_finished_state_with_its_own_conclusion(state, conclusion):
    assert github_status(state) == "completed"
    assert github_conclusion(state) == conclusion


@pytest.mark.parametrize(
    "state,expected",
    [
        (STATE_PENDING, "running"),
        (STATE_PASS, "success"),
        (STATE_FAIL, "failed"),
        (STATE_SKIPPED, "canceled"),
    ],
)
def test_gitlab_states_are_gitlabs_own_vocabulary(state, expected):
    assert gitlab_state(state) == expected


@pytest.mark.parametrize(
    "state,expected",
    [
        (STATE_PENDING, "INPROGRESS"),
        (STATE_PASS, "SUCCESSFUL"),
        (STATE_FAIL, "FAILED"),
        (STATE_SKIPPED, "STOPPED"),
    ],
)
def test_bitbucket_states_are_bitbuckets_own_vocabulary(state, expected):
    assert bitbucket_state(state) == expected


@pytest.mark.parametrize(
    "mapper,passing",
    [(github_conclusion, "success"), (gitlab_state, "success"), (bitbucket_state, "SUCCESSFUL")],
)
def test_only_pass_ever_maps_to_a_providers_passing_status(mapper, passing):
    # Bitbucket has no "skipped" and GitLab's nearest word is "canceled"; neither may quietly
    # become a green tick. "We did not look" and "we looked and it is fine" are different answers.
    assert mapper(STATE_PASS) == passing
    for state in (STATE_PENDING, STATE_FAIL, STATE_SKIPPED):
        assert mapper(state) != passing


# ---------------------------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------------------------


def test_a_blank_name_falls_back_to_the_namespaced_default():
    assert normalize_check_name("") == DEFAULT_CHECK_NAME
    assert normalize_check_name(None) == DEFAULT_CHECK_NAME
    assert DEFAULT_CHECK_NAME.startswith("apiome/")


@pytest.mark.parametrize(
    "name", ["apiome/api-change", "breaking_changes", "a", "Team.Checks/v2", "9lives"]
)
def test_a_provider_safe_slug_is_kept_as_it_is(name):
    assert normalize_check_name(f"  {name}  ") == name


@pytest.mark.parametrize(
    "name",
    [
        "/leading-slash",
        "-leading-dash",
        "has space",
        "quotes'",
        "semi;colon",
        "back\\slash",
        "new\nline",
    ],
)
def test_a_name_that_is_not_a_slug_is_refused(name):
    with pytest.raises(ProviderCheckValidationError) as refused:
        normalize_check_name(name)
    assert refused.value.code == CODE_INVALID_NAME


def test_a_name_longer_than_the_column_is_refused():
    with pytest.raises(ProviderCheckValidationError) as refused:
        normalize_check_name("a" * (MAX_NAME_LENGTH + 1))
    assert refused.value.code == CODE_INVALID_NAME
    assert normalize_check_name("a" * MAX_NAME_LENGTH) == "a" * MAX_NAME_LENGTH


# ---------------------------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------------------------


def test_the_fingerprint_depends_on_content_and_not_on_key_order():
    one = request_fingerprint({"method": "POST", "url": "https://x", "body": {"a": 1, "b": 2}})
    two = request_fingerprint({"body": {"b": 2, "a": 1}, "url": "https://x", "method": "POST"})
    assert one == two
    assert one.startswith("sha256:")


def test_any_change_to_the_request_changes_the_fingerprint():
    base = {"method": "POST", "url": "https://x", "body": {"state": "pending"}}
    changed = {"method": "POST", "url": "https://x", "body": {"state": "pass"}}
    assert request_fingerprint(base) != request_fingerprint(changed)


# ---------------------------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "states,expected",
    [
        ([], STATE_SKIPPED),
        ([STATE_PASS], STATE_PASS),
        ([STATE_PASS, STATE_SKIPPED], STATE_PASS),
        ([STATE_SKIPPED, STATE_SKIPPED], STATE_SKIPPED),
        ([STATE_PASS, STATE_PENDING], STATE_PENDING),
        ([STATE_PASS, STATE_PENDING, STATE_FAIL], STATE_FAIL),
        ([STATE_PENDING, STATE_FAIL], STATE_FAIL),
    ],
)
def test_aggregation_is_pessimistic_in_the_order_every_ci_system_uses(states, expected):
    assert summarize_states(states) == expected


def test_aggregation_ignores_a_state_that_is_not_one_of_the_four():
    assert summarize_states(["pass", "nonsense"]) == STATE_PASS
    assert summarize_states(["nonsense"]) == STATE_SKIPPED


# ---------------------------------------------------------------------------------------------
# The request model
# ---------------------------------------------------------------------------------------------


def test_the_request_defaults_to_a_published_pending_check_under_the_default_name():
    request = CheckRunUpsert()
    assert request.name == DEFAULT_CHECK_NAME
    assert request.state == STATE_PENDING
    assert request.publish is True
    assert request.rerun is False


def test_the_request_model_accepts_no_credential_field():
    # The ticket's "browser clients never receive repository tokens" has a mirror: no client can
    # supply one either. extra="forbid" is what enforces it.
    with pytest.raises(Exception):
        CheckRunUpsert(token="ghp_not_allowed")


# ---------------------------------------------------------------------------------------------
# Commits and links
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("sha", ["a" * 40, "A" * 64, "abc1234", "0123456789abcdef"])
def test_a_hexadecimal_object_id_is_accepted_and_lowercased(sha):
    assert normalize_commit_sha(f"  {sha}  ") == sha.lower()


@pytest.mark.parametrize(
    "sha", ["", None, "main", "abc123", "g" * 40, "a" * 65, "../../etc/passwd", "a" * 40 + "?x=1"]
)
def test_anything_that_is_not_a_commit_is_refused(sha):
    # The value reaches a provider URL; a verdict must never be attached to something that is not
    # a commit, and a short id is the only abbreviation allowed.
    with pytest.raises(ProviderCheckValidationError) as refused:
        normalize_commit_sha(sha)
    assert refused.value.code == CODE_INVALID_COMMIT


@pytest.mark.parametrize(
    "url", ["https://app.apiome.dev/x", "http://localhost:3000/checks/1", "HTTPS://X/Y"]
)
def test_an_http_details_link_is_kept(url):
    assert normalize_details_url(f" {url} ") == url


def test_no_details_link_is_allowed():
    assert normalize_details_url("") == ""
    assert normalize_details_url(None) == ""


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "//evil.example.com",
        "app.apiome.dev/x",
    ],
)
def test_a_details_link_that_is_not_http_is_refused(url):
    # A check's link is rendered as a link on a pull request. Providers reject most of these
    # themselves; relying on that would make our safety their implementation detail.
    with pytest.raises(ProviderCheckValidationError) as refused:
        normalize_details_url(url)
    assert refused.value.code == CODE_INVALID_DETAILS_URL


def test_a_details_link_longer_than_the_bound_is_refused():
    with pytest.raises(ProviderCheckValidationError) as refused:
        normalize_details_url("https://x/" + "a" * MAX_DETAILS_URL_LENGTH)
    assert refused.value.code == CODE_INVALID_DETAILS_URL
