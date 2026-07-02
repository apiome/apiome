import { analyzeSpecification } from '@/app/utils/openapi-analyzer';
import { describe, expect, it } from '@jest/globals';

describe('OpenAPI quality score breakdown (#247)', () => {
  it('exposes five weighted categories whose points sum to the overall score', async () => {
    const spec = `openapi: 3.0.0
info:
  title: Minimal
  version: "1.0"
paths: {}
`;
    const a = await analyzeSpecification(spec, 'minimal.yaml');
    const { categories, overall } = a.qualityScore;
    const sum = Object.values(categories).reduce((s, x) => s + x.points, 0);
    expect(sum).toBe(overall);
    expect(Object.keys(categories).sort()).toEqual(
      ['apiBestPractices', 'designQuality', 'documentation', 'performance', 'security'].sort()
    );
    expect(categories.designQuality.maxPoints).toBe(30);
    expect(categories.documentation.maxPoints).toBe(20);
    expect(categories.apiBestPractices.maxPoints).toBe(25);
    expect(categories.security.maxPoints).toBe(15);
    expect(categories.performance.maxPoints).toBe(10);
  });
});
