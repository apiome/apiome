"""Consumer-version selectors and the pacts a provider must verify — PFX-1.3 (#6916).

A provider's CI does not ask for pacts by name. It asks the broker "which pacts must I verify?"
with **consumer-version selectors** (``POST …/pacts/provider/{p}/for-verification``), and the broker
answers with one URL per distinct pact and the reasons it was chosen. This module is the pure part
of that exchange — no database, no HTTP:

* :func:`parse_for_verification_request` reads and checks the request body. The rules are the
  Pact Broker's (``ConsumerVersionSelectorContract``): a selector must say *what* it selects, and a
  selector that combines criteria the broker refuses (``tag`` with ``branch``, ``mainBranch`` with
  anything but ``consumer``, ``fallbackTag`` without ``latest: true`` …) is refused with
  ``pact-selector-invalid`` and the JSON Pointer of the selector — a 400.
* :func:`select_verifiable_pacts` applies the selectors to the provider's publications
  (:class:`PactCandidate`, read by :func:`app.pact_publication_store.list_pact_candidates`) and
  merges what they select into one :class:`VerifiablePact` per consumer and pact content.
* :func:`build_notices`, :func:`short_description` and :func:`encode_metadata` render the parts of
  the response, in the broker's wording, which Pact verifiers print and Pact Go names tests after.

Selectors, as a verifier sends them:

====================  ==========================================================================
``mainBranch: true``  The latest version of each consumer from its main branch.
``branch: "x"``       The latest version of each consumer from branch ``x`` (``fallbackBranch``
                      or ``fallbackToMainBranch`` when a consumer has none there).
``matchingBranch``    ``branch`` set to the request's ``providerVersionBranch``.
``tag: "x"``          Every version tagged ``x``; with ``latest: true`` only the latest per
                      consumer (``fallbackTag`` when a consumer has none).
``latest: true``      Alone: the latest version of each consumer that has a pact with the provider.
``consumer: "name"``  Narrows any of the above to one consumer.
``deployed``,         Versions deployed or released to an environment. Environments arrive with
``released``,         PFX-1.5 (#6918); until then these selectors are accepted and select nothing.
``deployedOrReleased``,
``environment``
====================  ==========================================================================

**Pending.** A pact is *pending* for a provider until a verification of it from that provider (on
the request's ``providerVersionBranch``) has succeeded; a failure of a pending pact does not fail
the provider's build. Verification results are recorded from PFX-1.4 (#6917) on, so today no pact
has been verified and every pact is pending — the correct answer under the broker's definition.
:func:`is_pending` is the one place that changes when results exist (PFX-1.7, #6920).

**Work in progress.** ``includeWipPactsSince`` is accepted and checked; selecting WIP pacts is
PFX-1.7 (#6920), so none are added yet.
"""

from __future__ import annotations

import base64
import datetime
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote_plus

from .pact_publication import PactPublicationError
from .pacticipant import slugify_pacticipant_name

__all__ = [
    "CODE_SELECTOR_INVALID",
    "ConsumerVersionSelector",
    "ForVerificationQuery",
    "PactCandidate",
    "SelectedBy",
    "VerifiablePact",
    "build_notices",
    "encode_metadata",
    "inclusion_reason",
    "is_pending",
    "latest_per_consumer",
    "parse_for_verification_request",
    "pending_reason",
    "select_verifiable_pacts",
    "short_description",
    "verification_metadata",
]

#: A for-verification request or one of its selectors is malformed or ambiguous (HTTP 400).
CODE_SELECTOR_INVALID = "pact-selector-invalid"

#: Where a verifier's notices point a reader for pending and WIP pacts (the broker's links).
READ_MORE_PENDING = "Read more at https://docs.pact.io/go/pending"

#: The most selectors one request may carry; a verifier sends a handful.
MAX_SELECTORS = 100

_BRANCH_KEYS = (
    "latest",
    "tag",
    "fallbackTag",
    "branch",
    "fallbackBranch",
    "fallbackToMainBranch",
    "matchingBranch",
    "mainBranch",
)
_ENVIRONMENT_KEYS = ("environment", "deployed", "released", "deployedOrReleased")
_STRING_KEYS = ("tag", "branch", "fallbackTag", "fallbackBranch", "consumer", "environment")
_TRUE_ONLY_KEYS = ("mainBranch", "matchingBranch", "fallbackToMainBranch", "deployed", "released", "deployedOrReleased")

# The kinds of a selector, in the order the broker lists them in a notice.
KIND_OVERALL_LATEST = "overall_latest"
KIND_MAIN_BRANCH = "latest_for_main_branch"
KIND_BRANCH = "latest_for_branch"
KIND_LATEST_TAG = "latest_for_tag"
KIND_ALL_TAG = "all_for_tag"
KIND_DEPLOYED = "currently_deployed"
KIND_RELEASED = "currently_supported"
KIND_ENVIRONMENT = "in_environment"
_KIND_ORDER = (
    KIND_OVERALL_LATEST,
    KIND_MAIN_BRANCH,
    KIND_BRANCH,
    KIND_LATEST_TAG,
    KIND_ALL_TAG,
    KIND_DEPLOYED,
    KIND_RELEASED,
    KIND_ENVIRONMENT,
)


