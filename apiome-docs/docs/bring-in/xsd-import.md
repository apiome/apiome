---
title: "Import an XML Schema (XSD)"
description: "Catalog an XSD schema, or a schema split across files, as data types."
sidebar_position: 44
tags: [import, xsd, xml-schema, c14n]
---

The **XSD** importer (`xsd`) reads a W3C XML Schema into the [Catalog](./catalog.mdx) as a
schemas-only item. Its named complex and simple types become types, and its global elements are
listed with the type each one uses. You can then search, version, diff and convert it like any other
catalog item. A schema inside a SOAP description is read by the
[WSDL importer](./wsdl-import.md) instead.

## Import it

| What you have | How to bring it in |
| --- | --- |
| One `.xsd` file | Upload, paste or link it in the [import wizard](./import-wizard.mdx) (**Import to catalog** → **XSD**), or `apiome import xsd ./invoice.xsd`. |
| A schema that imports or includes other files | Upload them together as a `.zip`, `.tar.gz` or `.tar`, or `apiome import xsd ./schemas/`. |

## A schema split across files

When you upload the files together, the schema's `xs:import`, `xs:include`, `xs:redefine` and
`xs:override` are followed, at any depth, and the types of every schema they reach are read with the
root's:

- Each `schemaLocation` is found relative to the file that declares it, then by its file name when
  only one file in the upload has that name. The rules are the same as for a
  [WSDL split across files](./wsdl-import.md#a-description-split-across-files).
- A name declared in two files is read once: the root's declaration wins, then the first one found.
- A location nothing in the upload answers is skipped and listed under `xml_import_graph`.

A single `.xsd` uploaded on its own is read alone, as before: the files it imports are not part of
the upload, so their types are not in the item.

## What the catalog item keeps about its files

The XSD importer records the same keys as the WSDL importer:

- `xml_import_graph`, the files read and the locations nothing answered.
- `xml_c14n_sha256`, a hash over every file in Canonical XML. It ignores whitespace, comments,
  attribute order and namespace prefixes, and changes on any other edit to any file.
- `xsd_version`, which is `1.1` for an XSD 1.1 schema.

See [What the catalog item keeps about its files](./wsdl-import.md#what-the-catalog-item-keeps-about-its-files)
for each key and what XSD 1.1 support covers.

## UBL and Peppol document schemas

OASIS **UBL** publishes one schema per business document: `UBL-Invoice-2.1.xsd`,
`UBL-CreditNote-2.1.xsd`, `UBL-Order-2.1.xsd` and so on. Each one imports the shared Common Aggregate
(`cac:`) and Common Basic (`cbc:`) Components. **Peppol BIS Billing 3.0**, the e-invoicing profile EU
mandates build on, has no schema of its own. A Peppol invoice *is* a UBL 2.1 Invoice, and a Peppol
credit note a UBL 2.1 CreditNote, restricted by Peppol's Schematron rules.

To bring one in, upload the document schema **together with** the component schemas it imports, as a
`.zip` or a folder (see [A schema split across files](#a-schema-split-across-files)). A document schema
uploaded on its own reads almost empty, because every member of a UBL type is a reference to a
component in another file. Try `apiome-ui/examples/xsd/07-ubl-2.1-invoice-set/` or
`08-ubl-2.1-creditnote-set/`:

```bash
apiome import xsd ./07-ubl-2.1-invoice-set/
```

Apiome recognises the schema by its target namespace
(`urn:oasis:names:specification:ubl:schema:xsd:Invoice-2`) and imports it as an XSD item:

- **Title:** the document and release, such as **Invoice (UBL 2.1)**.
- **References:** every `<xs:element ref="cbc:IssueDate"/>` member is read as the global element it
  names, with that element's type, so the Invoice type lists `IssueDate`, `AccountingSupplierParty`,
  `InvoiceLine` and the rest.
- **`ubl_document`:** the document type, the namespace, the major version, the release (the schema's
  `version` attribute) and whether it is a document or a component library.
- **Provenance:** the `ubl` profile (`formatProfile` on the revision) with the evidence it was
  recognised on. For a UBL 2.1 Invoice or CreditNote it also notes **Peppol BIS Billing 3.0**.

The item versions, diffs, lints and exports like any other XML Schema. Peppol's business rules are a
Schematron file: import that separately as a [Schematron item](./schematron-import.md).

## Related

- [Import a SOAP / WSDL service](./wsdl-import.md)
- [Import an EDI X12 interchange](./x12-import.md)
- [Supported formats](./supported-formats.md)
