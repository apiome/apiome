# RC10 — Plan: Contracts and PactFlow (after RC9)

_Drafted 2026-11-19 against `main` @ `e952b7d0c`. RC10 is the release after RC9 (Catalog, Projects, OpenAPI and Arazzo; see [`RC9_PLAN.md`](RC9_PLAN.md)). **Theme: Contracts and
PactFlow.** Priority: **extremely high** — this is the next release-candidate feature list._
_Status: **filed** (2026-11-19): milestone and project exist and the tickets are in the project in order of execution (Rank). §6 records the set-up steps that were run._

**Tracking:** the [**Apiome: RC10**](https://github.com/orgs/apiome/projects/132) GitHub Project and the **RC10** milestone on `apiome/apiome`. The project is the source of truth for status; this plan holds scope and the reason each ticket is in. (This release was first named RC9; it was renumbered when the Catalog, Projects and OpenAPI/Arazzo release took RC9.)

---

## 0. What is in RC10

| Section | What | Roadmap |
| --- | --- | --- |
| §1 | Carry-over from RC8 | RC8_PLAN §1 |
| §2 | **Pact Broker / PactFlow parity** — broker, bi-directional contract testing, verifier, CLI/CI, UI, migration | [`ROADMAP_PACTFLOW_PARITY.md`](ROADMAP_PACTFLOW_PARITY.md) (`PFX`, ~52 issues, 7 epics) |
| §3 | **Contract agreements** — SLA builder, data sharing and consent, billing, audit and compliance, platform services | [`ROADMAP_CONTRACT_AGREEMENTS.md`](ROADMAP_CONTRACT_AGREEMENTS.md) (`CAG`, ~57 issues, 11 epics) |
| §4 | Everything in `apiome/private-suite` about contracts / Pact, and where it goes | PACTFLOW roadmap §3 |
| §5 | Foundations that already shipped and are reused (not re-planned) | CTG, ECA, XPC |
| §6 | Set-up steps on approval | — |

Estimated size: **~128 tickets** (19 epics + umbrella + ~108 issues). RC10 MVP is a deliberately smaller set
(§2.2, §3.2); the rest is V2 and may slip to RC10 only by an explicit decision.

---

## 1. Carry-over from RC8

Only V2 RC8 tickets can carry over (MVP tickets block RC8).

| RC8 ticket | Reason | Moved on |
| --- | --- | --- |
| _none yet_ | | |

---

## 2. Pact Broker and PactFlow parity (`PFX`)

Goal: existing Pact tooling works against Apiome by changing the base URL and token, plus PactFlow's
bi-directional testing wired to Apiome's spec model.

### 2.1 Epics

| Epic | Scope | Issues | MVP issues |
| --- | --- | --- | --- |
| PFX-EPIC-1 | Broker core: pacticipants, publish/fetch, selectors, verification results, environments, matrix + can-i-deploy, pending/WIP, conformance suite, webhooks | 11 | 1.1–1.6, 1.8, 1.9 |
| PFX-EPIC-2 | Bi-directional contract testing: provider contract, comparison engine, verdicts, self-verification evidence | 6 | 2.1–2.4 |
| PFX-EPIC-3 | Provider verification engine: pact→suite, hosted verifier, provider states, matching rules, message and plugin pacts | 7 | 3.1–3.3 |
| PFX-EPIC-4 | CLI (`apiome pact`), broker-compatible auth, CI actions, commit statuses, MCP, Postman | 7 | 4.1–4.3 |
| PFX-EPIC-5 | UI: pacticipants, pact viewer, matrix and can-i-deploy console, webhooks, environments | 8 | 5.1, 5.2, 5.4, 5.6 |
| PFX-EPIC-6 | RBAC and audit, scheduling, health analytics, ownership, scale, **migration from Pact Broker/PactFlow**, self-host | 8 | 6.1, 6.7 |
| PFX-EPIC-7 | Integration: one consumer model, can-i-deploy as a deploy-gate signal, publish quality gate | 5 | 7.1–7.3 |

### 2.2 Ranking (why this order)

| # | Item | Why |
| --- | --- | --- |
| 1 | PFX-1.1 → 1.2 → 1.6 (model, publish, can-i-deploy) | Nothing else is usable without them; this is the product's headline |
| 2 | PFX-1.8 conformance suite | "Drop-in" must be proven in CI from the first publish endpoint onward |
| 3 | PFX-2.1–2.3 bi-directional | PactFlow's differentiator and Apiome's advantage: the spec model already exists |
| 4 | PFX-3.2 hosted verifier | Teams without a Pact library in the provider language can still verify |
| 5 | PFX-6.7 migration | Removes the main adoption blocker for existing Broker/PactFlow users |
| 6 | PFX-7.2/7.3 gate integration | Connects the new verdict to the CTG-4.5 deploy gate and the publish guardrail |

---

## 3. Contract agreements (`CAG`)

Moved from private-suite's Contracts roadmap. Epics 1–4 and 6–9 and 11 keep their source numbering; the Pact
epics (5, 10) are re-homed into `PFX` except the three binding items that connect Pact to an agreement.

### 3.1 Epics

| Epic | Title | Source issues |
| --- | --- | --- |
| CAG-EPIC-1 | Contract Builder & Templates | 1.1–1.6 (private-suite #402–#407) |
| CAG-EPIC-2 | Data Sharing & Consent Management | 2.1–2.5 (#408–#412) |
| CAG-EPIC-3 | Billing & Revenue Integration | 3.1–3.5 (#413–#417) |
| CAG-EPIC-4 | Audit Trail & Compliance | 4.1–4.5 (#418–#422) |
| CAG-EPIC-5 | Pact ↔ agreement binding (reduced) | CAG-5.1, 5.3, 5.5a |
| CAG-EPIC-6 | Authoring & Lifecycle Enhancements | 6.1–6.6 (#2305…) |
| CAG-EPIC-7 | Data Sharing Enforcement & Intelligence | 7.1–7.8 |
| CAG-EPIC-8 | Billing Operations & Financial Integrations | 8.1–8.6 |
| CAG-EPIC-9 | Compliance, Audit & Dispute Operations | 9.1–9.7 |
| CAG-EPIC-10 | Contract health rollup (reduced) | CAG-10.4 |
| CAG-EPIC-11 | Platform Services & Enterprise Administration | 11.1–11.5 |

### 3.2 RC10 MVP vs V2 for agreements

- **MVP:** epic 1; epic 2; 4.1 and 4.5; 8.1; 9.1; 11.1–11.3; CAG-5.1, 5.3, 5.5a.
- **V2 (cut line):** 3.x metering/invoicing/payments, 8.2–8.6, 4.4 and 9.2–9.7, 7.3–7.4, 11.4, 11.5 (exploratory).

### 3.3 Reuse checks required when filing

The source predates much of the platform. Before each CAG issue is filed it is checked against: *Apiome:
Monetization*, `ROADMAP_API_PRODUCTS_AND_APPLICATION_ACCESS.md`, `ROADMAP_CREDENTIAL_VAULT.md`, the audit log, and
CTG-3.3 push webhooks. Overlaps are linked and the CAG issue narrowed (not duplicated).

---

## 4. Private-suite issues that move

All are open in `apiome/private-suite`. The full table (Testing Epic 6 #1543–#1548, Test Lab #1040–#1044,
Contracts #402–#422, Pact epics #2298–#2304 and #2336–#2340, Epics 6–11 #2305–#2350) with the target `PFX` /
`CAG` id is in `ROADMAP_PACTFLOW_PARITY.md` §3. Method: **re-file in `apiome/apiome`** with the apiome issue
template (Documentation section, labels, RC10 milestone), then close the private-suite original with a link, so
history and comments stay readable at the source. `gh issue transfer` is not used because it drops the project
and milestone fields and would import the stale roadmap numbering and missing Documentation sections.
Not moved: Designer DCW-EPIC-4 (#2350) and V2-MCP-14.7 (#2297).

Private-suite housekeeping on approval: pointer banner on `FUTURE_FEATURE_ROADMAP_CONTRACTS.md` (done in this
draft) and ticks in the private-suite roadmaps when issues close, per AGENTS.md.

---

## 5. Already shipped and reused (not re-planned)

CTG-1.1–4.5 (classifier, diff CLI/action, consumer registry V251, consumer-aware analysis, provider verification
V252, scheduled verification V253, deploy-gate `/gate` V254), ECA-1.1–2.2 (suite compiler, target registry,
runner, CLI), XPC GraphQL/gRPC adapters, Pact **parse-only** import. The `PFX` roadmap §1 maps each to the issue
that extends it.

---

## 6. On approval — set-up steps

1. Create milestone **RC10** and the **RC10** Project (copy RC8's fields and board).
2. File the umbrella `[PFX]` and `[CAG]` issues, 7 + 11 epics, then the issues via the `create-issues` skill
   (Documentation section included; ~108 issues + epics). Add sub-issue links and the Project fields.
3. Re-file private-suite originals as in §4 and close them with links; update `Apiome: Contracts` (#114) and
   `Private Suite: Pact` (#53) project readmes to point at RC10.
4. Add the RC10 plan and roadmap links to `Apiome: Release Candidates` (#96).

## 7. Decisions needed

1. **Scope of the agreement half in RC10** — keep the MVP/V2 split in §3.2, or ship all of it?
2. **Base-URL shape** and HAL compatibility level (PFX roadmap §6).
3. **Re-file vs transfer** for private-suite issues (recommended: re-file).
4. **Hosted verifier in MVP** (recommended: yes).

## 8. Issue numbers

Umbrellas: PFX [#6906](https://github.com/apiome/apiome/issues/6906), CAG [#6966](https://github.com/apiome/apiome/issues/6966). Epics and issues are listed in the two roadmaps. The Apiome: RC10 project orders every ticket by *Rank*.
