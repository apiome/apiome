/**
 * Unit tests for the OData service-root helpers of the catalog URL intake (MFI-11.6, #3781).
 *
 * `odataMetadataUrl` must follow the same rules as the CLI's `odata_metadata_url` and the REST
 * adapter's `service_urls`; `odataMetadataUrlForServiceDocument` must recognise a service document of
 * every OData version and nothing else.
 */

import { odataMetadataUrl, odataMetadataUrlForServiceDocument } from '../src/app/utils/odata-service-url';

describe('odataMetadataUrl', () => {
  it.each([
    ['https://h/odata/trippin', 'https://h/odata/trippin/$metadata'],
    ['https://h/odata/trippin/', 'https://h/odata/trippin/$metadata'],
    ['https://h/odata/trippin/$metadata', 'https://h/odata/trippin/$metadata'],
    ['  https://h/odata/trippin/#top ', 'https://h/odata/trippin/$metadata'],
    ['HTTPS://h/sap/ZBP_SRV/?sap-client=100', 'https://h/sap/ZBP_SRV/$metadata?sap-client=100'],
  ])('%s → %s', (url, expected) => {
    expect(odataMetadataUrl(url)).toBe(expected);
  });

  it.each(['', 'not a url', 'ftp://h/svc', '/relative/svc'])('refuses %p', (url) => {
    expect(odataMetadataUrl(url)).toBeNull();
  });
});

describe('odataMetadataUrlForServiceDocument', () => {
  const ROOT = 'https://h/odata/svc/';
  const METADATA = 'https://h/odata/svc/$metadata';

  it('recognises a v4 JSON service document', () => {
    const doc = JSON.stringify({
      '@odata.context': 'https://h/odata/svc/$metadata',
      value: [{ name: 'People', kind: 'EntitySet', url: 'People' }],
    });
    expect(odataMetadataUrlForServiceDocument(ROOT, doc)).toBe(METADATA);
  });

  it('recognises a v3 JSON light service document', () => {
    const doc = JSON.stringify({ 'odata.metadata': 'https://h/odata/svc/$metadata', value: [{ name: 'A', url: 'A' }] });
    expect(odataMetadataUrlForServiceDocument(ROOT, doc)).toBe(METADATA);
  });

  it('recognises a v2 verbose JSON service document and keeps the query string', () => {
    const doc = JSON.stringify({ d: { EntitySets: ['BusinessPartnerSet', 'ProductSet'] } });
    expect(odataMetadataUrlForServiceDocument('https://sap/sap/opu/odata/sap/ZBP_SRV/?sap-client=100', doc)).toBe(
      'https://sap/sap/opu/odata/sap/ZBP_SRV/$metadata?sap-client=100',
    );
  });

  it('recognises an AtomPub (v2 / v3 XML) service document', () => {
    const doc =
      '<?xml version="1.0" encoding="utf-8"?>\n' +
      '<service xml:base="https://h/odata/svc/" xmlns="http://www.w3.org/2007/app" ' +
      'xmlns:atom="http://www.w3.org/2005/Atom"><workspace><atom:title>Default</atom:title>' +
      '<collection href="Products"><atom:title>Products</atom:title></collection></workspace></service>';
    expect(odataMetadataUrlForServiceDocument(ROOT, doc)).toBe(METADATA);
  });

  it('recognises a prefixed AtomPub root', () => {
    const doc = '<app:service xmlns:app="http://www.w3.org/2007/app"><app:workspace/></app:service>';
    expect(odataMetadataUrlForServiceDocument(ROOT, doc)).toBe(METADATA);
  });

  it.each([
    ['EDMX metadata', '<edmx:Edmx xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx" Version="4.0"/>'],
    ['CSDL JSON metadata', JSON.stringify({ $Version: '4.0', $EntityContainer: 'Shop.Svc' })],
    ['a bare value array', JSON.stringify({ value: [{ id: 1 }] })],
    ['an OpenAPI document', JSON.stringify({ openapi: '3.1.0', info: { title: 'x', version: '1' } })],
    ['a non-AtomPub service element', '<service xmlns="urn:example"/>'],
    ['YAML', 'openapi: 3.1.0\n'],
    ['malformed JSON', '{"d": '],
    ['empty text', ''],
  ])('ignores %s', (_label, text) => {
    expect(odataMetadataUrlForServiceDocument(ROOT, text)).toBeNull();
  });

  it('does not loop when a $metadata URL answers with a service document', () => {
    const doc = JSON.stringify({ d: { EntitySets: ['A'] } });
    expect(odataMetadataUrlForServiceDocument(METADATA, doc)).toBeNull();
  });
});
