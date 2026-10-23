---
title: "Import SHACL, OWL and JSON-LD"
description: "Catalog SHACL shapes, OWL / RDFS ontologies and JSON-LD contexts as data schemas."
sidebar_position: 27
tags: [import, shacl, owl, rdfs, json-ld, linked-data, rdf, ontology]
---

Publishing, pharmaceutical and government estates describe their data as **linked data**: SHACL
shapes say what a record must contain, OWL and RDFS ontologies name the classes and properties, and
JSON-LD contexts map JSON keys to IRIs. Apiome reads all three into the [Catalog](./catalog.mdx) as
**data schema** items you can search, version, diff and convert:

| Importer | Key | Reads |
| --- | --- | --- |
| **SHACL shapes** | `shacl` | A shapes graph in Turtle (`.ttl`), RDF/XML (`.rdf`) or JSON-LD (`.jsonld`) |
| **OWL / RDFS ontologies** | `owl` | An OWL or RDFS ontology in Turtle, RDF/XML (`.owl`, `.rdf`) or JSON-LD |
| **JSON-LD contexts** | `jsonld` | A JSON-LD document's `@context` (with or without the data it describes) |

## Import it

Import the file like any other specification: in the [import wizard](./import-wizard.mdx), with
`apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)). Apiome
tells the three apart by vocabulary, not by file type: a Turtle file that declares `sh:NodeShape`
is SHACL, one that declares `owl:Class` is an ontology, and a JSON document with a top-level
`@context` is a JSON-LD context. A JSON-LD document that holds SHACL shapes is read as SHACL.

**Upload the whole set when files refer to each other.** A shapes graph or an ontology that pulls
another in with `owl:imports`, or a context array that names a sibling context file, needs those
files in the same archive (`.zip`, `.tar.gz`). Apiome matches each `owl:imports` to the ontology IRI
another file declares, and each relative context to the file at that path.

**Apiome never fetches anything.** An `owl:imports` or a context that is not in the upload is
refused with `INPUT_REFERENCE_UNRESOLVED`, and the message names it. The one exception: importing a
well-known W3C or DCMI vocabulary (DCAT, Dublin Core, SKOS, FOAF, PROV, schema.org and the RDF, RDFS,
OWL, XSD and SHACL namespaces) is kept and listed in the coverage ledger.

## SHACL shapes

| SHACL | In the catalog item |
| --- | --- |
| A node shape (`ex:PersonShape a sh:NodeShape`) | A **record** `PersonShape`. Its IRI is kept as the type's native ID, and its targets (`sh:targetClass`) are kept on the type |
| A property shape (`sh:property [ sh:path ex:email ; … ]`) | A field named after the path, `email` |
| `sh:datatype xsd:string` (`xsd:integer`, `xsd:date` …) | The matching scalar: `string`, `integer`, `date` … |
| `sh:node ex:AddressShape` | A field typed by the `AddressShape` record |
| `sh:class ex:Organisation` | A field typed by the record of the shape that targets `ex:Organisation`; with no such shape, an IRI string |
| `sh:maxCount 1` | A single value. Without `sh:maxCount 1` the field is a **list**, with `sh:minCount` / `sh:maxCount` as its minimum and maximum items |
| `sh:minCount 1` (or more) | A required field |
| `sh:minInclusive` … `sh:maxExclusive`, `sh:minLength`, `sh:maxLength`, `sh:pattern` | The matching constraints |
| `sh:in ( … )`, `sh:hasValue` | The allowed values |
| `sh:node` or `sh:and` on a node shape | Inheritance: the referenced shape's fields are added to this record |
| `sh:or` / `sh:xone` of property sets | Every alternative's fields, all optional |
| A node shape that is only `sh:or` of other shapes or datatypes | A **union** |
| An anonymous (blank-node) shape | A record named after the field that uses it, labelled **synthesized** |
| `sh:severity`, `sh:message`, `sh:name`, `sh:order`, `sh:group`, `sh:closed` | Kept on the field or type |

**Cycles are kept, and declared.** Shapes may refer to each other in a loop (`PersonShape` requires
`KnowsShape`, which requires `PersonShape`). SHACL leaves validation through such a loop undefined;
Apiome keeps the references, so `PersonShape.knows` is typed by `KnowsShape`, stops there, and lists
every shape in a cycle in the coverage ledger.

## OWL and RDFS ontologies

| OWL / RDFS | In the catalog item |
| --- | --- |
| `owl:Ontology` with `rdfs:label`, `owl:versionInfo`, `rdfs:comment` | The item's name, version and description |
| A class (`owl:Class`, `rdfs:Class`) | A **record**. Its IRI is kept as the type's native ID |
| `rdfs:subClassOf ex:Agent` | Inheritance: the class carries `Agent`'s fields |
| A property with `rdfs:domain ex:Order` | A field of `Order` (and of every subclass) |
| `rdfs:range xsd:string` / `rdfs:range ex:Customer` | A `string` field / a field typed by the `Customer` record |
| `rdfs:subPropertyOf` | The property inherits its parent's domain and range |
| `owl:FunctionalProperty` | A single value. Any other property is a **list**: OWL lets a property have many values |
| A cardinality restriction (`owl:cardinality`, `owl:minQualifiedCardinality` …) | The field's minimum and maximum items; a minimum of one makes it required. The restriction also attaches the property to the class |
| `owl:oneOf ( ex:Red ex:Green )` | An **enum** of those individuals |
| A class with named individuals but no `owl:oneOf` | An enum of the individuals it lists, labelled **inferred**: OWL does not close the class |
| `owl:unionOf` of named classes | A **union** |
| A named `rdfs:Datatype` with `owl:withRestrictions` | An alias of its base type, with the facets as constraints |

**OWL is open-world; the catalog is closed-world.** An ontology licenses a reasoner to infer facts
it never states. Apiome imports what the ontology asserts and never what a reasoner would infer,
and every OWL import says so in its coverage ledger. The axioms that only drive inference are kept
on the type or field and listed in the ledger: `owl:intersectionOf` / `owl:complementOf` class
expressions, `owl:someValuesFrom` / `owl:allValuesFrom` restrictions, transitive, symmetric and
other property characteristics, property chains, `owl:inverseOf`, `owl:equivalentClass`,
`owl:disjointWith`, `owl:sameAs` and `owl:differentFrom`.

Apiome reads Turtle, RDF/XML and JSON-LD. Export OWL/XML, Manchester or functional syntax to one of
those first.

## JSON-LD contexts

| JSON-LD | In the catalog item |
| --- | --- |
| The `@context` | One **record**, named after the file (`catalog-context.jsonld` → `CatalogContext`), with a field per term |
| A term (`"email": "schema:email"`) | A field `email`. The IRI it expands to (`https://schema.org/email`) is kept as the field's native ID, and the definition as written is kept beside it |
| `"@type": "xsd:date"` | A `date` field |
| `"@type": "@id"` or `"@vocab"` | An IRI string |
| `"@type": "@json"`, or no `@type` | Any value |
| `"@container": "@set"` / `"@list"` | A list (an `@list` is marked ordered) |
| `"@container": "@language"` | A `LanguageMap`: language tag → string |
| `"@container": "@index"` / `"@id"` / `"@type"` | A map keyed by index, IRI or type |
| A term with its own `@context` | A nested **record** named after the term, labelled **synthesized** |
| An `@vocab` term whose `@context` only names values | An **enum** of those values |
| A prefix (`"schema": "https://schema.org/"`), a keyword alias (`"id": "@id"`), a class name (`"Dataset": "dcat:Dataset"`) | Not fields: kept on the record |
| A context array | Merged in order: a later definition replaces an earlier one, and `null` starts again |

