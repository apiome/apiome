---
title: "Import and export SAP IDocs"
description: "Catalog SAP IDocs from flat files or XML, and export IDoc XML."
sidebar_position: 16
tags: [import, export, idoc, sap, edi, b2b]
---

An **IDoc** (intermediate document) is how SAP systems exchange business documents — purchase orders
(`ORDERS05`), invoices (`INVOIC02`), customer masters and every custom basic type an estate defines.
Apiome imports an IDoc into the [Catalog](./catalog.mdx) in either of its two transport forms, keeps
the whole document as a native analysis on the item's **Format details** tab, and can export the
schema back out as IDoc XML.

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| A **flat-file** IDoc (`.idoc`, `.txt`) — an `EDI_DC40` control record followed by `EDI_DD40` data records | One catalog item; each segment's payload is opaque unless a definition is supplied |
| An **IDoc XML** document (`.xml`) — `<ORDERS05>` → `<IDOC>` → `<EDI_DC40>` + segments | One catalog item with every field named |
| An archive (`.zip`, `.tar.gz`) of a flat IDoc **and its segment definition** (a WE60 `<IDocSegments>` export) | One catalog item with the flat fields cut at the declared offsets |
| A file holding several IDocs | One catalog item from the first IDoc; every IDoc is in the analysis |

**Both forms give the same schema.** A flat IDoc and an XML IDoc carrying the same document — read
with the same segment definitions — import to the same canonical model. Without a definition, a flat
segment's 1000-character `SDATA` has no field boundaries, so it is kept as one opaque `SDATA` value;
the segment hierarchy and the control record are still identical to the XML form's.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the IDoc — try
   `apiome-ui/examples/idoc/02-typical-xml-orders05.xml`. For a flat IDoc with its definition, zip
   `apiome-ui/examples/idoc/07-with-definition-set/` and drop the archive.
3. On **Detect & route**, Apiome reports **Auto-detected: SAP IDoc** (`idoc`) and routes it to the
   Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the document to the import endpoints with the source kind `idoc`; see
[Import sources](../reference/rest/import-sources.md).

## What Apiome reads

| In the IDoc | Becomes |
| --- | --- |
| The basic type (`IDOCTYP`, e.g. `ORDERS05`) | The root **record type** |
| Each segment type (`E1EDK01`, `E1EDP01`, `Z1CUSTHDR`) | A record type of its own: its fields, then its child segments |
| The parent segment numbers (`PSGNUM`) | The nesting — a segment sits under the segment whose number it names, **never** under the record that happens to precede it |
| A segment occurring more than once under one parent, or allowed more than once by the definition | A list |
| A field's description and length in the segment definition | The field's description and maximum length |
| The control record (`EDI_DC40`) | Recorded as **structure**: basic type, extension (`CIMTYP`), message type, partners, ports, direction, dates |

Payload values are never written into the schema. The control record is never treated as a
redactable value: it is what identifies the document, so it is always shown.

## The native analysis

The **Format details** tab shows **IDoc → segment → field**, one root per IDoc. See
[Read a catalog item's format details](./catalog-format-details.md#the-idoc-analysis) for how to read
it:

- **The control record** is on the IDoc row — basic type, extension, message type, sender and
  receiver ports and partners, direction (**Outbound**/**Inbound**), creation date and time, and the
  full non-empty record under **controlRecord**.
- **Segments** carry their **segmentNumber**, **parentSegmentNumber** and **depth**. A declared
  `HLEVEL` that disagrees with the depth the numbers give is shown as **declaredLevel**, with a
  warning (`idoc.hierarchy_level_disagrees`).
- **Fields** follow the value-visibility policy. In a flat IDoc each field also shows its **offset**
  within `SDATA`, its **recordOffset** within the record and its **length**.
- **What the offsets assume** is stated on every flat record (warning `idoc.layout_assumptions`): one
  character per byte, the release 4.0+ `EDI_DC40`/`EDI_DD40` layouts, trailing blanks as padding.

## Export as IDoc XML

Choose **SAP IDoc** (`idoc`) as the export target wherever you export (see
[Export a spec](../ship/export-a-spec.md)). It writes IDoc XML:
the basic type as the root, the control record as `<EDI_DC40>`, and each segment with the values the
import recorded. An imported XML IDoc exports back as the same document. Field descriptions from a
segment definition are not part of IDoc XML, so they are reported as a loss. A schema that was not
imported from an IDoc has no control record and cannot be exported as one.

## What Apiome does not check

- **Standard SAP segment layouts are not bundled.** A flat segment without a supplied definition is
  one opaque value.
- **Nothing is validated against the basic type** (WE30) or the qualifier code lists: a well-formed
  IDoc is not claimed to be a valid one.
- **Status records** (`EDI_DS40`) and the release 2.x `EDI_DC`/`EDI_DD` layouts are not read.

## When an import is refused

| What is wrong | Error code |
| --- | --- |
| The file stops mid-record or mid-element | `INPUT_TRUNCATED` |
| A record is the wrong length or has a non-numeric segment number, or the XML is not well-formed | `INPUT_MALFORMED` |
| There is no control record, the control record is shorter than 524 characters, or a parent segment number names no earlier segment | `INPUT_SEMANTIC_INVALID` |
| The file was sent as `idoc` but is another format | `FORMAT_MISMATCH` |
| The file is not UTF-8 text (UTF-16, for example) | `INPUT_ENCODING_INVALID` |