# ---------------------------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsumerVersionSelector:
    """One consumer-version selector, checked.

    ``matchingBranch`` has been resolved to ``branch`` and ``deployedOrReleased`` split into a
    ``deployed`` and a ``released`` selector by the time a selector is built, as the broker does.

    Attributes:
        main_branch: Select from each consumer's main branch.
        branch: Select from this consumer branch.
        fallback_branch: The branch to use for a consumer with no pact from ``branch``.
        fallback_to_main_branch: Use the consumer's main branch for a consumer with none from
            ``branch``.
        matching_branch: The selector was ``matchingBranch: true`` (``branch`` is the provider's).
        tag: Select versions with this tag.
        fallback_tag: The tag to use for a consumer with no pact tagged ``tag``.
        latest: ``True`` for the latest version only; ``False`` for all; ``None`` when not sent.
        consumer: Narrow the selector to the consumer of this name.
        deployed: Versions currently deployed (to ``environment``, or any).
        released: Versions released and supported (in ``environment``, or any).
        environment: The environment name.
    """

    main_branch: bool = False
    branch: Optional[str] = None
    fallback_branch: Optional[str] = None
    fallback_to_main_branch: bool = False
    matching_branch: bool = False
    tag: Optional[str] = None
    fallback_tag: Optional[str] = None
    latest: Optional[bool] = None
    consumer: Optional[str] = None
    deployed: bool = False
    released: bool = False
    environment: Optional[str] = None

    @property
    def kind(self) -> str:
        """What the selector selects: one of the ``KIND_*`` constants."""
        if self.main_branch:
            return KIND_MAIN_BRANCH
        if self.branch is not None:
            return KIND_BRANCH
        if self.deployed:
            return KIND_DEPLOYED
        if self.released:
            return KIND_RELEASED
        if self.environment is not None:
            return KIND_ENVIRONMENT
        if self.tag is not None:
            return KIND_LATEST_TAG if self.latest else KIND_ALL_TAG
        return KIND_OVERALL_LATEST


@dataclass(frozen=True)
class ForVerificationQuery:
    """A checked ``for-verification`` request.

    Attributes:
        selectors: The consumer-version selectors; empty means the broker's defaults.
        provider_version_branch: The branch of the provider build that will verify.
        provider_version_tags: The tags of that build (the older alternative to a branch).
        include_pending_status: Whether each pact reports ``pending`` and the pending notices.
        include_wip_pacts_since: The ``includeWipPactsSince`` date, when sent.
    """

    selectors: Tuple[ConsumerVersionSelector, ...] = ()
    provider_version_branch: Optional[str] = None
    provider_version_tags: Tuple[str, ...] = ()
    include_pending_status: bool = False
    include_wip_pacts_since: Optional[datetime.date] = None


def _invalid(pointer: str, message: str) -> PactPublicationError:
    """A ``pact-selector-invalid`` refusal locating ``pointer``."""
    return PactPublicationError(CODE_SELECTOR_INVALID, f"{pointer or '(request body)'}: {message}", pointer=pointer)


def _sent(value: Any) -> bool:
    """Whether a selector field was given a value (the broker's ``provided?``)."""
    return value is not None and value != ""


def _check_field_types(raw: Mapping[str, Any], pointer: str) -> None:
    """Refuse a selector field of the wrong JSON type.

    Args:
        raw: The selector as sent.
        pointer: The selector's JSON Pointer.

    Raises:
        PactPublicationError: ``pact-selector-invalid`` naming the field.
    """
    for key in _STRING_KEYS:
        if key in raw and raw[key] is not None:
            value = raw[key]
            if not isinstance(value, str) or not value.strip():
                raise _invalid(f"{pointer}/{key}", f"{key} must be a non-blank string")
    for key in _TRUE_ONLY_KEYS:
        if key in raw and raw[key] is not None and raw[key] is not True:
            raise _invalid(f"{pointer}/{key}", f"{key} can only be true")
    if "latest" in raw and raw["latest"] is not None and not isinstance(raw["latest"], bool):
        raise _invalid(f"{pointer}/latest", "latest must be true or false")


