---
title: "Import DICOM metadata"
description: "Catalog DICOM SOP classes, attributes and Structured Report trees — never pixel data."
sidebar_position: 21
tags: [import, dicom, healthcare, imaging]
---

**DICOM** is the imaging half of healthcare, beside **FHIR** and **HL7**. Its information model —
SOP classes, modules, and attributes with tags and value representations (VRs) — is a real schema.
Apiome imports that schema into the [Catalog](./catalog.mdx). It reads the **metadata layer only**:
the file meta information, the attribute structure and Structured Report content trees.

:::info Pixel data is never read
Apiome is a schema importer, not an image tool. It steps over every **Pixel Data**, **Float Pixel
Data**, **Double Float Pixel Data** and **Overlay Data** value by its declared length without
reading it. Pixel data is never stored and never analysed. Each pixel-data element is still recorded
as present and skipped, with its VR and length, so you can see that the file had one.
:::

## What you can import

| You have | What Apiome reads |
| --- | --- |
| A DICOM **Part 10** file (`.dcm`, `.dicom`) — the 128-byte preamble, `DICM`, then the file meta group | The file meta information and the dataset's attributes |
| **DICOM JSON** (PS3.18 Annex F), as a DICOMweb server returns it from QIDO-RS or WADO-RS metadata — one dataset or an array | Every dataset in the document |
| An archive (`.zip`, `.tar.gz`) of DICOM JSON documents — for example a study-level query result and one instance from each series | Every DICOM JSON member, root first |

Part 10 files can use any transfer syntax: implicit or explicit VR little endian, explicit VR big
endian, deflated explicit VR little endian, and every compressed (encapsulated) syntax — JPEG,
JPEG 2000, RLE and the rest. Only the pixel data inside a compressed syntax is compressed, and that
is never read.

A **FHIR** `ImagingStudy` resource describes a study in FHIR's own JSON; it is not DICOM JSON, and
sent as `dicom` it is refused (`FORMAT_MISMATCH`).

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the file — try
   `apiome-ui/examples/dicom/04-stress-part10-sequences-and-pixeldata.dcm` — or choose **Paste** and
   paste DICOM JSON, such as `apiome-ui/examples/dicom/03-composition-structured-report-json.json`.
3. On **Detect & route**, Apiome reports **Auto-detected: DICOM** (`dicom`) and routes it to the
   Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

To import a study set, upload the DICOM JSON documents together as an archive, with the
study-level query result as the root. Try the `apiome-ui/examples/dicom/07-study-set/` folder.

Over the API, send the file to the import endpoints with the source kind `dicom` (aliases `dcm`,
`dicom-json`); see [Import sources](../reference/rest/import-sources.md).

## What Apiome reads

| In the file | Becomes |
| --- | --- |
| A SOP class — the `SOP Class UID` (0008,0016) each instance names, such as **CT Image Storage** | A **record type** (`CTImageStorage`). Every instance of the class in the upload is folded into it |
| A query/retrieve result, which names no SOP class | A record type named by its level (`StudyQueryResult`) |
| An attribute | A **field** keyed by its tag (`DICOM.CTImageStorage.00100010`), named by its keyword (`PatientName`) and typed by its **VR** |
| An attribute whose VM allows several values (`ImageType`, 2-n), or that carries several | A list of its VR |
| A sequence (`SQ`) | A list of a nested record type, one per sequence tag (`ReferencedImageSequenceItem`), folded across every item. Sequences nest to any depth |
| The Part 10 file meta group (0002,xxxx) | The `FileMetaInformation` record type |
| An attribute missing from some instance or item | A nullable field |

Each field also records the tag, keyword, VR and dictionary VM as written (`dicom_tag`,
`dicom_keyword`, `dicom_vr`, `dicom_vm`), and marks retired, private and patient-identifying
attributes.

### Value representations are types

| VR | Canonical type |
| --- | --- |
| `AE`, `AS`, `CS`, `DA`, `DT`, `LO`, `LT`, `SH`, `ST`, `TM`, `UC`, `UI`, `UR`, `UT`, `AT` | A named alias of text, with the VR's maximum length (`CS` 16, `UI` 64…) |
| `DS`, `FL`, `FD` | A named alias of number |
| `IS`, `SS`, `US`, `SL`, `UL`, `SV`, `UV` | A named alias of integer |
| `OB`, `OW`, `OD`, `OF`, `OL`, `OV`, `UN` | A named alias of text; the bytes are never decoded |
| `PN` | A record: `Alphabetic`, `Ideographic`, `Phonetic` (PS3.18 F.2.2) |
| `SQ` | A nested record type (see above) |

