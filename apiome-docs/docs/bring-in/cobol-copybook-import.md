---
title: "Import COBOL copybooks"
description: "Catalog COBOL record layouts as types, with layout diffs and lint."
sidebar_position: 31.5
tags: [import, mainframe, cobol, copybook, redefines, occurs, ebcdic, lint, breaking-change]
---

A **COBOL copybook** is the record layout of a mainframe file, message or CICS COMMAREA:
level numbers give the nesting, `PIC` clauses give each item its type and width, `OCCURS`
makes a table and `REDEFINES` lays the same bytes out a second way. The **COBOL Copybook**
importer (`cobolcopybook`) reads a copybook into the [Catalog](./catalog.mdx) as a **data
schema**. You can then search, version, diff and lint it like any other catalog item. Each
version compares the records **by byte position**, which is how the programs that read them
see them.

## What you can import

A copybook with one `01` record, in fixed format (sequence area in columns 1–6, code from
column 8) or free format:

```cobol
       01  PAYMENT-RECORD.
           05  PAYMENT-ID              PIC 9(10).
           05  PAYMENT-TYPE            PIC X(1).
               88  PAY-BY-CARD         VALUE 'C'.
               88  PAY-BY-BANK         VALUE 'B'.
           05  PAYMENT-AMOUNT          PIC S9(9)V99 COMP-3.
           05  PAYMENT-DETAIL          PIC X(30).
           05  CARD-DETAIL REDEFINES PAYMENT-DETAIL.
               10  CARD-NUMBER         PIC 9(16).
               10  CARD-EXPIRY-YYMM    PIC 9(4).
               10  FILLER              PIC X(10).
           05  BANK-DETAIL REDEFINES PAYMENT-DETAIL.
               10  BANK-ROUTING        PIC 9(9).
               10  BANK-ACCOUNT        PIC X(17).
               10  FILLER              PIC X(4).
           05  PAYMENT-POSTED-DATE     PIC 9(8).
```

The importer reads `PICTURE`, `USAGE` (`DISPLAY`, `COMP` / `BINARY`, `COMP-3` /
`PACKED-DECIMAL`, `COMP-1`, `COMP-2`), fixed and variable `OCCURS … DEPENDING ON`, `REDEFINES`
and 88-level conditions. It also reads clauses continued onto the next line.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the copybook — try
   `apiome-ui/examples/cobol-copybook/03-payment-redefines.cpy` — or choose **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: COBOL Copybook** (`cobolcopybook`) and
   routes it to the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the copybook to the import endpoints with the source kind `cobolcopybook`; see
[Import sources](../reference/rest/import-sources.md). From the CLI:

```bash
apiome import cobolcopybook ./03-payment-redefines.cpy
```

The eight examples in `apiome-ui/examples/cobol-copybook/` include a customer record with a
variable phone table, an order line, a payment with two `REDEFINES` layouts, a warehouse snapshot
with packed and binary items, an ACH entry and an account master. One has unmodelled clauses and
one has deliberately faulty overlays.

## What Apiome reads

| In the copybook | Becomes |
| --- | --- |
| The `01` record and each group item | A **record type** (`PAYMENT-RECORD.CARD-DETAIL`), one field per subordinate item, in source order |
| `PIC X(n)`, `PIC A(n)`, a numeric-edited picture (`ZZ9.99`) | `string`, its width as the maximum length |
| `PIC 9(n)` / `S9(n)`, up to 9 digits / up to 18 | `i32` / `i64`, with the bounds the digits allow (minimum `0` when unsigned) |
| A picture with an implied decimal point (`V`), or more than 18 digits | `decimal`, with its bounds |
| `COMP-1` / `COMP-2` | `float` / `double` |
| `OCCURS n TIMES`, `OCCURS m TO n TIMES DEPENDING ON` | A list of the item's type, its bounds as the minimum and maximum item count |
| `REDEFINES` | A **union** named `<base>-OVERLAY` with one member per layout of the shared bytes (see below) |
| Each item's position | Its byte **offset** and **length** in the record, and how its bytes are encoded (below) |

