"""Slate Edge functions and safe personalization — UXE-3.3 (private-suite#2475).

The decisions that must hold before a function, a capability grant, an egress allowance or a
personalization variant is written, and the evaluation that explains what those things would do
to a request, kept in one pure module so they can be tested exhaustively without a database and
so the REST layer cannot implement a second, subtly different copy of them. It is the function
counterpart of :mod:`app.slate_cache` and :mod:`app.slate_security` and deliberately reads like
them: an operator who has learned what ``glob`` means on the cache surface, or what ``simulate``
means on the security surface, must not have to relearn either here.

The refusal vocabulary is shared with the authoring surface's ``AuthoringEdgeRefusalReason`` for
the reason :mod:`app.slate_cache` states: the surface makes ``disabledReason`` the only way to
disable a control, so a backend that invented its own codes would leave the operator with a
greyed-out dead end instead of a sentence explaining what to do.

Five things are worth stating outright, and the last one is the whole ticket.

1. **Catalogs are values, not adjectives.** :data:`CAPABILITY_CATALOG`, :data:`RUNTIME_CATALOG`,
   :data:`RESIDENCY_CLASS_CATALOG` and :data:`CACHE_KEY_EFFECT_CATALOG` are tables of literals,
   each stating in prose what it will and will not do. "Deny-by-default" is not a mood the system
   interprets at request time; it is the absence of a grant row, and the catalog is what tells an
   operator what granting one actually costs. A capability that cannot say what it is unsafe for
   fails a golden test, not a code review.

2. **Secrets are references, and a reference cannot cross a boundary.** §29.5's first flat
   prohibition is that no arbitrary function reads tenant secrets or crosses project boundaries.
   V189 makes the first half a schema impossibility — ``slate_function_secret_refs`` has no
   column able to hold a value — and :data:`_HARD_REFUSALS` makes the second half a refusal with
   no acknowledgement path, because a cross-project reference is not a cost somebody may accept
   on their own authority.

3. **Deny-by-default is a runtime answer, not a write-time refusal.** A function configured with
   no ``fetch-egress`` grant is configured perfectly legally; it simply cannot reach the network.
   So :func:`simulate_invocation` reports ``capability-denied`` and ``egress-denied`` as
   *outcomes in the considered list*, and only a function that *declares* a destination outside
   its own allowlist is refused at write time. Confusing those two would either refuse ordinary
   functions or hide the denial that will actually happen.

4. **Personalization is only safe when it says what it did to the cache key.** A variant that
   varies a shared cache key on an identity credential serves one reader's page to another — the
   exact defect §29.3 refuses for cache — so it is refused here rather than warned about.

5. **Nothing here runs anything.** ``deploy/`` is a single Caddyfile: there is no isolate pool,
   no WASM runtime and no egress proxy. This module plans, explains and simulates; the store
   records. An unenforced cache rule wastes a purge and an unenforced WAF rule leaves an attacker
   unblocked — but a green "ran" row would be evidence of an isolation guarantee that was never
   tested, which is worse than either. So :class:`InvocationVerdict` carries ``executed``,
   ``observed`` and ``enforced`` as fields this module always sets to ``False``, and there is no
   code path here able to set them otherwise.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

__all__ = [
    "CACHE_KEY_EFFECTS",
    "CACHE_KEY_EFFECT_CATALOG",
    "CAPABILITIES",
    "CAPABILITY_CATALOG",
    "CHANGE_KINDS",
    "CONSENT_BASES",
    "EGRESS_DESTINATION_KINDS",
    "EGRESS_SCHEMES",
    "INVOCATION_OUTCOMES",
    "MATCHER_KINDS",
    "PRIVACY_CLASSES",
    "RESIDENCY_CLASSES",
    "RESIDENCY_CLASS_CATALOG",
    "ROLLOUT_MODES",
    "RUNTIMES",
    "RUNTIME_CATALOG",
    "SECRET_SCOPES",
    "SOURCE_ORIGINS",
    "CacheKeyEffect",
    "CapabilityDefinition",
    "FunctionRefusal",
    "FunctionRefusalReason",
    "FunctionWarning",
    "InvocationRequest",
    "InvocationVerdict",
    "ResidencyClass",
    "RuntimeProfile",
    "SlateFunctionRefusedError",
    "body_digest",
    "covers_everything",
    "evaluate_approval_safety",
    "evaluate_capability_safety",
    "evaluate_egress_safety",
    "evaluate_function_safety",
    "evaluate_policy_safety",
    "evaluate_variant_safety",
    "functions_digest",
    "matches_route",
    "normalize_capability",
    "normalize_egress_rule",
    "normalize_function",
    "normalize_policy",
    "normalize_secret_ref",
    "normalize_variant",
    "simulate_invocation",
]

# ─── Enumerations, mirroring V189's CHECK constraints ─────────────────────────

#: The four matcher kinds, identical to ``slate_cache_rules`` and ``slate_security_rules``.
#: Sharing them is the point: three surfaces that spelled route matching differently would make
#: two of them a trap.
MATCHER_KINDS = ("exact", "prefix", "glob", "regex")

#: Execution environments, ordered by how narrow the sandbox is. An isolate with no filesystem is
#: a smaller blast radius than a WASM module with a host interface.
RUNTIMES = ("js-isolate", "wasm")

#: A function is either recording what it would have done, or acting.
ROLLOUT_MODES = ("simulate", "enforce")

#: What crossing a border is allowed to mean, most restrictive first. The order is load-bearing:
#: :func:`evaluate_function_safety` compares indices to decide whether a function is trying to be
#: more permissive than its lane.
RESIDENCY_CLASSES = ("in-region-only", "region-pinned", "unrestricted")

#: What a function may do at runtime, ordered safest-first. Reading geography is a smaller
#: privilege than reading a secret, and writing a cookie is how a function reaches into a
#: reader's session. Deny-by-default is the absence of a grant, not a value in this tuple.
CAPABILITIES = (
    "geo-read",
    "env-read",
    "kv-read",
    "kv-write",
    "crypto-subtle",
    "fetch-egress",
    "cookie-write",
    "secret-read",
)

#: What a personalization variant does to the shared cache key, safest first.
CACHE_KEY_EFFECTS = ("none", "vary-on-dimension", "bypass-cache")

#: §29.5's privacy classification, least personal first.
PRIVACY_CLASSES = ("non-personal", "pseudonymous", "personal")

#: Ordered by how defensible the basis is. ``not-required`` is only honest for non-personal data,
#: which V189 also enforces with a CHECK.
CONSENT_BASES = ("not-required", "explicit-consent", "legitimate-interest")

#: How far a secret reference reaches, narrowest first.
SECRET_SCOPES = ("function", "environment")

#: How an egress destination is matched, narrowest first. There is deliberately no wildcard kind:
#: an egress allowlist with a wildcard is a denylist wearing a costume.
EGRESS_DESTINATION_KINDS = ("exact-host", "host-suffix")

#: Egress schemes, https first because a plaintext hop is the one that leaks in transit.
EGRESS_SCHEMES = ("https", "http")

#: What an invocation record concludes, ordered from "nothing happened" to "something went
#: wrong". ``would-run`` is what a simulated function reports; nothing in this module can produce
#: ``ran``, because there is nothing to run code in.
INVOCATION_OUTCOMES = (
    "skipped",
    "would-run",
    "ran",
    "refused",
    "capability-denied",
    "egress-denied",
    "limit-exceeded",
    "error",
)

#: How a source version arrived, so an artifact can be traced back.
SOURCE_ORIGINS = ("upload", "build", "import")

#: What produced a revision, so a revert of a revert reads correctly in history.
CHANGE_KINDS = (
    "created",
    "updated",
    "disabled",
    "deleted",
    "reverted",
    "rollout-changed",
    "version-added",
)


# ─── Runtime catalog ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RuntimeProfile:
    """One execution environment, as a complete set of values rather than a name.

    Attributes:
        key: One of :data:`RUNTIMES`.
        label: Operator-facing name.
        intent: The one-line intent, quoted from roadmap §29.5 rather than paraphrased.
        expected_impact: What choosing this runtime means for the blast radius of a function that
            misbehaves, in prose. A runtime that cannot say what escaping it would cost is a
            runtime nobody can safely choose.
        sandbox: What the sandbox does and does not contain.
        unsafe_if: What this runtime is a poor fit for, as sentences the UI renders next to it.
    """

    key: str
    label: str
    intent: str
    expected_impact: str
    sandbox: str
    unsafe_if: Tuple[str, ...]


RUNTIME_CATALOG: Mapping[str, RuntimeProfile] = {
    "js-isolate": RuntimeProfile(
        key="js-isolate",
        label="JavaScript isolate",
        intent="Small, short-lived request handlers with no host interface",
        expected_impact=(
            "The safe default, and the runtime a documentation lane should use. An isolate starts "
            "with no filesystem, no process table and no ambient network, so the only things a "
            "function can reach are the ones granted to it by name. The cost is that anything "
            "needing a compiled dependency or more than a few tens of milliseconds of CPU does "
            "not fit, and a function that outgrows the isolate is better moved to the origin than "
            "given a wider runtime."
        ),
        sandbox=(
            "No filesystem, no subprocesses, no ambient sockets. Capabilities and egress are the "
            "only doors, and both are closed until a grant row exists."
        ),
        unsafe_if=(
            "The work is CPU-heavy: an isolate is billed and bounded in milliseconds, and a "
            "function that needs more of them will be terminated mid-request rather than slowed.",
            "The code depends on a native module, which an isolate cannot load at all.",
        ),
    ),
    "wasm": RuntimeProfile(
        key="wasm",
        label="WebAssembly module",
        intent="Compiled modules that need a host interface",
        expected_impact=(
            "Runs precompiled modules, which makes languages other than JavaScript usable and "
            "makes cold starts predictable. The trade is the host interface: a WASM module talks "
            "to the world through imported host functions, and every one of those imports is a "
            "door the isolate runtime simply does not have. Expect capability review to be longer "
            "and expect the module's imports to be part of what gets approved, not just its "
            "source digest."
        ),
        sandbox=(
            "Linear memory with no ambient authority, plus whatever host functions the module "
            "imports. The imports are the attack surface, so they are reviewed as capabilities."
        ),
        unsafe_if=(
            "The module's imports have not been reviewed: a WASM module is only as contained as "
            "the host interface it was linked against.",
            "The work would fit in an isolate: choosing the wider runtime for a handler that did "
            "not need it widens the blast radius for nothing.",
        ),
    ),
}


# ─── Capability catalog ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class CapabilityDefinition:
    """One runtime capability, versioned in code rather than seeded per environment.

    V189 models deny-by-default as the *absence* of a row, so there is no table anywhere that
    lists what the capabilities are. That only works if the catalog is a reviewable literal —
    which is why this lives here, in a diff, and not in a seed script that drifts per tenant.

    Attributes:
        id: Catalog identifier, stored in ``slate_function_capabilities.capability``.
        title: Operator-facing name.
        description: What the capability lets a function do, in the terms an operator would use.
        expected_impact: What granting it actually costs, including the failure mode it makes
            possible. A capability that cannot say what it opens is one nobody can review.
        requires_expiry: Whether a grant of this capability must carry an expiry. True for the
            capabilities whose legitimate uses are incidents and migrations rather than steady
            state; see :data:`_MAX_CAPABILITY_WINDOW_DAYS`.
        privacy_reach: Whether the capability can touch reader data at all —
            ``none``, ``coarse`` or ``identifying``.
        unsafe_if: Sentences the UI renders next to the grant control.
    """

    id: str
    title: str
    description: str
    expected_impact: str
    requires_expiry: bool
    privacy_reach: str
    unsafe_if: Tuple[str, ...]


CAPABILITY_CATALOG: Mapping[str, CapabilityDefinition] = {
    "geo-read": CapabilityDefinition(
        id="geo-read",
        title="Read request geography",
        description=(
            "Lets the function read the country and region the request appears to come from, as "
            "resolved by the edge rather than from anything the client sent."
        ),
        expected_impact=(
            "The smallest grant on this list and the one most personalization actually needs. "
            "Country is coarse enough that it identifies nobody on its own, but it is still a "
            "fact about a reader: a variant that branches on it has moved from serving a document "
            "to observing an audience, and the privacy classification on the variant is where "
            "that gets recorded."
        ),
        requires_expiry=False,
        privacy_reach="coarse",
        unsafe_if=(
            "The lane promised readers that nothing about their location is used: geography is "
            "the first thing a reader assumes is not being read.",
        ),
    ),
    "env-read": CapabilityDefinition(
        id="env-read",
        title="Read environment variables",
        description=(
            "Lets the function read the non-secret environment variables named on it. Secret "
            "material is not reachable this way and has no column in this schema at all."
        ),
        expected_impact=(
            "Reads configuration the operator put there deliberately, so the exposure is exactly "
            "the set of names on the function and nothing wider. The failure this grant enables "
            "is not a leak but a mistake: an operator who puts a credential into an environment "
            "variable because it was easier than declaring a secret reference has made this "
            "capability into secret-read without the review that comes with it."
        ),
        requires_expiry=False,
        privacy_reach="none",
        unsafe_if=(
            "Any environment variable on this lane holds credential material: move it to a secret "
            "reference first, because this grant does not distinguish the two.",
        ),
    ),
    "kv-read": CapabilityDefinition(
        id="kv-read",
        title="Read from key-value storage",
        description=(
            "Lets the function read the lane's key-value namespace — feature flags, redirect "
            "tables, cohort assignments and similar small shared state."
        ),
        expected_impact=(
            "Reads shared state that other functions on the lane wrote. Nothing leaves the lane, "
            "and nothing is modified. The realistic cost is latency rather than exposure: a "
            "handler that reads on every request has added a lookup to every page load, and the "
            "wall-clock ceiling is what will notice first."
        ),
        requires_expiry=False,
        privacy_reach="none",
        unsafe_if=(
            "The namespace holds anything derived from a reader: key-value storage is shared "
            "across functions, so a per-reader value written by one function is readable by all "
            "of them.",
        ),
    ),
    "kv-write": CapabilityDefinition(
        id="kv-write",
        title="Write to key-value storage",
        description=(
            "Lets the function write to the lane's key-value namespace, including keys other "
            "functions read."
        ),
        expected_impact=(
            "Turns a request handler into a writer of shared state, which is the point at which "
            "one function's bug becomes another function's input. A handler that writes per-reader "
            "keys also turns a shared namespace into a store of reader data with no retention "
            "policy attached to it. Grant it for the migration or the experiment that needs it and "
            "let it lapse."
        ),
        requires_expiry=True,
        privacy_reach="identifying",
        unsafe_if=(
            "The function writes a key derived from the reader: that is a personal-data store "
            "created by a capability grant rather than by a schema, and nothing will expire it.",
            "Steady-state operation: a permanent write grant means every future revision of this "
            "function inherits it without anybody deciding to.",
        ),
    ),
    "crypto-subtle": CapabilityDefinition(
        id="crypto-subtle",
        title="Use subtle cryptography",
        description=(
            "Lets the function use the platform's cryptographic primitives — signing, verifying, "
            "hashing and key derivation."
        ),
        expected_impact=(
            "Enables signature verification of incoming webhooks and of signed URLs, which is "
            "usually a security improvement rather than a cost. What it also enables is a function "
            "deriving a stable identifier from something about a reader, which is how "
            "pseudonymous tracking gets built without anybody deciding to build it. The privacy "
            "classification on the variant is where that has to be declared."
        ),
        requires_expiry=False,
        privacy_reach="coarse",
        unsafe_if=(
            "The function hashes a reader attribute to produce a stable id: that is pseudonymous "
            "personal data however irreversible the hash is.",
        ),
    ),
    "fetch-egress": CapabilityDefinition(
        id="fetch-egress",
        title="Make outbound requests",
        description=(
            "Lets the function make outbound HTTP requests, and only to destinations that have "
            "their own allowlist row. The capability opens the door; the egress rules decide "
            "where it leads."
        ),
        expected_impact=(
            "This is the grant that turns the edge into a client. Every outbound request is a "
            "place a reader's data can go and a place a slow third party can hold a page open, "
            "and an unbounded version of it is an SSRF relay with the tenant's network position. "
            "It is deliberately two decisions rather than one: granting it does nothing until a "
            "destination is allowlisted, so a mistake in either place fails closed."
        ),
        requires_expiry=True,
        privacy_reach="identifying",
        unsafe_if=(
            "No destination has been allowlisted yet: the grant is inert, which is safe, but it "
            "is also not what the operator thinks they configured.",
            "The intended destination is a host suffix rather than an exact host: a suffix "
            "includes every subdomain anybody ever creates under it.",
        ),
    ),
    "cookie-write": CapabilityDefinition(
        id="cookie-write",
        title="Write response cookies",
        description=(
            "Lets the function set cookies on the response, which persist on the reader's device "
            "across requests and sites under the same domain."
        ),
        expected_impact=(
            "Reaches into the reader's browser and leaves something there. A cookie written for a "
            "cohort assignment is an identifier by any reading of the word, so a variant that "
            "depends on one is at least pseudonymous and needs a consent basis to match. The "
            "second cost is cacheability: a response that carries a Set-Cookie is a response that "
            "must not be served to the next reader, and forgetting that is exactly the shared-key "
            "defect this module refuses."
        ),
        requires_expiry=True,
        privacy_reach="identifying",
        unsafe_if=(
            "The variant using it is still classified non-personal: writing an identifier and "
            "declaring no personal data are not both true.",
            "The response is cached with an unchanged key: the next reader receives somebody "
            "else's cookie.",
        ),
    ),
    "secret-read": CapabilityDefinition(
        id="secret-read",
        title="Resolve secret references",
        description=(
            "Lets the function have its declared secret references resolved at the runtime "
            "boundary. It does not let the function enumerate secrets, and no secret value exists "
            "anywhere in this schema to be read."
        ),
        expected_impact=(
            "The most consequential grant here, and the one §29.5 names outright. It does not "
            "hand the function a vault — only the aliases already declared on it — but a function "
            "with this grant plus outbound egress can carry a credential off the lane in one "
            "request, which is why the two are reviewed together and why both lapse. Grant it for "
            "the integration that genuinely needs it, name the secret, and set an end date."
        ),
        requires_expiry=True,
        privacy_reach="none",
        unsafe_if=(
            "The same function also holds fetch-egress to a destination you do not operate: that "
            "pair is a credential exfiltration path with an approval attached to it.",
            "The secret belongs to another project or environment: that is refused outright, "
            "because a cross-boundary reference is not a risk anybody may accept locally.",
        ),
    ),
}


# ─── Residency class catalog ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ResidencyClass:
    """One residency posture, stated as what it does and does not cover.

    §29.6 asks the UX to state what a residency option does *not* cover, which is the field most
    residency controls quietly omit. It is a required attribute here so an entry that omits it
    fails a test.

    Attributes:
        key: One of :data:`RESIDENCY_CLASSES`.
        label: Operator-facing name.
        intent: The one-line intent.
        expected_impact: What choosing it means for where execution and data actually happen.
        does_not_cover: What the option explicitly leaves outside its promise.
        permits_personal: Whether a variant classified ``personal`` may run under it.
        requires_waiver_reason: Whether choosing it must carry a stated reason, matching V189's
            ``slate_function_policies_unrestricted_needs_reason``.
        unsafe_if: Sentences the UI renders next to the choice.
    """

    key: str
    label: str
    intent: str
    expected_impact: str
    does_not_cover: str
    permits_personal: bool
    requires_waiver_reason: bool
    unsafe_if: Tuple[str, ...]


RESIDENCY_CLASS_CATALOG: Mapping[str, ResidencyClass] = {
    "in-region-only": ResidencyClass(
        key="in-region-only",
        label="In region only",
        intent="Execution and data stay inside the chosen region",
        expected_impact=(
            "The default, and the only value this system will pick for a lane nobody configured. "
            "A request that arrives outside the region is served without the function rather than "
            "by a function running elsewhere, so the residency promise is kept by dropping "
            "personalization rather than by moving data. Expect readers far from the region to "
            "see the fallback variant, which is the honest outcome and should be designed for."
        ),
        does_not_cover=(
            "Ingress and TLS termination, which happen wherever the reader connects, and the "
            "request metadata a network path necessarily carries."
        ),
        permits_personal=True,
        requires_waiver_reason=False,
        unsafe_if=(
            "The audience is genuinely global and the fallback variant is not good enough to be "
            "the majority experience.",
        ),
    ),
    "region-pinned": ResidencyClass(
        key="region-pinned",
        label="Region pinned",
        intent="Execution is pinned to a region; incidental processing may happen closer",
        expected_impact=(
            "Function execution and stored data stay in the chosen region, while cache storage "
            "and log shipping may transit closer to the reader. That is a weaker promise than "
            "in-region-only and a stronger one than unrestricted, and it is the honest choice for "
            "a lane that has a residency commitment about data at rest but not about every hop."
        ),
        does_not_cover=(
            "Cache storage and log transit, which follow the reader rather than the region, and "
            "any third party a function reaches through egress."
        ),
        permits_personal=True,
        requires_waiver_reason=False,
        unsafe_if=(
            "The commitment made to readers was about processing rather than storage: this option "
            "keeps storage in region and does not make the same promise about every hop.",
        ),
    ),
    "unrestricted": ResidencyClass(
        key="unrestricted",
        label="Unrestricted",
        intent="Execution happens wherever is closest",
        expected_impact=(
            "Functions run in whichever region receives the request, which is the fastest option "
            "and the one that makes no residency promise at all. This is the setting chosen for a "
            "latency problem and still set a year later, so it requires a stated reason and it is "
            "refused outright for any variant classified personal — moving a document is a "
            "performance decision, and moving a reader's personal data across a border is not."
        ),
        does_not_cover=(
            "Anything: this option is the absence of a residency guarantee, and describing it as "
            "covering some hops but not others would be a promise it cannot keep."
        ),
        permits_personal=False,
        requires_waiver_reason=True,
        unsafe_if=(
            "Any variant on this lane is classified personal: that combination is refused, "
            "because the residency promise and the data classification would contradict.",
            "The tenant has a residency commitment of any kind: this option is the one that "
            "silently ends it.",
        ),
    ),
}


# ─── Cache-key effect catalog ─────────────────────────────────────────────────


@dataclass(frozen=True)
class CacheKeyEffect:
    """What a personalization variant does to the shared cache key.

    §29.5 requires the cache-key effect to be shown beside the audience rule, and V189 stores
    them in one row for the same reason. This catalog is what the surface renders there.

    Attributes:
        key: One of :data:`CACHE_KEY_EFFECTS`.
        label: Operator-facing name.
        intent: The one-line intent.
        expected_impact: What it does to hit ratio and to the risk of serving one reader's page to
            another.
        fragments_cache: Whether choosing it multiplies the number of stored entries.
        safe_for_personal: Whether a variant above ``non-personal`` may use it.
        unsafe_if: Sentences the UI renders next to the choice.
    """

    key: str
    label: str
    intent: str
    expected_impact: str
    fragments_cache: bool
    safe_for_personal: bool
    unsafe_if: Tuple[str, ...]


CACHE_KEY_EFFECT_CATALOG: Mapping[str, CacheKeyEffect] = {
    "none": CacheKeyEffect(
        key="none",
        label="No change",
        intent="The variant does not touch the cache key",
        expected_impact=(
            "The cache behaves exactly as it did before the variant existed: one entry per route, "
            "shared by every reader. That is correct and free for a variant whose output is the "
            "same for everybody, and it is a defect for any variant that is not — the second "
            "reader gets whatever the first reader's request produced. V189 refuses this "
            "combination with a CHECK for anything above non-personal, and so does this module."
        ),
        fragments_cache=False,
        safe_for_personal=False,
        unsafe_if=(
            "The variant produces different output for different readers: leaving the key "
            "unchanged is how one reader's personalized page reaches another.",
        ),
    ),
    "vary-on-dimension": CacheKeyEffect(
        key="vary-on-dimension",
        label="Vary on a dimension",
        intent="One cache entry per value of a named dimension",
        expected_impact=(
            "Adds the named dimension to the cache key, so readers sharing a value share an entry. "
            "For a coarse dimension — a country, a language, a device class — that is a handful of "
            "entries per route and the hit ratio barely moves. For a high-cardinality dimension it "
            "is one entry per value, which for a cohort is dozens and for anything identifying is "
            "one entry per reader: a cache that stores everything and hits nothing, at origin "
            "cost. Varying on an identity credential is refused rather than warned about."
        ),
        fragments_cache=True,
        safe_for_personal=True,
        unsafe_if=(
            "The dimension is derived from a cookie, a session or any other identity credential: "
            "that is a private cache pretending to be a shared one, and it is refused.",
            "The dimension has hundreds of values: the entries are stored and almost never reused.",
        ),
    ),
    "bypass-cache": CacheKeyEffect(
        key="bypass-cache",
        label="Bypass the cache",
        intent="Responses from this variant are never stored or served from cache",
        expected_impact=(
            "The safest effect and the most expensive one. Nothing is stored, so nothing can be "
            "served to the wrong reader, and every matching request reaches the function and the "
            "origin. Correct for a genuinely per-reader response; wasteful for anything else, and "
            "the first symptom of choosing it too broadly is origin load rather than a wrong page."
        ),
        fragments_cache=False,
        safe_for_personal=True,
        unsafe_if=(
            "The audience rule is broad: bypassing the cache for most of the lane's traffic moves "
            "the whole load to the origin.",
        ),
    ),
}


# ─── Refusals and warnings ────────────────────────────────────────────────────

#: Every reason a function, capability, egress or variant write can be refused. Mirrors the UI's
#: ``AuthoringEdgeRefusalReason``.
FunctionRefusalReason = Literal[
    "secret-cross-project",
    "egress-unapproved",
    "capability-without-reason",
    "capability-unbounded",
    "enforce-without-simulation",
    "enforce-without-approval",
    "enforce-without-version",
    "variant-without-fallback",
    "variant-identity-cache-key",
    "variant-personal-without-basis",
    "residency-violation",
    "limit-exceeds-ceiling",
    "matcher-invalid",
    "ordinal-conflict",
    "policy-version-conflict",
    "approval-stale",
    "approval-self",
]

# One operator-facing sentence per refusal, returned verbatim by the REST layer so the reason a
# control is disabled reaches the operator as words rather than as a code. The reason code is
# ours to style and test against; the words are not, because two copies of these sentences would
# eventually disagree and the copy on screen would be the one an operator trusted.
_REFUSAL_SENTENCES: Dict[str, str] = {
    "secret-cross-project": (
        "This function references a secret belonging to another project or environment. A "
        "function that can reach across a boundary makes every tenant's isolation depend on this "
        "one function's code being correct. Declare a secret in this environment, or move the "
        "function to the environment that owns the one you meant."
    ),
    "egress-unapproved": (
        "This function declares an outbound call to a destination with no allowlist entry. An "
        "egress allowlist is the difference between a function and an SSRF relay with your "
        "network position, so nothing is reachable until it is named. Add an allowlist entry for "
        "the exact host, with the reason it is needed."
    ),
    "capability-without-reason": (
        "This grant has no stated reason. The question at review is never what was granted but "
        "why, and an empty answer is the one nobody can defend six months later. Say what the "
        "function needs it for."
    ),
    "capability-unbounded": (
        "This capability requires an expiry and either has none or has one so distant it is "
        "permanent in practice. A grant that cannot lapse outlives the incident or migration it "
        "was opened for. Give it an end date inside the review window and renew it deliberately."
    ),
    "enforce-without-simulation": (
        "This function would begin enforcing without ever having run in simulate. Simulate first: "
        "it records exactly which requests the function would have handled and what it would have "
        "done to the cache key, and it is the only way to find that out before readers do."
    ),
    "enforce-without-approval": (
        "An enforcing function needs an approval from somebody other than its author. Running "
        "code in the request path is the change where a second pair of eyes is worth the delay."
    ),
    "enforce-without-version": (
        "This function is set to enforce with no active version, so a rollout would be driven "
        "against no code at all and the simulation would report nothing. Add a version and make "
        "it active before enforcing."
    ),
    "variant-without-fallback": (
        "This variant names no fallback. Every reader the audience rule does not match would "
        "receive nothing, which is an outage for the majority and the ordinary case on the day an "
        "experiment ends. Name what everybody else gets."
    ),
    "variant-identity-cache-key": (
        "This variant personalizes a response without saying something safe about the shared "
        "cache key — either leaving the key untouched, or varying it on an identity credential. "
        "Both end the same way: a stored entry that was right for one reader is served to the "
        "next, which is the defect the cache surface refuses for the same reason. Vary on a "
        "coarse dimension, or bypass the cache entirely."
    ),
    "variant-personal-without-basis": (
        "This variant is classified as handling personal data while claiming consent was not "
        "required. Those two statements cannot both be true. Choose the basis you actually rely "
        "on, or reclassify what the variant reads."
    ),
    "residency-violation": (
        "This combination moves personal data outside the residency the lane promised, or "
        "loosens residency with no stated reason. Region and data policy are one decision, so a "
        "personal-class variant cannot run unrestricted and an unrestricted lane cannot be "
        "unexplained. Pin the region, or reclassify the variant."
    ),
    "limit-exceeds-ceiling": (
        "This function asks for a CPU, memory or wall-clock limit above the lane's ceiling. A "
        "function may tighten a ceiling and cannot raise it, because adding one function must not "
        "quietly raise the lane's worst case. Raise the lane ceiling deliberately, or fit inside "
        "it."
    ),
    "matcher-invalid": (
        "This route matcher does not compile, so it can never be evaluated. Fix the pattern."
    ),
    "ordinal-conflict": (
        "Another function already holds that precedence on this lane. Two functions at the same "
        "precedence would make which one ran depend on row order, and a simulation of that is not "
        "reproducible."
    ),
    "policy-version-conflict": (
        "Another operator changed this lane's function policy while this edit was being prepared. "
        "Re-read the policy and try again."
    ),
    "approval-stale": (
        "The approved body is not the body being written. An approval names what was reviewed, "
        "not just which function it was about; get the current body approved."
    ),
    "approval-self": (
        "The author of a change cannot approve it. Dual control with one person is a record, not "
        "a review."
    ),
}

#: Refusals with no acknowledgement path. Each one is a boundary crossing, an unreviewed
#: execution, an unbounded privilege or a cache defect that serves one reader's page to another —
#: never merely a cost. An "I accept the risk" checkbox over these would be a checkbox over
#: another tenant's isolation, or over the review that was supposed to prevent an incident. Every
#: refusal this module raises is hard; the set is spelled out in full anyway so a future reason
#: added to :data:`_REFUSAL_SENTENCES` has to decide which side it is on rather than defaulting
#: to one.
_HARD_REFUSALS = frozenset(
    {
        "secret-cross-project",
        "egress-unapproved",
        "capability-without-reason",
        "capability-unbounded",
        "enforce-without-simulation",
        "enforce-without-approval",
        "enforce-without-version",
        "variant-without-fallback",
        "variant-identity-cache-key",
        "variant-personal-without-basis",
        "residency-violation",
        "limit-exceeds-ceiling",
        "matcher-invalid",
        "ordinal-conflict",
        "policy-version-conflict",
        "approval-stale",
        "approval-self",
    }
)

#: Warning reasons an operator may acknowledge. These cost hit ratio, attribution or clarity;
#: none of them crosses a tenant boundary, runs unreviewed code or serves one reader's page to
#: another.
_WARNING_SENTENCES: Dict[str, str] = {
    "broad-matcher": (
        "This function runs on a large share of the lane. That is right for a handler that only "
        "adds a header and expensive for one that does real work, because the routes it catches "
        "by accident are the ones nobody tested."
    ),
    "cache-fragmenting": (
        "This variant varies the cache key on a high-cardinality dimension, so the cache will "
        "hold many entries per route and hit few of them. The symptom is origin load rather than "
        "a wrong page, and it usually appears a week after the change."
    ),
    "rollout-jump": (
        "This function goes from reaching no traffic to reaching all of it in one step. A staged "
        "rollout exists so a mistake is visible at 1% instead of at 100%."
    ),
    "variant-without-analytics": (
        "This variant reports under no analytics dimension, so a regression it causes will be "
        "attributed to the release as a whole. That is the difference between finding the variant "
        "in an afternoon and finding it in a week."
    ),
    "limit-near-ceiling": (
        "This function's limits are close to the lane ceiling, so an ordinary slow day will "
        "terminate it mid-request rather than merely slow it. Leave headroom, or raise the lane "
        "ceiling deliberately."
    ),
    "function-shadowed": (
        "A higher-precedence function already covers everything this one matches, so it can never "
        "run. That is usually an editing mistake."
    ),
}

#: Above this share of the lane, a matcher is broad enough to be worth a sentence. **Invented**,
#: not derived from the roadmap, and expressed as a prefix depth rather than a percentage because
#: the lane's route inventory is not available here — a function anchored at or above the first
#: path segment is the broad case. Identical to the security surface's threshold on purpose.
_BROAD_MATCHER_MAX_SEGMENTS = 1

#: How close to a lane ceiling a function's own limit may sit before it is worth a sentence.
#: **Invented.** 0.9 is not a measured figure; it is the point at which the remaining headroom is
#: smaller than the ordinary variation between a warm and a cold execution, so the first slow day
#: turns a working function into a terminated one.
_LIMIT_NEAR_CEILING_RATIO = 0.9

#: Dimensions whose value space is large enough that varying a cache key on one stores far more
#: entries than it ever serves. **Invented**, and deliberately a short list of names rather than a
#: cardinality estimate, because no cardinality data exists here to estimate from. The identity
#: dimensions in :data:`_IDENTITY_DIMENSION_TOKENS` are refused rather than warned about, so they
#: never reach this list.
_HIGH_CARDINALITY_DIMENSIONS = (
    "cohort",
    "experiment",
    "postcode",
    "city",
    "referrer",
    "query",
)

#: Tokens that mark a dimension as an identity credential rather than an attribute. **Invented**,
#: and matched against the dimension name's word parts so ``sessionId`` and ``session_id`` are
#: caught alongside ``session``. Erring towards saying yes is deliberate: the cost of a false
#: positive is an operator renaming a dimension, and the cost of a false negative is a shared
#: cache entry keyed on a reader.
_IDENTITY_DIMENSION_TOKENS = frozenset(
    {
        "account",
        "apikey",
        "auth",
        "authorization",
        "bearer",
        "cookie",
        "credential",
        "email",
        "jwt",
        "session",
        "sessionid",
        "sid",
        "token",
        "uid",
        "user",
        "userid",
        "visitor",
        "visitorid",
    }
)

#: The longest a capability grant may run before it has to be renewed deliberately. **Invented**,
#: and the same ninety days the security surface uses for an exception, for the same reason: one
#: quarter is long enough to cover a vendor fix and short enough that every standing privilege is
#: re-justified within a review cycle.
_MAX_CAPABILITY_WINDOW_DAYS = 90

#: The methods an empty ``matcher_methods`` stands for, used only when comparing two functions'
#: method scopes. Kept as a literal so the comparison is decidable rather than open-ended.
_ALL_METHODS = ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT")


@dataclass(frozen=True)
class FunctionRefusal:
    """A named, explained refusal to change function policy."""

    reason: str
    sentence: str

    @staticmethod
    def of(reason: str) -> "FunctionRefusal":
        """Build a refusal from its reason code.

        Args:
            reason: One of :data:`FunctionRefusalReason`.

        Returns:
            The refusal with its operator-facing sentence attached.
        """
        return FunctionRefusal(
            reason=reason,
            sentence=_REFUSAL_SENTENCES.get(reason, "This function change cannot be applied."),
        )


@dataclass(frozen=True)
class FunctionWarning:
    """A named concern that does not block the write.

    Attributes:
        code: One of the keys of :data:`_WARNING_SENTENCES`.
        message: The operator-facing sentence.
        field: Which field the warning attaches to, so the UI can place it.
    """

    code: str
    message: str
    field: Optional[str] = None

    @staticmethod
    def of(code: str, field: Optional[str] = None) -> "FunctionWarning":
        """Build a warning from its code.

        Args:
            code: One of the keys of :data:`_WARNING_SENTENCES`.
            field: The field the warning is about, when there is one.

        Returns:
            The warning with its sentence attached.
        """
        return FunctionWarning(
            code=code,
            message=_WARNING_SENTENCES.get(code, "This function may not behave as intended."),
            field=field,
        )


class SlateFunctionRefusedError(Exception):
    """A function policy change was refused. Carries the named reason and its sentence.

    Raising rather than returning is deliberate, matching
    :class:`app.slate_security.SlateSecurityRefusedError`: a refused write must never be able to
    fall through to a persist because a caller forgot to inspect a return value.
    """

    def __init__(self, refusal: FunctionRefusal) -> None:
        self.refusal = refusal
        self.code = refusal.reason
        super().__init__(refusal.sentence)


# ─── Normalization ────────────────────────────────────────────────────────────


def normalize_function(function: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce a function mapping into the canonical shape evaluation and hashing assume.

    Missing fields take their V189 column default, and string lists are case-folded where the HTTP
    specification is case-insensitive. Doing this once, here, is what lets :func:`functions_digest`
    produce the same hash for two functions that differ only in spelling.

    Three fields are not columns in V189 and are read from the request body instead:
    ``simulated_at``, which records that this function has actually run in simulate;
    ``previous_rollout_percent``, which is what the rollout it is leaving was set to; and
    ``declared_destinations``, which is what the version manifest says the code will call. All
    three are facts the caller already holds — the store reconstructs the first two from
    ``slate_function_revisions`` and reads the third from the version body — and passing them in
    keeps this module free of a query.

    Args:
        function: A ``slate_functions`` row or request body.

    Returns:
        A new dict with every field present and canonically cased.
    """
    return {
        "id": str(function.get("id") or ""),
        "tenant_id": str(function.get("tenant_id") or ""),
        "environment_id": str(function.get("environment_id") or ""),
        "ordinal": int(function.get("ordinal") or 0),
        "enabled": bool(function.get("enabled", True)),
        "label": str(function.get("label") or ""),
        "matcher_kind": str(function.get("matcher_kind") or "prefix"),
        # An absent matcher defaults to "/", but an explicitly empty one is preserved so
        # _matcher_compiles can refuse it. Coercing "" to "/" here would silently turn a
        # half-filled form into a function that runs on every request the lane serves.
        "matcher_value": (
            "/" if function.get("matcher_value") is None else str(function.get("matcher_value"))
        ),
        # Empty means every method and every host, per V189.
        "matcher_methods": sorted(
            {str(m).upper() for m in (function.get("matcher_methods") or [])}
        ),
        "matcher_hosts": sorted({str(h).lower() for h in (function.get("matcher_hosts") or [])}),
        "runtime": str(function.get("runtime") or "js-isolate"),
        "active_version_id": (
            None if function.get("active_version_id") is None
            else str(function.get("active_version_id"))
        ),
        "rollout_mode": str(function.get("rollout_mode") or "simulate"),
        "rollout_percent": int(function.get("rollout_percent") or 0),
        "previous_rollout_percent": (
            None
            if function.get("previous_rollout_percent") is None
            else int(function["previous_rollout_percent"])
        ),
        # NULL means inherit, which is different from pinning today's lane value, so None is
        # preserved rather than resolved here. _effective_* does the resolution where a policy is
        # actually in hand.
        "region": function.get("region"),
        "residency_class": function.get("residency_class"),
        "cpu_ms_limit": (
            None if function.get("cpu_ms_limit") is None else int(function["cpu_ms_limit"])
        ),
        "memory_mb_limit": (
            None if function.get("memory_mb_limit") is None else int(function["memory_mb_limit"])
        ),
        "wall_ms_limit": (
            None if function.get("wall_ms_limit") is None else int(function["wall_ms_limit"])
        ),
        "env_var_names": sorted({str(n) for n in (function.get("env_var_names") or [])}),
        "declared_destinations": [
            str(d) for d in (function.get("declared_destinations") or [])
        ],
        "acknowledged_warnings": sorted(
            {str(w) for w in (function.get("acknowledged_warnings") or [])}
        ),
        "simulated_at": function.get("simulated_at"),
        "author_actor_key": str(function.get("author_actor_key") or ""),
        "approvals": list(function.get("approvals") or []),
    }


