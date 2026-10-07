# Agent toolset description enrichment (AGX-1.3, #4531)

Many specs leave operations and parameters undescribed. The AGX-1.1 compiler turns them into valid
tools that an agent cannot choose (no description) or fill in (no parameter description). The
enrichment pass does two things for an [agent toolset](agent_toolsets.md):

1. **Flags agent-hostile tools** with machine-readable reasons. This always runs, and the flags
   feed the AGX-4.4 agent-readiness score.
2. **Proposes better descriptions** for the thin ones, using the copilot (an Ollama chat model).
   This runs only when a model is configured.

**Nothing generated reaches an agent until a person accepts it.** A proposal is stored as
`proposed`, and only an `accept` makes the compiled toolset serve it. A database CHECK makes an
accepted description without a review impossible to store.

## Flags

| Code | Meaning |
| --- | --- |
| `missing-description` | The operation has no summary or description. |
| `thin-description` | Its description is under 40 characters (`MIN_TOOL_DESCRIPTION_CHARS`). |
| `missing-examples` | No example on its parameters, request, or responses. |
| `undocumented-errors` | An HTTP operation declares no `4XX`/`5XX` and no `default` response. |
| `missing-parameter-description` | A parameter has no description (`parameter: "query.limit"`). |
| `thin-parameter-description` | A parameter's description is under 12 characters (`MIN_PARAM_DESCRIPTION_CHARS`). |

The thresholds are the CLX-3.1 agent-readiness pack's (`app.mcp_agent_readiness`), so the two
features agree on what "thin" means. Flags describe the **source spec**, so they do not change
when a proposal is accepted. They are computed on read and not stored.

## Proposals

A **target** is a tool or parameter description that is missing or thin. The pass sends the
copilot one prompt per operation, built only from what the spec already documents: the API title
and description, the operation key, id and tags, its parameters, its request and response payload
types and fields, its response descriptions, and its examples. The model is told not to invent
anything. The reply is a JSON object (`{"tool": "...", "parameters": {"query.limit": "..."}}`).
Anything that is not a usable string for a requested key is dropped. Text is whitespace-collapsed,
capped (1,000 characters for a tool, 300 for a parameter) and credential-scrubbed.

- **Idempotent.** A target that already has a proposal, whatever its status, is never asked about
  again. `UNIQUE (toolset_id, target_key)` with `ON CONFLICT DO NOTHING` backs this up, so a
  reviewed proposal is never overwritten.
- **Bounded.** One run asks about at most 20 operations (`MAX_OPERATIONS_PER_RUN`) and reports
  `remainingOperations`. Run it again to continue, or pass `operations` to choose which.
  `failedOperations` counts operations that got no usable answer. They stay pending.
- **Flag-only without the copilot.** With `APIOME_AGENT_ENRICHMENT_MODEL` unset, `mode` is
  `flag-only` and the pass proposes nothing. An unreachable Ollama behaves the same, operation by
  operation: the call returns nothing and the operation stays pending.

## Review and serving

`PATCH …/enrichment/{proposalId}` takes `{"decision": "accept"}` (optionally with an edited
`description`) or `{"decision": "reject"}`. A decision can be changed: rejecting an accepted
proposal withdraws it. Reviewer and time are recorded on the proposal.

`GET …/compiled` returns the toolset as agents are served it: the enabled tools, compiled by
`compile_mcp_tools`. While the toolset's `descriptionEnrichment` is on (the default), accepted text
is written into the canonical model first. A tool description keeps the spec's summary as its first
line. `enrichedTargets` lists what was applied. `PATCH …/agent-toolsets/{id}` with
`{"descriptionEnrichment": false}` opts out: the spec-derived descriptions are served and the
proposals are kept. Enrichment never changes tool names or input schemas, only descriptions.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `APIOME_AGENT_ENRICHMENT_MODEL` | unset | The Ollama chat model that writes proposals. Unset means flag-only. |
| `OLLAMA_BASE_URL` (`ollama_base_url`) | `http://localhost:11434` | The Ollama server, shared with the embedding client. |

## REST surface

| Method | Path | Permission | Audit action |
| --- | --- | --- | --- |
| `GET` | `/v1/tenants/{t}/agent-toolsets/{id}/enrichment` | `api_keys:view` | — |
| `POST` | `/v1/tenants/{t}/agent-toolsets/{id}/enrichment` (`operations?`) | `api_keys:edit` | `agent.toolset.enrichment.run` |
| `PATCH` | `/v1/tenants/{t}/agent-toolsets/{id}/enrichment/{proposalId}` | `api_keys:edit` | `agent.toolset.enrichment.review` |
| `GET` | `/v1/tenants/{t}/agent-toolsets/{id}/compiled` | `api_keys:view` | — |

| Refusal code | Status |
| --- | --- |
| `agent-toolset-not-found` / `agent-toolset-enrichment-not-found` | 404 |
| `agent-toolset-source-unavailable` | 422 |
| `agent-toolset-enrichment-invalid` (unknown `operations`, a blank or over-long edit, an edit with `reject`) | 422 |

Audit rows hold metadata only. A run records its mode, model and counts. A review records the
target, the status before and after, and whether the text was edited, never the text itself.

```bash
# Flag, and propose when the copilot is configured.
curl -sX POST "$APIOME/v1/tenants/acme/agent-toolsets/$TOOLSET/enrichment" \
  -H "Authorization: Bearer $TOKEN"

# Accept one proposal, with an edit.
curl -sX PATCH "$APIOME/v1/tenants/acme/agent-toolsets/$TOOLSET/enrichment/$PROPOSAL" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"decision": "accept", "description": "Lists every pet in the store, newest first."}'

# What agents are served.
curl -s "$APIOME/v1/tenants/acme/agent-toolsets/$TOOLSET/compiled" -H "Authorization: Bearer $TOKEN"
```

## Where the pieces live

| Piece | What it owns |
| --- | --- |
| `apiome-db/scripts/V273__agent_toolset_enrichment_agx_1_3.sql` | `agent_toolsets.description_enrichment`, `agent_toolset_enrichments` and its review CHECK |
| `app.agent_tool_enrichment` | Pure: flags, targets, prompt, reply parsing, `apply_description_overrides` |
| `app.agent_toolset_enrichment` | The service: run, report, review, compile |
| `app.ollama_chat` | The stdlib Ollama `/api/chat` client (fails soft to `None`) |
| `app.agent_toolset_routes` | The four routes and their audit rows |

## Tests

| File | Pins |
| --- | --- |
| `tests/test_agent_tool_enrichment.py` | Flags, targets, prompt, reply parsing, overrides; a corpus sweep across every format |
| `tests/test_agent_toolset_enrichment.py` | Every acceptance criterion over the in-memory store with a scripted copilot |
| `tests/test_agent_toolset_enrichment_routes.py` | Permissions, status mapping, audit rows, the review loop end to end |
| `tests/test_ollama_chat.py` | The request shape and every soft failure |
| `tests/test_agent_toolset_enrichment_migration.py`, `apiome-db/test/agent-toolset-enrichment.test.ts` | The V273 schema promises |
