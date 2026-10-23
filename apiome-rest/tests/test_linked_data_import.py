"""SHACL, JSON-LD and OWL/RDFS import — FMT-9.4 (#5471).

Covers the shared linked-data intake (syntax selection, truncation-versus-malformed classification,
encoding refusal, ``owl:imports`` and ``@context`` resolution confined to the upload), the SHACL
projection (node shapes → records, cardinality / datatype / value constraints, ``sh:node``
inheritance, logical alternatives, shape cycles), the OWL / RDFS projection (domain / range
fields, functional properties and cardinality restrictions, inheritance, enumerations, unions,
datatype facets, the open-world declaration), the JSON-LD context projection (terms, IRIs as
provenance, coercion and containers, scoped contexts), every refusal's taxonomy code, detection,
the coverage-ledger rows and the registry wiring.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.canonical_model import ApiParadigm, CanonicalApi, Type, TypeKind
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.format_version_coverage import version_coverage_for
from app.import_preview_manifest import _linked_data_capability_rows
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    detect_import_source,
    get_import_source,
    load_builtin_import_sources,
)
from app.inference_provenance import INFERENCE_BASED_ADAPTERS
from app.jsonld_import_source import JsonLdImportSource
from app.owl_import_source import OwlImportSource
from app.rdf_graph import (
    RdfParseError,
    load_json_document,
    load_rdf_document,
    load_rdf_text,
    local_name,
    resolve_json_contexts,
    sniff_syntax,
)
from app.shacl_import_source import ShaclImportSource

load_builtin_import_sources()

PREFIXES = """@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix ex:   <https://example.com/ns#> .
"""


def _shacl(body: str) -> CanonicalApi:
    adapter = ShaclImportSource()
    return adapter.normalize(adapter.parse(PREFIXES + body, source_label="shapes.ttl"))


def _owl(body: str) -> CanonicalApi:
    adapter = OwlImportSource()
    return adapter.normalize(adapter.parse(PREFIXES + body, source_label="ontology.ttl"))


def _jsonld(text: str, label: str = "context.jsonld") -> CanonicalApi:
    adapter = JsonLdImportSource()
    return adapter.normalize(adapter.parse(text, source_label=label))


def _type(api: CanonicalApi, key: str) -> Type:
    return next(t for t in api.types if t.key == key)


def _field(api: CanonicalApi, type_key: str, name: str):
    return next(f for f in _type(api, type_key).fields if f.name == name)


def _limits(api: CanonicalApi, key: str) -> Dict[str, List[str]]:
    return {limit["construct"]: limit["locations"] for limit in api.extras[key]["capability_limits"]}


def _code(callable_, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(ImportSourceError) as caught:
        callable_(*args, **kwargs)
    return caught.value.code


# ===========================================================================
# Shared intake
# ===========================================================================


class TestIntake:
    def test_syntax_is_chosen_by_content_then_name(self):
        assert sniff_syntax('{"@context": {}}', "a.ttl") == "json-ld"
        assert sniff_syntax('<?xml version="1.0"?><rdf:RDF/>', "a.ttl") == "xml"
        assert sniff_syntax("<rdf:RDF xmlns:rdf='x'/>") == "xml"
        assert sniff_syntax("@prefix ex: <https://e/> .", "a.owl") == "turtle"
        assert sniff_syntax("<https://e/a> <https://e/b> <https://e/c> .", "a.nt") == "nt"

    def test_turtle_iri_subject_is_not_mistaken_for_xml(self):
        assert sniff_syntax("<https://example.com/x> a <https://example.com/C> .") == "turtle"

    @pytest.mark.parametrize(
        "text",
        [
            PREFIXES + "ex:A sh:property [ sh:path ex:b ;",  # open bracket
            PREFIXES + 'ex:A rdfs:label "unterminated',  # open string at EOF
            PREFIXES + 'ex:A rdfs:label "broken\n',  # string broken by a final newline
            PREFIXES + "ex:A rdfs:seeAlso <https://example.com/x",  # open IRI
            PREFIXES + 'ex:A rdfs:comment """long',  # open long string
        ],
    )
    def test_a_construct_open_at_eof_is_truncation(self, text):
        with pytest.raises(RdfParseError) as caught:
            load_rdf_text(text, label="t.ttl")
        assert caught.value.code == "INPUT_TRUNCATED"

    @pytest.mark.parametrize(
        "text",
        [
            PREFIXES + "ex:A a ex:B",  # missing final dot, nothing open
            "@prefix ex: <https://example.com/ns# .\nex:A a ex:B .",  # IRI broken mid-file
            PREFIXES + "ex:A a ex:B ] .",  # stray closer
        ],
    )
    def test_other_syntax_faults_are_malformed(self, text):
        with pytest.raises(RdfParseError) as caught:
            load_rdf_text(text, label="m.ttl")
        assert caught.value.code == "INPUT_MALFORMED"
        assert "m.ttl" in str(caught.value)

    def test_hash_inside_an_iri_is_not_a_comment(self):
        source = load_rdf_text(PREFIXES + "<https://example.com/a#b> a ex:C .", label="h.ttl")
        assert len(source.graph) == 1

    @pytest.mark.parametrize("text", ["﻿@prefix ex: <x> .", "@\x00p", "ex:a � ."])
    def test_non_utf8_text_is_refused(self, text):
        with pytest.raises(RdfParseError) as caught:
            load_rdf_text(text, label="e.ttl")
        assert caught.value.code == "INPUT_ENCODING_INVALID"

    def test_empty_text_is_refused(self):
        with pytest.raises(RdfParseError) as caught:
            load_rdf_text("   \n", label="e.ttl")
        assert caught.value.code == "INPUT_EMPTY"

    def test_json_truncation_and_malformation(self):
        with pytest.raises(RdfParseError) as caught:
            load_json_document('{"@context": {"a": "b', label="t.jsonld")
        assert caught.value.code == "INPUT_TRUNCATED"
        with pytest.raises(RdfParseError) as caught:
            load_json_document('{"@context": {"a": "b",}}', label="m.jsonld")
        assert caught.value.code == "INPUT_MALFORMED"

    def test_rdf_xml_runs_through_the_hardened_parser(self):
        hostile = (
            '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x "y">]>'
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">&x;</rdf:RDF>'
        )
        with pytest.raises(RdfParseError) as caught:
            load_rdf_text(hostile, label="x.owl")
        assert caught.value.code == "INPUT_UNSAFE_CONSTRUCT"

    def test_a_remote_json_ld_context_is_never_fetched(self):
        unresolved: List[str] = []
        out = resolve_json_contexts(
            {"@context": ["https://example.com/ctx.jsonld", {"a": "https://e/a"}]},
            path="d.jsonld",
            members={},
            unresolved=unresolved,
        )
        assert unresolved == ["https://example.com/ctx.jsonld"]
        assert out["@context"] == [{"a": "https://e/a"}]

    def test_relative_contexts_and_import_resolve_from_the_upload(self):
        members = {
            "dir/doc.jsonld": "{}",
            "dir/base.jsonld": '{"@context": {"a": "https://e/a", "b": "https://e/b"}}',
            "shared/terms.jsonld": '{"@context": {"c": "https://e/c"}}',
        }
        resolved: List[str] = []
        out = resolve_json_contexts(
            {"@context": ["base.jsonld", {"@import": "../shared/terms.jsonld", "b": "https://e/override"}]},
            path="dir/doc.jsonld",
            members=members,
            resolved=resolved,
        )
        assert out["@context"][0] == {"a": "https://e/a", "b": "https://e/b"}
        assert out["@context"][1] == {"c": "https://e/c", "b": "https://e/override"}
        assert resolved == ["dir/base.jsonld", "shared/terms.jsonld"]

    def test_json_ld_rdf_with_a_remote_context_is_refused(self):
        with pytest.raises(RdfParseError) as caught:
            load_rdf_text('{"@context": "https://schema.org/", "@id": "x"}', label="s.jsonld")
        assert caught.value.code == "INPUT_REFERENCE_UNRESOLVED"
        assert "https://schema.org/" in str(caught.value)

    def test_owl_imports_resolve_within_a_fileset(self):
        fileset = IntakeFileset.from_members(
            {
                "root.ttl": PREFIXES + "<https://e/root> a owl:Ontology ; owl:imports <https://e/core> .",
                "core.ttl": PREFIXES + "<https://e/core/> a owl:Ontology . ex:A a owl:Class .",
                "README.md": "not rdf",
            },
            root="root.ttl",
        )
        document = load_rdf_document(label="root.ttl", fileset=fileset)
        assert [s.path for s in document.sources] == ["root.ttl", "core.ttl"]
        assert document.is_fileset and document.file_of(next(iter(document.root.graph.subjects()))) == "root.ttl"

    def test_a_missing_import_is_refused_but_a_well_known_vocabulary_is_declared(self):
        with pytest.raises(RdfParseError) as caught:
            load_rdf_document(PREFIXES + "<https://e/x> owl:imports <https://e/missing> .", label="x.ttl")
        assert caught.value.code == "INPUT_REFERENCE_UNRESOLVED"
        document = load_rdf_document(
            PREFIXES + "<https://e/x> a owl:Ontology ; owl:imports <http://www.w3.org/ns/dcat#> .", label="x.ttl"
        )
        assert document.external_imports == ("http://www.w3.org/ns/dcat#",)

    def test_compact_uses_the_documents_own_prefixes(self):
        document = load_rdf_document(PREFIXES + "ex:A a owl:Class .", label="c.ttl")
        assert document.compact("https://example.com/ns#A") == "ex:A"
        assert document.compact("urn:other:x") == "<urn:other:x>"
        assert local_name("https://example.com/ns#A") == "A"
        assert local_name("https://example.com/path/B/") == "B"


