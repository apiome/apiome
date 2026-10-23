---
title: "Import VSAM cluster definitions and CICS BMS maps"
description: "Catalog VSAM record envelopes from IDCAMS and 3270 screens from BMS maps."
sidebar_position: 32
tags: [import, mainframe, vsam, idcams, listcat, cics, bms, 3270]
---

Two mainframe sources describe data without being a program. A **VSAM cluster definition** gives a
file's key positions, record lengths and organisation. A **CICS BMS map** gives the field layout of
a 3270 screen, which is in practice the API of a green-screen transaction. Apiome imports both into
the [Catalog](./catalog.mdx) as **data schemas**. There is one importer for each:

| Importer | Key | Reads |
| --- | --- | --- |
| **VSAM cluster definitions (IDCAMS)** | `vsam-idcams` | IDCAMS `DEFINE CLUSTER`, `DEFINE AIX`, `DEFINE PATH` and `DEFINE GDG` commands, bare or in the JCL that runs them, and `LISTCAT` listings |
| **CICS BMS maps** | `cics-bms` | `DFHMSD` / `DFHMDI` / `DFHMDF` macro source, and the symbolic-map copybook BMS generates from it |

Each importer refuses the other's files, so a BMS mapset sent to `vsam-idcams` fails with
`FORMAT_MISMATCH` instead of producing an empty item.

## Import it

Import the file or archive like any other specification: in the
[import wizard](./import-wizard.mdx), with `apiome import`, or through the REST API (see
[Import a specification](./import-a-spec.md)). Apiome detects which importer to use:

- **VSAM**: a `DEFINE CLUSTER`, `AIX`, `PATH` or `GDG` command, or a `LISTCAT` listing (`CLUSTER
  ------- <name>`).
- **BMS**: a `DFHMSD`, `DFHMDI` or `DFHMDF` statement, or a symbolic map.

Transfer mainframe members as **text** (EBCDIC to ASCII). A UTF-16 or binary transfer is refused
with `INPUT_ENCODING_INVALID`.

**Upload related files together.** An alternate index (`DEFINE AIX`) gives key offsets into its
*base* cluster's record, so if the base cluster is defined in another member, put both in one
archive (`.zip`, `.tar.gz`). For BMS, put the mapset source and its symbolic-map copybook in one
archive to get screen positions *and* the names the program uses.

## VSAM: what each part becomes

A cluster definition gives the record's **envelope**: its length, key positions and organisation. It
never gives the record's fields. Apiome models what is there and says what is missing.

| IDCAMS | In the catalog item |
| --- | --- |
| `DEFINE CLUSTER NAME(EXAMPLE.CUSTOMER.KSDS)` | A **record** `EXAMPLE_CUSTOMER_KSDS` in the `vsam` namespace. The dataset name is kept on the record |
| `INDEXED` / `NONINDEXED` / `NUMBERED` | The organisation, KSDS / ESDS / RRDS. A `NUMBERED` cluster whose average and maximum record sizes differ is a VRRDS. With no flag, IDCAMS assumes `INDEXED` |
| `KEYS(10 0)` | A field `PRIMARY_KEY`: `bytes`, exactly 10 long, at offset 0 of the record |
| `RECORDSIZE(200 200)` | The record size; **fixed** when the average and maximum are equal |
| `DEFINE AIX … RELATE(<cluster>) KEYS(8 40)` | A field `ALTERNATE_KEY_<last qualifier>` on the related cluster's record: 8 bytes at offset 40, unique (`UNIQUEKEY`, the default) or not (`NONUNIQUEKEY`) |
| `DEFINE PATH … PATHENTRY(<aix>)` | The path's name, listed on the alternate key it opens |
| `SHAREOPTIONS`, `FREESPACE`, `CONTROLINTERVALSIZE`, `CYLINDERS` / `TRACKS` / `RECORDS` / `MEGABYTES`, `VOLUMES`, SMS classes, `DATA` and `INDEX` component names | Storage details, kept on the record |
| A `LISTCAT` listing | The same record: `KEYLEN` and `RKP` are the key, `AVGLRECL` and `MAXLRECL` the record size, `SHROPTNS` the share options |

IDCAMS abbreviations are read as the full keyword: `IXD`, `NIXD`, `NUMD`, `RECSZ`, `SHR`, `FSPC`,
`CISZ`, `CYL`, `TRK`, `VOL`, `REL`, `PENT`, `UNQK`, `NUNQK` and others.

### What is declared, not imported

These are listed in the import's coverage ledger instead of being guessed:

