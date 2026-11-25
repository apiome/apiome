"""The pure half of the matrix and can-i-deploy — PFX-1.6 (#6919).

Reading a query as a Pact Broker does, describing selectors in its words, collapsing and ignoring
rows, and the verdict: golden answers for the Pact Broker's documented can-i-deploy scenarios
(pass, fail, unknown, pending, ignored pacticipant, environment with no deployments), without a
database. ``test_pact_matrix_db`` asks the same questions of a live one.
"""

from __future__ import annotations

from typing import Any, List, Optional
from urllib.parse import urlencode

import pytest

from app.pact_matrix import (
    CODE_MATRIX_INVALID,
    IGNORED,
    INFERRED,
    SPECIFIED,
    Integration,
    MatrixOptions,
    MatrixResult,
    MatrixRow,
    ResolvedSelector,
    UnresolvedSelector,
    apply_latestby,
    apply_success_filter,
    deployment_verdict,
    expand_unverified,
    parse_can_i_deploy_query,
    parse_matrix_query,
    resolve_selector,
    row_reason,
    sort_rows,
    split_ignored,
)
from app.pact_publication import PactPublicationError

FOO = {"id": "foo-id", "slug": "foo", "name": "Foo", "main_branch": "main"}
BAR = {"id": "bar-id", "slug": "bar", "name": "Bar", "main_branch": None}
PRODUCTION = MatrixOptions(latestby="cvpv", environment_name="production")


def _query(*pairs: Any) -> str:
    return urlencode(list(pairs))


def _row(
    consumer_version: str = "1",
    provider_version: Optional[str] = "4",
    success: Optional[bool] = True,
    **overrides: Any,
) -> MatrixRow:
    """Foo ``consumer_version`` → Bar ``provider_version``; version ids are ``foo-<n>`` / ``bar-<n>``."""
    verified = provider_version is not None
    values = {
        "consumer_id": "foo-id",
        "consumer_slug": "foo",
        "consumer_name": "Foo",
        "consumer_version_id": f"foo-{consumer_version}",
        "consumer_version_number": consumer_version,
        "consumer_version_seq": int(consumer_version),
        "provider_id": "bar-id",
        "provider_slug": "bar",
        "provider_name": "Bar",
        "pact_sha": "a" * 64,
        "provider_version_id": f"bar-{provider_version}" if verified else None,
        "provider_version_number": provider_version,
        "provider_version_seq": int(provider_version) if verified else None,
        "verification_number": 1 if verified else None,
        "verification_seq": 1 if verified else None,
        "success": success if verified else None,
    }
    values.update(overrides)
    return MatrixRow(**values)


def _foo(version: str = "1", **flags: Any) -> ResolvedSelector:
    """The selector ``--pacticipant Foo --version <version>``."""
    original = UnresolvedSelector(pacticipant_name="Foo", version_number=version)
    return resolve_selector(original, SPECIFIED, FOO, [{"id": f"foo-{version}", "number": version}], **flags)[0]


def _bar_in_production(*versions: str, ignore: List[ResolvedSelector] = ()) -> List[ResolvedSelector]:
    """The inferred selector(s) for Bar in production."""
    original = UnresolvedSelector(pacticipant_name="Bar", environment_name="production")
    found = [{"id": f"bar-{version}", "number": version} for version in versions]
    return resolve_selector(original, INFERRED, BAR, found, ignore)


FOO_NEEDS_BAR = Integration("foo-id", "Foo", "bar-id", "Bar", required=True)


def _deploy_foo(rows: List[MatrixRow], bar: List[ResolvedSelector], **extra: Any) -> MatrixResult:
    return MatrixResult(
        considered_rows=rows, selectors=[_foo()] + bar, integrations=[FOO_NEEDS_BAR], options=PRODUCTION, **extra
    )


# ---------------------------------------------------------------------------------------------
# Reading a query
# ---------------------------------------------------------------------------------------------


