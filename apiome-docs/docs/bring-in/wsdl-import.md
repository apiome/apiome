---
title: "Import a SOAP / WSDL service"
description: "Catalog a WSDL file, a WSDL split across files, or a live SOAP service."
sidebar_position: 44
tags: [import, wsdl, soap, xsd, singlewsdl, breaking-changes]
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

## What the catalog item records

| WSDL | Catalog item |
| --- | --- |
| Each `portType` (1.1) or `interface` (2.0) | A service, with one operation per WSDL operation |
| An operation's input and output | Its request and response messages |
| An operation's `wsdl:fault` (1.1) or `outfault` (2.0) | An **error** message named after the fault, with the fault's payload |
| A message with several parts (typical of `rpc` style) | A type named after the message, with one field per part |
| XSD complex types | Types, with each element's `minOccurs`, `maxOccurs`, `nillable`, `default` and restrictions |
| Each `port` (1.1) or `endpoint` (2.0) with an address | A server named after the port, with its binding's protocol (`soap11`, `soap12` or `http`) |
| The SOAP binding of an operation | Its `soapAction`, and `rpc` when the binding uses that style |

Each server also records its WSDL service, binding, port type and SOAP transport, so a description
with SOAP 1.1 and SOAP 1.2 ports keeps both. When you export the item to WSDL (see
[Export a specification](../ship/export-a-spec.md)), its bindings, services, ports, faults and
multi-part messages are written out again.

## A description split across files

A WSDL often pulls in other documents:

- `<xs:import schemaLocation="types.xsd">` and `<xs:include schemaLocation="…">` inside `<wsdl:types>`
  bring in XML Schema files;
- `<wsdl:import location="contract.wsdl">` (WSDL 1.1) brings in another WSDL with its own messages,
  port types, bindings and services. WCF services publish their contract this way.

When you upload the files together, every one of them is read, at any depth, and the API is cataloged
as one: types from the schemas, and messages and operations from the imported WSDL files. A location
nothing in the upload answers is skipped, and the types it would have supplied stay unresolved. Lint
reports it as [`wsi.unresolved-import`](#ws-i-basic-profile-checks).

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

## WS-I Basic Profile checks

Every imported description is checked against the
[WS-I Basic Profile](https://www.ws-i.org/Profiles/BasicProfile-1.2-2010-11-09.html), the rules SOAP
toolkits follow to interoperate. The checks read the bindings and imports exactly as written,
including those in the files the description imports. Problems never stop the import; each is
listed on the catalog item (`wsdl_wsi_issues`, up to 50, with `wsdl_wsi_issue_count`) and reported
by lint at a path such as `wsdl:/binding/OrdersSoap/operation/GetOrder/input`.

| Rule | Severity | What it catches |
| --- | --- | --- |
| [`wsi.literal-use`](../build/lint-rules.md#wsi-literal-use) | error | A `soap:body`, `soap:header`, `soap:headerfault` or `soap:fault` with `use="encoded"`. Only `literal` is interoperable. |
| [`wsi.binding-style`](../build/lint-rules.md#wsi-binding-style) | error | One binding that mixes `rpc` and `document` operations. |
| [`wsi.document-literal`](../build/lint-rules.md#wsi-document-literal) | error | A document-literal body that references more than one part, a part defined with `type` rather than `element`, or that carries a `namespace` attribute. |
| [`wsi.rpc-literal`](../build/lint-rules.md#wsi-rpc-literal) | error | An rpc-literal body that references a part defined with `element`, or has no `namespace`. |
| [`wsi.unique-operation-signature`](../build/lint-rules.md#wsi-unique-operation-signature) | error | Two operations of a binding that send the same body element with the same `soapAction`, so a receiver cannot tell them apart. |
| [`wsi.unresolved-import`](../build/lint-rules.md#wsi-unresolved-import) | error | A `wsdl:import`, `xs:import` or `xs:include` that resolves to nothing in the import, or an `xs:import` without `schemaLocation` whose namespace no schema declares. |
| [`wsi.wsdl-import-target`](../build/lint-rules.md#wsi-wsdl-import-target) | error | A `wsdl:import` with no `location`, or one that names a schema instead of a WSDL description. Import schemas with `xs:import` inside `wsdl:types`. |
| [`wsi.unique-soap-action`](../build/lint-rules.md#wsi-unique-soap-action) | warning | Two operations of a binding that share a `soapAction`, which a service that routes on it cannot tell apart. |

The binding rules apply to SOAP 1.1 and SOAP 1.2 bindings in WSDL 1.1; for WSDL 2.0, only the
import rules apply.

A single `.wsdl` uploaded without the schemas it imports reports each of them as
`wsi.unresolved-import`. Upload the files together, use `?singleWsdl`, or discover the live service,
and import it again.

## Breaking changes between versions

When you compare two versions of a WSDL catalog item, each change is graded by SOAP and XML
Schema compatibility. The import records what these rules need: each operation's message exchange
pattern and its SOAP binding's `soapAction` and style, and each element's `minOccurs`, `maxOccurs`,
`nillable`, `default` and simple-type restrictions (`enumeration`, `pattern`, `length`,
`minLength` / `maxLength`, `minInclusive` / `maxInclusive`, `minExclusive` / `maxExclusive`,
`totalDigits`, `fractionDigits`).

SOAP services validate messages strictly: a receiver that does not know an element rejects the
message. So in XML Schema, **adding is not automatically safe**: a new optional element is
dangerous, and a looser restriction is dangerous too.

| Change | Severity | Rule |
| --- | --- | --- |
| An operation's message exchange pattern changed | Breaking | `wsdl.mep-changed` |
| An operation's `soapAction` changed | Breaking | `wsdl.soap-action-changed` |
| An operation moved between `rpc` and `document` style | Breaking | `wsdl.soap-style-changed` |
| A required element added (`minOccurs` 1 or more) | Breaking | `wsdl.element-added-required` |
| An optional element added (`minOccurs="0"`) | Dangerous | `wsdl.element-added-optional` |
| An element's type changed | Breaking | `wsdl.element-type-changed` |
| `minOccurs` raised / lowered | Breaking / Dangerous | `wsdl.min-occurs-raised` / `wsdl.min-occurs-lowered` |
| `maxOccurs` lowered / raised | Breaking / Dangerous | `wsdl.max-occurs-lowered` / `wsdl.max-occurs-raised` |
| `nillable` turned off / on | Breaking / Dangerous | `wsdl.made-non-nillable` / `wsdl.made-nillable` |
| An element's `default` changed | Dangerous | `wsdl.default-changed` |
| A restriction tightened: an enumeration value removed, a facet added, a bound tightened, a `pattern` or base type changed | Breaking | `wsdl.facet-narrowed` |
| A restriction loosened: an enumeration value added, a facet removed, a bound loosened | Dangerous | `wsdl.facet-widened` |
| Only the spelling changed (`maxOccurs="1"` written out) | Safe | `wsdl.element-unchanged-on-the-wire` |

New operations and types are safe, and anything removed is breaking. Standalone `.xsd` catalog
items are graded by the standard rules.

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): WSDL's version coverage and export support
- [Import a SoapUI or ReadyAPI project](./soapui-import.md): a SOAP project with its WSDLs and test suites
