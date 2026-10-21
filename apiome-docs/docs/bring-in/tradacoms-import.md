---
title: "Import a TRADACOMS transmission"
description: "Catalog UK retail TRADACOMS order, invoice and delivery files."
sidebar_position: 19
tags: [import, tradacoms, edi, b2b, retail]
---

**TRADACOMS** is the EDI standard UK retail still runs on — orders, invoices, delivery notes and
acknowledgments between suppliers and retailers. It writes the same segments, elements and service
characters as [UN/EDIFACT](./edifact-import.md), but inside an envelope of its own (`STX` … `END`).
Apiome reads it as a **dialect profile on the EDIFACT engine**: EDIFACT's segment reader, with
TRADACOMS' own transmission, file and message structure on top. The messages become a schema in the
[Catalog](./catalog.mdx) that you can search, diff and convert, and every transmission, file and
message is kept as a native analysis on the item's **Format details** tab.

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| One transmission file (`.edi`, `.tra`) — `STX` … `END` | One catalog item |
| A file holding several transmissions back to back | One catalog item; every transmission is in the analysis |
| An archive (`.zip`, `.tar.gz`) of a transmission and its companions (an acknowledgment) | One catalog item read from the root transmission |
| The transmission on your clipboard | A paste |

A TRADACOMS transmission and an EDIFACT interchange share the `.edi` extension. Apiome tells them
apart by how the document opens: `STX=` is TRADACOMS, `UNB` (optionally after `UNA`) is EDIFACT. A
document sent to the wrong importer is refused as `FORMAT_MISMATCH`, never read as the other.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the transmission — try
   `apiome-ui/examples/tradacoms/03-typical-invoice-file.edi` — or choose **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: TRADACOMS** (`tradacoms`) and routes it to
   the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the transmission to the import endpoints with the source kind `tradacoms`; see
[Import sources](../reference/rest/import-sources.md).

## How a transmission is read

| Level | Opened by | What Apiome records |
| --- | --- | --- |
| **Transmission** | `STX` … `END` | Syntax (`ANAA:1`), sender and recipient codes, date and time, the sender's reference and application reference, and the message count `END` declares |
| **File** | A header message carrying `TYP` (`ORDHDR`, `INVFIL`, `DELHDR`, `ACKHDR`) | The header type, the transaction code and name (`0430 ORDERS`), and the `FIL` generation and version numbers |
| **Message** | `MHD` … `MTR` | The message reference (its sequence number), type and version (`ORDERS:9`), and the segment count `MTR` declares |
| **Segment** | `CLO=`, `ORD=`, `OLD=` … | Its elements and composite components, with exact source positions |

Segments are written `TAG=element+element:component'`, with `?` as the release character.

## What Apiome reads

| In the transmission | Becomes |
| --- | --- |
| The first **detail** message — the first that is not a file header (`ORDERS` rather than `ORDHDR`) | The canonical model — a **record type** named for the message (`MessageORDERS`) |
| A segment that occurs once in that message | Fields of the message type, named by reference (`ORD01`; `CLO01-2` for a composite's second component) |
| A segment that repeats (`OLD`, `ILD`) | Its own record type, listed from the message type |
| The `STX` envelope, the file and its other messages | The item's envelope record (`tradacoms_transmission`, `tradacoms_file`, `tradacoms_messages`), and the native analysis |

When a transmission carries more than one message, the analysis says which one the model came from
(warning `tradacoms.canonical_projection_subset`).

## The dialect profile

Every TRADACOMS import is recorded with the **TRADACOMS** profile:

- **In provenance.** The revision's import provenance carries `formatProfile` — the profile key and
  label, the evidence it was recognised on (`STX=`), and `implementation_guide_consulted: false`. The
  canonical model carries the same record under `format_profile`.
- **In the analysis.** The transmission row shows **profile** and **profileLabel**, each message shows
  whether TRADACOMS' message set names it (**inProfileMessageSet**), and the warning
  `tradacoms.dialect_profile_applied` states the profile and its boundary.
- **In the capability panel.** The format's entry names the profile, how it is recognised and where
  its modelling stops.

EANCOM and ODETTE/VDA are the other two dialect profiles; they are EDIFACT subsets and are recognised
on the [EDIFACT importer](./edifact-import.md#dialect-profiles).

## Control counts

`MTR` declares how many segments its message has (`MHD` to `MTR` inclusive) and `END` how many
messages the transmission has. Both are shown beside what was observed, with
**controlCountConsistent** saying whether they agree. A transmission whose counts disagree with
themselves is imported, not rejected, and each disagreement is stated as a warning
(`tradacoms.control_count_mismatch`).

The `MHD` message references are different: they must count 1, 2, 3 … through a transmission. A
document whose references skip is refused, because the messages it names are not the ones present.

## What Apiome does not check

- **The TRADACOMS manual is not consulted.** Which segments a message may carry, their order and
  their code values are recorded as written, not checked, and a file's transaction code is the
  sender's claim. The capability panel says the same.
- **Values follow the value-visibility policy.** By default an element's length is kept and its value
  withheld. The `STX` recipient's reference — which some trading partners use as a password — is
  never lifted out of its element.

## When an import is refused

| What is wrong | Error code |
| --- | --- |
| The file ends mid-segment, or inside a message before its `MTR` | `INPUT_TRUNCATED` |
| A segment tag is not followed by `=`, or a segment terminator is missing | `INPUT_MALFORMED` |
| A transmission has no `END` or no message, a segment sits outside any message, an `MHD` has no `MTR`, or the `MHD` references skip | `INPUT_SEMANTIC_INVALID` |
| The file was sent as `tradacoms` but is an EDIFACT interchange, or some other format | `FORMAT_MISMATCH` |
| The file is not UTF-8 text (UTF-16, for example) | `INPUT_ENCODING_INVALID` |
