---
title: "Import WADL descriptions"
description: "Catalog legacy WADL REST services, lint and diff them, then migrate to OpenAPI."
sidebar_position: 44.5
tags: [import, wadl, rest, xml, xsd, legacy, lint, migrate, openapi]
---

**WADL** (Web Application Description Language, a 2009 W3C member submission) is the XML REST
description that came before OpenAPI. It is still served by Jersey and other JAX-RS back-ends
(`/application.wadl`) and is still common in government and enterprise services. A WADL document
lists `resources` with nested `resource` paths, the HTTP `method`s on each, their `param`s and the
`representation`s they send and return, with XML Schema `grammars` for the bodies. The **WADL**
importer (`wadl`) reads it into the [Catalog](./catalog.mdx), so the service can be searched,
versioned, diffed and linted like any other catalog item. It also gives you a direct path to
OpenAPI.

## What you can import

A WADL document in the `http://wadl.dev.java.net/2009/02` namespace (the older
`http://wadl.dev.java.net/ns/wadl` namespace is also accepted):

```xml
<application xmlns="http://wadl.dev.java.net/2009/02"
             xmlns:xsd="http://www.w3.org/2001/XMLSchema"
             xmlns:tns="http://example.com/library">
  <grammars>
    <xsd:schema targetNamespace="http://example.com/library">
      <xsd:element name="loan" type="tns:Loan"/>
      <xsd:complexType name="Loan">
        <xsd:sequence>
          <xsd:element name="id" type="xsd:string"/>
          <xsd:element name="note" type="xsd:string" minOccurs="0"/>
        </xsd:sequence>
      </xsd:complexType>
    </xsd:schema>
  </grammars>
  <resource_type id="item">
    <param name="loanId" style="template" type="xsd:string"/>
    <method name="GET" id="getLoan">
      <response status="200 404">
        <representation mediaType="application/xml" element="tns:loan"/>
      </response>
    </method>
  </resource_type>
  <resources base="https://library.example.com/api/">
    <resource path="loans">
      <resource path="{loanId}" type="#item"/>
    </resource>
  </resources>
</application>
```

WADL's reuse is resolved as if it had been written inline: a `method href="#id"`, a
`param href="#id"`, a `representation href="#id"`, and a resource's `type="#a #b"` (the
`resource_type`s whose params, methods and child resources it takes on). Only references to
elements in the same document (`#id`) are followed. An external WADL is never fetched, and a
reference that names nothing is reported by the `wadl.reference-resolved` rule rather than
guessed at.

Grammars can be written inline or pulled in with `<grammars><include href="…"/>`. To bring an
included schema along, upload the WADL and its `.xsd` together as a `.zip` or a file set.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the `.wadl` file (try
   `apiome-ui/examples/wadl/06-task-tracker.wadl`). You can also choose **URL** and enter the
   service's `application.wadl` address, or choose **Paste** and paste the document.
3. On **Detect & route**, Apiome reports **Auto-detected: WADL** (`wadl`) and routes it to the
   Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the document to the import endpoints with the source kind `wadl`; see
[Import sources](../reference/rest/import-sources.md). From the CLI:

```bash
apiome import wadl ./06-task-tracker.wadl
```

The six examples in `apiome-ui/examples/wadl/` cover a bookstore, a minimal status ping, a
nested catalog, every param style in one file, a news-search service and a task tracker.

## What Apiome reads

