/**
 * Unit tests for the export-target → Monaco language / extension / filename mapping (MFX-9.4, #3869).
 *
 * The mappings are pure functions so they can be pinned without rendering Monaco: an emitter id
 * resolves (version-tolerant) to its canonical serialization, a byte sample refines JSON-or-YAML
 * targets, and everything unknown degrades to `plaintext` / `export.txt`.
 */

import {
  downloadFileNameForExportTarget,
  fileExtensionForExportTarget,
  monacoLanguageForArtifact,
  monacoLanguageForExportTarget,
} from '../src/app/utils/export-target-language';

describe('monacoLanguageForExportTarget', () => {
  it('defaults known targets to their canonical JSON serialization', () => {
    expect(monacoLanguageForExportTarget('openapi')).toBe('json');
    expect(monacoLanguageForExportTarget('swagger')).toBe('json');
    expect(monacoLanguageForExportTarget('asyncapi')).toBe('json');
    expect(monacoLanguageForExportTarget('protobuf')).toBe('protobuf');
    expect(monacoLanguageForExportTarget('grpc')).toBe('protobuf');
    expect(monacoLanguageForExportTarget('graphql')).toBe('graphql');
    expect(monacoLanguageForExportTarget('gql')).toBe('graphql');
    expect(monacoLanguageForExportTarget('avro')).toBe('json');
    expect(monacoLanguageForExportTarget('asn1')).toBe('plaintext');
    expect(monacoLanguageForExportTarget('asn')).toBe('plaintext');
    expect(monacoLanguageForExportTarget('edix12')).toBe('plaintext');
    expect(monacoLanguageForExportTarget('oncrpc')).toBe('plaintext');
    expect(monacoLanguageForExportTarget('sunrpc')).toBe('plaintext');
    expect(monacoLanguageForExportTarget('x12')).toBe('plaintext');
    expect(monacoLanguageForExportTarget('avsc')).toBe('json');
  });

  it('collapses version/variant suffixes to the base target id', () => {
    expect(monacoLanguageForExportTarget('openapi-3.1')).toBe('json');
    expect(monacoLanguageForExportTarget('openapi-3.0')).toBe('json');
    expect(monacoLanguageForExportTarget('swagger-2.0')).toBe('json');
    expect(monacoLanguageForExportTarget('OpenAPI-3.1')).toBe('json');
    expect(monacoLanguageForExportTarget('asyncapi-3')).toBe('json');
    expect(monacoLanguageForExportTarget('AsyncAPI-3')).toBe('json');
    expect(monacoLanguageForExportTarget('proto3')).toBe('protobuf');
    expect(monacoLanguageForExportTarget('proto')).toBe('protobuf');
    expect(monacoLanguageForExportTarget('Proto3')).toBe('protobuf');
    expect(monacoLanguageForExportTarget('sdl')).toBe('graphql');
    expect(monacoLanguageForExportTarget('GraphQL')).toBe('graphql');
    expect(monacoLanguageForExportTarget('avsc')).toBe('json');
    expect(monacoLanguageForExportTarget('Avro')).toBe('json');
  });

  it('refines a JSON-or-YAML target from the emitted bytes', () => {
    expect(monacoLanguageForExportTarget('openapi', '{\n  "openapi": "3.1.0"\n}')).toBe('json');
    expect(monacoLanguageForExportTarget('openapi', 'openapi: 3.1.0\ninfo:')).toBe('yaml');
    expect(monacoLanguageForExportTarget('openapi', '---\nopenapi: 3.1.0')).toBe('yaml');
    expect(monacoLanguageForExportTarget('openapi', '<?xml version="1.0"?>')).toBe('xml');
    // AsyncAPI is serialization-variable too: JSON by default, YAML when the bytes say so.
    expect(monacoLanguageForExportTarget('asyncapi-3', '{\n  "asyncapi": "3.1.0"\n}')).toBe('json');
    expect(monacoLanguageForExportTarget('asyncapi-3', 'asyncapi: 3.1.0\ninfo:')).toBe('yaml');
  });

  it('maps the no-op sample emitter to plaintext', () => {
    expect(monacoLanguageForExportTarget('sample')).toBe('plaintext');
  });

  it('degrades unknown or absent targets to plaintext, sniffing when possible', () => {
    expect(monacoLanguageForExportTarget(null)).toBe('plaintext');
    expect(monacoLanguageForExportTarget('')).toBe('plaintext');
    expect(monacoLanguageForExportTarget('totally-made-up')).toBe('plaintext');
    expect(monacoLanguageForExportTarget('totally-made-up', '{ "a": 1 }')).toBe('json');
    expect(monacoLanguageForExportTarget('totally-made-up', '<root/>')).toBe('xml');
  });
});

