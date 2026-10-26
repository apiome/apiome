"""Tests for RAML resource types and traits in the canonical model — MFI-15.2 (#3800).

Covers :mod:`app.raml_traits` (the resolver both parse paths share), the YAML reader and
the AMF mapper on documents that apply resource types and traits, and what the normalizer
puts in the canonical model. The AMF tests replay output recorded from the real ``amf``
5.7.1 CLI (``tests/fixtures/raml_amf/recordings/library.json`` for the
``tests/fixtures/raml_amf/library`` set, ``resource-types-and-traits.json`` for the corpus
example ``04-resource-types-and-traits.raml``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest
import yaml

from app import raml_amf
from app.canonical_model import MessageRole, ParameterLocation
from app.raml_amf import parse_raml_set_with_amf
from app.raml_normalizer import RamlNormalizer
from app.raml_parser import RamlParseError, parse_raml
from app.raml_traits import (
    AppliedReuse,
    RamlReuseTooLargeError,
    applied_reuse_from_text,
    declared_names,
    pluralize,
    resolve_resource_types_and_traits,
    singularize,
)
from tests.test_raml_amf import _replay

_LIBRARY_DIR = Path(__file__).resolve().parent / "fixtures" / "raml_amf" / "library"
_CORPUS_EXAMPLE = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/raml/04-resource-types-and-traits.raml"
)


def _library_members() -> Dict[str, str]:
    """The library fixture set's members, path → text."""
    return {
        str(path.relative_to(_LIBRARY_DIR)): path.read_text(encoding="utf-8")
        for path in sorted(_LIBRARY_DIR.rglob("*"))
        if path.is_file()
    }


def _resolve(text: str):
    """Resolve a RAML snippet's resource types and traits."""
    return resolve_resource_types_and_traits(yaml.safe_load(text))


# ===========================================================================
# Parameter functions
# ===========================================================================


@pytest.mark.parametrize(
    "singular, plural",
    [("Book", "Books"), ("category", "categories"), ("box", "boxes"), ("match", "matches"), ("day", "days")],
)
def test_pluralize_and_singularize(singular: str, plural: str):
    assert pluralize(singular) == plural
    assert singularize(plural) == singular


def test_singularize_keeps_words_that_are_not_plural():
    assert singularize("address") == "address"
    assert singularize("data") == "data"


def test_placeholders_take_parameters_and_functions():
    resolved, _ = _resolve(
        """
resourceTypes:
  rt:
    description: <<resourcePathName | !singularize | !uppercase>> at <<resourcePath>>
    get:
      displayName: <<methodName>> <<thing | !uppercamelcase>> <<thing | !lowerhyphencase>>
      description: <<unknown>> stays
/user-accounts/{id}/line_items:
  type: { rt: { thing: lineItem } }
  get: {}
"""
    )
    resource = resolved["/user-accounts/{id}/line_items"]
    assert resource["description"] == "LINE_ITEM at /user-accounts/{id}/line_items"
    assert resource["get"]["displayName"] == "get LineItem line-item"
    assert resource["get"]["description"] == "<<unknown>> stays"


# ===========================================================================
# Resolver
# ===========================================================================


def test_resource_type_methods_merge_and_the_resource_wins():
    resolved, applied = _resolve(
        """
resourceTypes:
  collection:
    description: The <<resourcePathName>> collection.
    get:
      description: List <<resourcePathName>>.
      responses:
        200:
          body:
            type: <<item>>[]
    post?:
      body:
        type: <<item>>
/books:
  type: { collection: { item: Book } }
  description: Our books.
  get:
    responses:
      200:
        description: The page.
"""
    )
    books = resolved["/books"]
    assert "type" not in books
    assert books["description"] == "Our books."
    assert books["get"]["description"] == "List books."
    # Maps merge key by key: the resource's own description and the type's body.
    assert books["get"]["responses"][200] == {"description": "The page.", "body": {"type": "Book[]"}}
    # `post?` applies only when the resource declares `post`.
    assert "post" not in books
    assert applied == {("/books", "get"): AppliedReuse(resource_type="collection", traits=())}


