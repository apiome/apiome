---
title: "Import IMS DBD and PSB"
description: "Catalog IMS segment hierarchies and the access profile each program declares."
sidebar_position: 34
tags: [import, mainframe, ims, dbd, psb, procopt, hierarchical-database]
---

IMS is the hierarchical database many banks, insurers and government agencies still run. Two macro
sources describe it. A **DBD** (Database Description) declares the segments, their fields and the
hierarchy. A **PSB** (Program Specification Block) declares what one program may see and what it
may do. Apiome imports both into the [Catalog](./catalog.mdx) as **data schemas**: the segment
hierarchy as nested records with byte-accurate fields, and each program's `PROCOPT` as a declared
**access profile**.

| Importer | Key | Reads |
| --- | --- | --- |
| **IMS DBD and PSB** | `ims` | `DBD` / `DATASET` / `SEGM` / `FIELD` / `LCHILD` / `XDFLD` … `DBDGEN`, and `PCB` / `SENSEG` / `SENFLD` … `PSBGEN` |

## Import it

Import the file or archive like any other specification: in the
[import wizard](./import-wizard.mdx), with `apiome import`, or through the REST API (see
[Import a specification](./import-a-spec.md)). Apiome picks the IMS importer for a file with a
`DBD NAME=…` or `PCB TYPE=…` statement. Files ending `.dbd` or `.psb` are also accepted.

Transfer members as **text** (EBCDIC to ASCII). A UTF-16 or binary transfer is refused with
`INPUT_ENCODING_INVALID`. Comment lines (`*` in column 1) and `PRINT` / `TITLE` / `FINISH`
statements are ignored.

**Upload a PSB with its DBD.** A PSB names segments and fields by name only; their types and lengths
are in the DBD. Put the DBD and the PSB in one archive (`.zip`, `.tar.gz`) and choose either as the
root. Each `PCB DBDNAME=` is matched to the DBD of that name in the archive. A PSB imported on its
own still shows its program views and access profile, with the fields untyped.

**Continuation lines.** A statement continues when a character sits in **column 72** after its
operands, and the next line carries on in column 16. A mark that lands one column late, in column
73 after a blank, is also read as a mark. An operand that itself runs past column 71 is read as one
long line, not a continued one.

## What each part becomes

| IMS | In the catalog item |
| --- | --- |
| `DBD NAME=CUSTDB,ACCESS=(HDAM,OSAM)` | The item's name; the access method, `DATASET`s and `RMNAME` are kept on the item |
| `SEGM NAME=ORDER,PARENT=CUSTOMER,BYTES=160` | A **record** `CUSTDB.ORDER` in the `ims` namespace, and on `CUSTOMER` a field **`ORDER`**: a list of `CUSTDB.ORDER` |
| `PARENT=0` (or no `PARENT`) | The root segment |
| `BYTES=(500,20)` | A variable-length segment, laid out at its maximum, with both bounds kept |
| `FIELD NAME=(CUSTID,SEQ,U)` / `(LINENO,SEQ,M)` | The **sequence field**, unique (`U`) or not (`M`) |
| `FIELD … TYPE=C` | A `string` of at most `BYTES` characters |
| `FIELD … TYPE=X` | `bytes` of exactly `BYTES` |
| `FIELD … TYPE=P` / `TYPE=Z` | `decimal` (packed: 2 × `BYTES` − 1 digits; zoned: `BYTES` digits) |
| `FIELD … TYPE=H` / `TYPE=F` | `integer` (2-byte / 4-byte binary) |
| `LCHILD … POINTER=INDX` and its `XDFLD` | A **secondary index** listed on the segment: index database, search fields (`SRCH`), `SUBSEQ`, `DDATA`, `NULLVAL` |
| `PARENT=((ORDER,SNGL),(CUSTOMER,PHYSICAL,CUSTDB))` | A logical child: the logical parent is named on the record |
| `ACCESS=LOGICAL` with `SOURCE=…` | One record per logical segment, naming the physical segments it is built from |
| `PCB TYPE=DB,DBDNAME=CUSTDB` with `SENSEG`s | A **program view**: a record `<PSB>.<PCB>.<segment>` for each sensitive segment, nested the same way |
| `SENFLD NAME=CUSTID,START=1` | A field of the program view, at its position in the program's I/O area |
| `PROCOPT=G`, `AP`, `GI` … | The **access profile**, decoded (see below) |

