# Generalized spec-import job pipeline (MFI-1.2)

> **Status:** in-process adapter driver + engine routing — `src/app/import_source_pipeline.py`,
> `src/app/spec_import_engine.py`
> **Issue:** [#3734](https://github.com/objectified-project/objectified/issues/3734) ·
> **Epic:** MFI-EPIC-1 (#3716) · **Builds on:** [MFI-1.1](./import_source_spi.md) ·
> **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

The async spec-import job engine (`app.spec_import_engine`) used to be OpenAPI-shaped:
every job ran the `apiome-ui` `tsx` worker, which only knows how to import an
OpenAPI/Swagger document. MFI-1.1 introduced the [`ImportSource` SPI](./import_source_spi.md)
so a *format* is added by registering an adapter; MFI-1.2 makes the **job engine** drive
any such adapter through the existing submit → poll → commit/rollback lifecycle.

## The four phases

`app.import_source_pipeline.run_adapter_import_job(adapter, payload, …)` drives one
adapter through the SPI and returns a terminal `SpecImportJobStatus`:

```
 parse            normalize             version              lint
 raw text ─▶ native_ast ─▶ CanonicalApi ─▶ fingerprint ─▶ LintReport ─▶ summary
 (ImportSource.parse)  (.normalize)     (.fingerprint)   (.lint)
```

After every phase it awaits an optional `on_snapshot` coroutine (so the engine can
publish poll-visible progress) and checks an optional `is_canceled` predicate (so a
delete between phases stops the run). A `ImportSourceError` from `parse`/`normalize` is
a clean user-facing failure → a `failed` status; any other fault is converted to a
failed job by the engine wrapper. The work runs **inline** (not on a worker thread):
these adapters handle bounded new-format documents, and the one heavy path —
OpenAPI/Swagger — stays on the subprocess worker.

## Engine routing

`_drive_job` resolves which path runs a job from the request's `metadata.source_kind`:

```python
adapter = _resolve_inprocess_adapter(payload)   # registry lookup by source_kind
if adapter is not None:
    await _run_inprocess_adapter_job(job_id, adapter, payload)   # in-process pipeline
else:
    ...                                                          # tsx worker (unchanged)
```

- A source kind that resolves to a registered adapter **other than** a worker-backed
  one (`_WORKER_BACKED_ADAPTER_KEYS = {"openapi"}`) runs the in-process pipeline.
- OpenAPI/Swagger keep running on the `tsx` worker (it persists a full catalog
  project/version and carries its own benchmark instrumentation), so their existing
  tests are unchanged.
- An unrecognized source kind falls through to the worker exactly as before.

## What the contract looks like for an adapter job

The in-process path is **preview-only**: it does not write to the catalog —
canonical→catalog persistence per format is a later epic (the format epics MFI-1.2
*blocks*). So:

- the job reaches `completed` with `percent: 100` and a `summary` carrying the
  revision `fingerprint`, `paradigm`/`format`, entity `counts`, the `lint`
  score/grade/finding-count, and the requested `dry_run`/`incremental_mode` flags
  (`persisted: false`);
- `result` identifiers (project/version) are absent, so `POST …/commit` returns `409`
  (nothing to commit yet) and `rollback` is unavailable — consistent with the existing
  state-machine semantics;
- `dry_run` and `incremental_mode` are recorded in the event stream and summary; with
  no writes yet, both behave identically while the persistence hook is pending.

Adapter phase events (`ADAPTER_INIT`, `PARSE_OK`, `NORMALIZE_OK`,
`VERSION_FINGERPRINT`, `LINT_COMPLETED`, `IMPORT_COMPLETED`, plus `DRY_RUN` /
`INCREMENTAL_MODE`) surface at INFO in the REST logs alongside the worker's
`PHASE_TIMING`/`BENCHMARK` codes.
