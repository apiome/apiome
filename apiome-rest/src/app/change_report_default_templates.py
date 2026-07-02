"""
Bundled Mustache templates for publication change reports (CR-03, #2701).

The same strings are seeded as the system row in ``change_report_template_versions``
(semver **1.0.0**, well-known id :data:`SYSTEM_TEMPLATE_ID`).
"""

from __future__ import annotations

# Well-known UUID for the system default template version (seeded at startup / migration).
SYSTEM_TEMPLATE_ID = "00000000-0000-4000-a000-000000000001"
SYSTEM_TEMPLATE_SEMVER = "1.0.0"

DEFAULT_HEADER_TEMPLATE = """# {{productName}}

**From:** {{fromVersionLabel}} → **To:** {{toVersionLabel}}

_Published:_ {{publishTimestamp}} · _Diff schema:_ {{schemaVersion}}
"""

DEFAULT_BODY_TEMPLATE = """## Summary

| | Count |
|--|--:|
| Schemas added | {{schemaCounts.added}} |
| Schemas removed | {{schemaCounts.removed}} |
| Schemas modified | {{schemaCounts.modified}} |
| Property changes | {{propertyCount}} |
| Reference changes | {{referenceCount}} |
| Relationship changes | {{relationshipCount}} |
| Documentation changes | {{documentationCount}} |
| Warnings | {{warningCount}} |
| Skipped areas | {{skippedCount}} |

## Schemas

### Added
{{#schemas.added}}
- `{{name}}`
{{/schemas.added}}

### Removed
{{#schemas.removed}}
- `{{name}}`
{{/schemas.removed}}

### Modified
{{#schemas.modified}}
- `{{name}}`
{{/schemas.modified}}

## Properties
{{#properties}}
- **{{schemaName}}** `{{path}}` — _{{changeKind}}_
{{/properties}}

## References
{{#references}}
- **{{schemaName}}** — _{{changeKind}}_{{#baselineRef}} (`{{baselineRef}}` → `{{candidateRef}}`){{/baselineRef}}
{{/references}}

## Relationships
{{#relationships}}
- **{{schemaName}}** `{{path}}` — _{{changeKind}}_{{#detail}} ({{detail}}){{/detail}}
{{/relationships}}

## Documentation
{{#documentation}}
- _{{scope}}_ / `{{field}}` — {{changeKind}}
{{/documentation}}

## Warnings
{{#warnings}}
- `{{code}}`: {{message}}
{{/warnings}}

## Not diffed (MVP)
{{#skipped}}
- {{reason}}{{#path}} at `{{path}}`{{/path}}
{{/skipped}}
"""

DEFAULT_FOOTNOTE_TEMPLATE = """_{{#staticNote}}{{staticNote}}{{/staticNote}}{{^staticNote}}Apiome change report.{{/staticNote}}_

Generator: **{{generatorVersion}}**
"""
