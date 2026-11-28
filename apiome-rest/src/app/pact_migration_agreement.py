"""The agreement check of a migration's **Switch over** step — PFX-8.17 (#7314).

Nothing else proves the migrated workspace answers like the broker it came from, so after a copy
the job asks both of them the same can-i-deploy questions and compares the verdicts:

* **The questions** (:func:`choose_questions`) come from what the source holds: every version it has
  deployed or released, then the latest version of each pacticipant, each asked about every
  environment the source has (or, when it has none, about the latest version of everything else —
  ``can-i-deploy --latest``). At most ``limit`` are asked; how many were left out is said.
* **The same query on both sides.** Each question is the matrix query ``pact-broker can-i-deploy``
  sends (``q[][pacticipant]``, ``q[][version]``, ``latestby=cvp`` and the destination). The source
  answers over HTTP (:func:`source_answer`); Apiome answers in-process through the matrix the Pact
  Broker routes use (:func:`apiome_answer`).
* **Every difference has a cause** (:func:`explain`): the version or the pact or the verification
  result that was not copied — with the reason the run gave when it left it behind — a result only
  Apiome has, a question the old broker could not answer (a selector it does not support), or rows
  that differ in some other way. A question one side could not answer is a difference, never
  dropped.

The answers are read, never written: asking changes nothing on either side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode

from .pact_migration_plan import Plan
from .pact_migration_source import SourceBroker, SourceError
from .pacticipant import PacticipantValidationError, slugify_pacticipant_name

__all__ = [
    "DEFAULT_QUESTIONS",
    "MAX_DIFFERENCES",
    "MAX_QUESTIONS",
    "Answer",
    "Question",
    "RowFact",
    "apiome_answer",
    "check_agreement",
    "choose_questions",
    "explain",
    "source_answer",
]

#: Questions asked unless the run says otherwise (the wizard's "40 can-i-deploy questions").
DEFAULT_QUESTIONS = 40
#: The most a run may ask: each is a request to the source.
MAX_QUESTIONS = 200
#: Differences kept on the run; more are counted.
MAX_DIFFERENCES = 100

_RESULT_NUMBER = re.compile(r"/verification-results/(\d+)")


@dataclass(frozen=True)
class Question:
    """One can-i-deploy question.

    Attributes:
        pacticipant: What would be deployed.
        version: Its version number.
        environment: Where to, or ``None`` for "with the latest of everything else".
    """

    pacticipant: str
    version: str
    environment: Optional[str] = None

    def query(self) -> str:
        """The matrix query string ``pact-broker can-i-deploy`` sends for this question."""
        pairs = [("q[][pacticipant]", self.pacticipant), ("q[][version]", self.version), ("latestby", "cvp")]
        pairs.append(("environment", self.environment) if self.environment else ("latest", "true"))
        return urlencode(pairs, safe="[]")

    def label(self) -> str:
        """``Web 3 → production`` (or ``→ latest``), for the report."""
        return f"{self.pacticipant} {self.version} → {self.environment or 'latest'}"


#: One matrix row reduced to what both brokers can be compared on:
#: ``(consumer, consumer version, provider, provider version, success, result number)``; the last
#: three are ``None`` for a pact with no result.
RowFact = Tuple[str, str, str, Optional[str], Optional[bool], Optional[int]]


@dataclass(frozen=True)
class Answer:
    """One broker's answer to a question.

    Attributes:
        deployable: ``True``, ``False`` or ``None`` (unknown: a result is missing).
        rows: The rows the verdict was reached from.
        error: Why the broker could not answer; ``deployable`` and ``rows`` mean nothing then.
    """

    deployable: Optional[bool] = None
    rows: FrozenSet[RowFact] = field(default_factory=frozenset)
    error: Optional[str] = None


def _handle(name: str) -> str:
    """A pacticipant name as both brokers compare it (Apiome stores the handle)."""
    try:
        return slugify_pacticipant_name(name)
    except PacticipantValidationError:
        return name.strip().lower()


def _verdict_word(answer: Answer) -> str:
    """``yes``, ``no``, ``unknown`` or ``no answer``."""
    if answer.error:
        return "no answer"
    return {True: "yes", False: "no"}.get(answer.deployable, "unknown")  # type: ignore[arg-type]


# =============================================================================================
# The questions
# =============================================================================================


def choose_questions(plan: Plan, limit: int = DEFAULT_QUESTIONS) -> Tuple[List[Question], int]:
    """Pick the questions to ask, from what the source returned.

    Args:
        plan: The records read from the source.
        limit: The most questions (0 asks none).

    Returns:
        The questions, and how many more there were than ``limit``.
    """
    environments = [record["name"] for _key, record in plan.records["environment"]]
    candidates: List[Tuple[str, str, Optional[str]]] = []
    for kind in ("deployment", "release"):
        for _key, record in plan.records[kind]:
            candidates.append((record["pacticipant"], record["version"], record.get("environment")))

    latest: Dict[str, str] = {}
    for _key, record in plan.records["version"]:  # oldest first: the last one seen is the latest
        latest[record["pacticipant"]] = record["number"]
    if not latest:
        for _key, record in sorted(plan.records["pact"], key=lambda item: item[1].get("created_at") or ""):
            latest[record["consumer"]] = record["consumer_version"]
    for pacticipant, number in latest.items():
        for environment in environments or [None]:
            candidates.append((pacticipant, number, environment))

    questions: List[Question] = []
    seen = set()
    for pacticipant, number, environment in candidates:
        question = Question(pacticipant, number, environment if environment in environments else None)
        if question not in seen:
            seen.add(question)
            questions.append(question)
    cap = max(0, limit)
    return questions[:cap], max(0, len(questions) - cap)


# =============================================================================================
# The answers
# =============================================================================================


def _party(row: Mapping[str, Any], side: str) -> Tuple[str, Optional[str]]:
    """``(name, version number)`` of one side of a source matrix row."""
    found = row.get(side)
    party: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
    inner = party.get("version")
    version: Mapping[str, Any] = inner if isinstance(inner, Mapping) else {}
    number = version.get("number")
    return str(party.get("name") or ""), (str(number) if number is not None else None)


def source_rows(document: Mapping[str, Any]) -> FrozenSet[RowFact]:
    """The considered rows of a source's matrix answer (an ignored row does not count)."""
    facts = set()
    for row in document.get("matrix") or []:
        if not isinstance(row, Mapping) or row.get("ignored"):
            continue
        consumer, consumer_version = _party(row, "consumer")
        provider, provider_version = _party(row, "provider")
        result = row.get("verificationResult") if isinstance(row.get("verificationResult"), Mapping) else None
        success = result.get("success") if result else None
        href = ((result or {}).get("_links") or {}).get("self", {}).get("href") if result else None
        match = _RESULT_NUMBER.search(href or "")
        facts.add(
            (
                _handle(consumer),
                consumer_version or "",
                _handle(provider),
                provider_version if result else None,
                success if isinstance(success, bool) else None,
                int(match.group(1)) if match else None,
            )
        )
    return frozenset(facts)


