"""The Pact matrix and the can-i-deploy verdict — PFX-1.6 (#6919). Pure: no database, no HTTP.

The **matrix** is the table of every consumer version against every provider version, with the
verification result between them. **can-i-deploy** asks one question of it: *is this version safe
to deploy next to what is already there?* This module holds everything about that question that
does not need a database:

* reading a query the way a Pact Broker does (:func:`parse_matrix_query` for ``GET /matrix``,
  :func:`parse_can_i_deploy_query` for ``GET /can-i-deploy``);
* what a selector resolved to, and how it is described in a message (:class:`ResolvedSelector`);
* collapsing rows to the latest result (:func:`apply_latestby`), a row for every provider version
  in question (:func:`expand_unverified`) and setting ignored pacticipants aside
  (:func:`split_ignored`);
* **the verdict** (:func:`deployment_verdict`): ``deployable`` ``True`` / ``False`` / ``None``
  (unknown), the reasons in the Pact Broker's words, and the counts.

:func:`deployment_verdict` is the one verdict function. The routes call it, and the deploy gate's
contract signal (PFX-7.2) calls the same function, so the two can never disagree.

**How the verdict is reached** (the Pact Broker's rules, ``DeploymentStatusSummary``):

1. a version the caller named that does not exist → ``False``;
2. (Apiome) the target environment requires a contract and the version has none → ``False``;
3. any considered row without a verification result → ``None`` (unknown — retry later);
4. a required integration with no row at all → ``None``;
5. otherwise ``True`` when every considered row succeeded (also when there are no rows: nothing
   depends on the version), ``False`` when one failed.

A *considered* row is one no ``ignore`` selector matched. A consumer **requires** its providers; a
provider does not require its consumers — deploying a provider where no consumer runs is safe.

**Every version in the environment is checked.** Several versions of a provider can be live in one
environment (two application instances, a release still supported). A pact one of them verified
and another did not is *unknown*, not a pass: :func:`expand_unverified` gives the unverified
version its own row.

**Pending pacts do not soften the verdict.** A failed verification of a pending pact did not fail
the provider's build, but the consumer still cannot deploy against that provider, exactly as on a
Pact Broker. The row's reason says ``pact is pending`` so a reader sees why the provider's
pipeline is green.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qsl

from .bidirectional_verification import KIND_BIDIRECTIONAL, VERDICT_UNVERIFIED
from .pact_publication import PactPublicationError

__all__ = [
    "CODE_MATRIX_INVALID",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "REASON_NO_PACT",
    "REASON_NO_RESULT",
    "REASON_PENDING",
    "REASON_FAILED",
    "REASON_VERIFIED",
    "RETRY_AFTER_SECONDS",
    "Integration",
    "MatrixOptions",
    "MatrixResult",
    "MatrixRow",
    "Reason",
    "ResolvedSelector",
    "UnresolvedSelector",
    "Verdict",
    "apply_latestby",
    "apply_success_filter",
    "WARNING_PROVIDER_CONTRACT_UNVERIFIED",
    "deployment_verdict",
    "expand_unverified",
    "ignores",
    "parse_can_i_deploy_query",
    "parse_matrix_query",
    "resolve_selector",
    "row_reason",
    "sort_rows",
    "split_ignored",
]

#: A matrix or can-i-deploy query is malformed, or names something that does not exist (HTTP 400).
CODE_MATRIX_INVALID = "pact-matrix-invalid"

#: Rows returned when the query gives no ``limit`` (the Pact Broker's default).
DEFAULT_LIMIT = 100
#: The most rows one query may ask for.
MAX_LIMIT = 1000

#: The ``Retry-After`` hint, in seconds, of an unknown verdict — the ``pact-broker`` CLI's default
#: ``--retry-interval``.
RETRY_AFTER_SECONDS = 10

#: How rows may be collapsed: latest per consumer version and provider (``cvp``), per consumer
#: version and provider version (``cvpv``), or per consumer and provider (``cp``).
LATEST_BY = ("cvp", "cvpv", "cp")

# Why a row (or the whole verdict) reads the way it does. A client branches on these.
REASON_VERIFIED = "verified"
REASON_FAILED = "verification-failed"
REASON_PENDING = "pact-pending"
REASON_NO_RESULT = "no-verification-result"
REASON_NO_PACT = "no-pact"

#: The short text of each row reason.
_ROW_REASON_TEXT = {
    REASON_VERIFIED: "verified",
    REASON_FAILED: "verification failed",
    REASON_PENDING: "pact is pending",
    REASON_NO_RESULT: "no verification result",
}

#: The short text of a row whose result is a bi-directional comparison (PFX-2.3). Same codes.
_BIDIRECTIONAL_REASON_TEXT = {
    REASON_VERIFIED: "verified by bi-directional comparison",
    REASON_FAILED: "bi-directional comparison failed",
}

#: The same, when the provider contract had no passing self-verification evidence (PFX-2.4).
_UNVERIFIED_REASON_TEXT = {
    REASON_VERIFIED: "verified by bi-directional comparison; provider contract unverified",
    REASON_FAILED: "bi-directional comparison failed: provider contract unverified",
    REASON_PENDING: "pact is pending; provider contract unverified",
}

#: The warning code of a deployable verdict that leans on an unverified provider contract.
WARNING_PROVIDER_CONTRACT_UNVERIFIED = "provider-contract-unverified"

_NESTED_KEY = re.compile(r"^(?P<name>[A-Za-z]+)\[(?P<index>\d*)\](?:\[(?P<key>[A-Za-z]+)\])?$")


def _invalid(message: str, pointer: str) -> PactPublicationError:
    """A 400 for a query the matrix cannot answer."""
    return PactPublicationError(CODE_MATRIX_INVALID, message, pointer=pointer)


# ---------------------------------------------------------------------------------------------
# The query
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UnresolvedSelector:
    """One selector as the caller wrote it: a pacticipant, and optionally which of its versions.

    Attributes:
        pacticipant_name: The pacticipant.
        version_number: Exactly this version.
        latest: Only the latest of the versions the other fields describe.
        tag: Versions with this tag.
        branch: Versions recorded on this branch.
        environment_name: Versions currently deployed to, or released and supported in, this
            environment.
        main_branch: Versions on the pacticipant's main branch.
    """

    pacticipant_name: Optional[str] = None
    version_number: Optional[str] = None
    latest: bool = False
    tag: Optional[str] = None
    branch: Optional[str] = None
    environment_name: Optional[str] = None
    main_branch: bool = False

    @property
    def only_pacticipant_name(self) -> bool:
        """Whether nothing but the name was given — every version of the pacticipant."""
        return not (
            self.version_number or self.latest or self.tag or self.branch or self.environment_name or self.main_branch
        )


@dataclass(frozen=True)
class MatrixOptions:
    """Everything of a matrix query that is not a selector.

    Attributes:
        latestby: How rows are collapsed (one of :data:`LATEST_BY`), or ``None`` for every row.
        limit: The most rows to return.
        latest: The other side of each integration is its latest version (with ``tag``: the latest
            with that tag; with ``main_branch``: the latest on the main branch).
        tag: The other side is the version(s) with this tag — ``can-i-deploy --to``.
        environment_name: The other side is whatever is in this environment —
            ``can-i-deploy --to-environment``.
        main_branch: The other side is each pacticipant's main branch.
        ignore_selectors: Pacticipants (or single versions) whose rows do not count.
        success: Keep only rows with one of these results (``None`` is "no result"); ``None`` to
            keep all.
    """

    latestby: Optional[str] = None
    limit: int = DEFAULT_LIMIT
    latest: bool = False
    tag: Optional[str] = None
    environment_name: Optional[str] = None
    main_branch: bool = False
    ignore_selectors: Tuple[UnresolvedSelector, ...] = ()
    success: Optional[Tuple[Optional[bool], ...]] = None

    @property
    def infers_selectors(self) -> bool:
        """Whether the query names a destination, so the other pacticipants are worked out."""
        return bool(self.latest or self.tag or self.environment_name or self.main_branch)


def _nested(pairs: Sequence[Tuple[str, str]], name: str) -> List[Any]:
    """Collect ``name[][key]=value`` and ``name[]=value`` parameters the way Rack does.

    ``q[][pacticipant]=A&q[][version]=1&q[][pacticipant]=B`` is two entries: a key that the entry
    being filled already has starts the next entry. An explicit index (``q[0][pacticipant]=A``)
    names its entry instead.

    Args:
        pairs: The decoded query parameters, in order.
        name: The parameter family (``q``, ``ignore``, ``success``).

    Returns:
        The entries in order: a ``dict`` for keyed entries, a ``str`` for plain ``name[]=value``.
    """
    entries: List[Any] = []
    indexed: Dict[str, Dict[str, str]] = {}
    for raw_key, value in pairs:
        match = _NESTED_KEY.match(raw_key)
        if not match or match.group("name") != name:
            continue
        key, index = match.group("key"), match.group("index")
        if key is None:
            entries.append(value)
        elif index:
            if index not in indexed:
                indexed[index] = {}
                entries.append(indexed[index])
            indexed[index][key] = value
        else:
            last = entries[-1] if entries else None
            if not isinstance(last, dict) or key in last or any(last is entry for entry in indexed.values()):
                last = {}
                entries.append(last)
            last[key] = value
    return entries


def _text(value: Any) -> Optional[str]:
    """A parameter's value, or ``None`` when it is absent or empty."""
    return value if isinstance(value, str) and value != "" else None