def _check_combination(raw: Mapping[str, Any], pointer: str, provider_version_branch: Optional[str]) -> None:
    """Refuse a selector whose criteria are missing or ambiguous — the broker's rules.

    Args:
        raw: The selector as sent (types already checked).
        pointer: The selector's JSON Pointer.
        provider_version_branch: The request's ``providerVersionBranch``.

    Raises:
        PactPublicationError: ``pact-selector-invalid`` with the broker's message.
    """
    present = {key for key, value in raw.items() if _sent(value)}
    latest = raw.get("latest")

    def fail(message: str) -> PactPublicationError:
        return _invalid(pointer, message)

    if not present & {"mainBranch", "tag", "branch", "environment"} and not any(
        raw.get(key) is True for key in ("matchingBranch", "deployed", "released", "deployedOrReleased", "latest")
    ):
        raise fail(
            "must specify a value for environment or tag or branch, or specify mainBranch=true, "
            "matchingBranch=true, latest=true, deployed=true, released=true or deployedOrReleased=true"
        )
    others = present - {"consumer"}
    if raw.get("mainBranch") and others - {"mainBranch", "latest"}:
        raise fail("cannot specify mainBranch=true with any other criteria apart from consumer")
    if raw.get("mainBranch") and latest is False:
        raise fail("cannot specify mainBranch=true with latest=false")
    if raw.get("matchingBranch") and others - {"matchingBranch"}:
        raise fail("cannot specify matchingBranch=true with any other criteria apart from consumer")
    if raw.get("matchingBranch") and not _sent(provider_version_branch):
        raise fail("the providerVersionBranch must be specified when the selector matchingBranch=true is used")
    if _sent(raw.get("tag")) and _sent(raw.get("branch")):
        raise fail("cannot specify both a tag and a branch")

    branch_fields = sorted(present & set(_BRANCH_KEYS))
    environment_fields = sorted(present & set(_ENVIRONMENT_KEYS))
    if branch_fields and environment_fields:
        raise fail(
            f"cannot specify the field{'s' if len(branch_fields) > 1 else ''} {'/'.join(branch_fields)} with the "
            f"field{'s' if len(environment_fields) > 1 else ''} {'/'.join(environment_fields)}"
        )

    if _sent(raw.get("fallbackTag")) and latest is not True:
        raise fail("fallbackTag can only be set if latest is true")
    if _sent(raw.get("fallbackTag")) and not _sent(raw.get("tag")):
        raise fail("a tag must be specified when a fallbackTag is specified")
    if _sent(raw.get("fallbackBranch")) and not _sent(raw.get("branch")):
        raise fail("a branch must be specified when a fallbackBranch is specified")
    if _sent(raw.get("fallbackBranch")) and latest is False:
        raise fail("fallbackBranch can only be set if latest is true")
    if raw.get("fallbackToMainBranch") and not _sent(raw.get("branch")):
        raise fail("a branch must be specified when fallbackToMainBranch=true is specified")
    if raw.get("fallbackToMainBranch") and _sent(raw.get("fallbackBranch")):
        raise fail("cannot specify both fallbackBranch and fallbackToMainBranch=true")
    if raw.get("fallbackToMainBranch") and latest is False:
        raise fail("fallbackToMainBranch can only be set if latest is true")
    if _sent(raw.get("branch")) and latest is False:
        raise fail("cannot specify a branch with latest=false")

    if raw.get("deployed") and raw.get("released"):
        raise fail("cannot specify both deployed=true and released=true")
    if raw.get("deployed") and raw.get("deployedOrReleased"):
        raise fail("cannot specify both deployed=true and deployedOrReleased=true")
    if raw.get("released") and raw.get("deployedOrReleased"):
        raise fail("cannot specify both released=true and deployedOrReleased=true")


