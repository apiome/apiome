---
title: "Import Natural / ADABAS DDM"
description: "Catalog an ADABAS file from its DDM listing, with arrays and keys."
sidebar_position: 35
tags: [import, mainframe, natural, adabas, ddm, periodic-group, descriptor]
---

Software AG's Natural and ADABAS run core systems in many insurers and public agencies. A **DDM**
(Data Definition Module) describes one ADABAS file: its fields, levels, formats, lengths,
multiple-value fields, periodic groups and descriptors. Apiome imports a DDM listing into the
[Catalog](./catalog.mdx) as a **data schema**. Multiple-value fields and periodic groups become
arrays, and descriptors become declared key metadata.

| Importer | Key | Reads |
| --- | --- | --- |
| **Natural / ADABAS DDM** | `natural-ddm` | A DDM listing (`DDM Name …` header, `T L DB Name F Leng S D Remark` columns), and Natural `DEFINE DATA` views uploaded beside it |

## Import it

Import the file or archive like any other specification: in the
[import wizard](./import-wizard.mdx), with `apiome import`, or through the REST API (see
[Import a specification](./import-a-spec.md)). Apiome picks the DDM importer for a file with a
`DDM Name ......` header. Files ending `.ddm` are also accepted.

Transfer the listing as **text** (EBCDIC to ASCII). A UTF-16 or binary transfer is refused with
`INPUT_ENCODING_INVALID`. Lines starting with `*` are comments. Field lines are read word by word,
so a listing whose columns drift by a position still reads.

**Add the programs' views for occurrence bounds.** A DDM does not say how many occurrences a
multiple-value field or periodic group may have. A Natural program's view does:
`2 PHONE-NUMBER (1:5)`. Put the DDM and the Natural source (`.nsp`, `.nsl`, `.nsa`, `.nsg`,
`.nat`) in one archive and choose the DDM as the root. Each `VIEW OF <DDM name>` is matched to the
DDM, and its bounds become the arrays' maximum sizes. A remark such as `Up to 99 occurrences` on the
group's line is also read as its bound.

## What each part becomes

| DDM | In the catalog item |
| --- | --- |
| `DDM Name ...... CUSTOMER-FILE` | A **record** `CUSTOMER-FILE` in the `natural` namespace; `DB`, `File` and `Default Sequence` are kept on it |
| `  1 AA CUSTOMER-NUMBER  A 10  U` | A field, with its short name (`AA`), level, format and length |
| `M 1 AH PHONE-NUMBER  A 20` (multiple-value) | A **list** of `string`, with each value's length limit |
| `P 1 AI CONTACT` (periodic group) and its level-2 fields | A **list** of the record `CUSTOMER-FILE.CONTACT` |
| `G 1 AK BILLING` (group) and its members | A field of the record `CUSTOMER-FILE.BILLING` |
| `R 2 AB PARTY-NAME` (redefinition) | A field that names the field it redefines and its starting position |
| `D` / `U` in the descriptor column | The field is marked a **descriptor** (or unique descriptor) |
| `S`, `Q`, `H`, `N`, `C` lines | **Super-, sub-, hyper-, phonetic and collation descriptors**, listed as keys with their source byte ranges — not fields |
| `N` in the S column, or `NU` / `FI` in the remark | Null suppression / fixed storage, kept on the field |

### Formats

| Format | Becomes | Bytes |
| --- | --- | --- |
| `A` alphanumeric, `W` wide | `string` of at most the length | the length |
| `U` Unicode | `string` of at most half the length | the length (UTF-16) |
| `N` unpacked numeric `n.d` | `decimal` (with `d` > 0) or `integer` | n + d (zoned, one per digit) |
| `P` packed numeric `n.d` | `decimal` or `integer` | (n + d) ÷ 2 + 1 |
| `I` integer | `integer` | the length |
| `B` binary | `bytes` of exactly the length | the length |
| `F` / `G` floating point | `float` (4) or `double` (8) | the length |
| `L` logical | `boolean` | 1 |
| `D` date / `T` time | `date` / `datetime` | the length (4 / 7, packed) |

A length of `0` is a variable-length (LOB) field: it has no length limit.

## Lengths and their assumptions

Every field records its short name, level, format, length and **byte length**. ADABAS compresses
records, so fields have a standard length but no fixed position: no offsets are computed. The DDM
does not state everything a byte count depends on, so each import lists what it assumed:

- `n.d` for `N` and `P` means n digits before the decimal point and d after;
- one byte per `A` character in a single-byte code page; `U` is UTF-16;
- `N` is zoned and `P` packed, with the sign in the last nibble;
- `D` and `T` are Natural dates and times stored packed.

## Descriptors

The file's record lists every key the DDM declares, in order:

- each field marked `D` or `U`, with whether it is unique;
- each derived descriptor — its kind, short name, name, format, length and the source fields it is
  built from, such as `AB(1-40),AC(1-1)`: positions 1–40 of `AB` then position 1 of `AC`.

A super- or subdescriptor's length must equal the sum of its source ranges.

## What is declared, not imported

These are listed in the import's coverage ledger instead of being guessed:

- **No offsets**: ADABAS records are compressed.
- **Unbounded occurrences**: an array without a bound from a view or remark.
- **Derived descriptors**: keys, not stored data.
- **Redefinitions**: fields that share their parent's storage.
- **LOB fields**: no length limit.
- **A view over a DDM that is not in the upload**: listed, its bounds not applied.

## When an import is refused

| Error code | Cause |
| --- | --- |
| `INPUT_EMPTY` | The file is empty |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 text |
| `FORMAT_MISMATCH` | No `DDM Name` header, such as a COBOL copybook. Import that with the COBOL copybook importer |
| `INPUT_TRUNCATED` | The last field line stops after its length, while every other line has its descriptor column |
| `INPUT_MALFORMED` | No column banner, or a field line that does not read: an unknown type or format, a missing level, short name or length, a short name that is not two characters |
| `INPUT_SEMANTIC_INVALID` | No field lines, a level that skips or sits under a plain field, a periodic group inside a periodic group, a name or short name used twice, an empty group, redefinitions longer than their field, or a descriptor whose length differs from its sources |
| `INPUT_REFERENCE_UNRESOLVED` | A descriptor source, a redefinition or the default sequence names a short name the DDM does not define, or a view reads a field the DDM lacks |

## Related

- [Supported formats](./supported-formats.md#format-natural-ddm): what the DDM importer reads.
- [Supported formats](./supported-formats.md#format-cobolcopybook): COBOL copybooks, for the
  records Natural programs exchange with other systems.
- [Import IMS DBD and PSB](./ims-dbd-psb-import.md): another mainframe database.
- [Import a specification](./import-a-spec.md): the import job and its options.
