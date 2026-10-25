/**
 * Client-side format detection does not read an OpenAPI document as Thrift, Protobuf or GraphQL
 * because of words in its descriptions (2026-10-25: `apiome-rest/openapi.yaml` imported as
 * Thrift through the project Import wizard). Twin of
 * `apiome-rest/tests/test_import_detect_structured_documents.py`.
 */
import { looksLikeStructuredDocument } from '@/app/utils/document-markers';
import { isGraphQL } from '@/app/utils/graphql-converter';
import { analyzeSpecification } from '@/app/utils/openapi-analyzer';
import { isProtobuf } from '@/app/utils/protobuf-converter';
import { isThrift } from '@/app/utils/thrift-converter';

const HEAD = 'openapi: 3.1.0\ninfo:\n  title: Orders\n  version: 1.0.0\n';

describe('looksLikeStructuredDocument', () => {
  it.each([
    [HEAD, true],
    ['{"openapi": "3.1.0"}', true],
    ['[\n  {"a": 1}\n]', true],
    ['# generated\n---\nopenapi: 3.0.3\n', true],
    ['﻿swagger: "2.0"\n', true],
    ['namespace java com.acme\n', false],
    ['include "shared.thrift"\n', false],
    ['const map<string,string> M = {"a": "b"}\n', false],
    ['syntax = "proto3";\n', false],
    ['type Query {\n  ping: String\n}\n', false],
    ['{1:F01EXAMPLNL2AXXXX2381000050}{2:I103EXAMPUS44XXXXN}\n', false],
    ['', false],
  ])('%j → %s', (text, expected) => {
    expect(looksLikeStructuredDocument(text)).toBe(expected);
  });
});

describe('IDL checks ignore words inside an OpenAPI document', () => {
  // The reported trigger: a folded description line that begins with "namespace".
  const reported =
    HEAD +
    'paths: {}\ncomponents:\n  schemas:\n    Ns:\n      description: >-\n' +
    '        Each tenant owns one\n        namespace to its primitives); only base URI\n';
  const prose = [
    reported,
    HEAD + 'paths: {}\n# service Orders { rpc Get() }\n',
    HEAD + 'paths: {}\n# struct Order { id }\n',
    HEAD + "  description: 'typedef id; message Order { id }'\npaths: {}\n",
    HEAD + 'paths: {}\n# include "shared.thrift"\n',
  ];

  it.each(prose)('is not Thrift, Protobuf or GraphQL (%#)', (text) => {
    expect(isThrift(text)).toBe(false);
    expect(isProtobuf(text)).toBe(false);
    expect(isGraphQL(text)).toBe(false);
  });

  it('is analyzed as OpenAPI by the Import wizard', async () => {
    const result = await analyzeSpecification(reported, 'openapi.yaml');
    expect(result.format).toBe('openapi');
  });
});

describe('real IDL sources are still recognised', () => {
  it('Thrift', () => {
    expect(isThrift('namespace java com.acme.orders\nstruct Order {\n  1: string id\n}\n')).toBe(true);
    expect(isThrift('namespace py acme.orders\n')).toBe(true);
    expect(isThrift('namespace to its primitives); only base URI\n')).toBe(false);
  });

  it('Protobuf and GraphQL', () => {
    expect(isProtobuf('syntax = "proto3";\nmessage Order { string id = 1; }\n')).toBe(true);
    expect(isProtobuf('message Order {\n  string id = 1;\n}\n')).toBe(true);
    expect(isGraphQL('type Query {\n  ping: String\n}\n')).toBe(true);
  });
});