def _strip(value: Any) -> Optional[str]:
    """A sent string, trimmed; ``None`` when not sent."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _build_selectors(raw: Mapping[str, Any], provider_version_branch: Optional[str]) -> List[ConsumerVersionSelector]:
    """Turn one checked selector into the selector(s) it stands for.

    ``matchingBranch`` becomes ``branch: <providerVersionBranch>``; ``deployedOrReleased`` becomes
    a ``deployed`` and a ``released`` selector.

    Args:
        raw: The selector as sent, already checked.
        provider_version_branch: The request's ``providerVersionBranch``.

    Returns:
        One selector, or two for ``deployedOrReleased``.
    """
    matching = raw.get("matchingBranch") is True
    branch = provider_version_branch if matching else _strip(raw.get("branch"))
    main_branch = raw.get("mainBranch") is True
    latest = raw.get("latest")
    if branch is not None or main_branch:
        latest = True  # A branch selector always means the latest version (the broker's setter).
    base = ConsumerVersionSelector(
        main_branch=main_branch,
        branch=branch,
        fallback_branch=_strip(raw.get("fallbackBranch")),
        fallback_to_main_branch=raw.get("fallbackToMainBranch") is True,
        matching_branch=matching,
        tag=_strip(raw.get("tag")),
        fallback_tag=_strip(raw.get("fallbackTag")),
        latest=latest,
        consumer=_strip(raw.get("consumer")),
        deployed=raw.get("deployed") is True,
        released=raw.get("released") is True,
        environment=_strip(raw.get("environment")),
    )
    if raw.get("deployedOrReleased") is True:
        return [
            ConsumerVersionSelector(deployed=True, consumer=base.consumer, environment=base.environment),
            ConsumerVersionSelector(released=True, consumer=base.consumer, environment=base.environment),
        ]
    return [base]


def _parse_date(value: Any) -> datetime.date:
    """Parse ``includeWipPactsSince`` (an ISO 8601 date or date-time).

    Raises:
        PactPublicationError: ``pact-selector-invalid`` for anything else.
    """
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            return datetime.date.fromisoformat(text[:10]) if len(text) <= 10 else _parse_datetime(text)
        except ValueError:
            pass
    raise _invalid("/includeWipPactsSince", "includeWipPactsSince must be a date, such as 2026-01-31")


def _parse_datetime(text: str) -> datetime.date:
    """The date of an ISO 8601 date-time (``Z`` accepted)."""
    return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).date()


def parse_for_verification_request(body: Any) -> ForVerificationQuery:
    """Read and check the body of ``POST …/pacts/provider/{p}/for-verification``.

    Unknown fields are ignored, as the broker ignores them.

    Args:
        body: The decoded JSON body (``None`` for an empty body).

    Returns:
        The checked query.

    Raises:
        PactPublicationError: ``pact-selector-invalid`` with the JSON Pointer of the problem.
    """
    if body is None:
        body = {}
    if not isinstance(body, Mapping):
        raise _invalid("", "the request body must be a JSON object")

    branch_value = body.get("providerVersionBranch")
    if branch_value is not None and not isinstance(branch_value, str):
        raise _invalid("/providerVersionBranch", "providerVersionBranch must be a string")
    if isinstance(branch_value, str) and branch_value and not branch_value.strip():
        raise _invalid("/providerVersionBranch", "providerVersionBranch cannot be blank")

    tags_value = body.get("providerVersionTags")
    if tags_value is None:
        tags_value = []
    if not isinstance(tags_value, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags_value):
        raise _invalid("/providerVersionTags", "providerVersionTags must be an array of non-blank strings")
    tags = tuple(dict.fromkeys(tag.strip() for tag in tags_value))

    pending_value = body.get("includePendingStatus", False)
    if pending_value is None:
        pending_value = False
    if not isinstance(pending_value, bool):
        raise _invalid("/includePendingStatus", "includePendingStatus must be true or false")

    wip_value = body.get("includeWipPactsSince")
    wip_since = _parse_date(wip_value) if wip_value is not None else None

    if not tags and (pending_value or wip_since) and isinstance(branch_value, str) and branch_value == "":
        raise _invalid(
            "/providerVersionBranch",
            "when pending or WIP pacts are enabled and there are no tags provided, the provider "
            "version branch must not be an empty string, as it is used in the calculations for "
            "WIP/pending. A value must be provided (recommended), or it must not be set at all.",
        )
    provider_branch = branch_value.strip() if isinstance(branch_value, str) and branch_value.strip() else None

    raw_selectors = body.get("consumerVersionSelectors")
    if raw_selectors is None:
        raw_selectors = []
    if not isinstance(raw_selectors, list):
        raise _invalid("/consumerVersionSelectors", "consumerVersionSelectors must be an array of objects")
    if len(raw_selectors) > MAX_SELECTORS:
        raise _invalid("/consumerVersionSelectors", f"send at most {MAX_SELECTORS} selectors")
    selectors: List[ConsumerVersionSelector] = []
    for index, raw in enumerate(raw_selectors):
        pointer = f"/consumerVersionSelectors/{index}"
        if not isinstance(raw, Mapping):
            raise _invalid(pointer, "a selector must be a JSON object")
        _check_field_types(raw, pointer)
        _check_combination(raw, pointer, provider_branch)
        selectors.extend(_build_selectors(raw, provider_branch))

    return ForVerificationQuery(
        selectors=tuple(selectors),
        provider_version_branch=provider_branch,
        provider_version_tags=tags,
        include_pending_status=pending_value,
        include_wip_pacts_since=wip_since,
    )


# ---------------------------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PactCandidate:
    """One publication of a pact for the provider: a consumer version and the pact it published.

    Attributes:
        consumer_id: The consumer pacticipant's id.
        consumer_slug: Its handle.
        consumer_name: Its display name.
        consumer_main_branch: Its main branch, when set.
        version_id: The consumer version's id.
        version_number: The consumer version number.
        version_seq: The order the version was recorded in (higher is later).
        sha: The content address of the pact it published.
        branches: The branches the version was recorded on.
        tags: The tags of the version.
    """

    consumer_id: str
    consumer_slug: str
    consumer_name: str
    consumer_main_branch: Optional[str]
    version_id: str
    version_number: str
    version_seq: int
    sha: str
    branches: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SelectedBy:
    """Why a pact was selected: one selector and the consumer version it matched.

    Attributes:
        selector: The selector.
        candidate: The publication it matched.
        fallback: ``True`` when the selector's fallback (tag, branch or main branch) matched.
    """

    selector: ConsumerVersionSelector
    candidate: PactCandidate
    fallback: bool = False

    @property
    def branch(self) -> Optional[str]:
        """The branch that matched: the fallback branch when the fallback was used."""
        selector = self.selector
        if self.fallback:
            return selector.fallback_branch or (
                self.candidate.consumer_main_branch if selector.fallback_to_main_branch else None
            )
        if selector.main_branch:
            return self.candidate.consumer_main_branch
        return selector.branch

    @property
    def tag(self) -> Optional[str]:
        """The tag that matched: the fallback tag when the fallback was used."""
        return self.selector.fallback_tag if self.fallback and self.selector.fallback_tag else self.selector.tag


@dataclass
class VerifiablePact:
    """One pact a provider must verify, with every reason it was selected.

    Attributes:
        candidate: The latest-recorded consumer version that published this content (the one the
            pact is named after).
        selected_by: The selectors that chose it, in the broker's order.
        pending: Whether the pact is pending for the verifying provider build.
        wip: Whether it was included as a work-in-progress pact (PFX-1.7).
    """

    candidate: PactCandidate
    selected_by: List[SelectedBy] = field(default_factory=list)
    pending: bool = True
    wip: bool = False


def _consumer_filter(selector: ConsumerVersionSelector) -> Callable[[PactCandidate], bool]:
    """A predicate matching the selector's ``consumer`` (every consumer when not set)."""
    if selector.consumer is None:
        return lambda _candidate: True
    wanted = slugify_pacticipant_name(selector.consumer)
    name = selector.consumer.casefold()
    return lambda candidate: candidate.consumer_slug == wanted or candidate.consumer_name.casefold() == name