# ===========================================================================
# SHACL
# ===========================================================================


SHAPES = """
ex:PersonShape a sh:NodeShape ;
    sh:targetClass ex:Person ;
    rdfs:comment "A person." ;
    sh:property [ sh:path ex:name ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ;
                  sh:minLength 1 ; sh:maxLength 60 ; sh:pattern "^[A-Z]" ; sh:flags "i" ] ;
    sh:property [ sh:path ex:age ; sh:datatype xsd:integer ; sh:maxCount 1 ; sh:minInclusive 0 ;
                  sh:maxExclusive 150 ] ;
    sh:property [ sh:path ex:nick ; sh:datatype xsd:string ; sh:minCount 2 ; sh:maxCount 4 ] ;
    sh:property [ sh:path ex:role ; sh:in ( "reader" "admin" ) ; sh:maxCount 1 ;
                  sh:severity sh:Warning ; sh:message "Unknown role." ; sh:order 3 ] ;
    sh:property [ sh:path ex:employer ; sh:class ex:Company ; sh:maxCount 1 ] ;
    sh:property [ sh:path ex:home ; sh:class ex:Unshaped ; sh:maxCount 1 ] ;
    sh:property [ sh:path ex:kind ; sh:hasValue "human" ; sh:maxCount 1 ] .
ex:CompanyShape a sh:NodeShape ; sh:targetClass ex:Company ;
    sh:property [ sh:path ex:legalName ; sh:datatype xsd:string ; sh:minCount 1 ] .
"""