def test_optional_resource_type_method_applies_when_the_resource_declares_it():
    resolved, _ = _resolve(
        """
resourceTypes:
  rt:
    post?:
      body:
        type: Thing
/things:
  type: rt
  post:
"""
    )
    assert resolved["/things"]["post"] == {"body": {"type": "Thing"}}


def test_traits_apply_to_methods_in_precedence_order():
    resolved, applied = _resolve(
        """
traits:
  paged:
    queryParameters:
      page: { type: integer, description: "<<methodName>> page" }
  secured:
    headers:
      Authorization: string
    queryParameters:
      page: { type: string, description: secured page }
  listing:
    queryParameters:
      sort: string
resourceTypes:
  collection:
    is: [listing]
    get:
      is: [paged]
/items:
  type: collection
  is: [secured]
  get:
    is: [paged]
    description: Own.
  delete:
"""
    )
    get = resolved["/items"]["get"]
    # The method's own trait is listed (and wins) before the resource's.
    assert applied[("/items", "get")].traits == ("paged", "secured", "listing")
    assert get["queryParameters"]["page"] == {"type": "integer", "description": "get page"}
    assert get["queryParameters"]["sort"] == "string"
    assert get["headers"] == {"Authorization": "string"}
    assert "is" not in get
    # A method with no body still receives the resource's traits.
    assert resolved["/items"]["delete"]["headers"] == {"Authorization": "string"}
    assert applied[("/items", "delete")] == AppliedReuse(resource_type="collection", traits=("secured", "listing"))


def test_trait_parameters_and_reserved_names():
    resolved, applied = _resolve(
        """
traits:
  filterable:
    queryParameters:
      <<field>>:
        description: Filter on <<field>> of <<resourcePathName>>.
/books/{isbn}/reviews:
  get:
    is: [{ filterable: { field: rating } }]
"""
    )
    params = resolved["/books/{isbn}/reviews"]["get"]["queryParameters"]
    assert params == {"rating": {"description": "Filter on rating of reviews."}}
    assert applied[("/books/{isbn}/reviews", "get")].traits == ("filterable",)


def test_resource_types_inherit_from_resource_types():
    resolved, applied = _resolve(
        """
traits:
  audited:
    headers:
      X-Audit: string
resourceTypes:
  base:
    is: [audited]
    get:
      responses:
        500:
          description: Server error.
  collection:
    type: base
    get:
      description: List.
/things:
  type: collection
  get:
"""
    )
    get = resolved["/things"]["get"]
    assert get["description"] == "List."
    assert get["responses"] == {500: {"description": "Server error."}}
    assert get["headers"] == {"X-Audit": "string"}
    assert applied[("/things", "get")] == AppliedReuse(resource_type="collection", traits=("audited",))


def test_a_parent_resource_type_receives_the_parameters_passed_on():
    resolved, _ = _resolve(
        """
resourceTypes:
  base:
    get:
      responses:
        200:
          body:
            type: <<item>>
  member:
    type: { base: { item: <<item>> } }
/books/{isbn}:
  type: { member: { item: Book } }
  get:
"""
    )
    assert resolved["/books/{isbn}"]["get"]["responses"][200] == {"body": {"type": "Book"}}


def test_a_resource_type_cycle_does_not_loop():
    resolved, applied = _resolve(
        """
resourceTypes:
  a: { type: b, get: { description: A } }
  b: { type: a, post: { description: B } }
/x:
  type: a
  get:
"""
    )
    assert resolved["/x"]["get"] == {"description": "A"}
    assert applied[("/x", "get")].resource_type == "a"


def test_names_declared_elsewhere_are_recorded_but_not_merged():
    resolved, applied = _resolve(
        """
/x:
  type: lib.collection
  is: [lib.secured]
  get:
    description: Mine.
"""
    )
    assert resolved["/x"]["get"] == {"description": "Mine."}
    assert applied[("/x", "get")] == AppliedReuse(resource_type="lib.collection", traits=("lib.secured",))


def test_nested_resources_are_resolved_with_their_full_path():
    resolved, applied = _resolve(
        """
resourceTypes:
  member:
    get:
      description: One of <<resourcePathName>> at <<resourcePath>>.
/books:
  /{isbn}:
    type: member
    get:
"""
    )
    assert resolved["/books"]["/{isbn}"]["get"]["description"] == "One of books at /books/{isbn}."
    assert ("/books/{isbn}", "get") in applied