JSON-LD states no cardinality, so every field is optional. A context that sets `@vocab` accepts any
key, not only the ones it defines; the import lists only the defined terms and says so in the
coverage ledger. Data in the same document (`@graph`) is counted, not imported.

## What is declared, not imported

The coverage ledger lists, for each import:

- **SHACL**: SPARQL constraints (`sh:sparql`), open-world targets (`sh:targetSubjectsOf`,
  `sh:targetObjectsOf`), sequence, inverse, alternative and unbounded property paths, logical
  alternatives, property-pair constraints (`sh:lessThan` …), qualified value shapes, `sh:not`,
  language constraints and shape cycles.
- **OWL / RDFS**: the open-world assumption, class expressions, quantified restrictions, property
  characteristics and chains, inverse properties, equivalence, disjointness, individual identity,
  classes the import does not define, and properties attached to no class.
- **JSON-LD**: an open vocabulary (`@vocab`), data beside the context, reverse properties and graph
  containers.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | The Turtle, RDF/XML or JSON does not parse, such as a statement with no final `.` or a trailing comma. The message gives the line. |
| `INPUT_TRUNCATED` | The file ends while a bracket, list, string or IRI is still open. |
| `INPUT_SEMANTIC_INVALID` | The file parses but has nothing to import: no shapes, no classes or properties (an ontology header alone), no `@context`, or a context with only prefixes. |
| `INPUT_REFERENCE_UNRESOLVED` | An `owl:imports`, a JSON-LD context or a shape (`sh:node ex:MissingShape`) that the upload does not contain. |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |
| `INPUT_UNSAFE_CONSTRUCT` | RDF/XML declares a DTD or an entity. |
| `FORMAT_MISMATCH` | The file is one of the other formats: an ontology sent to the SHACL importer, a shapes graph sent to the OWL importer, or plain JSON (such as a JSON Schema) sent to the JSON-LD importer. |

## Related

- [Supported formats](./supported-formats.md#format-shacl): what each importer reads.
- [Declared, inferred and synthesized](./inference-provenance.mdx): why some types are labelled
  synthesized or inferred.
- [Import a specification](./import-a-spec.md): the import job and its options.