class TestShacl:
    def test_node_shapes_become_records_with_iri_provenance(self):
        api = _shacl(SHAPES)
        assert api.paradigm is ApiParadigm.DATA_SCHEMA and api.format == "shacl"
        person = _type(api, "PersonShape")
        assert person.kind is TypeKind.RECORD
        assert person.extras["native_id"] == "https://example.com/ns#PersonShape"
        assert person.extras["shacl_target_class"] == ["ex:Person"]
        assert person.description == "A person."

    def test_cardinality_maps_to_required_single_or_list(self):
        api = _shacl(SHAPES)
        name = _field(api, "PersonShape", "name")
        assert name.type.name == "string" and not name.type.nullable
        nick = _field(api, "PersonShape", "nick")
        assert nick.type.item.name == "string"
        assert (nick.constraints.min_items, nick.constraints.max_items) == (2, 4)
        legal = _field(api, "CompanyShape", "legalName")
        assert legal.type.item is not None and not legal.type.nullable
        assert legal.constraints.min_items == 1 and legal.constraints.max_items is None

    def test_value_constraints_map_to_canonical_constraints(self):
        api = _shacl(SHAPES)
        name = _field(api, "PersonShape", "name")
        assert (name.constraints.min_length, name.constraints.max_length) == (1, 60)
        assert name.constraints.pattern == "^[A-Z]" and name.extras["shacl_flags"] == "i"
        assert name.extras["native_id"] == "https://example.com/ns#name"
        age = _field(api, "PersonShape", "age")
        assert age.type.name == "integer" and age.type.nullable
        assert (age.constraints.minimum, age.constraints.exclusive_maximum) == (0, 150)
        role = _field(api, "PersonShape", "role")
        assert role.constraints.enum == ["reader", "admin"] and role.type.name == "string"
        assert role.extras["shacl_severity"] == "Warning" and role.extras["shacl_message"] == "Unknown role."
        kind = _field(api, "PersonShape", "kind")
        assert kind.constraints.enum == ["human"] and kind.extras["shacl_has_value"] == ["human"]

    def test_sh_class_names_the_targeting_shape_or_an_iri(self):
        api = _shacl(SHAPES)
        assert _field(api, "PersonShape", "employer").type.name == "CompanyShape"
        home = _field(api, "PersonShape", "home")
        assert home.type.name == "string" and home.constraints.format == "iri"
        assert home.extras["shacl_class"] == "ex:Unshaped"

    def test_sh_node_on_a_node_shape_is_inheritance(self):
        api = _shacl(
            """
ex:Base a sh:NodeShape ; sh:property [ sh:path ex:id ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] .
ex:Child a sh:NodeShape ; sh:node ex:Base ;
    sh:property [ sh:path ex:extra ; sh:datatype xsd:boolean ; sh:maxCount 1 ] .
"""
        )
        child = _type(api, "Child")
        assert {f.name for f in child.fields} == {"id", "extra"}
        assert _field(api, "Child", "id").extras["shacl_inherited_from"] == "Base"
        assert child.extras["shacl_node"] == ["Base"]

    def test_anonymous_node_shapes_are_synthesized_records(self):
        api = _shacl(
            """
ex:Order a sh:NodeShape ;
    sh:property [ sh:path ex:address ; sh:maxCount 1 ;
                  sh:node [ sh:property [ sh:path ex:city ; sh:datatype xsd:string ] ] ] .
"""
        )
        address = _field(api, "Order", "address")
        synthesized = _type(api, address.type.name)
        assert synthesized.extras["provenance"] == "synthesized"
        assert [f.name for f in synthesized.fields] == ["city"]

    def test_xone_alternatives_are_optional_fields_and_declared(self):
        api = _shacl(
            """
ex:Pay a sh:NodeShape ; sh:xone (
    [ sh:property [ sh:path ex:card ; sh:minCount 1 ] ]
    [ sh:property [ sh:path ex:iban ; sh:minCount 1 ] ] ) .
"""
        )
        card = _field(api, "Pay", "card")
        assert card.type.nullable and card.extras["shacl_alternative"] == "xone"
        assert "shacl.logical_alternatives" in _limits(api, "shacl")

    def test_a_shape_that_is_only_alternatives_is_a_union(self):
        api = _shacl("ex:Id a sh:NodeShape ; sh:or ( [ sh:datatype xsd:string ] [ sh:datatype xsd:integer ] ) .")
        assert _type(api, "Id").kind is TypeKind.UNION
        assert _type(api, "Id").union_members == ["string", "integer"]

    def test_shape_cycles_terminate_and_are_declared(self):
        api = _shacl(
            """
ex:A a sh:NodeShape ; sh:property [ sh:path ex:b ; sh:node ex:B ] .
ex:B a sh:NodeShape ; sh:property [ sh:path ex:a ; sh:node ex:A ] .
ex:T a sh:NodeShape ; sh:property [ sh:path ex:child ; sh:node ex:T ] .
ex:Leaf a sh:NodeShape ; sh:property [ sh:path ex:v ; sh:datatype xsd:string ] .
"""
        )
        assert _limits(api, "shacl")["shacl.recursive_shape"] == ["A", "B", "T"]
        assert _field(api, "T", "child").type.item.name == "T"
        assert "shacl_recursive" not in _type(api, "Leaf").extras

    def test_paths_and_open_world_constructs_are_declared(self):
        api = _shacl(
            """
ex:S a sh:NodeShape ; sh:targetSubjectsOf ex:p ;
    sh:sparql [ a sh:SPARQLConstraint ; sh:message "m" ; sh:select "SELECT $this WHERE {}" ] ;
    sh:property [ sh:path ( ex:a ex:b ) ] ;
    sh:property [ sh:path [ sh:inversePath ex:c ] ] ;
    sh:property [ sh:path [ sh:zeroOrMorePath ex:d ] ] ;
    sh:property [ sh:path [ sh:alternativePath ( ex:e ex:f ) ] ] ;
    sh:property [ sh:path ex:g ; sh:lessThan ex:h ] ;
    sh:property [ sh:path ex:i ; sh:languageIn ( "en" ) ] .
"""
        )
        limits = _limits(api, "shacl")
        assert limits["shacl.complex_path"] == ["S.a_b", "S.c_inverse", "S.e_or_f"]
        assert limits["shacl.unbounded_path"] == ["S.d_zeroOrMore"]
        assert limits["shacl.open_world_target"] == ["S"]
        assert limits["shacl.sparql_constraint"] == ["S"]
        assert limits["shacl.property_pair"] == ["S.g"]
        assert limits["shacl.language_constraint"] == ["S.i"]
        assert _field(api, "S", "a_b").extras["shacl_path"] == "ex:a / ex:b"
        assert _field(api, "S", "c_inverse").extras["shacl_path"] == "^ex:c"
        assert _type(api, "S").extras["shacl_sparql"] == [{"message": "m", "select": "SELECT $this WHERE {}"}]

    def test_colliding_local_names_are_prefix_qualified(self):
        api = _shacl(
            "@prefix other: <https://other.example.com/ns#> .\n"
            "ex:Shape a sh:NodeShape ; sh:property [ sh:path ex:a ] .\n"
            "other:Shape a sh:NodeShape ; sh:property [ sh:path ex:b ] .\n"
        )
        assert {t.key for t in api.types} == {"ex.Shape", "other.Shape"}

    def test_json_ld_shapes_graph_reads_like_turtle(self):
        adapter = ShaclImportSource()
        text = (
            '{"@context": {"sh": "http://www.w3.org/ns/shacl#", "xsd": "http://www.w3.org/2001/XMLSchema#",'
            ' "ex": "https://example.com/ns#"}, "@id": "ex:P", "@type": "sh:NodeShape",'
            ' "sh:property": {"sh:path": {"@id": "ex:sku"}, "sh:datatype": {"@id": "xsd:string"},'
            ' "sh:minCount": 1, "sh:maxCount": 1}}'
        )
        api = adapter.normalize(adapter.parse(text, source_label="p.jsonld"))
        assert _field(api, "P", "sku").type.name == "string"

    def test_owl_imported_shapes_resolve_across_a_fileset(self):
        adapter = ShaclImportSource()
        fileset = IntakeFileset.from_members(
            {
                "main.ttl": PREFIXES
                + "<https://e/main> a owl:Ontology ; owl:imports <https://e/core> .\n"
                + "ex:Ship a sh:NodeShape ; sh:property [ sh:path ex:to ; sh:node ex:Addr ; sh:maxCount 1 ] .",
                "core.ttl": PREFIXES
                + "<https://e/core> a owl:Ontology .\nex:Addr a sh:NodeShape ; sh:property [ sh:path ex:city ] .",
            },
            root="main.ttl",
        )
        api = adapter.normalize(adapter.parse_fileset(fileset))
        assert _field(api, "Ship", "to").type.name == "Addr"
        assert _type(api, "Addr").extras["rdf_file"] == "core.ttl"
        assert api.extras["shacl"]["input"] == "fileset"

    def test_refusals_carry_their_codes(self):
        adapter = ShaclImportSource()
        missing = PREFIXES + "ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ; sh:node ex:Gone ] ."
        assert _code(adapter.parse, missing, source_label="m.ttl") == "INPUT_REFERENCE_UNRESOLVED"
        no_shapes = PREFIXES + "ex:A a owl:Class ."
        assert _code(adapter.parse, no_shapes, source_label="n.ttl") == "INPUT_SEMANTIC_INVALID"
        ontology = PREFIXES + "<https://e/o> a owl:Ontology . ex:A a owl:Class ."
        assert _code(adapter.parse, ontology, source_label="o.ttl") == "FORMAT_MISMATCH"
        assert _code(adapter.parse, PREFIXES + "ex:S a sh:NodeShape", source_label="b.ttl") == "INPUT_MALFORMED"

    def test_normalize_rejects_a_foreign_ast(self):
        with pytest.raises(ImportSourceError):
            ShaclImportSource().normalize({"not": "a document"})


