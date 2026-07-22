"""Auth-event mapping tests (OLO-1.6, #4191).

Covers the pure ``app.auth_events`` seam: the decision → :class:`AuthEvent` mapping for every
resolution action, the failure-path event-type recovery, and the privacy-preserving
``hash_client_value`` reducer. The DB write/read/prune side is covered in ``test_auth_events_db.py``.
"""

import hashlib

from app import account_resolution as ar
from app import auth_events as ae


# --- hash_client_value -------------------------------------------------------------------------


def test_hash_client_value_is_salted_sha256():
    assert ae.hash_client_value("203.0.113.7", salt="pepper") == hashlib.sha256(
        b"pepper203.0.113.7"
    ).hexdigest()


def test_hash_client_value_trims_and_is_deterministic():
    assert ae.hash_client_value("  Mozilla/5.0  ") == ae.hash_client_value("Mozilla/5.0")


def test_hash_client_value_none_for_empty_or_absent():
    assert ae.hash_client_value(None) is None
    assert ae.hash_client_value("") is None
    assert ae.hash_client_value("   ") is None


def test_hash_client_value_never_returns_the_raw_value():
    raw = "203.0.113.7"
    digest = ae.hash_client_value(raw)
    assert digest is not None and raw not in digest and len(digest) == 64


# --- event_from_decision: success paths --------------------------------------------------------


def _facts(**kw) -> ar.ResolutionInput:
    base = dict(provider="github", provider_user_id="gh-1", email="Ada@Example.com")
    base.update(kw)
    return ar.ResolutionInput(**base)


def test_sign_in_maps_to_sign_in_success():
    facts = _facts()
    ev = ae.event_from_decision(
        ar.ResolutionDecision(action=ar.ACTION_SIGN_IN, user_id="u-1"), facts
    )
    assert ev.event_type == ae.EVENT_SIGN_IN
    assert ev.outcome == ae.OUTCOME_SUCCESS
    assert ev.user_id == "u-1"
    assert ev.provider == "github"
    assert ev.user_label == "ada@example.com"  # canonicalized
    assert ev.error_code is None


def test_signup_maps_to_sign_up_success_and_labels_from_decision_email():
    facts = _facts(email=None)
    ev = ae.event_from_decision(
        ar.ResolutionDecision(action=ar.ACTION_SIGNUP, email="new@example.com"), facts
    )
    assert ev.event_type == ae.EVENT_SIGN_UP
    assert ev.outcome == ae.OUTCOME_SUCCESS
    assert ev.user_label == "new@example.com"


def test_auto_link_maps_to_link_success_with_auto_linked_detail():
    facts = _facts()
    ev = ae.event_from_decision(
        ar.ResolutionDecision(action=ar.ACTION_AUTO_LINK, user_id="u-2"), facts
    )
    assert ev.event_type == ae.EVENT_LINK
    assert ev.outcome == ae.OUTCOME_SUCCESS
    assert ev.user_id == "u-2"
    assert ev.detail == {"auto_linked": True}


def test_explicit_link_maps_to_link_success_without_auto_flag():
    facts = _facts(link_to_user_id="u-session")
    ev = ae.event_from_decision(
        ar.ResolutionDecision(action=ar.ACTION_LINK_TO_SESSION, user_id="u-session"), facts
    )
    assert ev.event_type == ae.EVENT_LINK
    assert ev.outcome == ae.OUTCOME_SUCCESS
    assert ev.user_id == "u-session"
    assert ev.detail is None


# --- event_from_decision: failure paths --------------------------------------------------------


def test_reject_on_normal_sign_in_is_sign_in_failure_with_code():
    facts = _facts()
    ev = ae.event_from_decision(
        ar.ResolutionDecision(action=ar.ACTION_REJECT, code=ar.UNVERIFIED_EMAIL), facts
    )
    assert ev.event_type == ae.EVENT_SIGN_IN
    assert ev.outcome == ae.OUTCOME_FAILURE
    assert ev.error_code == ar.UNVERIFIED_EMAIL
    assert ev.user_id is None


def test_reject_while_linking_is_link_failure_attributed_to_session_user():
    facts = _facts(link_to_user_id="u-session")
    ev = ae.event_from_decision(
        ar.ResolutionDecision(action=ar.ACTION_REJECT, code=ar.IDENTITY_LINKED_ELSEWHERE),
        facts,
    )
    assert ev.event_type == ae.EVENT_LINK
    assert ev.outcome == ae.OUTCOME_FAILURE
    assert ev.user_id == "u-session"
    assert ev.error_code == ar.IDENTITY_LINKED_ELSEWHERE


def test_reject_signup_disabled_is_sign_up_failure():
    facts = _facts()
    ev = ae.event_from_decision(
        ar.ResolutionDecision(action=ar.ACTION_REJECT, code=ar.SIGNUP_DISABLED), facts
    )
    assert ev.event_type == ae.EVENT_SIGN_UP
    assert ev.outcome == ae.OUTCOME_FAILURE
    assert ev.error_code == ar.SIGNUP_DISABLED
    assert ev.user_id is None


# --- invariants --------------------------------------------------------------------------------


def test_every_resolution_action_produces_a_valid_event():
    """Every action the engine can emit maps to a valid, constraint-satisfying event."""
    cases = [
        ar.ResolutionDecision(action=ar.ACTION_SIGN_IN, user_id="u"),
        ar.ResolutionDecision(action=ar.ACTION_SIGNUP, email="x@example.com"),
        ar.ResolutionDecision(action=ar.ACTION_AUTO_LINK, user_id="u"),
        ar.ResolutionDecision(action=ar.ACTION_LINK_TO_SESSION, user_id="u"),
        ar.ResolutionDecision(action=ar.ACTION_REJECT, code=ar.UNVERIFIED_EMAIL),
    ]
    for decision in cases:
        ev = ae.event_from_decision(decision, _facts())
        assert ev.event_type in ae.AUTH_EVENT_TYPES
        assert ev.outcome in ae.AUTH_EVENT_OUTCOMES


def test_default_retention_is_one_year():
    assert ae.DEFAULT_AUTH_EVENT_RETENTION_DAYS == 365
