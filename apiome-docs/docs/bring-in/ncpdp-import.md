---
title: "Import NCPDP SCRIPT and Telecom messages"
description: "Catalog NCPDP e-prescriptions and Telecommunication D.0 pharmacy claims."
sidebar_position: 22
tags: [import, ncpdp, script, telecom, pharmacy, healthcare]
---

**NCPDP** publishes the two standards US pharmacies run on: **SCRIPT**, the XML messages that carry
e-prescriptions between prescribers and pharmacies, and **Telecommunication D.0**, the delimited
format pharmacies bill claims in. Apiome reads both with one importer, `ncpdp`, and turns the
message into a schema in the [Catalog](./catalog.mdx). Every message's **transaction type** —
`NewRx`, `RxFill`, `B1` billing — is detected and recorded.

## What you can import

| You have | Sub-format | What Apiome makes of it |
| --- | --- | --- |
| A SCRIPT `Message` (`.xml`) — `NewRx`, `RxChangeRequest`, `RxFill`, `CancelRx`, `Status`, `Error`… | SCRIPT | One catalog item |
| A `Messages` batch of several SCRIPT messages | SCRIPT | One catalog item; the transaction type is recorded per message |
| A Telecom D.0 request (`.dat`) — `B1` billing, `B2` reversal, `B3` rebill, `E1` eligibility… | Telecom D.0 | One catalog item |
| An archive (`.zip`, `.tar.gz`) of a SCRIPT message and its responses | SCRIPT | One catalog item read from the root plus every SCRIPT file beside it |

## Import a message

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the file — try
   `apiome-ui/examples/ncpdp/02-typical-newrx.xml` for SCRIPT or
   `apiome-ui/examples/ncpdp/05-real-world-telecom-b1-claim.dat` for a Telecom claim — or choose
   **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: NCPDP SCRIPT / Telecom** (`ncpdp`) and
   routes it to the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the file to the import endpoints with the source kind `ncpdp`; see
[Import sources](../reference/rest/import-sources.md).

Apiome recognises the two sub-formats by how they open:

- **SCRIPT**: the first element is `Message` or `Messages` in the
  `http://www.ncpdp.org/schema/SCRIPT` namespace.
- **Telecom D.0**: a 56-character transaction header — a numeric BIN, the version/release, the
  transaction code — followed by `AM` segments.

## SCRIPT messages

A SCRIPT message has a `Header` (`To`, `From`, `MessageID`, `RelatesToMessageID`, `SentTime`…) and a
`Body` holding exactly one transaction element. That element's name is the **transaction type**,
detected per message, so a `Messages` batch carrying `RxFill`, `CancelRx` and `Status` records all
three.

| In the message | Becomes |
| --- | --- |
| Each element name (`NewRx`, `Patient`, `MedicationPrescribed`, `DrugCoded`…) | One record type, folded across every place it appears |
| A child element | A field: a nested record when it has children or attributes, otherwise a `string` |
| An attribute (`Qualifier`, `version`) | A field marked `ncpdp_xml: attribute`; the element's own text is its `value` field |
| An element that repeats | A list |
| An element missing from some occurrences | An optional field |
| The `Body` | One optional field per transaction type observed |
| Each message's transaction type, message ids and version | The item's file record (`ncpdp_transactions`, `ncpdp_transaction_types`) |

A `Status` or `RxChangeResponse` only says which prescription it answers through
`RelatesToMessageID`. Upload the pair as an archive and Apiome reads them as one conversation: the
response's **relatesToResolved** is `true` when the message it answers is in the upload.

## Telecom D.0 claims

A request transmission is a fixed **transaction header** and then segments. Each segment opens with
a separator and its `AM` segment id; each field opens with the field separator (`0x1C`) and a
two-character field id (`C2`, `D7`).

| Header field | Columns |
| --- | --- |
| 101-A1 BIN Number | 1–6 |
| 102-A2 Version/Release Number (`D0`) | 7–8 |
| 103-A3 Transaction Code (`B1`, `B2`, `E1`…) | 9–10 |
| 104-A4 Processor Control Number | 11–20 |
| 109-A9 Transaction Count | 21 |
| 202-B2 Service Provider ID Qualifier | 22–23 |
| 201-B1 Service Provider ID | 24–38 |
| 401-D1 Date of Service | 39–46 |
| 110-AK Software Vendor/Certification ID | 47–56 |

| In the transmission | Becomes |
| --- | --- |
| The transmission | Record type **TelecomTransmission** with `header`, `patient`, `insurance` and `transactions` |
| The patient (`AM01`) and insurance (`AM04`) segments | Fields on the transmission |
| Every other segment (`AM07` claim, `AM11` pricing, `AM03` prescriber…) | Fields on **Transaction**, one transaction per claim segment |
| Each segment id | One record type (**ClaimSegment**) with a `string` field per field id observed, described by its data element when Apiome knows it (`302-C2 Cardholder ID`) |
| The header | Record type **TransactionHeader**, each field with its columns recorded |
| Version, transaction code and transaction count | The item's file record (`ncpdp_telecom`, `ncpdp_transactions`) |

**Declared versus observed.** The header's transaction count (`109-A9`) is compared with the
transactions Apiome found, for the claim codes `B1`, `B2` and `B3` — each of their transactions
carries one claim segment. Both figures are recorded, and a disagreement is a warning
(`ncpdp.transaction_count_mismatch`): the transmission is **imported, not rejected**.

## Supported versions

| Sub-format | Versions read | How the version is used |
| --- | --- | --- |
| SCRIPT | Any — 10.x (`version="010" release="006"`) and 2017071 or later (`TransactionVersion`) | Recorded per message as the sender's claim; one element grammar is read for every version |
| Telecom | D.0 request transmissions only | Checked: a header naming any other version is refused |

The **capability panel** for NCPDP lists these versions too.

## What Apiome does not check

- **No implementation guide is consulted.** Not the SCRIPT Implementation Guide, not the Telecom
  D.0 Implementation Guide and data dictionary, and no payer sheet. A structurally readable message
  is never presented as a conformant one, and a field's presence is recorded, never its
  requiredness.
- **Telecom response transmissions are not read**, only requests.
- **No payload value enters the schema.** Patient names, dates of birth, drug codes, quantities and
  amounts live only in the native analysis on the item's **Format details** tab, where the
  value-visibility policy governs them ([the NCPDP analysis](./catalog-format-details.md#the-ncpdp-analysis)).
  By default a value's length is kept and the value itself withheld.

## When an import is refused

| What is wrong | Error code |
| --- | --- |
| The XML stops partway through, or the Telecom text stops inside its 56-character header | `INPUT_TRUNCATED` |
| The XML is not well formed; a Telecom segment has no `AM` id, a field has no two-character id, or the transmission contains a line break | `INPUT_MALFORMED` |
| A SCRIPT `Body` carries no transaction (or more than one), a message has no `Header` or `Body`, or a `Messages` batch is empty | `INPUT_SEMANTIC_INVALID` |
| A Telecom header names a version other than `D0`, an unknown transaction code, an unreadable transaction count, or no segments follow it | `INPUT_SEMANTIC_INVALID` |
| The file is neither SCRIPT nor Telecom — an HL7 v2 pharmacy order, for one | `FORMAT_MISMATCH` |
| The file is not UTF-8 text (UTF-16, for example) | `INPUT_ENCODING_INVALID` |