| In the document | Becomes |
| --- | --- |
| Each `method` of each `resource` (nested paths joined) | An **operation** keyed `VERB /path`, named by the method's `id` |
| A `param` with style `template`, `query` or `header` | A **path**, **query** or **header parameter**; `required`, `default`, `repeating` (a list) and its `option` values (an `enum`) are kept |
| A `param` with style `matrix` or `plain` | A path or query parameter, its WADL style kept in `wadl_style` so an export writes it back the same way |
| A `request`'s representations | The **request message**: the grammar element it names and every `mediaType` |
| Each code of a `response`'s `status` list | A **response message** with that status, its grammar element and its media types |
| Each grammar `complexType` | A **record type**: each sequence element is a field, optional when `minOccurs="0"` or `nillable`, and a list when `maxOccurs` is above 1 or `unbounded` (the bounds become `min_items` / `max_items`) |
| A named `simpleType` with `enumeration`s | An **enum type** |
| A named `simpleType` without enumerations | Its base type (the simple type's name is kept in `wadl_type`) |
| `resources/@base` | The item's **server** |

## Versions and changes

Import a newer WADL into the same item to add a version. A WADL service validates its XML against
the grammars, so the comparison grades changes the way XML Schema does: a sequence is
**ordered**, a missing required element fails validation, and an occurrence bound is enforced.

| Change | Severity | Rule |
| --- | --- | --- |
| A method gains a required param, or a param became required | Breaking | `wadl.parameter-added-required`, `wadl.parameter-made-required` |
| A param's type changed | Breaking | `wadl.parameter-type-changed` |
| A method gains an optional param, or a param became optional | Safe | `wadl.parameter-added-optional`, `wadl.parameter-made-optional` |
| A param is removed | Dangerous: callers that still send it may be rejected | `wadl.parameter-removed` |
| An `option` value removed / added | Breaking / Safe | `wadl.parameter-option-removed`, `wadl.parameter-option-added` |
| A representation's `mediaType` removed / added | Breaking / Safe | `wadl.media-type-removed`, `wadl.media-type-added` |
| A representation names a different element | Breaking | `wadl.representation-type-changed` |
| A sequence gains a required / optional element | Breaking / Safe | `wadl.element-added-required`, `wadl.element-added-optional` |
| An element's type changed, or it became repeated | Breaking | `wadl.element-type-changed` |
| An element became required | Breaking | `wadl.element-made-required` |
| An element became optional | Dangerous: readers may now find it missing | `wadl.element-made-optional` |
| Elements swapped places | Breaking: a sequence is validated in order | `wadl.element-reordered` |
| An element moved only because a sibling was added or removed | Safe: the sibling's change is graded on its own | `wadl.element-shifted` |
| `minOccurs` rose or `maxOccurs` fell | Breaking | `wadl.occurs-narrowed` |
| `minOccurs` fell or `maxOccurs` rose | Dangerous | `wadl.occurs-widened` |
| An enumeration value removed / added | Breaking / Dangerous | `wadl.enum-value-removed`, `wadl.enum-value-added` |

A removed method, response, type or element is breaking, and any other addition is safe.

## Lint

The **Quality** step and the item's **Lint & score** tab add the `wadl` rules on top of the
common ones. Several of them flag what will not carry over cleanly to OpenAPI:

| Rule | Severity | Flags |
| --- | --- | --- |
| [`wadl.reference-resolved`](../build/lint-rules.md#wadl-reference-resolved) | Error | An `href` or resource `type` that names no element of the document, or names an external WADL |
| [`wadl.template-param-declared`](../build/lint-rules.md#wadl-template-param-declared) | Error | A `{name}` in a path with no `template` param to give it a type |
| [`wadl.template-param-used`](../build/lint-rules.md#wadl-template-param-used) | Warning | A `template` param that no `{name}` in the path uses |
| [`wadl.method-id-unique`](../build/lint-rules.md#wadl-method-id-unique) | Error | Two methods with the same `id` |
| [`wadl.method-id-present`](../build/lint-rules.md#wadl-method-id-present) | Info | A method without an `id`: the OpenAPI migration has to invent an `operationId` |
| [`wadl.method-name-standard`](../build/lint-rules.md#wadl-method-name-standard) | Warning | A method name that is not a standard HTTP method; OpenAPI 3.1 has no slot for it |
| [`wadl.body-on-safe-method`](../build/lint-rules.md#wadl-body-on-safe-method) | Warning | A GET, HEAD or DELETE whose request carries a representation |
| [`wadl.response-declared`](../build/lint-rules.md#wadl-response-declared) | Warning | A method with no `response` |
| [`wadl.response-status-valid`](../build/lint-rules.md#wadl-response-status-valid) | Warning | A `status` that is not a three-digit HTTP code |
| [`wadl.type-resolved`](../build/lint-rules.md#wadl-type-resolved) | Warning | A type that is neither an XSD built-in nor declared by the grammars, such as an `include` that was not uploaded |
| [`wadl.representation-typed`](../build/lint-rules.md#wadl-representation-typed) | Info | An XML or JSON representation with no `element`; it converts as an untyped body |
| [`wadl.representation-media-type`](../build/lint-rules.md#wadl-representation-media-type) | Info | A typed representation with no `mediaType` |
| [`wadl.base-uri-present`](../build/lint-rules.md#wadl-base-uri-present) | Info | No `resources/@base`, so the OpenAPI document has no server |

## Migrate to OpenAPI

Converting a WADL catalog item **is** the migration. **Go to Bring in → Catalog**, open the
item and **click "Convert to OpenAPI Project"** (see
[Convert a catalog item to OpenAPI](./convert-to-openapi.md)). The `wadl` conversion pack
carries over:

- each resource path and method as an OpenAPI path and operation, and each method `id` as its
  `operationId`. An id that two methods share is replaced by a generated one, so the document
  stays valid;
- each `template`, `query` and `header` param as a parameter, with its `option` values as an
  `enum`;
- each representation as request or response content under its media type, referencing the
  grammar type, and each status code as its own response;
- each grammar type as a schema under `components.schemas`, renamed to a name OpenAPI allows
  (`http://example.com/library.Loan` becomes `library.Loan`);
- `resources/@base` as the server.

What does not carry over: a representation without a grammar element converts as an untyped
body, and a method whose name is not a standard HTTP verb has no OpenAPI 3.1 slot. Fix the
`wadl.representation-typed` and `wadl.method-name-standard` findings before converting.

## Export

A WADL item writes back out as WADL (with its grammar as a separate `.xsd`, or in one file)
through the **WADL** target; see [Export a spec](../ship/export-a-spec.md). Param styles,
`option` values, every media type and the elements' occurrence survive the round trip.

## When an import is refused

| Message | Why | What to do |
| --- | --- | --- |
| `Malformed XML: …` | The document is not well-formed XML (a mismatched or unclosed tag) | Fix the XML at the line and column given |
| `No WADL types or resources found` | The `application` declares no grammar type and no resource method | Add the resources |
| `Content does not appear to be a WADL document` | There is no `application` root in a WADL namespace (a WSDL, or a UTF-16 file) | Pick the right format, or save the file as UTF-8 |
| `INPUT_UNSAFE_CONSTRUCT` | The document declares a DTD or entities | Remove the `<!DOCTYPE>`; WADL never needs one |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): WADL's coverage and export support
- [Import WSDL descriptions](./wsdl-import.md): the SOAP counterpart
- [Import RAML](./raml-import.md): another pre-OpenAPI REST description
- [Built-in lint rules](../build/lint-rules.md): every rule with its rationale
