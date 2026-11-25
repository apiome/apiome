"""The provider-state registry — what a state is and how it is set up, PFX-3.3 (#6933).

A pact interaction says "given an invoice 1042 exists" (``providerStates[].name``, with
parameters such as ``{"id": 1042}``). The hosted verifier (PFX-3.2) can only replay it once the
provider is in that state. A provider declares here, once, each state it knows how to reach:

* its **name**, exactly as consumers write it;
* the **parameters** it takes — which are required, and the default of one that is not;
* its **setup** — one of two kinds:

  ==================  ===========================================================================
  ``state_change``    Call a state-change URL with the Pact state-change body
                      ``{"state", "params", "action": "setup"}`` (and ``"teardown"`` after the
                      interaction, unless ``teardown`` is false). A **path** (``/_pact/states``)
                      is sent to the verification target, with the target's credential; an
                      absolute ``https://`` URL is sent through the SSRF guard with none.
  ``fixture``         A recorded fixture: the requests that put the target into the state
                      (``requests``) and take it out again (``teardown_requests``), sent to the
                      verification target. An empty ``requests`` list says the target already
                      holds the recorded data. ``${param}`` in a path, header value or string in
                      the body is replaced with the parameter's value.
  ==================  ===========================================================================

* optional **per-target overrides** — a different setup for one verification target.

This module has no I/O: it checks what is stored and decides, for the states an interaction
names, whether they can be set up (:func:`state_issue`, :func:`check_states`). The database is
:mod:`app.pact_provider_state_store`; the HTTP calls are :mod:`app.pact_provider_state_handler`.

**Nothing is dropped silently.** A state no consumer can match, a placeholder that names no
parameter, a header carrying a credential: each is refused when the state is saved, with a JSON
Pointer to the place. A state an interaction names that is not registered, a required parameter
the interaction does not supply, or a parameter the state does not declare is **flagged** by the
check before a run, and the first two hold the interaction back in the run itself.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .contract_suite import PactProviderState
from .pact_publication import PactPublicationError

__all__ = [
    "CODE_PARAM_MISSING",
    "CODE_PARAM_UNDECLARED",
    "CODE_SETUP_BLOCKED",
    "CODE_STATE_INVALID",
    "CODE_STATE_NAME_TAKEN",
    "CODE_STATE_NOT_FOUND",
    "CODE_STATE_NOT_REGISTERED",
    "MAX_FIXTURE_REQUESTS",
    "MAX_OVERRIDES",
    "MAX_PARAMETERS",
    "MAX_STATES_PER_PROVIDER",
    "SETUP_FIXTURE",
    "SETUP_STATE_CHANGE",
    "SEVERITY_BLOCKING",
    "SEVERITY_WARNING",
    "FixtureRequest",
    "ProviderStateInput",
    "ProviderStateRecord",
    "StateOverrideInput",
    "StateOverrideRecord",
    "StateParameter",
    "StateProblem",
    "StateSetup",
    "Registry",
    "check_setup",
    "registry_of",
    "resolve_params",
    "setup_for_target",
    "state_issue",
    "state_problems",
    "substitute",
    "validate_state",
]

#: A state's body is malformed (HTTP 422); the pointer names the place.
CODE_STATE_INVALID = "provider-state-invalid"
#: No such state for this provider in this workspace (HTTP 404).
CODE_STATE_NOT_FOUND = "provider-state-not-found"
#: The provider already has a state with this name (HTTP 409).
CODE_STATE_NAME_TAKEN = "provider-state-name-taken"

#: An interaction names a state the provider has not registered.
CODE_STATE_NOT_REGISTERED = "provider-state-not-registered"
#: An interaction does not supply a parameter the state requires (and has no default for).
CODE_PARAM_MISSING = "provider-state-param-missing"
#: An interaction supplies a parameter the state does not declare. It is still passed on.
CODE_PARAM_UNDECLARED = "provider-state-param-undeclared"
#: The setup cannot run on the target: a fixture sends a mutating request the policy forbids.
CODE_SETUP_BLOCKED = "provider-state-setup-blocked"

#: The interaction will be held back.
SEVERITY_BLOCKING = "blocking"
#: Reported; the interaction still runs.
SEVERITY_WARNING = "warning"

SETUP_STATE_CHANGE = "state_change"
SETUP_FIXTURE = "fixture"

MAX_PARAMETERS = 20
MAX_FIXTURE_REQUESTS = 10
MAX_OVERRIDES = 20
MAX_STATES_PER_PROVIDER = 500

_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")
_SAFE_METHODS = ("GET", "HEAD")
_PARAM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_PLACEHOLDER = re.compile(r"\$\{([^}]*)\}")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,128}$")
#: Credentials come from the verification target, never from a stored fixture.
_CREDENTIAL_HEADERS = ("authorization", "proxy-authorization", "cookie", "x-api-key", "api-key")


def _invalid(pointer: str, message: str) -> PactPublicationError:
    """The 422 for one malformed place in a state's body."""
    return PactPublicationError(CODE_STATE_INVALID, f"{pointer}: {message}", pointer=pointer)


