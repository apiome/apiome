import type { DashboardRepository } from '@/app/components/ade/dashboard/repositories/repositoryStoreUi';
import {
  aggregateEstimatedImportableMix,
  estimatedImportableMixForRepo,
} from '@/app/components/ade/dashboard/repositories/repositoryStoreUi';

function repoStub(
  id: string,
  importable_count: number | null,
): DashboardRepository {
  return {
    id,
    name: id,
    full_name: id,
    provider: 'github',
    default_branch: 'main',
    status: 'ready',
    importable_count,
  };
}

describe('estimatedImportableMixForRepo', () => {
  it('returns zeros for null, undefined, or non-positive counts', () => {
    expect(estimatedImportableMixForRepo(null, 'a')).toEqual({
      openapi: 0,
      arazzo: 0,
      jsonSchema: 0,
    });
    expect(estimatedImportableMixForRepo(undefined, 'a')).toEqual({
      openapi: 0,
      arazzo: 0,
      jsonSchema: 0,
    });
    expect(estimatedImportableMixForRepo(0, 'a')).toEqual({
      openapi: 0,
      arazzo: 0,
      jsonSchema: 0,
    });
  });

  it('splits a positive total into three non-negative integers that sum to the total', () => {
    for (const T of [1, 2, 7, 42, 100, 9999]) {
      for (const id of ['repo-1', 'abc/def', '00000000-0000-4000-8000-000000000001']) {
        const m = estimatedImportableMixForRepo(T, id);
        expect(m.openapi + m.arazzo + m.jsonSchema).toBe(T);
        expect(m.openapi).toBeGreaterThanOrEqual(0);
        expect(m.arazzo).toBeGreaterThanOrEqual(0);
        expect(m.jsonSchema).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it('is stable for the same id and total', () => {
    const a = estimatedImportableMixForRepo(50, 'stable-id');
    const b = estimatedImportableMixForRepo(50, 'stable-id');
    expect(a).toEqual(b);
  });
});

describe('aggregateEstimatedImportableMix', () => {
  it('sums per-repo mixes to match summed importable_count', () => {
    const repos = [repoStub('r1', 10), repoStub('r2', 7)];
    const agg = aggregateEstimatedImportableMix(repos);
    expect(agg.total).toBe(17);
    expect(agg.openapi + agg.arazzo + agg.jsonSchema).toBe(17);
  });
});