### Structured Report content trees

A Structured Report (Basic Text SR, Enhanced SR, Comprehensive SR…) keeps its findings in a
**content tree**: nested `ContentSequence` items, each with a value type, a relationship to its
parent and a coded concept name. Apiome imports the tree two ways:

- **As a schema.** `ContentSequence` folds into one recursive `ContentSequenceItem` type — the SR
  content item macro — with `ValueType`, `RelationshipType`, `ConceptNameCodeSequence`,
  `TextValue`, `MeasuredValueSequence` and the other members the report uses.
- **As a hierarchy.** The report's own tree is recorded beside the model in
  `dicom_sr_content_trees`: each content item's **valueType** (`CONTAINER`, `TEXT`, `CODE`,
  `NUM`…), **relationshipType** (`CONTAINS`, `HAS CONCEPT MOD`…) and **conceptName** (code,
  scheme, meaning), with its children. The item's *value* — the finding text, the measurement — is
  payload and is not in the tree.

## Patient data stays out

A DICOM file is patient data. Apiome keeps it out of what it stores:

- **No attribute value is in the schema.** Names, identifiers, dates, UIDs and report text never
  enter the canonical model. The model holds each attribute's tag, keyword, VR and multiplicity.
  Only values that describe structure are recorded beside it — the SOP class, transfer syntax,
  modality, character set, and an SR content item's value type and concept name.
- **The analysis follows the value-visibility policy.** The **Format details** tab lists every
  attribute (see [the DICOM analysis](./catalog-format-details.md#the-dicom-analysis)). At the
  default policy it keeps only whether each value was present and how long it was, so no
  patient-identifying value is stored.
- **Identifying attributes are marked.** Attributes that DICOM's de-identification profile (PS3.15
  Annex E) lists, and every private attribute, carry `dicom_patient_identifying` on their field.
- **The uploaded file is not kept.** Other formats store the original upload so it can be converted
  later. A DICOM import does not: the version records that its source was withheld
  (`sourceWithheld: dicom-patient-and-pixel-data`). The catalog item has no source to download or
  convert.

The capability panel (**"DICOM — what apiome records"** on the **Format details** tab) states the
pixel-data boundary and this value policy.

## What Apiome does not check

- **IOD module requirements** (Type 1, 2 and 3 attributes) and **SR templates** (TID 2000…) are not
  checked. The schema is what the instances contain.
- **Codes are recorded as written** and never looked up in DCM, LOINC, SNOMED CT or any other
  terminology.
- **Private attributes** are read by tag, VR and length. Their meaning is not in the DICOM data
  dictionary and is not modelled; each dataset that has them gets a warning.
- **ISO 2022 character sets** (code extensions in Specific Character Set) are not decoded. This
  affects only values in the analysis, never the schema.
- **Part 10 files inside an archive** are skipped and listed in `dicom_fileset`: archive members are
  read as text. Upload a Part 10 file on its own.

## When an import is refused

| What is wrong | Error code |
| --- | --- |
| The Part 10 file stops inside an element, a sequence or its magic | `INPUT_TRUNCATED` |
| An element states an unknown VR, a value overruns its sequence item, or the DICOM JSON is not valid (a broken attribute object, `Value` that is not an array) | `INPUT_MALFORMED` |
| The four bytes after the 128-byte preamble are not `DICM`; the file meta group has no Transfer Syntax UID; or a dataset has no SOP Class UID and is not a query result | `INPUT_SEMANTIC_INVALID` |
| The file was sent as `dicom` but is JSON that holds no DICOM attribute (a FHIR `ImagingStudy`, for example) | `FORMAT_MISMATCH` |
| The JSON is not UTF-8 text (UTF-16, for example) | `INPUT_ENCODING_INVALID` |
| Sequences nest more than 32 levels, a deflated dataset expands past 64 MiB, or the file has more than 200,000 elements | `INPUT_DEPTH_LIMIT`, `INPUT_EXPANSION_LIMIT`, `INPUT_TOO_LARGE` |

## Related

- [Import HL7 v3 / CDA documents](./hl7v3-cda-import.md)
- [Catalog format details](./catalog-format-details.md)
- [Supported formats](./supported-formats.md)