def _selector_from(entry: Mapping[str, str]) -> UnresolvedSelector:
    """Read one ``q[]`` or ``ignore[]`` entry."""
    return UnresolvedSelector(
        pacticipant_name=_text(entry.get("pacticipant")),
        version_number=_text(entry.get("version")),
        latest=entry.get("latest") == "true",
        tag=_text(entry.get("tag")),
        branch=_text(entry.get("branch")),
        environment_name=_text(entry.get("environment")),
        main_branch=entry.get("mainBranch") == "true",
    )


def _scalar(pairs: Sequence[Tuple[str, str]], name: str) -> Optional[str]:
    """The last non-empty value of a plain parameter."""
    found = None
    for key, value in pairs:
        if key == name and value != "":
            found = value
    return found


def _limit(pairs: Sequence[Tuple[str, str]]) -> int:
    """Read ``limit``: a whole number from 1 to :data:`MAX_LIMIT`."""
    raw = _scalar(pairs, "limit")
    if raw is None:
        return DEFAULT_LIMIT
    if not raw.isdigit() or int(raw) < 1:
        raise _invalid("The limit must be 1 or greater.", "/limit")
    if int(raw) > MAX_LIMIT:
        raise _invalid(f"The limit must not exceed {MAX_LIMIT}.", "/limit")
    return int(raw)


