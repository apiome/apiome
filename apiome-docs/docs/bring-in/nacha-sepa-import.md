---
title: "Import NACHA ACH and SEPA payment files"
description: "Catalog ACH payment batches and route SEPA payment files to ISO 20022."
sidebar_position: 20
tags: [import, nacha, ach, sepa, iso20022, payments]
---

**NACHA ACH** and **SEPA** are the payment-batch formats of the US and the EU. They look nothing
alike, so Apiome reads them in two different ways:

- An **ACH file** is fixed-width text — every record exactly 94 characters — and has its own
  importer, `nacha`. Its batches and entries become a schema in the [Catalog](./catalog.mdx), and
  every control total the file declares is shown beside what Apiome counted.
- A **SEPA file** (`pain.001`, `pain.008`, `pacs.008`) is ISO 20022 XML, which Apiome already reads.
  It goes to the **ISO 20022** importer, which records the message id and the **SEPA** profile. There
  is no separate SEPA importer.

## What you can import

| You have | Importer | What Apiome makes of it |
| --- | --- | --- |
| An ACH file (`.ach`, `.txt`) — PPD, CCD, WEB, TEL… batches | **NACHA ACH** (`nacha`) | One catalog item |
| An ACH file written without line breaks (one long line) | **NACHA ACH** | One catalog item; Apiome cuts it into 94-character records |
| An archive (`.zip`, `.tar.gz`) of an ACH file and its companions (a return file) | **NACHA ACH** | One catalog item read from the root file |
| A SEPA credit transfer (`pain.001`), direct debit (`pain.008`) or interbank transfer (`pacs.008`) | **ISO 20022** (`iso20022`) | One catalog item with the SEPA profile |
| Another ISO 20022 message (`camt.053`, `pain.002`) | **ISO 20022** | One catalog item, as before, with no profile |

## Import an ACH file

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the file — try
   `apiome-ui/examples/nacha/03-composition-ccd-with-addenda.ach` — or choose **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: NACHA ACH** (`nacha`) and routes it to the
   Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the file to the import endpoints with the source kind `nacha`; see
[Import sources](../reference/rest/import-sources.md).

Apiome recognises an ACH file by its first record: record type `1`, record size `094` at positions
35–37 and blocking factor `10` at 38–39.

### How an ACH file is read

| Record | Code | What Apiome records |
| --- | --- | --- |
| **File header** | `1` | Immediate destination and origin, creation date and time, file ID modifier, record size, blocking factor |
| **Batch header** | `5` | Service class (200 mixed, 220 credits, 225 debits), company name and id, **SEC code**, entry description, effective date |
| **Entry detail** | `6` | Transaction code, receiving DFI routing number and check digit, account number, amount (in cents), identification number, name, addenda indicator, trace number |
| **Addenda** | `7` | Type `05` payment-related information (an `RMR` remittance, a `TXP` tax payment), `98` notification of change, `99` return |
| **Batch control** | `8` | Entry/addenda count, entry hash, total debit, total credit |
| **File control** | `9` | Batch count, block count, entry/addenda count, entry hash, total debit, total credit |

Addenda records belong to the entry before them. Lines of 94 nines after the file control are block
padding and are counted, not read.

### What becomes the schema

| In the file | Becomes |
| --- | --- |
| The file, its batches and their entries | Record types **AchFile** → **Batch** → **EntryDetail**, linked as lists (`batches`, `entries`) |
| Each record layout (file header, batch header, entry, controls) | Its own record type, one field per fixed-width field, with its positions and kind recorded |
| Each addenda type the file carries (`05`, `99`…) | A record type (**Addenda05**) and a list on **EntryDetail** (`addenda05`) |
| SEC codes, batches and every control total | The item's file record (`nacha_sec_codes`, `nacha_batches`, `nacha_control_totals`) |