def test_the_cli_query_is_read_as_the_broker_reads_it() -> None:
    # pact-broker can-i-deploy --pacticipant Foo --version 1 --to-environment production --ignore Bar
    selectors, options = parse_matrix_query(
        _query(
            ("q[][pacticipant]", "Foo"),
            ("q[][version]", "1"),
            ("latestby", "cvpv"),
            ("environment", "production"),
            ("ignore[][pacticipant]", "Bar"),
        )
    )
    assert selectors == [UnresolvedSelector(pacticipant_name="Foo", version_number="1")]
    assert options == MatrixOptions(
        latestby="cvpv", environment_name="production", ignore_selectors=(UnresolvedSelector(pacticipant_name="Bar"),)
    )
    assert options.infers_selectors and options.limit == 100


def test_a_repeated_key_starts_the_next_selector() -> None:
    selectors, options = parse_matrix_query(
        _query(
            ("q[][pacticipant]", "Foo"),
            ("q[][latest]", "true"),
            ("q[][tag]", "prod"),
            ("q[][pacticipant]", "Bar"),
            ("q[][branch]", "main"),
            ("q[][pacticipant]", "Baz"),
            ("q[][mainBranch]", "true"),
            ("q[][environment]", "test"),
            ("success[]", "true"),
            ("success[]", ""),
            ("limit", "5"),
            ("latest", "true"),
            ("tag", "prod"),
        )
    )
    assert selectors == [
        UnresolvedSelector(pacticipant_name="Foo", latest=True, tag="prod"),
        UnresolvedSelector(pacticipant_name="Bar", branch="main"),
        UnresolvedSelector(pacticipant_name="Baz", main_branch=True, environment_name="test"),
    ]
    assert (options.success, options.limit, options.latest, options.tag) == ((True, None), 5, True, "prod")
    assert not options.latestby
    assert selectors[1].only_pacticipant_name is False
    # Explicit indexes name their selector.
    indexed, _ = parse_matrix_query("q[0][pacticipant]=Foo&q[1][pacticipant]=Bar&q[0][version]=1")
    assert [(s.pacticipant_name, s.version_number) for s in indexed] == [("Foo", "1"), ("Bar", None)]


@pytest.mark.parametrize(
    "query, message, pointer",
    [
        ("", "Please provide 1 or more version selectors.", "/q"),
        ("q[][version]=1", "Please specify the pacticipant name", "/q/0/pacticipant"),
        (
            "q[][pacticipant]=Foo&q[][version]=1&q[][latest]=true",
            "A version number and latest flag cannot both be specified for Foo",
            "/q/0",
        ),
        (
            "q[][pacticipant]=Foo&ignore[][version]=1",
            "Please specify the pacticipant name to ignore",
            "/ignore/0/pacticipant",
        ),
        (
            "q[][pacticipant]=Foo&tag=prod&environment=production",
            "Cannot specify more than one of tag, environment and mainBranch.",
            "/environment",
        ),
        (
            "q[][pacticipant]=Foo&latest=true&environment=production",
            "Cannot specify both latest=true and an environment.",
            "/environment",
        ),
        ("q[][pacticipant]=Foo&latestby=nope", "latestby must be one of cvp, cvpv, cp.", "/latestby"),
        ("q[][pacticipant]=Foo&limit=0", "The limit must be 1 or greater.", "/limit"),
        ("q[][pacticipant]=Foo&limit=abc", "The limit must be 1 or greater.", "/limit"),
        ("q[][pacticipant]=Foo&limit=1001", "The limit must not exceed 1000.", "/limit"),
    ],
)
def test_a_malformed_matrix_query_is_refused(query: str, message: str, pointer: str) -> None:
    with pytest.raises(PactPublicationError) as refused:
        parse_matrix_query(query)
    assert (refused.value.code, str(refused.value), refused.value.pointer) == (CODE_MATRIX_INVALID, message, pointer)


