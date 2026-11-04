---
title: "Import HL7 v2 messages"
description: "Catalog HL7 v2 clinical messages, lint their MSH header, and plan a FHIR migration."
sidebar_position: 18
tags: [import, hl7, hl7v2, healthcare, lint, fhir]
---

**HL7 v2** is the pipe-and-hat messaging standard most hospital interfaces still run on: an
admission (`ADT^A01`), a lab result (`ORU^R01`), an order (`ORM^O01`), an immunization (`VXU^V04`)
and their acknowledgements (`ACK`). Apiome imports an HL7 v2 message into the
[Catalog](./catalog.mdx) beside the **FHIR** resources and **HL7 v3 / CDA** documents it also reads,
infers the message's segment schema, records the `MSH` envelope, lints it, and says which FHIR
resource each segment maps to when the interface moves to FHIR. You can then search, version, diff
and convert the item like any other.

## What you can import

| You have | What Apiome reads |
| --- | --- |
| One message in the classic encoding (`MSH\|^~\&\|…`), with `\r`, `\n` or `\r\n` segment terminators | The whole message: its header and every segment |
| An archive (`.zip`, `.tar.gz`, `.tar`) whose root member is such a message | The root message |

Any `MSH-12` version is read (2.3.1, 2.5, 2.5.1, 2.8 …): the segment and field grammar is the same
for every 2.x release. A FHIR JSON document, or anything mentioning `hl7.org/fhir`, is detected as
**FHIR**, not as HL7 v2.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the message — try
   `apiome-ui/examples/hl7v2/01-adt-a01.hl7` — or choose **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: HL7 v2** (`hl7v2`) and routes it to the
   Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the message to the import endpoints with the source kind `hl7v2` (aliases `hl7`,
`hl7v2x`); see [Import sources](../reference/rest/import-sources.md). From the CLI:

```bash
apiome import hl7v2 ./01-adt-a01.hl7
```

The six examples in `apiome-ui/examples/hl7v2/` cover an admission, a lab result, an
acknowledgement, an order, an update with repetitions and escapes, and an immunization.

## What Apiome reads

| In the message | Becomes |
| --- | --- |
| The message as a whole (`ADT^A01`) | A **record type** named after the message type, `MessageADTA01`, with one field per field of each segment that occurs once (`PID-05`, `PV1-02` …) and one list field per segment that repeats (`OBX`, `NK1`) |
| Each segment (`MSH`, `PID`, `OBX` …) | A **record type** named after the segment id, with one string field per field, numbered as in the message (`OBX-03`) |
| `MSH-9` message type, `MSH-12` version, `MSH-10` control id | Recorded beside the model as `hl7v2_message_type`, `hl7v2_version`, `hl7v2_control_id` |
| The rest of the `MSH` envelope — separators, sending and receiving application and facility, `MSH-11` processing id | Recorded as `hl7v2_envelope` |
| The segments in order, with their field values | Recorded as `hl7v2_segments`, so the item can be written back out as an HL7 v2 message |
| The FHIR resource each segment maps to | Recorded as `hl7v2_fhir_counterparts` — see [Migrate to FHIR](#migrate-to-fhir) |

A message is a sample, not a profile: the schema is inferred from the segments and fields the
message carries. A field the sample leaves empty is still a field; a segment the message does not
carry is not in the type. Import the longest, most complete message of each type you exchange.

## Lint

The **Quality** step and the item's **Lint & score** tab add the `hl7v2` rules on top of the common
ones. They check the `MSH` header, the part every interface engine depends on:

| Rule | Severity | Flags |
| --- | --- | --- |
| [`hl7v2.message-type-declared`](../build/lint-rules.md#hl7v2-message-type-declared) | Error | `MSH-9` is empty: no receiver can tell which structure the segments follow |
| [`hl7v2.trigger-event-declared`](../build/lint-rules.md#hl7v2-trigger-event-declared) | Warning | `MSH-9` names a message code but no trigger event (`ADT` instead of `ADT^A01`) |
| [`hl7v2.version-declared`](../build/lint-rules.md#hl7v2-version-declared) | Warning | `MSH-12` is empty: the receiver cannot pick the definitions to validate against |
| [`hl7v2.control-id-present`](../build/lint-rules.md#hl7v2-control-id-present) | Warning | `MSH-10` is empty: an acknowledgement cannot refer back to the message |
| [`hl7v2.processing-id-declared`](../build/lint-rules.md#hl7v2-processing-id-declared) | Info | `MSH-11` is empty: production, training and debugging traffic cannot be told apart |
| [`hl7v2.standard-encoding-characters`](../build/lint-rules.md#hl7v2-standard-encoding-characters) | Warning | `MSH-1` or `MSH-2` is not the conventional `\|` and `^~\&` |

## Versions and changes

Import a newer message of the same type into the same item to add a version. The comparison follows
the standard rules for record types: a segment or field that disappears is a removal, a new one is
an addition. Because fields are numbered, a value that moves to another position is reported as a
change, not a rename.

## Migrate to FHIR

HL7 v2 interfaces are being replaced by FHIR, and the catalog item carries the first step. As for
RAML → OpenAPI, converting the item *is* the migration; there is no separate migrator:

- **Where each segment lands.** `hl7v2_fhir_counterparts` names the FHIR resource each segment of the
  message maps to, following the HL7 v2-to-FHIR implementation guide: `MSH` → `MessageHeader`,
  `PID` → `Patient`, `PV1` → `Encounter`, `NK1` → `RelatedPerson`, `OBR` and `ORC` →
  `ServiceRequest`, `OBX` → `Observation`, `AL1` → `AllergyIntolerance`, `DG1` → `Condition`,
  `IN1` → `Coverage`, `RXA` → `Immunization`, `SCH` → `Appointment`. A segment with no FHIR
  counterpart (`EVN`, `MSA`, `ERR`) is left out.
- **Write the schema as FHIR.** [Export](../ship/export-a-spec.md#fhir-structuredefinition-from-any-source)
  the item as **FHIR** to get a `StructureDefinition` logical model per segment type, the shape a
  FHIR profile author starts from.
- **Hand partners its segment definitions.** Export the item as **HL7 v2 segment guide**
  ([HL7 v2 segment guide](../ship/export-a-spec.md#hl7-v2-segment-guide-from-any-source)) for the message and
  segment definitions an integration engine is configured from: its segments in order, and each field's data
  type, length, optionality, repetition and table.
- **Keep both sides in the catalog.** Import the FHIR server's CapabilityStatement
  ([FHIR import](./fhir-import.md)) next to the HL7 v2 item, so the interface's two generations are
  searched, versioned and governed together.

## When an import is refused

| Code | Why | What to do |
| --- | --- | --- |
| `INPUT_SYNTAX_INVALID` | The text does not start with an `MSH` segment, a segment has no three-letter id, or the header is truncated before `MSH-12` | Paste the complete message, starting with `MSH\|^~\&\|` |
| `INPUT_SEMANTIC_INVALID` | The message is only an `MSH` segment | Include at least one body segment |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (UTF-16 exports are common) | Re-save the file as UTF-8 |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): HL7 v2's coverage and export support
- [Import FHIR APIs and profiles](./fhir-import.md): the other side of the migration
- [Import HL7 v3 / CDA documents](./hl7v3-cda-import.md): clinical documents rather than messages
- [Built-in lint rules](../build/lint-rules.md): every rule with its rationale
- [Healthcare and finance standards](./healthcare-and-finance-standards.mdx): every healthcare, finance and EDI importer, and how they work together.
