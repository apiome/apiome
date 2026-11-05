---
title: "Push to a schema registry"
description: "Register Avro, JSON Schema or Protobuf subjects on a Confluent-compatible schema registry."
sidebar_position: 5.6
tags: [export, avro, json schema, protobuf, schema registry, confluent, karapace, apicurio, kafka, connector]
---

A Confluent-compatible schema registry holds three kinds of schema: **Avro**, **JSON Schema** and
**Protobuf**. A **push** exports a version to one of them, checks the export, and registers each schema
on the registry under its **subject**, the name the registry files it under. It works with Confluent
Platform or Cloud, Karapace, or Apicurio Registry's compatibility API.

A push goes through a [schema registry connector](../bring-in/schema-registry-connector.md) you
have already added. It uses that connector's URL and stored credentials, so the push needs no
credentials of its own. It is protected against internal addresses in the same way the connector's
syncs are. Pushing is available from the REST API only.

## Before you push

- **A connector.** Add a `schema-registry` connector for the registry. See
  [Add the connector](../bring-in/schema-registry-connector.md#add-the-connector). Its credentials
  must be allowed to register schemas, not only to read them. To set compatibility levels, they must
  be allowed to change subject configuration too.
- **Permission.** A push uses the connector's credentials to write to the registry, so you need
  `imports:edit`: the same permission as changing the connector. A dry run needs it too.
- **A Confluent-compatible registry.** The Buf Schema Registry (BSR) is not supported. To publish a
  Protobuf export there, download the export and run `buf push` on its files.

## What is pushed

| `format` | Exported as | One schema per | `schemaType` | References |
| --- | --- | --- | --- | --- |
| `avro` | [Avro](./export-a-spec.md#apache-avro-from-any-source) `.avsc` | Type | `AVRO` | By the type's full name |
| `json-schema` | [JSON Schema](./export-a-spec.md#json-schema-from-any-source), `packaging: per-type` | Type | `JSON` | By the `$ref` (`Owner.schema.json`) |
| `protobuf` | [Protocol Buffers](./export-a-spec.md#protobuf-and-thrift-from-an-openapi-source) `.proto` | Package (file) | `PROTOBUF` | By the `import` path (`acme/common.proto`) |

A schema that uses a type from another schema, like a `Widget` whose `owner` is an `Owner`, is
registered after that schema, with a Confluent **reference** (`{name, subject, version}`) to its
subject. A Protobuf import of a well-known type (`google/protobuf/timestamp.proto`) is not sent as a
reference: every registry already has those.

## Name the subjects

Subjects are named the same way for every format, from the schema's **record name**:

| Format | Record name | Example |
| --- | --- | --- |
| Avro | The type's full name | `acme.Widget` |
| JSON Schema | The document's `title` (the type's name) | `Widget` |
| Protobuf | The full name of the file's first message (else its first enum) | `acme.Widget` |

These are the record names Confluent's serializers use, so your producers and consumers find the
subjects. Pick a strategy with `subject_naming`:

- `record_name` (the default) gives `{record}-value`, one subject per schema;
- `topic_record_name` with a `topic` gives `{topic}-{record}-value`;
- `topic_name` with a `topic` gives `{topic}-value` for every schema. A subject holds one schema, so a
  push of more than one schema with `topic_name` is refused.

Set `subject_role` to `key` to end each subject in `-key` instead of `-value`.

## Push

```http
POST /v1/export/{tenant_slug}/schema-registry/push
Content-Type: application/json

{
  "format": "protobuf",
  "artifact": "<project id>",
  "version": "1.0.0",
  "connector_id": "<schema-registry connector id>",
  "subject_naming": "topic_record_name",
  "topic": "orders",
  "compatibility_level": "BACKWARD_TRANSITIVE",
  "dry_run": true
}
```

1. **Export and check.** The version is exported to the format and checked, as every export of it
   is (see [How an export is checked](./check-an-export.mdx)). If the export fails its check, the push
   stops with `EMITTED_ARTIFACT_INVALID` and its problems, and nothing is sent to the registry.
2. **Order.** Each schema is placed after the schemas it references.
3. **For each subject:**
   1. **Look it up.** If the registry already holds this exact schema under the subject, nothing is
      written. The result is `already_registered`, with its schema id and version.
   2. **Set the compatibility level.** Only when you set `compatibility_level`: the subject's level is
      set to it before the check.
   3. **Check compatibility.** The schema is checked against the subject's latest version, under the
      subject's compatibility level. A schema that breaks it is `incompatible`. The registry's messages
      are included, and the schema is not registered. A subject the registry doesn't have yet has
      nothing to check against.
   4. **Register.** The result is `registered`, with the new schema id and version.

`options` takes the format's own export options, with three limits. For Avro, `output_syntax` must stay
`avsc`, and subjects are named with the request's `subject_naming`, `topic` and `subject_role`, not
in `options`. For JSON Schema, `packaging` is `per-type` unless you set `bundle` (one subject for the
whole document, named by its title), and `mode` must stay `json-schema`.

Set `"dry_run": true` to look up and check every subject without writing anything: no level is set and
no schema is registered. Run a dry run first. Pushing the same version again changes nothing: every
subject comes back `already_registered`.

A severe conversion needs `"confirm": true`, as it does for an [export job](./export-jobs.mdx). An
OpenAPI or gRPC source exports only its schemas to Avro or JSON Schema, without its operations: see
[Understand export fidelity](./export-fidelity.md).

## Choose a compatibility level

`compatibility_level` is one of Confluent's levels: `BACKWARD`, `BACKWARD_TRANSITIVE`, `FORWARD`,
`FORWARD_TRANSITIVE`, `FULL`, `FULL_TRANSITIVE` or `NONE`. Leave it out to keep each subject's level as
the registry has it (the registry default is `BACKWARD`).

- It is set only on the subjects the push registers. A subject that comes back `already_registered`
  keeps its level.
- It is set before the check, so the check uses it. If the schema then turns out `incompatible`, the
  new level stays on the subject.
- In a dry run nothing is set. The check uses the subject's current level, and the result says so.

Confluent recommends `BACKWARD_TRANSITIVE` for Protobuf, because adding a message type is not
forward compatible.

## Read the result

The response has the `format`, a `summary` that counts each status, and one entry per subject in the
order the subjects were pushed. Each entry has its `subject`, `file`, `schema_type`, `record`, `status`,
`compatibility_level`, `schema_id`, `version`, `references` and `messages`.

| Status | What it means |
| --- | --- |
| `registered` | The schema was registered now. |
| `already_registered` | The registry already held this exact schema under the subject; nothing was written. |
| `would_register` | Dry run: the schema passed its check and would be registered. |
| `incompatible` | The subject's compatibility level refused the schema; it was not registered. |
| `failed` | The registry refused the schema or its compatibility level, or did not answer; `messages` has its reply. |
| `skipped` | The schema references a subject that did not register, so it was not pushed. |

In a dry run, some schemas reference a schema that the same push would register. The registry can't
check those yet, because the version they would reference doesn't exist. They show
`would_register` with `compatibility: "unchecked"`.

The response is `200` whenever the push ran, even if some subjects failed. A push that registered at
least one subject is recorded in the [workflow audit](/reference/rest/workflow-audit) as
`export.avro.pushed`, `export.json_schema.pushed` or `export.protobuf.pushed`, with the subjects it
registered.

## When a push is refused

These refusals happen before anything is sent to the registry:

| Code | Why | What to do |
| --- | --- | --- |
| `REGISTRY_PUSH_CONNECTOR_NOT_FOUND` (404) | No such connector in this workspace. | Check the connector id with `apiome connectors list`. |
| `REGISTRY_PUSH_CONNECTOR_KIND` | The connector is not a `schema-registry` connector. | Use the registry's connector. |
| `REGISTRY_PUSH_CREDENTIALS_UNREADABLE` | The connector's stored credential can't be opened. | Replace it with `PUT …/credentials`. |
| `REGISTRY_PUSH_NOT_AVSC` | Avro with `output_syntax: avdl`; a registry holds `.avsc` schemas. | Leave `output_syntax` out. |
| `REGISTRY_PUSH_SUBJECT_OPTIONS` | Avro `options` name the subjects. | Move `subject_naming`, `topic` and `subject_role` to the request. |
| `REGISTRY_PUSH_NOT_JSON_SCHEMA` | JSON Schema with `mode: jtd`, or a document that is not JSON. | Leave `mode` out. |
| `REGISTRY_PUSH_DUPLICATE_SUBJECT` | Two schemas map to one subject (`topic_name` with several). | Use `record_name` or `topic_record_name`. |
| `REGISTRY_PUSH_REFERENCE_CYCLE` | Schemas reference each other in a loop. | A registry cannot hold a loop; push a bundle instead. |
| `REGISTRY_PUSH_NO_RECORD` | A `.proto` file declares no message or enum to name its subject by. | Export with `emit_services: false`, or add a message to that package. |
| `AVRO_PUSH_DUPLICATE_SUBJECT`, `AVRO_PUSH_REFERENCE_CYCLE` | The same, from the Avro plan. | As above. |
| `EMITTED_ARTIFACT_INVALID` | The export failed its check. | Report it with the problems listed: the exporter wrote it. |

A request with `topic_name` or `topic_record_name` and no `topic`, or an unknown `compatibility_level`,
is refused with `422` before anything runs.

## Avro only: `/avro/push`

`POST /v1/export/{tenant_slug}/avro/push` is the earlier Avro-only route, and it still works. It takes
the same fields without `format`, names subjects from the Avro `options` (`subject_naming`, `topic`,
`subject_role`), and takes `compatibility_level` too. Its refusals start with `AVRO_PUSH_` instead
of `REGISTRY_PUSH_`.

Every route and field is in the [export reference](/reference/rest/export).
