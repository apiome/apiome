---
title: "Import an OPC UA NodeSet2 model"
description: "Catalog an OPC UA information model's types, methods and references."
sidebar_position: 24
tags: [import, opcua, nodeset2, industrial, iot]
---

An **OPC UA NodeSet2** file is the information model of an industrial automation server: the object
types, variable types, data types and methods its machines expose, joined by a graph of references.
Companion specifications (for robotics, machine tools and packaging, for example) ship as NodeSet2
files, and so do vendors' own models. The **OPC UA NodeSet2** importer (`opcua-nodeset`) reads one
into the [Catalog](./catalog.mdx) as an RPC API you can search, version and diff.

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| A NodeSet2 file (`.xml`, usually `*.NodeSet2.xml`) | One catalog item with the file's types and methods |
| A model and the companion models it requires, in one archive (`.zip`, `.tar.gz`) | One catalog item. The model is the root, and the required models resolve against the other files |
| A nodeset that holds only an address space (objects and variables, no types) | One catalog item with no types. The address space appears under **Format details** |
| An XML Schema (`.xsd`) or any XML whose root is not `UANodeSet` | Not this importer |

Apiome recognises a nodeset by its root element: `UANodeSet`, normally in the
`http://opcfoundation.org/UA/2011/03/UANodeSet.xsd` namespace. Both OPC UA 1.04 and 1.05 nodesets
are read.

## Import it

Import the file like any other specification: in the [import wizard](./import-wizard.mdx), with
`apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)). Apiome
picks **OPC UA NodeSet2** (`opcua-nodeset`).

For a model that builds on a companion specification, **put both NodeSet2 files in one archive** and
choose the model as the root. Each file numbers its namespaces in its own table; Apiome matches them
by namespace URI, so a subtype or data type defined in the companion model resolves.

The catalog item is named after the model's URI (`http://example.com/UA/Machine/` becomes
**Machine**), and its version is the model's `Version`.

## What each part becomes

| NodeSet2 | In the catalog item |
| --- | --- |
| `UAObjectType` | A **record**. Its fields are the variables and objects the type declares (its *instance declarations*). A supertype in the file contributes its fields first |
| `Mandatory` / `Optional` modelling rule | A required field / an optional field. A declaration with no rule is optional |
| `OptionalPlaceholder` / `MandatoryPlaceholder` | A list field (the mandatory one needs at least one entry) |
| `UAVariableType` | An **alias** of its data type |
| `UADataType` with a structure `Definition` | A **record** with one field per `Field`. `IsOptional` fields are optional |
| `UADataType` that is an enumeration | An **enum**, with each field's `Value` |
| An `OptionSet` data type | An **enum** of its bits (that the bits combine is recorded) |
| A union data type | A **record** whose fields are all optional |
| A subtype of a built-in type (for example of `String`) | An **alias** of that type |
| `UAMethod` | An **operation** in a service named after the type that owns it. Its `InputArguments` and `OutputArguments` become the request and response, which Apiome names `<Type>_<Method>_Request` and `_Response` and labels **synthesized** (see [Declared, inferred and synthesized](./inference-provenance.mdx)) |
| `ValueRank` and `ArrayDimensions` | Lists, nested lists for several dimensions, and a maximum length where a dimension is bounded |
| Built-in data types | Scalars with a format: `Int32` is an integer (`int32`), `DateTime` a string (`date-time`), `Double` a number (`double`) |
| `References` | Kept on each type, with their reference type, target and direction |
| `UAReferenceType` | Listed with its inverse name and supertype |
| `NamespaceUris`, `Models`, `RequiredModel` | Recorded as provenance: every namespace, model URI, version and publication date |
| `UAObject` / `UAVariable` / `UAView` that belong to the address space | **Not turned into types.** They appear under **Format details** only |

## What is declared, not imported

Apiome records these in the import's coverage ledger instead of guessing:

- **A reference into another model that is not in the upload** (often OPC UA for Devices, DI). A
  field of that type keeps the NodeId and is typed as *any*. A supertype there contributes no
  inherited fields. Import the archive with the required model to resolve it.
- **A base structure referenced by NodeId**, such as `Range` or `EUInformation`. The field is typed
  as an opaque object.
- **A structured or enumerated data type with no `Definition`**. It is modelled empty.
- **Unions, option sets and multi-dimensional arrays** keep their type, and what the model cannot
  express is recorded.
- **Address-space instances**, counted.
- **Variable values, access levels and role permissions** are not read.

## The address space and the reference graph

Open the item's **Format details** tab to see the whole nodeset in OPC UA's own terms:

1. **Namespaces**, **models** and **aliases** come first.
2. Then one group per node class: object types, variable types, data types, reference types,
   methods, objects, variables and views.
3. Each node shows its **role**: a *type*, a type's *declaration*, a method's *signature*, or an
   address-space *instance*.
4. Under each node come its definition fields and its references.

The tab keeps at most 5000 nodes. A large plant model keeps every node and drops references first,
and the record says it is **partial** (see
[Bounds: when the tree is cut](./catalog-format-details.md#bounds-when-the-tree-is-cut)).

## When an import is refused

| Error code | Why |
| --- | --- |
| `FORMAT_MISMATCH` | The file is not XML, or its root element is not `UANodeSet` (an XML Schema, for example). |
| `INPUT_MALFORMED` | The XML is not well formed, such as an unclosed node element. |
| `INPUT_TRUNCATED` | The file ends in the middle of the nodeset. |
| `INPUT_SEMANTIC_INVALID` | The nodeset declares no node, a node has no `NodeId` or `BrowseName`, or two nodes share a `NodeId`. |
| `INPUT_REFERENCE_UNRESOLVED` | A reference points at a node in the nodeset's own namespace that nothing declares, or at a namespace index with no URI. |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |
| `INPUT_UNSAFE_CONSTRUCT` | The XML has a `DOCTYPE`, an entity or an external reference. |

## Related

- [Supported formats](./supported-formats.md#format-opcua-nodeset): what this importer reads.
- [Read a catalog item's format details](./catalog-format-details.md#the-opc-ua-nodeset2-analysis):
  the address space and the reference graph.
- [Declared, inferred and synthesized](./inference-provenance.mdx): why method argument records are
  labelled synthesized.
- [Convert a catalog item to OpenAPI](./convert-to-openapi.md): turn the methods into an API
  description.