_ANCHOR_BOMB = """#%RAML 1.0
title: Bomb
traits:
  t:
    description: &a [x, x, x, x, x, x, x, x, x, x]
    headers:
      b: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a, *a]
      c: &c [*b, *b, *b, *b, *b, *b, *b, *b, *b, *b]
      d: &d [*c, *c, *c, *c, *c, *c, *c, *c, *c, *c]
      e: &e [*d, *d, *d, *d, *d, *d, *d, *d, *d, *d]
      f: [*e, *e, *e, *e, *e, *e, *e, *e, *e, *e]
/a:
  get:
    is: [t]
"""


def test_anchor_expansion_past_the_limit_is_refused():
    with pytest.raises(RamlReuseTooLargeError):
        resolve_resource_types_and_traits(yaml.safe_load(_ANCHOR_BOMB))
    with pytest.raises(RamlParseError, match="more than"):
        parse_raml(_ANCHOR_BOMB)
    # On the AMF path the provenance is simply left out.
    assert applied_reuse_from_text(_ANCHOR_BOMB) == {}


def test_declared_names_reads_raml_10_maps_and_raml_08_lists():
    assert declared_names({"traits": {"a": {}, "b": {}}}, "traits") == ("a", "b")
    assert declared_names({"traits": [{"a": {}}, {"b": {}}]}, "traits") == ("a", "b")
    assert declared_names({"resourceTypes": "oops"}, "resourceTypes") == ()


def test_applied_reuse_from_text_tolerates_includes_and_bad_input():
    text = "#%RAML 1.0\ntitle: T\nresourceTypes:\n  rt: !include rt.raml\n/a:\n  type: rt\n  get:\n"
    assert applied_reuse_from_text(text) == {("/a", "get"): AppliedReuse(resource_type="rt", traits=())}
    assert applied_reuse_from_text("a: [unclosed") == {}
    assert applied_reuse_from_text("- just a list") == {}


# ===========================================================================
# YAML reader (no AMF)
# ===========================================================================


def test_yaml_reader_resolves_resource_types_and_traits():
    doc = parse_raml(_CORPUS_EXAMPLE.read_text(encoding="utf-8"))
    assert doc.traits == ("paged",)
    assert doc.resource_types == ("collection",)
    ops = {(o.method, o.path): o for o in doc.operations}
    listing = ops[("get", "/devices")]
    assert [(p.name, p.location, p.type_expr, p.required) for p in listing.parameters] == [
        ("page", "query", "integer", False),
        ("pageSize", "query", "integer", False),
    ]
    assert (listing.resource_type, listing.traits) == ("collection", ("paged",))
    assert ops[("post", "/devices")].traits == ()
    assert ops[("get", "/devices/{deviceId}")].untyped_response_statuses == ("404",)


def test_yaml_reader_reads_headers_and_untyped_responses():
    doc = parse_raml(
        """#%RAML 1.0
title: T
traits:
  secured:
    headers:
      Authorization:
        type: string
        description: Bearer token.
/things/{id}:
  delete:
    is: [secured]
    responses:
      204:
      404:
        description: Not found.
"""
    )
    (op,) = doc.operations
    assert [(p.name, p.location, p.required, p.description) for p in op.parameters] == [
        ("Authorization", "header", True, "Bearer token.")
    ]
    assert op.response_types == ()
    assert op.untyped_response_statuses == ("204", "404")


# ===========================================================================
# AMF mapper (recorded AMF output)
# ===========================================================================