No payment value — account number, name, amount — goes into the schema. Those live only in the
native analysis on the item's **Format details** tab, where the value-visibility policy governs
them ([the NACHA analysis](./catalog-format-details.md#the-nacha-ach-analysis)).

### Control totals: declared versus observed

Every total a batch control or file control record declares is recomputed from the records that
are actually there:

| Total | How Apiome counts it |
| --- | --- |
| Entry/addenda count | Entry detail records plus addenda records |
| Entry hash | The sum of every entry's 8-digit receiving DFI routing number, keeping the rightmost ten digits |
| Total debit / total credit | Entry amounts in cents, split by transaction code (`x1`–`x4` credit, `x5`–`x9` debit) |
| Batch count | Batches in the file |
| Block count | Ten-record blocks the file fills, padding included |

Both figures are shown — **declared…** beside **observed…** on the batch and file rows, with
**controlTotalsConsistent** — and the item's file record lists them too. A file that disagrees with
itself is **imported, not rejected**, and each disagreement is stated as a warning
(`nacha.control_total_mismatch`). Try `apiome-ui/examples/nacha/06-stress-control-total-mismatch.ach`:
it declares five entries, a zero hash and a 999999 credit total for two entries, and all eight
disagreements are listed.

## Import a SEPA file

1. **Go to Bring in → Catalog** and **click "Import to catalog"**.
2. On **Source**, choose **File** and drop the file — try
   `apiome-ui/examples/sepa/04-stress-pain008-direct-debit.xml`.
3. On **Detect & route**, Apiome reports **Auto-detected: ISO 20022** (`iso20022`). The detection
   reason names the message id and says it is a SEPA payment message
   (`pain.008.001.08 (SEPA payment message)`).
4. On **Quality**, review the lint findings and **click "Import"**.

The SEPA profile is recorded:

- **In provenance.** The revision's import provenance carries `formatProfile` — key `sepa`, the
  message id (`pain.001.001.09`), its family and scheme (SEPA Credit Transfer, SEPA Direct Debit),
  the evidence it was recognised on, and `implementation_guide_consulted: false`. The canonical model
  carries the same record under `format_profile`, beside `iso20022_message_id`.
- **In the capability panel.** The ISO 20022 entry's versions list the SEPA families and their
  recognised versions.

Apiome applies two rules to a SEPA message, both from the message definition itself:

- Each payment block (`PmtInf`) — or, in a `pacs.008`, the message — must carry at least one
  transaction (`CdtTrfTxInf` or `DrctDbtTxInf`).
- The message-definition version must be one Apiome recognises: `pain.001.001.01`–`.12`,
  `pain.008.001.01`–`.11`, `pacs.008.001.01`–`.13`. An unpublished version such as
  `pain.001.001.99` is refused.

## What Apiome does not check

- **The NACHA Operating Rules are not consulted.** SEC-code requirements, return-reason meanings and
  bank file specifications are not evaluated, and routing numbers are not looked up (only their
  check digit is recomputed). An **IAT** batch is read with the domestic layouts, and the analysis
  says so (`nacha.iat_layout_not_modelled`).
- **The EPC rulebooks are not consulted.** The EUR-only rule, the SEPA character set, IBAN and BIC
  validity and field lengths are not checked, so a structurally valid SEPA message is not presented
  as a rulebook-conformant one.
- **Values follow the value-visibility policy.** By default a field's length is kept and its value
  withheld.

## When an import is refused

| What is wrong | Importer | Error code |
| --- | --- | --- |
| The file stops inside a record, inside a batch, or before the file control | NACHA ACH | `INPUT_TRUNCATED` |
| A record is not 94 characters, or has a record type other than 1, 5, 6, 7, 8, 9 | NACHA ACH | `INPUT_MALFORMED` |
| A batch has no entries, an addenda has no entry before it, a record sits outside a batch, or content follows the file control | NACHA ACH | `INPUT_SEMANTIC_INVALID` |
| The file does not open with an ACH file header (a SEPA XML file, for one) | NACHA ACH | `FORMAT_MISMATCH` |
| The XML stops partway through a tag or value | ISO 20022 | `INPUT_TRUNCATED` |
| A SEPA payment block carries no transaction | ISO 20022 | `INPUT_SEMANTIC_INVALID` |
| A SEPA message version is above the recognised range | ISO 20022 | `FORMAT_VERSION_UNSUPPORTED` |
| An ACH file was sent to the ISO 20022 importer | ISO 20022 | `FORMAT_MISMATCH` |
| The file is not UTF-8 text (UTF-16, for example) | Either | `INPUT_ENCODING_INVALID` |