def _check_selectors(selectors: Sequence[UnresolvedSelector], options: MatrixOptions) -> None:
    """Refuse what a Pact Broker refuses (``Matrix::Service.validate_selectors``).

    Raises:
        PactPublicationError: ``pact-matrix-invalid`` with the broker's message.
    """
    if not selectors:
        raise _invalid("Please provide 1 or more version selectors.", "/q")
    for index, selector in enumerate(selectors):
        if not selector.pacticipant_name:
            raise _invalid("Please specify the pacticipant name", f"/q/{index}/pacticipant")
        if selector.version_number and selector.latest:
            raise _invalid(
                f"A version number and latest flag cannot both be specified for {selector.pacticipant_name}",
                f"/q/{index}",
            )
    for index, selector in enumerate(options.ignore_selectors):
        if not selector.pacticipant_name:
            raise _invalid("Please specify the pacticipant name to ignore", f"/ignore/{index}/pacticipant")
        if selector.version_number and selector.latest:
            raise _invalid(
                f"A version number and latest flag cannot both be specified for {selector.pacticipant_name} to ignore",
                f"/ignore/{index}",
            )
    destinations = [d for d in (options.tag, options.environment_name, "main" if options.main_branch else None) if d]
    if len(destinations) > 1:
        raise _invalid("Cannot specify more than one of tag, environment and mainBranch.", "/environment")
    if options.latest and options.environment_name:
        raise _invalid("Cannot specify both latest=true and an environment.", "/environment")


def parse_matrix_query(query_string: str) -> Tuple[List[UnresolvedSelector], MatrixOptions]:
    """Read the query string of ``GET /matrix`` as a Pact Broker does.

    ``q[][pacticipant]`` with ``q[][version]``, ``q[][latest]``, ``q[][tag]``, ``q[][branch]``,
    ``q[][environment]`` and ``q[][mainBranch]`` are the selectors; ``latestby``, ``limit``,
    ``latest``, ``tag``, ``environment``, ``mainBranch``, ``success[]`` and ``ignore[][pacticipant]``
    (with ``ignore[][version]``) the options.

    Args:
        query_string: The raw query string, still percent-encoded.

    Returns:
        The selectors and the options.

    Raises:
        PactPublicationError: ``pact-matrix-invalid`` — no selector, a selector without a
            pacticipant, a version together with ``latest``, more than one destination, an unknown
            ``latestby`` or a ``limit`` out of range.
    """
    pairs = parse_qsl(query_string or "", keep_blank_values=True)
    selectors = [_selector_from(entry) for entry in _nested(pairs, "q") if isinstance(entry, dict)]
    latestby = _scalar(pairs, "latestby")
    if latestby is not None and latestby not in LATEST_BY:
        raise _invalid(f"latestby must be one of {', '.join(LATEST_BY)}.", "/latestby")
    success_values = [entry for entry in _nested(pairs, "success") if isinstance(entry, str)]
    success_values += [value for key, value in pairs if key == "success"]
    has_success = bool(success_values)
    options = MatrixOptions(
        latestby=latestby,
        limit=_limit(pairs),
        latest=_scalar(pairs, "latest") == "true",
        tag=_scalar(pairs, "tag"),
        environment_name=_scalar(pairs, "environment"),
        main_branch=_scalar(pairs, "mainBranch") == "true",
        ignore_selectors=tuple(_selector_from(entry) for entry in _nested(pairs, "ignore") if isinstance(entry, dict)),
        success=tuple(None if value == "" else value == "true" for value in success_values) if has_success else None,
    )
    _check_selectors(selectors, options)
    return selectors, options


def parse_can_i_deploy_query(query_string: str) -> Tuple[List[UnresolvedSelector], MatrixOptions]:
    """Read the query string of ``GET /can-i-deploy``.

    ``pacticipant`` and ``version`` name what is being deployed; ``to`` (a tag) or
    ``toEnvironment`` (an environment; the Pact Broker's ``environment`` is accepted too) names
    where. ``ignore`` names pacticipants whose rows do not count: ``ignore=Name``,
    ``ignore[]=Name``, or ``ignore[][pacticipant]=Name`` with an optional ``ignore[][version]``.

    To a tag, each other pacticipant is its latest version with that tag and rows collapse per
    consumer version and provider. To an environment, every version there is checked on its own
    (several can be live at once), so rows collapse per consumer version and provider *version*.

    Args:
        query_string: The raw query string, still percent-encoded.

    Returns:
        The one selector and the options.

    Raises:
        PactPublicationError: ``pact-matrix-invalid`` — ``pacticipant`` or ``version`` missing,
            both a tag and an environment, or neither.
    """
    pairs = parse_qsl(query_string or "", keep_blank_values=True)
    pacticipant, version = _scalar(pairs, "pacticipant"), _scalar(pairs, "version")
    if not pacticipant:
        raise _invalid("pacticipant is missing", "/pacticipant")
    if not version:
        raise _invalid("version is missing", "/version")
    tag = _scalar(pairs, "to")
    environment = _scalar(pairs, "toEnvironment") or _scalar(pairs, "environment")
    if tag and environment:
        raise _invalid("Cannot specify both a 'to' tag and an environment.", "/toEnvironment")
    if not tag and not environment:
        raise _invalid("Must specify either an environment or a 'to' tag.", "/toEnvironment")
    ignore: List[UnresolvedSelector] = [
        UnresolvedSelector(pacticipant_name=value) for key, value in pairs if key == "ignore" and value
    ]
    for entry in _nested(pairs, "ignore"):
        if isinstance(entry, str) and entry:
            ignore.append(UnresolvedSelector(pacticipant_name=entry))
        elif isinstance(entry, dict) and entry.get("pacticipant"):
            ignore.append(
                UnresolvedSelector(pacticipant_name=entry["pacticipant"], version_number=_text(entry.get("version")))
            )
    options = MatrixOptions(
        latestby="cvpv" if environment else "cvp",
        latest=bool(tag),
        tag=tag,
        environment_name=environment,
        ignore_selectors=tuple(ignore),
    )
    return [UnresolvedSelector(pacticipant_name=pacticipant, version_number=version)], options


