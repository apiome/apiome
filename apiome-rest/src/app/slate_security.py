"""Slate Edge security policy rules — UXE-3.2 (private-suite#2474).

The decisions that must hold before security policy changes, and the evaluation that explains
what a policy would do to a request, kept in one pure module so they can be tested exhaustively
without a database and so the REST layer cannot implement a second, subtly different copy of
them. It is the security counterpart of :mod:`app.slate_cache` and deliberately reads like it:
an operator who has learned what ``glob`` means on the cache surface must not have to relearn it
here.

The refusal vocabulary is shared with ``designer/lib/authoring/security-actions.ts`` for the
reason :mod:`app.slate_cache` states: the authoring surface makes ``disabledReason`` the only way
to disable a control, so a backend that invented its own codes would leave the operator with a
greyed-out dead end instead of a sentence explaining what to do.

Four things are worth stating outright, and the last one is the whole ticket.

1. **Presets are values, not adjectives.** :data:`MANAGED_RULESETS`, :data:`BOT_PRESETS`,
   :data:`RATE_PRESETS` and :data:`MANAGED_GROUPS` are tables of literals, each stating in prose
   what it will and will not do to real traffic. "Aggressive" is not a mood the system interprets
   at request time. That is what makes acceptance criterion 2 ("managed presets have safe
   defaults and explain expected impact") checkable rather than claimed — a preset that does not
   explain itself fails a golden test, not a code review.

2. **Evaluation is a total order.** Rules are sorted by ``(ordinal, id)`` and
   ``UNIQUE (environment_id, ordinal)`` in V188 forbids ties. Without that, which rule blocked
   the customer who phoned in would depend on physical row order. :func:`rules_digest` is the
   receipt; :func:`body_digest` is what an approval is checked against, so approving one body and
   shipping another is detectable rather than merely unlikely.

3. **A staged rollout cannot lock anybody out.** A rule in ``simulate`` reports ``would-block``
   and never ``blocked``, and a rule at 0% reaches no traffic at all. The refusals in
   :data:`_HARD_REFUSALS` are the rest of that guarantee: a ``block`` rule covering every route,
   a rule reaching ``enforce`` without ever having run in ``simulate``, and an unbounded
   exception each have no acknowledgement path, because each of them is a lockout or a hole
   rather than a cost.

4. **Nothing here blocks anything.** ``deploy/`` is a single Caddyfile with no WAF, no bot
   management and no CDN behind it. This module plans, explains and simulates; the store records.
   An unenforced cache rule wastes a purge — an unenforced WAF rule means somebody believes they
   are stopping an attacker and is not. So :class:`SimulationVerdict` carries ``enforced`` and
   ``observed`` as fields this module always sets to ``False``, and there is no code path here
   able to set them otherwise.
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
    "BOT_PRESETS",
    "BOT_PRESET_IDS",
    "EVENT_ACTIONS",
    "GROUP_MODES",
    "MANAGED_GROUPS",
    "MANAGED_GROUP_IDS",
    "MANAGED_RULESETS",
    "MANAGED_RULESET_IDS",
    "MATCHER_KINDS",
    "RATE_PRESETS",
    "RATE_PRESET_IDS",
    "ROLLOUT_MODES",
    "RULE_ACTIONS",
    "BotPreset",
    "ManagedGroup",
    "ManagedRuleset",
    "RatePreset",
    "SecurityRefusal",
    "SecurityWarning",
    "SimulationRequest",
    "SimulationVerdict",
    "SlateSecurityRefusedError",
    "body_digest",
    "covers_everything",
    "evaluate_approval_safety",
    "evaluate_exception_safety",
    "evaluate_policy_safety",
    "evaluate_security_safety",
    "matches_route",
    "normalize_exception",
    "normalize_policy",
    "normalize_rule",
    "rules_digest",
    "simulate_request",
]

# ─── Enumerations, mirroring V188's CHECK constraints ─────────────────────────

#: The four matcher kinds, identical to ``slate_cache_rules``. Sharing them is the point: two
#: surfaces that spelled route matching differently would make one of them a trap.
MATCHER_KINDS = ("exact", "prefix", "glob", "regex")

#: What a custom rule does when it wins. ``allow`` is an early exit that stops later rules, which
#: is how a carve-out is expressed as a rule rather than as a special case in the evaluator.
RULE_ACTIONS = ("allow", "log", "challenge", "rate-limit", "block")

#: A rule is either recording what it would have done, or acting.
ROLLOUT_MODES = ("simulate", "enforce")

#: Modes a managed WAF group can be put into on one lane.
GROUP_MODES = ("off", "log", "challenge", "block")

#: What a security event records. ``would-block`` is what a simulated enforcing block reports;
#: nothing in this module can produce ``blocked``, because nothing in the request path can block.
EVENT_ACTIONS = ("allowed", "logged", "challenged", "rate-limited", "blocked", "would-block")

MANAGED_RULESET_IDS = ("off", "core", "strict")
BOT_PRESET_IDS = ("off", "monitor", "balanced", "aggressive")
RATE_PRESET_IDS = ("off", "generous", "standard", "strict")


# ─── Managed ruleset tiers ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ManagedRuleset:
    """A managed WAF tier, as a complete set of values rather than a name.

    Attributes:
        key: One of :data:`MANAGED_RULESET_IDS`.
        label: Operator-facing name.
        intent: The one-line intent from roadmap §29.4, quoted rather than paraphrased.
        expected_impact: What turning this tier on does to ordinary documentation traffic, in
            prose. Acceptance criterion 2 is satisfied by this field being true and specific, so
            it names the false-positive families rather than promising there are none.
        groups: Catalog ids of the managed groups the tier enables, in catalog order.
        group_modes: The mode each enabled group runs in under this tier.
        requires_reason: Whether choosing this tier must carry a stated reason. Only ``off``
            does: disabling the WAF with no explanation is the change nobody can account for
            afterwards, and V188 enforces the same thing with a CHECK.
        unsafe_if: What this tier is a poor fit for, as sentences the UI renders next to it.
    """

    key: str
    label: str
    intent: str
    expected_impact: str
    groups: Tuple[str, ...]
    group_modes: Mapping[str, str]
    requires_reason: bool
    unsafe_if: Tuple[str, ...]


# ─── Managed WAF group catalog ────────────────────────────────────────────────


@dataclass(frozen=True)
class ManagedGroup:
    """One curated WAF group, versioned in code rather than seeded per environment.

    V188 stores only the deviation from ``default_mode``, so an empty override table means
    "everything is as shipped". That only works if the catalog is a reviewable literal — which
    is why this lives here, in a diff, and not in a seed script that drifts per tenant.

    Attributes:
        id: Catalog identifier, stored in ``slate_security_managed_groups.group_id``.
        title: Operator-facing name.
        description: What the group detects, in the terms an operator would describe an attack.
        default_mode: The mode the group ships in, one of :data:`GROUP_MODES`.
        false_positive_risk: ``low``, ``medium`` or ``high`` — how likely this group is to act on
            a legitimate request.
        expected_impact: What an operator should expect to see once this group acts, including
            the legitimate traffic most likely to be caught. A group that cannot say what it will
            break is a group nobody can safely enable.
    """

    id: str
    title: str
    description: str
    default_mode: str
    false_positive_risk: str
    expected_impact: str


MANAGED_GROUPS: Mapping[str, ManagedGroup] = {
    "sql-injection": ManagedGroup(
        id="sql-injection",
        title="SQL injection",
        description=(
            "Requests carrying SQL fragments in a path, query string or body — union selects, "
            "comment terminators, stacked statements and the usual tautologies."
        ),
        default_mode="block",
        false_positive_risk="low",
        expected_impact=(
            "Blocks a family of requests a documentation site has no legitimate reason to "
            "receive, so on a docs lane it is close to free. The one place it bites is a search "
            "box that puts the reader's raw query in the URL: a reader searching for "
            "\"SELECT ... UNION\" in a SQL guide can trip it. If this lane documents SQL, add a "
            "scoped exception for the search route rather than turning the group off."
        ),
    ),
    "xss": ManagedGroup(
        id="xss",
        title="Cross-site scripting",
        description=(
            "Requests carrying script tags, event-handler attributes or javascript: URLs in a "
            "parameter that is likely to be reflected back into a page."
        ),
        default_mode="block",
        false_positive_risk="medium",
        expected_impact=(
            "Blocks reflected-XSS probes. The medium risk is real and has one common cause: a "
            "documentation site about web development quotes markup constantly, so a page "
            "anchor, a code-sample permalink or a shared search query containing a script tag "
            "can match. Trial it in log mode for a release before letting it block."
        ),
    ),
    "path-traversal": ManagedGroup(
        id="path-traversal",
        title="Path traversal",
        description=(
            "Requests whose path attempts to escape the document root — dot-dot segments, "
            "encoded separators, null bytes and absolute filesystem paths."
        ),
        default_mode="block",
        false_positive_risk="low",
        expected_impact=(
            "Blocks attempts to read files outside the published site. Well-formed links never "
            "contain traversal sequences, so legitimate readers are unaffected; the traffic this "
            "removes is almost entirely automated scanning."
        ),
    ),
    "remote-code-execution": ManagedGroup(
        id="remote-code-execution",
        title="Remote code execution",
        description=(
            "Requests carrying shell metacharacters, interpreter invocations or known "
            "deserialization payloads aimed at running code on the origin."
        ),
        default_mode="block",
        false_positive_risk="low",
        expected_impact=(
            "Blocks command-injection and deserialization probes. A static documentation site "
            "executes nothing, so this group is best understood as removing noise from the logs "
            "rather than as closing a hole — but it stays on because the origin behind the lane "
            "is not guaranteed to stay static."
        ),
    ),
    "scanner-detection": ManagedGroup(
        id="scanner-detection",
        title="Scanner detection",
        description=(
            "Requests bearing the signatures of automated vulnerability scanners: known tool "
            "user agents, and the characteristic sweep of probes for admin panels and backup "
            "files that a real reader never makes."
        ),
        default_mode="log",
        false_positive_risk="medium",
        expected_impact=(
            "Ships in log mode on purpose. Scanner signatures overlap with legitimate automation "
            "— uptime monitors, link checkers, accessibility crawlers and your own CI smoke "
            "tests all look a little like a scanner. Logging first tells you which of those you "
            "actually run before a block mode surprises you during a release."
        ),
    ),
    "protocol-anomaly": ManagedGroup(
        id="protocol-anomaly",
        title="Protocol anomaly",
        description=(
            "Requests that violate HTTP itself: conflicting content-length and transfer-encoding "
            "headers, malformed request lines, duplicated host headers and other request "
            "smuggling primitives."
        ),
        default_mode="block",
        false_positive_risk="low",
        expected_impact=(
            "Blocks malformed requests that no compliant client produces. The rare false "
            "positive comes from an old proxy in front of a corporate reader emitting headers "
            "that were legal a decade ago; when that happens it affects one network, and the "
            "event evidence names the client prefix so it can be identified."
        ),
    ),
}

MANAGED_GROUP_IDS = tuple(MANAGED_GROUPS)

MANAGED_RULESETS: Mapping[str, ManagedRuleset] = {
    "off": ManagedRuleset(
        key="off",
        label="Off",
        intent="No managed WAF coverage",
        expected_impact=(
            "No managed group inspects anything. Custom rules still apply, but the curated "
            "coverage for injection, traversal and code execution is gone entirely. This is the "
            "setting chosen at 03:00 to prove the WAF is not the cause of an outage, and the one "
            "most likely to still be set a month later, which is why it requires a stated reason "
            "and appears in the audit trail as its own entry."
        ),
        groups=(),
        group_modes={},
        requires_reason=True,
        unsafe_if=(
            "Any use beyond an incident: a WAF turned off for debugging becomes the "
            "configuration unless somebody turns it back on.",
        ),
    ),
    "core": ManagedRuleset(
        key="core",
        label="Core",
        intent="Curated coverage for the attack families that matter to a published site",
        expected_impact=(
            "The safe default, and the tier a documentation lane should run. Injection, "
            "traversal and code-execution groups block; scanner detection only logs. Expect "
            "blocked traffic to be almost entirely automated, and expect roughly no effect on "
            "readers unless the site's own search puts raw reader input into a URL."
        ),
        groups=(
            "sql-injection",
            "xss",
            "path-traversal",
            "remote-code-execution",
            "scanner-detection",
            "protocol-anomaly",
        ),
        group_modes={
            "sql-injection": "block",
            "xss": "log",
            "path-traversal": "block",
            "remote-code-execution": "block",
            "scanner-detection": "log",
            "protocol-anomaly": "block",
        },
        requires_reason=False,
        unsafe_if=(
            "A lane serving an interactive application rather than published pages: Core is "
            "tuned for documents, and an application's own API traffic is more varied.",
        ),
    ),
    "strict": ManagedRuleset(
        key="strict",
        label="Strict",
        intent="Every curated group enforcing, including the ones with false positives",
        expected_impact=(
            "Every group blocks, including cross-site scripting and scanner detection. Expect "
            "false positives: a page whose URL quotes markup, a shared search link, an uptime "
            "monitor or a link checker can all be blocked, and the reader sees a failure rather "
            "than a page. Choose this when the lane is under active attack and a blocked reader "
            "is cheaper than a successful probe — and watch the event stream afterwards, because "
            "the site being unreadable is the failure mode this tier has."
        ),
        groups=(
            "sql-injection",
            "xss",
            "path-traversal",
            "remote-code-execution",
            "scanner-detection",
            "protocol-anomaly",
        ),
        group_modes={
            "sql-injection": "block",
            "xss": "block",
            "path-traversal": "block",
            "remote-code-execution": "block",
            "scanner-detection": "block",
            "protocol-anomaly": "block",
        },
        requires_reason=False,
        unsafe_if=(
            "A site whose own search reflects reader input into the URL: Strict blocks readers "
            "for searching.",
            "A lane monitored by third-party uptime or accessibility crawlers: scanner detection "
            "blocks them, and the first symptom is a monitoring alert rather than a security "
            "event.",
        ),
    ),
}


# ─── Bot presets ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BotPreset:
    """A safe bot-management preset (roadmap §29.4).

    Attributes:
        key: One of :data:`BOT_PRESET_IDS`.
        label: Operator-facing name.
        intent: The one-line intent, quoted from the roadmap.
        expected_impact: What this preset does to real crawlers, in prose, naming the ones a
            documentation site depends on.
        verified_bots: What happens to verified search-engine and platform crawlers.
        likely_automated: What happens to traffic classified as likely automated.
        automated: What happens to traffic classified as definitely automated.
        unsafe_if: Sentences the UI renders next to the choice.
    """

    key: str
    label: str
    intent: str
    expected_impact: str
    verified_bots: str
    likely_automated: str
    automated: str
    unsafe_if: Tuple[str, ...]


BOT_PRESETS: Mapping[str, BotPreset] = {
    "off": BotPreset(
        key="off",
        label="Off",
        intent="No bot classification",
        expected_impact=(
            "Nothing is classified and nothing is acted on. Automated traffic reaches the origin "
            "exactly as a reader does. The cost is not usually security; it is that the event "
            "stream can no longer tell you whether a traffic spike was people or a scraper."
        ),
        verified_bots="Untouched.",
        likely_automated="Untouched.",
        automated="Untouched.",
        unsafe_if=(
            "You are investigating a traffic anomaly: with classification off there is nothing "
            "to correlate against.",
        ),
    ),
    "monitor": BotPreset(
        key="monitor",
        label="Monitor",
        intent="Classify and record, act on nothing",
        expected_impact=(
            "Every request is classified and recorded as a security event; none is challenged or "
            "blocked. This is how you find out what your automated traffic actually is before "
            "deciding to act on it, and it cannot break a reader or a crawler because it does "
            "nothing to either."
        ),
        verified_bots="Recorded as allowed.",
        likely_automated="Recorded as allowed.",
        automated="Recorded as allowed.",
        unsafe_if=(
            "You are under active scraping load: monitoring describes the problem without "
            "reducing it.",
        ),
    ),
    "balanced": BotPreset(
        key="balanced",
        label="Balanced",
        intent="Challenge definite automation, leave verified crawlers alone",
        expected_impact=(
            "The safe default for a published site. Verified search-engine crawlers pass "
            "untouched, so indexing is unaffected — this is the clause that matters, because a "
            "documentation site that falls out of search results has been damaged as surely as "
            "one that is offline. Traffic classified as definitely automated is challenged, "
            "which stops naive scrapers and costs a real reader nothing because a real reader is "
            "not classified that way. Likely-automated traffic is only logged, because that "
            "class is where the misclassifications live."
        ),
        verified_bots="Allowed without challenge.",
        likely_automated="Logged.",
        automated="Challenged.",
        unsafe_if=(
            "A partner integration reads this lane programmatically without a verified crawler "
            "identity: it will be challenged and will fail. Add a scoped exception for it.",
        ),
    ),
    "aggressive": BotPreset(
        key="aggressive",
        label="Aggressive",
        intent="Challenge anything that looks automated",
        expected_impact=(
            "Both automated and likely-automated traffic is challenged. Verified crawlers still "
            "pass, but the likely-automated class contains real readers behind corporate proxies "
            "and privacy browsers, and they will meet a challenge on a page that should have "
            "just loaded. Expect support contacts. Choose this while being scraped, and go back "
            "to Balanced afterwards."
        ),
        verified_bots="Allowed without challenge.",
        likely_automated="Challenged.",
        automated="Challenged.",
        unsafe_if=(
            "Ordinary operation: challenging the likely-automated class means challenging some "
            "share of real readers every day.",
            "A lane read by scripts, CI jobs or documentation tooling you own.",
        ),
    ),
}


# ─── Rate presets ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RatePreset:
    """A safe rate-limit preset (roadmap §29.4).

    The budget is stated as a concrete request count over a concrete window, not as a word, so
    that :func:`evaluate_security_safety` can compare a custom rule against a floor and so a
    golden test can assert the value byte for byte.

    Attributes:
        key: One of :data:`RATE_PRESET_IDS`.
        label: Operator-facing name.
        intent: The one-line intent, quoted from the roadmap.
        expected_impact: What this budget means for somebody actually reading the site.
        requests: Request budget, or 0 when the preset imposes none.
        window_seconds: Window the budget applies over, or 0 when there is none.
        action: What happens when the budget is exceeded, one of :data:`RULE_ACTIONS`.
        unsafe_if: Sentences the UI renders next to the choice.
    """

    key: str
    label: str
    intent: str
    expected_impact: str
    requests: int
    window_seconds: int
    action: str
    unsafe_if: Tuple[str, ...]


RATE_PRESETS: Mapping[str, RatePreset] = {
    "off": RatePreset(
        key="off",
        label="Off",
        intent="No rate limiting",
        expected_impact=(
            "No client is ever slowed. A single origin can be saturated by one determined "
            "scraper, and the first symptom is a slow site rather than a security event."
        ),
        requests=0,
        window_seconds=0,
        action="allow",
        unsafe_if=("The origin has no capacity headroom of its own.",),
    ),
    "generous": RatePreset(
        key="generous",
        label="Generous",
        intent="A ceiling only a scraper reaches",
        expected_impact=(
            "600 requests a minute from one client prefix. A person reading fast, with every "
            "asset request counted and nothing cached, does not approach this; a scraper "
            "downloading the site does. Exceeding it logs rather than blocks, so the first thing "
            "this preset ever does is tell you it would have acted."
        ),
        requests=600,
        window_seconds=60,
        action="log",
        unsafe_if=(
            "You need the limit to actually reduce load: this one reports and does not act.",
        ),
    ),
    "standard": RatePreset(
        key="standard",
        label="Standard",
        intent="Challenge sustained automated reading",
        expected_impact=(
            "300 requests a minute from one client prefix, then a challenge. A documentation page "
            "with its assets is a few dozen requests, so this leaves a person roughly ten full "
            "page loads a minute with an empty cache — comfortably above real reading, and below "
            "what a scraper wants. Shared office or university networks arriving behind one "
            "address are the group most likely to notice."
        ),
        requests=300,
        window_seconds=60,
        action="challenge",
        unsafe_if=(
            "Large numbers of readers share one egress address: the budget is per client prefix, "
            "not per person.",
        ),
    ),
    "strict": RatePreset(
        key="strict",
        label="Strict",
        intent="A tight budget for a lane under load",
        expected_impact=(
            "120 requests a minute from one client prefix, then a challenge. This is close enough "
            "to real reading that a reader on a cold cache opening several pages quickly can meet "
            "a challenge. It is an incident setting: it trades some legitimate reading for origin "
            "headroom, and that trade is only worth making while the origin is actually under "
            "pressure."
        ),
        requests=120,
        window_seconds=60,
        action="challenge",
        unsafe_if=(
            "Ordinary operation: a budget this tight will challenge real readers on a shared "
            "network.",
            "A lane whose pages carry many separate assets, which multiplies every page view "
            "against the budget.",
        ),
    ),
}


# ─── Refusals and warnings ────────────────────────────────────────────────────

#: Every reason a security write can be refused. Mirrors the UI's
#: ``AuthoringSecurityRefusalReason``.
SecurityRefusalReason = Literal[
    "blocks-entire-site",
    "blocks-documentation-root",
    "enforce-without-simulation",
    "enforce-without-approval",
    "exception-unbounded",
    "exception-outlives-limit",
    "managed-off-without-reason",
    "rate-limit-below-floor",
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
    "blocks-entire-site": (
        "This rule blocks every route on the lane. There is no request it would let through, "
        "including the one an operator would use to remove it. Scope the matcher to the routes "
        "you mean to protect."
    ),
    "blocks-documentation-root": (
        "This rule blocks or challenges the documentation root, so the site's entry point stops "
        "being reachable. Documentation that cannot be opened is indistinguishable from "
        "documentation that is down. Scope the matcher below the root."
    ),
    "enforce-without-simulation": (
        "This rule would begin enforcing without ever having run in simulate. Simulate first: it "
        "records exactly what the rule would have done, and it is the only way to find out "
        "whether it catches real readers before it catches them."
    ),
    "enforce-without-approval": (
        "An enforcing block rule needs an approval from somebody other than its author. Blocking "
        "traffic is the one change where a second pair of eyes is worth the delay."
    ),
    "exception-unbounded": (
        "This exception matches every route, or never expires. An exception that covers "
        "everything, or that cannot lapse, has stopped being an exception and become the policy. "
        "Give it a route scope and an end date."
    ),
    "exception-outlives-limit": (
        "This exception expires beyond the maximum carve-out window. A hole that outlives the "
        "reason it was opened is the one nobody can justify at review; renew it deliberately "
        "instead of opening it indefinitely."
    ),
    "managed-off-without-reason": (
        "Turning the managed ruleset off needs a stated reason. This is the change that is "
        "hardest to explain months later, and the reason is the part that survives the incident."
    ),
    "rate-limit-below-floor": (
        "This rate budget is below what ordinary reading costs, so it would challenge or block "
        "readers rather than automation. A documentation page and its assets are dozens of "
        "requests; set a budget above that."
    ),
    "matcher-invalid": (
        "This route matcher does not compile, so it can never be evaluated. Fix the pattern."
    ),
    "ordinal-conflict": (
        "Another rule already holds that precedence on this lane. Two rules at the same "
        "precedence would make which one blocked a request depend on row order."
    ),
    "policy-version-conflict": (
        "Another operator changed this lane's security policy while this edit was being "
        "prepared. Re-read the policy and try again."
    ),
    "approval-stale": (
        "The approved body is not the body being written. An approval names what was reviewed, "
        "not just which rule it was about; get the current body approved."
    ),
    "approval-self": (
        "The author of a change cannot approve it. Dual control with one person is a record, not "
        "a review."
    ),
}

#: Refusals with no acknowledgement path. Each one is a lockout, an unbounded hole or a broken
#: control — never merely a cost. An "I accept the risk" checkbox over these would be a checkbox
#: over an outage or over the absence of the review that was supposed to prevent one. Every
#: refusal this module raises is hard; the set is spelled out anyway so a future reason added to
#: :data:`_REFUSAL_SENTENCES` has to decide which side it is on rather than defaulting to one.
_HARD_REFUSALS = frozenset(
    {
        "blocks-entire-site",
        "blocks-documentation-root",
        "enforce-without-simulation",
        "enforce-without-approval",
        "exception-unbounded",
        "exception-outlives-limit",
        "managed-off-without-reason",
        "rate-limit-below-floor",
        "matcher-invalid",
        "ordinal-conflict",
        "policy-version-conflict",
        "approval-stale",
        "approval-self",
    }
)

#: Warning reasons an operator may acknowledge. These cost reach, clarity or search visibility;
#: none of them makes the lane unreadable or opens an unbounded hole.
_WARNING_SENTENCES: Dict[str, str] = {
    "broad-matcher": (
        "This rule covers a large share of the lane. That is right for a rule that logs and "
        "risky for one that acts, because the routes it catches by accident are the ones nobody "
        "tested."
    ),
    "challenge-on-crawlable-route": (
        "This rule challenges a route that search engines index. A crawler cannot solve a "
        "challenge, so the affected pages will fall out of search results — which looks like a "
        "content problem weeks later, not like a security setting."
    ),
    "rule-shadowed": (
        "A higher-precedence rule already covers everything this one matches, so it can never "
        "win. That is usually an editing mistake."
    ),
    "rollout-jump": (
        "This rule goes from reaching no traffic to reaching all of it in one step. A staged "
        "rollout exists so a mistake is visible at 1% instead of at 100%."
    ),
    "expiry-missing": (
        "This rule has no expiry. Security rules are usually written during an incident, and one "
        "that cannot lapse outlives the reason it was added."
    ),
}

#: Routes whose loss makes the site unreadable rather than merely narrower. Blocking or
#: challenging any of them is refused outright, because a documentation site whose entry point
#: returns a challenge is down as far as a reader is concerned.
_DOCUMENTATION_ROOTS = ("/", "/docs", "/docs/", "/index.html")

#: Actions that deny or interrupt a reader. The distinction from ``allow``/``log`` is what
#: separates a rule that observes from one that can lock somebody out.
_DENYING_ACTIONS = frozenset({"challenge", "rate-limit", "block"})

#: The lowest request budget a rule may impose, expressed per minute. A documentation page with
#: its stylesheet, fonts, scripts and images is easily thirty requests on a cold cache, and a
#: reader opening two pages in a minute should never meet a challenge. Sixty is that number with
#: room to be wrong in the safe direction.
_RATE_FLOOR_REQUESTS_PER_MINUTE = 60

#: The longest an exception may run before it has to be renewed deliberately. Ninety days is one
#: quarter: long enough to cover a vendor fix, short enough that every carve-out is re-justified
#: within a review cycle.
_MAX_EXCEPTION_WINDOW_DAYS = 90

#: Above this share of the lane, a matcher is broad enough to be worth a sentence. Expressed as
#: a prefix depth rather than a percentage because the lane's route inventory is not available
#: here — a rule anchored at or above the first path segment is the broad case.
_BROAD_MATCHER_MAX_SEGMENTS = 1


@dataclass(frozen=True)
class SecurityRefusal:
    """A named, explained refusal to change security policy."""

    reason: str
    sentence: str

    @staticmethod
    def of(reason: str) -> "SecurityRefusal":
        """Build a refusal from its reason code.

        Args:
            reason: One of :data:`SecurityRefusalReason`.

        Returns:
            The refusal with its operator-facing sentence attached.
        """
        return SecurityRefusal(
            reason=reason,
            sentence=_REFUSAL_SENTENCES.get(
                reason, "This security policy change cannot be applied."
            ),
        )


@dataclass(frozen=True)
class SecurityWarning:
    """A named concern that does not block the write.

    Attributes:
        code: One of the keys of :data:`_WARNING_SENTENCES`.
        message: The operator-facing sentence.
        field: Which rule field the warning attaches to, so the UI can place it.
    """

    code: str
    message: str
    field: Optional[str] = None

    @staticmethod
    def of(code: str, field: Optional[str] = None) -> "SecurityWarning":
        """Build a warning from its code.

        Args:
            code: One of the keys of :data:`_WARNING_SENTENCES`.
            field: Rule field the warning is about, when there is one.

        Returns:
            The warning with its sentence attached.
        """
        return SecurityWarning(
            code=code,
            message=_WARNING_SENTENCES.get(code, "This rule may not behave as intended."),
            field=field,
        )


class SlateSecurityRefusedError(Exception):
    """A security policy change was refused. Carries the named reason and its sentence.

    Raising rather than returning is deliberate for the REST layer, matching
    :class:`app.slate_cache.SlateCacheRefusedError`: a refused rule write must never fall through
    to a persist.
    """

    def __init__(self, refusal: SecurityRefusal) -> None:
        self.refusal = refusal
        self.code = refusal.reason
        super().__init__(refusal.sentence)


# ─── Normalization ────────────────────────────────────────────────────────────


def normalize_rule(rule: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce a rule mapping into the canonical shape evaluation and hashing assume.

    Missing fields take their V188 column default, and string lists are upper- or lower-cased
    where the HTTP specification is case-insensitive (methods, hosts). Doing this once, here, is
    what lets :func:`rules_digest` produce the same hash for two rules that differ only in
    spelling.

    Two fields are not columns in V188 and are read from the request body instead:
    ``simulated_at``, which records that this rule has actually run in simulate, and
    ``previous_rollout_percent``, which is what the rollout it is leaving was set to. Both are
    facts the caller already holds — the store reconstructs them from
    ``slate_security_rule_revisions`` — and passing them in keeps this module free of a query.

    Args:
        rule: A rule row or request body.

    Returns:
        A new dict with every field present and canonically cased.
    """
    return {
        "id": str(rule.get("id") or ""),
        "ordinal": int(rule.get("ordinal") or 0),
        "enabled": bool(rule.get("enabled", True)),
        "label": str(rule.get("label") or ""),
        "matcher_kind": str(rule.get("matcher_kind") or "prefix"),
        # An absent matcher defaults to "/", but an explicitly empty one is preserved so
        # _matcher_compiles can refuse it. Coercing "" to "/" here would silently turn a
        # half-filled form into a rule that covers the entire site — which for a block rule is
        # the lockout this module exists to prevent.
        "matcher_value": (
            "/" if rule.get("matcher_value") is None else str(rule.get("matcher_value"))
        ),
        # Empty means every method. V188 says so explicitly, and for a security rule that is the
        # safe default rather than the dangerous one: a rule that protected GET and forgot POST
        # would be a hole shaped like a typo.
        "matcher_methods": sorted({str(m).upper() for m in (rule.get("matcher_methods") or [])}),
        "matcher_hosts": sorted({str(h).lower() for h in (rule.get("matcher_hosts") or [])}),
        "conditions": list(rule.get("conditions") or []),
        "action": str(rule.get("action") or "log"),
        "rate_requests": (
            None if rule.get("rate_requests") is None else int(rule["rate_requests"])
        ),
        "rate_window_seconds": (
            None if rule.get("rate_window_seconds") is None else int(rule["rate_window_seconds"])
        ),
        "rollout_mode": str(rule.get("rollout_mode") or "simulate"),
        "rollout_percent": int(rule.get("rollout_percent") or 0),
        "previous_rollout_percent": (
            None
            if rule.get("previous_rollout_percent") is None
            else int(rule["previous_rollout_percent"])
        ),
        "simulated_at": rule.get("simulated_at"),
        "expires_at": rule.get("expires_at"),
        "acknowledged_warnings": sorted(
            {str(w) for w in (rule.get("acknowledged_warnings") or [])}
        ),
        "author_actor_key": str(rule.get("author_actor_key") or ""),
        "approvals": list(rule.get("approvals") or []),
    }


