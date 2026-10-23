---
title: "Import MQTT Sparkplug B payloads"
description: "Catalog Sparkplug B topics and metrics as an event-driven MQTT API."
sidebar_position: 25
tags: [import, sparkplug, mqtt, industrial, iot]
---

**Sparkplug B** is the payload and topic standard of industrial MQTT. An edge node publishes
protobuf payloads of **metrics** (temperatures, counters, setpoints) on topics of the form
`spBv1.0/<group>/<message type>/<edge node>[/<device>]`. The **MQTT Sparkplug B** importer
(`sparkplug`) reads those payloads, or a description of the topic namespace, into the
[Catalog](./catalog.mdx) as an **event-driven** API you can search, version and diff.

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| One binary payload (`.bin`), such as a saved NBIRTH, DBIRTH or DDATA message | One catalog item with one MQTT channel and the payload's metrics. Everything is labelled **inferred** |
| Several payloads from one session in an archive (`.zip`, `.tar.gz`): a BIRTH and the DATA and DEATH payloads after it | One catalog item with a channel per message type. A DATA payload's metrics are named through the BIRTH |
| A topic-namespace description (`.json`) | One catalog item with every listed topic as a channel and each device's metric catalogue as its message schema. Everything is **declared** |
| The Sparkplug `.proto` schema itself | Not this importer: it describes the payloads rather than being one. Import it as Protocol Buffers |

Apiome recognises a payload by decoding it: it must be a complete Sparkplug B payload with at least
one metric. It recognises a namespace description by `"namespace": "spBv1.0"`. Sparkplug 2.2 and
3.0 share the payload schema and the `spBv1.0` namespace, so both are read.

### The topic-namespace description

A namespace description is a JSON document that names the group and the edge node, lists the
topics, and gives the metric catalogue of the edge node and of each device:

```json
{
  "namespace": "spBv1.0",
  "groupId": "PlantAmsterdam",
  "edgeNodeId": "Line1",
  "hostApplicationId": "SCADA-Primary",
  "broker": { "url": "ssl://mqtt.example.com:8883", "qos": 0 },
  "topics": [
    { "messageType": "NBIRTH", "topic": "spBv1.0/PlantAmsterdam/NBIRTH/Line1" },
    { "messageType": "DDATA", "topic": "spBv1.0/PlantAmsterdam/DDATA/Line1/Filler01" },
    { "messageType": "DCMD", "topic": "spBv1.0/PlantAmsterdam/DCMD/Line1/Filler01", "direction": "inbound" },
    { "messageType": "STATE", "topic": "spBv1.0/STATE/SCADA-Primary", "retained": true }
  ],
  "nodeMetrics": [{ "name": "bdSeq", "alias": 0, "datatype": "UInt64" }],
  "devices": [
    {
      "deviceId": "Filler01",
      "metrics": [
        { "name": "Inputs/Temperature", "alias": 1, "datatype": "Double", "engUnit": "degC" }
      ]
    }
  ]
}
```

Any other key of a metric (`engUnit`, `engLow`, `writable` …) is kept as one of its properties.

## Import it

