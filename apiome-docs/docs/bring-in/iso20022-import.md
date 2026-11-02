---
title: "Import ISO 20022 messages and message definitions"
description: "Catalog ISO 20022 financial messages and the XSD message definitions behind them."
sidebar_position: 51
tags: [import, iso20022, swift, sepa, xsd, payments, finance]
---

**ISO 20022** is the financial messaging standard SWIFT, SEPA and most market infrastructures now
run on: payment initiations (`pain.001`), interbank transfers (`pacs.008`), statements (`camt.053`)
and hundreds more, each defined by an XML Schema the standard publishes. The **ISO 20022** importer
(`iso20022`) reads two things into the [Catalog](./catalog.mdx):

- a **message**, the XML a bank or corporate exchanges, whose schema Apiome infers from the elements
  it carries; and
- a **message definition**, the XSD itself (`pain.001.001.09.xsd`), read through the
  [XSD importer](./xsd-import.md) and labelled with the message it defines.

Either way the item is tagged with its message identifier, versions, diffs, lints and is searched
like any other catalog item. A SEPA payment message or definition also carries the **SEPA** profile
(see [NACHA ACH and SEPA](./nacha-sepa-import.md)).

## What you can import

| You have | How it is recognised | What Apiome reads |
| --- | --- | --- |
| A message: `<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">` | The `Document` namespace | The whole message: its structure becomes types, its values stay in the stored source |
| A message definition: `<xs:schema targetNamespace="urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08">` | The schema's target namespace | Every complex and simple type the definition declares |
| An archive whose root is either | The root member, chosen as for any archive | The root; a definition's `xs:import`s are answered by the other members |

An XML Schema in any other namespace is imported as a plain [XSD](./xsd-import.md). The
**Auto-detect** reason names the message identifier it found, and **SEPA payment message** when the
family is one.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the message or the schema — try
   `apiome-ui/examples/iso20022/01-pain.001-credit-transfer.xml` or
   `apiome-ui/examples/iso20022/07-pain.001.001.09-message-definition.xsd` — or choose **Paste**.
3. On **Detect & route**, Apiome reports **Auto-detected: ISO 20022** (`iso20022`) and routes it to
   the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the document to the import endpoints with the source kind `iso20022`; see
[Import sources](../reference/rest/import-sources.md). From the CLI:

```bash
apiome import iso20022 ./pain.001-credit-transfer.xml
apiome import iso20022 ./pain.001.001.09.xsd
```

The examples in `apiome-ui/examples/iso20022/` hold six messages (`pain.001`, `camt.053`,
`admi.004`, `pain.008`, `camt.054`, `pacs.008`) and two message definitions (`pain.001.001.09`,
`pacs.008.001.08`), the latter representative subsets of the published schemas.

## What Apiome reads from a message definition

| In the schema | Becomes |
| --- | --- |
| Each `xs:complexType` (`CustomerCreditTransferInitiationV09`, `PaymentInstruction30` …) | A **record type** with one field per member element, keeping `minOccurs` / `maxOccurs` as optional and list fields |
| A `…Choice` type (`AccountIdentification4Choice`: `IBAN` or `Othr`) | A record whose members are all optional: any one of them may be present |
| An amount type (`ActiveOrHistoricCurrencyAndAmount`: a decimal with a `Ccy` attribute) | A record with a `value` field of the amount's simple type and a `Ccy` field |
| Each `xs:simpleType` — text lengths (`Max35Text`), patterns (`IBAN2007Identifier`), dates | A **scalar type** with its base type |
| A code list (`PaymentMethod3Code`: `CHK`, `TRF`, `TRA`) | An **enum** |
| The `Document` root and the business element it wraps | Recorded as `iso20022_message_definition`: `root_element`, `business_element` (`CstmrCdtTrfInitn`), its type, and the message id split into `family`, `variant` and `version` |
| The target namespace | Recorded as `iso20022_message_id` and `iso20022_namespace`, as for a message |

The item's title names the business element and the message id, `CstmrCdtTrfInitn (pain.001.001.09)`,
so a definition and the messages that follow it sit together in search. The XSD provenance an XSD
import records (`xsd_root_element`, the canonical-XML hash, the import graph) stays on the item.

What a message import reads — the inferred types and the `iso20022_tree` that lets the message be
written back out — is unchanged; see [Supported formats](./supported-formats.md).

## Versions, diffs and lint

Import a newer release of the same definition (`pain.001.001.10`) into the same item to add a
version: added, removed and changed types and fields are reported by the standard rules for record
types, and because the two definitions of a family reuse the same component names
(`PartyIdentification135`, `CashAccount38`), a `pain.001` and a `pacs.008` definition compare
component by component.

The **Quality** step and the item's **Lint & score** tab apply the common rules. The SEPA
version ceiling (a `pain.001.001.99` message is refused) applies to messages, not to definitions: a
newer definition is the thing you import to learn what changed.

## Export

A message item writes back out as an ISO 20022 message. A message-definition item holds a schema,
not a message, so the **ISO 20022** target refuses it with that reason; export it as **XSD**,
**JSON Schema** or any other schema target instead (see [Export a spec](../ship/export-a-spec.md)).

## When an import is refused

| Code | Why | What to do |
| --- | --- | --- |
| `INPUT_SYNTAX_INVALID` | The XML is malformed or truncated | Paste the complete document |
| `INPUT_SEMANTIC_INVALID` | A message's `Document` is empty, or a SEPA payment block carries no transaction | Include the business element and at least one transaction |
| `INPUT_VERSION_UNSUPPORTED` | A SEPA message declares a message-definition version above the recognised ceiling | Import the message as the recognised version, or import its definition |
| `INPUT_DTD_REJECTED`, `INPUT_ENTITY_REJECTED` | The document declares a DTD or external entities | Remove them; ISO 20022 documents never need them |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): ISO 20022's coverage and export support
- [Import an XML Schema (XSD)](./xsd-import.md): the reader a message definition goes through
- [NACHA ACH and SEPA](./nacha-sepa-import.md): the SEPA profile on ISO 20022 payment files
- [Import SWIFT MT messages](./swift-mt-import.md): the MT side of the MT/MX migration
