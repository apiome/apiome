---
title: "Import HL7 v3 / CDA documents"
description: "Catalog CCDs, discharge summaries and other C-CDA clinical documents."
sidebar_position: 18
tags: [import, hl7, cda, healthcare]
---

**HL7 v3 Clinical Document Architecture (CDA)** is the XML standard for clinical documents — the
Continuity of Care Document (CCD), discharge summaries, referral notes and the other C-CDA document
types that national health programmes require. Apiome imports CDA documents into the
[Catalog](./catalog.mdx) beside the **HL7 v2** messages and **FHIR** resources it already reads. It
infers the document's schema, keeps the header and the section hierarchy, and records every
`templateId` as a conformance **claim** the document makes. Apiome does not check those claims.

## What you can import

| You have | What Apiome reads |
| --- | --- |
| A CDA R2 document (`<ClinicalDocument xmlns="urn:hl7-org:v3">`) — CCD, discharge summary, any C-CDA type | The whole document |
| An archive holding an HL7 v3 **transmission wrapper** (`MCCI_IN000002UV01`, for example) and the CDA document it carries | The CDA document the wrapper references, plus the wrapper as structure |

A **FHIR** `Composition` is detected as **FHIR**, not as CDA. An HL7 v3 message that is not a CDA
document (a patient registry message, for example) is refused.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the document — try
   `apiome-ui/examples/hl7v3/02-typical-ccd.xml` — or choose **Paste** and paste it. For a wrapper
   and its payload, upload both files together as a `.zip` archive.
3. On **Detect & route**, Apiome reports **Auto-detected: HL7 v3 / CDA** (`hl7v3`) and routes it to
   the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the document to the import endpoints with the source kind `hl7v3` (aliases `cda`,
`c-cda`); see [Import sources](../reference/rest/import-sources.md).

## What Apiome reads

| In the document | Becomes |
| --- | --- |
| RIM classes — `ClinicalDocument`, `RecordTarget`, `PatientRole`, `Author`, `Custodian`, `Section`, `Entry`, `Observation`, `Organizer` … | A **record type** each. Every occurrence of a class is folded into one type: a member that repeats anywhere is a list, and a member missing anywhere is optional |
| `component`, `participant`, `performer`, `subject` | A record type named after the class it sits in — `StructuredBodyComponent`, `SectionComponent`, `OrganizerComponent` — so the header → body → section → entry hierarchy reads from the types |
| Class attributes — `classCode`, `moodCode`, `typeCode`, `ID` | String fields |
| RIM data types | Canonical types — see the table below |
| An `xsi:type` that varies — an observation `value` that is `PQ` in one entry and `CD` in another | A union (`ObservationValueChoice`) |
| The section tree — each section's code, title, template ids and the clinical statement each entry holds | Recorded beside the model as `cda_sections` |
| The document type `code` and `typeId` | Recorded beside the model as `cda_document_code` and `cda_type_id` |

**Payload values are never written into the schema.** Patient names, identifiers, addresses, dates and
observation values stay in the stored source; the model holds only their shape.

### RIM data types

| RIM data type | Canonical type |
| --- | --- |
| `II` instance identifier | Record: `root`, `extension`, `assigningAuthorityName`, `displayable` |
| `CD`, `CE` coded values | Record: `code`, `codeSystem`, `codeSystemName`, `codeSystemVersion`, `displayName`, `originalText`, a list of `translation` |
| `CV`, `CS` | Record: the coded members (`CS` holds only `code`) |
| `TS` point in time | Record with a patterned `value` (`YYYYMMDDHHMMSS±ZZZZ` — an HL7 timestamp, not ISO 8601) |
| `IVL_TS` interval | Record: `value`, `low`, `high`, `center` (`TS`) and `width` (`PQ`) |
| `PQ`, `IVL_PQ`, `RTO_PQ_PQ` | Record: `value` (number) and `unit`; intervals and ratios of `PQ` |
| `INT`, `REAL`, `BL` | Record with a `value` (integer, number, boolean) |
| `AD` postal address | Record: `use`, a list of `streetAddressLine`, `city`, `state`, `postalCode`, `country`, `useablePeriod` … |
| `PN` person name | Record: `use`, lists of `prefix`, `given`, `family` and `suffix`, `validTime` |
| `TEL` | Record: `value`, `use` |
| `ED` encapsulated data | Record: `mediaType`, `language`, `representation`, `reference`, `text` |
| `ST`, `SC`, `ON`, a section's narrative block | Text |

Every record also carries `nullFlavor`. A data type outside this table (`PIVL_TS`, `MO`, `GLIST` …)
is a **declared parsing limit**. The element is kept as text and listed in `cda_datatype_limits` with
the field it was found in. It never fails the import.

## Template ids are claims, not verdicts

A `templateId` is what the document **asserts** it conforms to — a US Realm Header, a CCD, an
Allergies section. Apiome records every one in `cda_template_claims` with its location, `root`,
`extension`, `status: "asserted"` and `validated: false`, and states it in the item's capability
panel (**"HL7 v3 / CDA — what apiome records"** on the **Format details** tab):

> Asserted by the document, not validated: a templateId records which implementation-guide template
> the document claims to conform to. Apiome reads the claim; it does not check the document against
> the template's constraints, and a recognised template name is not a conformance verdict.

- A template id from the C-CDA R2.1 list gains its name (`Continuity of Care Document (CCD)`) and
  `recognised: true` — and nothing more.
- A template id Apiome does not recognise imports like any other, with `recognised: false`. Try
  `apiome-ui/examples/hl7v3/06-typical-unknown-template.xml`.

## Transmission wrappers

Upload a wrapper and its CDA document together, as an archive, with the wrapper as the root. Apiome
follows the wrapper's payload `reference` to the member holding the document and imports that
document. It records the wrapper in `cda_transmission`: the interaction, its `interactionId`, the
payload path, and whether the document id the wrapper names matches the document's own `id`
(**payloadIdMatches**). Try the `apiome-ui/examples/hl7v3/07-transmission-set/` folder. If you
upload a wrapper on its own, the import is refused, because the document it carries is missing.

## What Apiome does not check

- **The CDA schema and implementation guides** are not checked. Beyond the header rules below,
  Apiome makes no conformance claim.
- **Codes are recorded as written** and never looked up in LOINC, SNOMED CT or any other
  terminology.
- **Narrative markup** inside a section's `text` is kept as text, not modelled element by element.
- **Name and address part qualifiers** (`qualifier="IN"` on a given name, for example) are not
  carried into the model.

## When an import is refused

| What is wrong | Error code |
| --- | --- |
| The XML ends before the document does | `INPUT_TRUNCATED` |
| The XML is not well formed (an unclosed `<section>`, for example) | `INPUT_MALFORMED` |
| The header has no `id`, `code`, `effectiveTime`, `recordTarget`, `author`, `custodian` or body `component`; or the root is an HL7 v3 element that is not a `ClinicalDocument` | `INPUT_SEMANTIC_INVALID` |
| A narrative `reference` (`#vs-9`) points at an `ID` no element carries; or a transmission wrapper was uploaded without the document it references | `INPUT_REFERENCE_UNRESOLVED` |
| The file was sent as `hl7v3` but is not XML in the `urn:hl7-org:v3` namespace (a FHIR JSON resource, for example) | `FORMAT_MISMATCH` |
| The file is not UTF-8 text (UTF-16, for example) | `INPUT_ENCODING_INVALID` |
| The document declares a DTD or entities | `INPUT_UNSAFE_CONSTRUCT` |
