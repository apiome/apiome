# DEMONSTRATION — AGX-EPIC-1: Spec → MCP Tool Compiler

> **Written ahead of the recording.** Routes, control labels and outputs below come from the
> epic's acceptance criteria, not from a running build. Walk it once against the shipped UI and
> correct this file before you record.

| | |
|---|---|
| Epic | [AGX-EPIC-1 #4504](https://github.com/apiome/apiome/issues/4504) · umbrella [AGX #4503](https://github.com/apiome/apiome/issues/4503) |
| Wave | 5 — the agent lane's foundation |
| Tickets | [1.1 #4529](https://github.com/apiome/apiome/issues/4529) · [1.2 #4530](https://github.com/apiome/apiome/issues/4530) · [1.4 #4532](https://github.com/apiome/apiome/issues/4532) · [1.3 #4531](https://github.com/apiome/apiome/issues/4531) |
| Builds on | canonical model ✅ · SDK-1.3-style ref preprocessing ✅ · `apiome-mcp` ✅ |
| Runtime | ~10 min, plus 15 min prep |
| Audience | anyone who has hand-written an MCP server wrapping their own API |
| The one beat | **Your published API becomes a set of agent tools — and by default the agent can only read.** |

> Chapter 1 of three. [AGX-EPIC-2](DEMONSTRATION_EPIC_4505.md) makes the tools callable;
> [AGX-EPIC-3](DEMONSTRATION_EPIC_4506.md) puts identity and limits around them. This one is the
> compiler, and it ends before anything is invoked — on purpose.

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | The hand-written MCP server | Six hundred lines that go stale on the next release. | 1:00 |
| 2 | Compile the spec | Twelve operations, twelve tools, zero code. | 2:30 |
| 3 | Read the tool schema | This is why generated tools usually don't work. | 2:30 |
| 4 | Safe by default | Every read on. Every write off. | 2:00 |
| 5 | Regenerate — byte for byte | Determinism, and the corpus that enforces it. | 2:00 |

---

## PREP — before anyone is watching (~15 min)

**DO** — Start the stack.

```bash
yarn dev
```

**DO** — Publish the petstore spec. You need a version with both reads and mutating operations —
Act 4 is meaningless without a `DELETE`.

**DO** — Have a **second, uglier spec** ready. Petstore is a fair demo but it is *tidy*; the
compiler's real claim is about anonymous schemas and missing operation IDs. Pick something from
`apiome-ui/examples/openapi/` that has inline response schemas. Act 3 lands twice as hard on it.

**DO** — Have an MCP inspector or client to hand for reading `tools/list` output. Decide in prep
whether you're showing raw JSON or a client's tool list — raw JSON reads better on a projector
for Act 3.

**DO** — Full dry run.

---

## ACT 1 — The hand-written MCP server (1:00)

**DO** — Show a hand-written MCP server file — one wrapping an API in tool definitions. Scroll it.

**SAY**

> This is what teams are writing right now to make their API usable by an agent. A tool
> definition per operation, an input schema per tool, hand-transcribed from a spec that is sitting
> right there in the repository.
>
> Two problems, and the second is the fatal one. It's tedious — and it is a *copy*. Ship a new
> API version and this file is quietly wrong, in the specific way where the agent still calls it
> and gets confusing errors.
>
> The spec already describes every one of these operations. Nobody should be typing this.

---

## ACT 2 — Compile the spec (2:30)

**DO** — Go to <http://localhost:3000/ade/dashboard/mcp> → **Toolsets** → **Create toolset** from
the published petstore version.

**DO** — *Pause on the result.* Twelve operations, twelve tools, names derived from operation IDs.

**DO** — Show `tools/list` output against the toolset.

**SAY**

> Twelve tools, from the document you already publish. No file to maintain, and no second place
> for the truth to live.
>
> The names come from operation IDs, sanitized, and collisions resolve the same way every time —
> so a tool name is stable across regenerations. An agent that learned `get_pet_by_id` yesterday
> finds `get_pet_by_id` today.

---

## ACT 3 — Read the tool schema (2:30)

*The technical heart. This is where the ugly spec earns its keep.*

**DO** — Open one tool's `inputSchema` in full.

**DO** — Point at each part as you narrate: path parameters, query parameters, headers, and the
request body — merged into **one** flat input schema, with `$ref`s resolved.

**DO** — Now switch to the ugly spec's compiled toolset. Show a tool whose source operation had
an anonymous inline schema and no operation ID — and show that it still has a sensible tool name
and a named schema.

**SAY**

> Here's the thing that makes this work rather than technically exist.
>
> An agent does not have a concept of "path parameter versus query parameter versus body". It has
> one arguments object. So the compiler merges all four parameter locations into a single input
> schema, resolves every reference, and emits JSON Schema that stays inside the subset MCP
> actually supports — no `oneOf` gymnastics an agent's tool-calling layer will reject.
>
> And on the messy spec: that operation had no operation ID and an inline anonymous response
> schema. That is the normal condition of real specs, and it's exactly where naive generators
> emit `postPets_1` and `Inline_Response_200`. There's a deterministic preprocessing pass in
> front of the compiler — the same one the SDK generators use — that synthesizes stable IDs and
> names schemas from context.
>
> The output description comes from the 2xx response, because an agent deciding whether to call a
> tool needs to know what it gets back, not just what it sends.

---

## ACT 4 — Safe by default (2:00)

**DO** — Open the toolset editor. Show the tool list with per-tool toggles.

**DO** — *Pause.* Every `GET` and `HEAD` is enabled. Every `POST`, `PUT`, `PATCH` and `DELETE`
is off.

**DO** — Enable `DELETE /pets/{petId}`. It requires an explicit confirmation, and the row is
flagged as a write operation.

**DO** — Show the audit entry for that change.

**SAY**

> Every read is on. Every write is off. You have to reach for the dangerous thing on purpose.
>
> This is the difference between this and generating an MCP server as a file. A generated file
> exposes whatever you generated — and the person running it usually didn't read all of it. Here,
> exposure is a curated set, stored, versioned, and audited, and the default is the safe one.
>
> The write flag isn't only a gate, either. It becomes the `destructiveHint` annotation on the
> tool itself in the next chapter, so the agent's own client can warn a user before the call.

---

## ACT 5 — Regenerate, byte for byte (2:00)

**DO** — Recompile the same version. Diff the two toolsets. Identical.

**DO** — Show the regression corpus in CI — golden toolset JSON for the examples corpus.

```bash
cd apiome-mcp && pytest tests/test_toolset_goldens.py -q
```

**DO** — Change something in the compiler, re-run, and show a golden failing loudly.

**SAY**

> Same spec in, identical tools out. Not "equivalent" — identical.
>
> That matters because an agent's behaviour depends on the exact text of a tool description and
> the exact shape of its schema. A compiler that reorders keys between runs produces an agent that
> works on Tuesday and doesn't on Wednesday, and nobody will ever find out why.
>
> So there are golden toolsets for the whole examples corpus, asserted in CI. Change the compiler
> and you see precisely which tools moved, on every spec shape we know about, before it ships.
>
> What we have not done yet is *call* anything. Tools are compiled and curated; nothing has
> touched an upstream API. That's the next chapter — and it's the one with the vault in it.

---

## RESCUE — when it goes wrong on stage

**Compilation fails on the ugly spec**
A preprocessing gap.
*On stage:* fall back to petstore and describe the harder case. File the spec as a corpus
addition — that's a genuinely useful outcome.

**A tool's input schema is missing the request body**
Ref resolution failed for that operation.
*On stage:* show a different tool. Note it: this is a correctness bug, not a presentation issue.

**`tools/list` is empty**
The toolset is created but not enabled, or the MCP endpoint points at a different tenant.
*On stage:* check the enabled toggle first, tenant second.

**Goldens fail on an unmodified compiler**
Something non-deterministic leaked in — a timestamp or a dict ordering.
*On stage:* this is Act 5's claim failing. Say so and file it.

---

## IF ASKED

**"How is this different from generating an MCP server artifact?"**
[SDK-4.5](https://github.com/apiome/apiome/issues/4499) generates a runnable server you host and
maintain. This is hosted and *governed* — curated exposure, audited changes, and in the next two
chapters, a credential vault, safety rails, scoped keys and usage records. The file is a
starting point; this is an operating model.

**"Do descriptions get improved? Our summaries are thin."**
[AGX-1.3](https://github.com/apiome/apiome/issues/4531) is an optional enrichment pass, always
human-reviewable, and it flags "agent-hostile" operations — no description, no examples. It runs
last in the wave, after the core works, because an AI-written description on top of a broken
schema helps nobody.

**"Can I expose only part of my API?"**
That's what the toolset is. Per-operation, per-version.

---

## Reference

| Surface | Where |
|---|---|
| MCP section | <http://localhost:3000/ade/dashboard/mcp> |
| Capabilities | <http://localhost:3000/ade/dashboard/mcp/capabilities> |
| Published versions | <http://localhost:3000/ade/dashboard/published> |
| Corpus | `apiome-ui/examples/openapi/` |
| Roadmap | `private-suite/docs/roadmaps/ROADMAP_AGENT_EXPERIENCE.md` §3 |
