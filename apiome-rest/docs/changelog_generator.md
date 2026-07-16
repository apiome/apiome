# Changelog generator (CTG-1.3)

> **Status:** Library + publish persistence (`version_changelogs`, CTG-3.1)  
> **Issue:** [#4469](https://github.com/apiome/apiome/issues/4469) (renderer), [#4475](https://github.com/apiome/apiome/issues/4475) (publish persist)  
> **Epic:** CTG-EPIC-1 (#4459), CTG-EPIC-3 (#4461)  
> **Depends on:** CTG-1.1 classifier (`app.change_taxonomy`)

Turns a :class:`~app.change_taxonomy.ClassifiedDiff` into an ordered, grouped,
human-readable changelog. Downstream surfaces (CTG-2.2 PR comments, CTG-3.2 UI,
CTG-3.3 webhooks, browse pages, CLI markdown) should consume these renderers
rather than formatting classified changes ad hoc.

```
 ClassifiedDiff ──▶ build_changelog ──▶ Changelog
                         │                  ├─ render_changelog_markdown
                         │                  └─ render_changelog_json / _json_text
 version chain ──▶ changelog_since ─────────┘
 (label, doc)*
```

## Ordering (deterministic)

For the same input, entry order is stable:

1. **Severity:** breaking → non-breaking → docs-only
2. **Within severity:** `pathGroup` (lexicographic JSON-Pointer group)
3. **Within group:** `pointer`, then `ruleId`, then `changeKind`

Path groups collapse pointers to a surface key, e.g.:

| Pointer | `pathGroup` |
|---------|-------------|
| `/paths/~1pets/get/responses/200` | `/paths/~1pets` |
| `/components/schemas/Pet/properties/name` | `/components/schemas/Pet` |
| `/servers/0/url` | `/servers` |
| `/info/description` | `/info` |

## Public API

```python
from app.change_taxonomy import classify_openapi_changes
from app.changelog_generator import (
    build_changelog,
    changelog_since,
    render_changelog_markdown,
    render_changelog_json,
    render_changelog_json_text,
)

diff = classify_openapi_changes(base_doc, head_doc)
cl = build_changelog(diff, from_version="1.0.0", to_version="1.1.0")

md = render_changelog_markdown(cl)
payload = render_changelog_json(cl)  # schemaVersion = "ctg.changelog.v1"
```

### Since \<version\> aggregation

```python
cl = changelog_since([
    ("1.0.0", doc_v1),
    ("1.1.0", doc_v11),
    ("1.2.0", doc_v12),
])
# Classifies each adjacent hop, merges entries, re-sorts by severity → path.
# Aggregate fromVersion/toVersion = 1.0.0 → 1.2.0; per-entry hop labels preserved.
```

Also available: `aggregate_classified_diffs`, `aggregate_changelogs`.

## JSON schema (`ctg.changelog.v1`)

Stable camelCase keys for consumers:

```json
{
  "schemaVersion": "ctg.changelog.v1",
  "fromVersion": "1.0.0",
  "toVersion": "1.2.0",
  "counts": {
    "breaking": 1,
    "non-breaking": 1,
    "docs-only": 0,
    "unclassified": 0,
    "total": 2
  },
  "maxSeverity": "breaking",
  "entries": [
    {
      "severity": "breaking",
      "pathGroup": "/paths/~1pets",
      "pointer": "/paths/~1pets",
      "ruleId": "ctg.path_removed",
      "changeKind": "path_removed",
      "summary": "Path removed from the API surface.",
      "before": { "...": "..." },
      "after": null,
      "unclassified": false,
      "fromVersion": "1.1.0",
      "toVersion": "1.2.0"
    }
  ]
}
```

`render_changelog_json_text` emits sorted-key JSON for golden fixtures.

## Markdown shape

```markdown
# Changelog

**Since** `1.0.0` → `1.2.0`

_2 change(s): 1 breaking, 1 non-breaking, 0 docs-only._

## Breaking changes

### `/pets`

- **Path removed from the API surface** (`ctg.path_removed`) — `/paths/~1pets` _1.1.0 → 1.2.0_

## Non-breaking changes

### `/components/schemas/Pet`

- **Optional schema property added** (`ctg.property_added`) — `/components/schemas/Pet/properties/tag` _1.0.0 → 1.1.0_
```

## Modules

| Module | Role |
|--------|------|
| `app.changelog_generator` | Types, ordering, aggregation, md/json renderers |
| `app.change_taxonomy` | Classifier input (`ClassifiedDiff`) |
| `app.publication_changelog` | Publish-time persist into `version_changelogs` (CTG-3.1) |
| `app.version_changelog_routes` | Authenticated GET APIs over stored changelogs (CTG-3.2) |

**Publish persistence (CTG-3.1 / #4475):** after `db.publish_version` succeeds,
`generate_version_changelog_on_publish` runs as a FastAPI `BackgroundTasks`
hook (alongside the Mustache change-report pipeline). It reuses
`get_prior_published_baseline_revision_id`, classifies via CTG-1.1, renders
`ctg.changelog.v1`, and upserts `apiome.version_changelogs` (`ready` |
`initial` | `failed`). Failures never raise out of the hook. After V178,
backfill latest published revisions with
`PYTHONPATH=src python scripts/backfill_version_changelogs.py`.
**Read APIs (CTG-3.2 / #4476):** `GET /v1/versions/{tenant}/{project}/changelogs`
returns one summary row per published revision (status, `max_severity`, counts;
revisions without a stored row appear with `status: null` so UIs can render a
pending state), and `GET /v1/versions/{tenant}/{project}/{revision}/changelog`
returns the full stored `ctg.changelog.v1` payload with baseline labels. The
dashboard "Changes" tab and diff badges consume these; the public browse app
reads `version_changelogs` directly and serves per-project RSS / JSON Feed
changelog feeds.
