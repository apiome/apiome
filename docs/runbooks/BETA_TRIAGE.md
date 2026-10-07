# Private Beta & Dogfood Triage Runbook

**Status:** RC1 baseline (ticket RC1-4.1 / #3620) · **Owner:** Release lead · **Feeds:** RC1-4.2 bug burn-down (#3621)

Before `v1.0.0-rc.1` is tagged, the spine has to survive real use by a small group: import, lint,
design, discuss, review, publish, mock, generate, consume. This runbook covers how that group is
brought in, how what they report reaches the repository, and how each report is triaged so the
release gate can answer one question with evidence: **are there zero open Critical and zero open
High issues?**

Dogfooding starts at Wave 0 and runs the whole time (see
[`RC5_EPIC_ORDER_OF_EXECUTION.md`](../next-steps/RC5_EPIC_ORDER_OF_EXECUTION.md)). It is the
input to the burn-down, not a step after it.

---

## 1. The pieces

| Piece | Where | What it does |
|---|---|---|
| Issue form | [`.github/ISSUE_TEMPLATE/beta-feedback.yml`](../../.github/ISSUE_TEMPLATE/beta-feedback.yml) | "Beta feedback" on the repo's **New issue** page. Applies `beta` and `triage:new`. |
| Label set | [`.github/beta-labels.json`](../../.github/beta-labels.json) | Every label below, with its colour and description. |
| Label sync | [`scripts/sync_beta_labels.py`](../../scripts/sync_beta_labels.py) | Creates or updates the labels on GitHub. Idempotent; never deletes. |
| Consistency test | [`scripts/tests/test_beta_intake.py`](../../scripts/tests/test_beta_intake.py) | Fails if the form, the labels and this runbook disagree. |

First-time setup, once per repository (needs `gh` with permission to manage labels):

```bash
python3 scripts/sync_beta_labels.py --dry-run   # review the commands
python3 scripts/sync_beta_labels.py             # apply
```

Re-run it after editing `beta-labels.json`. Check the form and labels are consistent with
`python3 -m unittest scripts/tests/test_beta_intake.py`.

---

## 2. Onboarding the cohort

Keep the group small enough that every report gets read the same day: **five to ten people**, at
least two of whom are not on the team.

1. **Pick** people who will use Apiome for a real API, not a demo spec. Cover each golden-path
   step at least twice across the group.
2. **Provision** a tenant per person (or per team) on the release-candidate stack (RC1-3.3), not on
   a dev stack.
3. **Send** each person:
   - the sign-in URL and their tenant;
   - the golden-path checklist in §5 as the suggested first session;
   - the link to file a report: `https://github.com/apiome/apiome/issues/new?template=beta-feedback.yml`
     (anyone without GitHub access sends the same fields by email, and the release lead files it
     for them, adding their name in the body);
   - the expected turnaround (§4).
4. **Record** the cohort as a comment on [#3620](https://github.com/apiome/apiome/issues/3620):
   who, which tenant, start date, and which workflows they cover. That comment is the cohort
   record the gate review cites. Update it when someone joins or leaves.

**Done when:** every cohort member has signed in and filed at least one report, even if it is a
`sev:low` suggestion. This is the "Beta cohort onboarded" criterion.

---

## 3. Labels

Every beta issue ends up with exactly one label from each of the three groups below. `beta`
stays on it for life.

Severity and triage state are not beta-only. Any defect that reaches the RC1 burn-down, such as
the OLO-7.3 security follow-ups, gets a `sev:*` and a `triage:*` label too. `beta` and `wf:*` are
for cohort reports only.

### Origin

| Label | Meaning |
|---|---|
| `beta` | Reported by the private beta / dogfood cohort. Applied by the form. |

### Workflow

The form asks the reporter which workflow they were in. GitHub cannot turn a dropdown answer into
a label, so **triage applies the matching `wf:*` label by hand**. That label is what lets the gate
review group the issue list by workflow.

| Label | Form option |
|---|---|
| `wf:sign-in` | Sign-in / tenant |
| `wf:import` | Import |
| `wf:lint` | Lint / grade |
| `wf:studio` | Studio editing |
| `wf:review` | Discussion & review |
| `wf:publish` | Publish |
| `wf:mock` | Mock |
| `wf:sdk` | SDK generation |
| `wf:browse` | Browse (public) |
| `wf:other` | Other |

### Severity

Set by triage, never by the reporter. The form's "How bad is it for you?" answer is an input to
this decision, not the decision itself.

| Label | Definition | Gate |
|---|---|---|
| `sev:critical` | The spine is broken or data is lost or exposed, and there is no workaround. | **Blocks the tag.** |
| `sev:high` | A golden-path step fails, or completes only with a workaround the reporter had to be told. | **Blocks the tag.** |
| `sev:medium` | Wrong, misleading or confusing, but the workflow completes unaided. | Fix or defer with a reason. |
| `sev:low` | Cosmetic, copy, or a suggestion. | Fix or defer with a reason. |

A report of a security problem is at least `sev:high`. Move its details out of the public issue
following the security process, and leave a placeholder.

### Triage state

| Label | Meaning | Next step |
|---|---|---|
| `triage:new` | Filed, not yet read. Applied by the form. | Triage within one working day. |
| `triage:needs-info` | Can't reproduce or understand it yet. | Ask a specific question. Close after 7 days without an answer, with a note. |
| `triage:accepted` | Reproduced (or clearly real), severity and workflow set. | The burn-down owns it (§4). Add `bug` if it is one. |
| `triage:deferred` | Real, but not for `v1.0.0-rc.1`. | **Must** carry a comment with the reason. Severity stays as set. |
| `triage:duplicate` | Already reported. | Close with a link to the original, and add the reporter's detail there. |

Replace the state label when the state changes; an issue never has two.

---

## 4. Triage loop

Daily, by the release lead or whoever holds the triage rota:

1. **Open** the queue:
   `gh issue list --label beta --label triage:new --state open`
2. **For each** issue:
   - reproduce it on the RC stack;
   - set one `wf:*` label and one `sev:*` label;
   - replace `triage:new` with the resulting state;
   - reply to the reporter with what happens next.
3. **Hand off.** Accepted `sev:critical` and `sev:high` issues go straight to the RC1-4.2 burn-down
   ([#3621](https://github.com/apiome/apiome/issues/3621)): add a row to the ledger,
   [`RC1_BURN_DOWN.md`](../next-steps/RC1_BURN_DOWN.md) §2, and set its gate status to RED. Critical
   issues are also raised the same day with whoever owns the affected service.
4. **Defer deliberately.** A `triage:deferred` issue without a written reason is not deferred. It
   is untriaged. A `sev:critical` or `sev:high` issue can only be deferred by the release lead, and
   the reason has to say why the RC can ship with it.

Turnaround: reporters hear back **within one working day**, even if the answer is "needs info".

**Done when:** no open `beta` issue still has `triage:new`, and every open one has a `wf:*` and a
`sev:*` label. This is the "Feedback/issues triaged and labeled" criterion.

---

## 5. Suggested first session for a cohort member

The golden path from the gate demo (Act 1 of
[`DEMONSTRATION_EPIC_3607.md`](../next-steps/DEMONSTRATION_EPIC_3607.md)). Do it on your own API:

1. Sign in; create a tenant or enter yours.
2. Import a spec. Lint it and read the grade.
3. Edit it in Studio. Comment on a field. Request a review; have someone approve it.
4. Publish. Watch the gate.
5. Turn the mock on and call it.
6. Generate an SDK and download it.
7. Open the public Browse page while signed out, and get the SDK from there.

Anything that stops you, slows you down or surprises you is worth a report.

---

## 6. Artifacts for the release gate

These are the "have these ready" items in the gate demo's prep list. Export them as files
before the review; don't run them live.

```bash
# The cohort's issue list, with workflow, severity and state
gh issue list --label beta --state all --limit 500 \
  --json number,title,state,labels,createdAt,closedAt \
  > beta-issues.json

# Open beta issues by severity. The gate needs the first two to be empty.
for sev in critical high medium low; do
  echo "== sev:$sev"
  gh issue list --label beta --label "sev:$sev" --state open
done

# The deferred list. Each one must have a reason comment.
gh issue list --label beta --label triage:deferred --state open \
  --json number,title,labels,url

# Still untriaged. Must be empty before the review.
gh issue list --label beta --label triage:new --state open
```

The numbers to state in the review:
- cohort size and period (from the #3620 cohort comment);
- reports filed;
- the split by `wf:*`;
- the open count by `sev:*`;
- the count deferred.
