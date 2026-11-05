---
title: Export over MCP
description: Let an AI agent export a version to any format, with its fidelity report.
sidebar_position: 5.15
---

An agent connected to Apiome's [MCP server](../getting-started/connect-an-mcp-host.mdx) can export an
artifact version to **any** format Apiome exports to — the same pipeline as the
[Export dialog](./export-dialog.mdx) and [`apiome export`](./export-from-the-cli.md). Two tools cover
every format, so a new export format is available to agents as soon as Apiome supports it:

| Tool | What it does |
| --- | --- |
| `export.targets` | Lists every export target for an artifact version, each with its fidelity tier and preserved share for this source, its options and their defaults. |
| `version.export` | Exports the version to one target and returns the files and the fidelity report. |

Both need an MCP API key. They export within the key's own workspace, and only artifacts the key's
scope includes.

## Pick a target

Call `export.targets` with the artifact's id, and a `version` (a revision id or label) unless you want
the latest:

```json
{ "artifact": "0b7c2a4e-5d1f-4e8a-9c3b-2f6d8e1a7b90", "version": "1.4.0" }
```

Each entry in `targets` has the target's `descriptor` (its `key`, format and label), its `fidelity`
(`tier`: lossless, lossy or types-only, and how much it preserves) and its `options_schema` with
`default_options`. Pass a `descriptor.key` to `version.export`.

## Export

Call `version.export` with the artifact, the target key and, optionally, `version`, `options`,
`allow_lossy` and `confirm`:

```json
{ "artifact": "0b7c2a4e-5d1f-4e8a-9c3b-2f6d8e1a7b90", "target": "graphql", "options": {} }
```

The answer carries:

| Field | What it holds |
| --- | --- |
| `state` | `completed`, `failed`, `blocked` when a lossy export was not allowed (below), or `running` / `queued` when the export outlived the wait. |
| `advisory` | The fidelity advisory, word for word what the Export dialog, the browse page and `apiome export` show. |
| `fidelity` | The structured fidelity report: `summary` (tier and preserved share), `report` (every construct the conversion drops, approximates or invents, with its severity) and `advisory` (the warning a person would see). |
| `guard` | The transcoding guard: how severe the conversion is, and whether it needs `confirm`. |
| `files` | Each emitted file's `path`, `mediaType` and `sizeBytes` — and its `content` when `contentInline` is true. |
| `downloadPath` | The REST download of the whole export, for output too large to return inline (over 256 KiB). |
| `error` | Why a `failed` export failed, with a stable `code`. |

## Lossy exports need allow_lossy

When the target cannot carry everything the source has (its tier is lossy or types-only), `version.export`
emits nothing unless you pass `"allow_lossy": true` — like `--force` on `apiome export`. Without it the
answer is `"state": "blocked"`, with no `jobId` and no `files`, carrying:

- `advisory`: what the export would lose, in the same words a person sees;
- `fidelity.report`: every construct it drops, approximates or invents, with its severity;
- `error.code`: `mcp-export-lossy-not-allowed`.

Read the advisory and the report, then call again with `"allow_lossy": true` to export anyway. A lossless
target exports without it.

```json
{ "artifact": "0b7c2a4e-5d1f-4e8a-9c3b-2f6d8e1a7b90", "target": "asyncapi", "allow_lossy": true }
```

A severe conversion (most of the source lost) also fails unless you pass `"confirm": true` — the same
acknowledgement the Export dialog asks a person for. Options are checked against the target's
`options_schema`; an unknown target or an invalid option is refused with the reason.

## Long exports

`version.export` waits up to 60 seconds for the export. If it is still running, the answer is
`"state": "running"` with a `jobId`. Call `version.export` again with only `job_id` to collect it:

```json
{ "job_id": "2ffbeb4f-3187-4f82-8cbe-e8bbf5bc2075" }
```

## Set it up

The MCP server runs exports through apiome-rest. On a self-hosted install, set on the `mcp` service:

| Variable | Value |
| --- | --- |
| `APIOME_MCP_REST_INTERNAL_URL` | apiome-rest as the MCP server reaches it — `http://rest:8000` in the Docker Compose stack (the default there) |
| `APIOME_MCP_REST_INTERNAL_SERVICE_TOKEN` | apiome-rest's `INTERNAL_SERVICE_TOKEN`, byte for byte (the Compose stack passes it through) |
| `APIOME_MCP_EXPORT_WAIT_SECONDS` | How long `version.export` waits before answering `running` (default 60, at most 300) |

Without them, both tools answer that export over MCP is not configured. `APIOME_MCP_EXPORT_INLINE_MAX_BYTES`
on apiome-rest sets the inline limit (default 262144). Every argument and field is in the
[MCP tool reference](/reference/mcp/tools#export-targets).
