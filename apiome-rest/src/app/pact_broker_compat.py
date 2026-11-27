"""What of the Pact Broker API Apiome serves — the compatibility catalog, PFX-1.8 (#6921).

"Drop-in" is a claim, so it is written down once, here, endpoint by endpoint, against one release
of the Pact Broker (:data:`PACT_BROKER_VERSION`, whose ``lib/pact_broker/api.rb`` route table the
catalog follows). Three things read it:

* the tests (``tests/test_pact_broker_compat.py``) — every method the catalog calls supported is a
  route of the app, and every Pact Broker route of the app is in the catalog, so neither can drift;
* :mod:`app.pact_broker_compat_routes` — a request for a method or path the catalog does not
  support is answered ``501 Not Implemented`` naming the endpoint, its status, its tracking issue
  and the compatibility page, never a bare ``404``;
* ``scripts/generate_pact_broker_compat_doc.py`` — the table on
  ``apiome-docs/docs/ship/pact-broker/compatibility.mdx``.

Each endpoint lists the methods the Pact Broker allows on it (``OPTIONS`` aside) and the methods
Apiome serves. Its status follows from the two:

* ``supported`` — every method;
* ``partial`` — some methods; the rest answer 501;
* ``planned`` — none yet, and an Apiome issue schedules it (``tracking``);
* ``not planned`` — none, and none is scheduled; ``note`` says why, and ``alternative`` names the
  Apiome route that does the same job when there is one.

Paths are relative to the broker base URL (``/v1/tenants/<tenant>/pact-broker``) and use
``{name}`` placeholders; the names are free — only the literal segments and the number of
segments are compared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .docs_site import DOCS_SITE_PAGES_ROOT, site_url

__all__ = [
    "BROKER_PREFIX",
    "COMPATIBILITY_PAGE",
    "ENDPOINTS",
    "GROUPS",
    "NOT_PLANNED",
    "PACT_BROKER_CLIENT_VERSION",
    "PACT_BROKER_VERSION",
    "PARTIAL",
    "PLANNED",
    "STATUSES",
    "SUPPORTED",
    "BrokerEndpoint",
    "compatibility_url",
    "endpoints_by_group",
    "find_endpoint",
    "issue_url",
    "normalise_path",
    "status_counts",
]

#: The Pact Broker release the catalog is checked against (``pactfoundation/pact-broker``).
PACT_BROKER_VERSION = "2.124.0"

#: The ``pact_broker-client`` gem in the ``pactfoundation/pact-cli`` image the conformance suite runs.
PACT_BROKER_CLIENT_VERSION = "1.78.0"

#: Where the Pact Broker surface is mounted; ``{tenant_slug}`` is the tenant in the URL.
BROKER_PREFIX = "/v1/tenants/{tenant_slug}/pact-broker"

#: The guide page holding the generated table.
COMPATIBILITY_PAGE = f"{DOCS_SITE_PAGES_ROOT}/ship/pact-broker/compatibility.mdx"

SUPPORTED = "supported"
PARTIAL = "partial"
PLANNED = "planned"
NOT_PLANNED = "not planned"

#: Every status, in the order the page explains them.
STATUSES = (SUPPORTED, PARTIAL, PLANNED, NOT_PLANNED)

#: The table's sections, in page order.
GROUPS = (
    "Index",
    "Publishing and fetching pacts",
    "Pact history and diffs",
    "Verification results",
    "Pacticipants and versions",
    "Branches and tags",
    "Environments and deployments",
    "Matrix and can-i-deploy",
    "Webhooks",
    "Badges",
    "Labels",
    "Other",
    "Provider contracts (PactFlow)",
    "Apiome additions",
)

_ISSUES = "https://github.com/apiome/apiome/issues/"

# Tracking issues (docs/ROADMAP_PACTFLOW_PARITY.md).
_BADGE_NOTE = (
    "Apiome serves public SVG and shields.io status badges for a public project instead, "
    "not the broker's tag-aware ones."
)
_BADGES = "/v1/browse/tenants/{tenant}/projects/{project}/pact-badges"  # PFX-1.10 (#6923)
# PFX-1.11 (#6924) shipped labels, pacticipant and version delete, and selector-based retention.
_RETENTION = "/v1/tenants/{tenant}/pact-retention"
_DELETE_VERSION = (
    "Delete the consumer version instead (`DELETE …/pacticipants/{p}/versions/{v}`), which removes its pacts."
)

_NATIVE = "/v1/tenants/{tenant}/pacticipants"


@dataclass(frozen=True)
class BrokerEndpoint:
    """One resource of the Pact Broker API and how much of it Apiome serves.

    Attributes:
        group: The table section (one of :data:`GROUPS`).
        path: The path under the broker base URL, e.g. ``/pacts/provider/{p}/latest``.
        title: What the resource is, in a few words.
        methods: The methods the Pact Broker allows, ``OPTIONS`` aside.
        supported: The methods Apiome serves — a subset of ``methods``.
        used_by: The ``pact-broker`` CLI commands and client calls that reach it.
        tracking: The Apiome issue (``#n``) that schedules what is missing, if any.
        note: A short explanation for the table and the 501 body.
        alternative: An Apiome route that does the same job, when the broker shape is missing.
    """

    group: str
    path: str
    title: str
    methods: Tuple[str, ...]
    supported: Tuple[str, ...] = ()
    used_by: str = ""
    tracking: Optional[str] = None
    note: str = ""
    alternative: Optional[str] = None
    _pattern: "re.Pattern[str]" = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Check the entry is coherent and compile its path pattern.

        Raises:
            ValueError: When a supported method is not one the broker allows, the group is unknown,
                or an endpoint with nothing supported has neither a tracking issue nor a note.
        """
        if not set(self.supported) <= set(self.methods):
            raise ValueError(f"{self.path}: supported {self.supported} not within {self.methods}")
        if self.group not in GROUPS:
            raise ValueError(f"{self.path}: unknown group {self.group!r}")
        if not self.supported and not (self.tracking or self.note):
            raise ValueError(f"{self.path}: an unsupported endpoint needs a tracking issue or a note")
        object.__setattr__(self, "_pattern", _compile(self.path))

    @property
    def status(self) -> str:
        """``supported``, ``partial``, ``planned`` or ``not planned`` (see the module docstring)."""
        if self.supported and set(self.supported) == set(self.methods):
            return SUPPORTED
        if self.supported:
            return PARTIAL
        return PLANNED if self.tracking else NOT_PLANNED

    @property
    def unsupported(self) -> Tuple[str, ...]:
        """The broker's methods Apiome does not serve, in the broker's order."""
        return tuple(method for method in self.methods if method not in self.supported)

    @property
    def literal_segments(self) -> int:
        """How many path segments are fixed text — the more, the more specific the path."""
        return sum(1 for part in self.path.split("/") if part and not part.startswith("{"))

    def matches(self, path: str) -> bool:
        """Whether a concrete path (under the base URL) is this endpoint.

        Args:
            path: The request path after the broker base, starting with ``/`` (``""`` = index).

        Returns:
            ``True`` when every literal segment matches and the segment counts agree.
        """
        return self._pattern.fullmatch(path.rstrip("/")) is not None


def _compile(path: str) -> "re.Pattern[str]":
    """Turn a ``{name}`` path into a pattern where each placeholder is one segment."""
    parts = re.split(r"(\{[^}]+\})", path)
    return re.compile("".join("[^/]+" if part.startswith("{") else re.escape(part) for part in parts))


def normalise_path(path: str) -> str:
    """Erase placeholder names (and ``:path`` converters) so two route templates compare.

    Args:
        path: A template such as ``/pacticipants/{pacticipant}/branches/{branch:path}``.

    Returns:
        ``/pacticipants/{}/branches/{}``.
    """
    return re.sub(r"\{[^}]+\}", "{}", path)


def issue_url(tracking: Optional[str]) -> Optional[str]:
    """The GitHub URL of a ``#n`` tracking reference, or ``None``."""
    return f"{_ISSUES}{tracking.lstrip('#')}" if tracking else None


def _e(
    group: str,
    path: str,
    title: str,
    methods: str,
    supported: str = "",
    *,
    used_by: str = "",
    tracking: Optional[str] = None,
    note: str = "",
    alternative: Optional[str] = None,
) -> BrokerEndpoint:
    """Build an entry from space-separated method lists (keeps the table below readable)."""
    return BrokerEndpoint(
        group=group,
        path=path,
        title=title,
        methods=tuple(methods.split()),
        supported=tuple(supported.split()),
        used_by=used_by,
        tracking=tracking,
        note=note,
        alternative=alternative,
    )


_PAIR = "/pacts/provider/{provider}/consumer/{consumer}"
_SHA = _PAIR + "/pact-version/{sha}"
_VERSION = "/pacticipants/{pacticipant}/versions/{version}"
_BRANCH = "/pacticipants/{pacticipant}/branches/{branch}"

_G_INDEX, _G_PACTS, _G_HISTORY, _G_RESULTS, _G_PARTICIPANTS, _G_BRANCHES = GROUPS[:6]
_G_ENVIRONMENTS, _G_MATRIX, _G_WEBHOOKS, _G_BADGES, _G_LABELS, _G_OTHER = GROUPS[6:12]
_G_PROVIDER_CONTRACTS = GROUPS[12]
_G_APIOME = GROUPS[13]

#: The catalog — every resource of the Pact Broker API, in the order of the page.
ENDPOINTS: Tuple[BrokerEndpoint, ...] = (
    # Index ------------------------------------------------------------------------------------
    _e(_G_INDEX, "", "Index (HAL entry point)", "GET", "GET", used_by="every client"),
    # Publishing and fetching pacts --------------------------------------------------------------
    _e(
        _G_PACTS,
        "/contracts/publish",
        "Publish the pacts of a consumer version",
        "POST",
        "POST",
        used_by="`pact-broker publish`, pact-js `publishPacts`, pact-jvm `pactPublish`",
    ),
    _e(
        _G_PACTS,
        _PAIR + "/version/{consumerVersion}",
        "A pact of a consumer version",
        "GET PUT DELETE PATCH",
        "GET PUT",
        used_by="older `pact-broker publish`, pact-jvm publisher",
        note=(
            "`PATCH` (merging interactions into a published pact) is not planned: a pact is immutable. "
            "`DELETE`: " + _DELETE_VERSION
        ),
    ),
    _e(_G_PACTS, _PAIR + "/latest", "Latest pact of a consumer and provider", "GET", "GET"),
    _e(_G_PACTS, _PAIR + "/latest/{tag}", "Latest pact with a tag", "GET", "GET"),
    _e(_G_PACTS, _PAIR + "/branch/{branch}/latest", "Latest pact from a branch", "GET", "GET"),
    _e(
        _G_PACTS,
        _PAIR + "/latest-untagged",
        "Latest untagged pact",
        "GET",
        note="Tags are legacy in the Pact Broker; use branches, or `…/latest`.",
    ),
    _e(_G_PACTS, _SHA, "A pact by its content version", "GET", "GET", used_by="every verifier"),
    _e(_G_PACTS, _SHA + "/metadata/{metadata}", "A pact as a for-verification link names it", "GET", "GET"),
    _e(
        _G_PACTS,
        "/pacts/provider/{provider}/for-verification",
        "Pacts a provider must verify (consumer-version selectors)",
        "GET POST",
        "GET POST",
        used_by="pact-js, pact-jvm, pact-go, pact-python, the Rust and Ruby verifiers",
        note="The Rust verifier `GET`s the resource before it `POST`s its selectors.",
    ),
    _e(_G_PACTS, "/pacts/provider/{provider}/latest", "Latest pact of every consumer", "GET", "GET"),
    _e(_G_PACTS, "/pacts/provider/{provider}/latest/{tag}", "Latest tagged pact of every consumer", "GET", "GET"),
    _e(
        _G_PACTS,
        "/pacts/provider/{provider}",
        "Every pact of a provider",
        "GET",
        note="Use `…/latest` or `for-verification`.",
    ),
    _e(
        _G_PACTS,
        "/pacts/provider/{provider}/tag/{tag}",
        "Every pact of a provider with a tag",
        "GET",
        note="Use `…/latest/{tag}` or a `tag` selector.",
    ),
    _e(
        _G_PACTS,
        "/pacts/provider/{provider}/branch",
        "Pacts from each consumer's main branch",
        "GET",
        note="Use a `mainBranch` selector on `for-verification`.",
    ),
    _e(
        _G_PACTS,
        "/pacts/provider/{provider}/branch/{branch}",
        "Pacts from a consumer branch",
        "GET",
        note="Use a `branch` selector on `for-verification`.",
    ),
    _e(
        _G_PACTS,
        "/pacts/provider/{provider}/branch/latest",
        "Latest pacts from each consumer's main branch",
        "GET",
        note="Use a `mainBranch` selector on `for-verification`.",
    ),
    _e(
        _G_PACTS,
        "/pacts/provider/{provider}/branch/{branch}/latest",
        "Latest pacts from a consumer branch",
        "GET",
        note="Use a `branch` selector on `for-verification`.",
    ),
    _e(
        _G_PACTS,
        "/pacts/latest",
        "Latest pact of every integration",
        "GET",
        used_by="`pact-broker list-latest-pact-versions`",
        note="Not planned in the broker shape.",
        alternative="the `GET …/matrix` query",
    ),
    _e(
        _G_PACTS,
        "/pacts/provider/{provider}/provider-states",
        "Provider states the consumers use",
        "GET",
        note="Provider states are declared in Apiome's own registry (PFX-3.3, #6933).",
    ),
    _e(
        _G_PACTS,
        "/pacts/provider/{provider}/provider-states/branch/{branch}",
        "Provider states from a consumer branch",
        "GET",
        note="See PFX-3.3 (#6933).",
    ),
    _e(
        _G_PACTS,
        "/pacts/provider/{provider}/provider-states/environment/{uuid}",
        "Provider states of what is deployed in an environment",
        "GET",
        note="See PFX-3.3 (#6933).",
    ),
    _e(
        _G_PACTS,
        "/pact/provider/{provider}/consumer/{consumer}/version/{consumerVersion}",
        "Deprecated singular `/pact/…` path",
        "GET PUT DELETE PATCH",
        note="Deprecated in the Pact Broker; use `/pacts/…`.",
    ),
    _e(
        _G_PACTS,
        "/pact/provider/{provider}/consumer/{consumer}/latest",
        "Deprecated singular `/pact/…/latest` path",
        "GET",
        note="Deprecated in the Pact Broker; use `/pacts/…/latest`.",
    ),
    # Pact history and diffs ---------------------------------------------------------------------
    _e(
        _G_HISTORY,
        _PAIR + "/versions",
        "Every published pact of an integration",
        "GET DELETE",
        note="Not planned in the broker shape; clean a history up with a retention run.",
        alternative=_RETENTION,
    ),
    _e(
        _G_HISTORY,
        _PAIR + "/versions/{consumerVersion}",
        "Deprecated alias of `…/version/{v}`",
        "GET PUT DELETE PATCH",
        note="Deprecated in the Pact Broker; use `…/version/{v}`.",
    ),
    _e(
        _G_HISTORY,
        _PAIR + "/tag/{tag}",
        "Every pact with a tag",
        "GET DELETE",
        note="Tags are legacy in the Pact Broker; use branches.",
    ),
    _e(_G_HISTORY, _PAIR + "/branch/versions", "Pacts from the main branch", "GET DELETE", note="Not planned."),
    _e(_G_HISTORY, _PAIR + "/branch/{branch}", "Pacts from a branch", "GET DELETE", note="Not planned."),
    _e(
        _G_HISTORY,
        _PAIR + "/branch/latest/versions",
        "Latest pacts from the main branch",
        "GET DELETE",
        note="Not planned.",
    ),
    _e(
        _G_HISTORY,
        _PAIR + "/branch/{branch}/latest/versions",
        "Latest pacts from a branch",
        "GET DELETE",
        note="Not planned.",
    ),
    _e(
        _G_HISTORY,
        _PAIR + "/version/{consumerVersion}/previous-distinct",
        "The previous different pact",
        "GET",
        note="The pact viewer shows the difference (PFX-5.2, #6946).",
    ),
    _e(
        _G_HISTORY,
        _PAIR + "/version/{consumerVersion}/diff/previous-distinct",
        "Diff with the previous different pact",
        "GET",
        note="The pact viewer shows the difference (PFX-5.2, #6946).",
    ),
    _e(
        _G_HISTORY,
        _PAIR + "/version/{consumerVersion}/diff/version/{otherVersion}",
        "Diff with another consumer version's pact",
        "GET",
        note="The pact viewer shows the difference (PFX-5.2, #6946).",
    ),
    _e(
        _G_HISTORY,
        _SHA + "/diff/pact-version/{otherSha}",
        "Diff with another pact version",
        "GET",
        note="The pact viewer shows the difference (PFX-5.2, #6946).",
    ),
    # Verification results -------------------------------------------------------------------------
    _e(
        _G_RESULTS,
        _SHA + "/verification-results",
        "Publish a verification result",
        "POST",
        "POST",
        used_by="every verifier with result publishing on",
    ),
    _e(
        _G_RESULTS,
        _SHA + "/metadata/{metadata}/verification-results",
        "Publish a result (for-verification link form)",
        "POST",
        "POST",
        used_by="verifiers that follow `pb:publish-verification-results`",
    ),
    _e(_G_RESULTS, _SHA + "/verification-results/latest", "Latest result of a pact version", "GET", "GET"),
    _e(
        _G_RESULTS,
        _SHA + "/verification-results/{number}",
        "One verification result",
        "GET DELETE",
        "GET",
        note="Deleting one result is not planned; deleting the provider version removes the results it published.",
    ),
    _e(
        _G_RESULTS,
        _SHA + "/metadata/{metadata}/verification-results/{number}",
        "One result (for-verification link form)",
        "GET DELETE",
        note="Use `…/pact-version/{sha}/verification-results/{n}`.",
    ),
    _e(
        _G_RESULTS,
        _SHA + "/verification-results/{number}/triggered-webhooks",
        "Webhooks a result triggered",
        "GET",
        "GET",
    ),
    _e(
        _G_RESULTS,
        _PAIR + "/version/{consumerVersion}/verification-results/latest",
        "Latest result of a consumer version's pact",
        "GET",
        note="Use `…/pact-version/{sha}/verification-results/latest`.",
    ),
    _e(
        _G_RESULTS,
        _PAIR + "/latest/verification-results/latest",
        "Latest result of the latest pact",
        "GET",
        note="Use the matrix.",
    ),
    _e(
        _G_RESULTS,
        _PAIR + "/latest/{tag}/verification-results/latest",
        "Latest result of the latest tagged pact",
        "GET",
        note="Use the matrix.",
    ),
    _e(
        _G_RESULTS,
        "/verification-results/consumer/{consumer}/version/{consumerVersion}/latest",
        "Latest results for a consumer version",
        "GET",
        note="Use the matrix (`q[][pacticipant]=…&q[][version]=…`).",
    ),
    # Pacticipants and versions -----------------------------------------------------------------
    _e(
        _G_PARTICIPANTS,
        "/pacticipants",
        "List or create pacticipants",
        "GET POST",
        used_by="`pact-broker list-pacticipants`, `create-or-update-pacticipant`",
        note="Not planned in the broker shape.",
        alternative=_NATIVE,
    ),
    _e(
        _G_PARTICIPANTS,
        "/pacticipants/{pacticipant}",
        "A pacticipant",
        "GET PUT PATCH DELETE",
        "GET DELETE",
        used_by="`pact-broker describe-pacticipant`, `create-or-update-pacticipant`",
        note=(
            "To create or update one (main branch, repository URL) use Apiome's pacticipant API. "
            "`DELETE` is soft: restorable until it is purged, and refused while a version is deployed "
            "unless `force=true`."
        ),
        alternative=_NATIVE + "/{pacticipant}",
    ),
    _e(
        _G_PARTICIPANTS,
        "/pacticipants/{pacticipant}/versions",
        "Versions of a pacticipant",
        "GET",
        note="Not planned in the broker shape.",
        alternative=_NATIVE + "/{pacticipant}/versions",
    ),
    _e(
        _G_PARTICIPANTS,
        _VERSION,
        "A pacticipant version",
        "GET PUT PATCH DELETE",
        "GET DELETE",
        used_by="`pact-broker describe-version`, `record-deployment`, `create-or-update-version`",
        note=(
            "To record a version without publishing a pact use Apiome's pacticipant API. `DELETE` is "
            "soft: restorable until it is purged, and refused while it is deployed unless `force=true`."
        ),
        alternative=_NATIVE + "/{pacticipant}/versions/{version}",
    ),
    _e(
        _G_PARTICIPANTS,
        "/pacticipants/{pacticipant}/latest-version",
        "Latest version of a pacticipant",
        "GET",
        used_by="`pact-broker describe-version --latest`",
        note="Not planned in the broker shape.",
        alternative=_NATIVE + "/{pacticipant}/versions",
    ),
    _e(
        _G_PARTICIPANTS,
        "/pacticipants/{pacticipant}/latest-version/{tag}",
        "Latest version with a tag",
        "GET",
        note="Not planned in the broker shape.",
        alternative=_NATIVE + "/{pacticipant}/versions?tag={tag}",
    ),
    _e(
        _G_PARTICIPANTS,
        "/pacticipants/{pacticipant}/deployed-or-released/versions",
        "Versions deployed or released anywhere",
        "GET",
        note="Use the environment's `currently-deployed` and `currently-supported` lists.",
    ),
    _e(
        _G_PARTICIPANTS,
        "/pacticipants/{pacticipant}/environments/{uuid}/versions",
        "Versions in an environment",
        "GET",
        note="Use the environment's `currently-deployed` and `currently-supported` lists.",
    ),
    # Branches and tags ------------------------------------------------------------------------------
    _e(
        _G_BRANCHES,
        "/pacticipants/{pacticipant}/branches",
        "Branches of a pacticipant",
        "GET DELETE",
        note="Not planned in the broker shape.",
        alternative=_NATIVE + "/{pacticipant}/branches",
    ),
    _e(
        _G_BRANCHES,
        _BRANCH,
        "A branch",
        "GET DELETE",
        used_by="`pact-broker delete-branch`",
        note="Not planned: a branch goes when its versions are deleted, by hand or by a retention run.",
        alternative=_RETENTION,
    ),
    _e(
        _G_BRANCHES,
        _BRANCH + "/versions",
        "Versions on a branch",
        "GET",
        note="Not planned in the broker shape.",
        alternative=_NATIVE + "/{pacticipant}/versions?branch={branch}",
    ),
    _e(
        _G_BRANCHES,
        _BRANCH + "/versions/{version}",
        "Add a version to a branch",
        "GET PUT DELETE",
        "PUT",
        used_by="`pact-broker create-version-tag --auto-create-version`, pact-jvm",
        note="A version's branches are on its own document; taking one off a branch is not planned.",
    ),
    _e(
        _G_BRANCHES,
        _BRANCH + "/latest-version",
        "Latest version on a branch",
        "GET",
        note="Not planned in the broker shape.",
        alternative=_NATIVE + "/{pacticipant}/branches",
    ),
    _e(
        _G_BRANCHES,
        _VERSION + "/tags/{tag}",
        "A tag on a version",
        "GET PUT DELETE",
        "PUT",
        used_by="`pact-broker create-version-tag`, `publish --tag`",
        note="A version's tags are on its own document; removing one tag is not planned.",
    ),
    _e(
        _G_BRANCHES,
        "/pacticipants/{pacticipant}/tags/{tag}/versions",
        "Versions with a tag",
        "GET",
        note="Not planned in the broker shape.",
        alternative=_NATIVE + "/{pacticipant}/versions?tag={tag}",
    ),
    # Environments and deployments -------------------------------------------------------------
    _e(
        _G_ENVIRONMENTS,
        "/environments",
        "List or create environments",
        "GET POST",
        "GET POST",
        used_by="`pact-broker list-environments`, `create-environment`",
    ),
    _e(
        _G_ENVIRONMENTS,
        "/environments/{uuid}",
        "An environment",
        "GET PUT DELETE",
        "GET PUT DELETE",
        used_by="`pact-broker describe-environment`, `update-environment`, `delete-environment`",
    ),
    _e(
        _G_ENVIRONMENTS,
        "/environments/{uuid}/deployed-versions/currently-deployed",
        "What is deployed in an environment",
        "GET",
        "GET",
        used_by="`pact-broker record-undeployment`",
    ),
    _e(
        _G_ENVIRONMENTS,
        "/environments/{uuid}/released-versions/currently-supported",
        "What is released and supported",
        "GET",
        "GET",
        used_by="`pact-broker record-support-ended`",
    ),
    _e(
        _G_ENVIRONMENTS,
        _VERSION + "/deployed-versions/environment/{uuid}",
        "Record a deployment",
        "GET POST",
        "GET POST",
        used_by="`pact-broker record-deployment`",
    ),
    _e(
        _G_ENVIRONMENTS,
        _VERSION + "/released-versions/environment/{uuid}",
        "Record a release",
        "GET POST",
        "GET POST",
        used_by="`pact-broker record-release`",
    ),
    _e(
        _G_ENVIRONMENTS,
        "/deployed-versions/{uuid}",
        "A deployment (mark it undeployed)",
        "GET PATCH",
        "GET PATCH",
        used_by="`pact-broker record-undeployment`",
    ),
    _e(
        _G_ENVIRONMENTS,
        "/released-versions/{uuid}",
        "A release (end its support)",
        "GET PATCH",
        "GET PATCH",
        used_by="`pact-broker record-support-ended`",
    ),
    # Matrix and can-i-deploy ------------------------------------------------------------------
    _e(
        _G_MATRIX,
        "/matrix",
        "The compatibility matrix",
        "GET",
        "GET",
        used_by="`pact-broker can-i-deploy`",
    ),
    _e(_G_MATRIX, "/can-i-deploy", "Can a version be deployed to an environment", "GET", "GET"),
    _e(
        _G_MATRIX,
        "/matrix/provider/{provider}/consumer/{consumer}",
        "The matrix of one integration",
        "GET",
        note="Use `GET …/matrix` with two `q[]` selectors.",
    ),
    _e(
        _G_MATRIX,
        "/pacticipants/{pacticipant}/latest-version/{tag}/can-i-deploy/to/{to}",
        "Can the latest tagged version be deployed to a tag",
        "GET",
        note="Tags are legacy; use `GET …/can-i-deploy`.",
    ),
    _e(
        _G_MATRIX,
        _BRANCH + "/latest-version/can-i-deploy/to-environment/{environment}",
        "Can a branch's latest version be deployed",
        "GET",
        note="Use `GET …/can-i-deploy` with the version.",
    ),
    # Webhooks -----------------------------------------------------------------------------------
    _e(
        _G_WEBHOOKS,
        "/webhooks",
        "List or create webhooks",
        "GET POST",
        "GET POST",
        used_by="`pact-broker create-webhook`",
    ),
    _e(
        _G_WEBHOOKS,
        "/webhooks/{uuid}",
        "A webhook",
        "GET PUT DELETE",
        "GET PUT DELETE",
        used_by="`pact-broker create-or-update-webhook`",
    ),
    _e(
        _G_WEBHOOKS,
        "/webhooks/{uuid}/execute",
        "Run a webhook now",
        "POST",
        "POST",
        used_by="`pact-broker test-webhook`",
    ),
    _e(_G_WEBHOOKS, "/webhooks/execute", "Run an unsaved webhook", "POST", "POST"),
    _e(
        _G_WEBHOOKS,
        "/webhooks/provider/{provider}/consumer/{consumer}",
        "Webhooks of an integration",
        "GET POST",
        "GET POST",
    ),
    _e(_G_WEBHOOKS, "/webhooks/provider/{provider}", "Webhooks of a provider", "GET POST", "GET POST"),
    _e(_G_WEBHOOKS, "/webhooks/consumer/{consumer}", "Webhooks of a consumer", "GET POST", "GET POST"),
    _e(_G_WEBHOOKS, _PAIR + "/webhooks", "Webhooks of a pact", "GET POST", "GET POST"),
    _e(_G_WEBHOOKS, _PAIR + "/webhooks/status", "Webhook status of a pact", "GET", "GET"),
    _e(
        _G_WEBHOOKS,
        _PAIR + "/version/{consumerVersion}/triggered-webhooks",
        "Webhooks a publication triggered",
        "GET",
        "GET",
    ),
    _e(_G_WEBHOOKS, "/triggered-webhooks/{uuid}/logs", "Execution log of a webhook run", "GET", "GET"),
    # Badges -----------------------------------------------------------------------------------------
    _e(_G_BADGES, _PAIR + "/latest/badge", "Badge of the latest pact", "GET", note=_BADGE_NOTE, alternative=_BADGES),
    _e(
        _G_BADGES,
        _PAIR + "/latest/{tag}/badge",
        "Badge of the latest tagged pact",
        "GET",
        note=_BADGE_NOTE,
        alternative=_BADGES,
    ),
    _e(
        _G_BADGES,
        _PAIR + "/latest-untagged/badge",
        "Badge of the latest untagged pact",
        "GET",
        note=_BADGE_NOTE,
        alternative=_BADGES,
    ),
    _e(
        _G_BADGES,
        "/matrix/provider/{provider}/latest/{providerTag}/consumer/{consumer}/latest/{tag}/badge",
        "Badge of a tagged matrix row",
        "GET",
        note=_BADGE_NOTE,
        alternative=_BADGES,
    ),
    _e(
        _G_BADGES,
        "/pacticipants/{pacticipant}/latest-version/{tag}/can-i-deploy/to/{to}/badge",
        "can-i-deploy badge (tag to tag)",
        "GET",
        note=_BADGE_NOTE,
        alternative=_BADGES,
    ),
    _e(
        _G_BADGES,
        _BRANCH + "/latest-version/can-i-deploy/to-environment/{environment}/badge",
        "can-i-deploy badge (branch to environment)",
        "GET",
        note=_BADGE_NOTE,
        alternative=_BADGES,
    ),
    _e(
        _G_BADGES,
        "/pacticipants/{pacticipant}/main-branch/can-i-merge/badge",
        "can-i-merge badge",
        "GET",
        note=_BADGE_NOTE,
        alternative=_BADGES,
    ),
    # Labels -----------------------------------------------------------------------------------------
    _e(_G_LABELS, "/labels", "Every label", "GET", "GET"),
    _e(_G_LABELS, "/pacticipants/label/{label}", "Pacticipants with a label", "GET", "GET"),
    _e(
        _G_LABELS,
        "/pacticipants/{pacticipant}/labels/{label}",
        "A label on a pacticipant",
        "GET PUT DELETE",
        "GET PUT DELETE",
        note="`PUT` on an unknown pacticipant is a 404; the Pact Broker would create the pacticipant.",
    ),
    # Other ----------------------------------------------------------------------------------------------
    _e(
        _G_OTHER,
        "/integrations",
        "Every integration",
        "GET DELETE",
        note="The Contracts workspace UI lists integrations (PFX-5.3, #6947).",
    ),
    _e(
        _G_OTHER,
        "/integrations/provider/{provider}/consumer/{consumer}",
        "Delete an integration",
        "DELETE",
        note="Not planned: delete the consumer's versions (or a pacticipant) instead.",
        alternative=_RETENTION,
    ),
    _e(_G_OTHER, "/dashboard", "Dashboard data", "GET", note="The Pact Broker's own UI; Apiome has its own."),
    _e(
        _G_OTHER,
        "/dashboard/provider/{provider}/consumer/{consumer}",
        "Dashboard data of an integration",
        "GET",
        note="The Pact Broker's own UI; Apiome has its own.",
    ),
    _e(_G_OTHER, "/relationships", "Integrations as CSV", "GET", note="The Pact Broker's own UI."),
    _e(_G_OTHER, "/groups/{pacticipant}", "Network graph data", "GET", note="See PFX-5.3 (#6947)."),
    _e(_G_OTHER, "/metrics", "Row counts", "GET", note="Apiome reports usage under `/v1/ops`."),
    _e(_G_OTHER, "/test/error", "Error test", "GET POST", note="A Pact Broker diagnostic."),
    # Provider contracts (PactFlow's bi-directional contract testing) ----------------------------
    _e(
        _G_PROVIDER_CONTRACTS,
        "/contracts/provider/{provider}/version/{providerVersion}",
        "The OpenAPI provider contract of a provider version",
        "GET PUT",
        "GET PUT",
        used_by="PactFlow's provider-contract publishing API",
        note=(
            "Also takes `apiomeVersion` to render the contract from an Apiome version (PFX-2.1, #6925). "
            "Publishing compares the contract with the pacts that need it and stores bi-directional "
            "verification results; the answer lists them in `comparisons` (PFX-2.3, #6927). "
            "`verificationResults` is read — JUnit, Newman JSON, Schemathesis NDJSON, or an Apiome "
            "report via `providerVerificationReportId` — into `selfVerification`; a contract without "
            "passing evidence is unverified (PFX-2.4, #6928)."
        ),
    ),
    # Apiome additions: not Pact Broker or PactFlow endpoints, served under the broker base URL so
    # `apiome pact` commands reach them with the same base URL and token -----------------------
    _e(
        _G_APIOME,
        "/pacts/check",
        "Check a pact against provider versions before publishing",
        "POST",
        "POST",
        used_by="`apiome pact check`, the Publish page",
        note=(
            "Not a Pact Broker endpoint. Compares an unpublished pact with the provider contracts of "
            "the versions `against` names (`main`, `deployed:<env>`, `version:<n>`, `draft:<revision>`) "
            "and stores nothing (PFX-8.4, #7301)."
        ),
    ),
)


def find_endpoint(path: str) -> Optional[BrokerEndpoint]:
    """The catalog entry a concrete request path is, the most specific when several match.

    ``…/latest/badge`` matches both ``…/latest/{tag}`` and ``…/latest/badge``; the one with more
    fixed segments wins, as in the Pact Broker's router.

    Args:
        path: The request path after the broker base URL (``""`` or ``/`` is the index).

    Returns:
        The entry, or ``None`` when the path is no Pact Broker resource.
    """
    candidates = [endpoint for endpoint in ENDPOINTS if endpoint.matches(path)]
    if not candidates:
        return None
    return max(candidates, key=lambda endpoint: endpoint.literal_segments)


def endpoints_by_group() -> Dict[str, List[BrokerEndpoint]]:
    """The catalog grouped by section, in :data:`GROUPS` order."""
    grouped: Dict[str, List[BrokerEndpoint]] = {group: [] for group in GROUPS}
    for endpoint in ENDPOINTS:
        grouped[endpoint.group].append(endpoint)
    return grouped


def status_counts(endpoints: Sequence[BrokerEndpoint] = ENDPOINTS) -> Dict[str, int]:
    """How many endpoints have each status, in :data:`STATUSES` order."""
    counts = {status: 0 for status in STATUSES}
    for endpoint in endpoints:
        counts[endpoint.status] += 1
    return counts


def compatibility_url() -> str:
    """The published URL of the compatibility page."""
    return site_url(COMPATIBILITY_PAGE)
