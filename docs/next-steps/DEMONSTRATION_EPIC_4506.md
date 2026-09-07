# DEMONSTRATION — AGX-EPIC-3: Agent Identity, Quotas & Analytics

> **Written ahead of the recording.** Routes, control labels and outputs below come from the
> epic's acceptance criteria, not from a running build. Walk it once against the shipped UI and
> correct this file before you record.

| | |
|---|---|
| Epic | [AGX-EPIC-3 #4506](https://github.com/apiome/apiome/issues/4506) · umbrella [AGX #4503](https://github.com/apiome/apiome/issues/4503) |
| Wave | 5 — closes the Agent Experience MVP |
| Tickets | [3.1 #4537](https://github.com/apiome/apiome/issues/4537) · [3.3 #4539](https://github.com/apiome/apiome/issues/4539) · [3.2 #4538](https://github.com/apiome/apiome/issues/4538) · [3.4 #4540](https://github.com/apiome/apiome/issues/4540) |
| Builds on | AGX-2.1 proxy ✅ · CTG-2.3 / MTG-1.3 API-key scopes ✅ · OLO-5.x license tiers ✅ |
| Runtime | ~10 min, plus 20 min prep |
| Audience | whoever gets paged when something calls your API a hundred thousand times |
| The one beat | **Every agent call has a name, a limit, and a line in a ledger.** |

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | Two agents, two keys | The key *is* the identity, and it's scoped. | 2:00 |
| 2 | Each sees a different API | `tools/list` differs per key. | 1:45 |
| 3 | Run them, then look | Calls, tools, latency, errors — per agent. | 2:30 |
| 4 | Hit the quota | Refused, in a shape the agent understands. | 2:15 |
| 5 | Revoke one | Access ends mid-conversation. | 1:30 |

---

## PREP — before anyone is watching (~20 min)

**DO** — Complete the [AGX-EPIC-2](DEMONSTRATION_EPIC_4505.md) end state: a working toolset with
a stored upstream credential and an MCP client that can call it.

**DO** — Create **two agent keys** in prep, with different tool allowlists. Name them after real
things — `support-bot` and `analytics-agent` narrate far better than `key-1` and `key-2`.

**DO** — **Generate traffic before you record.** Act 3 shows charts, and charts need history. Run
a script that makes a few hundred calls across both keys, over a few hours if you can, including
some deliberate errors and a couple of slow calls. Empty charts are the single most common way an
analytics demo falls flat.

```bash
# run this the day before, not on stage
while true; do apiome-mcp-call get_pets --key "$SUPPORT_BOT_KEY"; sleep 2; done
```

**DO** — Set a **low daily cap** on one key so Act 4 can actually hit it. Confirm you can trip it
in under thirty seconds; adjust the cap in prep until you can.

**DO** — Full dry run.

---

## ACT 1 — Two agents, two keys (2:00)

**DO** — Go to <http://localhost:3000/ade/dashboard/api-keys>. Show the key list — and show that
agent keys are a **kind** alongside the existing key types, not a separate system.

**DO** — Open `support-bot`. Show the toolset binding, the tool allowlist, and the expiry.

**DO** — Open `analytics-agent`. Different allowlist — reads only, and fewer of them.

**SAY**

> Two agents, two keys, in the same key management surface your API keys already live in. There
> is one key authority in this platform, and agents did not get a second one — which matters the
> day someone asks "show me everything that can call our API", and the answer has to be one list.
>
> The scope isn't just "which toolset". It's which *tools* within it, plus an expiry, because an
> agent credential that never expires is a credential you will eventually forget about.

---

## ACT 2 — Each sees a different API (1:45)

**DO** — Run `tools/list` with the `support-bot` key. Count the tools.

**DO** — Run the same call with the `analytics-agent` key. Fewer tools.

**SAY**

> Same endpoint, same toolset, two different APIs — because the key resolves to a permitted set
> before the list is built.
>
> Note what this is *not*: it isn't a permission error when the agent tries to call something.
> The tool is simply absent from the list, so the agent never proposes it, never gets refused,
> and never spends three turns trying to work out why.
>
> That's a better security property and a better agent experience at the same time, which is
> rare enough to be worth pointing at.

---

## ACT 3 — Run them, then look (2:30)

**DO** — Make a couple of live calls with each key so there's fresh data on top of your seeded
history.

**DO** — Go to <http://localhost:3000/ade/dashboard/mcp/analytics>. Walk the view:
- calls over time, split by agent key,
- calls per tool — the top tools, which is the interesting one,
- error rate, with the errors broken out by status,
- latency distribution.

**DO** — Click into a single invocation record. Show tool, timestamp, latency, status and sizes —
and no body.

**SAY**

> Which agent, which tool, how often, how fast, how often it failed.
>
> The per-tool breakdown is the one people don't expect to care about and then can't stop looking
> at. It tells you which parts of your API an agent actually finds usable — and the tools that
> get called and fail repeatedly are usually the ones with thin descriptions or an awkward schema.
> That's a design signal you cannot get any other way.
>
> Individual records are metadata only. Bodies are excluded by default with opt-in sampling,
> because a complete log of agent traffic through a customer-facing API is a copy of customer
> data, and it should be a decision rather than a default.

---

## ACT 4 — Hit the quota (2:15)

**DO** — Hammer the low-cap key until it trips.

**DO** — *Pause on the refusal.* Show the error payload — MCP-conformant, with a retry hint.

**DO** — Show the agent's own behaviour: it reports being rate-limited rather than failing
opaquely or retrying in a loop.

**DO** — Show where the cap came from: the tenant's license tier, in the same place seats and
features come from.

**SAY**

> Refused, and refused in a shape the agent can read. That last part is the difference between a
> rate limit and an incident: an agent that gets an opaque failure retries, and an agent that
> retries a rate limit is a denial of service you built yourself.
>
> Per-key RPS and a daily cap, and the numbers come from the license tier — the same tier that
> governs seats. So quotas are already a commercial lever without a second billing system, and
> the counters feeding them are the same ones behind the charts you just saw. One number, two
> uses.

---

## ACT 5 — Revoke one (1:30)

**DO** — With the agent mid-conversation, revoke `support-bot`.

**DO** — Ask the agent to do something. It has no tools.

**DO** — Show the revocation in the audit log, and the historical usage still intact in analytics.

**SAY**

> Access ends immediately, mid-conversation, from a dashboard.
>
> And the history survives the revocation — you can still see everything that key did, which is
> exactly what you need when the reason you revoked it was that it did something surprising.
>
> That's the Agent Experience MVP. Your published API compiles into tools, exposure is curated
> and safe by default, the agent calls it without ever holding a credential, it cannot reach your
> internal network or your destructive operations, and every call has a name, a limit and a
> record.
>
> Which means "can agents use our API?" stops being a security argument and becomes a
> configuration.

---

## RESCUE — when it goes wrong on stage

**The charts are empty**
The seeded traffic didn't land, or the rollup job hasn't run.
*On stage:* drop to the raw invocation list, which is per-call and immediate. Seed traffic the
day before, not the hour before.

**The quota won't trip**
The cap is higher than you can reach by hand.
*On stage:* lower it live in the tier settings and retry once. Verify the trip time in prep.

**Revocation doesn't take effect immediately**
A cached key resolution.
*On stage:* wait one call cycle and retry. If it persists, file it — a revocation that lags is a
security finding, not a caching detail.

**`tools/list` returns the same count for both keys**
The allowlists are identical, or scope resolution isn't applied to listing.
*On stage:* check the allowlists first. If they differ and the lists don't, that's Act 2's claim
failing — say so.

---

## IF ASKED

**"Can I alert on a spike?"**
[AGX-3.5](https://github.com/apiome/apiome/issues/4541) — `Future`. It runs threshold and spike
detection on these rollups and fans out through the collaboration notification system.

**"How long is invocation history kept?"**
Retention per license tier, same as the platform's other retention policies.

**"Can an agent key be scoped to the mock instead of production?"**
Yes, through the toolset's target — [AGX-2.4 #4536](https://github.com/apiome/apiome/issues/4536),
already shipped.

**"Who can create an agent key?"**
The same RBAC that governs API keys today. Agent keys did not get their own permission model.

---

## Reference

| Surface | Where |
|---|---|
| API keys (agent kind) | <http://localhost:3000/ade/dashboard/api-keys> |
| MCP analytics | <http://localhost:3000/ade/dashboard/mcp/analytics> |
| MCP toolsets | <http://localhost:3000/ade/dashboard/mcp> |
| Audit log | <http://localhost:3000/ade/dashboard/audit> |
| Roadmap | `private-suite/docs/roadmaps/ROADMAP_AGENT_EXPERIENCE.md` §3 |
| Previous chapters | [4504](DEMONSTRATION_EPIC_4504.md) · [4505](DEMONSTRATION_EPIC_4505.md) |