Every field also keeps its level number, `PIC` and `USAGE` text, `OCCURS` bounds, `DEPENDING ON`
controller and 88-level conditions. The item's **Format details** tab shows the full layout as a
storage map; see [the COBOL copybook inspector](./catalog-format-details.md#the-cobol-copybook-inspector).

### REDEFINES becomes a union

`CARD-DETAIL` and `BANK-DETAIL` are not more fields after `PAYMENT-DETAIL`. They are the same
30 bytes, read two other ways. The record therefore keeps **one** field, `PAYMENT-DETAIL`, typed
by the union `PAYMENT-DETAIL-OVERLAY`. The union's members are `PAYMENT-DETAIL` (the bytes as
`PIC X(30)`), `CARD-DETAIL` and `BANK-DETAIL`. An item that redefines something the copybook does
not declare stays an ordinary field, and lint flags it.

### Storage and EBCDIC notes

A copybook does not say which code page its data is in. Apiome assumes **EBCDIC** and records
that as an assumption, together with the sizing assumptions every byte count rests on. Each
elementary item records how its bytes are encoded, so a consumer moving the data off the
mainframe knows what to transcode and what to leave alone:

| Storage | Items | What to do with the bytes |
| --- | --- | --- |
| EBCDIC text | `PIC X`, `PIC A` | Transcode as text, one character per byte |
| EBCDIC edited | Numeric-edited pictures | Transcode as text; it is formatted for printing |
| Zoned decimal | `PIC 9` / `S9`, `DISPLAY` | One EBCDIC digit per byte, the sign in the last byte's zone nibble. Convert as a number |
| Packed decimal | `COMP-3` / `PACKED-DECIMAL` | Two digits per byte and a sign nibble. Never transcode |
| Binary | `COMP` / `COMP-4` / `BINARY` | Big-endian two's complement. Never transcode |
| Hexadecimal float | `COMP-1` / `COMP-2` | IBM hexadecimal floating point unless compiled for IEEE. Never transcode |

### The layout fingerprint

Besides the fingerprint every catalog item has, a copybook item records a **record-layout hash**
(`cobol-record-layout-sha256`). It is computed from each item's position, length, storage,
`OCCURS` bounds and `REDEFINES` target, and never from a name. Renaming items, renumbering
levels or editing 88-level conditions keeps the hash. Moving a byte changes it. Two copybooks
with the same layout hash read each other's records.

## Versions and changes

Import a newer copybook into the same item to add a version. A program reads an item by its
offset and length, not by its name, so the comparison grades every change by what it does to
the bytes:

| Change | Severity | Rule |
| --- | --- | --- |
| An item starts at another offset | Breaking: it, and everything after it, is cut wrongly | `cobolcopybook.offset-moved` |
| An item's length, `OCCURS` bounds, `PIC` or `USAGE` changed | Breaking | `cobolcopybook.length-changed`, `cobolcopybook.occurs-changed`, `cobolcopybook.picture-changed` |
| An item removed, or inserted before other items | Breaking | `cobolcopybook.field-removed`, `cobolcopybook.field-inserted` |
| An item added after the last byte | Dangerous: offsets hold, but the record grows | `cobolcopybook.field-appended` |
| An item added in spare `FILLER`, the record length unchanged | Safe | `cobolcopybook.field-added-in-place`, `cobolcopybook.filler-reclaimed` |
| A `REDEFINES` layout added / removed | Dangerous / Breaking | `cobolcopybook.overlay-added`, `cobolcopybook.overlay-removed` |
| The record grew with every offset held / changed length otherwise | Dangerous / Breaking | `cobolcopybook.record-length-changed` |
| An 88-level condition removed or its value changed | Dangerous: programs testing it break | `cobolcopybook.condition-removed` |
| Only 88-level conditions added | Safe | `cobolcopybook.condition-added` |
| Only level numbers changed | Safe | `cobolcopybook.level-renumbered` |

To see the classic safe change, import `POLICY-RECORD.v1.cpy` and then
`POLICY-RECORD.v2-compatible.cpy` from `apiome-rest/tests/fixtures/cobolcopybook_versions/`:
`POL-AGENT-CODE` is carved out of the spare `FILLER`, and every change grades **Safe**.
`POLICY-RECORD.v3-breaking.cpy` inserts an item after `POL-NUMBER`, and every later item
reports **Breaking**.

