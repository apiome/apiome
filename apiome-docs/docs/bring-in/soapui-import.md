---
title: "Import a SoapUI or ReadyAPI project"
description: "Catalog a SoapUI or ReadyAPI project, its WSDLs and test suites, as one API."
sidebar_position: 31
tags: [import, soapui, readyapi, soap, wsdl, testing]
---

**SoapUI** and SmartBear **ReadyAPI** keep a SOAP estate's interfaces, saved requests and test
suites in one project file. The **SoapUI / ReadyAPI project** importer (`soapui`) reads that
project into the [Catalog](./catalog.mdx) as one API. You can then search, version, diff and
convert it like any other catalog item.

A project can hold two kinds of interface, and Apiome reads each with the importer that already
owns it:

- **A WSDL interface** is read by the [WSDL](./supported-formats.md) importer. Its operations and
  XSD types are exactly what importing the WSDL on its own gives you.
- **A REST interface** is inferred from its saved requests and mock responses, by the same engine
  as the Postman, [Hoppscotch](./hoppscotch-import.md) and [Thunder Client](./thunder-client-import.md)
  imports. What it builds is labelled **inferred** (see
  [Declared, inferred and synthesized](./inference-provenance.mdx)).

The project's **test suites** are kept too, as **declared tests**: what each test case calls and
what it asserts.

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| A project file (`<name>-soapui-project.xml`) | One catalog item, named after the project |
| A project file plus the WSDL and XSD files its interfaces name, in one archive (`.zip`, `.tar.gz`) | One catalog item, with each WSDL's types |

Apiome recognises a project by its `<con:soapui-project>` root in the
`http://eviware.com/soapui/config` namespace. SoapUI 5.x and ReadyAPI 3.x save the same file.
ReadyAPI **composite projects**, which save one file per item in a folder, are not read; save the
project as a single file first (**Project** › **Save as**, with **Composite project** cleared).

## Import it

Import the file or the archive like any other specification: in the
[import wizard](./import-wizard.mdx), with `apiome import`, or through the REST API (see
[Import a specification](./import-a-spec.md)). Apiome picks **SoapUI / ReadyAPI project**
(`soapui`).

**Where Apiome finds each WSDL.** A WSDL interface names its WSDL in its `definition`. Apiome looks
for it in this order:

1. **The project's own copy.** SoapUI caches every WSDL and XSD it loaded in the project's
   `definitionCache`. When the copy is there, nothing else is needed.
2. **A file uploaded beside the project.** Put the project and its WSDL in one archive. Apiome
   matches the `definition` path, or just its file name (`C:\soap\catalogue.wsdl` finds
   `catalogue.wsdl`).
3. **A WSDL the project only links to** (`https://billing.example.com/BillingService?wsdl`, no
   cached copy) is **never fetched**. The interface's operations are still imported, by name and
   SOAP action, but without message schemas. Upload the WSDL with the project to get them.

A WSDL interface whose `definition` is a **local file** that is neither cached nor uploaded is
refused (`INPUT_REFERENCE_UNRESOLVED`): upload the WSDL beside the project.

## What each part becomes

| SoapUI | In the catalog item |
| --- | --- |
| A WSDL interface | The WSDL's **services**, **operations** and **types**, exactly as the WSDL importer reads them. Two interfaces over one WSDL (a SOAP 1.1 and a 1.2 binding) import it once |
| A WSDL interface whose WSDL is not uploaded | A **service** named after the interface, with one operation per binding operation: its name, SOAP action and whether it is **one-way**. No message schemas |
| A saved SOAP request (`call`) | Listed by name, with its auth type, under its operation. The envelope is not modelled; the message schema comes from the WSDL |
| A REST interface | Its methods become **operations**, keyed by method and path (`GET /v2/orders/{orderId}`), tagged with the interface name. The interface's `basePath` and each resource's path (child resources included) make up the path |
| `QUERY`, `TEMPLATE` and `HEADER` parameters | **Query**, **path** and **header parameters**. A saved request's own value wins over the parameter's default |
| A saved REST request body | A request **schema** inferred from a JSON body, with its media type |
| A `RESPONSE` representation's status | A **response** with that status |
| A REST mock service's canned responses | **Response schemas** of the operation each one answers |
| An interface's endpoints, and each environment's endpoints | **Servers**. An environment's server says which environment it is (`Production environment (Orders)`) |
| An endpoint written `${#Project#apiBaseUrl}` | A **server** `{apiBaseUrl}` with a server variable. Its default is the project property's value, unless the property's name says it holds a credential |
| Test suites, test cases and test steps | **Declared tests** — see below |
| Groovy scripts, matrix parameters, mock dispatch rules, SOAP mock services | Not imported; listed in the coverage ledger |