# ---------------------------------------------------------------------------------------------
# Resolved selectors
# ---------------------------------------------------------------------------------------------

SPECIFIED = "specified"
INFERRED = "inferred"
IGNORED = "ignored"


@dataclass(frozen=True)
class ResolvedSelector:
    """A selector matched against the registry: one pacticipant and, usually, one version.

    A selector that describes several versions (every version with a tag) becomes one of these per
    version. A selector that names only the pacticipant has no version: it stands for all of them.

    Attributes:
        pacticipant_name: The pacticipant's name (as asked for, when it does not exist).
        original: The selector this came from; an empty one for a selector made up from a row.
        kind: ``specified`` (the caller wrote it), ``inferred`` (worked out from the destination)
            or ``ignored`` (an ``ignore`` selector).
        pacticipant_id: The pacticipant's id; ``None`` when no such pacticipant exists.
        pacticipant_slug: Its handle.
        version_id: The version's id; ``None`` for "all versions" or a version that does not exist.
        version_number: The version number — the one asked for when it does not exist.
        version_missing: The selector describes a version and none matched.
        branch: The branch the version was selected from (the main branch's name for
            ``mainBranch``).
        ignore: Whether an ``ignore`` selector covers it.
        one_of_many: Whether the original selector matched several versions.
    """

    pacticipant_name: str
    original: UnresolvedSelector = field(default_factory=UnresolvedSelector)
    kind: str = INFERRED
    pacticipant_id: Optional[str] = None
    pacticipant_slug: Optional[str] = None
    version_id: Optional[str] = None
    version_number: Optional[str] = None
    version_missing: bool = False
    branch: Optional[str] = None
    ignore: bool = False
    one_of_many: bool = False

    @property
    def specified(self) -> bool:
        """Whether the caller wrote this selector."""
        return self.kind == SPECIFIED

    @property
    def consider(self) -> bool:
        """Whether it counts towards the verdict (it is not ignored)."""
        return not self.ignore

    @property
    def pacticipant_missing(self) -> bool:
        """Whether no pacticipant has this name."""
        return self.pacticipant_id is None

    @property
    def only_pacticipant_name(self) -> bool:
        """Whether the original selector gave nothing but the name."""
        return self.original.only_pacticipant_name

    @property
    def description(self) -> str:
        """How the selector reads in a reason — the Pact Broker's ``ResolvedSelector#description``."""
        name, number, original = self.pacticipant_name, self.version_number, self.original
        resolved = None if self.version_missing and not original.version_number else number
        tag, branch, environment = original.tag, self.branch or original.branch, original.environment_name
        if original.latest and tag:
            return f"the latest version of {name} with tag {tag} ({resolved or 'no such version exists'})"
        if original.main_branch and resolved is None:
            which = "the latest" if original.latest else "any"
            return f"{which} version of {name} from the main branch (no versions exist for this branch)"
        if original.latest and branch:
            return f"the latest version of {name} from branch {branch} ({resolved or 'no such version exists'})"
        if branch and resolved:
            prefix = "one of the versions" if self.one_of_many else "the version"
            return f"{prefix} of {name} from branch {branch} ({resolved})"
        if branch:
            return f"a version of {name} from branch {branch} (no such version exists)"
        if original.latest:
            return f"the latest version of {name} ({resolved or 'no such version exists'})"
        if tag:
            return f"a version of {name} with tag {tag} ({resolved or 'no such version exists'})"
        if environment and resolved:
            prefix = "one of the versions" if self.one_of_many else "the version"
            return f"{prefix} of {name} currently in {environment} ({resolved})"
        if environment:
            return (
                f"a version of {name} currently in {environment} "
                "(no version is currently recorded as deployed/released in this environment)"
            )
        if number and self.version_missing:
            return f"version {number} of {name} (no such version exists)"
        if number:
            return f"version {number} of {name}"
        if self.pacticipant_missing:
            return f"any version of {name} (no such pacticipant exists)"
        return f"any version of {name}"

    @property
    def version_does_not_exist_description(self) -> str:
        """The error for a version the caller named that does not exist."""
        name, original = self.pacticipant_name, self.original
        if original.tag:
            return f"No version with tag {original.tag} exists for {name}"
        if original.branch:
            return f"No version of {name} from branch {original.branch} exists"
        if original.main_branch:
            return f"No version of {name} from the main branch exists"
        if original.environment_name:
            return (
                f"No version of {name} is currently recorded as deployed or released in environment "
                f"{original.environment_name}"
            )
        if self.version_number:
            return f"No pacts or verifications have been published for version {self.version_number} of {name}"
        return f"No pacts or verifications have been published for {name}"