# ===========================================================================
# OWL / RDFS
# ===========================================================================


ONTOLOGY = """
<https://example.com/ns> a owl:Ontology ; rdfs:label "Commerce" ; owl:versionInfo "2.0.0" ;
    rdfs:comment "Orders." .
ex:Agent a owl:Class ; rdfs:label "Agent" .
ex:Customer a owl:Class ; rdfs:subClassOf ex:Agent ; rdfs:comment "Buys things." .
ex:Order a owl:Class ;
    rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:orderId ;
                      owl:qualifiedCardinality "1"^^xsd:nonNegativeInteger ; owl:onDataRange xsd:string ] ;
    rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:line ; owl:minCardinality "1"^^xsd:nonNegativeInteger ] .
ex:name a owl:DatatypeProperty ; rdfs:domain ex:Agent ; rdfs:range xsd:string .
ex:placedBy a owl:ObjectProperty , owl:FunctionalProperty ; rdfs:domain ex:Order ; rdfs:range ex:Customer ;
    owl:inverseOf ex:placed .
ex:placed a owl:ObjectProperty ; rdfs:domain ex:Customer ; rdfs:range ex:Order .
ex:orderId a owl:DatatypeProperty .
ex:line a owl:ObjectProperty ; rdfs:range ex:Line .
ex:Line a owl:Class .
ex:loose a owl:DatatypeProperty .
ex:Colour a owl:Class ; owl:oneOf ( ex:Red ex:Green ) .
ex:Status a owl:Class .
ex:New a owl:NamedIndividual , ex:Status .
ex:Done a owl:NamedIndividual , ex:Status .
"""


