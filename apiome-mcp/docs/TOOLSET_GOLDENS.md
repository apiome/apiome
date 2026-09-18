# Tool-schema regression corpus (AGX-1.4)

**Ticket:** AGX-1.4 ([#4532](https://github.com/apiome/apiome/issues/4532)).
Suite: [`tests/test_toolset_goldens.py`](../tests/test_toolset_goldens.py). Runner, store
and checks: [`tests/toolset_corpus.py`](../tests/toolset_corpus.py).

The [operation→tool compiler](TOOL_COMPILER.md) decides what every tenant's agents see: the
tool names, descriptions and schemas. If a mapping change renames a tool or drifts a schema,
every served toolset breaks at once. The golden corpus pins the compiler's output for the
whole examples corpus, so a change like that fails CI and shows up in review as a diff.

## What is checked in

For each `valid` entry of the examples corpus (`apiome-ui/examples/corpus.manifest.json`)
there is one golden at `tests/golden/toolsets/<corpus path>.json`. For example,
`openapi/30-openapi-3.0-petstore.yaml` has its golden at
`tests/golden/toolsets/openapi/30-openapi-3.0-petstore.yaml.json`.

- **Content:** the entry's `McpToolset.serialize()` output, exactly: `mappingVersion` plus
  every tool (`name`, `description`, `inputSchema`, `operation`, `output`). Losses are not
  part of it, so rewording a loss never changes a golden.
- **Exposure:** the default. Every callable, non-deprecated operation is a tool, which is
  what a version serves before any AGX-1.2 curation.
- **Empty toolsets are goldens too.** A schema-only format (JSON Schema, Avro, …) compiles
  to `"tools": []`. If a normalizer change gives it operations, the golden shows that.
- **Selection** is the same as the IXH-1.6 canonical goldens. The suite uses apiome-rest's
  `corpus_loader` and `corpus_adapter_support`, so it never hard-codes a fixture path:
  - multi-file sets compile once, through their root;
  - an entry on `KNOWN_IMPORT_BUGS` is a strict xfail;
  - an entry whose adapter needs a bundled tool (`buf`, `asyncapi-parser`) that doesn't
    resolve is skipped, and its golden stays.

## The gates

| Gate | Test | Fails when |
|---|---|---|
| Determinism | `test_the_compiled_toolset_reproduces_its_golden` | recompiling an entry does not reproduce its golden **byte for byte**, or the golden is missing |
| MCP validity | `test_every_golden_tool_is_mcp_valid` | a stored tool fails `validate_mcp_tool`, the MCP SDK's `mcp.types.Tool`, or the JSON-Schema 2020-12 metaschema; an `output.schema` leaves the MCP keyword subset; a name repeats; `mappingVersion` is stale |
| Store hygiene | `test_no_golden_outlives_its_corpus_entry` | a golden has no corpus entry left |

The validity gate reads the **stored** files, not a fresh compile. So a hand-edited golden,
or one for an entry that is skipped here, is still checked.

A drift failure names each changed tool by the operation it invokes, then shows a short
diff:

```text
openapi/30-openapi-3.0-petstore.yaml: the compiled toolset no longer matches its golden.
  RENAMED 'listPets' → 'list_pets' (GET /pets)
  CHANGED 'createPet' (POST /pets): inputSchema
--- golden
+++ compiled
…
```

## Updating the goldens

Run this from `apiome-mcp/`:

```bash
uv run pytest tests/test_toolset_goldens.py --update-golden
```

It rewrites every golden that changed, adds goldens for new corpus entries and deletes
goldens whose entry is gone. Then:

1. Review `git diff tests/golden/toolsets`. This diff is the change every agent will see.
2. If a **mapping** change alters output for an unchanged spec, bump
   `MCP_TOOL_MAPPING_VERSION` in `apiome-rest/src/app/mcp_tool_mapping.py` and regenerate.
   A corpus fixture edit needs no bump.
3. Commit the goldens in the **same PR** as the change that caused them.

## CI

The suite is part of `uv run pytest` in the **Apiome MCP** workflow
(`.github/workflows/apiome-mcp.yml`), after ruff and mypy. That workflow runs on changes
to `apiome-mcp/**`, to `apiome-rest/**` (where the compiler lives) and to
`apiome-ui/examples/**` (the corpus). So a change to the compiler, or to a fixture, can't
merge without its goldens.

Before the tests run, the workflow installs the pinned `buf` and `asyncapi-parser` with
`apiome-rest/scripts/install_dev_toolchain.sh`. Without them, the protobuf, connectrpc and
asyncapi entries would skip. To run those entries locally, run the same script from
`apiome-rest/`.
