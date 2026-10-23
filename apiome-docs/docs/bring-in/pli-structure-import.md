---
title: "Import PL/I structures"
description: "Catalog PL/I DECLARE structures with their byte-accurate storage map."
sidebar_position: 33
tags: [import, mainframe, pli, pl1, declare, include, storage-map]
---

PL/I structures sit beside COBOL copybooks in the same mainframe estates. They describe the same
records with a different declaration syntax. Apiome imports `DCL` / `DECLARE` structures, and the
`%INCLUDE` members they pull in, into the [Catalog](./catalog.mdx) as **data schemas**. Each
structure keeps a **storage map**: where every item starts and how many bytes it takes.

| Importer | Key | Reads |
| --- | --- | --- |
| **PL/I structures** | `pli` | `DCL` / `DECLARE` statements with level-numbered structures, and `%INCLUDE` directives resolved against the upload |

## Import it

Import the file or archive like any other specification: in the
[import wizard](./import-wizard.mdx), with `apiome import`, or through the REST API (see
[Import a specification](./import-a-spec.md)). Apiome picks the PL/I importer for a file with a
`DCL 1 <name>` structure, or any `DCL` statement or `%INCLUDE` directive. Files ending `.pli`,
`.pl1` or `.inc` are also accepted.

Transfer members as **text** (EBCDIC to ASCII). A UTF-16 or binary transfer is refused with
`INPUT_ENCODING_INVALID`. Sequence numbers in columns 73–80 and `*PROCESS` lines are ignored.

**Upload included members together.** A structure that clones a block with `LIKE`, or whose members
come from an `%INCLUDE`, only has a complete layout when the included members are in the upload.
Put the main file and its members in one archive (`.zip`, `.tar.gz`) and choose the main file as
the root. `%INCLUDE ADDRBLK;`, `%INCLUDE SYSLIB(ADDRBLK);` and `%INCLUDE 'addrblk.inc';` all find a
member named `ADDRBLK` with any suffix, in any folder of the archive.

## What each part becomes

| PL/I | In the catalog item |
| --- | --- |
| `DCL 1 ORDER_REC, …` (a major structure) | A **record** `ORDER_REC` in the `pli` namespace |
| `2 SHIP_TO, 3 …` (a minor structure) | A **record** named by its path, `ORDER_REC.SHIP_TO`, and a field that refers to it |
| `2 BILL_TO LIKE ADDRESS_BLOCK` | A field that refers to the `ADDRESS_BLOCK` record. The storage map lists the cloned members at their own offsets |
| `CHAR(n)`, `GRAPHIC(n)`, `WIDECHAR(n)`, with or without `VARYING` | A `string` of at most n characters |
| `FIXED DEC(p,q)`, `FIXED BIN(p,q)` | `decimal` when there is a scale `q`, otherwise `integer` |
| `FLOAT BIN` / `FLOAT DEC` | `float` (short precision) or `double` |
| `BIT(1)` / `BIT(n)` | `boolean` / `bytes` |
| `PIC'999V99'`, `PIC'ZZ9.99'`, `PIC'XXX'` | `decimal` or `integer` for a numeric picture; `string` for an edited or character picture |
| `POINTER`, `OFFSET`, `HANDLE`, `AREA` | `bytes` |
| `(10)`, `(1:12)`, `(4,3)` | A list of exactly that many items; a second dimension nests a second list |
| `UNION` | A record whose fields all start at the same offset. Each later member names the first as the storage it **redefines**, which is how COBOL `REDEFINES` is shown |
| `BASED(p)`, `STATIC`, `DEFINED`, `ALIGNED` / `UNALIGNED` | Kept on the item as declared |

Level numbers do not have to be consecutive: a `4` after a `2` is a member of the `2`, as in PL/I.
An item with no data attributes takes PL/I's defaults: `FIXED BIN(15)` for a name starting with
I–N, otherwise `FLOAT DEC(6)`. The item records which attributes were assumed.

## The storage map

