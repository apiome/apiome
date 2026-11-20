---
title: "Arazzo workflow records"
description: "What an Arazzo import stores per workflow and step, and how to read it."
sidebar_position: 5.5
tags: [arazzo, workflows, rest, cli]
---

When you import an Arazzo document, Apiome stores each workflow and each of its steps as records of
their own, next to the revision that holds the document. Each step records the operation it calls
and whether that operation was found. The **Workflows** tab shows these records (see
[Arazzo workflows](../build/arazzo-workflows.mdx)). You can also read them with the REST API and
with `apiome arazzo`.

## Read them with the CLI

```bash
# The workflows of a project's revision, with how many steps resolved
apiome arazzo list --project checkout-flow --version 1.0.0

# One workflow: its sources and its ordered steps
apiome arazzo show checkout --project checkout-flow --version 1.0.0

# A catalog item's latest revision, or one revision by id
apiome arazzo list --catalog <item-uuid>
apiome arazzo list --catalog <item-uuid> --revision <version-uuid>

# Fail (exit 7) when a stored step did not resolve or a source is missing
apiome arazzo validate --project checkout-flow --version 1.0.0

# Check a local document against the Arazzo schema for its version, without a server
apiome arazzo validate checkout.arazzo.yaml
```

Put `--json` before the command (`apiome --json arazzo list …`) to get the REST response. Every
flag is listed in the [`apiome arazzo` reference](./cli/arazzo.md).

## Read them with the REST API

| Request | Returns |
| --- | --- |
| `GET /v1/workflows/{tenant_slug}/versions/{version_id}` | Every workflow of a revision, with its steps |
| `GET /v1/workflows/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}` | One workflow, by its `workflowId` |
| `GET /v1/workflows/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}/steps` | Its steps, in order, counted by resolution state |
| `GET /v1/workflows/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}/steps/{step_id}` | One step, by its `stepId` |
| `GET /v1/workflows/{tenant_slug}/catalog/{item_id}` | A catalog item's latest revision |
| `GET /v1/workflows/{tenant_slug}/catalog/{item_id}/revisions/{version_id}` | One revision of a catalog item |

`workflowId` and `stepId` are matched exactly, as Arazzo compares them. A revision outside your
tenant, or a `workflowId` or `stepId` it does not hold, returns `404`. A malformed revision or item
id returns `400`. A revision with no Arazzo document returns an empty `workflows` list. The request
and response schemas are on the [Arazzo workflows REST reference](./rest/arazzo-workflows.md).

## A workflow record

| Field | What it holds |
| --- | --- |
| `workflow_id` | The workflow's `workflowId`. |
| `summary`, `description` | As written in the document. |
| `ordinal` | The workflow's position in the document, from 0. |
| `inputs` | The workflow's `inputs` JSON Schema, as written. |
| `outputs` | The workflow's `outputs` map, as written. |
| `depends_on`, `success_actions`, `failure_actions` | `dependsOn`, `successActions` and `failureActions`, as written. |
| `sources` | The source descriptions its steps call, each with a status (see below). |
| `step_resolution` | Its steps counted by resolution state, for example `{"resolved": 2, "unresolved": 1}`. |
| `steps` | Its steps, in document order. |

## A step record

| Field | What it holds |
| --- | --- |
| `step_id` | The step's `stepId`. |
| `order_index` | The step's position in the workflow, from 0. |
| `target_kind` | `operation` (the step calls an operation), `workflow` (it calls another workflow) or `none`. |
| `operation_ref`, `operation_id` | The step's `operationRef` (or `operationPath`) and `operationId`, kept as written even when they did not resolve. |
| `target_workflow_id` | The `workflowId` the step calls, when `target_kind` is `workflow`. |
| `resolution_status` | Whether the target was found. See the next table. |
| `resolution_reason` | Why it was not found, when it was not. See the next table. |
| `operation` | The operation the step resolved to: `method`, `path`, `summary`, and the project and revision that hold it. `null` when the step did not resolve, or the operation has been deleted since the import. |
| `source_names` | The source descriptions the step's target points into. |
| `parameters`, `request_body`, `success_criteria`, `on_success`, `on_failure`, `outputs`, `depends_on` | As written in the document. |

## Resolution states

| `resolution_status` | `resolution_reason` | Meaning |
| --- | --- | --- |
| `resolved` | — | The target matches an operation Apiome holds. `operation` describes it. |
| `unresolved` | `unknown-operation` | No operation Apiome holds matches the target. The API it calls may not have been imported yet. |
| `unresolved` | `ambiguous-operation` | More than one operation matches, so none was picked. |
| `unresolved` | `unparsable-ref` | The `operationRef` could not be read as a reference to an operation. |
| `unresolved` | `no-operation-target` | The step names no operation to call. |
| `not_applicable` | `calls-workflow` | The step calls another workflow, so there is no operation to find. |
| `parse_error` | `malformed-step` | The step could not be read. The other steps were still stored. |

An unresolved step is not an import error. The import keeps the reference as written and reports
it as a warning. `apiome arazzo validate --project … --version …` fails on `unresolved` and
`parse_error` steps, and on `missing` sources.

## Source statuses

Each entry in `sources` is one `sourceDescriptions` entry of the document:

| `status` | Meaning |
| --- | --- |
| `resolved` | The import found the document. `tier` says where: `fileset`, `catalog` or `remote`. |
| `missing` | No tier found the document. `reason` gives a stable code; see [Import an Arazzo workflow with its API files](../bring-in/import-a-spec.md#import-an-arazzo-workflow-with-its-api-files). |
| `unknown` | The revision was imported before Apiome recorded where sources came from. |