def source_answer(broker: SourceBroker, question: Question) -> Answer:
    """Ask the source broker.

    Args:
        broker: The source.
        question: The question.

    Returns:
        Its answer; a refusal or an unreadable answer is an :class:`Answer` with ``error``.
    """
    try:
        document = broker.get(f"/matrix?{question.query()}") or {}
    except SourceError as exc:
        return Answer(error=str(exc))
    summary = document.get("summary") if isinstance(document.get("summary"), Mapping) else None
    if summary is None or "deployable" not in summary:
        return Answer(error=f"{broker.host}'s answer has no summary.deployable")
    deployable = summary.get("deployable")
    return Answer(deployable=deployable if isinstance(deployable, bool) else None, rows=source_rows(document))


def apiome_answer(db: Any, tenant_id: str, question: Question) -> Answer:
    """Ask Apiome, through the matrix the Pact Broker routes answer from.

    Args:
        db: The database.
        tenant_id: The workspace.
        question: The question.

    Returns:
        Its answer; a query Apiome refuses is an :class:`Answer` with ``error``.
    """
    from .pact_matrix import deployment_verdict, parse_matrix_query
    from .pact_matrix_store import query_matrix
    from .pact_publication import PactPublicationError

    try:
        selectors, options = parse_matrix_query(question.query())
        result = query_matrix(db, tenant_id, selectors, options)
    except PactPublicationError as exc:
        return Answer(error=str(exc))
    verdict = deployment_verdict(result)
    rows = frozenset(
        (
            _handle(row.consumer_name),
            row.consumer_version_number,
            _handle(row.provider_name),
            row.provider_version_number if row.success is not None else None,
            row.success,
            row.verification_number if row.success is not None else None,
        )
        for row in result.considered_rows
    )
    return Answer(deployable=verdict.deployable, rows=rows)


# =============================================================================================
# Comparing
# =============================================================================================


def _reason(left_behind: Mapping[str, str], key: str) -> str:
    """``: <why>`` when the run said why it left ``key`` behind, else nothing."""
    reason = left_behind.get(key)
    return f": {reason}" if reason else ""


def _name_of(plan_names: Mapping[str, str], handle: str) -> str:
    """The source's spelling of a pacticipant handle."""
    return plan_names.get(handle, handle)


