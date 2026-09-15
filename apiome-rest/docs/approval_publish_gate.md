# Approval policy & publish gate (COL-2.3, #4519)

COL-2.1 (#4517) made review decisions *recordable*. This gate makes them *binding* by answering
one question at publish time:

> Has this draft collected the approvals its tenant's policy requires?

Recording reviews is not enough for a team with governance requirements: nothing stopped an
author from publishing a version no reviewer had ever looked at. The gate closes that hole
without walling anyone in — the GOV-2.5 force-publish escape stays, and using it is audited.

## Policy

Two **style-guide settings** (`style_guides.required_approvals` and
`style_guides.required_reviewer_role`, migration **V262**) resolved through the GOV-1.4 chain:
project assignment → tenant assignment → tenant default.

| Setting | Meaning |
|---|---|
| `requiredApprovals` | Approvals the version's **current review round** must carry. `0` (default) switches the gate off entirely. Capped at 20, the reviewer cap, so the policy stays satisfiable. |
| `requiredReviewerRole` | Optional `roles.slug` at least one of those approvals must come from, e.g. `release-manager`. `null` means any approver counts. |

A required role **on its own never gates a publish**: "no approvals, one of them from a release
manager" is not a policy a version can satisfy, so the gate is armed by `requiredApprovals >= 1`
alone.

Edit both at `PUT /v1/style-guides/{tenantSlug}/{guideId}/policy`, beside the CTG-3.4
breaking-publish level and the CLX-1.3 gates. Builtin guides are read-only, so arming the gate
means assigning a custom guide — the same rule every other guide setting follows. Both values
are frozen into each `style_guide_revisions` snapshot (GOV-1.6), so an escalation is auditable
history.

`requiredReviewerRole` is the one field where **omitted and `null` differ**: omitting it leaves
the stored role alone, sending `null` clears it.

The role slug is compared, never joined. A renamed or deleted role therefore degrades to
"nobody holds it" — publish blocked, force-publish available — rather than silently disarming
the policy.

## How the verdict is reached

Only the **open** review of the version counts, and only its **current round**. Earlier rounds
are history; a withdrawn review approved nothing.

| Rule | Verdict |
|---|---|
| No open review | `blocked` · `no-review` |
| A current-round reviewer requested changes | `blocked` · `changes-requested` |
| The content moved since the round was requested (COL-2.1 `spec_changed`) | `blocked` · `spec-changed` |
| Fewer current-round `approve` decisions than required | `blocked` · `insufficient-approvals` |
| Enough approvals, none from a holder of the required role | `blocked` · `missing-required-role` |
| Otherwise | `satisfied` |

The order is the order a reviewer would explain it in: a rejection outranks a shortfall, and a
stale round outranks both, because re-requesting it is the only way forward.

**Stale approvals are not approvals.** COL-2.1 records the fingerprint of the document each
round judged (a sha256 of the rebuilt OpenAPI) precisely so this gate can tell "approved" from
"approved something else". Editing a version after it is approved therefore blocks publish until
the review is re-requested.

A reviewer's role is their **effective** RBAC slug
(`Database.get_effective_role_slug`), resolved exactly as permissions are — so a tenant
administrator resolves to `owner`, whatever role row they also hold. Roles are only resolved
when the policy names one, so the common policy costs no extra queries.

## Statuses

| Status | Meaning | Blocks? |
|---|---|---|
| `disabled` | `requiredApprovals` is `0`. | no |
| `satisfied` | The policy is armed and the version meets it. | no |
| `blocked` | The policy is armed and the version does not meet it. | **yes** |
| `unavailable` | The gate could not be evaluated (unreadable review, unbuildable spec, DB fault). | no |

A gate that failed closed on its own bugs would stop more releases than the policy it enforces,
so **every fault degrades to `unavailable`** — and `unavailable` is audited, so the degradation
is visible rather than silent.

## Publish

`POST …/publish` runs the gate in `enforce_publish_prechecks`, **last** of the gates. It is the
only one whose answer a *person* has to change, so a publisher is told about a lint error or a
missing major bump first, rather than collecting approvals for a revision they are about to edit
— which would invalidate those approvals anyway.

A blocked publish is refused with `422`, the same contract as every other publish gate:

```json
{
  "detail": {
    "message": "1 of 2 required approval(s) recorded on this version. Collect the required approvals, relax the tenant approval policy, or force-publish with a reason.",
    "approvalGate": {
      "policy": { "requiredApprovals": 2, "requiredReviewerRole": "release-manager" },
      "status": "blocked",
      "blocked": true,
      "reason": "insufficient-approvals",
      "reviewId": "…",
      "reviewState": "in_review",
      "round": 1,
      "specChanged": false,
      "approvals": 1,
      "requiredApprovals": 2,
      "requiredReviewerRole": "release-manager",
      "roleApprovals": 1,
      "changesRequested": 0,
      "pending": 1,
      "approvers": [{ "userId": "…", "userName": "Ada", "roleSlug": "release-manager" }],
      "detail": null,
      "message": "1 of 2 required approval(s) recorded on this version."
    }
  }
}
```

At most `MAX_LISTED_APPROVERS` (20) approvers are listed; `approvals` always reports the true
total.

Force-publishing (`skipPublishChecks: true` + `forcePublishReason`) gets past it, exactly as it
does for style-guide errors, verification policy, and the breaking-publish guardrail.

## Audit trail

Every publish an **armed** policy judged appends one `workflow_audit` row with action
`version.approval_policy_gate`:

```json
{
  "action": "forced",
  "reason": "Incident 4519 — approver unavailable, CAB approved out of band",
  "approvalGate": { "…": "the full assessment payload" }
}
```

`action` is `satisfied`, `forced` (an unmet gate was force-published), or `unavailable`. Only a
tenant with no policy records nothing.

Satisfied publishes are recorded too, not just refused ones: an approval gate whose *passing*
verdicts leave no trace cannot answer "who signed off on this release?", which is the question
the policy exists to answer.

The forced case is assessed *after* publish, since `skipPublishChecks` skips the prechecks
wholesale — which is precisely the case where the audit trail matters most.

## Modules

| Module | Responsibility |
|---|---|
| `app/approval_policy.py` | The two settings and their normalizers — dependency-free, so guide surfaces need not import the review store |
| `app/approval_publish_gate.py` | Policy resolution, assessment, payload |
| `app/version_publish_prechecks.py` | Runs the gate and raises the 422 |
| `app/versions_routes.py` | The audit write |
| `app/style_guide_routes.py` | Reads and writes the policy beside the other guide gates |

## Not in this gate

Publishing does **not** close the version's open review — COL-2.1 left that to a later ticket,
and this gate only reads review state. A published version can therefore still show an open
review until then.

See also: [reviews.md](reviews.md), [breaking_publish_guardrail.md](breaking_publish_guardrail.md).
