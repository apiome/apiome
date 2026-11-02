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

## Related

- [Import a SOAP / WSDL service](./wsdl-import.md)
- [Supported formats](./supported-formats.md)