# =============================================================================================
# The shapes
# =============================================================================================


class StateParameter(BaseModel):
    """One parameter a state takes."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="The parameter's name, as interactions write it in `params` (`id`).")
    required: bool = Field(
        default=False, description="Whether an interaction must supply it (a `default` satisfies it)."
    )
    default: Optional[Any] = Field(default=None, description="The value used when an interaction does not supply one.")
    description: Optional[str] = Field(default=None, description="What it means.", max_length=500)


class FixtureRequest(BaseModel):
    """One request of a recorded fixture, sent to the verification target."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(description="`GET`, `POST`, `PUT`, `PATCH`, `DELETE` or `HEAD`.")
    path: str = Field(description="A path on the target (`/test-data/invoices/${id}`).", max_length=2000)
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="Request headers. Credentials are refused: the target's own credential is sent.",
    )
    body: Optional[Any] = Field(default=None, description="A JSON body, sent as `application/json`.")


class StateSetup(BaseModel):
    """How a state is set up — a state-change call or a recorded fixture."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["state_change", "fixture"] = Field(description="`state_change` or `fixture`.")
    url: Optional[str] = Field(
        default=None,
        description=(
            "`state_change` only: a path on the verification target (`/_pact/provider-states`, sent "
            "with the target's credential) or an absolute http(s) URL (SSRF-guarded, no credential)."
        ),
        max_length=2048,
    )
    teardown: bool = Field(
        default=True,
        description="`state_change` only: also call the URL with `action: teardown` after the interaction.",
    )
    requests: List[FixtureRequest] = Field(
        default_factory=list,
        description="`fixture` only: the requests that put the target into the state. Empty: it already is.",
    )
    teardown_requests: List[FixtureRequest] = Field(
        default_factory=list, description="`fixture` only: the requests that take it out again."
    )

    def sends_mutating(self) -> bool:
        """Whether this setup sends a mutating request to the verification target.

        Returns:
            ``True`` for a fixture with a non-``GET``/``HEAD`` request, and for a state-change call
            to a path on the target (it is a ``POST``).
        """
        if self.kind == SETUP_STATE_CHANGE:
            return bool(self.url and self.url.startswith("/"))
        return any(req.method.upper() not in _SAFE_METHODS for req in [*self.requests, *self.teardown_requests])


class StateOverrideInput(BaseModel):
    """A different setup for the state on one verification target."""

    model_config = ConfigDict(extra="forbid")

    target_ref: str = Field(description="Slug or id of the verification target.", min_length=1, max_length=200)
    setup: StateSetup = Field(description="The setup used on that target instead of the default.")


class ProviderStateInput(BaseModel):
    """The body that registers or replaces a provider state."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description="The state exactly as consumers write it (`an invoice 1042 exists`).",
        min_length=1,
        max_length=500,
    )
    description: Optional[str] = Field(default=None, description="What the state means.", max_length=1000)
    parameters: List[StateParameter] = Field(default_factory=list, description="The parameters the state takes.")
    setup: StateSetup = Field(description="How the state is set up by default.")
    overrides: List[StateOverrideInput] = Field(
        default_factory=list, description="Per-target setups, replacing the default on that target."
    )


class StateOverrideRecord(BaseModel):
    """A stored per-target setup."""

    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(description="The verification target's id.")
    target_slug: str = Field(description="Its handle.")
    setup: StateSetup = Field(description="The setup used on that target.")


