/**
 * Unit tests for the catalog source-format → Monaco language mapping (MFI-25.4, #4089).
 *
 * The mapping is a pure function so it can be pinned without rendering Monaco: known formats resolve
 * (through the alias/version-tolerant registry) to their Monaco language, JSON-or-YAML formats are
 * refined by a byte sample, and everything unknown degrades to `plaintext`.
 */

import { monacoLanguageForCatalogFormat } from '../src/app/utils/catalog-source-language';

describe('monacoLanguageForCatalogFormat', () => {
  it('maps unambiguous formats to their Monaco language', () => {
    expect(monacoLanguageForCatalogFormat('graphql')).toBe('graphql');
    expect(monacoLanguageForCatalogFormat('grpc')).toBe('protobuf');
    expect(monacoLanguageForCatalogFormat('protobuf')).toBe('protobuf');
    expect(monacoLanguageForCatalogFormat('jsonschema')).toBe('json');
    expect(monacoLanguageForCatalogFormat('wsdl')).toBe('xml');
    expect(monacoLanguageForCatalogFormat('apiblueprint')).toBe('markdown');
    expect(monacoLanguageForCatalogFormat('typespec')).toBe('typescript');
  });

  it('resolves aliases and versioned variants through the registry', () => {
    expect(monacoLanguageForCatalogFormat('OpenAPI 3.1')).toBe('yaml');
    expect(monacoLanguageForCatalogFormat('openapi-3.0')).toBe('yaml');
    expect(monacoLanguageForCatalogFormat('proto3')).toBe('protobuf');
    expect(monacoLanguageForCatalogFormat('gql')).toBe('graphql');
  });

  it('defaults JSON-or-YAML formats to yaml when no sample is given', () => {
    expect(monacoLanguageForCatalogFormat('openapi')).toBe('yaml');
    expect(monacoLanguageForCatalogFormat('asyncapi')).toBe('yaml');
    expect(monacoLanguageForCatalogFormat('arazzo')).toBe('yaml');
  });

  it('refines JSON-or-YAML formats to json/xml by sniffing the sample bytes', () => {
    expect(monacoLanguageForCatalogFormat('openapi', '  {\n  "openapi": "3.1.0"\n}')).toBe('json');
    expect(monacoLanguageForCatalogFormat('openapi', 'openapi: 3.1.0\ninfo:')).toBe('yaml');
    expect(monacoLanguageForCatalogFormat('asyncapi', '[1, 2]')).toBe('json');
    // A sample that opens with an angle bracket reads as XML even for a YAML-default format.
    expect(monacoLanguageForCatalogFormat('openapi', '<?xml version="1.0"?>')).toBe('xml');
  });

  it('never lets a sample override a format with a fixed grammar', () => {
    // protobuf stays protobuf even if the (nonsensical) sample looks like JSON.
    expect(monacoLanguageForCatalogFormat('protobuf', '{ "not": "proto" }')).toBe('protobuf');
    expect(monacoLanguageForCatalogFormat('graphql', '{ query }')).toBe('graphql');
  });

  it('degrades unknown or absent formats to plaintext, sniffing when possible', () => {
    expect(monacoLanguageForCatalogFormat(null)).toBe('plaintext');
    expect(monacoLanguageForCatalogFormat('')).toBe('plaintext');
    expect(monacoLanguageForCatalogFormat('totally-made-up')).toBe('plaintext');
    // An unknown format still gets JSON/XML when the bytes are conclusive.
    expect(monacoLanguageForCatalogFormat('totally-made-up', '{ "a": 1 }')).toBe('json');
    expect(monacoLanguageForCatalogFormat('totally-made-up', '<root/>')).toBe('xml');
  });

  it('maps grammar-less formats to plaintext so the raw text still renders', () => {
    expect(monacoLanguageForCatalogFormat('thrift')).toBe('plaintext');
    expect(monacoLanguageForCatalogFormat('asn1')).toBe('plaintext');
    expect(monacoLanguageForCatalogFormat('cobolcopybook')).toBe('plaintext');
  });
});
