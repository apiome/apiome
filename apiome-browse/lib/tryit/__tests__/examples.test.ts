import { describe, expect, it } from 'vitest';
import {
  bodyVariantHasPrefillSupport,
  buildInitialParamValues,
  collectBodyExamples,
  describeBodySource,
  formatBodyForEditor,
  resolveExampleValue,
} from '../examples';
import type { BodyVariant, ParamSpec } from '../operation';

describe('resolveExampleValue', () => {
  it('unwraps OpenAPI example objects', () => {
    expect(resolveExampleValue({ summary: 'A pet', value: { name: 'Rex' } })).toEqual({ name: 'Rex' });
    expect(resolveExampleValue('plain')).toBe('plain');
  });
});

describe('collectBodyExamples', () => {
  it('lists named examples before the single media example', () => {
    const variant: BodyVariant = {
      contentType: 'application/json',
      schema: { type: 'object' },
      examples: {
        minimal: { summary: 'Small', value: { name: 'a' } },
        full: { value: { name: 'b', tag: 'vip' } },
      },
      example: { name: 'fallback' },
    };
    expect(collectBodyExamples(variant).map((e) => e.name)).toEqual(['minimal', 'full', 'example']);
  });
});

describe('formatBodyForEditor', () => {
  it('pretty-prints JSON values', () => {
    expect(formatBodyForEditor({ id: 1 }, true)).toBe('{\n  "id": 1\n}');
  });

  it('keeps valid JSON strings as-is', () => {
    expect(formatBodyForEditor('{"ok":true}', true)).toBe('{"ok":true}');
  });

  it('stringifies non-JSON media examples', () => {
    expect(formatBodyForEditor('hello', false)).toBe('hello');
    expect(formatBodyForEditor(42, false)).toBe('42');
  });
});

describe('describeBodySource', () => {
  it('labels example, generated, manual, and empty sources', () => {
    expect(describeBodySource({ kind: 'example', name: 'minimal' })).toBe('Example: minimal');
    expect(describeBodySource({ kind: 'example', name: 'example' })).toBe('Example');
    expect(describeBodySource({ kind: 'generated', seed: 3 })).toBe('Generated (seed 3)');
    expect(describeBodySource({ kind: 'manual' })).toBe('Edited manually');
    expect(describeBodySource({ kind: 'empty' })).toBeNull();
  });
});

describe('bodyVariantHasPrefillSupport', () => {
  it('is true when examples or schema exist', () => {
    expect(
      bodyVariantHasPrefillSupport({
        contentType: 'application/json',
        schema: null,
        example: { ok: true },
      })
    ).toBe(true);
    expect(
      bodyVariantHasPrefillSupport({
        contentType: 'application/json',
        schema: { type: 'object' },
      })
    ).toBe(true);
    expect(
      bodyVariantHasPrefillSupport({
        contentType: 'text/plain',
        schema: null,
      })
    ).toBe(false);
  });
});

describe('buildInitialParamValues', () => {
  it('prefers default, then example, then named examples', () => {
    const params: ParamSpec[] = [
      {
        name: 'status',
        location: 'query',
        required: false,
        schema: { type: 'string', default: 'open' },
      },
      {
        name: 'tag',
        location: 'query',
        required: false,
        schema: { type: 'string', example: 'vip' },
      },
      {
        name: 'mode',
        location: 'query',
        required: false,
        schema: {
          type: 'string',
          examples: { fast: { value: 'quick' } },
        },
      },
    ];
    expect(buildInitialParamValues(params)).toEqual({
      'query:status': 'open',
      'query:tag': 'vip',
      'query:mode': 'quick',
    });
  });
});
