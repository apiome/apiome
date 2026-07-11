# How do I… lint & check quality?

Apiome computes a **server-side quality score** (an A–F grade out of 100) plus itemized lint
findings for a version. The score is computed on the server so the UI and the CLI always agree —
there is no client-side scoring to drift. Use it before cutting and publishing a version.

---

## In the UI

Open the **Designer** at `/ade/studio`; the quality grade and findings are shown for the version you
are editing. Fix the findings (most are missing descriptions) and the grade updates.

## With the CLI

```bash
apiome lint --project <id-or-slug> --version <id-or-label>

# gate on a minimum grade (exit non-zero if below)
apiome lint --project <id-or-slug> --version <id-or-label> --min-grade B

# compare against a base version to surface breaking changes
apiome lint --project <id-or-slug> --version <id-or-label> --base-version <id-or-label>
```

`--min-grade` (A–F) makes the command suitable for CI gates; `--base-version` adds breaking-change
findings relative to that base.

## With the REST API

```http
GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint?baseRevisionId=<optional>
X-API-Key: <your-api-key>
```

Returns the numeric score, the letter grade, and a list of findings (e.g. undocumented classes,
breaking changes when `baseRevisionId` is supplied). Every finding carries a stable `rule` id
attributable to the built-in rule catalog.

### List the built-in rule catalog

```http
GET /v1/lint/rules
X-API-Key: <your-api-key>
```

Returns every registered built-in rule with its stable id, pack, category, default severity,
one-line rationale, and a docs anchor into [lint-rules.md](lint-rules.md). The catalog is the
same for every tenant; style guides layer per-tenant overrides on top of it.

## Verify

The grade and findings returned by the CLI match what the UI shows for the same version — that
consistency is the point of server-side scoring.

## Related

- [lint-rules.md](lint-rules.md) — reference for every built-in lint rule (ids, severities, rationales)
- [edit-classes-and-properties.md](edit-classes-and-properties.md) — clear "missing description" findings
- [publish-a-version.md](publish-a-version.md) — publishing enforces its own gates on top of lint