def test_can_i_deploy_to_an_environment_or_a_tag() -> None:
    selectors, options = parse_can_i_deploy_query("pacticipant=Foo&version=1&toEnvironment=production&ignore=Bar")
    assert selectors == [UnresolvedSelector(pacticipant_name="Foo", version_number="1")]
    assert options == MatrixOptions(
        latestby="cvpv", environment_name="production", ignore_selectors=(UnresolvedSelector(pacticipant_name="Bar"),)
    )
    # The Pact Broker's own parameter name, and its nested ignore forms.
    _, broker = parse_can_i_deploy_query(
        "pacticipant=Foo&version=1&environment=production&ignore[]=Bar&ignore[][pacticipant]=Baz&ignore[][version]=3"
    )
    assert broker.environment_name == "production"
    assert broker.ignore_selectors == (
        UnresolvedSelector(pacticipant_name="Bar"),
        UnresolvedSelector(pacticipant_name="Baz", version_number="3"),
    )
    _, tagged = parse_can_i_deploy_query("pacticipant=Foo&version=1&to=prod")
    assert (tagged.latestby, tagged.latest, tagged.tag, tagged.environment_name) == ("cvp", True, "prod", None)


@pytest.mark.parametrize(
    "query, message",
    [
        ("version=1&toEnvironment=production", "pacticipant is missing"),
        ("pacticipant=Foo&toEnvironment=production", "version is missing"),
        ("pacticipant=Foo&version=1", "Must specify either an environment or a 'to' tag."),
        (
            "pacticipant=Foo&version=1&to=prod&toEnvironment=production",
            "Cannot specify both a 'to' tag and an environment.",
        ),
    ],
)
def test_a_malformed_can_i_deploy_query_is_refused(query: str, message: str) -> None:
    with pytest.raises(PactPublicationError) as refused:
        parse_can_i_deploy_query(query)
    assert (refused.value.code, str(refused.value)) == (CODE_MATRIX_INVALID, message)


# ---------------------------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------------------------


def _describe(original: UnresolvedSelector, versions: Optional[List[str]], pacticipant: Any = FOO) -> List[str]:
    found = None if versions is None else [{"id": f"foo-{v}", "number": v} for v in versions]
    return [s.description for s in resolve_selector(original, SPECIFIED, pacticipant, found)]


@pytest.mark.parametrize(
    "selector, versions, expected",
    [
        ({"version_number": "1"}, ["1"], ["version 1 of Foo"]),
        ({"version_number": "9"}, [], ["version 9 of Foo (no such version exists)"]),
        ({}, None, ["any version of Foo"]),
        ({"latest": True}, ["3"], ["the latest version of Foo (3)"]),
        ({"latest": True}, [], ["the latest version of Foo (no such version exists)"]),
        ({"latest": True, "tag": "prod"}, ["3"], ["the latest version of Foo with tag prod (3)"]),
        ({"latest": True, "tag": "prod"}, [], ["the latest version of Foo with tag prod (no such version exists)"]),
        ({"tag": "prod"}, ["3", "2"], ["a version of Foo with tag prod (3)", "a version of Foo with tag prod (2)"]),
        ({"tag": "prod"}, [], ["a version of Foo with tag prod (no such version exists)"]),
        ({"latest": True, "branch": "feat"}, ["3"], ["the latest version of Foo from branch feat (3)"]),
        (
            {"latest": True, "branch": "feat"},
            [],
            ["the latest version of Foo from branch feat (no such version exists)"],
        ),
        ({"branch": "feat"}, ["3"], ["the version of Foo from branch feat (3)"]),
        (
            {"branch": "feat"},
            ["3", "2"],
            ["one of the versions of Foo from branch feat (3)", "one of the versions of Foo from branch feat (2)"],
        ),
        ({"branch": "feat"}, [], ["a version of Foo from branch feat (no such version exists)"]),
        ({"latest": True, "main_branch": True}, ["3"], ["the latest version of Foo from branch main (3)"]),
        (
            {"latest": True, "main_branch": True},
            [],
            ["the latest version of Foo from the main branch (no versions exist for this branch)"],
        ),
        ({"main_branch": True}, [], ["any version of Foo from the main branch (no versions exist for this branch)"]),
        ({"environment_name": "production"}, ["3"], ["the version of Foo currently in production (3)"]),
        (
            {"environment_name": "production"},
            ["3", "2"],
            [
                "one of the versions of Foo currently in production (3)",
                "one of the versions of Foo currently in production (2)",
            ],
        ),
        (
            {"environment_name": "production"},
            [],
            [
                "a version of Foo currently in production "
                "(no version is currently recorded as deployed/released in this environment)"
            ],
        ),
    ],
)
def test_selectors_are_described_in_the_brokers_words(selector: Any, versions: Any, expected: List[str]) -> None:
    assert _describe(UnresolvedSelector(pacticipant_name="Foo", **selector), versions) == expected


