# CNCF xRegistry — `xregistry`

Fixtures for **MFI-19.2** ([#3980](https://github.com/apiome/apiome/issues/3980)) — cataloging a
CloudEvents xRegistry: the CNCF registry model that holds schemas, message definitions and endpoints
side by side. The `xregistry` adapter (`app.xregistry_import_source`) claims every entry here. (A single
CloudEvents *envelope* is the `cloudevents` adapter's; see `../cloudevents/`.)

**Shape.** One JSON object with up to three collections, each keyed by id:
`schemagroups` → `schemas` (a `format` such as `JsonSchema/draft-07`, `Avro/1.11.0`, `Protobuf/3`,
`XSD/1.1`, and the document inline as `schema` / `schemabase64`, by reference as `schemauri`, or under
`versions` with a `defaultversionid`); `messagegroups` → `messages` (`envelope`, `envelopemetadata`
with the CloudEvents `type` / `source` values, `protocolbinding`, `dataschemaxid` / `dataschemauri` or
an inline `dataschema`, `datacontenttype`); and `endpoints` (`usage`, `protocol`,
`protocoloptions.endpoints[].uri`, `messagegroups` references and inline `messages`). The earlier draft
names `definitiongroups`, `definitions` and `metadata` read the same way.

**Detection marker.** A JSON object with `schemagroups`, `messagegroups` (or `definitiongroups`) or
`endpoints` holding an object, and no other format's root marker (`openapi`, `asyncapi`, …).

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-schema-registry.json` | minimal | One schema group, one JSON Schema. |
| `02-typical-order-events.json` | typical | Schemas, a message group referencing them by xid and an MQTT producer endpoint. |
| `03-composition-shared-groups.json` | composition | Two endpoints sharing groups; Avro, Protobuf and JSON Schema (`definitions`) payloads. |
| `04-stress-edge-cases.json` | stress | Draft names, `schemabase64` XSD, an unknown format, a `schemauri`-only schema, an unresolved group, inline `dataschema`, `deprecated`, Unicode, duplicate schema ids. |
| `05-real-world-contoso-erp.json` | real-world | Reconstruction of the Contoso ERP sample registry (HTTP and AMQP endpoints). |
| `06-typical-order-events-v2.json` | typical | The next release of `02` — the diff fixture. |
| `negative/` | — | Trailing comma, an empty registry, truncation, an AsyncAPI document, UTF-16. |

**The contract the adapter meets.** Paradigm `event`. Schemas are types (Avro / Protobuf / XSD through
their own adapters, anything else an opaque type that still versions); each message is an operation on
the channel named by its CloudEvents `type`; each endpoint is a service (`publish` for a producer,
`subscribe` for a consumer); a message group no endpoint carries is a service of its own. The multi-file
rung is waived.