def ignores(
    ignore_selectors: Sequence[ResolvedSelector], pacticipant_id: Optional[str], version_id: Optional[str]
) -> bool:
    """Whether an ``ignore`` selector covers a pacticipant version.

    Args:
        ignore_selectors: The resolved ``ignore`` selectors.
        pacticipant_id: The pacticipant.
        version_id: Its version; ``None`` asks about the pacticipant as a whole, which only an
            ``ignore`` selector without a version covers.

    Returns:
        ``True`` when one of them names the pacticipant and either no version or this one.
    """
    if pacticipant_id is None:
        return False
    return any(
        s.pacticipant_id == pacticipant_id
        and (s.only_pacticipant_name or (version_id is not None and s.version_id == version_id))
        for s in ignore_selectors
    )


def resolve_selector(
    unresolved: UnresolvedSelector,
    kind: str,
    pacticipant: Optional[Mapping[str, Any]],
    versions: Optional[Sequence[Mapping[str, Any]]],
    ignore_selectors: Sequence[ResolvedSelector] = (),
) -> List[ResolvedSelector]:
    """Turn a selector and what the registry found for it into resolved selectors.

    Args:
        unresolved: The selector as written.
        kind: ``specified``, ``inferred`` or ``ignored``.
        pacticipant: The pacticipant (``id``, ``slug``, ``name``, ``main_branch``), or ``None``
            when no pacticipant has that name.
        versions: The versions it matched (``id``, ``number``), latest first; ``None`` when the
            selector names only the pacticipant (all versions); empty when none matched.
        ignore_selectors: The resolved ``ignore`` selectors, to mark what they cover.

    Returns:
        One selector per matched version; one without a version for "all versions"; one marked
        ``version_missing`` when nothing matched; one without a pacticipant when it does not exist.
    """
    name = unresolved.pacticipant_name or ""
    if pacticipant is None:
        return [ResolvedSelector(pacticipant_name=name, original=unresolved, kind=kind)]
    common: Dict[str, Any] = {
        "pacticipant_name": pacticipant["name"],
        "original": unresolved,
        "kind": kind,
        "pacticipant_id": pacticipant["id"],
        "pacticipant_slug": pacticipant["slug"],
    }
    if versions is None:
        return [ResolvedSelector(**common, ignore=ignores(ignore_selectors, pacticipant["id"], None))]
    branch = unresolved.branch or (pacticipant.get("main_branch") if unresolved.main_branch else None)
    if not versions:
        return [
            ResolvedSelector(
                **common,
                version_number=unresolved.version_number,
                version_missing=True,
                branch=unresolved.branch,
                ignore=ignores(ignore_selectors, pacticipant["id"], None),
            )
        ]
    return [
        ResolvedSelector(
            **common,
            version_id=version["id"],
            version_number=version["number"],
            branch=branch,
            ignore=ignores(ignore_selectors, pacticipant["id"], version["id"]),
            one_of_many=len(versions) > 1,
        )
        for version in versions
    ]


# ---------------------------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MatrixRow:
    """One line of the matrix: a pact a consumer version published, and one verification of it.

    ``provider_version_*`` and the verification fields are ``None`` when the pact has no result
    from any provider version the query asked about.

    Attributes:
        consumer_id / consumer_slug / consumer_name: The consumer.
        consumer_version_id / consumer_version_number / consumer_version_seq: Its version, and the
            order it was recorded in.
        provider_id / provider_slug / provider_name: The provider.
        pact_sha: The content address of the pact.
        pact_created_at: When this consumer version published it (ISO 8601).
        pact_revision: The publication's revision.
        provider_version_id / provider_version_number / provider_version_seq: The verifying
            provider version.
        verification_number: The result's number within its pact version.
        verification_seq: The order results were recorded in.
        success: ``True`` / ``False``; ``None`` without a result.
        verified_at: When the result was published (ISO 8601).
        pact_pending: Whether the verifier was told the pact was pending for that build.
        wip: Whether the pact was verified as a work-in-progress pact.
        verification_kind: ``native`` (a Pact verifier published the result) or ``bidirectional``
            (Apiome compared the pact with the provider contract, PFX-2.3); ``None`` without a
            result. The verdict reads both kinds the same way.
        comparison_verdict: For a bi-directional result, the comparison's verdict (``pass``,
            ``partial``, ``fail`` or ``unverified`` — the provider contract had no passing
            self-verification evidence, PFX-2.4); ``None`` otherwise.
    """

    consumer_id: str
    consumer_slug: str
    consumer_name: str
    consumer_version_id: str
    consumer_version_number: str
    consumer_version_seq: int
    provider_id: str
    provider_slug: str
    provider_name: str
    pact_sha: str
    pact_created_at: Optional[str] = None
    pact_revision: int = 1
    provider_version_id: Optional[str] = None
    provider_version_number: Optional[str] = None
    provider_version_seq: Optional[int] = None
    verification_number: Optional[int] = None
    verification_seq: Optional[int] = None
    success: Optional[bool] = None
    verified_at: Optional[str] = None
    pact_pending: Optional[bool] = None
    wip: bool = False
    verification_kind: Optional[str] = None
    comparison_verdict: Optional[str] = None

    @property
    def bidirectional(self) -> bool:
        """Whether the row's result is a bi-directional comparison."""
        return self.verification_kind == KIND_BIDIRECTIONAL

    @property
    def provider_contract_unverified(self) -> bool:
        """Whether the row's bi-directional result compared a provider contract without passing evidence."""
        return self.bidirectional and self.comparison_verdict == VERDICT_UNVERIFIED


