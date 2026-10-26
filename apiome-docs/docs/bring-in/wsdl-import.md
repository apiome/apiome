---
title: "Import a SOAP / WSDL service"
description: "Catalog a WSDL file, a WSDL split across files, or a live SOAP service."
sidebar_position: 44
tags: [import, wsdl, soap, xsd, singlewsdl]
---

The **WSDL** importer (`wsdl`) reads a SOAP service description, WSDL 1.1 or 2.0, into the
[Catalog](./catalog.mdx). Its XSD types become types, and each port-type operation becomes an
operation. You can then search, version, diff and convert it like any other catalog item.

## Import it

| What you have | How to bring it in |
| --- | --- |
| One `.wsdl` file | Upload, paste or link it in the [import wizard](./import-wizard.mdx) (**Import to catalog** → **WSDL**), or `apiome import wsdl ./service.wsdl`. |
| A WSDL that imports other files | Upload them together as a `.zip`, `.tar.gz` or `.tar`, or `apiome import wsdl ./service-folder/`. |
| A running SOAP service | `apiome import wsdl --discover https://host/Service.svc` |

## A description split across files

A WSDL often pulls in other documents:

- `<xs:import schemaLocation="types.xsd">` and `<xs:include schemaLocation="…">` inside `<wsdl:types>`
  bring in XML Schema files;
- `<wsdl:import location="contract.wsdl">` (WSDL 1.1) brings in another WSDL with its own messages,
  port types, bindings and services. WCF services publish their contract this way.

When you upload the files together, every one of them is read, at any depth, and the API is cataloged
as one: types from the schemas, and messages and operations from the imported WSDL files. A location
nothing in the upload answers is skipped, and the types it would have supplied stay unresolved.

## Discover a live service

Give `--discover` the service endpoint (or its `?wsdl` URL):

```bash
apiome import wsdl --discover https://soap.example.com/Calculator.svc
```

The CLI asks the service for its description:

1. **`?singleWsdl`** first. WCF services answer it with the whole description in one document, every
   import already inlined.
2. **`?wsdl`** when `?singleWsdl` is not offered.

It reports the URL that answered (`Discovered WSDL at …`) and imports that document like a `--url`
import. A `?singleWsdl` or `.wsdl` URL is used as given. `--discover` must be the only input.

A `?wsdl` description that imports other documents by URL arrives without them. For such services,
use `?singleWsdl` when the service offers it, or save the files and upload them together.

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): WSDL's version coverage and export support
- [Import a SoapUI or ReadyAPI project](./soapui-import.md): a SOAP project with its WSDLs and test suites
