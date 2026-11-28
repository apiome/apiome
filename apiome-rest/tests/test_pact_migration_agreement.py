"""The agreement check and who-has-moved — PFX-8.17 (#7314).

Pure functions: the questions chosen from a plan, the source's matrix answer read, every cause a
difference can have, and where each pacticipant last published. The job wiring is
``test_pact_migration_job``; the matrix Apiome answers from is ``test_pact_matrix*``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

from app.pact_migration_agreement import (
    MAX_DIFFERENCES,
    Answer,
    Question,
    check_agreement,
    choose_questions,
    explain,
    plan_names,
    source_answer,
    source_rows,
)
from app.pact_migration_moved import moved_report, source_latest
from app.pact_migration_plan import Plan
from app.pact_migration_source import SourceBroker, read_source
from tests.pact_migration_fakes import QUESTIONS, SOURCE, FakeSource

HOST = "broker.example.com"


def _plan() -> Plan:
    plan = Plan()
    with SourceBroker(SOURCE, token="t", transport=FakeSource().transport()) as broker:
        read_source(broker, plan)
    return plan


def _row(consumer_version: str = "2", provider_version: Any = "10", success: Any = True, number: Any = 3) -> Any:
    return ("web", consumer_version, "api", provider_version, success, number)


# ---------------------------------------------------------------------------------------------
# The questions
# ---------------------------------------------------------------------------------------------


def test_questions_are_what_is_deployed_then_the_latest_of_each_pacticipant_per_environment() -> None:
    questions, not_asked = choose_questions(_plan())
    assert [question.label() for question in questions] == [
        "Web 2 → production",
        "Web 3 → production",
        "API 10 → production",
    ]
    assert not_asked == 0


def test_the_query_is_the_one_can_i_deploy_sends() -> None:
    assert Question("Web", "2", "production").query() == (
        "q[][pacticipant]=Web&q[][version]=2&latestby=cvp&environment=production"
    )
    assert Question("Orders UI", "1.0+b", None).query() == (
        "q[][pacticipant]=Orders+UI&q[][version]=1.0%2Bb&latestby=cvp&latest=true"
    )


def test_without_environments_each_latest_version_is_asked_against_the_latest() -> None:
    plan = Plan()
    plan.add("version:Web/1", {"kind": "version", "pacticipant": "Web", "number": "1"})
    plan.add("version:Web/2", {"kind": "version", "pacticipant": "Web", "number": "2"})
    questions, _ = choose_questions(plan)
    assert questions == [Question("Web", "2", None)]


def test_the_limit_is_honoured_and_zero_asks_nothing() -> None:
    assert choose_questions(_plan(), 2)[1] == 1
    assert choose_questions(_plan(), 0) == ([], 3)


def test_an_empty_source_asks_nothing() -> None:
    assert choose_questions(Plan()) == ([], 0)


# ---------------------------------------------------------------------------------------------
# The source's answers
# ---------------------------------------------------------------------------------------------


def test_the_source_answer_is_read_from_its_matrix() -> None:
    source = FakeSource()
    with SourceBroker(SOURCE, token="t", transport=source.transport()) as broker:
        answer = source_answer(broker, Question("Web", "2", "production"))
    assert answer == Answer(deployable=True, rows=frozenset({_row()}))


def test_an_ignored_row_does_not_count() -> None:
    document = QUESTIONS["/matrix?q[][pacticipant]=Web&q[][version]=2&latestby=cvp&environment=production"]
    ignored = {**document["matrix"][0], "ignored": True}
    assert source_rows({"matrix": [ignored]}) == frozenset()


def test_a_refused_or_strange_answer_is_an_error_not_a_verdict() -> None:
    source = FakeSource({"/matrix": 400})
    with SourceBroker(SOURCE, token="t", transport=source.transport()) as broker:
        assert "HTTP 400" in (source_answer(broker, Question("Web", "2")).error or "")
    strange = FakeSource({"/matrix": {"matrix": []}})
    with SourceBroker(SOURCE, token="t", transport=strange.transport()) as broker:
        assert source_answer(broker, Question("Web", "2")).error == f"{HOST}'s answer has no summary.deployable"


def test_an_unknown_verdict_is_none() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"summary": {"deployable": None}, "matrix": []})

    with SourceBroker(SOURCE, token="t", transport=httpx.MockTransport(handle)) as broker:
        assert source_answer(broker, Question("Web", "2")) == Answer(deployable=None)


# ---------------------------------------------------------------------------------------------
# Every cause of a difference
# ---------------------------------------------------------------------------------------------

Q = Question("Web", "2", "production")
NAMES = {"web": "Web", "api": "API"}


def _explain(source: Answer, apiome: Answer, why: Dict[str, str] = {}) -> str:  # noqa: B006 — read only
    return explain(Q, source, apiome, host=HOST, left_behind=why, names=NAMES)


def test_the_cause_names_a_result_not_copied_and_why() -> None:
    source = Answer(True, frozenset({_row()}))
    apiome = Answer(None, frozenset({_row(provider_version=None, success=None, number=None)}))
    assert _explain(source, apiome) == "the verification result of Web 2 by API 10 was not copied"
    why = {"verification:API/Web/2/3": "results were not chosen"}
    assert _explain(source, apiome, why).endswith("was not copied: results were not chosen")


def test_the_cause_names_a_pact_not_copied() -> None:
    source = Answer(True, frozenset({_row()}))
    apiome = Answer(False, frozenset({("web", "2", "ledger", None, None, None)}))
    assert _explain(source, apiome, {"pact:API/Web/2": "kept Apiome's"}) == (
        "the pact Web 2 → API was not copied: kept Apiome's"
    )


def test_the_cause_names_a_version_not_copied() -> None:
    source = Answer(True, frozenset({_row()}))
    why = {"version:Web/2": "clean-up would remove it"}
    assert _explain(source, Answer(False), why) == "Web 2 was not copied: clean-up would remove it"


def test_the_cause_names_a_result_only_apiome_has() -> None:
    source = Answer(None, frozenset({_row(provider_version=None, success=None, number=None)}))
    apiome = Answer(True, frozenset({_row(provider_version="11", number=1)}))
    assert _explain(source, apiome) == (
        f"Apiome has a result {HOST} does not: API 11 verified Web 2 (published to Apiome directly)"
    )


def test_the_cause_names_a_question_either_side_could_not_answer() -> None:
    assert _explain(Answer(error="HTTP 400"), Answer(True)).startswith(f"{HOST} could not answer it")
    assert _explain(Answer(True), Answer(error="no such version")) == "Apiome could not answer it (no such version)"


def test_a_difference_with_the_same_results_points_at_the_environment() -> None:
    source = Answer(True, frozenset({_row()}))
    apiome = Answer(None, frozenset({_row(), ("web", "2", "ledger", None, None, None)}))
    assert _explain(source, apiome) == "what is deployed to or released in production differs between the two"
    unscoped = explain(Question("Web", "2"), source, apiome, host=HOST)
    assert unscoped == f"the same rows were read differently ({HOST}: 1 row(s), Apiome: 2)"


def test_the_check_counts_agreement_and_lists_each_difference() -> None:
    answers = {"2": (Answer(True), Answer(True)), "3": (Answer(True, frozenset({_row("3")})), Answer(None))}
    report = check_agreement(
        [Question("Web", "2"), Question("Web", "3")],
        lambda q: answers[q.version][0],
        lambda q: answers[q.version][1],
        host=HOST,
        not_asked=4,
        names=NAMES,
        checked_at="2026-11-27T14:21:07Z",
    )
    assert report["asked"] == 2 and report["agree"] == 1 and report["not_asked"] == 4
    assert report["differences"] == [
        {
            "question": "Web 3 → latest",
            "pacticipant": "Web",
            "version": "3",
            "environment": None,
            "source": "yes",
            "apiome": "unknown",
            "cause": "the pact Web 3 → API was not copied",
        }
    ]


def test_more_differences_than_are_kept_are_counted_not_dropped() -> None:
    questions = [Question("Web", str(n)) for n in range(MAX_DIFFERENCES + 5)]
    report = check_agreement(questions, lambda _q: Answer(True), lambda _q: Answer(False), host=HOST)
    assert len(report["differences"]) == MAX_DIFFERENCES and report["differences_dropped"] == 5
    assert report["agree"] == 0


def test_two_failures_to_answer_never_agree() -> None:
    report = check_agreement([Q], lambda _q: Answer(error="x"), lambda _q: Answer(error="y"), host=HOST)
    assert report["agree"] == 0 and report["differences"][0]["source"] == "no answer"


def test_plan_names_spell_each_handle_as_the_source_does() -> None:
    assert plan_names(_plan()) == {"web": "Web", "api": "API"}


# ---------------------------------------------------------------------------------------------
# Who has moved
# ---------------------------------------------------------------------------------------------


def _at(day: int, month: int = 3, year: int = 2025) -> datetime:
    return datetime(year, month, day, 9, 0, tzinfo=timezone.utc)


def test_the_source_latest_is_the_newest_pact_or_result_of_each() -> None:
    assert source_latest(_plan()) == {"Web": _at(3), "API": _at(2)}


def test_moved_means_published_to_apiome_after_the_last_publication_at_the_source() -> None:
    report = moved_report(
        {"Web": _at(3), "API": _at(2), "Ledger": None, "Cart": _at(1)},
        {"Web": _at(3), "API": _at(27, 11, 2026), "Ledger": None},
        checked_at="now",
    )
    assert report["total"] == 4 and report["moved"] == 1 and report["dropped"] == 0
    rows: List[Dict[str, Any]] = report["pacticipants"]
    assert [(row["name"], row["last"]) for row in rows] == [
        ("Cart", "source"),  # Apiome has no such pacticipant yet
        ("Web", "source"),  # its newest in Apiome is the copied pact
        ("API", "apiome"),
        ("Ledger", "none"),
    ]


def test_a_pacticipant_new_to_apiome_that_published_there_has_moved() -> None:
    report = moved_report({"Web": None}, {"Web": _at(1)})
    assert report["pacticipants"][0]["last"] == "apiome"
