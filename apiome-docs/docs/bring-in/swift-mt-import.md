---
title: "Import SWIFT MT messages"
description: "Catalog SWIFT MT103, MT202, MT940 and MT942 messages, with MX correspondence notes."
sidebar_position: 17
tags: [import, swift, payments, iso20022, finance]
---

**SWIFT MT** is the FIN message set banks still run in production beside ISO 20022 (MX) through the
coexistence period. Apiome imports MT messages into the [Catalog](./catalog.mdx) beside the MX
messages it already reads, keeps every block and field as a native analysis on the item's
**Format details** tab, and records which MX message each one corresponds to — as a **note**, never as
a conversion.

## What you can import

| Message | What it is | Documented MX counterpart |
| --- | --- | --- |
| **MT103** | Single customer credit transfer | `pacs.008` |
| **MT202** | General financial institution transfer | `pacs.009` |
| **MT202 COV** | Cover payment (block 3 field `119:COV`), with its sequence B | `pacs.009` (COV) |
| **MT940** | Customer statement | `camt.053` |
| **MT942** | Interim transaction report | `camt.052` |

A file may hold several messages written one after another; each one is in the analysis. Other MT
types (MT199, MT999, …) are refused. An ISO 20022 XML message is detected as **ISO 20022**, not as MT.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the message — try
   `apiome-ui/examples/swift-mt/02-typical-mt103.txt` — or choose **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: SWIFT MT** (`swift-mt`) and routes it to the
   Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the message to the import endpoints with the source kind `swift-mt`; see
[Import sources](../reference/rest/import-sources.md).

## What Apiome reads

| In the message | Becomes |
| --- | --- |
| `{1:}` basic header, `{2:}` application header, `{3:}` user header (`108` MUR, `121` UETR, `119` validation flag), `{5:}` trailer | Structure, recorded beside the model and on the message row |
| The message (`MT103`) | The root **record type** |
| Each field **with its option letter** — `32A`, `50K`, `50F`, `59F` | A record type of its own (`Field50K`) holding the field's components — currency, amount, account, BIC, debit/credit mark… |
| Code words in narrative fields — `/INV/`, `/RFB/`, `/ACC/`, `/OCMT/`, `/REMI/` | `CodeWord` records: the **qualifier** and its text |
| Option-F numbered lines — `1/NAME`, `2/ADDRESS` | `NumberedLine` records |
| A field that repeats (`71F`) | A list |
| MT940/942 `:61:` statement lines with the `:86:` after each | A list of `StatementLine` records |
| An MT202 COV's sequence B (underlying customer credit transfer) | A nested `SequenceB` record |

**Option letters are never flattened.** `50K` (name and address) and `50F` (structured, numbered lines)
are the same field in different options, so they stay different shapes. Payload values are never
written into the schema.

A field whose content does not match its documented shape is kept as its lines and flagged
(`swift.field_not_well_formed`) — the message is still imported.

## MT ↔ MX: a note, never a conversion

Each supported message carries its documented ISO 20022 counterpart, from SWIFT's published MT and MX
equivalence tables: on the message row as **mxCorrespondence** (with **verified** `false`), and as a
`swift.mx_correspondence_note` on the **Format details** tab. Every note says:

> This is a documented correspondence, recorded as a note. Apiome has not translated this message,
> has not checked it against the MX usage guidelines, and does not claim that a translation would be
> valid: field mappings, truncation and character-set rules, and data requirements of the MX message
> are outside what was read.

To work with the MX side, import the MX message itself — see
[Supported formats](./supported-formats.md).

## The native analysis

The **Format details** tab shows **message → block → sequence → field → component**. See
[Read a catalog item's format details](./catalog-format-details.md#the-swift-mt-analysis):

- **Headers and tags are structure.** The header blocks, each field's tag, option letter and name,
  a code word's qualifier and a numbered line's number are always shown.
- **Values follow the value-visibility policy.** Components, code-word texts and lines — accounts,
  names, amounts, references — are values; by default their length is kept and their text withheld.
- **A cover links to its payment.** In a file holding an MT103 and the MT202 COV that covers it, the
  cover's row shows **relatesToMessage**: the message whose field 20 its field 21 names.

## What Apiome does not check

- **SWIFT network-validated rules and usage rules** are not evaluated.
- **BICs are not looked up**, and `CHK`/`MAC` trailers are recorded but not verified.
- **No MX message is produced** from an MT message.

## When an import is refused

| What is wrong | Error code |
| --- | --- |
| The message stops inside a header block, or inside a field of an unterminated text block | `INPUT_TRUNCATED` |
| The text block has no `-}` terminator, a header is unreadable, or text sits outside the blocks | `INPUT_MALFORMED` |
| There is no field 20, no application header, or the message type is not one listed above | `INPUT_SEMANTIC_INVALID` |
| The file was sent as `swift-mt` but is another format (an ISO 20022 XML message, for example) | `FORMAT_MISMATCH` |
| The file is not UTF-8 text (UTF-16, for example) | `INPUT_ENCODING_INVALID` |