def normalize_policy(policy: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Coerce a function policy row into the canonical shape evaluation assumes.

    Args:
        policy: A ``slate_function_policies`` row, or ``None`` for a lane that has never been
            configured — which is treated as the shipped defaults rather than as an error, so a
            simulation against a fresh lane still renders.

    Returns:
        A new dict with every decisive policy field present.
    """
    source: Mapping[str, Any] = policy or {}
    return {
        "functions_enabled": bool(source.get("functions_enabled", False)),
        "policy_version": int(source.get("policy_version") or 0),
        # Never inferred and never defaulted true. There is one honest value this system can
        # write, and V189 CHECKs the consequences of the other one being false.
        "edge_attached": bool(source.get("edge_attached", False)),
        "edge_provider": source.get("edge_provider"),
        "default_region": str(source.get("default_region") or "auto"),
        "default_residency_class": str(
            source.get("default_residency_class") or "in-region-only"
        ),
        "default_cpu_ms_limit": int(source.get("default_cpu_ms_limit") or 50),
        "default_memory_mb_limit": int(source.get("default_memory_mb_limit") or 128),
        "default_wall_ms_limit": int(source.get("default_wall_ms_limit") or 5000),
        "residency_waiver_reason": source.get("residency_waiver_reason"),
    }


def normalize_variant(variant: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce a personalization variant into the canonical shape evaluation assumes.

    ``fallback_variant`` is left exactly as given, including an empty string, so
    :func:`evaluate_variant_safety` can refuse a missing fallback rather than inventing one — the
    same decision :func:`app.slate_security.normalize_exception` makes about a missing expiry.

    Args:
        variant: A ``slate_personalization_variants`` row or request body.

    Returns:
        A new dict with every field present.
    """
    analytics = str(variant.get("analytics_dimension") or "")
    return {
        "id": str(variant.get("id") or ""),
        "function_id": str(variant.get("function_id") or ""),
        "ordinal": int(variant.get("ordinal") or 0),
        "enabled": bool(variant.get("enabled", True)),
        "label": str(variant.get("label") or ""),
        "audience_kind": str(variant.get("audience_kind") or "geo"),
        "audience_matcher": list(variant.get("audience_matcher") or []),
        "fallback_variant": (
            "" if variant.get("fallback_variant") is None else str(variant["fallback_variant"])
        ),
        "cache_key_effect": str(variant.get("cache_key_effect") or "none"),
        # What the cache key actually varies on. V189 has no column for it because the effect and
        # the analytics dimension are usually the same string; where a caller distinguishes them,
        # the explicit value wins, and where it does not, the analytics dimension is the honest
        # stand-in for "what this variant branches on".
        "vary_dimension": str(variant.get("vary_dimension") or analytics),
        "analytics_dimension": analytics,
        "privacy_class": str(variant.get("privacy_class") or "non-personal"),
        "consent_basis": str(variant.get("consent_basis") or "not-required"),
    }


def normalize_capability(grant: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce a capability grant into the canonical shape evaluation assumes.

    Args:
        grant: A ``slate_function_capabilities`` row or request body.

    Returns:
        A new dict with every field present. ``expires_at`` is left as given, including ``None``,
        so :func:`evaluate_capability_safety` can refuse a missing expiry.
    """
    return {
        "id": str(grant.get("id") or ""),
        "function_id": str(grant.get("function_id") or ""),
        "capability": str(grant.get("capability") or ""),
        "reason": str(grant.get("reason") or ""),
        "expires_at": grant.get("expires_at"),
        "granted_at": grant.get("granted_at"),
        "granted_by_actor_key": str(grant.get("granted_by_actor_key") or ""),
    }


def normalize_egress_rule(rule: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce an egress allowlist entry into the canonical shape evaluation assumes.

    Args:
        rule: A ``slate_function_egress_rules`` row or request body.

    Returns:
        A new dict with every field present, host case-folded because DNS is case-insensitive.
    """
    return {
        "id": str(rule.get("id") or ""),
        "function_id": str(rule.get("function_id") or ""),
        "destination_kind": str(rule.get("destination_kind") or "exact-host"),
        "destination": str(rule.get("destination") or "").lower(),
        "scheme": str(rule.get("scheme") or "https").lower(),
        "port": None if rule.get("port") is None else int(rule["port"]),
        "methods": sorted({str(m).upper() for m in (rule.get("methods") or [])}),
        "reason": str(rule.get("reason") or ""),
        "expires_at": rule.get("expires_at"),
    }


def normalize_secret_ref(ref: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce a secret reference into the canonical shape evaluation assumes.

    There is nothing here able to hold a secret value, exactly as V189's table has no such column.
    The fields are a name, an alias, a scope and the boundary the reference belongs to.

    Args:
        ref: A ``slate_function_secret_refs`` row or request body.

    Returns:
        A new dict with every field present.
    """
    return {
        "id": str(ref.get("id") or ""),
        "function_id": str(ref.get("function_id") or ""),
        "secret_name": str(ref.get("secret_name") or ""),
        "alias": str(ref.get("alias") or ""),
        "scope": str(ref.get("scope") or "function"),
        # The boundary the *secret* belongs to, which is what makes a cross-project reference
        # detectable. Absent means "the same boundary as the function", which is the ordinary
        # case and the only one a caller that never crosses a boundary has to think about.
        "owner_tenant_id": str(ref.get("owner_tenant_id") or ""),
        "owner_environment_id": str(ref.get("owner_environment_id") or ""),
        "owner_function_id": str(ref.get("owner_function_id") or ""),
    }


# ─── Matching ─────────────────────────────────────────────────────────────────


def _matcher_compiles(function: Mapping[str, Any]) -> bool:
    """Whether a function's matcher can be evaluated at all.

    Args:
        function: A normalized function.

    Returns:
        False for an empty pattern, an unknown matcher kind, or a regex that does not compile. A
        matcher that cannot be evaluated is refused rather than treated as matching nothing: a
        function that silently never runs is worse than one that never existed, because somebody
        believes it is there.
    """
    value = function["matcher_value"]
    if not value:
        return False
    if function["matcher_kind"] not in MATCHER_KINDS:
        return False
    if function["matcher_kind"] == "regex":
        try:
            re.compile(value)
        except re.error:
            return False
    return True


def matches_route(function: Mapping[str, Any], request: "InvocationRequest") -> bool:
    """Whether a function's matcher selects this request.

    Prefix matching is textual rather than segment-aware, exactly as
    :func:`app.slate_cache.matches_route` and :func:`app.slate_security.matches_route` do it, so
    ``/docs`` also selects ``/docsearch``. An operator who means the section writes ``/docs/``.
    Keeping the three surfaces identical matters more than the alternative reading: a matcher that
    meant different things on the cache, security and function screens would eventually be copied
    from one to another.

    Args:
        function: A normalized function.
        request: A normalized request.

    Returns:
        True when method, host and path all match. A regex that does not compile matches nothing
        rather than raising: the write already refused it, and a simulation over stored policy
        should still render.
    """
    if function["matcher_methods"] and request.method not in function["matcher_methods"]:
        return False
    if function["matcher_hosts"] and request.host not in function["matcher_hosts"]:
        return False

    kind = function["matcher_kind"]
    value = function["matcher_value"]
    if kind == "exact":
        return request.path == value
    if kind == "prefix":
        return request.path.startswith(value)
    if kind == "glob":
        return fnmatch.fnmatchcase(request.path, value)
    if kind == "regex":
        try:
            return re.search(value, request.path) is not None
        except re.error:
            return False
    return False


def covers_everything(function: Mapping[str, Any]) -> bool:
    """Whether a matcher selects every route on the lane.

    Host scoping does not narrow this: a function limited to one host still runs on every route of
    that host, and a single-host lane is the ordinary case.

    Args:
        function: A normalized function.

    Returns:
        True when no request path could avoid the matcher. Always False for ``exact``, which
        selects exactly one path by construction.
    """
    kind = function["matcher_kind"]
    value = function["matcher_value"].strip()

    if kind == "exact":
        return False
    if kind == "prefix":
        # Every path begins with "/", so a "/" prefix is total, and an empty prefix matches by
        # str.startswith("") on anything at all.
        return value in ("", "/")
    if kind == "glob":
        return value in ("*", "**", "/*", "/**", "/*/**", "*/**")
    if kind == "regex":
        if not value:
            return True
        # re.search is unanchored, so a pattern that matches the empty string matches every path.
        try:
            compiled = re.compile(value)
        except re.error:
            return False
        return compiled.search("") is not None or compiled.search("/") is not None
    return False


def _path_segments(matcher_value: str) -> int:
    """How many path segments a matcher pins down.

    Args:
        matcher_value: The function's route pattern.

    Returns:
        The count of non-empty, non-wildcard leading segments. A pattern pinning few segments
        covers much of the lane, which is what :data:`_BROAD_MATCHER_MAX_SEGMENTS` compares
        against.
    """
    segments = 0
    for segment in matcher_value.split("/"):
        # Empty segments are the leading slash and any trailing one, which pin nothing down and
        # must not end the count — "/guide/" pins one segment, not zero.
        if not segment:
            continue
        if "*" in segment or segment.startswith("("):
            break
        segments += 1
    return segments


def _covers(outer: Mapping[str, Any], inner: Mapping[str, Any]) -> bool:
    """Whether ``outer`` matches everything ``inner`` does, for the shadowing warning.

    The conservative matcher-coverage helper from :mod:`app.slate_cache`, unchanged in spirit:
    only the cases that can be decided cheaply and certainly are reported. A prefix strictly
    containing another prefix is one; comparing two regexes is not, and guessing would produce a
    warning an operator cannot act on.

    Args:
        outer: The higher-precedence function.
        inner: The function that may be unreachable.

    Returns:
        True only when coverage is certain.
    """
    if outer["matcher_kind"] != "prefix":
        return False
    if inner["matcher_kind"] not in {"prefix", "exact"}:
        return False
    if outer["matcher_hosts"] and outer["matcher_hosts"] != inner["matcher_hosts"]:
        return False
    # Empty outer methods means every method, which subsumes any inner set.
    if outer["matcher_methods"] and not set(
        inner["matcher_methods"] or list(_ALL_METHODS)
    ).issubset(set(outer["matcher_methods"])):
        return False
    return inner["matcher_value"].startswith(outer["matcher_value"])


# ─── Effective settings ───────────────────────────────────────────────────────


def _effective_residency(
    function: Mapping[str, Any], policy: Mapping[str, Any]
) -> str:
    """The residency class a function actually runs under.

    Args:
        function: A normalized function.
        policy: A normalized policy.

    Returns:
        The function's own class when it pinned one, otherwise the lane default. NULL means
        inherit, which is why this is resolved here rather than in :func:`normalize_function`.
    """
    return str(function["residency_class"] or policy["default_residency_class"])


def _effective_region(function: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    """The region a function actually runs in.

    Args:
        function: A normalized function.
        policy: A normalized policy.

    Returns:
        The function's own region when it pinned one, otherwise the lane default.
    """
    return str(function["region"] or policy["default_region"])


def _effective_limits(
    function: Mapping[str, Any], policy: Mapping[str, Any]
) -> Dict[str, int]:
    """The CPU, memory and wall-clock limits a function actually runs under.

    Args:
        function: A normalized function.
        policy: A normalized policy.

    Returns:
        A dict of the three limits, each the function's own override or the lane default.
    """
    return {
        "cpu_ms": int(function["cpu_ms_limit"] or policy["default_cpu_ms_limit"]),
        "memory_mb": int(function["memory_mb_limit"] or policy["default_memory_mb_limit"]),
        "wall_ms": int(function["wall_ms_limit"] or policy["default_wall_ms_limit"]),
    }


# ─── Safety evaluation ────────────────────────────────────────────────────────


def evaluate_function_safety(
    function: Mapping[str, Any],
    *,
    siblings: Sequence[Mapping[str, Any]] = (),
    policy: Optional[Mapping[str, Any]] = None,
    secret_refs: Sequence[Mapping[str, Any]] = (),
    egress_rules: Sequence[Mapping[str, Any]] = (),
    now: datetime,
) -> List[FunctionWarning]:
    """Check a function for the conditions §29.5 makes flat prohibitions, and for the costs.

    This is the authority behind all four acceptance criteria as they apply to a function body.
    The UI renders what this returns and what :class:`SlateFunctionRefusedError` carries; it does
    not classify functions itself, because two copies of this policy would eventually disagree and
    the one that disagreed silently would be the one governing production.

    Deliberately split from the capability, egress, variant and policy evaluators so an unrelated
    edit is not refused for a problem it did not cause: an operator narrowing a matcher during an
    incident must not be blocked by an expiring capability somebody else granted an hour ago.

    Args:
        function: The function to check, normalized or raw.
        siblings: Other functions on the lane. Used for the precedence refusal and the shadowing
            warning; a function sharing this one's id is skipped, so re-checking a stored function
            against its own lane does not report it as conflicting with itself.
        policy: The lane's policy row, when there is one. Only the ceilings and the residency
            default are consulted.
        secret_refs: The secret references declared on this function, checked for the boundary
            crossing §29.5 forbids.
        egress_rules: This function's egress allowlist, checked against the destinations the
            version manifest declares.
        now: Evaluation time, injected rather than read, so the same function judged against the
            same instant always produces the same verdict.

    Returns:
        Warnings that do not block the write. Acknowledged warnings are still returned; the caller
        decides whether an acknowledgement is on file.

    Raises:
        SlateFunctionRefusedError: On any condition in :data:`_HARD_REFUSALS` reachable from a
            function body.
    """
    normalized = normalize_function(function)
    resolved_policy = normalize_policy(policy)

    # A matcher that cannot be evaluated comes first: every check below reasons about what the
    # function covers, and reasoning about a pattern that will never compile is meaningless.
    if not _matcher_compiles(normalized):
        raise SlateFunctionRefusedError(FunctionRefusal.of("matcher-invalid"))

    # Precedence next, because it is decidable from the lane alone and because a colliding
    # ordinal makes every simulation of this lane unreproducible — including the ones the checks
    # below would tell the operator to run.
    for sibling in siblings:
        other = normalize_function(sibling)
        if other["id"] and other["id"] == normalized["id"]:
            continue
        if other["ordinal"] == normalized["ordinal"]:
            raise SlateFunctionRefusedError(FunctionRefusal.of("ordinal-conflict"))

    # §29.5's flat prohibitions, before anything about rollout. These are properties of the
    # function as written, so they are refused whether or not it will ever enforce: a function
    # that references another project's secret is already wrong in simulate.
    _refuse_cross_boundary_secrets(normalized, secret_refs)
    _refuse_unapproved_egress(normalized, egress_rules, now=now)

    # Limits and residency, which are comparisons against the lane rather than against the
    # roadmap. A function may tighten either and cannot loosen either.
    limits = _effective_limits(normalized, resolved_policy)
    if (
        limits["cpu_ms"] > resolved_policy["default_cpu_ms_limit"]
        or limits["memory_mb"] > resolved_policy["default_memory_mb_limit"]
        or limits["wall_ms"] > resolved_policy["default_wall_ms_limit"]
    ):
        raise SlateFunctionRefusedError(FunctionRefusal.of("limit-exceeds-ceiling"))

    own = normalized["residency_class"]
    if own is not None and str(own) in RESIDENCY_CLASSES:
        lane = resolved_policy["default_residency_class"]
        if lane in RESIDENCY_CLASSES and RESIDENCY_CLASSES.index(str(own)) > (
            RESIDENCY_CLASSES.index(lane)
        ):
            raise SlateFunctionRefusedError(FunctionRefusal.of("residency-violation"))

    # Staged rollout is only a guarantee if the stages cannot be skipped. All three of these
    # apply to the enforcing function and not to the simulate-mode one, which is the point:
    # simulate is the cheap, always-available step and reaching enforce is the deliberate one.
    enforcing = normalized["rollout_mode"] == "enforce" and normalized["rollout_percent"] > 0
    if enforcing:
        if normalized["active_version_id"] is None:
            raise SlateFunctionRefusedError(FunctionRefusal.of("enforce-without-version"))
        if normalized["simulated_at"] is None:
            raise SlateFunctionRefusedError(FunctionRefusal.of("enforce-without-simulation"))
        evaluate_approval_safety(
            author_actor_key=normalized["author_actor_key"],
            approvals=normalized["approvals"],
            digest=body_digest(normalized),
        )

    warnings: List[FunctionWarning] = []
    if _path_segments(normalized["matcher_value"]) <= _BROAD_MATCHER_MAX_SEGMENTS:
        warnings.append(FunctionWarning.of("broad-matcher", field="matcher_value"))
    if normalized["rollout_percent"] == 100 and normalized["previous_rollout_percent"] == 0:
        warnings.append(FunctionWarning.of("rollout-jump", field="rollout_percent"))
    if _near_ceiling(limits, resolved_policy):
        warnings.append(FunctionWarning.of("limit-near-ceiling", field="cpu_ms_limit"))

    for sibling in siblings:
        other = normalize_function(sibling)
        if other["id"] and other["id"] == normalized["id"]:
            continue
        if not other["enabled"]:
            continue
        if other["ordinal"] < normalized["ordinal"] and _covers(other, normalized):
            warnings.append(FunctionWarning.of("function-shadowed", field="ordinal"))
            break

    return warnings


def _refuse_cross_boundary_secrets(
    function: Mapping[str, Any], secret_refs: Sequence[Mapping[str, Any]]
) -> None:
    """Refuse any secret reference that reaches outside this function's own boundary.

    §29.5's first flat prohibition. V189 makes reading a secret *value* a schema impossibility;
    this is the other half, which a schema cannot express because the boundary a reference crosses
    is only visible by comparing two rows.

    Args:
        function: A normalized function.
        secret_refs: The references declared on it.

    Returns:
        None. Communicates only by raising, so a caller cannot mistake a falsy return for safety.

    Raises:
        SlateFunctionRefusedError: ``secret-cross-project`` when a reference names another
            tenant, another environment, or — for a ``function``-scoped reference — another
            function. An absent owner field means "the same boundary as the function", which is
            the ordinary case; a *present* one that differs is the crossing.
    """
    for raw in secret_refs:
        ref = normalize_secret_ref(raw)
        if ref["owner_tenant_id"] and function["tenant_id"]:
            if ref["owner_tenant_id"] != function["tenant_id"]:
                raise SlateFunctionRefusedError(FunctionRefusal.of("secret-cross-project"))
        if ref["owner_environment_id"] and function["environment_id"]:
            if ref["owner_environment_id"] != function["environment_id"]:
                raise SlateFunctionRefusedError(FunctionRefusal.of("secret-cross-project"))
        # A function-scoped reference belongs to exactly one function. An environment-scoped one
        # deliberately does not, which is why the scope is checked rather than assumed.
        if ref["scope"] == "function" and ref["owner_function_id"] and function["id"]:
            if ref["owner_function_id"] != function["id"]:
                raise SlateFunctionRefusedError(FunctionRefusal.of("secret-cross-project"))


def _refuse_unapproved_egress(
    function: Mapping[str, Any],
    egress_rules: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
) -> None:
    """Refuse a function that declares a call to a destination with no allowlist entry.

    The distinction from the simulation's ``egress-denied`` outcome matters. A function that
    declares nothing and holds no allowlist entry is configured perfectly legally and simply
    cannot reach the network — that is deny-by-default working. A function whose own manifest says
    it will call a host nobody allowed is a function that is going to fail in production, and the
    write is where that is cheapest to find out.

    Args:
        function: A normalized function, whose ``declared_destinations`` come from the version
            manifest.
        egress_rules: This function's allowlist entries.
        now: Evaluation time, so an expired entry does not silently approve a destination.

    Returns:
        None.

    Raises:
        SlateFunctionRefusedError: ``egress-unapproved`` for the first destination not covered.
    """
    if not function["declared_destinations"]:
        return
    live = [
        normalize_egress_rule(rule)
        for rule in egress_rules
        if not _expired(normalize_egress_rule(rule)["expires_at"], now)
    ]
    for destination in function["declared_destinations"]:
        if _egress_rule_for(destination, live) is None:
            raise SlateFunctionRefusedError(FunctionRefusal.of("egress-unapproved"))


def _egress_rule_for(
    destination: str, rules: Sequence[Mapping[str, Any]]
) -> Optional[Mapping[str, Any]]:
    """The allowlist entry covering a destination, if any.

    Args:
        destination: A host, optionally with a scheme, as the function declared it.
        rules: Already-normalized, already-live allowlist entries.

    Returns:
        The covering entry, or ``None``. An ``exact-host`` entry covers only its own host; a
        ``host-suffix`` entry covers the host itself and anything under it, and requires a dot
        before the suffix so ``evilexample.com`` is not covered by ``example.com``.
    """
    host = destination.lower()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split(":", 1)[0]

    for rule in rules:
        target = rule["destination"]
        if not target:
            continue
        if rule["destination_kind"] == "exact-host" and host == target:
            return rule
        if rule["destination_kind"] == "host-suffix" and (
            host == target or host.endswith("." + target)
        ):
            return rule
    return None


def _near_ceiling(limits: Mapping[str, int], policy: Mapping[str, Any]) -> bool:
    """Whether any of a function's limits sits close enough to the lane ceiling to warn about.

    Args:
        limits: The resolved limits from :func:`_effective_limits`.
        policy: A normalized policy.

    Returns:
        True when any limit is at or above :data:`_LIMIT_NEAR_CEILING_RATIO` of its ceiling and
        below the ceiling itself. A limit *at* the ceiling is the inherited default, which is the
        ordinary case rather than a risk, so it does not warn.
    """
    pairs = (
        (limits["cpu_ms"], policy["default_cpu_ms_limit"]),
        (limits["memory_mb"], policy["default_memory_mb_limit"]),
        (limits["wall_ms"], policy["default_wall_ms_limit"]),
    )
    for value, ceiling in pairs:
        if ceiling <= 0:
            continue
        if value < ceiling and value >= ceiling * _LIMIT_NEAR_CEILING_RATIO:
            return True
    return False


def evaluate_capability_safety(
    grant: Mapping[str, Any], *, now: datetime
) -> List[FunctionWarning]:
    """Check a capability grant for the two ways a grant stops being reviewable.

    Kept separate from :func:`evaluate_function_safety` so an unrelated function edit is not
    refused because of a grant it did not make. §29.5 requires capabilities to be deny-by-default,
    and V189 achieves that by making a row a grant; what a schema cannot check is whether the
    grant says why it exists and when it ends, which is what this does.

    Args:
        grant: The grant to check, normalized or raw.
        now: Evaluation time, injected so the same grant judged against the same instant always
            produces the same verdict.

    Returns:
        Warnings that do not block the write. Empty today; the return type is stated so a future
        grant-level concern has somewhere to go that is not a refusal.

    Raises:
        SlateFunctionRefusedError: ``capability-without-reason`` for a blank reason, and
            ``capability-unbounded`` when a capability whose catalog entry sets
            ``requires_expiry`` has no expiry or one beyond
            :data:`_MAX_CAPABILITY_WINDOW_DAYS`.
    """
    normalized = normalize_capability(grant)

    # Reason first: it is the field a reviewer reads before anything else, and a grant that
    # cannot say why it exists does not deserve a second sentence about its expiry.
    if not normalized["reason"].strip():
        raise SlateFunctionRefusedError(FunctionRefusal.of("capability-without-reason"))

    definition = CAPABILITY_CATALOG.get(normalized["capability"])
    if definition is not None and definition.requires_expiry:
        expires_at = _as_datetime(normalized["expires_at"], now)
        if expires_at is None:
            raise SlateFunctionRefusedError(FunctionRefusal.of("capability-unbounded"))
        if expires_at > now + timedelta(days=_MAX_CAPABILITY_WINDOW_DAYS):
            raise SlateFunctionRefusedError(FunctionRefusal.of("capability-unbounded"))

    return []


def evaluate_egress_safety(
    rule: Mapping[str, Any],
    *,
    destinations: Sequence[str] = (),
    now: datetime,
) -> List[FunctionWarning]:
    """Check an egress allowlist entry, and optionally the destinations it is meant to cover.

    An allowlist entry is a grant in the same shape as a capability, so it carries the same
    grant-hygiene refusal: V189 makes ``reason`` NOT NULL for both tables for the same reason, and
    an unexplained hole in an allowlist is the one nobody can justify at review.

    ``capability-unbounded`` deliberately does *not* apply here. A permanent capability to read
    secrets is a standing privilege; a permanent allowance to reach an API the lane genuinely
    depends on is just the configuration, and forcing it to lapse would produce quarterly outages
    with no security gained.

    Args:
        rule: The allowlist entry to check, normalized or raw.
        destinations: Destinations the function declares it will call, checked against this entry
            when given. Passing them here is what lets a caller validate a rule and its intended
            use in one step.
        now: Evaluation time, so an expired entry cannot approve anything.

    Returns:
        Warnings that do not block the write. Empty today; the return type is stated so a future
        egress-level concern has somewhere to go that is not a refusal.

    Raises:
        SlateFunctionRefusedError: ``capability-without-reason`` for a blank reason, and
            ``egress-unapproved`` when a named destination is not covered by this entry.
    """
    normalized = normalize_egress_rule(rule)

    # Reason first, for the same ordering reason capabilities use.
    if not normalized["reason"].strip():
        raise SlateFunctionRefusedError(FunctionRefusal.of("capability-without-reason"))

    live = [] if _expired(normalized["expires_at"], now) else [normalized]
    for destination in destinations:
        if _egress_rule_for(destination, live) is None:
            raise SlateFunctionRefusedError(FunctionRefusal.of("egress-unapproved"))

    return []


def evaluate_variant_safety(
    variant: Mapping[str, Any],
    *,
    function: Optional[Mapping[str, Any]] = None,
    policy: Optional[Mapping[str, Any]] = None,
) -> List[FunctionWarning]:
    """Check a personalization variant for the ways personalization becomes unsafe.

    §29.5 requires audience rule, fallback, cache-key effect, analytics dimension and privacy
    classification to be shown together, and V189 stores them in one row so they cannot drift.
    This is the third half of that: the combinations that are contradictions rather than
    configurations are refused here, so the drift is impossible rather than merely visible.

    Args:
        variant: The variant to check, normalized or raw.
        function: The function that selects between variants, when known. Only its residency
            override is consulted, so a variant edit is not refused for something about the
            function's matcher.
        policy: The lane's policy row, for the residency default.

    Returns:
        Warnings that do not block the write.

    Raises:
        SlateFunctionRefusedError: ``variant-without-fallback``, ``variant-identity-cache-key``,
            ``variant-personal-without-basis`` or ``residency-violation``.
    """
    normalized = normalize_variant(variant)
    resolved_policy = normalize_policy(policy)

    # The fallback first: it is what every reader the audience rule does not match receives, so a
    # variant missing one is an outage for the majority whatever else is true about it.
    if not normalized["fallback_variant"].strip():
        raise SlateFunctionRefusedError(FunctionRefusal.of("variant-without-fallback"))

    # Then the cache defect, because it is the one that serves one reader's page to another and
    # the one §29.3 already refuses on the cache surface.
    if normalized["cache_key_effect"] == "vary-on-dimension" and _is_identity_dimension(
        normalized["vary_dimension"]
    ):
        raise SlateFunctionRefusedError(FunctionRefusal.of("variant-identity-cache-key"))

    # Then the two declarations that contradict each other. V189 CHECKs both; this is the
    # sentence rather than the enforcement, because an operator should meet the explanation and
    # not a constraint violation.
    if (
        normalized["privacy_class"] == "personal"
        and normalized["consent_basis"] == "not-required"
    ):
        raise SlateFunctionRefusedError(
            FunctionRefusal.of("variant-personal-without-basis")
        )
    if normalized["privacy_class"] != "non-personal" and (
        normalized["cache_key_effect"] == "none"
    ):
        raise SlateFunctionRefusedError(FunctionRefusal.of("variant-identity-cache-key"))

    # Residency last, because it is the only check that needs anything outside the variant row.
    residency = (
        _effective_residency(normalize_function(function), resolved_policy)
        if function is not None
        else resolved_policy["default_residency_class"]
    )
    posture = RESIDENCY_CLASS_CATALOG.get(residency)
    if (
        normalized["privacy_class"] == "personal"
        and posture is not None
        and not posture.permits_personal
    ):
        raise SlateFunctionRefusedError(FunctionRefusal.of("residency-violation"))

    warnings: List[FunctionWarning] = []
    if normalized["cache_key_effect"] == "vary-on-dimension" and _is_high_cardinality(
        normalized["vary_dimension"], normalized["audience_kind"]
    ):
        warnings.append(FunctionWarning.of("cache-fragmenting", field="cache_key_effect"))
    if not normalized["analytics_dimension"].strip():
        warnings.append(
            FunctionWarning.of("variant-without-analytics", field="analytics_dimension")
        )
    return warnings


def _dimension_tokens(dimension: str) -> Tuple[str, ...]:
    """Split a dimension name into comparable word parts.

    Args:
        dimension: The dimension name as an operator wrote it, in any casing or separator style.

    Returns:
        Lower-cased tokens, with camelCase split, so ``sessionId``, ``session_id`` and
        ``Session ID`` all reduce to the same parts.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", dimension)
    return tuple(part for part in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if part)


def _is_identity_dimension(dimension: str) -> bool:
    """Whether a dimension names an identity credential rather than an attribute.

    Args:
        dimension: The dimension the cache key would vary on.

    Returns:
        True when any word part is in :data:`_IDENTITY_DIMENSION_TOKENS`, or when the whole name
        joined without separators is. Erring towards yes is deliberate; see that constant.
    """
    tokens = _dimension_tokens(dimension)
    if any(token in _IDENTITY_DIMENSION_TOKENS for token in tokens):
        return True
    return "".join(tokens) in _IDENTITY_DIMENSION_TOKENS


def _is_high_cardinality(dimension: str, audience_kind: str) -> bool:
    """Whether varying a cache key on this dimension stores far more than it serves.

    Args:
        dimension: The dimension the cache key would vary on.
        audience_kind: What the audience is decided on, which is a second signal for the same
            question: a cohort or an experiment has many values whatever the dimension is called.

    Returns:
        True when either signal names a high-cardinality space.
    """
    if audience_kind in ("cohort", "experiment"):
        return True
    tokens = _dimension_tokens(dimension)
    return any(token in _HIGH_CARDINALITY_DIMENSIONS for token in tokens)


def evaluate_policy_safety(policy: Mapping[str, Any]) -> List[FunctionWarning]:
    """Check a lane policy for a residency change that removes a promise without accounting for it.

    Kept separate from :func:`evaluate_function_safety` deliberately, for the reason
    :func:`app.slate_security.evaluate_policy_safety` states: a policy-level problem must not
    refuse an unrelated function edit.

    Args:
        policy: A ``slate_function_policies`` row or request body.

    Returns:
        Warnings that do not block the write. Empty today; the return type is stated so a future
        policy-level concern has somewhere to go that is not a refusal.

    Raises:
        SlateFunctionRefusedError: ``residency-violation`` when residency is loosened to
            ``unrestricted`` with no stated waiver reason. V189 CHECKs the same thing, so this is
            the sentence rather than the enforcement.
    """
    resolved = normalize_policy(policy)
    posture = RESIDENCY_CLASS_CATALOG.get(resolved["default_residency_class"])
    if posture is not None and posture.requires_waiver_reason:
        if not str(resolved["residency_waiver_reason"] or "").strip():
            raise SlateFunctionRefusedError(FunctionRefusal.of("residency-violation"))
    return []


def evaluate_approval_safety(
    *,
    author_actor_key: str,
    approvals: Sequence[Mapping[str, Any]],
    digest: str,
) -> None:
    """Check that a change carries a genuine second-person approval of this exact body.

    Three failures are distinguished on purpose, because they need different actions. No approval
    at all means nobody has looked; an approval by the author means nobody *else* has; and an
    approval of a different body means the change was re-edited after review and has to go back.

    Args:
        author_actor_key: Immutable identity of whoever proposed the change. V189 compares these
            keys rather than the nullable user ids, because those are ``ON DELETE SET NULL`` and a
            constraint that weakens when somebody is offboarded is not a constraint.
        approvals: Recorded approvals, each carrying ``approver_actor_key`` and ``digest``.
        digest: The body digest actually being written, from :func:`body_digest`.

    Returns:
        None. This function communicates only by raising, so a caller cannot mistake a falsy
        return for approval.

    Raises:
        SlateFunctionRefusedError: ``enforce-without-approval``, ``approval-self`` or
            ``approval-stale``.
    """
    if not approvals:
        raise SlateFunctionRefusedError(FunctionRefusal.of("enforce-without-approval"))

    distinct = [
        approval
        for approval in approvals
        if str(approval.get("approver_actor_key") or "") != author_actor_key
    ]
    if not distinct:
        raise SlateFunctionRefusedError(FunctionRefusal.of("approval-self"))

    if not any(str(approval.get("digest") or "") == digest for approval in distinct):
        raise SlateFunctionRefusedError(FunctionRefusal.of("approval-stale"))


# ─── Simulation ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InvocationRequest:
    """The test request a simulation is evaluated against.

    The declared fields are what make a function simulation deterministic without a runtime. There
    is nothing in the request path to execute code, so this module cannot discover for itself
    which capabilities a handler reaches for or which hosts it calls. Instead the caller states
    what the version manifest declares, and the simulation answers what the *policy* does about
    it. That is a smaller claim than "this is what the function did", and it is the one that is
    actually true.

    Attributes:
        method: HTTP method, upper-cased by :meth:`normalized`.
        host: Request host, lower-cased.
        path: Request path.
        country: Resolved country, for a ``geo`` audience predicate.
        language: Resolved language, for a ``language`` predicate.
        device: Resolved device class, for a ``device`` predicate.
        cohort: Cohort assignment, for a ``cohort`` predicate.
        experiment: Experiment assignment, for an ``experiment`` predicate.
        requested_capabilities: Capabilities the function's code would use on this request.
        requested_destinations: Hosts the function's code would call on this request.
        estimated_cpu_ms: CPU the handler is expected to consume, for the limit check. Zero means
            the question does not arise.
        estimated_wall_ms: Wall-clock the handler is expected to hold the request for.
        estimated_memory_mb: Peak memory the handler is expected to reach.
        headers: Request headers, lower-cased by :meth:`normalized`.
    """

    method: str = "GET"
    host: str = ""
    path: str = "/"
    country: str = ""
    language: str = ""
    device: str = ""
    cohort: str = ""
    experiment: str = ""
    requested_capabilities: Tuple[str, ...] = ()
    requested_destinations: Tuple[str, ...] = ()
    estimated_cpu_ms: int = 0
    estimated_wall_ms: int = 0
    estimated_memory_mb: int = 0
    headers: Mapping[str, str] = field(default_factory=dict)

    def normalized(self) -> "InvocationRequest":
        """Return a copy with case normalized the way HTTP and DNS define it.

        Returns:
            A new :class:`InvocationRequest`; the original is untouched.
        """
        return InvocationRequest(
            method=self.method.upper(),
            host=self.host.lower(),
            path=self.path or "/",
            country=self.country.upper(),
            language=self.language.lower(),
            device=self.device.lower(),
            cohort=str(self.cohort or ""),
            experiment=str(self.experiment or ""),
            requested_capabilities=tuple(
                sorted({str(c) for c in self.requested_capabilities})
            ),
            requested_destinations=tuple(
                sorted({str(d).lower() for d in self.requested_destinations})
            ),
            estimated_cpu_ms=int(self.estimated_cpu_ms or 0),
            estimated_wall_ms=int(self.estimated_wall_ms or 0),
            estimated_memory_mb=int(self.estimated_memory_mb or 0),
            headers={k.lower(): v for k, v in self.headers.items()},
        )


@dataclass(frozen=True)
class InvocationVerdict:
    """What a lane's function policy decides for one request, and why everything else did not.

    One field per clause of the §29.5 acceptance criteria, so a partially-answered simulation is a
    type error rather than a subtle omission.

    ``executed``, ``observed`` and ``enforced`` are the honesty boundary in structural form.
    :func:`simulate_invocation` sets all three to ``False`` unconditionally and there is no
    argument by which a caller can change them, mirroring the way V189's CHECKs make the
    corresponding columns impossible to overstate. ``basis`` is ``policy-simulation`` for the same
    reason.

    Attributes:
        outcome: What the policy concluded, one of :data:`INVOCATION_OUTCOMES`. Never ``ran``.
        outcome_reason: One sentence naming both the outcome and what produced it.
        function_ref: Id of the function that won, or ``None`` when none did.
        function_label: Operator-facing name of the winning function.
        version_ref: The active version that would have run, or ``None``.
        runtime: The runtime the winning function declares, or ``""``.
        rollout_mode: The winning function's rollout mode, or ``""``.
        rollout_percent: The winning function's rollout percentage.
        region: The region the function would have run in, resolved from the lane default.
        residency_class: The residency class it would have run under.
        limits: The CPU, memory and wall-clock ceilings it would have run within.
        variant_ref: The personalization variant selected, or ``None`` when none matched.
        variant_label: Operator-facing name of the selected variant.
        fallback_variant: What every reader the audience rule does not match receives. Present
            whether or not a variant matched, because it is the answer to "and everybody else?"
        cache_key_effect: The resolved effect on the shared cache key, one of
            :data:`CACHE_KEY_EFFECTS`.
        privacy_class: The privacy classification of the selected variant.
        consent_basis: The consent basis of the selected variant.
        analytics_dimension: The dimension the selected variant reports under.
        capabilities_granted: Capabilities the request asked for and holds a live grant for.
        capabilities_denied: Capabilities the request asked for and does not hold. Deny-by-default
            surfaces here rather than as a refusal: the function is configured legally and simply
            cannot do the thing.
        egress_allowed: Destinations the request would call that an allowlist entry covers.
        egress_denied: Destinations it would call that none covers.
        denial_reason: Why a denial happened, or ``None``. Quoted into
            ``slate_function_invocations.denial_reason`` verbatim so the UI does not restate it.
        considered: Every function and variant evaluated, in order, each with an outcome from
            :data:`INVOCATION_OUTCOMES` and a sentence explaining why it won or lost.
        warnings: Concerns about the winning function and variant, as dicts the REST layer
            serializes directly.
        executed: Always ``False``. Nothing ran, because there is nothing to run it in.
        observed: Always ``False``. This is a simulation of policy, not a request that happened.
        enforced: Always ``False``. No runtime tier is attached.
        basis: Always ``policy-simulation``, matching ``slate_function_invocations.source``.
        functions_digest: The digest of the function set that produced this verdict, so a
            simulation can be reproduced from its recorded inputs or explained by having drifted
            from them.
    """

    outcome: str
    outcome_reason: str
    function_ref: Optional[str]
    function_label: str
    version_ref: Optional[str]
    runtime: str
    rollout_mode: str
    rollout_percent: int
    region: str
    residency_class: str
    limits: Dict[str, int]
    variant_ref: Optional[str]
    variant_label: str
    fallback_variant: str
    cache_key_effect: str
    privacy_class: str
    consent_basis: str
    analytics_dimension: str
    capabilities_granted: List[str]
    capabilities_denied: List[str]
    egress_allowed: List[str]
    egress_denied: List[str]
    denial_reason: Optional[str]
    considered: List[Dict[str, Any]]
    warnings: List[Dict[str, str]]
    executed: bool
    observed: bool
    enforced: bool
    basis: str
    functions_digest: str


def simulate_invocation(
    *,
    request: InvocationRequest,
    policy: Optional[Mapping[str, Any]],
    functions: Sequence[Mapping[str, Any]] = (),
    variants: Sequence[Mapping[str, Any]] = (),
    capabilities: Sequence[Mapping[str, Any]] = (),
    egress_rules: Sequence[Mapping[str, Any]] = (),
    now: datetime,
) -> InvocationVerdict:
    """Explain what this lane would do with this request, and why each function did not do it.

    No I/O, no clock and no randomness: ``now`` is a mandatory keyword parameter the way
    :func:`app.slate_cache.evaluate_trace` takes it, so a recorded simulation can be re-checked
    later rather than merely believed. **Every** function and every variant is reported — one that
    lost says why, because "why did my function not run", or worse "which function personalized
    this page", is the question a simulation exists to answer.

    Evaluation order is functions by ``(ordinal, id)`` — V189's ``UNIQUE (environment_id,
    ordinal)`` forbids ties, so this is a total order and the answer is reproducible — then the
    winning function's variants by ``(ordinal, id)``.

    Rollout is applied deterministically rather than sampled. A function at 0% reaches no traffic
    and is reported as skipped; a function above 0% is evaluated as though this request falls
    inside its cohort, and the sentence says so. Sampling here would make the same inputs produce
    different answers, which is exactly what a simulation must not do.

    A capability or egress denial is an *outcome*, not a refusal. The function is configured
    legally; it simply cannot do the thing at runtime, and hiding that behind a write-time error
    would mean the operator learned about it from a production incident instead.

    Args:
        request: The test request.
        policy: The lane's policy row, or ``None`` for shipped defaults.
        functions: The lane's functions, in any order; they are sorted here.
        variants: Personalization variants for any function on the lane; only the winning
            function's are selected between, and the rest are not reported, because a variant of a
            function that did not run explains nothing about this request.
        capabilities: Capability grants across the lane, filtered here to the winning function's
            and to the ones that have not lapsed.
        egress_rules: Egress allowlist entries across the lane, filtered the same way.
        now: Evaluation time, for grant and allowance expiry.

    Returns:
        The verdict: what the lane concluded, what concluded it, and one sentence for every
        function and variant that did not.
    """
    normalized_request = request.normalized()
    resolved_policy = normalize_policy(policy)

    considered: List[Dict[str, Any]] = []
    winner = _consider_functions(
        functions=functions,
        request=normalized_request,
        policy=resolved_policy,
        considered=considered,
    )

    if winner is None:
        return _no_function_verdict(functions, considered)

    limits = _effective_limits(winner, resolved_policy)

    # Capability, then egress, then limits. The order is the order in which a real runtime would
    # stop: a handler denied a capability never reaches its fetch, and one denied its fetch never
    # reaches the CPU ceiling. Reporting them in any other order would name a symptom rather than
    # the cause.
    granted, denied = _resolve_capabilities(
        winner, capabilities, normalized_request, now=now
    )
    allowed, refused = _resolve_egress(winner, egress_rules, normalized_request, now=now)
    exceeded = _exceeded_limit(limits, normalized_request)

    variant, fallback = _consider_variants(
        variants=variants,
        function=winner,
        request=normalized_request,
        considered=considered,
    )

    outcome, denial_reason = _resolve_outcome(
        winner=winner,
        denied_capabilities=denied,
        denied_egress=refused,
        exceeded=exceeded,
    )

    # The winning function's own considered entry carries the final outcome rather than the
    # provisional "would-run" it was given while matching, so the list and the verdict cannot
    # disagree about what happened to the function that won.
    _restate_winner(considered, winner, outcome, denial_reason)

    warnings = _simulation_warnings(
        winner=winner,
        functions=functions,
        variant=variant,
        policy=policy,
    )

    return InvocationVerdict(
        outcome=outcome,
        outcome_reason=denial_reason or _would_run_sentence(winner, normalized_request),
        function_ref=winner["id"] or None,
        function_label=winner["label"],
        version_ref=winner["active_version_id"],
        runtime=winner["runtime"],
        rollout_mode=winner["rollout_mode"],
        rollout_percent=winner["rollout_percent"],
        region=_effective_region(winner, resolved_policy),
        residency_class=_effective_residency(winner, resolved_policy),
        limits=limits,
        variant_ref=(variant["id"] or None) if variant else None,
        variant_label=variant["label"] if variant else "",
        fallback_variant=fallback,
        cache_key_effect=variant["cache_key_effect"] if variant else "none",
        privacy_class=variant["privacy_class"] if variant else "non-personal",
        consent_basis=variant["consent_basis"] if variant else "not-required",
        analytics_dimension=variant["analytics_dimension"] if variant else "",
        capabilities_granted=granted,
        capabilities_denied=denied,
        egress_allowed=allowed,
        egress_denied=refused,
        denial_reason=denial_reason,
        considered=considered,
        warnings=warnings,
        # Set here, never taken from an argument. A caller cannot make this response claim an
        # execution, an observation or an enforcement, because there is no parameter with which
        # to ask for one.
        executed=False,
        observed=False,
        enforced=False,
        basis="policy-simulation",
        functions_digest=functions_digest(functions),
    )


def _no_function_verdict(
    functions: Sequence[Mapping[str, Any]], considered: List[Dict[str, Any]]
) -> InvocationVerdict:
    """The verdict for a request no function claimed.

    Args:
        functions: The lane's functions, for the digest.
        considered: The already-populated list of every function that was evaluated and skipped.

    Returns:
        A verdict whose every personalization field is the neutral value, so a caller rendering it
        does not have to special-case the ordinary outcome of a lane with no matching function.
    """
    return InvocationVerdict(
        outcome="skipped",
        outcome_reason=(
            "No enabled function on this lane matches this request, so the response is served "
            "exactly as it would be with no functions configured at all."
        ),
        function_ref=None,
        function_label="",
        version_ref=None,
        runtime="",
        rollout_mode="",
        rollout_percent=0,
        region="",
        residency_class="",
        limits={},
        variant_ref=None,
        variant_label="",
        fallback_variant="",
        cache_key_effect="none",
        privacy_class="non-personal",
        consent_basis="not-required",
        analytics_dimension="",
        capabilities_granted=[],
        capabilities_denied=[],
        egress_allowed=[],
        egress_denied=[],
        denial_reason=None,
        considered=considered,
        warnings=[],
        executed=False,
        observed=False,
        enforced=False,
        basis="policy-simulation",
        functions_digest=functions_digest(functions),
    )


def _consider_functions(
    *,
    functions: Sequence[Mapping[str, Any]],
    request: InvocationRequest,
    policy: Mapping[str, Any],
    considered: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Evaluate the lane's functions in precedence order, recording every one.

    Args:
        functions: The lane's functions, in any order.
        request: A normalized request.
        policy: A normalized policy.
        considered: Accumulator, appended to in evaluation order.

    Returns:
        The normalized function that won, or ``None`` when none did.
    """
    ordered = sorted(
        (normalize_function(fn) for fn in functions), key=lambda f: (f["ordinal"], f["id"])
    )
    winner: Optional[Dict[str, Any]] = None

    for fn in ordered:
        entry: Dict[str, Any] = {
            "kind": "function",
            "ref": fn["id"] or None,
            "label": fn["label"],
            "ordinal": fn["ordinal"],
        }
        if winner is not None:
            entry["outcome"] = "skipped"
            entry["reason"] = (
                f"Not reached: function {winner['ordinal']} \"{winner['label']}\" already "
                "claimed this request."
            )
            considered.append(entry)
            continue

        skip_reason = _function_skip_reason(fn, request, policy)
        if skip_reason is not None:
            entry["outcome"] = "skipped"
            entry["reason"] = skip_reason
            considered.append(entry)
            continue

        entry["outcome"] = "would-run"
        entry["reason"] = _would_run_sentence(fn, request)
        considered.append(entry)
        winner = fn

    return winner


def _function_skip_reason(
    fn: Mapping[str, Any], request: InvocationRequest, policy: Mapping[str, Any]
) -> Optional[str]:
    """Why a function did not claim this request, as a sentence.

    Args:
        fn: A normalized function.
        request: A normalized request.
        policy: A normalized policy.

    Returns:
        A sentence, or ``None`` when the function claims the request. Checks run
        cheapest-and-most-decisive first so the sentence an operator reads is the most useful one:
        the lane having functions turned off explains more than a matcher that did not match.
    """
    if not policy["functions_enabled"]:
        return (
            "Functions are not enabled on this lane, so no function participates in any request "
            "including this one."
        )
    if not fn["enabled"]:
        return "Disabled. The function is retained and will participate again when re-enabled."
    if fn["active_version_id"] is None:
        return (
            "No active version, so there is no code to run even though the matcher would have "
            "selected this request."
        )
    if fn["rollout_percent"] == 0:
        return (
            "At 0% rollout this function reaches no traffic, so it cannot apply to any request "
            "including this one."
        )
    if not matches_route(fn, request):
        return (
            f"Matcher {fn['matcher_kind']} \"{fn['matcher_value']}\" does not match "
            f"{request.method} {request.path}."
        )
    return None


def _would_run_sentence(fn: Mapping[str, Any], request: InvocationRequest) -> str:
    """Explain in one sentence what a matching function would do and under what rollout.

    Args:
        fn: A normalized function that matched.
        request: A normalized request.

    Returns:
        A sentence phrased so a simulated execution cannot be misread as a real one. Both rollout
        modes report ``would-run`` because neither one executes anything here; what differs is
        what an attached runtime would do, and the sentence says which.
    """
    scope = (
        "at full rollout"
        if fn["rollout_percent"] == 100
        else f"at {fn['rollout_percent']}% rollout, and this request is treated as in scope"
    )
    posture = (
        "and would run and act on the response"
        if fn["rollout_mode"] == "enforce"
        else "and is in simulate mode, so an attached runtime would record what it did and "
        "discard the result"
    )
    return (
        f"Function {fn['ordinal']} \"{fn['label']}\" matched {request.method} {request.path} "
        f"{posture} — {scope}. Nothing executed: no runtime tier is attached to this lane."
    )


def _resolve_capabilities(
    fn: Mapping[str, Any],
    capabilities: Sequence[Mapping[str, Any]],
    request: InvocationRequest,
    *,
    now: datetime,
) -> Tuple[List[str], List[str]]:
    """Split the capabilities this request needs into the granted and the denied.

    Deny-by-default is the absence of a grant row, so a capability with no row and a capability
    whose grant has lapsed are the same answer arrived at two ways, and both belong in the denied
    list rather than in an error.

    Args:
        fn: The winning normalized function.
        capabilities: Grants across the lane.
        request: A normalized request, whose ``requested_capabilities`` say what the code needs.
        now: Evaluation time, so a lapsed grant denies rather than allows.

    Returns:
        ``(granted, denied)``, each sorted so the verdict is stable across calls.
    """
    live = set()
    for raw in capabilities:
        grant = normalize_capability(raw)
        if fn["id"] and grant["function_id"] and grant["function_id"] != fn["id"]:
            continue
        if _expired(grant["expires_at"], now):
            continue
        live.add(grant["capability"])

    granted = sorted(c for c in request.requested_capabilities if c in live)
    denied = sorted(c for c in request.requested_capabilities if c not in live)
    return granted, denied


def _resolve_egress(
    fn: Mapping[str, Any],
    egress_rules: Sequence[Mapping[str, Any]],
    request: InvocationRequest,
    *,
    now: datetime,
) -> Tuple[List[str], List[str]]:
    """Split the destinations this request would call into the allowed and the refused.

    A destination is only reachable when the function also holds ``fetch-egress``; that second
    condition is checked by :func:`_resolve_capabilities`, and keeping the two separate is what
    makes the verdict able to say *which* of the two doors was shut.

    Args:
        fn: The winning normalized function.
        egress_rules: Allowlist entries across the lane.
        request: A normalized request, whose ``requested_destinations`` say what the code calls.
        now: Evaluation time, so a lapsed allowance denies rather than allows.

    Returns:
        ``(allowed, refused)``, each sorted so the verdict is stable across calls.
    """
    live: List[Dict[str, Any]] = []
    for raw in egress_rules:
        rule = normalize_egress_rule(raw)
        if fn["id"] and rule["function_id"] and rule["function_id"] != fn["id"]:
            continue
        if _expired(rule["expires_at"], now):
            continue
        live.append(rule)

    allowed = sorted(
        d for d in request.requested_destinations if _egress_rule_for(d, live) is not None
    )
    refused = sorted(
        d for d in request.requested_destinations if _egress_rule_for(d, live) is None
    )
    return allowed, refused


def _exceeded_limit(
    limits: Mapping[str, int], request: InvocationRequest
) -> Optional[str]:
    """Which resource ceiling this request's estimate would cross, if any.

    Args:
        limits: The resolved limits from :func:`_effective_limits`.
        request: A normalized request carrying the caller's estimates. Zero means the caller did
            not estimate, which is treated as "the question does not arise" rather than as zero
            usage — a simulation that invented a measurement would be the thing this module most
            needs not to do.

    Returns:
        A phrase naming the crossed ceiling, or ``None``.
    """
    if request.estimated_cpu_ms and request.estimated_cpu_ms > limits["cpu_ms"]:
        return f"CPU ceiling of {limits['cpu_ms']}ms"
    if request.estimated_memory_mb and request.estimated_memory_mb > limits["memory_mb"]:
        return f"memory ceiling of {limits['memory_mb']}MB"
    if request.estimated_wall_ms and request.estimated_wall_ms > limits["wall_ms"]:
        return f"wall-clock ceiling of {limits['wall_ms']}ms"
    return None


def _resolve_outcome(
    *,
    winner: Mapping[str, Any],
    denied_capabilities: Sequence[str],
    denied_egress: Sequence[str],
    exceeded: Optional[str],
) -> Tuple[str, Optional[str]]:
    """Turn the three denial checks into one outcome and one sentence.

    Args:
        winner: The normalized function that claimed the request.
        denied_capabilities: Capabilities asked for and not held.
        denied_egress: Destinations called and not allowlisted.
        exceeded: The phrase from :func:`_exceeded_limit`, or ``None``.

    Returns:
        ``(outcome, denial_reason)``. ``denial_reason`` is ``None`` when nothing was denied, and
        is quoted verbatim into ``slate_function_invocations.denial_reason`` otherwise so the UI
        does not restate it and the two cannot drift.
    """
    if denied_capabilities:
        names = ", ".join(denied_capabilities)
        return (
            "capability-denied",
            (
                f"Function \"{winner['label']}\" would use {names}, which it holds no live grant "
                "for. Capabilities are deny-by-default: the absence of a grant is the denial, so "
                "the handler fails closed rather than proceeding without them."
            ),
        )
    if denied_egress:
        names = ", ".join(denied_egress)
        return (
            "egress-denied",
            (
                f"Function \"{winner['label']}\" would call {names}, which no allowlist entry "
                "covers. Egress is deny-by-default: an unlisted destination is unreachable, so "
                "the outbound request fails rather than leaving the lane."
            ),
        )
    if exceeded is not None:
        return (
            "limit-exceeded",
            (
                f"Function \"{winner['label']}\" is estimated to cross its {exceeded}, so an "
                "attached runtime would terminate it mid-request rather than slow it. Tighten "
                "the handler or raise the lane ceiling deliberately."
            ),
        )
    return "would-run", None


def _restate_winner(
    considered: List[Dict[str, Any]],
    winner: Mapping[str, Any],
    outcome: str,
    denial_reason: Optional[str],
) -> None:
    """Replace the winning function's provisional entry with its final outcome.

    The considered list is written while functions are being matched, before the capability,
    egress and limit checks have run. Leaving the provisional ``would-run`` in place would let the
    list and the verdict disagree about the same function, which is exactly the kind of quiet
    inconsistency an investigation cannot recover from.

    Args:
        considered: The accumulated list, mutated in place.
        winner: The normalized function that claimed the request.
        outcome: The final outcome from :func:`_resolve_outcome`.
        denial_reason: The sentence explaining a denial, or ``None``.
    """
    if denial_reason is None:
        return
    for entry in considered:
        if entry["kind"] == "function" and entry["ref"] == (winner["id"] or None):
            entry["outcome"] = outcome
            entry["reason"] = denial_reason
            return


def _consider_variants(
    *,
    variants: Sequence[Mapping[str, Any]],
    function: Mapping[str, Any],
    request: InvocationRequest,
    considered: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Select between the winning function's personalization variants, recording every one.

    Args:
        variants: Variants across the lane; those belonging to another function are not reported,
            because a variant of a function that did not run explains nothing about this request.
        function: The winning normalized function.
        request: A normalized request.
        considered: Accumulator, appended to in evaluation order.

    Returns:
        ``(variant, fallback)``. The variant is ``None`` when none matched, and the fallback is
        the first declared one — present either way, because "and everybody else?" is answered by
        the fallback whether or not this particular reader matched.
    """
    mine: List[Dict[str, Any]] = []
    for raw in variants:
        candidate = normalize_variant(raw)
        if function["id"] and candidate["function_id"]:
            if candidate["function_id"] != function["id"]:
                continue
        mine.append(candidate)
    ordered = sorted(mine, key=lambda v: (v["ordinal"], v["id"]))

    fallback = next((v["fallback_variant"] for v in ordered if v["fallback_variant"]), "")
    selected: Optional[Dict[str, Any]] = None

    for variant in ordered:
        entry: Dict[str, Any] = {
            "kind": "variant",
            "ref": variant["id"] or None,
            "label": variant["label"],
            "ordinal": variant["ordinal"],
        }
        if selected is not None:
            entry["outcome"] = "skipped"
            entry["reason"] = (
                f"Not reached: variant {selected['ordinal']} \"{selected['label']}\" was already "
                "selected for this reader."
            )
            considered.append(entry)
            continue
        if not variant["enabled"]:
            entry["outcome"] = "skipped"
            entry["reason"] = (
                "Disabled, so every reader it would have matched receives the fallback "
                f"\"{variant['fallback_variant']}\" instead."
            )
            considered.append(entry)
            continue

        unmet = _unmet_audience_predicate(variant, request)
        if unmet is not None:
            entry["outcome"] = "skipped"
            entry["reason"] = (
                f"Audience rule not met: {unmet}. This reader receives the fallback "
                f"\"{variant['fallback_variant']}\"."
            )
            considered.append(entry)
            continue

        entry["outcome"] = "would-run"
        entry["reason"] = (
            f"Variant {variant['ordinal']} \"{variant['label']}\" matched this reader on its "
            f"{variant['audience_kind']} audience rule, reports under "
            f"\"{variant['analytics_dimension'] or 'no dimension'}\", is classified "
            f"{variant['privacy_class']} on a {variant['consent_basis']} basis, and its cache-key "
            f"effect is {variant['cache_key_effect']}."
        )
        considered.append(entry)
        selected = variant

    return selected, fallback


def _unmet_audience_predicate(
    variant: Mapping[str, Any], request: InvocationRequest
) -> Optional[str]:
    """The first audience predicate this reader fails, as a phrase.

    V189 stores the audience matcher as a JSON list of heterogeneous predicates precisely so the
    simulation can name which one failed. A predicate of an unrecognized kind is treated as unmet
    rather than as satisfied: an unknown condition on a personalizing variant should narrow it,
    not widen it.

    Args:
        variant: A normalized variant.
        request: A normalized request.

    Returns:
        A phrase naming the failed predicate, or ``None`` when every predicate holds. An empty
        matcher holds trivially, which is how a catch-all variant is written.
    """
    values = {
        "country": request.country,
        "geo": request.country,
        "language": request.language,
        "device": request.device,
        "cohort": request.cohort,
        "experiment": request.experiment,
    }

    for predicate in variant["audience_matcher"]:
        if not isinstance(predicate, Mapping):
            return "a malformed audience predicate"
        kind = str(predicate.get("kind") or "")
        if kind not in values:
            return f"predicate kind \"{kind}\" is not one this evaluator understands"

        actual = values[kind]
        if "equals" in predicate:
            expected = str(predicate.get("equals") or "")
            if kind in ("country", "geo"):
                expected = expected.upper()
            elif kind in ("language", "device"):
                expected = expected.lower()
            if actual != expected:
                return f"{kind} is {actual or 'unset'}, not {expected}"
        elif "in" in predicate:
            options = [str(o) for o in (predicate.get("in") or [])]
            if kind in ("country", "geo"):
                options = [o.upper() for o in options]
            elif kind in ("language", "device"):
                options = [o.lower() for o in options]
            if actual not in options:
                return f"{kind} is {actual or 'unset'}, not one of {', '.join(options) or 'any'}"
        else:
            return f"predicate on {kind} states no comparison"
    return None


def _simulation_warnings(
    *,
    winner: Mapping[str, Any],
    functions: Sequence[Mapping[str, Any]],
    variant: Optional[Mapping[str, Any]],
    policy: Optional[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    """Collect the concerns about whatever actually decided this request.

    A stored function or variant can become unsafe when the policy around it changes, or can
    predate a refusal this module later added. The simulation reports that rather than refusing to
    render: an operator investigating a personalized page needs to see the verdict, and a
    simulation is a read.

    Args:
        winner: The normalized function that claimed the request.
        functions: The lane's functions, as siblings for the shadowing warning.
        variant: The selected variant, or ``None``.
        policy: The raw policy row, passed through to the evaluators.

    Returns:
        Warning dicts the REST layer serializes directly, refusals included as entries rather than
        raised.
    """
    warnings: List[Dict[str, str]] = []

    def _record(items: Sequence[FunctionWarning]) -> None:
        for item in items:
            warnings.append(
                {"code": item.code, "message": item.message, "field": item.field or ""}
            )

    # The declared destinations are stripped before the re-check. Whether this function can reach
    # a host is already answered by the verdict's own ``egress_denied`` field against the caller's
    # ``now``; re-deriving it here would report the same denial twice, once as an outcome and once
    # as a refusal, and an operator reading both would reasonably conclude they were two problems.
    probe = dict(winner, declared_destinations=[])
    try:
        _record(
            evaluate_function_safety(
                probe,
                siblings=functions,
                policy=policy,
                now=_EPOCH,
            )
        )
    except SlateFunctionRefusedError as exc:
        warnings.append(
            {"code": exc.refusal.reason, "message": exc.refusal.sentence, "field": "function"}
        )

    if variant is not None:
        try:
            _record(evaluate_variant_safety(variant, function=winner, policy=policy))
        except SlateFunctionRefusedError as exc:
            warnings.append(
                {"code": exc.refusal.reason, "message": exc.refusal.sentence, "field": "variant"}
            )

    return warnings


#: The instant the simulation's re-check of a stored function is judged against. A stored
#: function's own safety checks are all time-independent — every expiry-sensitive check lives on a
#: capability or egress grant, which the simulation evaluates separately against the caller's
#: ``now`` — so a fixed instant here is not a hidden clock. It is spelled out rather than passed
#: through so that no future check can quietly start depending on wall time by reading it.
_EPOCH = datetime(1970, 1, 1)


# ─── Digests ──────────────────────────────────────────────────────────────────

#: The fields that decide what a function does. Everything else — the label, the timestamps, the
#: revision counter, the acknowledgements — is metadata about the function rather than behaviour,
#: and is excluded so renaming a function does not invalidate an approval or a historical
#: simulation.
_DECISIVE_FUNCTION_FIELDS = (
    "ordinal",
    "enabled",
    "matcher_kind",
    "matcher_value",
    "matcher_methods",
    "matcher_hosts",
    "runtime",
    "active_version_id",
    "rollout_mode",
    "rollout_percent",
    "region",
    "residency_class",
    "cpu_ms_limit",
    "memory_mb_limit",
    "wall_ms_limit",
    "env_var_names",
    "declared_destinations",
)


def body_digest(function: Mapping[str, Any]) -> str:
    """Content-address one function body.

    This is what an approval names. An approval that named only a row id would still look valid
    after that row changed underneath it, so ``slate_functions.body_digest`` stores the value this
    function produces and :func:`evaluate_approval_safety` compares against it. Changing any
    decisive field changes the digest and therefore invalidates the approval — which is the
    intended behaviour, because a re-edited function has not been reviewed.

    Args:
        function: A function row or request body, normalized or raw.

    Returns:
        ``sha256:<64 hex chars>``, matching the CHECK constraint on
        ``slate_functions.body_digest``.
    """
    normalized = normalize_function(function)
    decisive = {key: normalized[key] for key in _DECISIVE_FUNCTION_FIELDS}
    canonical = json.dumps(decisive, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def functions_digest(functions: Sequence[Mapping[str, Any]]) -> str:
    """Content-address an ordered set of functions.

    The determinism receipt: two simulations carrying the same digest and the same request must
    agree, and a simulation whose digest no longer matches the lane is *explained* by that fact
    rather than contradicted by it. Same instinct as ``slate_artifacts.content_digest`` — identity
    by content.

    Only enabled functions contribute, and only the fields that affect a decision. A disabled
    function changes nothing about what the lane does, so including it would make an unrelated
    toggle appear to invalidate every recorded simulation.

    Args:
        functions: Functions in any order; they are normalized and sorted here.

    Returns:
        ``sha256:<64 hex chars>``.
    """
    decisive: List[Dict[str, Any]] = []
    for fn in functions:
        normalized = normalize_function(fn)
        if not normalized["enabled"]:
            continue
        decisive.append({key: normalized[key] for key in _DECISIVE_FUNCTION_FIELDS})
    # Sorted by (ordinal, matcher_value) rather than ordinal alone: V189's UNIQUE constraint
    # forbids ties on a saved lane, but this function is also called on unsaved bodies during a
    # preview, and an unstable sort there would produce two digests for one set.
    decisive.sort(key=lambda f: (f["ordinal"], str(f["matcher_value"])))
    canonical = json.dumps(decisive, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ─── Time ─────────────────────────────────────────────────────────────────────


def _as_datetime(value: Any, now: datetime) -> Optional[datetime]:
    """Parse a timestamp into a datetime comparable with ``now``.

    Args:
        value: A datetime, an ISO-8601 string, or ``None``.
        now: Evaluation time, whose tzinfo a naive value adopts. Comparing a naive and an aware
            datetime raises, and a capability check that raised on a timezone detail would fail in
            a way nobody could act on.

    Returns:
        The parsed moment, or ``None`` when the value is absent or unparseable.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None and now.tzinfo is not None:
        moment = moment.replace(tzinfo=now.tzinfo)
    if moment.tzinfo is not None and now.tzinfo is None:
        moment = moment.replace(tzinfo=None)
    return moment


def _expired(expires_at: Any, now: datetime) -> bool:
    """Whether an expiry has passed.

    Args:
        expires_at: The ``expires_at`` value, as a datetime or ISO-8601 string.
        now: Evaluation time.

    Returns:
        True when the grant or allowance no longer applies. An absent value is a permanent grant
        and is not expired; an *unparseable* one is also treated as not expired, matching
        :func:`app.slate_security._expired`. That is the safe direction on the security surface
        because protection stays on — here it is the safe direction for a different reason: a bad
        timestamp must not silently revoke a capability an operator is relying on, and
        :func:`evaluate_capability_safety` already refuses a grant whose expiry cannot be parsed
        at write time.
    """
    moment = _as_datetime(expires_at, now)
    if moment is None:
        return False
    return moment <= now
