---
title: "Project export format"
description: "The document apiome projects export writes: sections, ordering and determinism."
sidebar_position: 5
tags: [cli, export]
---

`apiome projects export <slug-or-id>` writes a whole project — every version with its classes and
paths, the property library, tags and migration plans — as **one document**. This page specifies
that document: format **`apiome.project-export`**, **`exporterVersion: 1`**. A future import command
will check `exporterVersion` before reading a file.

```bash
apiome projects export payments-api --output ./backups/payments-api.json
# ✔ Exported 8 versions, 24 classes, 142 properties, 18 paths, 5 tags, 2 migration plans
#   → ./backups/payments-api.json (4.2 MiB, deterministic SHA-256: 7f2c…a041)

apiome projects export payments-api --format yaml --gzip > backup.yaml.gz
```

The summary goes to **stderr**; stdout carries only the document, so it can be piped.

## Options

| Option | What it does |
| --- | --- |
| `--output`, `-o <file>` | Write to a file instead of stdout. The file appears under its name only once it is complete. |
| `--include <sections>` | Comma-separated sections to export. Default: all of them. |
| `--exclude <sections>` | Comma-separated sections to leave out. |
| `--versions <labels>` | Only these versions, by label — `2.0.0` and `v2.0.0` both match. |
| `--format json\|yaml` | `json` (default) is written as it is fetched, one version at a time; `yaml` is built in memory first. |
| `--gzip` | Compress the output. The gzip bytes are reproducible too (no timestamp or file name inside). |
| `--deterministic` / `--no-deterministic` | Deterministic (default): keys sorted, no timestamp — the same project state gives byte-identical output. `--no-deterministic` keeps the server's key order and adds `exportedAt`. |

Sections: `versions`, `classes`, `properties`, `paths`, `tags`, `migrations`. `classes` and `paths`
belong to versions, so they need `versions` too. A `data` section (data records) is **not available
yet** — the API cannot list a project's data records — and `--include data` is refused.

## The document

A single JSON object (or the same structure in YAML). With `--deterministic` it is written in
canonical form — UTF-8, keys sorted at every level, no whitespace between tokens, one trailing
newline — so its SHA-256 identifies the project's state.

| Key | Present | Value |
| --- | --- | --- |
| `exporterVersion` | always | `1` |
| `format` | always | `"apiome.project-export"` |
| `exportedAt` | `--no-deterministic` | When the export ran (ISO 8601, UTC). |
| `project` | always | The project, as `GET /v1/projects/{tenant}/{project}` returns it. |
| `sections` | always | The sections exported, e.g. `["versions","classes","properties","paths","tags","migrations"]`. |
| `versionsFilter` | `--versions` | The labels of the versions exported. |
| `properties` | `properties` | The project's property library (`GET /v1/properties/{tenant}/{project}`). |
| `tags` | `tags` | `{ "classTags": […], "versionTags": […] }` — the class-tag library and the version tags. Under `--versions`, only version tags pointing at an exported version. |
| `migrations` | `migrations` | Every migration plan: `{ id, from_version_id, to_version_id, created_at, updated_at, rules: [{ class_name, source_property, rule }] }`. Under `--versions`, only plans between two exported versions. |
| `versions` | `versions` | One entry per version, **oldest first**: `{ "version": {…}, "classes": […], "paths": […] }`. |

Each `versions[]` entry:

| Key | Present | Value |
| --- | --- | --- |
| `version` | always | The version (`GET /v1/versions/{tenant}/{project}`): its record `id`, its label `version_id`, `published`, `visibility`, lineage, `created_at`… |
| `classes` | `classes` | Every class of the version, each with `properties` (with the library property each one uses) and `tags` inline — `GET …/classes/{tenant}/version/{version}/with-properties-tags`. |
| `paths` | `paths` | Every path, ordered by `pathname`, each with its `operations` in full — parameters, request body and responses (`GET …/paths/{tenant}/{version}/{path}/full`). |

Ids are the server's UUIDs; references between sections (a class's `version_id`, a migration
plan's `from_version_id`, a version tag's `version_id`) use them.

## Determinism

The same project state exports to the same bytes because:

- keys are sorted at every level and there is no whitespace or timestamp;
- versions are ordered by creation time (then id), paths by `pathname`, and every list the server
  returns — classes, properties, tags, plans and their rules — is already in a fixed order;
- gzip output is written with no timestamp and no file name.

Any change to the project — an edited class, a new version, a re-publish — changes the SHA-256.

## Versioning

`exporterVersion` changes only for an incompatible change to this structure (a section renamed or
re-shaped). Fields the server adds to a project, version, class or path appear in the export without
a version change, since those objects are exported as the API returns them.
