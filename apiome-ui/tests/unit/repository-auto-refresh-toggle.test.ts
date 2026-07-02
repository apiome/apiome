/**
 * Auto-refresh enable/disable parsing (RAR-3.3, #3524).
 *
 * The repository detail Settings tab drives a Switch from
 * `DashboardRepository.auto_refresh_enabled`. These tests pin how
 * `dashboardRepositoryFromApi` derives that flag from the REST payload, including
 * the default-on fallback for older rows whose payload omits the field.
 */

import { dashboardRepositoryFromApi } from '@/app/components/ade/dashboard/repositories/repositoryStoreUi';

function basePayload(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'r1',
    name: 'repo',
    full_name: 'org/repo',
    provider: 'github',
    default_branch: 'main',
    status: 'ready',
    ...extra,
  };
}

describe('dashboardRepositoryFromApi auto_refresh_enabled', () => {
  it('parses an explicit true', () => {
    const repo = dashboardRepositoryFromApi(basePayload({ auto_refresh_enabled: true }));
    expect(repo?.auto_refresh_enabled).toBe(true);
  });

  it('parses an explicit false', () => {
    const repo = dashboardRepositoryFromApi(basePayload({ auto_refresh_enabled: false }));
    expect(repo?.auto_refresh_enabled).toBe(false);
  });

  it('accepts the camelCase spelling', () => {
    const repo = dashboardRepositoryFromApi(basePayload({ autoRefreshEnabled: false }));
    expect(repo?.auto_refresh_enabled).toBe(false);
  });

  it('defaults to enabled when the field is absent (older row)', () => {
    const repo = dashboardRepositoryFromApi(basePayload());
    expect(repo?.auto_refresh_enabled).toBe(true);
  });

  it('defaults to enabled when the field is null', () => {
    const repo = dashboardRepositoryFromApi(basePayload({ auto_refresh_enabled: null }));
    expect(repo?.auto_refresh_enabled).toBe(true);
  });
});
