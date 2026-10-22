/**
 * Export studio's tabs and the SDK settings redirect (HIVE-12.2, #5609).
 *
 * The rules behind the Export · SDK & branding strip — which tab a URL selects and how a tab
 * link keeps the rest of the session — and the guarantee that the old SDK settings URL still
 * resolves, now as a redirect to the tab.
 */

import { jest } from '@jest/globals';

const mockRedirect = jest.fn((href: string) => {
  // `redirect()` never returns; it throws Next's control-flow error.
  throw new Error(`NEXT_REDIRECT:${href}`);
});
jest.mock('next/navigation', () => ({ redirect: (href: string) => mockRedirect(href) }));

import {
  EXPORT_STUDIO_TABS,
  EXPORT_STUDIO_TAB_PARAM,
  exportStudioTabFromParams,
  exportStudioTabHref,
} from '../src/app/components/ade/export-studio/exportStudioTabs';
import SdkSettingsPage from '../src/app/ade/dashboard/sdk-settings/page';
import { PLATFORM_NAV_SDK_SETTINGS_HREF } from '../lib/platform-nav';

const STUDIO = '/ade/dashboard/export/studio';

describe('Export studio tabs', () => {
  it('lists Export then SDK & branding, each gated by its own feature id', () => {
    expect(EXPORT_STUDIO_TABS.map((tab) => [tab.id, tab.label, tab.feature])).toEqual([
      ['export', 'Export', 'export-studio'],
      ['sdk', 'SDK & branding', 'sdk-settings'],
    ]);
    expect(EXPORT_STUDIO_TAB_PARAM).toBe('tab');
  });

  it('selects SDK & branding only for ?tab=sdk', () => {
    expect(exportStudioTabFromParams(new URLSearchParams('tab=sdk'))).toBe('sdk');
    expect(exportStudioTabFromParams(new URLSearchParams(''))).toBe('export');
    expect(exportStudioTabFromParams(new URLSearchParams('tab=export'))).toBe('export');
    expect(exportStudioTabFromParams(new URLSearchParams('tab=SDK'))).toBe('export');
    expect(exportStudioTabFromParams(null)).toBe('export');
  });

  it('keeps the rest of the query when switching tabs, and never mutates its input', () => {
    const params = new URLSearchParams('artifact=proj-1&target=proto&step=verify');
    expect(exportStudioTabHref(STUDIO, params, 'sdk')).toBe(
      `${STUDIO}?artifact=proj-1&target=proto&step=verify&tab=sdk`
    );
    expect(params.has('tab')).toBe(false);

    const onSdk = new URLSearchParams('tab=sdk&artifact=proj-1');
    expect(exportStudioTabHref(STUDIO, onSdk, 'export')).toBe(`${STUDIO}?artifact=proj-1`);
    expect(onSdk.get('tab')).toBe('sdk');
  });

  it('drops the query entirely when nothing else is in it', () => {
    expect(exportStudioTabHref(STUDIO, new URLSearchParams('tab=sdk'), 'export')).toBe(STUDIO);
    expect(exportStudioTabHref(STUDIO, null, 'sdk')).toBe(`${STUDIO}?tab=sdk`);
  });

  it('builds the same address the navigation model gives SDK settings', () => {
    expect(exportStudioTabHref(STUDIO, null, 'sdk')).toBe(PLATFORM_NAV_SDK_SETTINGS_HREF);
  });
});

describe('/ade/dashboard/sdk-settings', () => {
  it('redirects to the SDK & branding tab of Export studio', () => {
    mockRedirect.mockClear();
    expect(() => SdkSettingsPage()).toThrow('NEXT_REDIRECT:/ade/dashboard/export/studio?tab=sdk');
    expect(mockRedirect).toHaveBeenCalledTimes(1);
    expect(mockRedirect).toHaveBeenCalledWith(PLATFORM_NAV_SDK_SETTINGS_HREF);
  });
});
