# Scheduled verification & drift alerts (CTG-4.4)

> apiome#4501 — the continuous half of CTG-EPIC-4 (#4466), umbrella #4458.
> Executes CTG-4.3 (#4489) runs on a cadence and notifies over the existing push-webhook channel
> (#2587/#2588). Feeds CTG-4.5 (#4502) with verification freshness.
>
> Complements MFI-EPIC-31 (#4386): that watches **sources** (an upstream spec being re-discovered);
> this watches **deployments** (a live API against the contract it published).

## Why

CTG-4.3 made a deployment checkable. On demand only helps if somebody remembers to ask. A Friday
deploy that breaks conformance sits unnoticed until the next incident, and the check that would have
caught it was one HTTP request away the whole time.

Three things were missing, and this ticket adds exactly those:

* **Nothing ran on its own.** Every verification needed a human or a pipeline step.
* **Nothing said anything.** A failing run wrote a report and waited to be read.
* **Nothing remembered.** "When did this last verify clean?" had no answer, so a deploy gate had
  nothing to be fresh about.

## Modules

| Module | Role |
|---|---|
| `app/verification_schedule.py` | Pure: what a schedule is, when it notifies (`decide_alert`), what the alert says (`build_alert_payload`). |
| `app/verification_schedule_store.py` | The only place a schedule or a history row is written or read. |
| `app/verification_schedule_sweep.py` | The periodic worker: select due → lock → run → judge → notify → record. |
| `app/verification_schedule_notifications.py` | Two events over the existing push-webhook pipeline. |
| `app/verification_schedule_routes.py` | The six endpoints below. |
| `apiome-db` **V253** | `verification_schedule` + `verification_schedule_run` (write-once history). |

**No execution machinery was added.** Each tick calls
`provider_verification_service.verify_version_against_target` — the CTG-4.3 service, unchanged. The
same suite is compiled, the same requests are sent, the same mutation rules apply, and the same
immutable ECA-1.3 evidence and V252 report are written. A scheduled check that behaved differently
from a manual one would be worthless as a gate input.

## Endpoints

```
GET    /v1/tenants/{tenant_slug}/verification-schedules
POST   /v1/tenants/{tenant_slug}/verification-schedules
GET    /v1/tenants/{tenant_slug}/verification-schedules/{schedule_ref}
PATCH  /v1/tenants/{tenant_slug}/verification-schedules/{schedule_ref}
DELETE /v1/tenants/{tenant_slug}/verification-schedules/{schedule_ref}
GET    /v1/tenants/{tenant_slug}/verification-schedules/{schedule_ref}/runs
```

`schedule_ref` is the handle **or** the id, the same way a verification target is addressed.

Definition:

```json
{
  "slug": "petstore-staging",
  "name": "Petstore · staging",
  "version_ref": "project/petstore/1.0.0",
  "target_ref": "staging",
  "cadence": "hourly",
  "enabled": true,
  "alert_on_recovery": true,
  "verification": { "allow_mutating": false, "fixtures": [] },
  "options": {}
}
```

`cadence` is a number of seconds or one of `5m`, `15m`, `30m`, `hourly`, `6h`, `12h`, `daily`,
`weekly`. The floor is **five minutes**: anything shorter against a live deployment is load, not
monitoring. The ceiling is thirty days, past which "scheduled" stops meaning anything.

Permissions reuse the two resources this surface already has — **no new RBAC resource**:

| Action | Permission | Why |
|---|---|---|
| List / read a schedule | `verification_targets:view` | A schedule is target configuration. |
| Create / update / retire | `verification_targets:create` / `edit` / `delete` | *Where and how often* a deployment is hit is the same class of decision V211 kept out of an Editor's hands. |
| Read run history | `verification_evidence:view` | A verification history is evidence. |

## Alerting: quiet by design

The acceptance criterion is exact — *a pass→fail transition triggers exactly one alert* — and
`decide_alert` is that rule as a pure function of the schedule's stored state and the tick:

| Previous state | This tick | Result |
|---|---|---|
| `ok` | passed | silent |
| `ok` | failed / errored | **alert** — `transition` → state becomes `alerting` |
| `alerting` | failed, same violations | **silent** (this is the no-storm rule) |
| `alerting` | failed, violations changed | **alert** — `new-violations` |
| `alerting` | passed | **alert** — `recovered` → state becomes `ok` |

Two decisions inside that table are worth stating plainly.

**"Same violations" is a fingerprint, not a report comparison.** `run_fingerprint` digests the
sorted set of `(operation_key, case_id, kind, code, pointer, expected)` — deliberately *excluding*
`actual` and `message`, because a deployment returning a different wrong id on every request is the
same violation, and folding the value in would make every tick look like new drift and reinstate
exactly the storm this exists to prevent. A tick that could not run at all has no violations to
digest, so its fingerprint comes from the refusal code: a version that keeps failing to compile
notifies once, and a *different* refusal is still news.

**Recovery always clears the state, even when it is not announced.** With `alert_on_recovery: false`
the recovery is silent, but the schedule still returns to `ok` — otherwise the next failure would be
filed as "new violations" instead of a transition, and a tenant who muted recovery notices would
eventually be muted about failures too.

The alert state lives on the schedule row (`alert_state`, `alert_fingerprint`), not in a worker's
memory, which is what makes "exactly once" survive a restart and hold across replicas.

## The events

```
verification.drift.detected   — a scheduled run found drift, or could not reach a verdict
verification.drift.resolved   — a schedule that was alerting verified clean again
```

Delivery, HMAC signing (`X-Apiome-Signature`), the four attempts with backoff, and the dead-letter
behaviour are the **standard push-webhook ones, untouched** — this ticket decides what is enqueued,
never how it is delivered. The `minSeverity` subscription filter is specific to `version.published`
and does not apply here.

Payload (abridged):

```json
{
  "event": "verification.drift.detected",
  "reason": "transition",
  "scheduleId": "…", "scheduleSlug": "petstore-staging",
  "versionRef": "project/petstore/1.0.0",
  "target": { "slug": "staging", "environment": "staging", "baseUrl": "https://staging…" },
  "status": "failed",
  "previousStatus": "passed",
  "reportId": "…", "runId": "…",
  "coverage": { "operationsTotal": 40, "operationsExercised": 22, "coveragePercent": 55.0, "…": 0 },
  "driftCount": 3,
  "operations": [
    {
      "operationKey": "GET /pets/{petId}",
      "outcome": "failed",
      "casesFailed": 1,
      "drift": [
        { "kind": "response_schema", "code": "response-schema-mismatch",
          "pointer": "/id", "expected": "integer", "actual": "1" }
      ],
      "driftTotal": 1, "driftTruncated": false
    }
  ],
  "operationsTotal": 3,
  "operationsTruncated": false,
  "consecutiveFailures": 1,
  "lastSuccessAt": "2026-09-06T12:00:00+00:00",
  "freshnessSeconds": 86400
}
```

The payload is **capped**: at most 20 violating operations, at most 5 located violations each, and
every string bounded — an alert carrying four hundred operations is an alert nobody reads. What was
dropped is *counted* (`operationsTotal`, `driftTotal`, `operationsTruncated`, `driftTruncated`),
never silently omitted, and `reportId` reaches the full picture. No credential, request header, or
response body is ever carried.

## Freshness and history

Every tick writes a **write-once** row to `verification_schedule_run`: the verdict, the coverage it
measured, the drift count, the violation-set fingerprint, and — for every tick, not only the noisy
ones — whether it notified and why. "Why was I not paged?" is answerable from the history rather
than from a worker's log.

The schedule itself carries the freshness answer, as indexed columns:

* `last_success_at` — when this deployment last verified clean;
* `freshness_seconds` — computed at read time from that anchor;
* `last_status`, `consecutive_failures`, `alert_state`.

`freshness_seconds` is **null when the schedule has never verified clean**. A gate must read that as
*unknown*, never as *fresh*: treating "never verified" as "verified recently" is worse than no gate.
This is the read CTG-4.5 makes — `GET …/verification-schedules?version_ref=project/petstore/1.0.0`.

## The sweep

Wired in `app.main` beside the repository-refresh, MCP-discovery, and catalog-digest sweeps, on its
own database connection (the per-schedule advisory locks are session-scoped).

| Setting | Default | Meaning |
|---|---|---|
| `APIOME_VERIFICATION_SCHEDULE_ENABLED` | `true` | Global kill switch: halts every scheduled run for incident response, independent of per-schedule state. |
| `APIOME_VERIFICATION_SCHEDULE_INTERVAL` | `60` | Tick floor — how often the loop looks for due schedules. Each schedule's own cadence gates actual runs. |
| `APIOME_VERIFICATION_SCHEDULE_BATCH_SIZE` | `5` | Max schedules executed per tick. Unlike the sibling sweeps this one sends real requests to live deployments, so the batch is bounded; the remainder stays due. |

Three properties, each deliberate:

* **Single-flight per schedule.** A Postgres session advisory lock, so two workers or two
  overlapping ticks never run one schedule at once — which would double the traffic at the
  deployment and could double an alert.
* **The anchor advances on every processed schedule** — clean, drifting, or unable to run at all —
  so a schedule whose version stopped compiling cannot stay perpetually due and hammer the sweep.
* **No idempotency key is passed to the run.** It is tempting: a key derived from the due anchor
  would make a second replica replay rather than re-execute. It is a trap. The stored evidence is
  returned *instead of* a fresh run when a key matches, so a failed anchor write would make the next
  tick report the previous tick's verdict as current — a stale `passed` masking live drift.
  Single-flight is the lock's job; freshness is not negotiable.

## Manual golden path

1. Register a verification target (`environment: staging`) and publish a version, per
   `provider_verification.md`.
2. `POST …/verification-schedules` with `{"slug":"petstore-staging","name":"Petstore · staging",
   "version_ref":"project/petstore/1.0.0","target_ref":"staging","cadence":"5m"}` → **201**.
3. Wait one cadence. `GET …/verification-schedules/petstore-staging/runs` shows a `passed` tick with
   `alerted: false`; the schedule's `last_success_at` and `freshness_seconds` are populated.
4. Point the deployment at a stub that drops a required field. The next tick is `failed`, with
   `alerted: true` and `alert_reason: "transition"`, and one `verification.drift.detected` delivery
   per active push-webhook subscription.
5. Leave it broken. The tick after that is `failed` with `alerted: false` — same fingerprint, no
   storm.
6. Fix the deployment. The next tick is `passed` with `alert_reason: "recovered"`.

## Out of scope

* The aggregate deploy-gate verdict — CTG-4.5 (#4502)
* Cron expressions (this is an interval cadence, the vocabulary every other periodic worker in the
  platform speaks)
* A dashboard surface — not in this ticket's affected modules