class TestOwl:
    def test_ontology_header_is_the_api_identity(self):
        api = _owl(ONTOLOGY)
        assert (api.identity.name, api.version, api.description) == ("Commerce", "2.0.0", "Orders.")
        assert api.extras["owl"]["ontology"]["iri"] == "https://example.com/ns"

    def test_domain_and_range_make_typed_fields(self):
        api = _owl(ONTOLOGY)
        placed_by = _field(api, "Order", "placedBy")
        assert placed_by.type.name == "Customer" and placed_by.type.nullable
        assert placed_by.extras["owl_property_kind"] == "object" and placed_by.extras["owl_functional"]
        name = _field(api, "Agent", "name")
        assert name.type.item.name == "string", "a non-functional property is multi-valued"
        assert name.extras["native_id"] == "https://example.com/ns#name"

    def test_restrictions_attach_and_bound_properties(self):
        api = _owl(ONTOLOGY)
        order_id = _field(api, "Order", "orderId")
        assert order_id.type.name == "string" and not order_id.type.nullable
        line = _field(api, "Order", "line")
        assert line.type.item.name == "Line" and line.constraints.min_items == 1 and not line.type.nullable

    def test_subclasses_inherit_superclass_fields(self):
        api = _owl(ONTOLOGY)
        customer = _type(api, "Customer")
        assert {f.name for f in customer.fields} == {"name", "placed"}
        assert _field(api, "Customer", "name").extras["owl_inherited_from"] == "Agent"
        assert customer.extras["owl_superclasses"] == ["Agent"]

    def test_enumerations_and_individual_code_lists(self):
        api = _owl(ONTOLOGY)
        colour = _type(api, "Colour")
        assert colour.kind is TypeKind.ENUM and [v.name for v in colour.enum_values] == ["Red", "Green"]
        status = _type(api, "Status")
        assert status.kind is TypeKind.ENUM and [v.name for v in status.enum_values] == ["Done", "New"]
        assert status.extras["provenance"] == "inferred"
        assert _limits(api, "owl")["owl.individual_enumeration"] == ["Status"]

    def test_open_world_is_always_declared(self):
        api = _owl(ONTOLOGY)
        limits = _limits(api, "owl")
        assert limits["owl.open_world"] == ["Commerce"]
        assert limits["owl.inverse_property"] == ["Customer.placed", "Order.placedBy"]
        assert limits["owl.property_without_domain"] == ["ex:loose"]
        assert api.extras["owl"]["unattached_properties"] == ["ex:loose"]

    def test_inference_axioms_are_declared_not_modelled(self):
        api = _owl(
            """
ex:A a owl:Class . ex:B a owl:Class ; owl:disjointWith ex:A ; owl:equivalentClass <https://o/X> .
ex:U a owl:Class ; owl:unionOf ( ex:A ex:B ) .
ex:N a owl:Class ; owl:complementOf ex:A .
ex:p a owl:ObjectProperty , owl:TransitiveProperty ; rdfs:domain ex:A ; rdfs:range ex:A ;
    owl:propertyChainAxiom ( ex:p ex:p ) .
ex:K a owl:Class ; rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:p ; owl:someValuesFrom ex:B ] .
ex:i1 owl:sameAs ex:i2 .
"""
        )
        limits = _limits(api, "owl")
        for key in (
            "owl.disjointness",
            "owl.class_equivalence",
            "owl.class_expression",
            "owl.property_characteristic",
            "owl.property_chain",
            "owl.quantified_restriction",
            "owl.individual_identity",
        ):
            assert key in limits, key
        assert _type(api, "U").kind is TypeKind.UNION and _type(api, "U").union_members == ["A", "B"]
        assert _field(api, "A", "p").extras["owl_characteristics"] == ["TransitiveProperty"]
        assert _field(api, "K", "p").extras["owl_restrictions"] == {"someValuesFrom": "ex:B"}

    def test_sub_properties_inherit_domain_and_range(self):
        api = _owl(
            """
ex:Party a owl:Class . ex:Org a owl:Class ; rdfs:subClassOf ex:Party .
ex:identifier a owl:DatatypeProperty ; rdfs:domain ex:Party ; rdfs:range xsd:string .
ex:legalName a owl:DatatypeProperty ; rdfs:subPropertyOf ex:identifier .
"""
        )
        legal = _field(api, "Party", "legalName")
        assert legal.type.item.name == "string"
        assert legal.extras["owl_sub_property_of"] == ["ex:identifier"]

    def test_named_datatypes_with_facets_are_aliases(self):
        api = _owl(
            """
ex:Pct a rdfs:Datatype ; owl:equivalentClass [ a rdfs:Datatype ; owl:onDatatype xsd:decimal ;
    owl:withRestrictions ( [ xsd:minInclusive "0"^^xsd:decimal ] [ xsd:maxInclusive "100"^^xsd:decimal ] ) ] .
ex:Gauge a owl:Class . ex:level a owl:DatatypeProperty ; rdfs:domain ex:Gauge ; rdfs:range ex:Pct .
"""
        )
        pct = _type(api, "Pct")
        assert pct.kind is TypeKind.ALIAS and pct.aliased.name == "decimal"
        assert (pct.constraints.minimum, pct.constraints.maximum) == (0, 100)
        assert _field(api, "Gauge", "level").type.item.name == "Pct"

    def test_external_classes_are_declared_references(self):
        api = _owl(
            "@prefix ext: <https://ext.example.com/#> .\n"
            "ex:A a owl:Class ; rdfs:subClassOf ext:Base .\n"
            "ex:r a owl:ObjectProperty ; rdfs:domain ex:A ; rdfs:range ext:Thing .\n"
        )
        r = _field(api, "A", "r")
        assert r.type.item.name == "string" and r.constraints.format == "iri" and r.extras["owl_range"] == "ext:Thing"
        assert set(_limits(api, "owl")["owl.external_reference"]) == {"A", "A.r"}

    def test_plain_rdfs_vocabulary_reads(self):
        adapter = OwlImportSource()
        text = PREFIXES + (
            "ex:Work a rdfs:Class . ex:Book a rdfs:Class ; rdfs:subClassOf ex:Work .\n"
            "ex:title a rdf:Property ; rdfs:domain ex:Work ; rdfs:range xsd:string .\n"
            "ex:about a rdf:Property ; rdfs:domain ex:Book ; rdfs:range ex:Work .\n"
        ).replace("@prefix owl:  <http://www.w3.org/2002/07/owl#> .\n", "")
        api = adapter.normalize(adapter.parse(text, source_label="v.ttl"))
        assert _field(api, "Book", "title").extras["owl_inherited_from"] == "Work"
        assert _field(api, "Book", "about").extras["owl_property_kind"] == "object"

    def test_rdf_xml_ontology_reads(self):
        adapter = OwlImportSource()
        text = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Class rdf:about="https://e/ns#Truck"/>
  <owl:DatatypeProperty rdf:about="https://e/ns#vin">
    <rdfs:domain rdf:resource="https://e/ns#Truck"/>
    <rdfs:range rdf:resource="http://www.w3.org/2001/XMLSchema#string"/>
  </owl:DatatypeProperty>
