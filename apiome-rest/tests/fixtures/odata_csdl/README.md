# OData CSDL fixtures (MFI-11.1, #3776)

`oasis-products-categories.xml` and `oasis-products-categories.json` are the "Products and
Categories" example (section 16.1) of the OASIS OData CSDL XML 4.01 and CSDL JSON 4.01
specifications, extracted from:

- https://docs.oasis-open.org/odata/odata-csdl-xml/v4.01/os/odata-csdl-xml-v4.01-os.html
- https://docs.oasis-open.org/odata/odata-csdl-json/v4.01/os/odata-csdl-json-v4.01-os.html

Copyright © OASIS Open 2020. All Rights Reserved. Distributed under the OASIS IPR Policy
(https://www.oasis-open.org/policies-guidelines/ipr/).

The two published examples differ in a few places the conversion cannot (and should not)
reconcile: the JSON version gives the schema the alias `self` and the `@Core.DefaultNamespace`
annotation and references the vocabularies' `.json` URLs, and its `Product/ID` omits the
`Edm.Int32` type the XML version declares. `tests/test_odata_csdl_json.py` lists them.