def test_a_pacticipant_that_does_not_exist_is_described_as_such() -> None:
    (missing,) = resolve_selector(UnresolvedSelector(pacticipant_name="Nope"), IGNORED, None, None)
    assert missing.description == "any version of Nope (no such pacticipant exists)"
    assert missing.pacticipant_missing and not missing.version_missing


@pytest.mark.parametrize(
    "selector, expected",
    [
        ({"version_number": "9"}, "No pacts or verifications have been published for version 9 of Foo"),
        ({"tag": "prod", "latest": True}, "No version with tag prod exists for Foo"),
        ({"branch": "feat"}, "No version of Foo from branch feat exists"),
        ({"main_branch": True}, "No version of Foo from the main branch exists"),
        (
            {"environment_name": "production"},
            "No version of Foo is currently recorded as deployed or released in environment production",
        ),
    ],
)
def test_a_missing_version_has_its_own_error(selector: Any, expected: str) -> None:
    (missing,) = resolve_selector(UnresolvedSelector(pacticipant_name="Foo", **selector), SPECIFIED, FOO, [])
    assert missing.version_missing
    assert missing.version_does_not_exist_description == expected


def test_ignore_selectors_mark_what_they_cover() -> None:
    (whole,) = resolve_selector(UnresolvedSelector(pacticipant_name="Bar"), IGNORED, BAR, None)
    one = resolve_selector(
        UnresolvedSelector(pacticipant_name="Bar", version_number="4"), IGNORED, BAR, [{"id": "bar-4", "number": "4"}]
    )
    assert [s.ignore for s in _bar_in_production("4", "5", ignore=[whole])] == [True, True]
    assert [s.ignore for s in _bar_in_production("4", "5", ignore=one)] == [True, False]
    assert _bar_in_production(ignore=[whole])[0].ignore is True
    assert _bar_in_production(ignore=one)[0].ignore is False
    assert _foo(ignore_selectors=[whole]).ignore is False


# ---------------------------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------------------------


def test_latestby_keeps_the_latest_result_of_each_group() -> None:
    rows = [_row("1", "4"), _row("1", "5", False), _row("2", "5"), _row("2", None), _row("3", None)]
    assert apply_latestby(rows, None) == rows
    assert apply_latestby(rows, "cvpv") == rows
    cvp = apply_latestby(rows, "cvp")
    assert [(r.consumer_version_number, r.provider_version_number) for r in cvp] == [
        ("1", "5"),
        ("2", "5"),
        ("3", None),
    ]
    cp = apply_latestby(rows, "cp")
    assert [(r.consumer_version_number, r.provider_version_number) for r in cp] == [("1", "5")]
    # Among results of one provider version, the later one wins.
    again = [_row("1", "4", False, verification_seq=1), _row("1", "4", True, verification_seq=2)]
    assert apply_latestby(again, "cvpv") == [again[1]]


def test_rows_are_filtered_ignored_sorted_and_explained() -> None:
    rows = [_row("1", "4", True), _row("2", "4", False), _row("3", None)]
    assert apply_success_filter(rows, None) == rows
    assert apply_success_filter(rows, (False, None)) == rows[1:]
    assert apply_success_filter(rows, (True,)) == rows[:1]

    (whole,) = resolve_selector(UnresolvedSelector(pacticipant_name="Bar"), IGNORED, BAR, None)
    assert split_ignored(rows, [whole]) == ([], rows)
    one = resolve_selector(
        UnresolvedSelector(pacticipant_name="Foo", version_number="2"), IGNORED, FOO, [{"id": "foo-2", "number": "2"}]
    )
    assert split_ignored(rows, one) == ([rows[0], rows[2]], [rows[1]])
    assert split_ignored(rows, []) == (rows, [])

    other = _row("1", "4", consumer_name="Alpha", consumer_id="alpha-id")
    ordered = sort_rows(rows + [other])
    assert [(r.consumer_name, r.consumer_version_number) for r in ordered] == [
        ("Alpha", "1"),
        ("Foo", "3"),
        ("Foo", "2"),
        ("Foo", "1"),
    ]

    assert row_reason(rows[0]) == {"code": "verified", "text": "verified"}
    assert row_reason(rows[1]) == {"code": "verification-failed", "text": "verification failed"}
    assert row_reason(rows[2]) == {"code": "no-verification-result", "text": "no verification result"}
    assert row_reason(_row("1", "4", False, pact_pending=True)) == {"code": "pact-pending", "text": "pact is pending"}
    # A pending pact that passed is simply verified.
    assert row_reason(_row("1", "4", True, pact_pending=True))["code"] == "verified"