The hierarchy comes from `PARENT=`, not from the order of the statements. A child can be written
before its parent.

## Field positions and their assumptions

Every field records its **offset** (`START` − 1), its 1-based `START` and its **length**. A DBD
declares only the fields IMS needs — the sequence field and the fields programs search on — so a
segment usually has byte ranges no field covers. Those ranges are listed as **undescribed** on the
record, never filled in. Fields that overlap keep their own positions and name each other.

The DBD does not state everything a byte count depends on, so each import lists what it assumed:

- `START` and `BYTES` are 1-based byte positions and lengths in the segment as the program sees it;
- one byte per character (`TYPE=C`) in a single-byte code page;
- packed decimal holds 2 × `BYTES` − 1 digits with the sign in the last nibble, and no decimal point;
- `TYPE=H` is a 2-byte and `TYPE=F` a 4-byte signed binary integer;
- in a variable-length segment, positions are taken as written, not shifted past the 2-byte length
  prefix;
- a `SENFLD`'s `START` is its position in the program's I/O area, not in the stored segment.

## The access profile

Each `PROCOPT` is decoded into what it lets the program do:

| Letter | Meaning |
| --- | --- |
| `G` | get (read) |
| `I` | insert |
| `R` | replace |
| `D` | delete |
| `A` | all: get, insert, replace and delete |
| `P` | path calls |
| `K`, `O`, `E`, `L`, `S`, `H` … | key-sensitive, read without integrity, exclusive, load, sequential, high-speed sequential |

A `SENSEG` without its own `PROCOPT` takes the PCB's. The profile is shown three ways: on each
program-view record, in the PSB summary on the item (every PCB, its DBD and its sensitive segments
and fields), and — when the DBD is in the same upload — on the DBD's own segment record, listing
each program that can see it.

## What is declared, not imported

These are listed in the import's coverage ledger instead of being guessed:

- **Undescribed bytes**: the parts of a segment no `FIELD` covers.
- **Overlapping fields** and **variable-length segments**: kept, with the detail noted.
- **Index databases** and **`XDFLD` search fields**: named on the segment, not modelled.
- **Logical relationships** and **LOGICAL databases**: the logical parent and `SOURCE` segments are
  named, and resolved to their records when their DBD is in the upload.
- **System-related fields** (`/SX`, `/CK`): listed, not modelled.
- **A PSB whose DBD is not in the upload**: its views keep segment and field names without types.
- **TP and GSAM PCBs**: a message destination or a sequential file, listed on the PSB.

## When an import is refused

| Error code | Cause |
| --- | --- |
| `INPUT_EMPTY` | The file is empty |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 text |
| `FORMAT_MISMATCH` | No `DBD NAME=` or `PCB TYPE=` statement, such as a COBOL copybook. Import that with the COBOL copybook importer |
| `INPUT_TRUNCATED` | The source ends on a continuation mark, inside an operand list, or before the `DBDGEN` / `PSBGEN` that closes it |
| `INPUT_MALFORMED` | A statement that is not a DBD or PSB macro, a continuation line that does not start in column 16, an operand without `=`, unbalanced parentheses, a `FIELD` before any `SEGM`, or a `SENSEG` outside a database PCB |
| `INPUT_SEMANTIC_INVALID` | A DBD with no segment, no root or two roots, a `PARENT` loop, a name used twice, a field past the end of its segment, an unknown `TYPE`, or a `SENSEG` placed under a different parent than the DBD's |
| `INPUT_REFERENCE_UNRESOLVED` | A `PARENT` names no segment of the DBD, an `XDFLD` names a missing segment or field, or a `SENSEG` / `SENFLD` names something the PSB's DBD does not define |

## Related

- [Supported formats](./supported-formats.md#format-ims): what the IMS importer reads.
- [Supported formats](./supported-formats.md#format-cobolcopybook): COBOL copybooks, the full
  segment layout the programs use.
- [Import VSAM cluster definitions and CICS BMS maps](./vsam-cics-bms-import.md): other mainframe
  sources.
- [Import a specification](./import-a-spec.md): the import job and its options.