def test_amf_operations_carry_what_resource_types_and_traits_add(monkeypatch):
    _replay(monkeypatch, "library")
    doc = parse_raml_set_with_amf(_library_members(), "api.raml")
    ops = {(o.method, o.path): o for o in doc.operations}
    assert set(ops) == {("get", "/books"), ("post", "/books"), ("get", "/books/{isbn}"), ("delete", "/books/{isbn}")}

    listing = ops[("get", "/books")]
    assert listing.description == "List books."
    assert sorted((p.name, p.location, p.type_expr, p.required) for p in listing.parameters) == [
        ("Authorization", "header", "string", True),
        ("page", "query", "integer", False),
    ]
    assert listing.response_types == (("200", "Book"), ("401", "Error"))
    assert (listing.resource_type, listing.traits) == ("collection", ("secured", "paging.pageable"))

    add = ops[("post", "/books")]
    assert add.description == "Add one of the books."
    assert add.request_type == "Book"
    assert add.response_types == (("201", "Book"), ("401", "Error"))

    get = ops[("get", "/books/{isbn}")]
    assert get.description == "Get one of the Books."
    assert (get.resource_type, get.traits) == ("member", ())
    assert get.response_types == (("200", "Book"), ("404", "Error"))

    remove = ops[("delete", "/books/{isbn}")]
    assert remove.untyped_response_statuses == ("204",)
    assert remove.response_types == (("401", "Error"),)
    assert {(p.name, p.location) for p in remove.parameters} == {("isbn", "path"), ("Authorization", "header")}


def test_amf_declared_traits_and_resource_types_include_libraries(monkeypatch):
    _replay(monkeypatch, "library")
    doc = parse_raml_set_with_amf(_library_members(), "api.raml")
    assert doc.traits == ("secured", "paging.pageable")
    assert doc.resource_types == ("collection", "member")
    # Traits and resource types are not data types.
    assert [t.name for t in doc.types] == ["Book", "Error"]


def test_yaml_reader_and_amf_agree_on_resolved_operations(monkeypatch):
    text = _CORPUS_EXAMPLE.read_text(encoding="utf-8")
    from_yaml = parse_raml(text)
    _replay(monkeypatch, "resource-types-and-traits")
    from_amf = parse_raml_set_with_amf({"api.raml": text}, "api.raml")

    def _shape(doc):
        return {
            (o.method, o.path): (
                sorted((p.name, p.location, p.type_expr, p.required) for p in o.parameters),
                o.request_type,
                sorted(o.response_types),
                o.untyped_response_statuses,
                o.resource_type,
                o.traits,
            )
            for o in doc.operations
        }

    assert _shape(from_yaml) == _shape(from_amf)
    assert (from_yaml.traits, from_yaml.resource_types) == (from_amf.traits, from_amf.resource_types)


@pytest.mark.skipif(not raml_amf.amf_available(), reason="AMF (amf) is not installed in this runtime")
def test_live_amf_matches_the_library_recording(monkeypatch):
    live = parse_raml_set_with_amf(_library_members(), "api.raml")
    _replay(monkeypatch, "library")
    replayed = parse_raml_set_with_amf(_library_members(), "api.raml")
    assert live.operations == replayed.operations
    assert (live.traits, live.resource_types) == (replayed.traits, replayed.resource_types)
    assert live.model_sha256 == replayed.model_sha256


# ===========================================================================
# Canonical model
# ===========================================================================


def test_canonical_model_records_resolution_and_provenance(monkeypatch):
    _replay(monkeypatch, "library")
    api = RamlNormalizer().normalize(parse_raml_set_with_amf(_library_members(), "api.raml"))
    assert api.extras["raml_traits"] == ["secured", "paging.pageable"]
    assert api.extras["raml_resource_types"] == ["collection", "member"]

    ops = {op.key: op for op in api.services[0].operations}
    listing = ops["GET /books"]
    assert listing.extras == {"raml_resource_type": "collection", "raml_traits": ["secured", "paging.pageable"]}
    header = next(p for p in listing.parameters if p.name == "Authorization")
    assert header.location is ParameterLocation.HEADER
    assert header.required is True

    remove = ops["DELETE /books/{isbn}"]
    empty = next(m for m in remove.messages if m.extras.get("http_status") == "204")
    assert empty.role is MessageRole.RESPONSE
    assert empty.payload is None
    assert empty.key == "DELETE /books/{isbn}#response.204"
    # The status is the message's own, so an OpenAPI export keeps every response.
    assert {m.status_code for m in remove.messages} == {"204", "401"}


def test_canonical_model_omits_provenance_when_nothing_is_applied():
    api = RamlNormalizer().normalize(parse_raml("#%RAML 1.0\ntitle: T\n/a:\n  get:\n"))
    assert api.services[0].operations[0].extras == {}
    assert "raml_traits" not in api.extras
    assert "raml_resource_types" not in api.extras