# ---------------------------------------------------------------------------------------------
# The verdict: the Pact Broker's documented scenarios
# ---------------------------------------------------------------------------------------------


def test_pass() -> None:
    verdict = deployment_verdict(_deploy_foo([_row("1", "4", True)], _bar_in_production("4")))
    assert verdict.deployable is True
    assert verdict.reason == "All required verification results are published and successful"
    assert [(r.type, r.code) for r in verdict.reasons] == [("success", "verified")]
    assert verdict.counts == {"success": 1, "failed": 0, "unknown": 0}
    assert not verdict.unknown


def test_fail() -> None:
    verdict = deployment_verdict(_deploy_foo([_row("1", "4", False)], _bar_in_production("4")))
    assert verdict.deployable is False
    assert verdict.reason == (
        "The verification for the pact between version 1 of Foo and "
        "the version of Bar currently in production (4) failed"
    )
    assert [(r.type, r.code) for r in verdict.reasons] == [("error", "verification-failed")]
    assert verdict.counts == {"success": 0, "failed": 1, "unknown": 0}


def test_a_bidirectional_result_counts_exactly_as_a_native_one() -> None:
    # PFX-2.3: same verdict, same codes and counts; the wording names the comparison.
    passed = deployment_verdict(
        _deploy_foo([_row("1", "4", True, verification_kind="bidirectional")], _bar_in_production("4"))
    )
    native = deployment_verdict(_deploy_foo([_row("1", "4", True)], _bar_in_production("4")))
    assert (passed.deployable, passed.counts, passed.reasons) == (native.deployable, native.counts, native.reasons)

    failed = deployment_verdict(
        _deploy_foo([_row("1", "4", False, verification_kind="bidirectional")], _bar_in_production("4"))
    )
    assert failed.deployable is False
    assert failed.reason == (
        "The bi-directional comparison of the pact between version 1 of Foo and "
        "the version of Bar currently in production (4) with its provider contract failed"
    )
    assert [(r.type, r.code) for r in failed.reasons] == [("error", "verification-failed")]
    assert failed.counts == {"success": 0, "failed": 1, "unknown": 0}


def test_a_bidirectional_row_says_how_it_was_verified() -> None:
    assert row_reason(_row(verification_kind="bidirectional")) == {
        "code": "verified",
        "text": "verified by bi-directional comparison",
    }
    assert row_reason(_row(success=False, verification_kind="bidirectional")) == {
        "code": "verification-failed",
        "text": "bi-directional comparison failed",
    }
    assert row_reason(_row(provider_version=None, success=None, verification_kind=None))["code"] == (
        "no-verification-result"
    )
    assert _row(verification_kind="bidirectional").bidirectional
    assert not _row(verification_kind="native").bidirectional


def test_unknown() -> None:
    verdict = deployment_verdict(_deploy_foo([_row("1", None)], _bar_in_production("4")))
    assert verdict.deployable is None and verdict.unknown
    assert verdict.reason == (
        "There is no verified pact between version 1 of Foo and the version of Bar currently in production (4)"
    )
    assert [(r.type, r.code) for r in verdict.reasons] == [("error", "no-verification-result")]
    assert verdict.counts == {"success": 0, "failed": 0, "unknown": 1}