- **The record layout.** Every record has only its keys. The fields come from the COBOL copybook or
  PL/I declaration that the programs use. Import that separately (see
  [Supported formats](./supported-formats.md#format-cobolcopybook)).
- **A `LINEAR` cluster.** A linear dataset has no record structure, so no record is made.
- **A generation data group.** A GDG holds a series of similar files and has no record structure.
- **A utility command.** `REPRO`, `BLDINDEX`, `DELETE`, `LISTCAT`, `SET` and non-VSAM `DEFINE`s
  describe work done on a file, not its record. They are listed on the item.
- **`LISTCAT` statistics.** `HISTORY`, `STATISTICS`, `ALLOCATION` and `VOLUME` sections are not read.
- **An unlisted alternate index.** A listing can name an associated AIX without listing it, so its
  key is unknown.

## BMS: what each part becomes

| BMS | In the catalog item |
| --- | --- |
| `DFHMSD` (the mapset) | The item's name and namespace. `LANG`, `MODE`, `CTRL` and the other operands are kept |
| `DFHMDI` (a map, one screen) | A **record** `<mapset>.<map>`. `SIZE=(rows,cols)` is its geometry. With no `SIZE`, BMS's 24 × 80 is used |
| `DFHMDF` with a label | A **field**, numbered in screen order |
| `DFHMDF` without a label | A literal: screen text such as a title, prompt or function-key line. It is kept on the map, not made a field |
| `POS=(row,col)`, `LENGTH` | The field's position and length. `POS=n` is an offset into the map |
| `PICIN` / `PICOUT` | The type, from the input picture if there is one, otherwise the output picture: `9(8)` is an integer, `9(7)V99` a decimal, and `X(10)` or an edited picture such as `ZZ,ZZ9.99` a string. A string's maximum length is `LENGTH` |
| `OCCURS=8` | A list of exactly 8 |
| `ATTRB=(…)` | Declared attributes: **protection** (`PROT`, `UNPROT`, `ASKIP`; default autoskip), **numeric** (`NUM`), **intensity** (`BRT`, `NORM`, `DRK`; default normal), **initial cursor** (`IC`) and **modified-data tag** (`FSET`) |
| `COLOR`, `HILIGHT`, `VALIDN`, `JUSTIFY`, `INITIAL`, `GRPNAME` | Kept on the field. A mapset or map `COLOR` / `HILIGHT` is shown on each field that does not set its own |
| A symbolic-map copybook (`<map>I`, `<map>O REDEFINES <map>I`) | With its mapset, each field's `L` / `F` / `A` / `I` / `O` entry names and pictures. On its own, a record per map, without screen positions |

Field attributes are **declared metadata**, not validation rules. A map gives field names, lengths,
positions and pictures. It says nothing about business meaning or what the transaction does with a
field, and Apiome does not infer either.

### What is declared, not imported

- **A literal field**: an unlabelled `DFHMDF`, kept on the map.
- **An edited picture**: a display picture (`Z`, comma, sign, currency) is read as a string.
- **The layout of repeated fields**: only the first occurrence of an `OCCURS` field is placed.
- **Positions of a copybook read alone**: import the mapset beside it to place the fields.
- **A symbolic map that does not match**: the copybook names a field the map does not have, or a
  different length. It was generated from another version of the mapset, so regenerate it.

## When an import is refused

| Error code | VSAM | BMS |
| --- | --- | --- |
| `INPUT_MALFORMED` | A command IDCAMS does not know, a parameter inside another parameter's values (a parenthesis left open), a stray `)`, or a non-numeric `KEYS` / `RECORDSIZE` | A statement that is not a BMS macro (a continuation line without the column-72 mark reads this way), operands ending in a comma with no continuation, unbalanced parentheses, a map outside a mapset or a field outside a map |
| `INPUT_TRUNCATED` | The input ends on a `-` continuation, inside a parameter list or inside a comment | The source ends on a continuation mark, inside a quoted value, or before `DFHMSD TYPE=FINAL` |
| `INPUT_SEMANTIC_INVALID` | A definition without `NAME`; an `INDEXED` cluster without `KEYS` (Apiome does not assume IDCAMS's `KEYS(64 0)`); `KEYS` on a cluster that has no key; a key past the end of the record; a name defined twice; nothing but linear datasets | A map with no named field, a mapset with no map, a named field without `POS` or length, a name used twice, or fields that overlap or fall outside the map |
| `INPUT_REFERENCE_UNRESOLVED` | An `AIX` whose `RELATE`, or a `PATH` whose `PATHENTRY`, names nothing defined in the upload | — |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 text | Same |
| `FORMAT_MISMATCH` | No IDCAMS command and no LISTCAT listing, such as a BMS mapset | No BMS macro and no symbolic map, such as an IDCAMS job or an ordinary copybook |

## Related

- [Supported formats](./supported-formats.md#format-vsam-idcams): what the VSAM importer reads.
- [Supported formats](./supported-formats.md#format-cics-bms): what the BMS importer reads.
- [Import a specification](./import-a-spec.md): the import job and its options.