describe('fileExtensionForExportTarget', () => {
  it('defaults known targets to .json and refines to .yaml from a sample', () => {
    expect(fileExtensionForExportTarget('openapi')).toBe('.json');
    expect(fileExtensionForExportTarget('openapi-3.1')).toBe('.json');
    expect(fileExtensionForExportTarget('openapi', 'openapi: 3.1.0')).toBe('.yaml');
    expect(fileExtensionForExportTarget('protobuf')).toBe('.proto');
    expect(fileExtensionForExportTarget('grpc')).toBe('.proto');
    expect(fileExtensionForExportTarget('proto3')).toBe('.proto');
    expect(fileExtensionForExportTarget('graphql')).toBe('.graphql');
    expect(fileExtensionForExportTarget('gql')).toBe('.graphql');
    expect(fileExtensionForExportTarget('avro')).toBe('.avsc');
    expect(fileExtensionForExportTarget('avsc')).toBe('.avsc');
    expect(fileExtensionForExportTarget('asn1')).toBe('.asn1');
    expect(fileExtensionForExportTarget('asn')).toBe('.asn1');
    expect(fileExtensionForExportTarget('edix12')).toBe('.edi');
    expect(fileExtensionForExportTarget('oncrpc')).toBe('.x');
    expect(fileExtensionForExportTarget('sunrpc')).toBe('.x');
    expect(fileExtensionForExportTarget('x12')).toBe('.edi');
    expect(fileExtensionForExportTarget('x12')).toBe('.edi');
    expect(fileExtensionForExportTarget('sdl')).toBe('.graphql');
  });

  it('falls back to .txt for unrecognised targets', () => {
    expect(fileExtensionForExportTarget('totally-made-up')).toBe('.txt');
    expect(fileExtensionForExportTarget(null)).toBe('.txt');
  });
});

describe('downloadFileNameForExportTarget', () => {
  it('names the artifact from the target id and serialization', () => {
    expect(downloadFileNameForExportTarget('openapi')).toBe('openapi.json');
    expect(downloadFileNameForExportTarget('openapi-3.1')).toBe('openapi.json');
    expect(downloadFileNameForExportTarget('openapi', 'openapi: 3.1.0')).toBe('openapi.yaml');
    expect(downloadFileNameForExportTarget('swagger-2.0')).toBe('swagger.json');
    expect(downloadFileNameForExportTarget('asyncapi-3')).toBe('asyncapi.json');
    expect(downloadFileNameForExportTarget('asyncapi-3', 'asyncapi: 3.1.0')).toBe('asyncapi.yaml');
    expect(downloadFileNameForExportTarget('protobuf')).toBe('api.proto');
    expect(downloadFileNameForExportTarget('grpc')).toBe('api.proto');
    expect(downloadFileNameForExportTarget('proto3')).toBe('api.proto');
    expect(downloadFileNameForExportTarget('graphql')).toBe('schema.graphql');
    expect(downloadFileNameForExportTarget('gql')).toBe('schema.graphql');
    expect(downloadFileNameForExportTarget('sdl')).toBe('schema.graphql');
    expect(downloadFileNameForExportTarget('avro')).toBe('schema.avsc');
    expect(downloadFileNameForExportTarget('avsc')).toBe('schema.avsc');
    expect(downloadFileNameForExportTarget('asn1')).toBe('schema.asn1');
    expect(downloadFileNameForExportTarget('edix12')).toBe('interchange.edi');
    expect(downloadFileNameForExportTarget('oncrpc')).toBe('program.x');
  });

  it('falls back to export.txt for unrecognised targets', () => {
    expect(downloadFileNameForExportTarget('totally-made-up')).toBe('export.txt');
  });
});

