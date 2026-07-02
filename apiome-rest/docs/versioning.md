# Versioning + Tagging Reuse (MFI-3.4)

> **Status:** pure version-on-change decision over the canonical model — `src/app/versioning.py`
> **Issue:** [#3745](https://github.com/objectified-project/objectified/issues/3745) ·
> **Epic:** MFI-EPIC-3 (#3718) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

Each imported artifact should get a dated version **only when its fingerprint changes**:
re-importing an unchanged document mints nothing, while a real change produces one dated
version plus the diff that explains it. The MCP catalog already solved this for discovered
endpoints (version-on-change V2-MCP-18.3 and date/time tagging V2-MCP-18.4). This module
lifts that *decision* out of the MCP-specific path and generalizes it over the
[`CanonicalApi`](./canonical_model.md) model, so every importable format gets the same
behavior — **no new mechanism**, just the proven recipe applied to the canonical model.

```
fingerprint(model) ─▶ compare to previous.fingerprint ─▶ VersionDecision
                       │   equal      → SKIP  (mint nothing; current_version unchanged)
                       │   different  → CREATE (dated version_tag + ModelDiff)
                       └─ no previous → CREATE (initial; no diff to compute)
```

## The decision: `decide_version(...)`

```python
from app.versioning import decide_version, PreviousVersion

decision = decide_version(
    model,                       # the freshly normalized CanonicalApi being imported
    previous=PreviousVersion(    # the artifact's current version (None on first import)
        version_tag="2026-06-25T09:00Z",
        fingerprint="sha256:…",  # the stored semantic fingerprint to compare against
        model=current_model,     # optional; supply it to also get the before→after diff
    ),
    when=import_time,            # import timestamp (passed in — the module reads no clock)
    existing_tags=used_tags,     # tags already used for this artifact (collision avoidance)
)
```

It composes the three EPIC-3 primitives already in place:

- **fingerprint** ([MFI-3.1](./fingerprint_spi.md)) — the stable semantic hash that
  *identifies* a revision. An unchanged re-import is detected by string equality against
  the previously stored fingerprint, exactly the MCP `previous.surface_fingerprint ==
  fingerprint` test, but over the canonical model. It is doc- and order-insensitive, so a
  description-only edit never mints a version.
- **diff** ([MFI-3.2](./diff_spi.md)) — when the fingerprint changed *and* the previous
  model was supplied, the structured before→after `ModelDiff` the new version carries
  (oriented previous → new).
- **date/time tag** — a minute-precision UTC tag (see below).

## `VersionDecision`

| Field                  | Meaning                                                                      |
|------------------------|------------------------------------------------------------------------------|
| `action`               | `VersionAction.CREATE` or `VersionAction.SKIP`.                              |
| `changed`              | Whether the import differs from the current version (`True` on a first import). |
| `is_initial`           | Whether this is the artifact's first version (no previous).                   |
| `fingerprint`          | The new import's `FingerprintResult` (semantic + any per-format hash) to store. |
| `previous_fingerprint` | The fingerprint compared against; `None` on the initial import.              |
| `version_tag`          | The date/time tag minted for the new version; `None` on a skip.             |
| `current_version_tag`  | The tag the artifact's `current_version` should point at afterward.         |
| `diff`                 | The before→after `ModelDiff`; present on a change with a previous model.     |

`created` is sugar for `action is VersionAction.CREATE`.

### Decision table

| Situation                                     | `action` | `version_tag` | `diff`            | `current_version_tag` |
|-----------------------------------------------|----------|---------------|-------------------|-----------------------|
| First import (`previous is None`)             | CREATE   | new tag       | `None` (nothing to compare) | new tag       |
| Unchanged re-import (fingerprint matches)     | SKIP     | `None`        | `None`            | previous tag (held)   |
| Changed re-import, previous model supplied    | CREATE   | new tag       | previous → new    | new tag               |
| Changed re-import, no previous model          | CREATE   | new tag       | `None`            | new tag               |

The `current_version` pointer advances **only on a change** — mirroring how
`mcp_endpoints.current_version_id` is left untouched on a no-change discovery and updated
when a new snapshot is recorded.

## Date/time tags

`format_version_tag(when)` produces a compact, minute-precision UTC label such as
`2026-06-26T14:03Z` (naive timestamps are treated as UTC; aware ones are converted), the
generalized form of the MCP tagger's `format_mcp_version_tag`.

`mint_version_tag(when, existing_tags)` adds same-minute collision handling: when the base
tag is already used, the next version gets the lowest free `-2` / `-3` / … suffix, exactly
as `Database._next_mcp_version_tag` disambiguates same-minute snapshots. `decide_version`
always treats `previous.version_tag` as taken, so a change landing in the previous
version's minute never reuses its tag.

## Purity

The module is **pure**: no DB, no network, and it reads no clock — the import time and the
previously recorded version are inputs. That keeps version-on-change unit-testable the same
way the sibling [fingerprint](./fingerprint_spi.md) / [diff](./diff_spi.md) /
[breaking-change](./breaking_change_spi.md) modules are, and lets the persistence wiring
(the per-format catalog write — MFI-2.2 `api_artifacts` and the format epics) reuse one
audited decision instead of re-deriving "did this change?" per format. The persistence
layer is responsible for the actual `versions` / `version_tags` row writes that the
decision describes.

## Tests

`tests/test_versioning.py` (27 tests): no-change-skips and change-creates-dated-version+diff
per paradigm (REST / event / graph), doc-only-edit skips, diff orientation and removal,
fingerprint-only deciding without a previous model, same-minute tag collision suffixing,
the `current_version` pointer advancing only on a change, determinism, and JSON round-trip.