def latest_per_consumer(
    candidates: Iterable[PactCandidate], predicate: Callable[[PactCandidate], bool]
) -> List[PactCandidate]:
    """The latest-recorded matching publication of each consumer.

    Args:
        candidates: The provider's publications.
        predicate: Which publications count.

    Returns:
        At most one publication per consumer, in no particular order.
    """
    best: Dict[str, PactCandidate] = {}
    for candidate in candidates:
        if predicate(candidate):
            current = best.get(candidate.consumer_id)
            if current is None or candidate.version_seq > current.version_seq:
                best[candidate.consumer_id] = candidate
    return list(best.values())


def _environment_matches(selector: ConsumerVersionSelector, candidates: Sequence[PactCandidate]) -> List[PactCandidate]:
    """The publications of consumer versions deployed or released to an environment.

    Environments and deployment records are PFX-1.5 (#6918). Until they exist no version is
    deployed anywhere, so the environment selectors select nothing.

    Args:
        selector: A ``deployed``, ``released`` or ``environment`` selector.
        candidates: The provider's publications.

    Returns:
        An empty list.
    """
    del selector, candidates
    return []


def _on_main_branch(candidate: PactCandidate) -> bool:
    """Whether the version was recorded on its consumer's main branch."""
    return bool(candidate.consumer_main_branch) and candidate.consumer_main_branch in candidate.branches


def _on_branch(branch: str) -> Callable[[PactCandidate], bool]:
    """A predicate: the version was recorded on ``branch``."""
    return lambda candidate: branch in candidate.branches


def _has_tag(tag: str) -> Callable[[PactCandidate], bool]:
    """A predicate: the version carries ``tag``."""
    return lambda candidate: tag in candidate.tags


def _apply_selector(selector: ConsumerVersionSelector, candidates: Sequence[PactCandidate]) -> List[SelectedBy]:
    """Everything one selector selects, fallbacks included.

    A fallback applies per consumer: a consumer with no pact for the tag or branch gets its
    fallback pact even when another consumer has one, as the broker does.

    Args:
        selector: The selector.
        candidates: The provider's publications.

    Returns:
        One :class:`SelectedBy` per publication selected.
    """
    for_consumer = _consumer_filter(selector)
    kind = selector.kind

    def latest(
        predicate: Callable[[PactCandidate], bool], pool: Sequence[PactCandidate] = candidates
    ) -> List[PactCandidate]:
        return latest_per_consumer(pool, lambda c: for_consumer(c) and predicate(c))

    if kind == KIND_OVERALL_LATEST:
        return [SelectedBy(selector, c) for c in latest(lambda c: True)]
    if kind == KIND_MAIN_BRANCH:
        return [SelectedBy(selector, c) for c in latest(_on_main_branch)]
    if kind == KIND_ALL_TAG:
        return [SelectedBy(selector, c) for c in candidates if for_consumer(c) and selector.tag in c.tags]
    if kind in (KIND_DEPLOYED, KIND_RELEASED, KIND_ENVIRONMENT):
        return [SelectedBy(selector, c) for c in _environment_matches(selector, candidates)]

    fallback_test: Optional[Callable[[PactCandidate], bool]] = None
    if kind == KIND_BRANCH:
        primary = latest(lambda c: selector.branch in c.branches)
        if selector.fallback_branch:
            fallback_test = _on_branch(selector.fallback_branch)
        elif selector.fallback_to_main_branch:
            fallback_test = _on_main_branch
    else:  # KIND_LATEST_TAG
        primary = latest(lambda c: selector.tag in c.tags)
        if selector.fallback_tag:
            fallback_test = _has_tag(selector.fallback_tag)

    selected = [SelectedBy(selector, c) for c in primary]
    if fallback_test is not None:
        covered = {c.consumer_id for c in primary}
        rest = [c for c in candidates if c.consumer_id not in covered]
        selected.extend(SelectedBy(selector, c, fallback=True) for c in latest(fallback_test, rest))
    return selected


