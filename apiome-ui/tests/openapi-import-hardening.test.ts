/**
 * Hardening tests for OpenAPI 3.0 / 3.1 import (parseOpenAPISpec).
 *
 * These cases previously caused the entire import to fail with a generic
 * "Failed to parse OpenAPI specification" error or to silently corrupt data.
 * The expectation now is that a single bad schema yields an unsupported
 * class with a per-schema warning while the remainder of the document is
 * still importable.
 */

import YAML from 'yaml';
import { parseOpenAPISpec } from '../src/app/utils/openapi-import';

describe('OpenAPI import hardening', () => {
  it('does not infinitely recurse on circular allOf $ref chains', () => {
    const spec = {
      openapi: '3.1.0',
      info: { title: 'C', version: '1' },
      components: {
        schemas: {
          A: {
            allOf: [{ $ref: '#/components/schemas/B' }],
            properties: { a: { type: 'string' } },
          },
          B: {
            allOf: [{ $ref: '#/components/schemas/A' }],
            properties: { b: { type: 'string' } },
          },
        },
      },
    };
    const r = parseOpenAPISpec(YAML.stringify(spec));
    expect(r.success).toBe(true);
    expect(r.classes.map((c) => c.name).sort()).toEqual(['A', 'B']);
  });

  it('does not infinitely recurse on a self-referential allOf', () => {
    const spec = {
      openapi: '3.1.0',
      info: { title: 'C', version: '1' },
      components: {
        schemas: {
          A: {
            allOf: [{ $ref: '#/components/schemas/A' }],
            properties: { x: { type: 'string' } },
          },
        },
      },
    };
    const r = parseOpenAPISpec(YAML.stringify(spec));
    expect(r.success).toBe(true);
    expect(r.classes[0]?.name).toBe('A');
  });

  it('isolates a malformed schema (null property) and keeps the rest importable', () => {
    const spec = {
      openapi: '3.1.0',
      info: { title: 'M', version: '1' },
      components: {
        schemas: {
          Bad: { type: 'object', properties: { broken: null } },
          Good: { type: 'object', properties: { name: { type: 'string' } } },
        },
      },
    };
    const r = parseOpenAPISpec(YAML.stringify(spec));
    expect(r.success).toBe(true);
    const good = r.classes.find((c) => c.name === 'Good');
    expect(good?.isSupported).toBe(true);
    expect(good?.properties.map((p) => p.name)).toContain('name');
    // Bad schema should still be present (with `broken` property having empty data)
    const bad = r.classes.find((c) => c.name === 'Bad');
    expect(bad).toBeDefined();
  });

  it('does not treat a string `required` as substring-matched required flags', () => {
    // Spec says `required: 'id'` (string, malformed). Previously
    // `'id'.includes('id') === true` would falsely mark `id` as required and
    // `'id'.includes('i') === true` would falsely mark a property `i` required.
    const spec = {
      openapi: '3.1.0',
      info: { title: 'R', version: '1' },
      components: {
        schemas: {
          T: {
            type: 'object',
            properties: { id: { type: 'string' }, i: { type: 'string' } },
            required: 'id',
          },
        },
      },
    };
    const r = parseOpenAPISpec(YAML.stringify(spec));
    expect(r.success).toBe(true);
    const cls = r.classes.find((c) => c.name === 'T');
    expect(cls?.properties.find((p) => p.name === 'id')?.data?.required).toBeUndefined();
    expect(cls?.properties.find((p) => p.name === 'i')?.data?.required).toBeUndefined();
  });

  it('returns a clear error when the document parses to null', () => {
    const r = parseOpenAPISpec('null');
    expect(r.success).toBe(false);
    expect(r.error).toMatch(/Invalid specification/);
  });

  it('returns a clear error when the document parses to a primitive', () => {
    const r = parseOpenAPISpec('"just a string"');
    expect(r.success).toBe(false);
    expect(r.error).toMatch(/Invalid specification/);
  });

  it('tolerates a boolean property schema (JSON Schema 2020-12)', () => {
    const spec = {
      openapi: '3.1.0',
      info: { title: 'B', version: '1' },
      components: {
        schemas: { T: { type: 'object', properties: { anything: true } } },
      },
    };
    const r = parseOpenAPISpec(YAML.stringify(spec));
    expect(r.success).toBe(true);
    const cls = r.classes.find((c) => c.name === 'T');
    expect(cls?.properties.map((p) => p.name)).toEqual(['anything']);
  });

  it('does not misdetect Thrift when OpenAPI 3.0.1 text contains "include a …" (Ably / APIs-guru)', () => {
    // Raw string is checked before YAML parse; a loose `\binclude\s+` Thrift heuristic matched RFC 5988 prose in ably.io platform openapi.yaml.
    const spec = `
openapi: 3.0.1
info:
  title: T
  version: "1"
components:
  headers:
    Link:
      description: This will potentially include a link with relation type next.
      schema:
        type: string
  schemas:
    ChannelDetails:
      type: object
      required: [channelId]
      properties:
        channelId:
          type: string
`;
    const r = parseOpenAPISpec(spec);
    expect(r.success).toBe(true);
    const ch = r.classes.find((c) => c.name === 'ChannelDetails');
    expect(ch?.isSupported).toBe(true);
    expect(ch?.properties.map((p) => p.name)).toContain('channelId');
  });
});
