---
title: "Import an EDI X12 interchange"
description: "Catalog ANSI X12 interchanges, lint their envelopes, and diff transaction sets."
sidebar_position: 14.8
tags: [import, x12, edi, b2b, lint]
---

**ANSI ASC X12** is the EDI standard North American supply chains, retailers and health plans run
on: a purchase order (`850`), an invoice (`810`), a ship notice (`856`), a health care claim (`837`),
a benefit enrollment (`834`) and the functional acknowledgement that answers them (`997`). Apiome
imports an X12 interchange into the [Catalog](./catalog.mdx) beside its twin,
[UN/EDIFACT](./edifact-import.md). The transaction set becomes a schema you can search, version, diff
and convert. Apiome lints the envelopes the way a trading partner's translator checks them, and keeps
the whole interchange as a native analysis on the item's **Format details** tab.

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| One interchange file (`.edi`, `.x12`): `ISA` … `IEA`, with `GS` … `GE` groups and `ST` … `SE` transaction sets | One catalog item |
| An interchange with several groups or transaction sets | One catalog item; every group and set is in the analysis |
| An archive (`.zip`, `.tar.gz`) whose root member is an interchange | One catalog item read from the root interchange |
| The interchange on your clipboard | A paste |

A **UN/EDIFACT** interchange (`UNB` / `UNH`) shares the `.edi` extension but is a different syntax:
Apiome detects it as [UN/EDIFACT](./edifact-import.md) instead.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the interchange (try
   `apiome-ui/examples/edi-x12/01-850-purchase-order.edi`), or choose **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: EDI X12** (`edix12`) and routes it to the
   Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the interchange to the import endpoints with the source kind `edix12` (aliases
`x12`, `edi`); see [Import sources](../reference/rest/import-sources.md). From the CLI:

```bash
apiome import edix12 ./01-850-purchase-order.edi
```

The examples in `apiome-ui/examples/edi-x12/` cover an 850, an 810, a 997, an interchange with two
groups, an 856 with an `HL` hierarchy, an 834 and an 837 with composite elements.

## What Apiome reads

| In the interchange | Becomes |
| --- | --- |
| The first group's first transaction set | The canonical model: a **record type** named for the set (`TransactionSet850`) |
| A segment that occurs once in that set | Fields of the set's type, named by reference designator (`BEG03`: segment `BEG`, element `03`) |
| A segment that repeats (`PO1`, `N1`, `HL`) | Its own record type, listed from the set's type |
| Element values | The fields' sample values: what this interchange carried, not a definition |
| `ISA`, `GS`, `ST` and their trailers | The item's envelope record (`x12_envelope`), the controls the lint pack checks (`x12_controls`) and the native analysis |

When an interchange carries more than one transaction set, the analysis says which one the model came
from. See [The X12 inspector](./catalog-format-details.md#the-x12-inspector) for how to read the
**Format details** tab.

## Lint rules

The `edix12` lint pack runs on every X12 item with the common pack, and its findings count toward the
item's score and grade. It checks the envelopes, and checks nothing an implementation guide decides:

| Rule | Severity | Fires when |
| --- | --- | --- |
| [`edix12.control-numbers-match`](../build/lint-rules.md#edix12-control-numbers-match) | error | A trailer does not repeat its header's control number: `SE02` ≠ `ST02`, `GE02` ≠ `GS06`, or `IEA02` ≠ `ISA13` |
| [`edix12.control-totals-match`](../build/lint-rules.md#edix12-control-totals-match) | error | A trailer's total is not what it closes: `SE01` ≠ the segments from `ST` to `SE`, `GE01` ≠ the group's transaction sets, or `IEA01` ≠ the interchange's groups |
| `edix12.control-numbers-unique` | warning | Two transaction sets in a group, or two groups in the interchange, share a control number |
| `edix12.functional-id-matches-set` | warning | `GS01` is not the functional identifier X12 assigns the set (`PO` for an `850`, `IN` for an `810`, `HC` for an `837`) |
| `edix12.version-declared` | warning | `GS08` is empty |
| `edix12.usage-indicator-valid` | warning | `ISA15` is not `P` (production), `T` (test) or `I` (information) |
| `edix12.test-interchange` | info | `ISA15` is `T` |

An interchange whose trailers disagree still imports. The two errors fail a quality gate, and the
**Format details** tab shows the declared and observed figures side by side. Every rule's rationale
is on [Built-in lint rules](../build/lint-rules.md#pack-edix12).

## Versions and diffs

An X12 item is a sample, so its diff is graded as one. A new interchange with the same structure and
other values is a **safe** version, not a dangerous one:

| Change between two versions | Grade | Rule |
| --- | --- | --- |
| Another transaction set (`ST01` `850` → `855`) | breaking | `edix12.transaction-set-changed` |
| A segment is no longer sent | breaking | `edix12.segment-removed` |
| A segment no longer carries an element | breaking | `edix12.element-removed` |
| A segment is now sent | dangerous | `edix12.segment-added` |
| A segment now carries another element | dangerous | `edix12.element-added` |
| A segment repeats in one version and occurs once in the other | dangerous | `edix12.segment-repetition-changed` |
| An element's position in the flattened record moved, because a segment before it was added or removed | safe | `edix12.ordinal-shifted` |
| Only the values changed | safe | `edix12.sample-value-changed` |

A receiver that validates against an implementation guide rejects a segment or element the guide does
not list, so an addition is **dangerous**, not safe. Whether a segment may repeat is the guide's
maximum use, which Apiome does not read, so a change in repetition is **dangerous** too.

## What Apiome does not check

- **No implementation guide is consulted.** Apiome reads the X12 syntax only, not the 004010 or 005010
  guides, so segment usage, element lengths and code lists are not checked. A structurally valid
  interchange is not claimed to be a conformant one.
- **`HL` loops** are read as the segments they are, not as the hierarchy they encode.
- **Values are samples.** Two interchanges of one transaction set can differ in every value and still
  follow the same definition; the diff grades them that way.

## Related

- [Import a UN/EDIFACT interchange](./edifact-import.md)
- [Read a catalog item's format details](./catalog-format-details.md#the-x12-inspector)
- [Import an XML Schema (XSD)](./xsd-import.md#ubl-and-peppol-document-schemas), for UBL 2.1 and
  Peppol e-invoicing
- [Built-in lint rules](../build/lint-rules.md#pack-edix12)