def _default_selectors(candidates: Sequence[PactCandidate]) -> List[ConsumerVersionSelector]:
    """The selectors the broker uses when a request sends none.

    For each consumer: its main branch when it has a pact from there, else the latest version
    tagged with the main branch's name, else its overall latest; then whatever is deployed or
    released (nothing until PFX-1.5).

    Args:
        candidates: The provider's publications.

    Returns:
        The default selectors, one per consumer, then ``deployed`` and ``released``.
    """
    selectors: List[ConsumerVersionSelector] = []
    seen: Dict[str, PactCandidate] = {}
    for candidate in candidates:
        seen.setdefault(candidate.consumer_id, candidate)
    for consumer_id, first in sorted(seen.items(), key=lambda item: item[1].consumer_name.casefold()):
        mine = [c for c in candidates if c.consumer_id == consumer_id]
        main = first.consumer_main_branch
        if main and any(main in c.branches for c in mine):
            selectors.append(ConsumerVersionSelector(main_branch=True, latest=True, consumer=first.consumer_name))
        elif main and any(main in c.tags for c in mine):
            selectors.append(ConsumerVersionSelector(tag=main, latest=True, consumer=first.consumer_name))
        else:
            selectors.append(ConsumerVersionSelector(latest=True, consumer=first.consumer_name))
    selectors.append(ConsumerVersionSelector(deployed=True))
    selectors.append(ConsumerVersionSelector(released=True))
    return selectors


def _selection_order(selected: SelectedBy) -> Tuple[int, str, int]:
    """Sort key of a reason within a pact: the broker's selector order, then version order."""
    return (
        _KIND_ORDER.index(selected.selector.kind),
        selected.branch or selected.tag or "",
        selected.candidate.version_seq,
    )


def is_pending(pact: VerifiablePact, query: ForVerificationQuery) -> bool:
    """Whether a pact is pending for the provider build that is about to verify it.

    A pact is pending until a verification of its content by the provider — from the request's
    ``providerVersionBranch``, or with one of its ``providerVersionTags`` — has succeeded.
    Verification results are recorded from PFX-1.4 (#6917) on, so no pact has been verified yet
    and every pact is pending. PFX-1.7 (#6920) replaces this with the lookup.

    Args:
        pact: The selected pact.
        query: The request.

    Returns:
        ``True``.
    """
    del pact, query
    return True


def select_verifiable_pacts(candidates: Sequence[PactCandidate], query: ForVerificationQuery) -> List[VerifiablePact]:
    """The pacts a provider must verify for a request.

    Every selector is applied (the broker's defaults when the request has none); what they select
    is merged into one pact per consumer and content, named after the latest-recorded consumer
    version that published it, and carrying every selector that chose it.

    Args:
        candidates: The provider's publications.
        query: The checked request.

    Returns:
        The pacts, ordered by consumer name and then by consumer version.
    """
    selectors = list(query.selectors) or _default_selectors(candidates)
    merged: Dict[Tuple[str, str], VerifiablePact] = {}
    for selector in selectors:
        for selected in _apply_selector(selector, candidates):
            key = (selected.candidate.consumer_id, selected.candidate.sha)
            pact = merged.get(key)
            if pact is None:
                pact = merged[key] = VerifiablePact(candidate=selected.candidate)
            elif selected.candidate.version_seq > pact.candidate.version_seq:
                pact.candidate = selected.candidate
            if selected not in pact.selected_by:
                pact.selected_by.append(selected)
    pacts = sorted(merged.values(), key=lambda p: (p.candidate.consumer_name.casefold(), p.candidate.version_seq))
    for pact in pacts:
        pact.selected_by.sort(key=_selection_order)
        pact.pending = is_pending(pact, query)
    return pacts


# ---------------------------------------------------------------------------------------------
# Wording — the broker's, so verifier output reads the same against Apiome
# ---------------------------------------------------------------------------------------------


def _join(words: Sequence[str], last: str = " and ") -> str:
    """``a``, ``a and b``, ``a, b and c``."""
    words = list(words)
    if len(words) <= 2:
        return last.join(words)
    return f"{', '.join(words[:-2])}, {last.join(words[-2:])}"


def _join_quoted(words: Sequence[str]) -> str:
    """Like :func:`_join`, each word in single quotes."""
    return _join([f"'{word}'" for word in words])


def _version_label(selected: SelectedBy) -> str:
    """``version`` or ``version of <consumer>`` when the selector named one."""
    return f"version of {selected.selector.consumer}" if selected.selector.consumer else "version"


