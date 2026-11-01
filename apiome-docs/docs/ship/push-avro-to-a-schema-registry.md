---
title: "Push Avro to a schema registry"
description: "Register an Avro export's subjects on a Confluent-compatible schema registry."
sidebar_position: 5.6
tags: [export, avro, schema registry, confluent, karapace, apicurio, kafka, connector]
---

An Avro export writes one `.avsc` schema per type. Each schema has a **subject**, the name a
Confluent-compatible schema registry files it under. A **push** exports a version to Avro, checks it,
and registers each subject on a registry for you. It works with Confluent Platform or Cloud, Karapace,
or Apicurio Registry's compatibility API.

A push goes through a [schema registry connector](../bring-in/schema-registry-connector.md) you
have already added. It uses that connector's URL and stored credentials, so the push needs no
credentials of its own. It is protected against internal addresses in the same way the connector's
syncs are. Pushing is available from the REST API only.

## Before you push

- **A connector.** Add a `schema-registry` connector for the registry. See
  [Add the connector](../bring-in/schema-registry-connector.md#add-the-connector). Its credentials
  must be allowed to register schemas, not only to read them.
- **Permission.** A push uses the connector's credentials to write to the registry, so you need
  `imports:edit`: the same permission as changing the connector. A dry run needs it too.
- **Subjects.** The subject comes from the Avro options:
  - `record_name` (the default) gives `{namespace}.{Type}-value`, one subject per type;
  - `topic_record_name` with a `topic` gives `{topic}-{namespace}.{Type}-value`;
  - `subject_role: "key"` ends a subject in `-key` instead of `-value`.

  `topic_name` gives every type the same subject (`{topic}-value`). A subject holds one schema, so a
  push of more than one type with `topic_name` is refused.

## Push

```http
POST /v1/export/{tenant_slug}/avro/push
Content-Type: application/json

{
  "artifact": "<project id>",
  "version": "1.0.0",
  "connector_id": "<schema-registry connector id>",
  "options": { "subject_naming": "record_name" },
  "dry_run": true
}
```

1. **Export and check.** The version is exported to Avro (`.avsc`) and checked with fastavro, the
   same check every Avro export runs (see [How an export is checked](./check-an-export.mdx)). If the
   export fails its check, the push stops with `EMITTED_ARTIFACT_INVALID` and its problems, and nothing
   is sent to the registry.
2. **Order.** Some schemas name a type from another schema: a `Widget` with an `owner` of type `Owner`,
   for example. That schema is registered after the one it names. It is registered with a
   Confluent **reference** (`{name, subject, version}`) to that schema's subject.
3. **For each subject:**
   1. **Look it up.** If the registry already holds this exact schema under the subject, nothing is
      written. The result is `already_registered`, with its schema id and version.
   2. **Check compatibility.** The schema is checked against the subject's latest version, under the
      subject's compatibility level on the registry. A schema that breaks it is `incompatible`. The
      registry's messages are included, and the schema is not registered. A subject the registry
      doesn't have yet has nothing to check against.
   3. **Register.** The result is `registered`, with the new schema id and version.

Set `"dry_run": true` to look up and check every subject without registering anything. Run a dry run
first. Pushing the same version again changes nothing: every subject comes back `already_registered`.

A severe conversion needs `"confirm": true`, as it does for an [export job](./export-jobs.mdx). An
OpenAPI or gRPC source exports only its schemas to Avro, without its operations: see
[Understand export fidelity](./export-fidelity.md).

## Read the result

The response has a `summary` that counts each status, and one entry per subject in the order the
subjects were pushed. Each entry has its `subject`, `file`, `status`, `schema_id`, `version`,
`references` and `messages`.

| Status | What it means |
| --- | --- |
| `registered` | The schema was registered now. |
| `already_registered` | The registry already held this exact schema under the subject; nothing was written. |
| `would_register` | Dry run: the schema passed its check and would be registered. |
| `incompatible` | The subject's compatibility level refused the schema; it was not registered. |
| `failed` | The registry refused the schema or did not answer; `messages` has its reply. |
| `skipped` | The schema references a subject that did not register, so it was not pushed. |

In a dry run, some schemas reference a schema that the same push would register. The registry can't
check those yet, because the version they would reference doesn't exist. They show
`would_register` with `compatibility: "unchecked"`.

The response is `200` whenever the push ran, even if some subjects failed. A push that registered at
least one subject is recorded in the [workflow audit](/reference/rest/workflow-audit) as
`export.avro.pushed`, with the subjects it registered.

## When a push is refused

These refusals happen before anything is sent to the registry:

| Code | Why | What to do |
| --- | --- | --- |
| `AVRO_PUSH_CONNECTOR_NOT_FOUND` (404) | No such connector in this workspace. | Check the connector id with `apiome connectors list`. |
| `AVRO_PUSH_CONNECTOR_KIND` | The connector is not a `schema-registry` connector. | Use the registry's connector. |
| `AVRO_PUSH_CREDENTIALS_UNREADABLE` | The connector's stored credential can't be opened. | Replace it with `PUT …/credentials`. |
| `AVRO_PUSH_NOT_AVSC` | `output_syntax` is `avdl`; a registry holds `.avsc` schemas. | Leave `output_syntax` out. |
| `AVRO_PUSH_DUPLICATE_SUBJECT` | Two schemas map to one subject (`topic_name` with several types). | Use `record_name` or `topic_record_name`. |
| `EMITTED_ARTIFACT_INVALID` | The Avro export failed its check. | Report it with the problems listed: the exporter wrote it. |

Every route and field is in the [export reference](/reference/rest/export).