</rdf:RDF>"""
        api = adapter.normalize(adapter.parse(text, source_label="fleet.owl"))
        assert _field(api, "Truck", "vin").type.item.name == "string"

    def test_refusals_carry_their_codes(self):
        adapter = OwlImportSource()
        header_only = PREFIXES + "<https://e/o> a owl:Ontology ."
        assert _code(adapter.parse, header_only, source_label="h.ttl") == "INPUT_SEMANTIC_INVALID"
        shapes = PREFIXES + "ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ] ."
        assert _code(adapter.parse, shapes, source_label="s.ttl") == "FORMAT_MISMATCH"
        dangling = PREFIXES + "<https://e/o> a owl:Ontology ; owl:imports <https://e/gone> . ex:A a owl:Class ."
        assert _code(adapter.parse, dangling, source_label="d.ttl") == "INPUT_REFERENCE_UNRESOLVED"


# ===========================================================================
# JSON-LD
# ===========================================================================


CONTEXT = """{
  "@context": {
    "@version": 1.1,
    "@vocab": "https://example.com/ns#",
    "schema": "https://schema.org/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "id": "@id",
    "Person": "schema:Person",
    "name": "schema:name",
    "born": {"@id": "schema:birthDate", "@type": "xsd:date"},
    "home": {"@id": "schema:url", "@type": "@id"},
    "tags": {"@id": "schema:keywords", "@container": "@list"},
    "knows": {"@id": "schema:knows", "@type": "@id", "@container": "@set"},
    "label": {"@id": "schema:label", "@container": "@language"},
    "byId": {"@id": "schema:items", "@container": ["@id", "@set"]},
    "payload": {"@id": "schema:data", "@type": "@json"},
    "plain": {"@type": "xsd:integer"},
    "parentOf": {"@reverse": "schema:children"},
    "address": {"@id": "schema:address", "@context": {"city": "schema:addressLocality"}},
    "status": {"@id": "schema:status", "@type": "@vocab",
               "@context": {"open": "https://example.com/ns#Open", "shut": "https://example.com/ns#Shut"}}
  }
}"""


class TestJsonLd:
    def test_terms_become_fields_with_iris_as_provenance(self):
        api = _jsonld(CONTEXT)
        assert api.format == "jsonld" and api.paradigm is ApiParadigm.DATA_SCHEMA
        root = _type(api, "Context")
        assert _field(api, "Context", "name").extras["native_id"] == "https://schema.org/name"
        assert _field(api, "Context", "plain").extras["native_id"] == "https://example.com/ns#plain"
        assert _field(api, "Context", "born").extras["jsonld_definition"] == {
            "@id": "schema:birthDate",
            "@type": "xsd:date",
        }
        assert root.extras["jsonld_prefixes"] == {
            "schema": "https://schema.org/",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
        }
        assert root.extras["jsonld_keyword_aliases"] == {"id": "@id"}
        assert root.extras["jsonld_class_terms"] == {"Person": "https://schema.org/Person"}
        assert all(f.type.nullable for f in root.fields), "JSON-LD states no cardinality"

    def test_coercion_and_containers_map_to_types(self):
        api = _jsonld(CONTEXT)
        assert _field(api, "Context", "born").type.name == "date"
        home = _field(api, "Context", "home")
        assert home.type.name == "string" and home.constraints.format == "iri"
        assert _field(api, "Context", "tags").type.item.name == "any"
        assert _field(api, "Context", "tags").extras["jsonld_ordered"] is True
        assert _field(api, "Context", "knows").type.item.name == "string"
        assert _field(api, "Context", "label").type.name == "LanguageMap"
        assert _type(api, "LanguageMap").kind is TypeKind.MAP
        by_id = _type(api, _field(api, "Context", "byId").type.name)
        assert by_id.kind is TypeKind.MAP and by_id.value_type.item is not None
        assert _field(api, "Context", "payload").type.name == "any"
        assert _field(api, "Context", "plain").type.name == "integer"

    def test_scoped_contexts_and_vocab_values(self):
        api = _jsonld(CONTEXT)
        address = _type(api, _field(api, "Context", "address").type.name)
        assert address.kind is TypeKind.RECORD and [f.name for f in address.fields] == ["city"]
        assert address.extras["provenance"] == "synthesized"
        assert _field(api, "Address", "city").extras["native_id"] == "https://schema.org/addressLocality"
        status = _type(api, _field(api, "Context", "status").type.name)
        assert status.kind is TypeKind.ENUM and [v.value for v in status.enum_values] == [
            "https://example.com/ns#Open",
            "https://example.com/ns#Shut",
        ]

    def test_declared_limits(self):
        api = _jsonld(CONTEXT)
        limits = _limits(api, "jsonld")
        assert limits["jsonld.open_vocabulary"] == ["Context"]
        assert limits["jsonld.reverse_property"] == ["Context.parentOf"]
        with_graph = _jsonld('{"@context": {"name": "https://schema.org/name"}, "@graph": [{"name": "x"}]}')
        assert with_graph.extras["jsonld"]["instance_data"] == {"nodes": 1, "types": []}
        assert "jsonld.instance_data" in _limits(with_graph, "jsonld")

    def test_context_arrays_merge_in_order_and_null_resets(self):
        api = _jsonld(
            '{"@context": [{"a": "https://e/a", "b": "https://e/b"}, null, {"c": "https://e/c"}, {"c": "https://e/c2"}]}'
        )
        root = _type(api, "Context")
        assert [f.name for f in root.fields] == ["c"]
        assert root.fields[0].extras["native_id"] == "https://e/c2"

    def test_prefixes_defined_after_use_still_expand(self):
        api = _jsonld('{"@context": {"term": "ex:local", "ex": "https://example.com/ns#"}}')
        assert _field(api, "Context", "term").extras["native_id"] == "https://example.com/ns#local"

    def test_root_record_is_named_after_the_file(self):
        api = _jsonld(CONTEXT, label="02-typical-catalog-context.jsonld")
        assert api.identity.name == "TypicalCatalogContext"

    def test_a_context_fileset_resolves_sibling_contexts(self):
        adapter = JsonLdImportSource()
        fileset = IntakeFileset.from_members(
            {
                "main.jsonld": '{"@context": ["shared.jsonld", {"orderId": "https://e/orderId"}]}',
                "shared.jsonld": '{"@context": {"name": "https://schema.org/name"}}',
            },
            root="main.jsonld",
        )
        api = adapter.normalize(adapter.parse_fileset(fileset))
        assert {f.name for f in _type(api, "Main").fields} == {"name", "orderId"}
        assert api.extras["jsonld"]["resolved_contexts"] == ["shared.jsonld"]

    def test_refusals_carry_their_codes(self):
        adapter = JsonLdImportSource()
        remote = '{"@context": ["https://ctx.example.com/v1", "./gone.jsonld", {"a": "https://e/a"}]}'
        assert _code(adapter.parse, remote, source_label="r.jsonld") == "INPUT_REFERENCE_UNRESOLVED"
        assert _code(adapter.parse, '{"id": "x", "name": "y"}', source_label="d.jsonld") == "INPUT_SEMANTIC_INVALID"
        schema = '{"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "properties": {}}'
        assert _code(adapter.parse, schema, source_label="s.json") == "FORMAT_MISMATCH"
        only_prefixes = '{"@context": {"schema": "https://schema.org/", "id": "@id"}}'
        assert _code(adapter.parse, only_prefixes, source_label="p.jsonld") == "INPUT_SEMANTIC_INVALID"
        assert _code(adapter.parse, '{"@context": {"a": "b"', source_label="t.jsonld") == "INPUT_TRUNCATED"


# ===========================================================================
# Detection, ledger and registry wiring
# ===========================================================================


class TestDetection:
    @pytest.mark.parametrize(
        "text, filename, expected",
        [
            (PREFIXES + "ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ] .", "s.ttl", "shacl"),
            (PREFIXES + "<https://e/o> a owl:Ontology . ex:A a owl:Class .", "o.ttl", "owl"),
            ('{"@context": {"name": "https://schema.org/name"}}', "c.jsonld", "jsonld"),
            (
                '{"@context": {"sh": "http://www.w3.org/ns/shacl#"}, "@type": "sh:NodeShape", "sh:property": {}}',
                "s.jsonld",
                "shacl",
            ),
        ],
    )
    def test_each_format_wins_its_own_documents(self, text, filename, expected):
        best = detect_import_source(DetectionInput(text=text, filename=filename))
        assert best is not None and best[0].key == expected

    def test_a_shapes_graph_that_imports_owl_is_still_shacl(self):
        text = PREFIXES + "<https://e/s> a owl:Ontology . ex:S a sh:NodeShape ; sh:property [ sh:path ex:a ] ."
        assert OwlImportSource().detect(DetectionInput(text=text)).confidence < 0.5
        assert ShaclImportSource().detect(DetectionInput(text=text)).confidence > 0.9

    def test_plain_rdfs_is_detected_as_rdfs(self):
        text = "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n<https://e/A> a rdfs:Class ."
        result = OwlImportSource().detect(DetectionInput(text=text))
        assert result.format == "rdfs" and result.matched

    def test_unrelated_text_is_not_claimed(self):
        for adapter in (ShaclImportSource(), OwlImportSource(), JsonLdImportSource()):
            assert not adapter.detect(DetectionInput(text='{"openapi": "3.1.0"}', filename="a.json")).matched


class TestWiring:
    @pytest.mark.parametrize("key", ["shacl", "owl", "jsonld"])
    def test_adapters_are_registered_and_declared(self, key):
        adapter = get_import_source(key)
        assert adapter.paradigm is ApiParadigm.DATA_SCHEMA
        assert capability_for(key) is not None
        assert version_coverage_for(key).reads
        assert key in INFERENCE_BASED_ADAPTERS

    def test_ledger_rows_grade_partial_and_dropped_limits(self):
        rows = {row.source_construct: row for row in _linked_data_capability_rows(_owl(ONTOLOGY))}
        assert rows["owl.open_world"].coverage.value == "not-parsed-by-adapter"
        assert rows["owl.individual_enumeration"].coverage.value == "partially-mapped"
        assert "Status" in rows["owl.individual_enumeration"].detail
        assert all(row.document_scoped for row in rows.values())
        jsonld_rows = {row.source_construct for row in _linked_data_capability_rows(_jsonld(CONTEXT))}
        assert {"jsonld.open_vocabulary", "jsonld.reverse_property"} <= jsonld_rows
        assert _linked_data_capability_rows(_shacl(SHAPES)) == [], "a shapes graph with no limits has no rows"