@dataclass(frozen=True)
class Integration:
    """A consumer and a provider that have a pact between them.

    Attributes:
        consumer_id / consumer_name: The consumer.
        provider_id / provider_name: The provider.
        required: Whether the verdict needs a row for it. ``True`` when the version being deployed
            is the consumer (it needs its provider to be there); ``False`` when it is the provider.
    """

    consumer_id: str
    consumer_name: str
    provider_id: str
    provider_name: str
    required: bool


def row_reason(row: MatrixRow) -> Dict[str, str]:
    """Why one row reads the way it does.

    Args:
        row: The row.

    Returns:
        ``{"code", "text"}`` — ``verified``; ``pact-pending`` ("pact is pending": the result failed
        but the pact was pending for that provider build, so the build did not fail);
        ``verification-failed``; or ``no-verification-result``. A bi-directional result keeps the
        code and says so in the text ("verified by bi-directional comparison"), and says when its
        provider contract was unverified ("…; provider contract unverified").
    """
    if row.success is None:
        code = REASON_NO_RESULT
    elif row.success:
        code = REASON_VERIFIED
    else:
        code = REASON_PENDING if row.pact_pending else REASON_FAILED
    if row.provider_contract_unverified:
        texts = _UNVERIFIED_REASON_TEXT
    else:
        texts = _BIDIRECTIONAL_REASON_TEXT if row.bidirectional else {}
    return {"code": code, "text": texts.get(code, _ROW_REASON_TEXT[code])}


def _latest_of(rows: Sequence[MatrixRow]) -> MatrixRow:
    """The row of a group to keep: the one without a result, else the latest provider version's."""
    if rows[0].provider_version_number is None:
        return rows[0]
    return max(rows, key=lambda row: (row.provider_version_seq or 0, row.verification_seq or 0))


def apply_latestby(rows: Sequence[MatrixRow], latestby: Optional[str]) -> List[MatrixRow]:
    """Collapse rows to the latest result of each group.

    Args:
        rows: The rows.
        latestby: ``cvpv`` (one row per consumer version and provider version), ``cvp`` (per
            consumer version and provider), ``cp`` (per consumer and provider), or ``None`` to
            keep every row.

    Returns:
        One row per group, in the order the groups first appear.
    """
    if not latestby:
        return list(rows)
    groups: Dict[Tuple[Any, ...], List[MatrixRow]] = {}
    for row in rows:
        key: Tuple[Any, ...] = (row.consumer_id, row.provider_id)
        if latestby in ("cvp", "cvpv"):
            key += (row.consumer_version_id,)
        if latestby == "cvpv":
            key += (row.provider_version_id,)
        groups.setdefault(key, []).append(row)
    return [_latest_of(group) for group in groups.values()]


def expand_unverified(rows: Sequence[MatrixRow], selectors: Sequence[ResolvedSelector]) -> List[MatrixRow]:
    """Give every provider version in question its own row, also when it has no result.

    A pact is joined to the results of the provider versions a query selects. When several
    versions of one provider are selected — two are live in the environment at once — and only one
    of them verified the pact, the join returns that one row and the other version would go
    unnoticed. This adds a row without a result for each selected version of that provider the
    pact has no row for, replacing the pact's version-less "no result" row.

    Providers with a single selected version are left exactly as read.

    Args:
        rows: The rows, after ``latestby``.
        selectors: Every resolved selector of the query.

    Returns:
        The rows, with one per consumer version and selected provider version.
    """
    versions: Dict[str, List[ResolvedSelector]] = {}
    for selector in selectors:
        if selector.pacticipant_id and selector.version_id:
            versions.setdefault(selector.pacticipant_id, []).append(selector)
    several = {pacticipant: found for pacticipant, found in versions.items() if len(found) > 1}
    if not several:
        return list(rows)
    groups: Dict[Tuple[str, str], List[MatrixRow]] = {}
    for row in rows:
        groups.setdefault((row.consumer_version_id, row.provider_id), []).append(row)
    expanded: List[MatrixRow] = []
    for (_, provider_id), group in groups.items():
        if provider_id not in several:
            expanded += group
            continue
        expanded += [row for row in group if row.provider_version_id is not None]
        verified = {row.provider_version_id for row in group}
        expanded += [
            replace(
                group[0],
                provider_version_id=selector.version_id,
                provider_version_number=selector.version_number,
                provider_version_seq=None,
                verification_number=None,
                verification_seq=None,
                success=None,
                verified_at=None,
                pact_pending=None,
                wip=False,
                verification_kind=None,
            )
            for selector in several[provider_id]
            if selector.version_id not in verified
        ]
    return expanded


