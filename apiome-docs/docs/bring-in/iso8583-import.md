---
title: "Import ISO 8583 card messages"
description: "Catalog ISO 8583 message definitions with their MTI, bitmaps and data elements."
sidebar_position: 21
tags: [import, iso8583, cards, payments, atm, pos, finance, lint]
---

**ISO 8583** is the message standard behind card transactions: an ATM withdrawal, a point-of-sale
authorization, a reversal, a network echo. On the wire a message is a four-digit **Message Type
Indicator** (MTI), one or two **bitmaps** that flag which of the 128 numbered **data elements**
follow, and the elements themselves, each cut by its type and length. The **ISO 8583** importer
(`iso8583`) reads the documented field-map form of such a message — the MTI plus its data elements
as JSON — into the [Catalog](./catalog.mdx), decodes the MTI, derives the bitmaps, and records the
definition so it can be searched, versioned, diffed and linted like any other catalog item.

## What you can import

A JSON object with an `mti` and a `dataElements` (or `data_elements`) map keyed by data element
number. Each element names its `type`, `length` and a sample `value`:

```json
{
  "mti": "0100",
  "name": "Authorization Request",
  "dataElements": {
    "2":  { "name": "Primary Account Number", "type": "n", "length": "..19", "value": "4111111111111111" },
    "3":  { "name": "Processing Code", "type": "n", "length": "6", "value": "000000" },
    "11": { "name": "System Trace Audit Number", "type": "n", "length": "6", "value": "000001" }
  }
}
```

Lengths are written as the standard does: a fixed length (`6`), `..LL` for a two-digit length
prefix (`..19`) and `...LLL` for a three-digit one (`...999`). Types are the standard's codes:
`n`, `a`, `an`, `ans`, `b`, `z`, `x+n` and the rest.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the document — try
   `apiome-ui/examples/iso8583/01-authorization-0100.json` — or choose **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: ISO 8583** (`iso8583`) and routes it to
   the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the document to the import endpoints with the source kind `iso8583`; see
[Import sources](../reference/rest/import-sources.md). From the CLI:

```bash
apiome import iso8583 ./01-authorization-0100.json
```

The six examples in `apiome-ui/examples/iso8583/` cover an authorization request and response, a
network echo, two financial requests and a reversal advice, with primary and secondary bitmaps.

## What Apiome reads

| In the document | Becomes |
| --- | --- |
| The message as a whole | A **record type** named after the MTI, `Message0100`, with one field per data element, numbered by the **data element number** (`DE2` is field 2, `DE128` field 128) |
| Each data element | A **record type** named `DE<n>`, with its name, type and length recorded (`iso8583_de_name`, `iso8583_de_type`, `iso8583_de_length`) |
| The `mti` | Decoded and recorded as `iso8583_mti_decoded`: the ISO 8583 release (`0` = 1987, `1` = 1993, `2` = 2003), the class (`1` authorization, `2` financial, `4` reversal, `8` network management …), the function (`0` request, `1` response, `2` advice …) and the origin, with a summary such as `Authorization request (acquirer)` |
| The data elements present | The **bitmaps** they imply, recorded as `iso8583_bitmap`: the primary bitmap as 16 hex digits, the secondary bitmap when any element above 64 is present (bit 1 of the primary is then set), and the element numbers |
| Sample values | Kept as each field's default and in the stored source; they are samples, not the contract |

## Versions and changes

Import a newer definition of the same message into the same item to add a version. Because fields
are numbered by data element, the comparison grades every change with ISO 8583 semantics:

| Change | Severity | Rule |
| --- | --- | --- |
| The MTI changed | Breaking: it is another message | `iso8583.mti-changed` |
| A data element removed | Breaking: counterparties on the old definition still set its bit and send it | `iso8583.de-removed` |
| A data element added | Dangerous: counterparties on the old definition never set its bit | `iso8583.de-added` |
| A data element's length changed | Breaking: the wire no longer cuts where it did | `iso8583.de-length-changed` |
| A data element's type changed | Breaking | `iso8583.de-type-changed` |
| Only a data element's descriptive name changed | Safe | `iso8583.de-renamed` |
| Only a sample value changed | Safe | `iso8583.sample-value-changed` |

## Lint

The **Quality** step and the item's **Lint & score** tab add the `iso8583` rules on top of the
common ones:

| Rule | Severity | Flags |
| --- | --- | --- |
| [`iso8583.mti-known`](../build/lint-rules.md#iso8583-mti-known) | Warning | An MTI digit the standard reserves (class `0` or `9`, function `8` or `9`, an unknown version or origin) |
| [`iso8583.de-number-valid`](../build/lint-rules.md#iso8583-de-number-valid) | Error | A data element number outside 2–128 |
| [`iso8583.de-type-known`](../build/lint-rules.md#iso8583-de-type-known) | Warning | A type that is not an ISO 8583 type code |
| [`iso8583.de-length-declared`](../build/lint-rules.md#iso8583-de-length-declared) | Warning | A data element with no length |
| [`iso8583.stan-present`](../build/lint-rules.md#iso8583-stan-present) | Warning | No DE 11 (System Trace Audit Number): a response cannot be matched to its request |
| [`iso8583.response-code-on-response`](../build/lint-rules.md#iso8583-response-code-on-response) | Warning | A response or acknowledgement without DE 39 (Response Code) |
| [`iso8583.transmission-datetime-present`](../build/lint-rules.md#iso8583-transmission-datetime-present) | Info | No DE 7 (Transmission Date and Time) |

## Export

An ISO 8583 item writes back out as the same field-map JSON through the **ISO 8583** target; see
[Export a spec](../ship/export-a-spec.md). The binary wire form is not written.

## When an import is refused

| Code | Why | What to do |
| --- | --- | --- |
| `INPUT_SYNTAX_INVALID` | The JSON is malformed or truncated | Paste the complete document |
| `INPUT_SEMANTIC_INVALID` | A data element has no `value`, or the document has no data elements | Give every element a sample value |
| `FORMAT_MISMATCH` | The document has no four-digit `mti` or no `dataElements` map | Add the MTI and the element map |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): ISO 8583's coverage and export support
- [Import ISO 20022 messages and message definitions](./iso20022-import.md): the other payments standard
- [Built-in lint rules](../build/lint-rules.md): every rule with its rationale
