import { describe, expect, it } from '@jest/globals';
import {
  SNIFF_MAX_BYTES,
  STREAMING_SNIFF_THRESHOLD_BYTES,
  detectRepositorySpecFormat,
  type DetectedRepositorySpecFormat,
} from '@lib/repositories/scanner/detect';

interface Fixture {
  format: Exclude<DetectedRepositorySpecFormat, 'unknown_spec'>;
  path: string;
  positive: string;
  negative: string;
}

const FIXTURES: Fixture[] = [
  {
    format: 'openapi_3_0',
    path: 'apis/openapi.yaml',
    positive: 'openapi: 3.0.3\ninfo:\n  title: Store API',
    negative: 'openapi: 4.0.0\ninfo:\n  title: Invalid',
  },
  {
    format: 'openapi_3_1',
    path: 'apis/openapi.json',
    positive: '{"openapi":"3.1.0","info":{"title":"Store API"}}',
    negative: '{"openapi":"2.9.0","info":{"title":"Invalid"}}',
  },
  {
    format: 'swagger_2_0',
    path: 'apis/swagger.yml',
    positive: "swagger: '2.0'\ninfo:\n  title: Legacy API",
    negative: "swagger: '2.1'\ninfo:\n  title: Invalid",
  },
  {
    format: 'asyncapi_2',
    path: 'events/asyncapi.yaml',
    positive: 'asyncapi: 2.6.0\ninfo:\n  title: Event API',
    negative: 'asyncapi: 1.0.0\ninfo:\n  title: Invalid',
  },
  {
    format: 'asyncapi_3',
    path: 'events/asyncapi-v3.yaml',
    positive: 'asyncapi: 3.0.0\ninfo:\n  title: Event API',
    negative: 'asyncapi: 4.0.0\ninfo:\n  title: Invalid',
  },
  {
    format: 'arazzo_1',
    path: 'workflows/arazzo.yaml',
    positive: 'arazzo: 1.0.1\ninfo:\n  title: Workflow',
    negative: 'arazzo: 2.0.0\ninfo:\n  title: Invalid',
  },
  {
    format: 'json_schema',
    path: 'schemas/user.schema.json',
    positive:
      '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","properties":{"id":{"type":"string"}}}',
    negative: '{"title":"No discriminator keys","description":"schema-like text only"}',
  },
  {
    format: 'graphql_sdl',
    path: 'graphql/schema.graphql',
    positive: 'type Query {\n  health: String!\n}',
    negative: 'query Health {\n  health\n}',
  },
  {
    format: 'protobuf',
    path: 'proto/service.proto',
    positive: 'syntax = "proto3";\nmessage User { string id = 1; }',
    negative: 'syntax = "proto2";\nmessage User { optional string id = 1; }',
  },
  {
    format: 'avro',
    path: 'avro/user.avsc',
    positive:
      '{"type":"record","name":"User","fields":[{"name":"id","type":"string"},{"name":"email","type":"string"}]}',
    negative: '{"type":"record","name":"User","doc":"missing fields array"}',
  },
];

describe('detectRepositorySpecFormat', () => {
  for (const fixture of FIXTURES) {
    it(`detects ${fixture.format} from a positive sample`, async () => {
      const result = await detectRepositorySpecFormat({
        path: fixture.path,
        sizeBytes: fixture.positive.length,
        readSnippet: async () => fixture.positive,
      });

      expect(result.format).toBe(fixture.format);
      expect(result.confidence).toBeGreaterThan(0.3);
      expect(result.discriminator).not.toBe('no_known_discriminator');
    });

    it(`does not classify ${fixture.format} from its negative sample`, async () => {
      const result = await detectRepositorySpecFormat({
        path: `samples/not-${fixture.path}`,
        sizeBytes: fixture.negative.length,
        readSnippet: async () => fixture.negative,
      });

      expect(result.format).not.toBe(fixture.format);
    });
  }

  it('returns unknown_spec when no known discriminators exist', async () => {
    const result = await detectRepositorySpecFormat({
      path: 'docs/readme.txt',
      sizeBytes: 64,
      readSnippet: async () => 'This is just plain text with no schema signals.',
    });

    expect(result).toEqual({
      format: 'unknown_spec',
      confidence: 0.05,
      discriminator: 'no_known_discriminator',
    });
  });

  it('requests stream mode for files over 5MB', async () => {
    const seenModes: string[] = [];
    const result = await detectRepositorySpecFormat({
      path: 'huge/spec.proto',
      sizeBytes: STREAMING_SNIFF_THRESHOLD_BYTES + 1,
      readSnippet: async ({ mode, maxBytes }) => {
        seenModes.push(mode);
        expect(maxBytes).toBe(SNIFF_MAX_BYTES);
        return (async function* generator() {
          yield 'syntax = "proto3";\n';
          yield 'message BigFile {}';
        })();
      },
    });

    expect(seenModes).toEqual(['stream']);
    expect(result.format).toBe('protobuf');
  });
});