class ProviderStateRecord(BaseModel):
    """A registered provider state, as stored."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The state's id.")
    provider: str = Field(description="The provider's handle.")
    name: str = Field(description="The state, as consumers write it.")
    description: Optional[str] = Field(default=None, description="What it means.")
    parameters: List[StateParameter] = Field(default_factory=list, description="The parameters it takes.")
    setup: StateSetup = Field(description="The default setup.")
    overrides: List[StateOverrideRecord] = Field(default_factory=list, description="Per-target setups.")
    created_at: datetime = Field(description="When it was registered.")
    updated_at: datetime = Field(description="When it last changed.")


class StateProblem(BaseModel):
    """One reason a state named by an interaction cannot be set up as written."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        description=(
            "`provider-state-not-registered`, `provider-state-param-missing`, "
            "`provider-state-param-undeclared` or `provider-state-setup-blocked`."
        )
    )
    severity: str = Field(description="`blocking` (the interaction is held back) or `warning` (it still runs).")
    state: str = Field(description="The state concerned.")
    parameter: Optional[str] = Field(default=None, description="The parameter concerned, when there is one.")
    message: str = Field(description="What is wrong and what to do, in a sentence.")
    consumer: Optional[str] = Field(default=None, description="The consumer whose interaction it is (the check only).")
    interaction: Optional[str] = Field(default=None, description="The interaction's description (the check only).")


# =============================================================================================
# Saving: everything a run would trip over is refused here, with its place
# =============================================================================================


def _check_path(path: str, pointer: str, declared: Sequence[str]) -> None:
    """A fixture path must be a path on the target, and name only declared parameters."""
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        raise _invalid(pointer, f"{path!r} is not a path on the target (it must start with a single '/')")
    _check_placeholders(path, pointer, declared)


def _check_placeholders(text: str, pointer: str, declared: Sequence[str]) -> None:
    """Every ``${name}`` in ``text`` must name a declared parameter."""
    for name in _PLACEHOLDER.findall(text):
        if name not in declared:
            raise _invalid(pointer, f"'${{{name}}}' names no declared parameter")


def _check_body(value: Any, pointer: str, declared: Sequence[str]) -> None:
    """Placeholders in a body's strings must name declared parameters."""
    if isinstance(value, str):
        _check_placeholders(value, pointer, declared)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_body(item, f"{pointer}/{index}", declared)
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_body(item, f"{pointer}/{key}", declared)


def _check_request(request: FixtureRequest, pointer: str, declared: Sequence[str]) -> None:
    """One fixture request: a known method, a path on the target, no credential header."""
    if request.method.upper() not in _METHODS:
        raise _invalid(f"{pointer}/method", f"{request.method!r} is not one of {', '.join(_METHODS)}")
    _check_path(request.path, f"{pointer}/path", declared)
    for name, value in request.headers.items():
        where = f"{pointer}/headers/{name}"
        if not _HEADER_NAME.match(name):
            raise _invalid(where, f"{name!r} is not a header name")
        if name.lower() in _CREDENTIAL_HEADERS:
            raise _invalid(where, "a credential is never stored here; the verification target's credential is sent")
        _check_placeholders(value, where, declared)
    _check_body(request.body, f"{pointer}/body", declared)


