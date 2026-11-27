"""Setting provider states up during a hosted verification — PFX-3.3 (#6933).

:class:`RegistryStateHandler` is the :class:`app.pact_verifier.ProviderStateHandler` the hosted
verifier (PFX-3.2) uses when the provider has registered states (:mod:`app.pact_provider_state`).
Before an interaction that names states is replayed, it sets each one up, in the recorded order;
after the interaction it tears them down, in reverse.

==================  =========================================================================
Setup               What is sent
==================  =========================================================================
``state_change``    ``POST {url}`` with ``{"state", "params", "action": "setup"}`` — and
                    ``"action": "teardown"`` afterwards unless the state turns teardown off.
                    A path is joined onto the verification target and carries the target's
                    credential; an absolute URL goes through the SSRF guard with none.
``fixture``         Each request of ``requests`` before, of ``teardown_requests`` after, to the
                    verification target with its credential, ``${param}`` substituted.
==================  =========================================================================

**The target's policy still rules.** Requests to the target use the target's guarded client —
its private-network approval, TLS and redirect rules, timeout — and a mutating request is never
sent to a target whose policy forbids mutating methods (the planner already holds such an
interaction back; this is the second lock). A URL off the target is always treated as public.

**A failed setup holds the interaction back.** Any answer outside 2xx, or a transport error,
stops the setup: what was already set up for that interaction is torn down, and the interaction
is skipped with ``provider-state-setup-failed`` naming the state and the call. A failed teardown
cannot change a result already observed, so it is recorded in :attr:`teardown_failures` and
reported with the pact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import httpx

from .contract_suite import PactProviderState
from .pact_provider_state import (
    CODE_SETUP_BLOCKED,
    SETUP_STATE_CHANGE,
    FixtureRequest,
    ProviderStateRecord,
    Registry,
    StateSetup,
    resolve_params,
    setup_for_target,
    state_issue,
    substitute,
)
from .ssrf_guard import build_guarded_client
from .verification_target import NETWORK_CLASS_PRIVATE, ResolvedTarget

logger = logging.getLogger(__name__)

__all__ = ["RegistryStateHandler", "SetupUrlStateHandler"]

_SAFE_METHODS = ("GET", "HEAD")
_BODY_EXCERPT = 200


@dataclass
class _Active:
    """A state set up for the interaction in flight."""

    name: str
    setup: StateSetup
    params: Dict[str, Any]


def _join(base_url: str, path: str) -> str:
    """Join a path on the target onto its base URL (the runner's rule: the base keeps its path)."""
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _excerpt(response: httpx.Response) -> str:
    """The start of a response body, for a failure message."""
    text = (response.text or "").strip().replace("\n", " ")
    return f": {text[:_BODY_EXCERPT]}" if text else ""


class RegistryStateHandler:
    """Sets a provider's registered states up on one verification target.

    One handler serves one verification run; the runner calls it one interaction at a time.
    """

    def __init__(
        self,
        registry: Registry,
        target: ResolvedTarget,
        auth_headers: Mapping[str, str],
        *,
        target_client: Optional[httpx.Client] = None,
        external_client: Optional[httpx.Client] = None,
    ) -> None:
        """Build the handler.

        Args:
            registry: The provider's registered states, by name.
            target: The resolved verification target.
            auth_headers: The target's materialised credential headers (sent only to the target).
            target_client: A client for the target (tests); by default a guarded client under
                the target's policy, created on first use.
            external_client: A client for state-change URLs off the target (tests); by default a
                guarded public-only client, created on first use.
        """
        self.registry = registry
        self.target = target
        self.auth_headers = dict(auth_headers)
        self._target_client = target_client
        self._external_client = external_client
        self._owned: List[httpx.Client] = []
        self._active: List[_Active] = []
        self.teardown_failures: List[str] = []

    # -- what the planner asks -----------------------------------------------------------------

    def issue(self, states: Sequence[PactProviderState]) -> Optional[Tuple[str, str]]:
        """The first reason ``states`` cannot be set up on this target, before anything is sent.

        Args:
            states: An interaction's provider states.

        Returns:
            ``(code, message)``, or ``None`` when every state can be set up.
        """
        return state_issue(
            states,
            self.registry,
            target_id=self.target.target_id,
            target_allows_mutating=self.target.policy.allow_mutating_methods,
        )

    # -- the ProviderStateHandler protocol ----------------------------------------------------

    def setup(self, states: Sequence[PactProviderState]) -> Optional[str]:
        """Set every state up, in order; undo the ones done if one fails.

        Args:
            states: The interaction's provider states.

        Returns:
            ``None`` when the provider is ready, else why not.
        """
        self._active = []
        for state in states:
            registered: Optional[ProviderStateRecord] = self.registry.get(state.name)
            if registered is None:
                self._undo()
                return f"the provider has no registered state '{state.name}'"
            setup, _ = setup_for_target(registered, self.target.target_id)
            params, _problems = resolve_params(registered, state.params)
            problem = self._run(state.name, setup, params, action="setup")
            if problem is not None:
                self._undo()
                return f"'{state.name}': {problem}"
            self._active.append(_Active(name=state.name, setup=setup, params=params))
        return None

    def teardown(self, states: Sequence[PactProviderState]) -> None:
        """Tear down what :meth:`setup` set up, in reverse order.

        Args:
            states: The same states (the handler remembers what it actually set up).
        """
        _ = states
        self._undo()

    def close(self) -> None:
        """Close the clients this handler created."""
        for client in self._owned:
            client.close()
        self._owned = []

    def drain_teardown_failures(self) -> List[str]:
        """The teardown failures recorded since the last call, cleared.

        Returns:
            One sentence per failed teardown.
        """
        failures, self.teardown_failures = self.teardown_failures, []
        return failures

    # -- sending ------------------------------------------------------------------------------

    def _undo(self) -> None:
        """Tear down the active states, newest first, recording failures."""
        active, self._active = self._active, []
        for entry in reversed(active):
            if entry.setup.kind == SETUP_STATE_CHANGE and not entry.setup.teardown:
                continue
            try:
                problem = self._run(entry.name, entry.setup, entry.params, action="teardown")
            except Exception as exc:  # noqa: BLE001 - a teardown must not end the run
                logger.exception("provider state teardown failed for %r", entry.name)
                problem = exc.__class__.__name__
            if problem is not None:
                self.teardown_failures.append(f"teardown of '{entry.name}' failed: {problem}")

    def _run(self, name: str, setup: StateSetup, params: Dict[str, Any], *, action: str) -> Optional[str]:
        """Perform one setup or teardown.

        Args:
            name: The state.
            setup: How it is set up.
            params: The resolved parameters.
            action: ``setup`` or ``teardown``.

        Returns:
            ``None`` on success, else what went wrong.
        """
        if setup.kind == SETUP_STATE_CHANGE:
            url = setup.url or ""
            body = {"state": name, "params": params, "action": action}
            if url.startswith("/"):
                return self._send_to_target("POST", url, {}, body)
            return self._send_external(url, body)
        requests: List[FixtureRequest] = setup.requests if action == "setup" else setup.teardown_requests
        for request in requests:
            problem = self._send_to_target(
                request.method,
                str(substitute(request.path, params)),
                {key: str(substitute(value, params)) for key, value in request.headers.items()},
                substitute(request.body, params),
            )
            if problem is not None:
                return problem
        return None

    def _client(self, *, external: bool) -> httpx.Client:
        """The client for the target, or for a URL off it; created on first use."""
        if external:
            if self._external_client is None:
                self._external_client = self._own(allow_private=False)
            return self._external_client
        if self._target_client is None:
            self._target_client = self._own(allow_private=self.target.network_class == NETWORK_CLASS_PRIVATE)
        return self._target_client

    def _own(self, *, allow_private: bool) -> httpx.Client:
        """A guarded client under the target's timeout, TLS and redirect rules."""
        policy = self.target.policy
        client = build_guarded_client(
            allow_private=allow_private,
            timeout=httpx.Timeout(policy.request_timeout_seconds),
            follow_redirects=policy.follow_redirects,
            verify=policy.verify_tls,
        )
        self._owned.append(client)
        return client

    def _send_to_target(self, method: str, path: str, headers: Dict[str, str], body: Any) -> Optional[str]:
        """Send one request to the verification target, with its credential."""
        method = method.upper()
        if method not in _SAFE_METHODS and not self.target.policy.allow_mutating_methods:
            return f"{method} {path} was not sent: the target's policy has allow_mutating_methods=false"
        if not path.startswith("/") or path.startswith("//"):
            return f"{path!r} is not a path on the target"
        return self._send(
            self._client(external=False),
            method,
            _join(self.target.base_url, path),
            {**headers, **self.auth_headers},
            body,
            label=f"{method} {path}",
        )

    def _send_external(self, url: str, body: Any) -> Optional[str]:
        """POST a state-change body to a URL off the target, without any credential."""
        return self._send(self._client(external=True), "POST", url, {}, body, label=f"POST {url}")

    @staticmethod
    def _send(
        client: httpx.Client, method: str, url: str, headers: Dict[str, str], body: Any, *, label: str
    ) -> Optional[str]:
        """Send a request and say what went wrong, if anything.

        Returns:
            ``None`` for a 2xx answer; otherwise the status or the transport error.
        """
        content: Optional[bytes] = None
        if body is not None:
            headers = {"Content-Type": "application/json", **headers}
            content = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        try:
            response = client.request(method, url, headers=headers, content=content)
        except Exception as exc:  # noqa: BLE001 - classified into the reason
            return f"{label} could not be sent ({exc.__class__.__name__}: {str(exc)[:_BODY_EXCERPT]})"
        if 200 <= response.status_code < 300:
            return None
        return f"{label} answered {response.status_code}{_excerpt(response)}"


class SetupUrlStateHandler(RegistryStateHandler):
    """Sets every state up through the provider's own setup endpoint (PFX-8.8, #7305).

    The choice a Pact verifier calls ``--provider-states-setup-url``: no registry, one URL. Before
    an interaction that names states, each state is ``POST``-ed to the URL as
    ``{"state", "params", "action": "setup"}``, in the recorded order, and after the interaction as
    ``"action": "teardown"``, in reverse — exactly a registered ``state_change`` setup, so the same
    rules apply: a path is joined onto the target and carries its credential, an absolute URL goes
    through the SSRF guard with none, and a failed setup holds the interaction back with the call
    named.

    **A path on the target is a ``POST`` to it.** When the target's policy forbids mutating
    methods, every interaction that names a state is held back with ``provider-state-setup-blocked``
    before anything is sent, as the registry does for its own ``state_change`` setups.
    """

    def __init__(
        self,
        url: str,
        target: ResolvedTarget,
        auth_headers: Mapping[str, str],
        *,
        target_client: Optional[httpx.Client] = None,
        external_client: Optional[httpx.Client] = None,
    ) -> None:
        """Build the handler.

        Args:
            url: The setup endpoint — a path on the target or an absolute http(s) URL (already
                checked by :class:`app.pact_verifier.PactVerificationOptions`).
            target: The resolved verification target.
            auth_headers: The target's credential headers (sent only to the target).
            target_client: A client for the target (tests).
            external_client: A client for a URL off the target (tests).
        """
        super().__init__(
            {}, target, auth_headers, target_client=target_client, external_client=external_client
        )
        self.url = url
        self.state_setup = StateSetup(kind=SETUP_STATE_CHANGE, url=url, teardown=True)

    def issue(self, states: Sequence[PactProviderState]) -> Optional[Tuple[str, str]]:
        """Why ``states`` cannot be set up through the URL, before anything is sent.

        Args:
            states: An interaction's provider states.

        Returns:
            ``(provider-state-setup-blocked, message)`` when the URL is a path on a target whose
            policy forbids mutating methods; otherwise ``None`` — every state is the endpoint's to
            set up.
        """
        if states and self.state_setup.sends_mutating() and not self.target.policy.allow_mutating_methods:
            return (
                CODE_SETUP_BLOCKED,
                f"the setup endpoint {self.url} is a POST to the target, and the target's policy has "
                "allow_mutating_methods=false",
            )
        return None

    def setup(self, states: Sequence[PactProviderState]) -> Optional[str]:
        """POST every state to the URL, in order; undo the ones done if one fails.

        Args:
            states: The interaction's provider states.

        Returns:
            ``None`` when the provider is ready, else why not.
        """
        self._active = []
        for state in states:
            params = dict(state.params or {})
            problem = self._run(state.name, self.state_setup, params, action="setup")
            if problem is not None:
                self._undo()
                return f"'{state.name}': {problem}"
            self._active.append(_Active(name=state.name, setup=self.state_setup, params=params))
        return None