def apply_success_filter(rows: Sequence[MatrixRow], success: Optional[Sequence[Optional[bool]]]) -> List[MatrixRow]:
    """Keep the rows whose result is one of ``success`` (``None`` keeps all)."""
    if success is None:
        return list(rows)
    return [row for row in rows if row.success in success]


def split_ignored(
    rows: Sequence[MatrixRow], ignore_selectors: Sequence[ResolvedSelector]
) -> Tuple[List[MatrixRow], List[MatrixRow]]:
    """Set aside the rows an ``ignore`` selector covers.

    Args:
        rows: The rows.
        ignore_selectors: The resolved ``ignore`` selectors.

    Returns:
        The considered rows and the ignored rows.
    """
    considered: List[MatrixRow] = []
    ignored: List[MatrixRow] = []
    for row in rows:
        covered = ignores(ignore_selectors, row.consumer_id, row.consumer_version_id) or ignores(
            ignore_selectors, row.provider_id, row.provider_version_id
        )
        (ignored if covered else considered).append(row)
    return considered, ignored


def sort_rows(rows: Sequence[MatrixRow]) -> List[MatrixRow]:
    """Order rows for reading: by consumer, newest consumer version first, then provider, newest first."""
    return sorted(
        rows,
        key=lambda row: (
            row.consumer_name.lower(),
            -row.consumer_version_seq,
            row.provider_name.lower(),
            -(row.provider_version_seq or 0),
            -(row.verification_seq or 0),
        ),
    )


# ---------------------------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Reason:
    """One line of the verdict's explanation.

    Attributes:
        type: ``success``, ``error`` or ``warning`` — a Pact Broker notice type.
        code: What kind of reason it is; a client branches on this.
        text: The sentence, in the Pact Broker's wording.
    """

    type: str
    code: str
    text: str


@dataclass(frozen=True)
class MatrixResult:
    """Everything the verdict is computed from.

    Attributes:
        considered_rows: The rows that count.
        ignored_rows: The rows an ``ignore`` selector covered.
        selectors: The resolved selectors: the ones the caller wrote, then the inferred ones.
        ignore_selectors: The resolved ``ignore`` selectors.
        integrations: The integrations the query involves.
        options: The query's options.
        uncontracted: Specified selectors whose version has no pact at all, when the target
            environment requires a contract (Apiome's ``contractRequired``).
    """

    considered_rows: Sequence[MatrixRow] = ()
    ignored_rows: Sequence[MatrixRow] = ()
    selectors: Sequence[ResolvedSelector] = ()
    ignore_selectors: Sequence[ResolvedSelector] = ()
    integrations: Sequence[Integration] = ()
    options: MatrixOptions = field(default_factory=MatrixOptions)
    uncontracted: Sequence[ResolvedSelector] = ()


@dataclass(frozen=True)
class Verdict:
    """The answer to "can I deploy?".

    Attributes:
        deployable: ``True`` (yes), ``False`` (no) or ``None`` (unknown: a result is missing).
        reasons: Why, in order: warnings, then the errors or the success line.
        counts: ``success``, ``failed`` and ``unknown`` rows, and ``ignored`` when the query
            ignored anything.
    """

    deployable: Optional[bool]
    reasons: Tuple[Reason, ...]
    counts: Dict[str, int]

    @property
    def reason(self) -> str:
        """Every reason, one per line — the Pact Broker's ``summary.reason``."""
        return "\n".join(reason.text for reason in self.reasons)

    @property
    def unknown(self) -> bool:
        """Whether the verdict is waiting on a verification result."""
        return self.deployable is None


def _dummy_selectors(rows: Sequence[MatrixRow], integrations: Sequence[Integration]) -> List[ResolvedSelector]:
    """Selectors made up from the rows and integrations, for rows no real selector explains.

    When the query names no destination, the other side of each row was never resolved to a
    selector; a reason still has to name it.
    """
    dummies: List[ResolvedSelector] = []
    for row in rows:
        dummies.append(
            ResolvedSelector(
                pacticipant_name=row.consumer_name,
                pacticipant_id=row.consumer_id,
                version_id=row.consumer_version_id,
                version_number=row.consumer_version_number,
            )
        )
        dummies.append(
            ResolvedSelector(
                pacticipant_name=row.provider_name,
                pacticipant_id=row.provider_id,
                version_id=row.provider_version_id,
                version_number=row.provider_version_number,
            )
        )
    for integration in integrations:
        dummies.append(
            ResolvedSelector(pacticipant_name=integration.consumer_name, pacticipant_id=integration.consumer_id)
        )
        dummies.append(
            ResolvedSelector(pacticipant_name=integration.provider_name, pacticipant_id=integration.provider_id)
        )
    return dummies


def _selector_for(
    selectors: Sequence[ResolvedSelector], dummies: Sequence[ResolvedSelector], name: str, number: Optional[str]
) -> ResolvedSelector:
    """The selector that put a pacticipant version into the matrix, to describe it in a reason."""
    found = [s for s in selectors if s.pacticipant_name == name]
    if len(found) == 1:
        return found[0]
    if number is not None:
        for selector in found:
            if selector.version_number == number:
                return selector
    for dummy in dummies:
        if dummy.pacticipant_name == name:
            return dummy
    return ResolvedSelector(pacticipant_name=name)


def _unique(reasons: Sequence[Reason]) -> List[Reason]:
    """Drop repeated reasons, keeping the first of each."""
    seen = set()
    kept = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            kept.append(reason)
    return kept


