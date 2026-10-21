---
title: "Import a UN/EDIFACT interchange"
description: "Catalog UN/EDIFACT interchanges — ORDERS, INVOIC, DESADV — beside EDI X12."
sidebar_position: 15
tags: [import, edifact, edi, b2b]
---

**UN/EDIFACT** (ISO 9735) is the rest of the world's EDI standard — the twin of the North American
**ANSI X12**. Apiome imports an EDIFACT interchange into the [Catalog](./catalog.mdx) the same way it
imports an X12 one: the messages become a schema you can search, diff and convert, and the whole
interchange — every group, message, segment and element — is kept as a native analysis on the
item's **Format details** tab.

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| One interchange file (`.edi`, `.edifact`) — `UNB` … `UNZ`, optionally after a `UNA` | One catalog item |
| An interchange with functional groups (`UNG` … `UNE`) | One catalog item; every group is in the analysis |
| An archive (`.zip`, `.tar.gz`) of an interchange and its companions (a `CONTRL` acknowledgement) | One catalog item read from the root interchange |
| The interchange on your clipboard | A paste |

An **X12** interchange (`ISA` / `GS` / `ST`) shares the `.edi` extension but is a different syntax:
Apiome detects it as **EDI X12** instead. A **TRADACOMS** transmission (`STX=`) writes EDIFACT-style
segments inside its own envelope, and is detected as [TRADACOMS](./tradacoms-import.md).

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the interchange — try
   `apiome-ui/examples/edifact/02-typical-invoic-d96a.edi` — or choose **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: UN/EDIFACT** (`edifact`) and routes it to
   the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the interchange to the import endpoints with the source kind `edifact`; see
[Import sources](../reference/rest/import-sources.md).

## Dialect profiles

EANCOM (GS1 retail) and ODETTE/VDA (automotive) are subsets of UN/EDIFACT, so they are read by this
importer and recognised as **dialect profiles** of it:

| Profile | Recognised by |
| --- | --- |
| **EANCOM** | An EANCOM association assigned code — `EAN` and three digits (`EAN008`) — in a `UNH` message identifier or a `UNG` message version |
| **ODETTE/VDA** | An ODETTE or VDA subset designator in an association code, or an interchange party identified with an ODETTE organisation code (`O` and digits) **and** every message in the ODETTE/VDA message set (`DELFOR`, `DELJIT`, `DESADV` …) |
| **UN/EDIFACT** | Neither — the interchange is read as plain UN/EDIFACT |

A weak resemblance is never enough: a GS1 party id alone does not make an interchange EANCOM.

The profile applied is recorded in three places:

- **Provenance** — the revision's import provenance carries `formatProfile`: the profile key and
  label, the evidence it was recognised on, and `implementation_guide_consulted: false`. The
  canonical model carries the same record under `format_profile`.
- **The analysis** — the interchange row shows **profile** and **profileLabel**; each message shows
  whether the profile's message set names it (**inProfileMessageSet**). The warning
  `edifact.dialect_profile_applied` states the profile and its evidence, and
  `edifact.message_outside_profile_set` names a message the set does not list — it is still read.
- **The capability panel** — the format's entry names both profiles, how each is recognised, and
  where each stops.

**Detect & route** names the profile too: *`UNB` interchange header … — EANCOM profile*.

Recognising a dialect is not validating against it: the EANCOM and ODETTE/VDA implementation guides,
their segment status rules and their restricted code lists are not evaluated, and GS1 identifiers
are recorded as written (check digits are not verified).

## Delimiters

Apiome reads the interchange with the service characters it was written with:

- **With a `UNA` segment**, its six characters are honoured exactly — component separator, element
  separator, decimal mark, release character, repetition separator and segment terminator. A
  `UNA:+,? '` interchange is read with a comma decimal mark.
- **Without `UNA`**, the ISO 9735 defaults apply: `:` `+` `.` `?` and `'`.
- A **release character** escapes the next character, so `?+` and `?'` inside a value read as `+`
  and `'`.
- A **repetition separator** exists only at syntax version 4 (`UNB` `UNOC:4`); before it, that `UNA`
  position is reserved and never splits a value.

The **Format details** tab shows which delimiters were declared and which were defaults.

## What Apiome reads

| In the interchange | Becomes |
| --- | --- |
| The first group's first message (or the first message, when there are no groups) | The canonical model — a **record type** named for the message (`MessageINVOIC`) |
| A segment that occurs once in that message | Fields of the message type, named by reference (`BGM02`; `DTM01-2` for a composite's second component) |
| A segment that repeats (`NAD`, `LIN`) | Its own record type, listed from the message type |
| `UNB`, `UNG`, `UNH`, the delimiters and the other messages | The item's envelope record, and the native analysis |

When an interchange carries more than one message, the analysis says which one the model came from
(warning `edifact.canonical_projection_subset`). The rest are described on the **Format details** tab
and nowhere else.

## The native analysis

The **Format details** tab renders the interchange in EDIFACT's own terms — **interchange →
functional group → message → segment → element**, with composite components under their element
and syntax-4 repetitions under the element they repeat. See
[Read a catalog item's format details](./catalog-format-details.md#the-edifact-analysis) for how to
read it:

- **Control counts, declared and observed.** The counts `UNT`, `UNE` and `UNZ` declare are shown
  beside the counts actually observed, and the control references they repeat are checked against
  their headers. A self-inconsistent interchange is imported, not rejected, and each disagreement is
  stated as a warning (`edifact.control_count_mismatch`, `edifact.control_reference_mismatch`).
- **Element presence** distinguishes *Has a value*, *Present, empty*, *Withheld*, *Not present* and
  *Not recorded*. `LIN+2++++'` writes five positions and only the first has a value.
- **Values follow the value-visibility policy.** By default an element's length is kept and its value
  withheld. Envelope facts (parties, references, delimiters, counts) are structure and are always
  shown; the `UNB` recipient password never is.

## What Apiome does not check

- **No implementation guide is consulted.** Only the UN/EDIFACT syntax is read — not the D.96A or
  D.01B directory, and not the EANCOM or ODETTE guide even when that
  [profile](#dialect-profiles) is recognised. A structurally valid interchange is not claimed to be
  a conformant one, and a message's directory (`D:96A`) and association code (`EAN008`) are
  recorded as the sender's claim. The capability panel says the same.
- **Segment groups** are shown as the flat segments they are, not as the nesting a directory gives
  them, and code values are recorded as written rather than looked up.
- **One batch interchange per document.** Interactive EDIFACT (`UIB` / `UIH`), packages (`UNO` /
  `UNP`) and a file holding several interchanges are refused rather than read in part.

## When an import is refused

| What is wrong | Error code |
| --- | --- |
| The file ends mid-segment, inside a message, or before `UNZ` | `INPUT_TRUNCATED` |
| A segment terminator is missing, a segment tag is unreadable, or `UNA` is malformed | `INPUT_MALFORMED` |
| A `UNH` has no `UNT`, a segment sits outside any message, or the interchange carries no message | `INPUT_SEMANTIC_INVALID` |
| The file was sent as `edifact` but is X12, TRADACOMS, or some other format | `FORMAT_MISMATCH` |
| The file is not UTF-8 text (UTF-16, for example) | `INPUT_ENCODING_INVALID` |