def test_every_provider_version_in_the_environment_is_checked() -> None:
    # Two versions of Bar are live in production. The join only returns the one that verified.
    bar = _bar_in_production("4", "5")
    read = [_row("1", "4", True)]
    rows = expand_unverified(read, [_foo()] + bar)
    assert [(r.provider_version_number, r.success, r.verification_number) for r in rows] == [
        ("4", True, 1),
        ("5", None, None),
    ]
    verdict = deployment_verdict(_deploy_foo(rows, bar))
    assert verdict.deployable is None
    assert verdict.reason == (
        "There is no verified pact between version 1 of Foo and one of the versions of Bar currently in production (5)"
    )
    assert verdict.counts == {"success": 1, "failed": 0, "unknown": 1}
    # Neither verified: the version-less row becomes one row per version.
    neither = expand_unverified([_row("1", None)], [_foo()] + bar)
    assert [(r.provider_version_number, r.success) for r in neither] == [("4", None), ("5", None)]
    # Unknown outranks failed, and both are explained.
    mixed = deployment_verdict(_deploy_foo(expand_unverified([_row("1", "4", False)], [_foo()] + bar), bar))
    assert mixed.deployable is None
    assert mixed.reason.splitlines() == [
        "The verification for the pact between version 1 of Foo and "
        "one of the versions of Bar currently in production (4) failed",
        "There is no verified pact between version 1 of Foo and one of the versions of Bar currently in production (5)",
    ]
    assert mixed.counts == {"success": 0, "failed": 1, "unknown": 1}
    # One version in question: rows are left exactly as read.
    single = [_row("1", None), _row("2", "4")]
    assert expand_unverified(single, [_foo()] + _bar_in_production("4")) == single


def test_pending_does_not_soften_the_verdict() -> None:
    verdict = deployment_verdict(_deploy_foo([_row("1", "4", False, pact_pending=True)], _bar_in_production("4")))
    assert verdict.deployable is False
    assert [(r.type, r.code) for r in verdict.reasons] == [("error", "pact-pending")]
    assert verdict.reason.endswith("failed")
    assert verdict.counts["failed"] == 1


def test_an_ignored_pacticipant() -> None:
    (ignore,) = resolve_selector(UnresolvedSelector(pacticipant_name="Bar"), IGNORED, BAR, None)
    result = MatrixResult(
        considered_rows=[],
        ignored_rows=[_row("1", "4", False)],
        selectors=[_foo(ignore_selectors=[ignore])] + _bar_in_production("4", ignore=[ignore]),
        ignore_selectors=[ignore],
        integrations=[FOO_NEEDS_BAR],
        options=PRODUCTION,
    )
    verdict = deployment_verdict(result)
    assert verdict.deployable is True
    assert verdict.reason == "There are no missing dependencies"
    assert verdict.counts == {"success": 0, "failed": 0, "unknown": 0, "ignored": 1}


def test_an_ignore_selector_that_matches_nothing_is_a_warning() -> None:
    nope = resolve_selector(UnresolvedSelector(pacticipant_name="Nope"), IGNORED, None, None)
    result = _deploy_foo([_row("1", "4", True)], _bar_in_production("4"), ignore_selectors=nope)
    verdict = deployment_verdict(result)
    assert verdict.deployable is True
    assert [(r.type, r.code, r.text) for r in verdict.reasons][0] == (
        "warning",
        "cannot-ignore",
        "WARN: Cannot ignore any version of Nope (no such pacticipant exists)",
    )
    assert verdict.counts["ignored"] == 0


def test_environment_with_no_deployments() -> None:
    # A consumer cannot go first: its provider is not there.
    consumer = deployment_verdict(_deploy_foo([_row("1", None)], _bar_in_production()))
    assert consumer.deployable is None
    assert consumer.reason == (
        "There is no verified pact between version 1 of Foo and a version of Bar currently in production "
        "(no version is currently recorded as deployed/released in this environment)"
    )
    # A provider can: it does not need its consumers.
    bar = resolve_selector(
        UnresolvedSelector(pacticipant_name="Bar", version_number="4"), SPECIFIED, BAR, [{"id": "bar-4", "number": "4"}]
    )
    foo = resolve_selector(UnresolvedSelector(pacticipant_name="Foo", environment_name="production"), INFERRED, FOO, [])
    provider = deployment_verdict(
        MatrixResult(
            selectors=bar + foo,
            integrations=[Integration("foo-id", "Foo", "bar-id", "Bar", required=False)],
            options=PRODUCTION,
        )
    )
    assert provider.deployable is True
    assert provider.reason == "There are no missing dependencies"
    assert provider.counts == {"success": 0, "failed": 0, "unknown": 0}