def _selector_description(selected: SelectedBy, provider_name: str) -> str:
    """One bullet of the inclusion notice, ending with the consumer version it matched."""
    selector = selected.selector
    kind = selector.kind
    if kind == KIND_OVERALL_LATEST:
        text = f"latest version of {selector.consumer or 'a consumer'} that has a pact with {provider_name}"
    elif kind == KIND_LATEST_TAG:
        if selected.fallback:
            text = (
                f"latest {_version_label(selected)} tagged '{selector.fallback_tag}' (fallback tag used as no "
                f"pact was found with tag '{selector.tag}')"
            )
        else:
            text = f"latest {_version_label(selected)} tagged '{selector.tag}'"
    elif kind == KIND_MAIN_BRANCH:
        text = f"latest {_version_label(selected)} from the main branch '{selected.candidate.consumer_main_branch}'"
    elif kind == KIND_BRANCH:
        if selected.fallback:
            text = (
                f"latest {_version_label(selected)} from branch '{selected.branch}' (fallback branch used as no "
                f"pact was found from branch '{selector.branch}')"
            )
        else:
            text = f"latest {_version_label(selected)} from branch '{selector.branch}'"
    elif kind == KIND_ALL_TAG:
        text = (
            f"all {selector.consumer} versions tagged '{selector.tag}'"
            if selector.consumer
            else f"all consumer versions tagged '{selector.tag}'"
        )
    else:
        text = f"{selector.consumer or 'a consumer'} version in environment {selector.environment}"
    return f"{text} ({selected.candidate.version_number})"


def _environment_description(group: Sequence[SelectedBy], verb: str) -> List[str]:
    """The bullets for ``deployed`` or ``released`` reasons, one per consumer named."""
    lines: List[str] = []
    by_consumer: Dict[Optional[str], List[SelectedBy]] = {}
    for selected in group:
        by_consumer.setdefault(selected.selector.consumer, []).append(selected)
    for consumer, entries in by_consumer.items():
        label = f"version(s) of {consumer}" if consumer else "consumer version(s)"
        places = [
            f"{entry.selector.environment or 'any environment'} ({entry.candidate.version_number})" for entry in entries
        ]
        lines.append(f"{label} {verb} {_join(places)}")
    return lines


def _selector_descriptions(pact: VerifiablePact, provider_name: str) -> str:
    """The bulleted list of why a pact was selected."""
    lines: List[str] = []
    for kind in _KIND_ORDER:
        group = [selected for selected in pact.selected_by if selected.selector.kind == kind]
        if not group:
            continue
        if kind == KIND_DEPLOYED:
            lines.extend(_environment_description(group, "currently deployed to"))
        elif kind == KIND_RELEASED:
            lines.extend(_environment_description(group, "released and supported in"))
        else:
            lines.extend(_selector_description(selected, provider_name) for selected in group)
    return "\n".join(f"    * {line}" for line in lines)


def inclusion_reason(pact: VerifiablePact, pact_url: str, provider_name: str) -> str:
    """The notice saying why the pact is being verified.

    Args:
        pact: The selected pact.
        pact_url: Its for-verification URL.
        provider_name: The verifying provider.

    Returns:
        The broker's ``before_verification`` inclusion text.
    """
    count = len(pact.selected_by)
    versions = "the consumer version" if count == 1 else "the consumer versions"
    criteria = "criterion" if count == 1 else "criteria"
    return (
        f"The pact at {pact_url} is being verified because the pact content belongs to {versions} matching the "
        f"following {criteria}:\n{_selector_descriptions(pact, provider_name)}"
    )


def _provider_description(query: ForVerificationQuery, provider_name: str, any_or_a: str) -> str:
    """Which provider builds the pending state is about: a branch, tags, or the provider."""
    if query.provider_version_branch:
        return f"{any_or_a} version of {provider_name} from branch '{query.provider_version_branch}'"
    tags = query.provider_version_tags
    if not tags:
        return provider_name
    if len(tags) == 1:
        return f"{any_or_a} version of {provider_name} with tag '{tags[0]}'"
    return f"{any_or_a} versions of {provider_name} with tag {_join_quoted(tags)}"


def _with_these_tags(query: ForVerificationQuery) -> str:
    """``""``, ``"with this tag "`` or ``"with these tags "``."""
    count = len(query.provider_version_tags)
    if count == 0:
        return ""
    return "with this tag " if count == 1 else "with these tags "


def pending_reason(pact: VerifiablePact, query: ForVerificationQuery, provider_name: str) -> str:
    """The notice saying whether a failure of this pact fails the build.

    Args:
        pact: The selected pact.
        query: The request.
        provider_name: The verifying provider.

    Returns:
        The broker's pending (or not pending) ``before_verification`` text.
    """
    if pact.pending:
        return (
            f"This pact is in pending state for this version of {provider_name} because a successful verification "
            f"result for {_provider_description(query, provider_name, 'a')} has not yet been published. If this "
            f"verification fails, it will not cause the overall build to fail. {READ_MORE_PENDING}"
        )
    if query.provider_version_branch:
        verified_by = f"a version of {provider_name} from branch '{query.provider_version_branch}'"
    elif query.provider_version_tags:
        verified_by = f"a version of {provider_name} with tag {_join_quoted(query.provider_version_tags)}"
    else:
        verified_by = provider_name
    return (
        f"This pact has previously been successfully verified by {verified_by}. If this verification fails, it "
        f"will fail the build. {READ_MORE_PENDING}"
    )


