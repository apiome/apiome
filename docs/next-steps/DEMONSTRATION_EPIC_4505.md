# DEMONSTRATION — AGX-EPIC-2: Managed MCP Invocation Runtime

> **Written ahead of the recording.** Routes, control labels and outputs below come from the
> epic's acceptance criteria, not from a running build. Walk it once against the shipped UI and
> correct this file before you record.

| | |
|---|---|
| Epic | [AGX-EPIC-2 #4505](https://github.com/apiome/apiome/issues/4505) · umbrella [AGX #4503](https://github.com/apiome/apiome/issues/4503) |
| Wave | 5 — after [AGX-EPIC-1](DEMONSTRATION_EPIC_4504.md) |
| Tickets | [2.2 #4534](https://github.com/apiome/apiome/issues/4534) · [2.1 #4533](https://github.com/apiome/apiome/issues/4533) · [2.3 #4535](https://github.com/apiome/apiome/issues/4535) |
| Builds on | AGX-1.1/1.2 toolsets ✅ · AGX-3.1 agent keys ✅ · V2-MCP-20.2 encryption ✅ · SIM-3.2 SSRF policy ✅ |
| Runtime | ~12 min, plus 20 min prep |
| Audience | the security reviewer who will decide whether agents get to touch your API |
| The one beat | **The agent calls your API and never holds a credential.** |

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | How agents get credentials today | An API key in a config file on a laptop. | 1:15 |
| 2 | Store the upstream credential | Write-only. Nobody reads it back. | 2:00 |
| 3 | The agent makes a real call | Claude, a tool, your API, live. | 3:00 |
| 4 | Look at what the agent had | It never saw the key. | 1:45 |
| 5 | Point it at something internal | SSRF guard refuses. | 2:00 |
| 6 | Ask for the destructive tool | Not exposed. And annotated when it is. | 2:00 |

---

## PREP — before anyone is watching (~20 min)

**DO** — Start the stack. Complete the [AGX-EPIC-1](DEMONSTRATION_EPIC_4504.md) end state: a
published spec with a compiled, curated toolset.

**DO** — Stand up an upstream that requires authentication and that you control. The hosted mock
works and keeps the demo self-contained; anything that visibly rejects an unauthenticated request
is fine. **Do not point this at a real production API on camera.**

**DO** — Configure an MCP client — Claude Desktop is the strongest visual — pointed at the
tenant's MCP endpoint with an agent key. **Test the whole loop end to end before the demo.**
Restarting a desktop client on stage costs three minutes and all your momentum.

**DO** — Have an internal-looking URL ready for Act 5: `http://169.254.169.254/latest/meta-data/`
is the one everyone in a security review recognizes.

**DO** — Full dry run, twice. Act 3 is the demo; everything else is supporting material.

---

## ACT 1 — How agents get credentials today (1:15)

**DO** — Show a typical MCP client config with an API key in it.

**SAY**

> This is the normal way an agent gets access to an API today. A key, in a JSON file, on a
> laptop, in plaintext.
>
> Think about what that key is. It's usually a *service* credential, scoped to whatever the
> service can do, sitting on a developer machine, inside the context window of a model that can
> be asked to print its own configuration.
>
> Nobody thinks this is good. It's just what's available. So let's take the credential away from
> the agent entirely and see whether the thing still works.

---

## ACT 2 — Store the upstream credential (2:00)

**DO** — Open the toolset → **Upstream authentication**. Choose the scheme — bearer, API key in
header or query, or basic. Enter the credential and the server URL it's bound to. Save.

**DO** — Reload. The field shows a masked placeholder and a **Rotate** action. There is no reveal.

**DO** — Try to read it back through the API.

```bash
curl -s "$APIOME_BASE_URL/v1/toolsets/<id>/credentials" -H "X-API-Key: $APIOME_API_KEY" | jq
```

```json
{ "kind": "bearer", "server_url": "https://api.example.com", "created_at": "...", "last_rotated_at": "..." }
```

**SAY**

> Metadata comes back. The secret does not — not to me, not to an administrator, not to anyone
> with a token.
>
> Encrypted at rest with the same key management as the platform's backup encryption, bound to
> this toolset and this server URL. And it can be rotated without taking the toolset down, which
> is what makes rotation something a team will actually do rather than schedule and skip.

---

## ACT 3 — The agent makes a real call (3:00)

*The whole product, in one exchange. Do not narrate over it — let it run.*

**DO** — Switch to Claude Desktop. Ask something that requires a real call: *"What pets are
available, and what's the status of pet 42?"*

**DO** — *Pause and let the tool call happen on screen.* The tool invocation, then the result,
then the answer.

**DO** — Ask a follow-up that needs a second call with different arguments.

**SAY**

> That's a real HTTP request to a real API, made by an agent that has no credential.
>
> What happened underneath: the arguments were validated against the tool's input schema before
> anything left the building — so a malformed call fails here rather than as a confusing 400 from
> your service. Then the URL, query string, headers and body were constructed according to the
> spec's own serialization rules. The credential was injected server-side. The response was
> mapped back into a tool result the model can actually use, including the status code, because
> an agent that can't tell a 404 from a 500 will retry the wrong one forever.
>
> And when your API returns an error, the agent gets a spec-shaped error with hint text — not an
> HTML error page, which is what usually reaches a model and is why it then invents an
> explanation.

---

## ACT 4 — Look at what the agent had (1:45)

**DO** — Show the MCP client's configuration on screen. It contains the endpoint and an agent
key. No upstream credential.

**DO** — Ask the agent directly: *"What credentials do you have for this API?"* It can only
describe its tools.

**DO** — Show the invocation record on the platform side: which tool, when, latency, status. No
credential, and no request body by default.

**SAY**

> The agent had an endpoint and a key scoped to a toolset. That's all it ever had.
>
> Which means the blast radius of a leaked agent key is: the tools in that toolset, revocable
> from a dashboard, with every call already recorded. Compare that with a leaked upstream service
> key, which is the whole API and which you find out about later.
>
> And bodies aren't captured by default — sampled capture is opt-in. An audit trail that
> accidentally becomes a copy of your customer data is a liability, not a control.

---

## ACT 5 — Point it at something internal (2:00)

**DO** — Change the toolset's upstream server URL to `http://169.254.169.254/latest/meta-data/`.
Save.

**DO** — Trigger a call. It refuses — the host resolves to a blocked range.

**DO** — Also show a DNS name that *resolves* to a private address being refused.

**SAY**

> That address is the cloud metadata endpoint. If you can make a server fetch it, you can often
> get its credentials — it's the first thing anyone tries against a proxy.
>
> Refused, and refused on the **resolved** address rather than the string. Checking the hostname
> before resolution is the classic mistake: you block `169.254.169.254` and someone registers a
> DNS name that points at it.
>
> Same policy the mock's fetching path uses. One SSRF policy in the platform, not one per feature
> — because the second implementation is always the one with the hole.

---

## ACT 6 — Ask for the destructive tool (2:00)

**DO** — Restore the real upstream URL. In the agent, ask it to delete a pet.

**DO** — It reports it has no such tool — `DELETE` was never enabled on this toolset.

**DO** — Now enable it in the toolset editor. Re-run. Show the tool arriving with
`destructiveHint` set, and the client surfacing a confirmation.

**DO** — Show the size cap and the timeout budget in the toolset's settings.

**SAY**

> First it simply wasn't there. The agent could not call it, could not be persuaded to call it,
> and could not be prompt-injected into calling it — because it wasn't in the tool list at all.
> That is a much stronger control than a permission check on a tool the agent can see.
>
> Once you do enable it, it arrives annotated as destructive, so the client can put a human in
> front of it.
>
> And the rails underneath: methods allowlisted per tool, request and response size caps, and a
> cumulative timeout budget per call — so one agent cannot hold a connection open indefinitely,
> which is the accidental denial of service nobody plans for.
>
> That's the runtime. The agent calls your API, holds no credential, cannot reach your internal
> network, and cannot do anything you didn't turn on. What it does *not* have yet is a quota or
> an itemized bill — which is the next chapter.

---

## RESCUE — when it goes wrong on stage

**The MCP client can't connect**
Endpoint, key, or the client cached a failed connection.
*On stage:* fall back to an MCP inspector or a raw `tools/call`. Slower story, same beats. Do not
restart Claude Desktop on camera.

**The tool call returns 401 from upstream**
The stored credential is wrong or bound to a different server URL.
*On stage:* rotate it — it's two fields — and retry once. If it fails twice, move to Act 5, which
doesn't need a working upstream.

**The SSRF guard allows the metadata address**
A real security finding.
*On stage:* stop the act. Do not shrug past it in a video about safety.

**The agent invents an answer instead of calling a tool**
Model behaviour, not a platform failure.
*On stage:* ask again, more directly — "use the tool to look up pet 42". Rehearse the phrasing
that reliably triggers a call.

---

## IF ASKED

**"What's the latency cost?"**
The target is under 100ms of overhead at P95 over the upstream call. Validation and construction
are local; the vault lookup is the only extra I/O.

**"OAuth upstreams? Client credentials?"**
[AGX-4.5](https://github.com/apiome/apiome/issues/4546) — `Future`. Today: API key, bearer, and
basic.

**"Can I point a toolset at the mock instead of production?"**
Yes, and it already works — [AGX-2.4 #4536](https://github.com/apiome/apiome/issues/4536)
shipped with the mock consolidation in August. Set the toolset's target to `mock` and the agent
practises against the hosted mock with zero upstream risk. Worth demoing live if your audience
is a security team: it is the answer to "we're not pointing an agent at production on day one".

**"What stops an agent from calling the same tool ten thousand times?"**
Nothing yet. That's [AGX-EPIC-3](DEMONSTRATION_EPIC_4506.md) — the next chapter, and the honest
answer here is "not this one".

---

## Reference

| Surface | Where |
|---|---|
| MCP toolsets | <http://localhost:3000/ade/dashboard/mcp> |
| API keys | <http://localhost:3000/ade/dashboard/api-keys> |
| Mock data plane | `http://localhost:8775/{tenant}/{project}/{version}` |
| Roadmap | `private-suite/docs/roadmaps/ROADMAP_AGENT_EXPERIENCE.md` §3 |
| Previous chapter | [DEMONSTRATION_EPIC_4504](DEMONSTRATION_EPIC_4504.md) |
