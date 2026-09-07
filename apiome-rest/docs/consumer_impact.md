# Consumer-aware breaking analysis — CTG-4.2 (#4480)

CTG-1.1 grades a change against the whole published surface, because nothing tells it who uses
what. That verdict makes every breaking change an incident: "47 breaking changes" tells the
provider to panic and the consumer nothing. CTG-4.1 registered the missing half — what each
consumer declared it uses. This is the join.

The question it answers is the one that gates a release: **whose build does this break?**

```
breaks 2 of 7 consumers: billing-service, mobile-app
```

| Module | What it owns |
|---|---|
| `app.consumer_impact` | The analysis. Pure: pointer algebra, attribution rules, report models, markdown. |
| `app.consumer_impact_service` | The one place the registry is read for an analysis. |
| `app.classified_diff_routes` | `POST /v1/diff/{tenant}/classified` with `consumers: true`. |
| `apiome-cli` `diff --consumers` | The CI report. |

Nothing was added to the database. A verdict is derived from a stored contract and a diff, and
both already exist.

## How a change is attributed

Both sides speak the same JSON Pointer vocabulary — CTG-4.1 stores pointers written exactly the
way `app.change_taxonomy_enum` writes them — so attribution is a pointer comparison, not a
re-derivation of what a change touched.

Overlap is **segment-aware**: `/components/schemas/Pet` covers
`/components/schemas/Pet/properties/name` but *not* `/components/schemas/PetFood`. This is
stricter than `db.find_consumer_contracts_by_pointers`, whose `starts_with` may over-select; the
SQL only narrows the candidate set, this module renders the verdict.

Overlap is tested **both ways**, because a change and a declared field are not always at the same
depth: a change at `/components/schemas/Pet` touches a field at `…/Pet/properties/name`, and a
change at `…/properties/name/type` touches the field declared at `…/properties/name`.

Three match kinds, most specific first:

| Match | When | Example |
|---|---|---|
| `field` | The change overlaps a declared field's `pointer` **or** its `schema_pointer` | `…/schema/properties/name` removed, and the consumer reads `name` |
| `operation` | The change is at or above a declared operation, or inside one at a node that reaches every caller | `/paths/~1pets` removed; a newly required parameter; a removed response code; the schema root replaced |
| `document` | The change is under `/security`, `/servers` or `/components/securitySchemes` | auth tightened for everybody |

Field matches win when there are any — reporting the operation as well would count the same change
twice.

### The exclusion is the point

A change **inside a body schema**, on an operation whose consumer declared which fields it reads,
attributes only when one of those fields is met. Removing a field nobody reads breaks nobody. That
single rule is what turns a whole-spec verdict into a gating decision.

Two deliberate exceptions keep it from under-reporting:

* **An operation declared with no fields is operation-wide throughout.** Nothing finer than "I call
  this" was declared, so nothing finer is claimed.
* **`/parameters/…` is always operation-wide.** A newly required query parameter breaks every
  caller, whether or not they thought to declare it.

### Known limitation

A change under `/components/schemas/…` reaches a consumer only through a declared field's
`schema_pointer`. A contract that declared an operation but no fields cannot be linked to the
components its body `$ref`s, so such a change is reported unattributed for that consumer.
Declaring fields — which the Pact importer and the UI picker both do — resolves it.

## The denominator

"Breaks 2 of 7" is a claim about seven services. A consumer registered without a current contract
cannot be counted as safe, so it is **not** in the denominator; it is reported beside it:

```
breaks 1 of 5 consumers: billing-service (2 registered consumers have declared no surface)
```

Its verdict is `undeclared`, which is a statement about the registry, not about the change.

## Verdicts

| Verdict | Meaning |
|---|---|
| `breaking` | At least one breaking change meets the declared surface |
| `non-breaking` | Something meets it, worst severity non-breaking |
| `docs-only` | Only documentation changes meet it |
| `unaffected` | The change set touches nothing this consumer declared |
| `undeclared` | Registered, but has never declared a surface |

Each verdict also carries `contract_matches_base`: whether the surface was resolved against the
same revision the diff is based on. A stale contract still yields the best available answer, but
it is flagged rather than silently equated.

## The response

`POST /v1/diff/{tenant_slug}/classified` with `consumers: true` (needs `consumer_contracts:view`
in addition to `versions:view`) adds two things:

* `consumers` — the report: `summary`, `counts`, one verdict per live consumer,
  `breakingConsumers`, and `attribution`.
* `consumers` on **each change** — the handles it touches. `null` when the analysis was not
  requested; `[]` is the "no registered consumer affected" flag.

`attribution` lists every change with the consumers it touches and is **exact**. A consumer's
`impacts` list is capped at `MAX_IMPACTS_PER_CONSUMER` (one change can meet forty declared fields);
its `counts` and the attribution stay exact when it is, and `truncated` says so.

`counts` keys are `snake_case` — they name tallies rather than model fields, exactly as
`ClassifiedDiff.counts` does:

| Key | Meaning |
|---|---|
| `consumers_total` | Live consumers registered on the project |
| `consumers_declared` | …of which have a current contract (the denominator) |
| `consumers_undeclared` | …of which do not |
| `consumers_affected` | Consumers the change set touches at all |
| `consumers_breaking` | Consumers it breaks |
| `changes_total` / `changes_attributed` / `changes_unattributed` | Change tallies |

Asking for markdown (`Accept: text/markdown`) appends a **Consumer impact** section to the CTG-1.3
changelog.

The consumers considered are those registered against the **base** project — the published
contract they declared against — whether the head side is stored or an inline candidate.

## In CI

```bash
apiome diff ./openapi.yaml --against payments-api@latest --consumers
```

```
  [breaking] ctg.property_removed /components/schemas/Pet/properties/name — breaks billing-service

Consumer impact: breaks 1 of 2 consumers: billing-service
  breaks billing-service
    [breaking] GET /pets — 200 response `name` (ctg.property_removed)
  mobile-app: unaffected
```

The **exit code is unchanged**. `--fail-on` still grades the whole specification, so a build never
passes merely because nobody has registered as a consumer yet. Gating *on* a consumer verdict is
CTG-4.5's aggregate endpoint, which reads this report.

See also: [`consumer_contracts.md`](consumer_contracts.md), [`change_taxonomy.md`](change_taxonomy.md),
[`changelog_generator.md`](changelog_generator.md).