## Declared tests

Test suites are why SOAP estates keep these projects, so Apiome does not discard them. Each test
case is recorded with:

- its **suite**, its **run type** (sequential or parallel) and the names of its **properties**;
- each **step**: its name and type (`request`, `restrequest`, `transfer`, `delay`, `groovy`,
  `datasource` …) and, for a request step, the **operation it calls**;
- each **assertion**: its type and name (`Valid HTTP Status Codes`, `XPath Match`, `SOAP Response`
  …) and what it expects — the status codes, the JSON path or XPath and the expected value, the
  response time limit.

Open the catalog item: the **Overview** tab shows a **Declared tests** group after the API surface.
Each test case is one entry, tagged **TEST**, with its suite and its step and assertion counts.
Each step says which operation it calls and what it asserts. A step that calls an operation the
project does not define says so: *(not in this model)*.

The tests are **not run**. Groovy scripts, in script steps and script assertions, are never read;
the step is kept by name. In the item's canonical model the record is the `declared_tests`
extra, so contract-testing tools can read which operations your SoapUI suites already exercise.

## Credentials are never kept

A saved request can hold a password, a WS-Security password in its envelope, or an API key in a
parameter. Apiome does not keep any of them:

- **Auth is read as a type only.** The `username`, `password` and `domain` of a request's
  credentials are never read; only the auth type (`Basic`, `NTLM`, `OAuth 2.0` …) and the
  WS-Security password type (`PasswordText`, `PasswordDigest`) are.
- **Every other value is scrubbed** before it reaches the catalog item: endpoints, parameter and
  header values, bodies and property values. A parameter or header whose name says it holds a
  secret (`Authorization`, `X-Api-Key`, `api_key` …) is redacted whatever its value looks like.
- **Credential properties are listed by name only**, and never become a server variable default.
- **The stored copy of your upload is scrubbed too.** The secret scrubber also finds the shapes a
  SoapUI project keeps credentials in: a `<con:password>` element, a `<wsse:Password>` inside a
  saved envelope, a `<con:entry key="X-Api-Key" value="…"/>` and a property's
  `<con:name>`/`<con:value>` pair. Those values are replaced with `«redacted»` in the stored copy.

The coverage ledger lists every saved request whose credentials were withheld, and every
credential property.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | The file is not well-formed XML, a REST method has no HTTP verb, or a cached WSDL cannot be read. |
| `INPUT_TRUNCATED` | The XML ends while an element or attribute is still open. The file looks cut short. |
| `INPUT_SEMANTIC_INVALID` | The project has no interfaces or mock services, or its interfaces declare no operations. |
| `INPUT_REFERENCE_UNRESOLVED` | A WSDL interface names a local WSDL file that is neither cached in the project nor uploaded with it. |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |
| `FORMAT_MISMATCH` | The file is not a SoapUI project, such as a bare WSDL or a WADL. Import it as that format instead. |

## Related

- [Supported formats](./supported-formats.md): what this importer reads.
- [Import a Thunder Client collection](./thunder-client-import.md): the same inferred import for
  another API client.
- [Declared, inferred and synthesized](./inference-provenance.mdx): why a REST interface's
  operations are labelled inferred.
- [Import a specification](./import-a-spec.md): the import job and its options.