## Lint

The **Quality** step and the item's **Lint & score** tab add the `cobolcopybook` rules on top of
the common ones. Each finding names the item by its qualified name (`PAYMENT-RECORD.CARD-DETAIL`):

| Rule | Severity | Flags |
| --- | --- | --- |
| [`cobolcopybook.redefines-target-declared`](../build/lint-rules.md#cobolcopybook-redefines-target-declared) | Warning | A `REDEFINES` naming no earlier item of the same group |
| [`cobolcopybook.redefines-fits`](../build/lint-rules.md#cobolcopybook-redefines-fits) | Warning | A redefining layout larger than the item it redefines |
| [`cobolcopybook.redefines-discriminated`](../build/lint-rules.md#cobolcopybook-redefines-discriminated) | Info | An ambiguous overlay: no earlier item has enough 88-level conditions to say which layout holds data |
| [`cobolcopybook.redefines-variable`](../build/lint-rules.md#cobolcopybook-redefines-variable) | Warning | An `OCCURS … DEPENDING ON` table inside a `REDEFINES` |
| [`cobolcopybook.odo-controller-declared`](../build/lint-rules.md#cobolcopybook-odo-controller-declared) | Warning | A `DEPENDING ON` naming an item the copybook does not declare |
| [`cobolcopybook.odo-controller-precedes`](../build/lint-rules.md#cobolcopybook-odo-controller-precedes) | Warning | A `DEPENDING ON` controller declared after the table or inside it |
| [`cobolcopybook.odo-trailing-items`](../build/lint-rules.md#cobolcopybook-odo-trailing-items) | Info | Items after a variable-length table, whose offsets then vary |
| [`cobolcopybook.duplicate-name`](../build/lint-rules.md#cobolcopybook-duplicate-name) | Warning | A data name other than `FILLER` declared twice |
| [`cobolcopybook.storage-sized`](../build/lint-rules.md#cobolcopybook-storage-sized) | Warning | An item whose storage cannot be computed, such as `PIC N` |
| [`cobolcopybook.packed-odd-digits`](../build/lint-rules.md#cobolcopybook-packed-odd-digits) | Info | A `COMP-3` item with an even number of digits |
| [`cobolcopybook.filler-unused`](../build/lint-rules.md#cobolcopybook-filler-unused) | Info | A `FILLER`: storage no program can read by name |
| [`cobolcopybook.condition-values-unique`](../build/lint-rules.md#cobolcopybook-condition-values-unique) | Warning | Two 88-level conditions of one item testing the same value |

Import `08-overlay-warnings.cpy` to see the three `REDEFINES` rules fire.

## Export

A copybook item writes back out as the same copybook through the **COBOL Copybook** target,
`REDEFINES` and all; see [Export a spec](../ship/export-a-spec.md). Export it to **JSON Schema** to
describe the record to a modern consumer: each overlay becomes a `oneOf` of its layouts, and each
item keeps its maximum length or numeric bounds.

## When an import is refused

| What Apiome reports | Why | What to do |
| --- | --- | --- |
| *Content does not appear to be a COBOL copybook* | No `01` level with a `PIC` clause | Check that the file is a copybook, or pick the right format |
| *COBOL copybook must begin with a level-01 group item* | A `05` (or other level) comes before the first `01` | Start the record at `01` |
| *Invalid or empty COBOL copybook content* | The file is empty or holds only comments | Upload the copybook itself |

Level-66 `RENAMES` and `COPY … REPLACING` are not read. The record imports, and the inspector
marks it partial with the reason.

## Related

- [The COBOL copybook inspector](./catalog-format-details.md#the-cobol-copybook-inspector): the storage map of an imported copybook
- [Link z/OS Connect to its copybooks](./zos-connect-binding.md): copybooks behind a REST API on z/OS
- [Import PL/I structures](./pli-structure-import.md): the same records, declared in PL/I
- [Import VSAM cluster definitions and CICS BMS maps](./vsam-cics-bms-import.md): the files and screens copybooks describe
- [Built-in lint rules](../build/lint-rules.md): every rule with its rationale
