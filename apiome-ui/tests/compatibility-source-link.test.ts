import { describe, it, expect } from '@jest/globals';
import {
  buildCompatibilitySourceHref,
  parseCompatibilitySourceQuery,
} from '../lib/compatibility-source-link';

describe('compatibility source links', () => {
  it('builds sourcePath and line query params', () => {
    const href = buildCompatibilitySourceHref({
      path: 'revision/openapi.yaml',
      line: 16,
      pathname: '/ade/dashboard/catalog/abc',
    });
    expect(href).toContain('/ade/dashboard/catalog/abc?');
    expect(href).toContain('sourcePath=revision%2Fopenapi.yaml');
    expect(href).toContain('line=16');
    expect(href).toContain('tab=source');
  });

  it('parses source deep-link query params', () => {
    const params = new URLSearchParams(
      'sourcePath=openapi.yaml&line=7&tab=source'
    );
    expect(parseCompatibilitySourceQuery(params)).toEqual({
      sourcePath: 'openapi.yaml',
      line: 7,
    });
  });
});