describe('monacoLanguageForArtifact (registry-driven, MFX-43.1)', () => {
  it('trusts a known fixed-serialization emitter over the artifact hints', () => {
    // protobuf/graphql/avro are authoritative — the emitter, not the bytes, decides.
    expect(monacoLanguageForArtifact({ targetFormat: 'protobuf' })).toBe('protobuf');
    expect(monacoLanguageForArtifact({ targetFormat: 'grpc', mediaType: 'text/plain' })).toBe('protobuf');
    expect(monacoLanguageForArtifact({ targetFormat: 'graphql', filename: 'schema.txt' })).toBe('graphql');
    expect(monacoLanguageForArtifact({ targetFormat: 'avro' })).toBe('json');
  });

  it('decides a JSON-or-YAML emitter from bytes, then media type, then filename', () => {
    // Bytes are truth.
    expect(monacoLanguageForArtifact({ targetFormat: 'openapi', sample: 'openapi: 3.1.0\ninfo:' })).toBe('yaml');
    expect(monacoLanguageForArtifact({ targetFormat: 'openapi', sample: '{ "openapi": "3.1.0" }' })).toBe('json');
    // No conclusive bytes: fall to the media type.
    expect(
      monacoLanguageForArtifact({ targetFormat: 'asyncapi', mediaType: 'application/yaml' }),
    ).toBe('yaml');
    // No bytes, no media type: fall to the filename.
    expect(
      monacoLanguageForArtifact({ targetFormat: 'openapi', filename: 'openapi.yaml' }),
    ).toBe('yaml');
    // Nothing to refine with: the canonical JSON default.
    expect(monacoLanguageForArtifact({ targetFormat: 'openapi' })).toBe('json');
  });

  it('types an unknown emitter from its media type', () => {
    expect(monacoLanguageForArtifact({ mediaType: 'application/graphql' })).toBe('graphql');
    expect(monacoLanguageForArtifact({ mediaType: 'application/x-protobuf' })).toBe('protobuf');
    expect(monacoLanguageForArtifact({ mediaType: 'application/schema+json' })).toBe('json');
    expect(monacoLanguageForArtifact({ mediaType: 'application/wsdl+xml' })).toBe('xml');
    expect(monacoLanguageForArtifact({ mediaType: 'text/markdown; charset=utf-8' })).toBe('markdown');
    expect(monacoLanguageForArtifact({ mediaType: 'application/sql' })).toBe('sql');
  });

  it('types an unknown emitter from its filename extension (the ~20-language registry)', () => {
    expect(monacoLanguageForArtifact({ filename: 'api.proto' })).toBe('protobuf');
    expect(monacoLanguageForArtifact({ filename: 'schema.graphql' })).toBe('graphql');
    expect(monacoLanguageForArtifact({ filename: 'schema.gql' })).toBe('graphql');
    expect(monacoLanguageForArtifact({ filename: 'service.wsdl' })).toBe('xml');
    expect(monacoLanguageForArtifact({ filename: 'types.xsd' })).toBe('xml');
    expect(monacoLanguageForArtifact({ filename: 'schema.avsc' })).toBe('json');
    expect(monacoLanguageForArtifact({ filename: 'api.raml' })).toBe('yaml');
    expect(monacoLanguageForArtifact({ filename: 'schema.sql' })).toBe('sql');
    expect(monacoLanguageForArtifact({ filename: 'api.apib' })).toBe('markdown');
    expect(monacoLanguageForArtifact({ filename: 'README.md' })).toBe('markdown');
  });

  it('renders grammar-less formats as plaintext rather than mis-highlighting', () => {
    expect(monacoLanguageForArtifact({ filename: 'service.thrift' })).toBe('plaintext');
    expect(monacoLanguageForArtifact({ filename: 'types.asn1' })).toBe('plaintext');
    expect(monacoLanguageForArtifact({ filename: 'record.cpy' })).toBe('plaintext');
    expect(monacoLanguageForArtifact({ filename: 'record.copybook' })).toBe('plaintext');
  });

  it('sniffs the bytes when neither media type nor extension identify the artifact', () => {
    expect(monacoLanguageForArtifact({ filename: 'blob.bin', sample: '{ "a": 1 }' })).toBe('json');
    expect(monacoLanguageForArtifact({ mediaType: 'text/plain', sample: '<root/>' })).toBe('xml');
  });

  it('degrades to plaintext when nothing recognises the artifact', () => {
    expect(monacoLanguageForArtifact({})).toBe('plaintext');
    expect(monacoLanguageForArtifact({ targetFormat: 'totally-made-up' })).toBe('plaintext');
    expect(monacoLanguageForArtifact({ filename: 'mystery.zzz', mediaType: 'text/plain' })).toBe('plaintext');
  });

  it('prefers the media type over a mismatched filename for an unknown emitter', () => {
    // A GraphQL SDL delivered with a .txt name still highlights from its media type.
    expect(
      monacoLanguageForArtifact({ mediaType: 'application/graphql', filename: 'schema.txt' }),
    ).toBe('graphql');
  });
});