Every field records its **offset** (1-based, from the start of the record it belongs to), its
**length** and **total length** (all elements of an array), and any **padding** placed before it
to reach its boundary. Each major structure also carries the full storage map, from its first
byte, with every `LIKE` copy expanded. The import's native analysis describes the same tree in PL/I's own terms: levels,
attributes as written, and the storage of each item.

PL/I does not state everything a byte count depends on, so the import says what it assumed. The
assumptions are on every import and every analysis:

- one byte per `CHAR` position, two per `GRAPHIC` or `WIDECHAR` position;
- a 2-byte length prefix before a `VARYING` string, and a terminator after a `VARYINGZ` one;
- packed decimal for `FIXED DEC`, the usual widths for `FIXED BIN` and `FLOAT`, and 4-byte locators;
- arithmetic and locator items `ALIGNED` by default, strings and pictures `UNALIGNED`, and
  `ALIGNED` on a structure applied to its members;
- an `ALIGNED` item padded to its natural boundary, counted from a structure that starts on a
  doubleword. The compiler can move a structure's start to save padding, and this calculation does
  not.

An `UNALIGNED` bit string starts at the next free bit, so its offset can fall part-way into a byte.
A `REFER` or `*` extent is a runtime value: that item has no fixed length, and nothing after it has
a single offset. An item whose size is not described, such as an `ENTRY`, also leaves later offsets
unknown. In each case the field shows why, rather than a guessed number.

## When an `%INCLUDE` is missing

What happens depends on what the missing member would have supplied:

| The missing member… | Result |
| --- | --- |
| declares a block that a `LIKE` (or `DEFINED`) needs | The import is refused with `INPUT_REFERENCE_UNRESOLVED`, naming the member. Upload it with the main file |
| sits **inside** a structure, so its lines would have been members | The record is marked **partial** and names the member. Nothing after that point has an offset, and the record has no total length |
| sits between declarations and nothing refers to it | The import goes ahead. The include is listed as unresolved on the item |

A layout is never shown as complete when part of it is missing.

## What is declared, not imported

These are listed in the import's coverage ledger instead of being guessed:

- **Unresolved includes**, as described above.
- **Shared storage**: a `UNION`'s members are fields at one offset.
- **Runtime extents**: `REFER` and `*` lengths and bounds.
- **Defaulted attributes**: items that took the language defaults.
- **Edited pictures**: read as strings, with the picture kept.
- **Locators and program-control items**: `POINTER` / `AREA` as bytes, `ENTRY` / `FILE` / `LABEL` as
  untyped.
- **Unread attributes**: an attribute the importer does not know is kept as written.
- **Scalars, other statements and unused members**: a declaration without a level number, a
  statement that is not a `DCL`, and an archive member no `%INCLUDE` reached are listed but not
  modelled.

## When an import is refused

| Error code | Cause |
| --- | --- |
| `INPUT_EMPTY` | The file is empty or holds only comments |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 text |
| `FORMAT_MISMATCH` | No `DCL`, `DECLARE` or `%INCLUDE`, such as a COBOL copybook. Import that with the COBOL copybook importer |
| `INPUT_TRUNCATED` | The source ends inside a comment, a quoted string, parentheses or a statement |
| `INPUT_MALFORMED` | A statement that does not parse, such as a missing `;` before the next `DCL` or a stray `)` |
| `INPUT_SEMANTIC_INVALID` | Level numbers that do not form a tree (a level 2 with no level 1 above it), a member under an item with data attributes, a `LIKE` of an element or in a cycle, members that include each other, a structure declared twice, or no structure at all |
| `INPUT_REFERENCE_UNRESOLVED` | A `LIKE` or `DEFINED` names something the upload does not declare |

## Related

- [Supported formats](./supported-formats.md#format-pli): what the PL/I importer reads.
- [Supported formats](./supported-formats.md#format-cobolcopybook): COBOL copybooks, the same records
  in COBOL syntax.
- [Import a specification](./import-a-spec.md): the import job and its options.
