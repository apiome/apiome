import {
  validateOpenApiParameterName,
} from '../../lib/utils/openapi-parameter-name';

describe('validateOpenApiParameterName', () => {
  it('accepts typical header and cookie tokens', () => {
    expect(validateOpenApiParameterName('Authorization', 'header')).toBeNull();
    expect(validateOpenApiParameterName('X-Request-ID', 'header')).toBeNull();
    expect(validateOpenApiParameterName('session', 'cookie')).toBeNull();
  });

  it('rejects header names with spaces', () => {
    expect(validateOpenApiParameterName('Auth Token', 'header')).not.toBeNull();
  });

  it('accepts query and path names', () => {
    expect(validateOpenApiParameterName('page_size', 'query')).toBeNull();
    expect(validateOpenApiParameterName('userId', 'path')).toBeNull();
  });

  it('accepts hyphenated path parameter names (e.g. from template {user-id})', () => {
    expect(validateOpenApiParameterName('user-id', 'path')).toBeNull();
    expect(validateOpenApiParameterName('org-name', 'path')).toBeNull();
  });

  it('accepts hyphenated and special-character query parameter names', () => {
    expect(validateOpenApiParameterName('filter-by', 'query')).toBeNull();
    expect(validateOpenApiParameterName('sort.order', 'query')).toBeNull();
    expect(validateOpenApiParameterName('page[size]', 'query')).toBeNull();
  });

  it('rejects query parameter names with whitespace', () => {
    expect(validateOpenApiParameterName('my param', 'query')).not.toBeNull();
    expect(validateOpenApiParameterName('a b', 'query')).not.toBeNull();
  });

  it('rejects empty names for all locations', () => {
    for (const loc of ['path', 'query', 'header', 'cookie'] as const) {
      expect(validateOpenApiParameterName('', loc)).not.toBeNull();
      expect(validateOpenApiParameterName('   ', loc)).not.toBeNull();
    }
  });
});