def check_setup(setup: StateSetup, pointer: str, declared: Sequence[str]) -> StateSetup:
    """Check one setup and return it with methods upper-cased.

    Args:
        setup: The setup as sent.
        pointer: Where it is in the body (``/setup``, ``/overrides/0/setup``).
        declared: The state's parameter names.

    Returns:
        The normalised setup.

    Raises:
        PactPublicationError: ``provider-state-invalid`` naming the place.
    """
    if setup.kind == SETUP_STATE_CHANGE:
        if setup.requests or setup.teardown_requests:
            raise _invalid(f"{pointer}/requests", "a state_change setup takes a url, not requests")
        url = (setup.url or "").strip()
        if not url:
            raise _invalid(f"{pointer}/url", "a state_change setup needs a url")
        if url.startswith("/"):
            if url.startswith("//") or "\\" in url:
                raise _invalid(f"{pointer}/url", f"{url!r} is not a path on the target")
        else:
            # The shape rules (scheme, no credentials); the address rule runs on every send.
            from .verification_target import TargetValidationError, validate_base_url

            try:
                validate_base_url(url, resolve=False)
            except TargetValidationError as exc:
                raise _invalid(f"{pointer}/url", str(exc)) from exc
        return setup.model_copy(update={"url": url})

    if setup.url is not None:
        raise _invalid(f"{pointer}/url", "a fixture setup takes requests, not a url")
    for field in ("requests", "teardown_requests"):
        requests = getattr(setup, field)
        if len(requests) > MAX_FIXTURE_REQUESTS:
            raise _invalid(f"{pointer}/{field}", f"at most {MAX_FIXTURE_REQUESTS} requests")
        for index, request in enumerate(requests):
            _check_request(request, f"{pointer}/{field}/{index}", declared)
    upper = lambda reqs: [r.model_copy(update={"method": r.method.upper()}) for r in reqs]  # noqa: E731
    return setup.model_copy(
        update={"requests": upper(setup.requests), "teardown_requests": upper(setup.teardown_requests)}
    )


def validate_state(state: ProviderStateInput) -> ProviderStateInput:
    """Check a state's body as a whole and return its normalised form.

    Args:
        state: The body.

    Returns:
        The state with its name trimmed and its setups normalised.

    Raises:
        PactPublicationError: ``provider-state-invalid`` naming the place.
    """
    name = state.name.strip()
    if not name:
        raise _invalid("/name", "a state needs a name")
    if len(state.parameters) > MAX_PARAMETERS:
        raise _invalid("/parameters", f"at most {MAX_PARAMETERS} parameters")
    seen: List[str] = []
    for index, parameter in enumerate(state.parameters):
        if not _PARAM_NAME.match(parameter.name):
            raise _invalid(f"/parameters/{index}/name", f"{parameter.name!r} is not a parameter name")
        if parameter.name in seen:
            raise _invalid(f"/parameters/{index}/name", f"'{parameter.name}' is declared twice")
        seen.append(parameter.name)
    if len(state.overrides) > MAX_OVERRIDES:
        raise _invalid("/overrides", f"at most {MAX_OVERRIDES} overrides")
    targets: List[str] = []
    overrides: List[StateOverrideInput] = []
    for index, override in enumerate(state.overrides):
        ref = override.target_ref.strip()
        if ref in targets:
            raise _invalid(f"/overrides/{index}/target_ref", f"target '{ref}' has two overrides")
        targets.append(ref)
        overrides.append(
            StateOverrideInput(target_ref=ref, setup=check_setup(override.setup, f"/overrides/{index}/setup", seen))
        )
    return state.model_copy(
        update={"name": name, "setup": check_setup(state.setup, "/setup", seen), "overrides": overrides}
    )


# =============================================================================================
# Running: which setup, which parameters, and what an interaction's states lack
# =============================================================================================


#: A provider's registered states, by name.
Registry = Mapping[str, ProviderStateRecord]


def setup_for_target(state: ProviderStateRecord, target_id: Optional[str]) -> Tuple[StateSetup, bool]:
    """The setup a state uses on a target.

    Args:
        state: The registered state.
        target_id: The verification target's id, or ``None`` for the default.

    Returns:
        ``(setup, overridden)`` — the target's override when it has one, else the default.
    """
    for override in state.overrides:
        if target_id and override.target_id == target_id:
            return override.setup, True
    return state.setup, False


def resolve_params(state: ProviderStateRecord, given: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[StateProblem]]:
    """The parameters a setup is called with, and what is wrong with what the interaction gave.

    Declared defaults fill what the interaction left out. A parameter the state does not declare
    is still passed on (the provider may know it) and reported as a warning.

    Args:
        state: The registered state.
        given: The interaction's ``params``.

    Returns:
        ``(params, problems)``.
    """
    params: Dict[str, Any] = dict(given)
    problems: List[StateProblem] = []
    declared = {parameter.name for parameter in state.parameters}
    for parameter in state.parameters:
        if parameter.name in params:
            continue
        if parameter.default is not None:
            params[parameter.name] = parameter.default
        elif parameter.required:
            problems.append(
                StateProblem(
                    code=CODE_PARAM_MISSING,
                    severity=SEVERITY_BLOCKING,
                    state=state.name,
                    parameter=parameter.name,
                    message=(
                        f"the state '{state.name}' requires the parameter '{parameter.name}' and the "
                        "interaction does not supply it; give it a default or ask the consumer to add it."
                    ),
                )
            )
    for name in sorted(set(given) - declared):
        problems.append(
            StateProblem(
                code=CODE_PARAM_UNDECLARED,
                severity=SEVERITY_WARNING,
                state=state.name,
                parameter=name,
                message=(
                    f"the interaction passes '{name}' to the state '{state.name}', which does not declare "
                    "it; it is passed on unchanged."
                ),
            )
        )
    return params, problems