def build_notices(
    pact: VerifiablePact, pact_url: str, query: ForVerificationQuery, provider_name: str
) -> List[Dict[str, str]]:
    """The ``verificationProperties.notices`` of one pact: what a verifier prints, and when.

    Args:
        pact: The selected pact.
        pact_url: Its for-verification URL.
        query: The request.
        provider_name: The verifying provider.

    Returns:
        ``[{"when", "text"}]``: the inclusion reason, and with ``includePendingStatus`` the pending
        reason and the four ``after_verification:…`` lines for a pending pact.
    """
    notices = [{"when": "before_verification", "text": inclusion_reason(pact, pact_url, provider_name)}]
    if not query.include_pending_status:
        return notices
    notices.append({"when": "before_verification", "text": pending_reason(pact, query, provider_name)})
    if pact.pending:
        about = _provider_description(query, provider_name, "any")
        tags = _with_these_tags(query)
        not_published = (
            f"This pact is still in pending state for {about} as a successful verification result {tags}has not "
            f"yet been published"
        )
        notices.extend(
            [
                {
                    "when": "after_verification:success_true_published_false",
                    "text": (
                        f"This pact is still in pending state for {about} as the successful verification results "
                        f"{tags}have not yet been published."
                    ),
                },
                {"when": "after_verification:success_false_published_false", "text": not_published},
                {
                    "when": "after_verification:success_true_published_true",
                    "text": (
                        f"This pact is no longer in pending state for {about}, as a successful verification result "
                        f"{tags}has been published. If a verification for a version of {provider_name} {tags}fails "
                        f"in the future, it will fail the build. {READ_MORE_PENDING}"
                    ),
                },
                {"when": "after_verification:success_false_published_true", "text": not_published},
            ]
        )
    return notices


def _short(selected: SelectedBy) -> str:
    """A selector in a few words (Pact Go names its test after these)."""
    selector = selected.selector
    kind = selector.kind
    if kind == KIND_OVERALL_LATEST:
        return "latest"
    if kind == KIND_LATEST_TAG:
        return f"latest with tag {selected.tag}"
    if kind == KIND_MAIN_BRANCH:
        return "latest from main branch"
    if kind == KIND_BRANCH:
        return f"latest from branch {selected.branch}"
    if kind == KIND_ALL_TAG:
        return f"one of {selector.consumer} {selector.tag}" if selector.consumer else f"one of {selector.tag}"
    if kind == KIND_DEPLOYED:
        return f"deployed to {selector.environment}"
    if kind == KIND_RELEASED:
        return f"released in {selector.environment}"
    return f"in environment {selector.environment}"


def short_description(pact: VerifiablePact) -> str:
    """The pact's ``shortDescription``: each reason in a few words, comma-separated."""
    return ", ".join(_short(selected) for selected in pact.selected_by)


# ---------------------------------------------------------------------------------------------
# The metadata segment of a for-verification URL
# ---------------------------------------------------------------------------------------------


def verification_metadata(pact: VerifiablePact) -> Dict[str, Any]:
    """What the broker stores in a for-verification URL so results can be traced back.

    ``s`` holds one entry per reason (``b`` branch, ``t`` tag, ``l`` latest, ``e`` environment,
    ``cv`` the consumer version id) and ``p`` the pending flag. PFX-1.4 reads it back when the
    verifier publishes its result to the URL.

    Args:
        pact: The selected pact.

    Returns:
        The metadata, with unset fields left out.
    """
    if pact.wip:
        return {"w": True}
    entries = []
    for selected in pact.selected_by:
        entry = {
            "b": selected.branch,
            "t": selected.tag,
            "l": selected.selector.latest,
            "e": selected.selector.environment,
            "cv": selected.candidate.version_id,
        }
        entries.append({key: value for key, value in entry.items() if value is not None})
    return {"s": entries, "p": pact.pending}


def _nested_query(value: Any, prefix: str) -> List[str]:
    """Rack's ``build_nested_query``: ``s[][b]=main&s[][cv]=…&p=true``."""
    if isinstance(value, Mapping):
        parts: List[str] = []
        for key, item in value.items():
            parts.extend(_nested_query(item, f"{prefix}[{quote_plus(str(key))}]" if prefix else quote_plus(str(key))))
        return parts
    if isinstance(value, list):
        parts = []
        for item in value:
            parts.extend(_nested_query(item, f"{prefix}[]"))
        return parts
    text = "true" if value is True else "false" if value is False else str(value)
    return [f"{prefix}={quote_plus(text)}"]


def encode_metadata(metadata: Mapping[str, Any]) -> str:
    """Encode metadata for a URL segment the way the broker does.

    Args:
        metadata: From :func:`verification_metadata`.

    Returns:
        URL-safe base64 of the nested query string, without padding.
    """
    query = "&".join(_nested_query(dict(metadata), ""))
    return base64.urlsafe_b64encode(query.encode("utf-8")).decode("ascii").rstrip("=")
