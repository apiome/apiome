---
title: "Import a CNCF xRegistry"
description: "Catalog CloudEvents schemas, message definitions and endpoints from an xRegistry."
sidebar_position: 14
tags: [import, xregistry, cloudevents, events]
---

**xRegistry** is the CNCF CloudEvents project's catalog model. One xRegistry document — or the same
model served over its REST API — holds three registries side by side: **schemas** (JSON Schema, Avro,
Protobuf, XSD), **message definitions** (the CloudEvents envelope, its attributes and the payload
schema) and **endpoints** (where the messages flow, over MQTT, AMQP, Kafka, NATS or HTTP). Apiome
imports it into the [Catalog](./catalog.mdx) as an event-driven API, next to AsyncAPI and single
CloudEvents.

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| An xRegistry document (a saved `.json`, often `.xreg.json`) | One catalog item with every schema, message and endpoint in it |
| A document that holds only `schemagroups` | A catalog item of types, with no services |
| A running xRegistry (`https://<host>/reg`) | A [registry crawl](../reference/rest/connectors.md): each schema, message group and endpoint becomes its own catalog item, re-crawled on a schedule |
| The JSON on your clipboard | A paste |

A single CloudEvent — `specversion`, `type`, `source` and `data` — is not an xRegistry document; it
imports as **CloudEvents**.

## Import it

**In the app:**

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the document — try
   `apiome-ui/examples/xregistry/02-typical-order-events.json` — or choose **URL**, enter the document's
   address as the **Document URL** and **click "Fetch and detect"**.
3. On **Detect & route**, Apiome reports **Auto-detected: CNCF xRegistry** (`xregistry`) and routes it
   to the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

**With the CLI:**

```bash
apiome import xregistry ./registry.xreg.json
apiome import xregistry --url https://example.com/registry.json --dry-run
```

`--dry-run` previews the import without saving. See [`apiome import`](../reference/cli/import.md).

**From a live registry:** add a **Registry crawl** connector with the protocol **CNCF xRegistry
(schemas, messages, endpoints)** — see [Registry crawl](../reference/rest/connectors.md).

## What Apiome reads

| In the document | Becomes |
| --- | --- |
| `name`, `description`, `registryid` | The item's title, description and id |
| Each schema of `schemagroups.<group>.schemas` | A **type** named by its schema id, or `<group>.<id>` when two groups reuse an id. The default version is read: `defaultversionid` among `versions`, else the schema's own `schema`, `schemabase64` or `schemauri`. |
| A JSON Schema's `definitions` / `$defs` | Types of their own |
| An Avro, Protobuf or XSD schema (from its `format`) | The types that format's importer reads |
| Each message of `messagegroups.<group>.messages` | An **operation** carrying one event message, on the **channel** named by its CloudEvents `type` (`envelopemetadata.type.value`; the message id when it pins none) |
| A message's `envelopemetadata` attributes | The message's **headers**; a pinned `value` is the header's default, `required` makes it required |
| `dataschemaxid` / `dataschemauri`, or an inline `dataschema` | The message's **payload** type |
| `datacontenttype`, `protocolbinding` | The payload's content type and the channel's bindings |
| Each endpoint | A **service** whose operations are the messages of the groups it lists in `messagegroups` plus the messages it declares itself. A `producer` publishes them; a `consumer` or `subscriber` subscribes. |
| An endpoint's `protocoloptions.endpoints[].uri` | The item's **servers** |
| A message group that no endpoint lists | A service of its own, so every message is cataloged |

The earlier draft names read the same way: `definitiongroups` and `definitions` for message groups
and messages, `metadata` for `envelopemetadata`, and `schemaurl` / `dataschemaurl` for the `…uri`
forms.

**Kept but not read structurally:** a schema in a format Apiome has no importer for (for example
`JsonStructure/…`), a schema given only by `schemauri`, and an Avro / Protobuf / XSD document that does
not parse. Each stays a type that records its format and why, so it still versions and diffs. A
message whose schema reference points outside the document keeps the reference, with no payload type.
An endpoint that lists a message group the document does not hold records it as unresolved.

**Not read:** the registry's bookkeeping — `epoch`, `createdat`, `modifiedat`, `self` URLs. They move
whenever the registry touches an entity, so they never make an unchanged registry look like a new
version.

## Versions and changes

Each import is fingerprinted from the normalized model, so re-importing an unchanged document — even
reordered — is the same version. Importing a new release reports:

- a message **added** or **removed** (an operation of each endpoint that carries it), and a new
  CloudEvents `type` as an added channel;
- a schema **changed** — a new default version, a field or enum value added — as a changed type;
- an endpoint **added** or **removed**, or a change to its protocol, options or URIs, as a change to
  the service.

Try it with `02-typical-order-events.json` and its next release, `06-typical-order-events-v2.json`.

## Lint rules

Apiome scores the document with the common rules — for example a type or field with no description.
Give each schema a `description` (Apiome uses it for the type when the schema document has none).

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_SEMANTIC_INVALID` | The document defines no schema, message or endpoint, or a collection is not an object keyed by id. |
| `FORMAT_MISMATCH` | The document is not an xRegistry document — for example an AsyncAPI or OpenAPI file. |
| `INPUT_MALFORMED`, `INPUT_TRUNCATED`, `INPUT_ENCODING_INVALID` | The JSON is not valid, is cut off, or is not UTF-8. |

## Related

- [Registry crawl](../reference/rest/connectors.md): import a live xRegistry, one item per schema,
  message group and endpoint.
- [Supported formats](./supported-formats.md): the versions this importer reads.
- [Import a spec](./import-a-spec.md): every way to bring a document in.
