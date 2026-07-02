import {
  extractRepositorySpecOriginalMetadata,
  projectDraftFromRepositorySpec,
} from '../../lib/project-draft-from-repository-spec';

describe('projectDraftFromRepositorySpec', () => {
  it('extracts OpenAPI info fields into a project draft', () => {
    const yaml = `
openapi: 3.0.3
info:
  title: Storefront API
  version: 1.0.0
  description: Public storefront operations.
  termsOfService: https://example.com/terms
  contact:
    name: Support
    url: https://example.com/support
    email: support@example.com
  license:
    name: Apache 2.0
    identifier: Apache-2.0
    url: https://www.apache.org/licenses/LICENSE-2.0.html
paths: {}
`;
    const r = projectDraftFromRepositorySpec(yaml, 'openapi/storefront.yaml');
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.draft.projectName).toBe('Storefront API');
    expect(r.draft.projectDescription).toContain('Public storefront');
    expect(r.draft.metadataContactEmail).toBe('support@example.com');
    expect(r.draft.metadataLicenseIdentifier).toBe('Apache-2.0');
  });

  it('returns ok false for non-info specs', () => {
    const r = projectDraftFromRepositorySpec('hello: world', 'x.yaml');
    expect(r.ok).toBe(false);
  });
});

describe('extractRepositorySpecOriginalMetadata', () => {
  it('returns the untouched OpenAPI info block', () => {
    const yaml = `
openapi: 3.0.3
info:
  title: Storefront API
  version: 1.0.0
  description: Public storefront operations.
paths: {}
`;
    const meta = extractRepositorySpecOriginalMetadata(yaml, 'openapi/storefront.yaml');
    expect(meta.format).toBe('openapi');
    expect(meta.sectionLabel).toBe('info');
    expect(meta.payload?.title).toBe('Storefront API');
    expect(meta.payload?.description).toContain('Public storefront');
    expect(meta.specContext.openapi).toBe('3.0.3');
  });

  it('returns root metadata fields for JSON Schema documents', () => {
    const json = JSON.stringify({
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      title: 'Widget',
      description: 'A widget schema.',
      type: 'object',
    });
    const meta = extractRepositorySpecOriginalMetadata(json, 'schemas/widget.json');
    expect(meta.format).toBe('json_schema');
    expect(meta.sectionLabel).toBe('root');
    expect(meta.payload?.title).toBe('Widget');
    expect(meta.payload?.type).toBe('object');
  });
});