def explain(
    question: Question,
    source: Answer,
    apiome: Answer,
    *,
    host: str,
    left_behind: Optional[Mapping[str, str]] = None,
    names: Optional[Mapping[str, str]] = None,
) -> str:
    """Say why two answers to one question differ.

    Args:
        question: The question.
        source: The old broker's answer.
        apiome: Apiome's answer.
        host: The old broker's host, for the wording.
        left_behind: ``{source key: why}`` of the records the run did not copy (refused or skipped).
        names: ``{handle: name}`` — the source's spelling of each pacticipant.

    Returns:
        One sentence naming the cause.
    """
    why = left_behind or {}
    spell = names or {}
    if source.error:
        return f"{host} could not answer it — a selector it does not support? ({source.error})"
    if apiome.error:
        return f"Apiome could not answer it ({apiome.error})"
    if not apiome.rows and source.rows:
        key = f"version:{question.pacticipant}/{question.version}"
        if key in why:
            return f"{question.pacticipant} {question.version} was not copied{_reason(why, key)}"
    for consumer, consumer_version, provider, provider_version, success, number in sorted(
        source.rows, key=lambda row: tuple(str(part) for part in row)
    ):
        pact = (consumer, consumer_version, provider)
        apiome_pacts = {(row[0], row[1], row[2]) for row in apiome.rows}
        c, p = _name_of(spell, consumer), _name_of(spell, provider)
        if pact not in apiome_pacts:
            key = f"pact:{p}/{c}/{consumer_version}"
            return f"the pact {c} {consumer_version} → {p} was not copied{_reason(why, key)}"
        if success is None:
            continue
        has_result = any(row[:3] == pact and row[3] == provider_version and row[4] is not None for row in apiome.rows)
        if not has_result:
            key = f"verification:{p}/{c}/{consumer_version}/{number}" if number is not None else ""
            return (
                f"the verification result of {c} {consumer_version} by {p} {provider_version} "
                f"was not copied{_reason(why, key)}"
            )
    for consumer, consumer_version, provider, provider_version, success, _number in sorted(
        apiome.rows, key=lambda row: tuple(str(part) for part in row)
    ):
        if success is None:
            continue
        on_source = any(
            row[:4] == (consumer, consumer_version, provider, provider_version) and row[4] is not None
            for row in source.rows
        )
        if not on_source:
            return (
                f"Apiome has a result {host} does not: {_name_of(spell, provider)} {provider_version} verified "
                f"{_name_of(spell, consumer)} {consumer_version} (published to Apiome directly)"
            )
    if question.environment and source.rows != apiome.rows:
        return f"what is deployed to or released in {question.environment} differs between the two"
    return f"the same rows were read differently ({host}: {len(source.rows)} row(s), Apiome: {len(apiome.rows)})"


def check_agreement(
    questions: Sequence[Question],
    ask_source: Callable[[Question], Answer],
    ask_apiome: Callable[[Question], Answer],
    *,
    host: str,
    not_asked: int = 0,
    left_behind: Optional[Mapping[str, str]] = None,
    names: Optional[Mapping[str, str]] = None,
    checked_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask both brokers every question and list where they disagree.

    Args:
        questions: The questions (:func:`choose_questions`).
        ask_source: Asks the old broker.
        ask_apiome: Asks Apiome.
        host: The old broker's host.
        not_asked: Questions left out by the limit.
        left_behind: ``{source key: why}`` of what the run did not copy.
        names: ``{handle: name}`` of the source's pacticipants.
        checked_at: When (ISO 8601).

    Returns:
        ``{asked, agree, not_asked, differences: [{question, pacticipant, version, environment,
        source, apiome, cause}], differences_dropped, checked_at}`` — stored on the run as
        ``facts.agreement``.
    """
    differences: List[Dict[str, Any]] = []
    dropped = 0
    agree = 0
    for question in questions:
        source = ask_source(question)
        apiome = ask_apiome(question)
        if not source.error and not apiome.error and source.deployable == apiome.deployable:
            agree += 1
            continue
        if len(differences) >= MAX_DIFFERENCES:
            dropped += 1
            continue
        differences.append(
            {
                "question": question.label(),
                "pacticipant": question.pacticipant,
                "version": question.version,
                "environment": question.environment,
                "source": _verdict_word(source),
                "apiome": _verdict_word(apiome),
                "cause": explain(question, source, apiome, host=host, left_behind=left_behind, names=names),
            }
        )
    return {
        "asked": len(questions),
        "agree": agree,
        "not_asked": not_asked,
        "differences": differences,
        "differences_dropped": dropped,
        "checked_at": checked_at,
    }


def plan_names(plan: Plan) -> Dict[str, str]:
    """``{handle: name}`` of every pacticipant the plan names."""
    names: Dict[str, str] = {}
    for _key, record in plan.records["pacticipant"]:
        names.setdefault(_handle(record["name"]), record["name"])
    for kind in ("pact", "verification"):
        for _key, record in plan.records[kind]:
            names.setdefault(_handle(record["consumer"]), record["consumer"])
            names.setdefault(_handle(record["provider"]), record["provider"])
    return names