def normalize_policy(policy: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Coerce a policy row into the canonical shape evaluation assumes.

    Args:
        policy: A ``slate_security_policies`` row, or ``None`` for a lane that has never been
            configured — which is treated as the shipped defaults rather than as an error, so a
            simulation against a fresh lane still renders.

    Returns:
        A new dict with every decisive policy field present.
    """
    source: Mapping[str, Any] = policy or {}
    return {
        "managed_ruleset": str(source.get("managed_ruleset") or "core"),
        "bot_preset": str(source.get("bot_preset") or "balanced"),
        "rate_preset": str(source.get("rate_preset") or "standard"),
        "preset_overrides": dict(source.get("preset_overrides") or {}),
        "challenge_mode": str(source.get("challenge_mode") or "managed"),
        "policy_version": int(source.get("policy_version") or 0),
        # Never inferred and never defaulted true. There is one honest value this system can
        # write, and V188 CHECKs the consequences of the other one being false.
        "edge_attached": bool(source.get("edge_attached", False)),
        "edge_provider": source.get("edge_provider"),
        "managed_off_reason": source.get("managed_off_reason"),
    }


def normalize_exception(exception: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce an exception row into the canonical shape evaluation assumes.

    Args:
        exception: A ``slate_security_exceptions`` row or request body.

    Returns:
        A new dict with every field present. ``expires_at`` is left as given, including ``None``,
        so :func:`evaluate_exception_safety` can refuse a missing expiry rather than inventing
        one.
    """
    return {
        "id": str(exception.get("id") or ""),
        "subject_kind": str(exception.get("subject_kind") or "policy"),
        "subject_ref": str(exception.get("subject_ref") or ""),
        "matcher_kind": str(exception.get("matcher_kind") or "prefix"),
        "matcher_value": (
            ""
            if exception.get("matcher_value") is None
            else str(exception.get("matcher_value"))
        ),
        # An exception carries no method or host scope in V188, so it applies to every method on
        # every host within its route scope. Modelling that explicitly here keeps matches_route
        # usable for exceptions and rules alike.
        "matcher_methods": [],
        "matcher_hosts": [],
        "expires_at": exception.get("expires_at"),
        "reason": str(exception.get("reason") or ""),
        "created_at": exception.get("created_at"),
    }


# ─── Matching ─────────────────────────────────────────────────────────────────


def _matcher_compiles(rule: Mapping[str, Any]) -> bool:
    """Whether a rule's matcher can be evaluated at all.

    Args:
        rule: A normalized rule or exception.

    Returns:
        False for an empty pattern, an unknown matcher kind, or a regex that does not compile.
        A matcher that cannot be evaluated is refused rather than treated as matching nothing:
        a security rule that silently never fires is worse than one that never existed, because
        somebody believes it is there.
    """
    value = rule["matcher_value"]
    if not value:
        return False
    if rule["matcher_kind"] not in MATCHER_KINDS:
        return False
    if rule["matcher_kind"] == "regex":
        try:
            re.compile(value)
        except re.error:
            return False
    return True


def matches_route(rule: Mapping[str, Any], request: "SimulationRequest") -> bool:
    """Whether a rule's matcher selects this request.

    Prefix matching is textual rather than segment-aware, exactly as
    :func:`app.slate_cache.matches_route` does it, so ``/docs`` also selects ``/docsearch``. An
    operator who means the section writes ``/docs/``. Keeping the two surfaces identical matters
    more than the alternative reading: a matcher that meant different things on the cache and
    security screens would eventually be copied from one to the other.

    An empty ``matcher_methods`` means every method, and an empty ``matcher_hosts`` means every
    host, both per V188.

    Args:
        rule: A normalized rule or exception.
        request: A normalized request.

    Returns:
        True when method, host and path all match. A regex that does not compile matches nothing
        rather than raising: the rule write already refused it, and a simulation over stored
        policy should still render.
    """
    if rule["matcher_methods"] and request.method not in rule["matcher_methods"]:
        return False
    if rule["matcher_hosts"] and request.host not in rule["matcher_hosts"]:
        return False

    kind = rule["matcher_kind"]
    value = rule["matcher_value"]
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


def covers_everything(rule: Mapping[str, Any]) -> bool:
    """Whether a matcher selects every route on the lane.

    This is the load-bearing predicate behind the ``blocks-entire-site`` refusal, so it errs
    towards saying yes. A pattern this function calls total is refused for a blocking rule; the
    cost of a false positive is an operator narrowing a matcher that was already narrow enough,
    and the cost of a false negative is a lane nobody can open — including the operator who would
    remove the rule.

    Host scoping does not narrow this. A rule limited to one host still blocks every route on
    that host, and a single-host lane is the ordinary case.

    Args:
        rule: A normalized rule or exception.

    Returns:
        True when no request path could avoid the matcher. Always False for ``exact``, which
        selects exactly one path by construction.
    """
    kind = rule["matcher_kind"]
    value = rule["matcher_value"].strip()

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
        # That covers ".*", "", "(?:)" and the anchored variants at once, without this function
        # having to enumerate the ways of writing "anything".
        try:
            compiled = re.compile(value)
        except re.error:
            return False
        return compiled.search("") is not None or compiled.search("/") is not None
    return False


def _path_segments(matcher_value: str) -> int:
    """How many path segments a matcher pins down.

    Args:
        matcher_value: The rule's route pattern.

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

    Only the cases that can be decided cheaply and certainly are reported. A prefix strictly
    containing another prefix is one; comparing two regexes is not, and guessing would produce a
    warning an operator cannot act on.

    Args:
        outer: The higher-precedence rule.
        inner: The rule that may be unreachable.

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
    if outer["matcher_methods"] and not set(inner["matcher_methods"] or list(_ALL_METHODS)).issubset(
        set(outer["matcher_methods"])
    ):
        return False
    return inner["matcher_value"].startswith(outer["matcher_value"])


#: The methods an empty ``matcher_methods`` stands for, used only when comparing two rules'
#: method scopes. Kept as a literal so the comparison is decidable rather than open-ended.
_ALL_METHODS = ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT")


# ─── Safety evaluation ────────────────────────────────────────────────────────


def evaluate_security_safety(
    rule: Mapping[str, Any],
    *,
    siblings: Sequence[Mapping[str, Any]] = (),
    policy: Optional[Mapping[str, Any]] = None,
) -> List[SecurityWarning]:
    """Check a rule for conditions that would lock readers out, or that merely deserve a sentence.

    This is the authority behind acceptance criteria 2 and 3. The UI renders what this returns
    and what :class:`SlateSecurityRefusedError` carries; it does not classify rules itself,
    because two copies of this policy would eventually disagree and the one that disagreed
    silently would be the one governing production.

    Args:
        rule: The rule to check, normalized or raw.
        siblings: Other rules on the lane. Used for the precedence conflict refusal and the
            shadowing warning; a rule sharing this rule's id is skipped, so re-checking a stored
            rule against its own lane does not report it as conflicting with itself.
        policy: The lane's policy row, when there is one. Only ``challenge_mode`` is consulted:
            when challenges are off entirely, a challenging rule cannot cost search visibility
            and the crawlable-route warning would be noise. Everything else about the policy is
            evaluated by :func:`evaluate_policy_safety`, so an unrelated rule edit is not refused
            because of a policy-level problem it did not cause.

    Returns:
        Warnings that do not block the write. Acknowledged warnings are still returned; the
        caller decides whether an acknowledgement is on file.

    Raises:
        SlateSecurityRefusedError: On any condition in :data:`_HARD_REFUSALS` reachable from a
            rule body — a lockout, a rule reaching enforce unreviewed or unsimulated, a budget
            below what reading costs, a broken matcher, or a precedence collision.
    """
    normalized = normalize_rule(rule)
    resolved_policy = normalize_policy(policy)

    # A matcher that cannot be evaluated comes first: every check below reasons about what the
    # matcher covers, and reasoning about a pattern that will never compile is meaningless.
    if not _matcher_compiles(normalized):
        raise SlateSecurityRefusedError(SecurityRefusal.of("matcher-invalid"))

    acts = normalized["action"] in _DENYING_ACTIONS
    enforcing = normalized["rollout_mode"] == "enforce" and normalized["rollout_percent"] > 0

    # Lockouts first. These are refused for the rule as written, whatever its rollout, because a
    # rule that covers the whole site is a rule somebody will eventually promote to enforce, and
    # the moment they do there is no request left with which to undo it.
    if normalized["action"] == "block" and covers_everything(normalized):
        raise SlateSecurityRefusedError(SecurityRefusal.of("blocks-entire-site"))
    if acts and _hits_documentation_root(normalized):
        raise SlateSecurityRefusedError(SecurityRefusal.of("blocks-documentation-root"))

    if normalized["action"] == "rate-limit" and _below_rate_floor(normalized):
        raise SlateSecurityRefusedError(SecurityRefusal.of("rate-limit-below-floor"))

    # Staged rollout is only a guarantee if the stages cannot be skipped. Both of these apply to
    # the acting rule and not to the simulate-mode one, which is the point: simulate is the
    # cheap, always-available step, and reaching enforce is the deliberate one.
    if enforcing and acts and normalized["simulated_at"] is None:
        raise SlateSecurityRefusedError(SecurityRefusal.of("enforce-without-simulation"))
    if enforcing and normalized["action"] == "block":
        evaluate_approval_safety(
            author_actor_key=normalized["author_actor_key"],
            approvals=normalized["approvals"],
            digest=body_digest(normalized),
        )

    for sibling in siblings:
        other = normalize_rule(sibling)
        if other["id"] and other["id"] == normalized["id"]:
            continue
        if other["ordinal"] == normalized["ordinal"]:
            raise SlateSecurityRefusedError(SecurityRefusal.of("ordinal-conflict"))

    warnings: List[SecurityWarning] = []
    if acts and _path_segments(normalized["matcher_value"]) <= _BROAD_MATCHER_MAX_SEGMENTS:
        warnings.append(SecurityWarning.of("broad-matcher", field="matcher_value"))
    if (
        normalized["action"] == "challenge"
        and resolved_policy["challenge_mode"] != "off"
        and _is_crawlable(normalized)
    ):
        warnings.append(SecurityWarning.of("challenge-on-crawlable-route", field="action"))
    if (
        normalized["rollout_percent"] == 100
        and normalized["previous_rollout_percent"] == 0
        and acts
    ):
        warnings.append(SecurityWarning.of("rollout-jump", field="rollout_percent"))
    if normalized["expires_at"] is None and acts:
        warnings.append(SecurityWarning.of("expiry-missing", field="expires_at"))

    for sibling in siblings:
        other = normalize_rule(sibling)
        if other["id"] and other["id"] == normalized["id"]:
            continue
        if not other["enabled"]:
            continue
        # Only a rule that decides can shadow one. A log rule matches and then steps aside, so a
        # rule behind it is still reachable.
        if other["action"] == "log":
            continue
        if other["ordinal"] < normalized["ordinal"] and _covers(other, normalized):
            warnings.append(SecurityWarning.of("rule-shadowed", field="ordinal"))
            break

    return warnings


def _hits_documentation_root(rule: Mapping[str, Any]) -> bool:
    """Whether an acting rule would catch the site's entry point.

    Args:
        rule: A normalized rule.

    Returns:
        True when any route in :data:`_DOCUMENTATION_ROOTS` is selected by the matcher. A rule
        that covers everything necessarily covers the root, so this is also the path by which a
        site-wide ``challenge`` — which ``blocks-entire-site`` deliberately does not catch, since
        that refusal is scoped to ``block`` — is still refused.
    """
    for root in _DOCUMENTATION_ROOTS:
        probe = SimulationRequest(path=root)
        if matches_route(rule, probe):
            return True
    return False


def _is_crawlable(rule: Mapping[str, Any]) -> bool:
    """Whether a rule's routes are the kind a search engine indexes.

    Args:
        rule: A normalized rule.

    Returns:
        True for rules scoped to GET or HEAD, or to no method at all. A crawler issues no other
        method, so a rule restricted to POST cannot cost search visibility however broad it is.
    """
    methods = set(rule["matcher_methods"])
    if not methods:
        return True
    return bool(methods & {"GET", "HEAD"})


def _below_rate_floor(rule: Mapping[str, Any]) -> bool:
    """Whether a rate budget would trip on ordinary reading.

    The comparison is normalized to a per-minute rate so that a budget expressed over an hour and
    one expressed over ten seconds are judged by the same standard — otherwise the window becomes
    a way of writing a punishing limit that passes the check.

    Args:
        rule: A normalized rule with ``action`` of ``rate-limit``.

    Returns:
        True when the effective budget is below :data:`_RATE_FLOOR_REQUESTS_PER_MINUTE`. A rule
        with no budget at all is also below the floor: V188 forbids that combination, and
        treating a missing budget as unlimited here would let it through the one check that would
        have noticed.
    """
    requests = rule["rate_requests"]
    window = rule["rate_window_seconds"]
    if not requests or not window:
        return True
    return (requests * 60.0 / window) < _RATE_FLOOR_REQUESTS_PER_MINUTE


def evaluate_policy_safety(policy: Mapping[str, Any]) -> List[SecurityWarning]:
    """Check a policy row for changes that remove protection without accounting for it.

    Kept separate from :func:`evaluate_security_safety` deliberately. A policy-level problem must
    not refuse an unrelated rule edit — an operator narrowing a matcher during an incident should
    not be blocked by a managed ruleset somebody else turned off an hour ago.

    Args:
        policy: A ``slate_security_policies`` row or request body.

    Returns:
        Warnings that do not block the write. Empty today; the return type is stated so a future
        policy-level concern has somewhere to go that is not a refusal.

    Raises:
        SlateSecurityRefusedError: When the managed ruleset is off with no stated reason. V188
            CHECKs the same thing, so this is the sentence rather than the enforcement — but an
            operator should meet the explanation, not a constraint violation.
    """
    resolved = normalize_policy(policy)
    if resolved["managed_ruleset"] == "off" and not str(
        resolved["managed_off_reason"] or ""
    ).strip():
        raise SlateSecurityRefusedError(SecurityRefusal.of("managed-off-without-reason"))
    return []


def evaluate_exception_safety(
    exception: Mapping[str, Any], *, now: datetime
) -> List[SecurityWarning]:
    """Check a carve-out for the two ways an exception stops being one.

    An exception is a hole in the policy. §29.4 wants them possible; keeping them scoped and
    bounded is what stops them becoming the policy, so both refusals here are hard and neither
    has an acknowledgement path.

    Args:
        exception: The exception to check, normalized or raw.
        now: Evaluation time, injected rather than read, so the same exception judged against the
            same instant always produces the same verdict.

    Returns:
        Warnings that do not block the write.

    Raises:
        SlateSecurityRefusedError: When the matcher does not compile, when the exception covers
            every route or has no expiry, or when it would outlive
            :data:`_MAX_EXCEPTION_WINDOW_DAYS`.
    """
    normalized = normalize_exception(exception)

    if not _matcher_compiles(normalized):
        raise SlateSecurityRefusedError(SecurityRefusal.of("matcher-invalid"))
    if covers_everything(normalized):
        raise SlateSecurityRefusedError(SecurityRefusal.of("exception-unbounded"))

    expires_at = _as_datetime(normalized["expires_at"], now)
    if expires_at is None:
        raise SlateSecurityRefusedError(SecurityRefusal.of("exception-unbounded"))
    if expires_at > now + timedelta(days=_MAX_EXCEPTION_WINDOW_DAYS):
        raise SlateSecurityRefusedError(SecurityRefusal.of("exception-outlives-limit"))

    return []


def evaluate_approval_safety(
    *,
    author_actor_key: str,
    approvals: Sequence[Mapping[str, Any]],
    digest: str,
) -> None:
    """Check that a change carries a genuine second-person approval of this exact body.

    Two failures are distinguished on purpose, because they need different actions. An approval
    of a different body means the change was re-edited after review and has to go back; an
    approval by the author means nobody else has looked at it yet.

    Args:
        author_actor_key: Immutable identity of whoever proposed the change. V188 compares these
            keys rather than the nullable user ids, because those are ``ON DELETE SET NULL`` and
            a constraint that weakens when somebody is offboarded is not a constraint.
        approvals: Recorded approvals, each carrying ``approver_actor_key`` and ``digest``.
        digest: The body digest actually being written, from :func:`body_digest`.

    Returns:
        None. This function communicates only by raising, so a caller cannot mistake a falsy
        return for approval.

    Raises:
        SlateSecurityRefusedError: ``approval-self`` when the only approvals are the author's,
            ``enforce-without-approval`` when there are none at all, and ``approval-stale`` when
            an approval exists but names a different body.
    """
    if not approvals:
        raise SlateSecurityRefusedError(SecurityRefusal.of("enforce-without-approval"))

    distinct = [
        approval
        for approval in approvals
        if str(approval.get("approver_actor_key") or "") != author_actor_key
    ]
    if not distinct:
        raise SlateSecurityRefusedError(SecurityRefusal.of("approval-self"))

    if not any(str(approval.get("digest") or "") == digest for approval in distinct):
        raise SlateSecurityRefusedError(SecurityRefusal.of("approval-stale"))


# ─── Simulation ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SimulationRequest:
    """The test request a simulation is evaluated against.

    The three signal fields are what make a WAF simulation deterministic without a detection
    engine. There is no inspector in the request path, so this module cannot decide for itself
    whether a payload looks like SQL injection. Instead the caller states which detections the
    request is meant to trip, and the simulation answers what the *policy* does about them. That
    is a smaller claim than "this request is malicious", and it is the one that is actually true.

    Attributes:
        method: HTTP method, upper-cased by :meth:`normalized`.
        host: Request host, lower-cased.
        path: Request path.
        query: Query parameters, as a mapping of name to value.
        signals: Catalog ids of the managed groups this request should be treated as tripping.
        bot_class: How the request is classified: ``human``, ``verified-bot``,
            ``likely-automated`` or ``automated``.
        burst_requests: How many requests this client prefix has made in the rate window, used to
            decide whether a rate budget is exceeded. Zero means the question does not arise.
        country: Source country, for a rule condition.
        asn: Source autonomous system number, for a rule condition.
        headers: Request headers, lower-cased by :meth:`normalized`.
    """

    method: str = "GET"
    host: str = ""
    path: str = "/"
    query: Mapping[str, str] = field(default_factory=dict)
    signals: Tuple[str, ...] = ()
    bot_class: str = "human"
    burst_requests: int = 0
    country: str = ""
    asn: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)

    def normalized(self) -> "SimulationRequest":
        """Return a copy with case normalized the way HTTP defines it.

        Returns:
            A new :class:`SimulationRequest`; the original is untouched.
        """
        return SimulationRequest(
            method=self.method.upper(),
            host=self.host.lower(),
            path=self.path or "/",
            query=dict(self.query),
            signals=tuple(sorted({str(s) for s in self.signals})),
            bot_class=self.bot_class.lower(),
            burst_requests=int(self.burst_requests or 0),
            country=self.country.upper(),
            asn=str(self.asn or ""),
            headers={k.lower(): v for k, v in self.headers.items()},
        )


@dataclass(frozen=True)
class SimulationVerdict:
    """What a policy decides for one request, and why every other rule did not decide it.

    One field per clause of the acceptance criteria, so a partially-answered simulation is a type
    error rather than a subtle omission.

    ``enforced``, ``observed`` and ``mitigated`` are the honesty boundary in structural form.
    :func:`simulate_request` sets all three to ``False`` unconditionally and there is no argument
    by which a caller can change them, mirroring the way V188 CHECKs make the corresponding
    columns impossible to overstate. ``basis`` is ``policy-simulation`` for the same reason.

    Attributes:
        action: What the policy decided, one of :data:`EVENT_ACTIONS`. A simulate-mode rule that
            would block reports ``would-block``; nothing here reports ``blocked``.
        action_reason: One sentence naming both the outcome and what produced it.
        winning_rule_kind: ``rule``, ``managed-group``, ``bot-preset``, ``rate-preset`` or
            ``default`` when nothing decided.
        winning_rule_ref: Rule id or catalog id of whatever decided, or ``None``.
        winning_rule_label: Operator-facing name of whatever decided.
        rollout_mode: The rollout mode of the deciding rule, or ``enforce`` for managed coverage,
            which has no staged rollout of its own.
        exception_applied: The exception that suppressed the decision, when one did.
        considered: Every rule, group and preset that was evaluated, in evaluation order, each
            with an outcome of ``matched``, ``skipped`` or ``not-reached`` and a sentence.
        warnings: Concerns about the deciding rule, as dicts the REST layer serializes directly.
        enforced: Always ``False``. No delivery tier is attached, so nothing acted.
        observed: Always ``False``. This is a simulation of policy, not a request that happened.
        mitigated: Always ``False``. Nothing was stopped, because nothing can be.
        basis: Always ``policy-simulation``, matching ``slate_security_events.source``.
        rules_digest: The digest of the ruleset that produced this verdict, so a simulation can
            be reproduced from its recorded inputs or explained by having drifted from them.
    """

    action: str
    action_reason: str
    winning_rule_kind: str
    winning_rule_ref: Optional[str]
    winning_rule_label: str
    rollout_mode: str
    exception_applied: Optional[Dict[str, str]]
    considered: List[Dict[str, Any]]
    warnings: List[Dict[str, str]]
    enforced: bool
    observed: bool
    mitigated: bool
    basis: str
    rules_digest: str


#: What each rule action reports when it wins and is actually enforcing.
_ACTION_OUTCOMES: Mapping[str, str] = {
    "allow": "allowed",
    "log": "logged",
    "challenge": "challenged",
    "rate-limit": "rate-limited",
    "block": "blocked",
}


def simulate_request(
    *,
    request: SimulationRequest,
    policy: Optional[Mapping[str, Any]],
    managed_groups: Sequence[Mapping[str, Any]] = (),
    rules: Sequence[Mapping[str, Any]] = (),
    exceptions: Sequence[Mapping[str, Any]] = (),
    now: datetime,
) -> SimulationVerdict:
    """Explain what this policy would decide for this request, and why each rule did not.

    No I/O, no clock and no randomness: ``now`` is injected the way
    :func:`app.slate_cache.evaluate_trace` injects it, so a simulation is reproducible from its
    recorded inputs. **Every** rule is reported — a rule that lost says why, because "why did my
    rule not fire", or worse "which rule blocked this customer", is the question a simulation
    exists to answer.

    Evaluation order is custom rules, then managed groups, then the bot preset, then the rate
    preset. Custom rules run first because ``allow`` is an early exit, and an early exit that
    could not pre-empt the managed ruleset would not be able to express a carve-out — which is
    the whole reason V188 gives the action that meaning. A ``log`` rule matches, records itself,
    and steps aside rather than deciding.

    Rollout is applied deterministically rather than sampled. A rule at 0% reaches no traffic and
    is reported as skipped; a rule above 0% is evaluated as though this request falls inside its
    cohort, and the sentence says so. Sampling here would make the same inputs produce different
    answers, which is exactly what a simulation must not do.

    Args:
        request: The test request.
        policy: The lane's policy row, or ``None`` for shipped defaults.
        managed_groups: Per-environment group overrides. Any group not listed runs in its
            catalog mode under the lane's managed ruleset tier.
        rules: The lane's custom rules, in any order; they are sorted here by ``(ordinal, id)``.
        exceptions: The lane's carve-outs. Expired ones are reported as skipped rather than
            silently ignored.
        now: Evaluation time, for rule and exception expiry.

    Returns:
        The verdict: what the policy decided, what decided it, and one sentence for every rule,
        group and preset that did not.
    """
    normalized_request = request.normalized()
    resolved_policy = normalize_policy(policy)
    active_exceptions = _active_exceptions(exceptions, normalized_request, now)

    considered: List[Dict[str, Any]] = []
    decision: Optional[Dict[str, Any]] = None

    decision = _consider_custom_rules(
        rules=rules,
        request=normalized_request,
        exceptions=active_exceptions,
        now=now,
        considered=considered,
    )
    if decision is None:
        decision = _consider_managed_groups(
            policy=resolved_policy,
            overrides=managed_groups,
            request=normalized_request,
            exceptions=active_exceptions,
            considered=considered,
        )
    else:
        _record_unreached_managed(resolved_policy, managed_groups, decision, considered)

    if decision is None:
        decision = _consider_bot_preset(
            policy=resolved_policy, request=normalized_request, considered=considered
        )
    if decision is None:
        decision = _consider_rate_preset(
            policy=resolved_policy, request=normalized_request, considered=considered
        )

    if decision is None:
        decision = {
            "kind": "default",
            "ref": None,
            "label": "No rule matched",
            "action": "allowed",
            "rollout_mode": "enforce",
            "reason": (
                "No custom rule, managed group or preset selected this request, so the policy "
                "leaves it alone."
            ),
            "exception": None,
            "rule": None,
        }

    warnings: List[Dict[str, str]] = []
    if decision["rule"] is not None:
        try:
            for warning in evaluate_security_safety(
                decision["rule"], siblings=rules, policy=policy
            ):
                warnings.append(
                    {
                        "code": warning.code,
                        "message": warning.message,
                        "field": warning.field or "",
                    }
                )
        except SlateSecurityRefusedError as exc:
            # A stored rule can become unsafe when the policy around it changes, or can predate a
            # refusal this module later added. The simulation reports that rather than refusing
            # to render: an operator investigating a block needs to see the verdict, and a
            # simulation is a read.
            warnings.append(
                {"code": exc.refusal.reason, "message": exc.refusal.sentence, "field": "action"}
            )

    return SimulationVerdict(
        action=decision["action"],
        action_reason=decision["reason"],
        winning_rule_kind=decision["kind"],
        winning_rule_ref=decision["ref"],
        winning_rule_label=decision["label"],
        rollout_mode=decision["rollout_mode"],
        exception_applied=decision["exception"],
        considered=considered,
        warnings=warnings,
        # Set here, never taken from an argument. A caller cannot make this response claim an
        # enforcement, an observation or a mitigation, because there is no parameter with which
        # to ask for one.
        enforced=False,
        observed=False,
        mitigated=False,
        basis="policy-simulation",
        rules_digest=rules_digest(rules),
    )


def _active_exceptions(
    exceptions: Sequence[Mapping[str, Any]], request: SimulationRequest, now: datetime
) -> List[Dict[str, Any]]:
    """Select the carve-outs that apply to this request at this instant.

    Args:
        exceptions: The lane's exceptions, in any order.
        request: A normalized request.
        now: Evaluation time.

    Returns:
        Normalized exceptions that have not expired and whose matcher selects the request,
        sorted by id so the one reported is stable across calls.
    """
    active: List[Dict[str, Any]] = []
    for exception in exceptions:
        normalized = normalize_exception(exception)
        if _expired(normalized["expires_at"], now):
            continue
        if not matches_route(normalized, request):
            continue
        active.append(normalized)
    active.sort(key=lambda e: e["id"])
    return active


def _exception_for(
    exceptions: Sequence[Mapping[str, Any]], *, subject_kind: str, subject_ref: str
) -> Optional[Dict[str, Any]]:
    """The first carve-out covering a given subject, if any.

    Args:
        exceptions: Already-filtered active exceptions.
        subject_kind: ``managed-group`` or ``rule``.
        subject_ref: The catalog id or rule id being evaluated.

    Returns:
        The exception that suppresses this subject, or ``None``. A ``policy``-scoped exception
        covers every subject, which is why it is checked alongside the specific ones.
    """
    for exception in exceptions:
        if exception["subject_kind"] == "policy":
            return exception
        if exception["subject_kind"] == subject_kind and exception["subject_ref"] == subject_ref:
            return exception
    return None


def _exception_summary(exception: Mapping[str, Any]) -> Dict[str, str]:
    """Reduce an exception to the fields a verdict reports.

    Args:
        exception: A normalized exception.

    Returns:
        Id, subject, matcher and reason, as strings the REST layer can serialize directly.
    """
    return {
        "id": exception["id"],
        "subject_kind": exception["subject_kind"],
        "subject_ref": exception["subject_ref"],
        "matcher": f"{exception['matcher_kind']} {exception['matcher_value']}",
        "reason": exception["reason"],
    }


def _consider_custom_rules(
    *,
    rules: Sequence[Mapping[str, Any]],
    request: SimulationRequest,
    exceptions: Sequence[Mapping[str, Any]],
    now: datetime,
    considered: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Evaluate the lane's custom rules in precedence order, recording every one.

    Args:
        rules: The lane's custom rules, in any order.
        request: A normalized request.
        exceptions: Active exceptions for this request.
        now: Evaluation time, for rule expiry.
        considered: Accumulator, appended to in evaluation order.

    Returns:
        The decision a rule reached, or ``None`` when no rule decided.
    """
    ordered = sorted(
        (normalize_rule(rule) for rule in rules), key=lambda r: (r["ordinal"], r["id"])
    )
    decision: Optional[Dict[str, Any]] = None

    for rule in ordered:
        entry: Dict[str, Any] = {
            "kind": "rule",
            "ref": rule["id"] or None,
            "label": rule["label"],
            "ordinal": rule["ordinal"],
        }
        if decision is not None:
            entry["outcome"] = "not-reached"
            entry["action"] = None
            entry["reason"] = (
                f"Not reached: rule {decision['ordinal']} \"{decision['label']}\" already "
                "decided this request."
            )
            considered.append(entry)
            continue

        skip_reason = _rule_skip_reason(rule, request, exceptions, now)
        if skip_reason is not None:
            entry["outcome"] = "skipped"
            entry["action"] = None
            entry["reason"] = skip_reason
            considered.append(entry)
            continue

        outcome_action = _rollout_action(rule)
        entry["outcome"] = "matched"
        entry["action"] = outcome_action
        entry["reason"] = _rule_match_sentence(rule, request, outcome_action)
        considered.append(entry)

        # A log rule observes and steps aside; everything else decides. That is what makes "log
        # first, then enforce" a usable rollout path rather than a rule that quietly shadows the
        # ones behind it.
        if rule["action"] == "log":
            continue

        decision = {
            "kind": "rule",
            "ref": rule["id"] or None,
            "label": rule["label"],
            "ordinal": rule["ordinal"],
            "action": outcome_action,
            "rollout_mode": rule["rollout_mode"],
            "reason": entry["reason"],
            "exception": None,
            "rule": rule,
        }

    return decision


def _rule_skip_reason(
    rule: Mapping[str, Any],
    request: SimulationRequest,
    exceptions: Sequence[Mapping[str, Any]],
    now: datetime,
) -> Optional[str]:
    """Why a rule did not participate in this request, as a sentence.

    Args:
        rule: A normalized rule.
        request: A normalized request.
        exceptions: Active exceptions for this request.
        now: Evaluation time.

    Returns:
        A sentence, or ``None`` when the rule participates. Checks run cheapest-and-most-decisive
        first so the sentence an operator reads is the most useful one: being disabled explains
        more than not matching.
    """
    if not rule["enabled"]:
        return "Disabled."
    if _expired(rule["expires_at"], now):
        return f"Expired at {rule['expires_at']}."
    if rule["rollout_percent"] == 0:
        return (
            "At 0% rollout this rule reaches no traffic, so it cannot apply to any request "
            "including this one."
        )
    if not matches_route(rule, request):
        return (
            f"Matcher {rule['matcher_kind']} \"{rule['matcher_value']}\" does not match "
            f"{request.method} {request.path}."
        )
    unmet = _unmet_condition(rule, request)
    if unmet is not None:
        return f"Matched the route but not the condition: {unmet}."
    exception = _exception_for(exceptions, subject_kind="rule", subject_ref=rule["id"])
    if exception is not None:
        return (
            f"Suppressed by exception {exception['id'] or '(unsaved)'} covering "
            f"{exception['matcher_kind']} \"{exception['matcher_value']}\": {exception['reason']}"
        )
    return None


def _unmet_condition(rule: Mapping[str, Any], request: SimulationRequest) -> Optional[str]:
    """The first non-route predicate this request fails, as a phrase.

    V188 stores conditions as a JSON list of heterogeneous predicates precisely so the simulation
    can name which one failed. A predicate of an unrecognized kind is treated as unmet rather
    than as satisfied: an unknown condition on a blocking rule should narrow it, not widen it.

    Args:
        rule: A normalized rule.
        request: A normalized request.

    Returns:
        A phrase naming the failed predicate, or ``None`` when every predicate holds.
    """
    for condition in rule["conditions"]:
        if not isinstance(condition, Mapping):
            return "a malformed condition entry"
        kind = str(condition.get("kind") or "")
        equals = condition.get("equals")
        name = str(condition.get("name") or "")

        if kind == "country":
            if request.country != str(equals or "").upper():
                return f"country is {request.country or 'unset'}, not {equals}"
        elif kind == "asn":
            if request.asn != str(equals or ""):
                return f"ASN is {request.asn or 'unset'}, not {equals}"
        elif kind == "bot-class":
            if request.bot_class != str(equals or "").lower():
                return f"bot class is {request.bot_class}, not {equals}"
        elif kind == "header":
            lowered = name.lower()
            if lowered not in request.headers:
                return f"header {name} is absent"
            if equals is not None and request.headers[lowered] != str(equals):
                return f"header {name} is not {equals}"
        elif kind == "query":
            if name not in request.query:
                return f"query parameter {name} is absent"
            if equals is not None and request.query[name] != str(equals):
                return f"query parameter {name} is not {equals}"
        else:
            return f"condition kind \"{kind}\" is not one this evaluator understands"
    return None


def _rollout_action(rule: Mapping[str, Any]) -> str:
    """What a matching rule reports, given its rollout mode.

    This is the single place the honesty boundary of a staged rollout lives. A rule in
    ``simulate`` that would deny reports ``would-block`` and never the acting outcome, so the
    event stream cannot be read as a record of requests that were stopped.

    Args:
        rule: A normalized rule that matched.

    Returns:
        One of :data:`EVENT_ACTIONS`.
    """
    acting = _ACTION_OUTCOMES.get(rule["action"], "logged")
    if rule["rollout_mode"] == "simulate" and rule["action"] in _DENYING_ACTIONS:
        return "would-block"
    return acting


def _rule_match_sentence(
    rule: Mapping[str, Any], request: SimulationRequest, outcome_action: str
) -> str:
    """Explain in one sentence what a matching rule did and under what rollout.

    Args:
        rule: A normalized rule that matched.
        request: A normalized request.
        outcome_action: The action from :func:`_rollout_action`.

    Returns:
        A sentence naming the rule, the route and the rollout, phrased so a simulated denial
        cannot be misread as a real one.
    """
    scope = (
        "at full rollout"
        if rule["rollout_percent"] == 100
        else f"at {rule['rollout_percent']}% rollout, and this request is treated as in scope"
    )
    if outcome_action == "would-block":
        return (
            f"Rule {rule['ordinal']} \"{rule['label']}\" matched {request.method} "
            f"{request.path} and is in simulate mode, so it records what it would have done "
            f"({rule['action']}) and acts on nothing — {scope}."
        )
    return (
        f"Rule {rule['ordinal']} \"{rule['label']}\" matched {request.method} {request.path} "
        f"and decided {outcome_action} — {scope}."
    )


def _effective_group_modes(
    policy: Mapping[str, Any], overrides: Sequence[Mapping[str, Any]]
) -> List[Tuple[str, str, Optional[str]]]:
    """Resolve the catalog and the lane's overrides into one ordered list of group modes.

    Args:
        policy: A normalized policy.
        overrides: Rows from ``slate_security_managed_groups``.

    Returns:
        One tuple of ``(group_id, mode, override_reason)`` per group in the managed tier, in
        catalog order so the evaluation order is the same on every call. An override for a group
        the tier does not include is ignored: the tier decides what runs, and the override table
        only records deviations within it.
    """
    tier = MANAGED_RULESETS.get(policy["managed_ruleset"], MANAGED_RULESETS["core"])
    by_group = {
        str(row.get("group_id") or ""): row for row in overrides if row.get("group_id") is not None
    }

    resolved: List[Tuple[str, str, Optional[str]]] = []
    for group_id in tier.groups:
        override = by_group.get(group_id)
        if override is not None:
            resolved.append((group_id, str(override.get("mode") or "off"), override.get("reason")))
        else:
            resolved.append((group_id, tier.group_modes.get(group_id, "off"), None))
    return resolved


def _consider_managed_groups(
    *,
    policy: Mapping[str, Any],
    overrides: Sequence[Mapping[str, Any]],
    request: SimulationRequest,
    exceptions: Sequence[Mapping[str, Any]],
    considered: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Evaluate the managed WAF groups this lane runs, recording every one.

    A group acts only when the request declares its signal. There is nothing in the request path
    to inspect a payload, so the simulation answers "what does this policy do about a request
    that trips this detection" rather than pretending to be the detector.

    Args:
        policy: A normalized policy.
        overrides: Per-environment group mode overrides.
        request: A normalized request.
        exceptions: Active exceptions for this request.
        considered: Accumulator, appended to in evaluation order.

    Returns:
        The decision a group reached, or ``None`` when none did.
    """
    decision: Optional[Dict[str, Any]] = None

    for group_id, mode, reason in _effective_group_modes(policy, overrides):
        group = MANAGED_GROUPS[group_id]
        entry: Dict[str, Any] = {
            "kind": "managed-group",
            "ref": group_id,
            "label": group.title,
            "ordinal": None,
        }
        if decision is not None:
            entry["outcome"] = "not-reached"
            entry["action"] = None
            entry["reason"] = (
                f"Not reached: managed group \"{decision['label']}\" already decided this "
                "request."
            )
            considered.append(entry)
            continue
        if mode == "off":
            entry["outcome"] = "skipped"
            entry["action"] = None
            entry["reason"] = (
                f"Turned off on this lane: {reason}"
                if reason
                else "Turned off on this lane."
            )
            considered.append(entry)
            continue
        if group_id not in request.signals:
            entry["outcome"] = "skipped"
            entry["action"] = None
            entry["reason"] = (
                f"This request does not trip {group.title.lower()} detection, so the group has "
                "nothing to act on."
            )
            considered.append(entry)
            continue

        exception = _exception_for(
            exceptions, subject_kind="managed-group", subject_ref=group_id
        )
        if exception is not None:
            entry["outcome"] = "skipped"
            entry["action"] = None
            entry["reason"] = (
                f"Suppressed by exception {exception['id'] or '(unsaved)'} covering "
                f"{exception['matcher_kind']} \"{exception['matcher_value']}\": "
                f"{exception['reason']}"
            )
            considered.append(entry)
            continue

        action = {"log": "logged", "challenge": "challenged", "block": "blocked"}.get(
            mode, "logged"
        )
        sentence = (
            f"Managed group \"{group.title}\" is in {mode} mode and this request trips its "
            f"detection on {request.path}, so the policy decided {action}."
        )
        entry["outcome"] = "matched"
        entry["action"] = action
        entry["reason"] = sentence
        considered.append(entry)

        if mode == "log":
            continue

        decision = {
            "kind": "managed-group",
            "ref": group_id,
            "label": group.title,
            "ordinal": None,
            "action": action,
            # Managed coverage has no staged rollout of its own; its stage is the group mode,
            # which the sentence above states in full.
            "rollout_mode": "enforce",
            "reason": sentence,
            "exception": None,
            "rule": None,
        }

    return decision


def _record_unreached_managed(
    policy: Mapping[str, Any],
    overrides: Sequence[Mapping[str, Any]],
    decision: Mapping[str, Any],
    considered: List[Dict[str, Any]],
) -> None:
    """Record every managed group a custom rule pre-empted.

    A group that never ran must still appear, with the reason it never ran. "Why did the WAF not
    catch this" is answered by seeing the ``allow`` rule that stopped evaluation, and that only
    works if the groups behind it are listed rather than omitted.

    Args:
        policy: A normalized policy.
        overrides: Per-environment group mode overrides.
        decision: The decision a custom rule already reached.
        considered: Accumulator, appended to in catalog order.
    """
    for group_id, _mode, _reason in _effective_group_modes(policy, overrides):
        considered.append(
            {
                "kind": "managed-group",
                "ref": group_id,
                "label": MANAGED_GROUPS[group_id].title,
                "ordinal": None,
                "outcome": "not-reached",
                "action": None,
                "reason": (
                    f"Not reached: rule {decision['ordinal']} \"{decision['label']}\" decided "
                    "this request before managed coverage was consulted."
                ),
            }
        )


def _consider_bot_preset(
    *,
    policy: Mapping[str, Any],
    request: SimulationRequest,
    considered: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Evaluate the lane's bot preset against this request's classification.

    Args:
        policy: A normalized policy.
        request: A normalized request.
        considered: Accumulator, appended to.

    Returns:
        The decision the preset reached, or ``None`` when it only logs or does nothing.
    """
    preset = BOT_PRESETS.get(policy["bot_preset"], BOT_PRESETS["balanced"])
    disposition = {
        "verified-bot": preset.verified_bots,
        "likely-automated": preset.likely_automated,
        "automated": preset.automated,
    }.get(request.bot_class)

    entry: Dict[str, Any] = {
        "kind": "bot-preset",
        "ref": preset.key,
        "label": f"{preset.label} bot preset",
        "ordinal": None,
    }

    if preset.key == "off" or disposition is None:
        entry["outcome"] = "skipped"
        entry["action"] = None
        entry["reason"] = (
            "Bot classification is off on this lane."
            if preset.key == "off"
            else (
                f"This request is classified {request.bot_class}, which the {preset.label} "
                "preset does not act on."
            )
        )
        considered.append(entry)
        return None

    if "Challenged" not in disposition:
        entry["outcome"] = "matched"
        entry["action"] = "logged" if preset.key == "monitor" else "allowed"
        entry["reason"] = (
            f"The {preset.label} bot preset classified this request {request.bot_class}: "
            f"{disposition.rstrip('.').lower()}."
        )
        considered.append(entry)
        return None

    sentence = (
        f"The {preset.label} bot preset classified this request {request.bot_class} and "
        "challenges that class."
    )
    entry["outcome"] = "matched"
    entry["action"] = "challenged"
    entry["reason"] = sentence
    considered.append(entry)

    return {
        "kind": "bot-preset",
        "ref": preset.key,
        "label": f"{preset.label} bot preset",
        "ordinal": None,
        "action": "challenged",
        "rollout_mode": "enforce",
        "reason": sentence,
        "exception": None,
        "rule": None,
    }


def _consider_rate_preset(
    *,
    policy: Mapping[str, Any],
    request: SimulationRequest,
    considered: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Evaluate the lane's rate preset against this request's declared burst.

    Args:
        policy: A normalized policy.
        request: A normalized request, whose ``burst_requests`` states how many requests the
            client prefix has already made in the window.
        considered: Accumulator, appended to.

    Returns:
        The decision the preset reached, or ``None`` when the budget is not exceeded.
    """
    preset = RATE_PRESETS.get(policy["rate_preset"], RATE_PRESETS["standard"])
    entry: Dict[str, Any] = {
        "kind": "rate-preset",
        "ref": preset.key,
        "label": f"{preset.label} rate preset",
        "ordinal": None,
    }

    if preset.requests <= 0:
        entry["outcome"] = "skipped"
        entry["action"] = None
        entry["reason"] = "Rate limiting is off on this lane."
        considered.append(entry)
        return None

    if request.burst_requests <= preset.requests:
        entry["outcome"] = "skipped"
        entry["action"] = None
        entry["reason"] = (
            f"This client has made {request.burst_requests} requests against a budget of "
            f"{preset.requests} per {preset.window_seconds}s, so the budget is not exceeded."
        )
        considered.append(entry)
        return None

    action = "logged" if preset.action == "log" else "rate-limited"
    sentence = (
        f"The {preset.label} rate preset budget of {preset.requests} requests per "
        f"{preset.window_seconds}s was exceeded at {request.burst_requests} requests, so the "
        f"policy decided {action}."
    )
    entry["outcome"] = "matched"
    entry["action"] = action
    entry["reason"] = sentence
    considered.append(entry)

    if preset.action == "log":
        return None

    return {
        "kind": "rate-preset",
        "ref": preset.key,
        "label": f"{preset.label} rate preset",
        "ordinal": None,
        "action": action,
        "rollout_mode": "enforce",
        "reason": sentence,
        "exception": None,
        "rule": None,
    }


# ─── Digests ──────────────────────────────────────────────────────────────────

#: The fields that decide what a rule does. Everything else — the label, the timestamps, the
#: revision counter, the acknowledgements — is metadata about the rule rather than behaviour, and
#: is excluded so renaming a rule does not invalidate an approval or a historical simulation.
_DECISIVE_RULE_FIELDS = (
    "ordinal",
    "enabled",
    "matcher_kind",
    "matcher_value",
    "matcher_methods",
    "matcher_hosts",
    "conditions",
    "action",
    "rate_requests",
    "rate_window_seconds",
    "rollout_mode",
    "rollout_percent",
    "expires_at",
)


def body_digest(rule: Mapping[str, Any]) -> str:
    """Content-address one rule body.

    This is what an approval names. An approval that named only a row id would still look valid
    after that row changed underneath it, so ``slate_security_approvals.digest`` stores the value
    this function produces and :func:`evaluate_approval_safety` compares against it. Changing any
    decisive field changes the digest and therefore invalidates the approval — which is the
    intended behaviour, because a re-edited rule has not been reviewed.

    Args:
        rule: A rule row or request body, normalized or raw.

    Returns:
        ``sha256:<64 hex chars>``, matching the CHECK constraint on
        ``slate_security_rules.body_digest``.
    """
    normalized = normalize_rule(rule)
    decisive = {key: normalized[key] for key in _DECISIVE_RULE_FIELDS}
    canonical = json.dumps(decisive, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def rules_digest(rules: Sequence[Mapping[str, Any]]) -> str:
    """Content-address an ordered ruleset.

    The determinism receipt: two simulations carrying the same digest and the same request must
    agree, and a simulation whose digest no longer matches the lane is *explained* by that fact
    rather than contradicted by it. Same instinct as ``slate_artifacts.content_digest`` —
    identity by content.

    Only enabled rules contribute, and only the fields that affect a decision. A disabled rule
    changes nothing about what the policy does, so including it would make an unrelated toggle
    appear to invalidate every recorded simulation.

    Args:
        rules: Rules in any order; they are normalized and sorted here.

    Returns:
        ``sha256:<64 hex chars>``.
    """
    decisive: List[Dict[str, Any]] = []
    for rule in rules:
        normalized = normalize_rule(rule)
        if not normalized["enabled"]:
            continue
        decisive.append({key: normalized[key] for key in _DECISIVE_RULE_FIELDS})
    # Sorted by (ordinal, matcher_value) rather than ordinal alone: V188's UNIQUE constraint
    # forbids ties on a saved lane, but this function is also called on unsaved bodies during a
    # preview, and an unstable sort there would produce two digests for one ruleset.
    decisive.sort(key=lambda r: (r["ordinal"], str(r["matcher_value"])))
    canonical = json.dumps(decisive, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ─── Time ─────────────────────────────────────────────────────────────────────


def _as_datetime(value: Any, now: datetime) -> Optional[datetime]:
    """Parse a timestamp into a datetime comparable with ``now``.

    Args:
        value: A datetime, an ISO-8601 string, or ``None``.
        now: Evaluation time, whose tzinfo a naive value adopts. Comparing a naive and an aware
            datetime raises, and a security check that raises on a timezone detail would fail in
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
        True when the rule or exception no longer applies. An absent or unparseable value is
        treated as not expired, so a bad timestamp cannot silently disable a rule an operator is
        relying on — the failure mode of this function is protection that stays on.
    """
    moment = _as_datetime(expires_at, now)
    if moment is None:
        return False
    return moment <= now
