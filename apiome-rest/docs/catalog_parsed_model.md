# Catalog Parsed Model (MFI-25.2)

> **Status:** Reference implementation — `src/app/catalog_parsed_model.py`
> **Issue:** [#4087](https://github.com/objectified-project/objectified/issues/4087) ·
> **Epic:** MFI-EPIC-25 (#4078) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT_UI.md` › MFI-25.2

The catalog **item detail** response (`GET /v1/catalog/{tenant_slug}/{item_id}`) carries a `parsed`
array: a **normalized, paradigm-tagged entity list** derived from the item's canonical model
([canonical_model.md](canonical_model.md), MFI-EPIC-2). It lets the detail Overview (MFI-25.3) render
the actual parsed entities — operations, types, services, messages, channels, with their fields —
instead of only the aggregate `summary` counts (MFI-23.9).

The shape is **presentation-agnostic**: no colors, ordering hints, or markup — just the parsed
structure. All styling (tag colors per paradigm, truncation, "N shown of M") is the renderer's job.

## Shape

```jsonc
"parsed": [                          // list of entity GROUPS (empty [] when no model)
  {
    "title": "Operations",           // group heading
    "subtitle": "root fields on …",  // optional sub-line (nullable)
    "entities": [                     // the entities in this group
      {
        "name": "orders",            // entity name
        "tag": "QUERY",              // paradigm-specific kind (see below)
        "meta": "→ [Order]",         // short human hint (nullable)
        "fields": [                   // field rows (may be empty)
          {
            "name": "status",        // field name
            "type": "OrderStatus",   // rendered type (see "Type rendering")
            "description": "…",      // nullable
            "required": false         // outer non-nullability
          }
        ]
      }
    ]
  }
]
```

Every group has `title` / `subtitle` / `entities`; every entity `name` / `tag` / `meta` / `fields`;
every field `name` / `type` / `description` / `required`. Empty groups are **dropped**, so a group is
never emitted with zero entities, and an absent/empty/unreconstructable model degrades to `[]`.

Response schemas: `CatalogParsedGroup` → `CatalogParsedEntity` → `CatalogParsedField` (see
`openapi.yaml`).

## Grouping per paradigm

Entities are grouped the way each paradigm reads most naturally. Tags are derived from the canonical
model (operation kind, type kind, streaming mode, the GraphQL `graphql_type` extra).

| Paradigm | Groups | Entity tags |
|----------|--------|-------------|
| **GraphQL** (`graph`) | `Operations`, `Types` | `QUERY` / `MUTATION` / `SUBSCRIPTION`; `OBJECT` / `INPUT` / `INTERFACE` / `ENUM` / `UNION` / `SCALAR` |
| **gRPC** (`rpc`) | `Services & methods`, `Messages` | `SERVICE` (methods are its field rows); `MESSAGE` / `ENUM` |
| **AsyncAPI** (`event`) | `Channels`, `Operations`, `Messages` | `CHANNEL`; `SEND` / `RECEIVE`; `MESSAGE` |
| **any other** (`rest`, `data_schema`) | `Operations`, `Types`, `Channels` (whichever are present) | HTTP verb or operation kind; type kind |

Notes:

- **gRPC** puts *methods* as field rows under each service; a field's `type` is the method signature
  `(Request) → Response`, with `stream` on a streaming side (e.g. `(Reading) → stream Reading`).
- **AsyncAPI** messages are inline `payload_schema` on operation messages (not named `types`), so the
  `Messages` group is built from the operations' payload schemas.
- A protobuf field's number is appended to its `type` (e.g. `string #1`).

## Type rendering & `required`

`type` is a compact, presentation-agnostic rendering of the canonical `TypeRef`:

- a leaf renders its type name (`OrderStatus`, `string`);
- a list nests with `[...]` (`[Order]`, `[String]`);
- nullability is **not** baked into the string — it is surfaced separately as `required` (a
  non-nullable field/argument is `required: true`), so the renderer decides how to mark optionality
  (e.g. re-adding a GraphQL `!`).

For AsyncAPI message fields (JSON Schema payloads), `type` shows the schema `type` with a `format`
hint in parentheses (`string (uuid)`) and arrays as `[...]`; `required` comes from the payload's
`required` list.

## Derivation & degradation

The model is reconstructed on read from the item's **captured source** using the same
parse → normalize path the convert endpoint uses (MFI-22.6, `catalog_conversion.build_conversion_source`),
then projected by `derive_parsed_model`. Any failure — no captured inline source, URL-only source,
unknown format, or unparseable text — is swallowed and yields `parsed: []` (a *read* never errors on a
missing or broken model, unlike the convert path, which surfaces these as HTTP errors).

Entry points (`src/app/catalog_parsed_model.py`):

- `derive_parsed_model(api)` — the pure projection `CanonicalApi -> [group, …]` (`[]` for `None`/empty).
- `reconstruct_catalog_api(item)` — rebuild the canonical model from a catalog item, or `None`.
- `derive_catalog_parsed_model(item)` — reconstruct + project (`[]` on any failure).