def test_a_required_integration_without_a_row_is_unknown() -> None:
    verdict = deployment_verdict(_deploy_foo([], _bar_in_production("4")))
    assert verdict.deployable is None
    assert verdict.reason == (
        "There is no verified pact between version 1 of Foo and the version of Bar currently in production (4)"
    )
    assert verdict.counts == {"success": 0, "failed": 0, "unknown": 1}


def test_a_named_version_that_does_not_exist_is_a_no() -> None:
    missing = resolve_selector(UnresolvedSelector(pacticipant_name="Foo", version_number="9"), SPECIFIED, FOO, [])
    verdict = deployment_verdict(MatrixResult(selectors=missing, options=PRODUCTION))
    assert verdict.deployable is False
    assert verdict.reason == "No pacts or verifications have been published for version 9 of Foo"
    assert [(r.type, r.code) for r in verdict.reasons] == [("error", "version-not-found")]
    # ... unless that pacticipant is ignored.
    (ignore,) = resolve_selector(UnresolvedSelector(pacticipant_name="Foo"), IGNORED, FOO, None)
    ignored = resolve_selector(
        UnresolvedSelector(pacticipant_name="Foo", version_number="9"), SPECIFIED, FOO, [], [ignore]
    )
    assert deployment_verdict(MatrixResult(selectors=ignored, ignore_selectors=[ignore], options=PRODUCTION)).deployable


def test_an_environment_that_requires_a_contract() -> None:
    foo = _foo()
    verdict = deployment_verdict(MatrixResult(selectors=[foo], options=PRODUCTION, uncontracted=[foo]))
    assert verdict.deployable is False
    assert verdict.reason == (
        "No pact has been published for version 1 of Foo, and environment production requires a contract"
    )
    assert [(r.type, r.code) for r in verdict.reasons] == [("error", "no-pact")]


def test_queries_that_cannot_be_relied_on_carry_the_brokers_warnings() -> None:
    # One selector and no destination.
    alone = deployment_verdict(MatrixResult(considered_rows=[_row()], selectors=[_foo()], options=MatrixOptions()))
    assert [r.code for r in alone.reasons] == ["no-environment-specified", "verified"]
    assert alone.reasons[0].text.startswith("WARN: It is recommended to specify the environment")
    # The row's other side has no selector: it is described from the row.
    failed = deployment_verdict(
        MatrixResult(considered_rows=[_row("1", "4", False)], selectors=[_foo()], options=MatrixOptions())
    )
    assert (
        failed.reasons[-1].text == "The verification for the pact between version 1 of Foo and version 4 of Bar failed"
    )
    # A tag instead of a version number.
    tagged = resolve_selector(
        UnresolvedSelector(pacticipant_name="Foo", latest=True, tag="dev"),
        SPECIFIED,
        FOO,
        [{"id": "foo-1", "number": "1"}],
    )
    racy = deployment_verdict(
        MatrixResult(considered_rows=[_row()], selectors=tagged + _bar_in_production("4"), options=PRODUCTION)
    )
    assert [r.code for r in racy.reasons] == ["no-version-specified", "verified"]
    # Name-only selectors are a matrix view, not a deployment: no warning.
    names = [
        resolve_selector(UnresolvedSelector(pacticipant_name=p["name"]), SPECIFIED, p, None)[0] for p in (FOO, BAR)
    ]
    view = deployment_verdict(MatrixResult(considered_rows=[_row()], selectors=names, options=MatrixOptions()))
    assert [r.code for r in view.reasons] == ["verified"]


def test_repeated_reasons_are_said_once() -> None:
    rows = [_row("1", None), _row("1", None, pact_sha="b" * 64)]
    verdict = deployment_verdict(_deploy_foo(rows, _bar_in_production("4")))
    assert len(verdict.reasons) == 1
    assert verdict.counts["unknown"] == 2
