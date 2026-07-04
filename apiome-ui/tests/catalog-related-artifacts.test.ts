import {
  allRepresentationsHref,
  linkSourceLabel,
  relatedArtifactHref,
} from '../src/app/utils/catalog-related-artifacts';

describe('catalog-related-artifacts', () => {
  it('builds hrefs for catalog items and publishable projects', () => {
    expect(
      relatedArtifactHref({
        projectId: 'cat-1',
        name: 'gRPC',
        slug: 'grpc',
        publishable: false,
      }),
    ).toBe('/ade/dashboard/catalog/cat-1');

    expect(
      relatedArtifactHref({
        projectId: 'proj-1',
        name: 'OpenAPI',
        slug: 'openapi',
        publishable: true,
      }),
    ).toBe('/ade/dashboard/versions?projectId=proj-1');
  });

  it('builds browse facet href for an identity group', () => {
    expect(allRepresentationsHref('group-abc')).toBe(
      '/ade/dashboard/catalog?identityGroupId=group-abc',
    );
  });

  it('labels conversion-seeded links', () => {
    expect(linkSourceLabel('conversion')).toBe('Converted');
    expect(linkSourceLabel('manual')).toBe('Linked');
  });
});
