/**
 * Tests for the OpenAPI detection helper used by the Studio chatbot (#258).
 */

import {
  detectOpenApiSpecs,
  hasOpenApiSpec,
} from '../../src/app/ade/studio/components/chatbot/openapi-detection';

const SAMPLE_SPEC = {
  openapi: '3.1.0',
  info: { title: 'Sample', version: '0.1.0' },
  components: { schemas: {} },
};

describe('detectOpenApiSpecs', () => {
  it('returns the parsed spec from a ```json``` fence', () => {
    const md = ['Here is the spec:', '', '```json', JSON.stringify(SAMPLE_SPEC, null, 2), '```'].join(
      '\n'
    );
    const result = detectOpenApiSpecs(md);
    expect(result).toHaveLength(1);
    expect(result[0].version).toBe('3.1.0');
    expect(result[0].spec.info).toMatchObject({ title: 'Sample' });
  });

  it('detects multiple specs in a single message in document order', () => {
    const md = [
      '```json',
      JSON.stringify({ ...SAMPLE_SPEC, info: { title: 'First', version: '1' } }),
      '```',
      '',
      'and a second one:',
      '',
      '```json',
      JSON.stringify({ ...SAMPLE_SPEC, info: { title: 'Second', version: '2' } }),
      '```',
    ].join('\n');
    const result = detectOpenApiSpecs(md);
    expect(result).toHaveLength(2);
    expect((result[0].spec.info as any).title).toBe('First');
    expect((result[1].spec.info as any).title).toBe('Second');
  });

  it('detects swagger 2.0 documents', () => {
    const md = ['```json', JSON.stringify({ swagger: '2.0', info: {}, paths: {} }), '```'].join(
      '\n'
    );
    const result = detectOpenApiSpecs(md);
    expect(result).toHaveLength(1);
    expect(result[0].swagger).toBe(true);
  });

  it('falls back to structural detection (info + paths) without an openapi key', () => {
    const md = [
      '```json',
      JSON.stringify({ info: { title: 'No version' }, paths: { '/x': {} } }),
      '```',
    ].join('\n');
    const result = detectOpenApiSpecs(md);
    expect(result).toHaveLength(1);
    expect(result[0].version).toBeUndefined();
  });

  it('ignores fenced JSON that is not an OpenAPI document', () => {
    const md = ['```json', JSON.stringify({ name: 'just data', value: 1 }), '```'].join('\n');
    expect(detectOpenApiSpecs(md)).toHaveLength(0);
  });

  it('ignores ```yaml and other non-json fences', () => {
    const md = ['```yaml', 'openapi: 3.1.0', 'info: {}', '```'].join('\n');
    expect(detectOpenApiSpecs(md)).toHaveLength(0);
  });

  it('ignores fences whose contents do not parse as JSON', () => {
    const md = ['```json', '{ this is not json }', '```'].join('\n');
    expect(detectOpenApiSpecs(md)).toHaveLength(0);
  });

  it('returns an empty array on empty input', () => {
    expect(detectOpenApiSpecs('')).toEqual([]);
  });

  it('treats arrays and primitives as non-specs', () => {
    const md = ['```json', JSON.stringify([1, 2, 3]), '```'].join('\n');
    expect(detectOpenApiSpecs(md)).toEqual([]);
  });
});

describe('hasOpenApiSpec', () => {
  it('returns true when at least one spec is present', () => {
    const md = ['```json', JSON.stringify(SAMPLE_SPEC), '```'].join('\n');
    expect(hasOpenApiSpec(md)).toBe(true);
  });

  it('returns false when no spec is present', () => {
    expect(hasOpenApiSpec('plain prose')).toBe(false);
  });
});