Import the file like any other specification: in the [import wizard](./import-wizard.mdx), with
`apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)). Apiome
picks **MQTT Sparkplug B** (`sparkplug`).

**Keep the message type in the file name** when you save a payload: `line1-ddata.bin`,
`dbirth.bin`. A payload does not carry the topic it was published on, so the file name is how
Apiome knows whether it is an NBIRTH, a DDATA or a DCMD. Without one, Apiome reads the metrics: a
payload holding only `bdSeq` is an NDEATH, and one with `bdSeq` among named metrics is an NBIRTH.
Otherwise the message type stays unknown.

**Import DATA payloads beside their BIRTH.** A DATA payload refers to its metrics by the numeric
alias the BIRTH certificate gave them. Put the BIRTH and the DATA payloads in one archive, and
Apiome names every metric. Every payload in the archive is read, whichever one is the root.

The catalog item is named after the file (`06-typical-ddata`), or after the group and edge node of
a namespace description (`PlantAmsterdam/Line1`).

## What each part becomes

| Sparkplug | In the catalog item |
| --- | --- |
| A topic | An MQTT **channel** whose address is the topic. Its group, message type, edge node and device are recorded. For a payload they are unknown, so the address keeps them as parameters: `spBv1.0/{group_id}/DDATA/{edge_node_id}/{device_id}` |
| NBIRTH, NDATA, NDEATH, DBIRTH, DDATA, DDEATH | A **publish** operation: the edge node sends it |
| NCMD, DCMD, STATE | A **subscribe** operation: the edge node receives it. A namespace description's `direction` overrides this |
| The metrics of a payload, or of a device's or the edge node's catalogue | A **record** that is the message's payload, one field per metric |
| A metric's datatype | A scalar: `Int8` … `UInt64` keep their width (`int8` … `uint64`), `Float` and `Double` stay, `Boolean`, `String` and `Text` become `boolean` and `string`, `DateTime` a `timestamp`, `UUID` a `uuid`, `Bytes` and `File` `bytes` |
| An array datatype (`DoubleArray` …) | A list of the element scalar |
| A `DataSet` metric | A list of a row record Apiome names `<metric> row`, labelled **synthesized** |
| A `Template` definition (`_types_/Motor`) and its instances | A record named after the definition (`Motor`); each instance is a field of that type |
| Alias, Sparkplug datatype, property set (`engUnit`, `engLow` …), metadata, `historical` / `transient` / `null` flags | Kept on the field |
| The broker's URL, `qos` and `retained` | The server, and each operation's MQTT binding (`qos`, `retain`) |
| Metric values | **Not imported.** Values are telemetry, not schema. They appear under **Format details** only |

**Payloads alone are inferred.** Every channel, operation, record and field that comes from a
payload is labelled **inferred**, with the sentence saying what it was inferred from (see
[Declared, inferred and synthesized](./inference-provenance.mdx)).

## What is declared, not imported

Apiome records these in the import's coverage ledger instead of guessing:

- **An alias-only metric whose BIRTH was not supplied.** The field keeps the placeholder name
  `alias:<n>`, never an invented name. Import the BIRTH beside it to name it.
- **A metric that sent no datatype** and has no BIRTH declaring one. It is typed from the value it
  carried (`integer`, `double` …), which cannot tell `Int8` from `UInt32`.
- **An unknown datatype**, or a `DataSet` or `Template` metric with no value to read its shape from.
  The field is typed as *any*.
- **A template instance whose definition is not in the upload.** The field is typed as *any* and
  keeps its `template_ref`.
- **A payload whose message type could not be inferred.** The channel keeps `{message_type}` as a
  parameter.
- **A device topic whose device has no metric catalogue** in a namespace description. The message
  has no payload schema.
- **Protobuf extension fields and a payload's opaque `body`** are not read.

## The payloads on Format details

Open the item's **Format details** tab to see each payload in Sparkplug's own terms:

1. One **payload** per file, with its inferred message type and the reason, its `timestamp`, `seq`
   and `uuid`.
2. Under it, every **metric** with its name or alias, datatype and flags. A metric's value is
   shown only if the value-visibility policy allows it (see
   [Read a catalog item's format details](./catalog-format-details.md#the-sparkplug-b-analysis)).
3. Under each metric, its property set, metadata, `DataSet` columns or template members.

For a namespace description, the tab lists the topics with their parsed components, then the edge
node's and each device's metric catalogue.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_TRUNCATED` | The payload ends in the middle of a metric, or the JSON ends with an object still open. |
| `INPUT_MALFORMED` | The payload is broken inside a complete metric (a wire type protobuf does not define, a field running past its metric), or the JSON is not valid. |
| `INPUT_SEMANTIC_INVALID` | The payload carries no metrics, or a metric has neither a name nor an alias. In a namespace description: a topic in another namespace, group or edge node than the one declared, a misshapen topic (a device message without a device, an unknown message type), or a topic listed twice. Every contradiction is listed. |
| `INPUT_ENCODING_INVALID` | A namespace description is not UTF-8 (for example, it was saved as UTF-16). |
| `FORMAT_MISMATCH` | The file is not Sparkplug at all, such as the Sparkplug `.proto` schema. |

## Related

- [Supported formats](./supported-formats.md#format-sparkplug): what this importer reads.
- [Declared, inferred and synthesized](./inference-provenance.mdx): why a payload-only import is
  labelled inferred.
- [Read a catalog item's format details](./catalog-format-details.md#the-sparkplug-b-analysis):
  the payloads and their metrics.
- [Import a specification](./import-a-spec.md): the import job and its options.