def state_problems(
    states: Sequence[PactProviderState],
    registry: Registry,
    *,
    target_id: Optional[str] = None,
    target_allows_mutating: Optional[bool] = None,
) -> List[StateProblem]:
    """Everything that stands between an interaction's states and their setup.

    Args:
        states: The interaction's provider states.
        registry: The provider's registered states.
        target_id: The verification target, to pick its overrides.
        target_allows_mutating: The target policy's ``allow_mutating_methods``; ``None`` skips
            that check (no target chosen).

    Returns:
        The problems, blocking and warning, in the states' order.
    """
    problems: List[StateProblem] = []
    for state in states:
        registered = registry.get(state.name)
        if registered is None:
            problems.append(
                StateProblem(
                    code=CODE_STATE_NOT_REGISTERED,
                    severity=SEVERITY_BLOCKING,
                    state=state.name,
                    message=(
                        f"the provider has no registered state '{state.name}'; register it (with how to "
                        "set it up) or ask the consumer to use a registered name."
                    ),
                )
            )
            continue
        problems.extend(resolve_params(registered, state.params)[1])
        setup, _ = setup_for_target(registered, target_id)
        if target_allows_mutating is False and setup.sends_mutating():
            problems.append(
                StateProblem(
                    code=CODE_SETUP_BLOCKED,
                    severity=SEVERITY_BLOCKING,
                    state=state.name,
                    message=(
                        f"setting up '{state.name}' sends a mutating request to the verification target, "
                        "whose policy has allow_mutating_methods=false; use a state-change URL off the "
                        "target, or a target that allows it."
                    ),
                )
            )
    return problems


def state_issue(
    states: Sequence[PactProviderState],
    registry: Registry,
    *,
    target_id: Optional[str] = None,
    target_allows_mutating: Optional[bool] = None,
) -> Optional[Tuple[str, str]]:
    """The first blocking problem with an interaction's states, as ``(code, message)``.

    Args:
        states: The interaction's provider states.
        registry: The provider's registered states.
        target_id: The verification target.
        target_allows_mutating: Its policy's ``allow_mutating_methods``.

    Returns:
        ``None`` when every state can be set up.
    """
    for problem in state_problems(states, registry, target_id=target_id, target_allows_mutating=target_allows_mutating):
        if problem.severity == SEVERITY_BLOCKING:
            return problem.code, problem.message
    return None


def substitute(value: Any, params: Mapping[str, Any]) -> Any:
    """Replace ``${name}`` with the parameter's value throughout a fixture value.

    A string that is exactly one placeholder takes the parameter's own value (so ``"${id}"`` in
    a JSON body stays the number ``1042``); anywhere else the value is written as text.

    Args:
        value: A path, header value or body.
        params: The resolved parameters.

    Returns:
        The value with every placeholder replaced. Saving refused placeholders that name no
        parameter; one whose parameter has no value here becomes an empty string.
    """
    if isinstance(value, str):
        whole = _PLACEHOLDER.fullmatch(value)
        if whole is not None and whole.group(1) in params:
            return params[whole.group(1)]
        return _PLACEHOLDER.sub(lambda match: _text(params.get(match.group(1))), value)
    if isinstance(value, list):
        return [substitute(item, params) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, params) for key, item in value.items()}
    return value


def _text(value: Any) -> str:
    """A parameter's value as it is written into a string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def registry_of(states: Iterable[ProviderStateRecord]) -> Dict[str, ProviderStateRecord]:
    """Index stored states by name."""
    return {state.name: state for state in states}