def _warnings(result: MatrixResult) -> List[Reason]:
    """Ignore selectors that match nothing, and queries whose answer cannot be relied on."""
    selectors, options = result.selectors, result.options
    warnings = [
        Reason("warning", "cannot-ignore", f"WARN: Cannot ignore {s.description}")
        for s in result.ignore_selectors
        if s.pacticipant_missing or s.version_missing
    ]
    specified = [s for s in selectors if s.specified]
    if len(specified) == 1 and not (options.tag or options.environment_name or options.main_branch):
        warnings.append(
            Reason(
                "warning",
                "no-environment-specified",
                "WARN: It is recommended to specify the environment into which you are deploying. "
                "Without the environment, this result will not be reliable.",
            )
        )
    versioned = [s for s in specified if not s.only_pacticipant_name]
    if versioned and not any(s.original.version_number for s in specified):
        warnings.append(
            Reason(
                "warning",
                "no-version-specified",
                "WARN: It is recommended to specify the version number (rather than the tag or branch) of the "
                "pacticipant you wish to deploy to avoid race conditions. Without a version number, this result "
                "will not be reliable.",
            )
        )
    # PFX-2.4: a passing bi-directional result whose provider contract had no passing
    # self-verification evidence (the ``warn`` policy) counts, but is said to be unverified.
    for row in result.considered_rows:
        if row.provider_contract_unverified and row.success:
            warnings.append(
                Reason(
                    "warning",
                    WARNING_PROVIDER_CONTRACT_UNVERIFIED,
                    f"WARN: The provider contract of {row.provider_name} {row.provider_version_number} has no "
                    f"passing self-verification evidence, so its bi-directional comparison with "
                    f"{row.consumer_name} {row.consumer_version_number} is unverified.",
                )
            )
    return warnings


def deployment_verdict(result: MatrixResult) -> Verdict:
    """Decide whether the queried versions can be deployed, and say why.

    Pure: the same :class:`MatrixResult` always gives the same :class:`Verdict`. Shared by the
    matrix and can-i-deploy routes and by the deploy gate's contract signal (PFX-7.2).

    Args:
        result: The rows, selectors and integrations of one matrix query.

    Returns:
        The verdict. See the module docstring for the rules.
    """
    considered = list(result.considered_rows)
    all_rows = considered + list(result.ignored_rows)
    selectors = list(result.selectors)
    dummies = _dummy_selectors(considered, result.integrations)

    missing_versions = [s for s in selectors if s.consider and s.specified and s.version_missing]
    uncontracted = [s for s in result.uncontracted if s.consider]
    missing_integrations = [
        integration
        for integration in result.integrations
        if integration.required
        and not any(
            row.consumer_id == integration.consumer_id and row.provider_id == integration.provider_id
            for row in all_rows
        )
    ]
    unknown_rows = [row for row in considered if row.success is None]
    failed_rows = [row for row in considered if row.success is False]

    deployable: Optional[bool]
    if missing_versions or uncontracted:
        deployable = False
    elif unknown_rows or missing_integrations:
        deployable = None
    else:
        deployable = not failed_rows

    def between(consumer: str, consumer_version: Optional[str], provider: str, provider_version: Optional[str]) -> str:
        left = _selector_for(selectors, dummies, consumer, consumer_version).description
        right = _selector_for(selectors, dummies, provider, provider_version).description
        return f"{left} and {right}"

    errors: List[Reason] = [
        Reason("error", "version-not-found", s.version_does_not_exist_description) for s in missing_versions
    ]
    if not errors:
        environment = result.options.environment_name
        errors += [
            Reason(
                "error",
                REASON_NO_PACT,
                f"No pact has been published for {s.description}, and environment {environment} requires a contract",
            )
            for s in uncontracted
        ]
        errors += [
            Reason(
                "error",
                REASON_NO_RESULT,
                "There is no verified pact between "
                + between(integration.consumer_name, None, integration.provider_name, None),
            )
            for integration in missing_integrations
        ]
        errors += [
            Reason(
                "error",
                row_reason(row)["code"],
                (
                    "The bi-directional comparison of the pact between "
                    if row.bidirectional
                    else "The verification for the pact between "
                )
                + between(
                    row.consumer_name, row.consumer_version_number, row.provider_name, row.provider_version_number
                )
                + (" with its provider contract failed" if row.bidirectional else " failed"),
            )
            for row in failed_rows
        ]
        errors += [
            Reason(
                "error",
                REASON_NO_RESULT,
                "There is no verified pact between "
                + between(
                    row.consumer_name, row.consumer_version_number, row.provider_name, row.provider_version_number
                ),
            )
            for row in unknown_rows
        ]

    if errors:
        outcome = _unique(errors)
    elif considered:
        outcome = [Reason("success", REASON_VERIFIED, "All required verification results are published and successful")]
    else:
        outcome = [Reason("success", "no-dependencies", "There are no missing dependencies")]

    counts = {
        "success": sum(1 for row in considered if row.success is True),
        "failed": len(failed_rows),
        "unknown": len(missing_integrations) + len(unknown_rows),
    }
    if result.ignore_selectors:
        counts["ignored"] = len(result.ignored_rows)
    return Verdict(deployable=deployable, reasons=tuple(_warnings(result) + outcome), counts=counts)
