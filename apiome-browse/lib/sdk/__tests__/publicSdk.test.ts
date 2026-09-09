/**
 * Public "Get SDK" helpers — SDK-3.3 (#4493).
 *
 * Pins the URL builders the panel fetches with, the download filename fallback, the coverage
 * sentence, and the error copy a failed download shows.
 */

import { describe, expect, it } from 'vitest';
import {
  coverageSummary,
  hasPackages,
  publicSdkDownloadUrl,
  publicSdkErrorFromResponse,
  publicSdkErrorMessage,
  publicSdkInfoUrl,
  sdkFallbackFilename,
  type PublicSdkInfoResponse,
} from '../publicSdk';

const COORDS = { tenantSlug: 'acme', projectSlug: 'widgets', versionSlug: '1.0.0' };
const BASE = 'https://api.example.com/v1';

/** An info response with sensible defaults, overridable per test. */
function info(overrides: Partial<PublicSdkInfoResponse> = {}): PublicSdkInfoResponse {
  return {
    tenant_slug: 'acme',
    project_slug: 'widgets',
    version_slug: '1.0.0',
    version_record_id: 'rev-1',
    version_label: '1.0.0',
    api_title: 'Widgets API',
    languages: [{ lang: 'ts', label: 'TypeScript', install: null, file_extension: 'ts' }],
    packages: [],
    operation_count: 3,
    total_operation_count: 3,
    truncated: false,
    download: {
      filename: 'widgets-1.0.0-sdk.zip',
      media_type: 'application/zip',
      schema_version: 'sdk.client-kit.v1',
    },
    ...overrides,
  };
}

/** A Response double carrying a status and a body. */
function response(status: number, body = ''): Response {
  return { status, text: async () => body } as unknown as Response;
}

describe('URL builders', () => {
  it('addresses the info route under the version', () => {
    expect(publicSdkInfoUrl(BASE, COORDS)).toBe(
      'https://api.example.com/v1/browse/tenants/acme/projects/widgets/versions/1.0.0/sdk'
    );
  });

  it('appends /download for the archive', () => {
    expect(publicSdkDownloadUrl(BASE, COORDS)).toBe(
      'https://api.example.com/v1/browse/tenants/acme/projects/widgets/versions/1.0.0/sdk/download'
    );
  });

  it('encodes each slug segment', () => {
    const url = publicSdkInfoUrl(BASE, {
      tenantSlug: 'a c',
      projectSlug: 'p/q',
      versionSlug: '1.0.0-rc 1',
    });
    expect(url).toContain('/tenants/a%20c/');
    expect(url).toContain('/projects/p%2Fq/');
    expect(url).toContain('/versions/1.0.0-rc%201/');
  });
});

describe('sdkFallbackFilename', () => {
  it('mirrors the filename the REST layer would name', () => {
    expect(sdkFallbackFilename(COORDS)).toBe('widgets-1.0.0-sdk.zip');
  });
});

describe('hasPackages', () => {
  it('is false when the tenant configured no package patterns', () => {
    expect(hasPackages(info())).toBe(false);
  });

  it('is true once an ecosystem resolved to a name', () => {
    expect(
      hasPackages(info({ packages: [{ ecosystem: 'npm', name: '@acme/widgets-sdk' }] }))
    ).toBe(true);
  });
});

describe('coverageSummary', () => {
  it('says "all" when every operation is covered', () => {
    expect(coverageSummary(info())).toBe('Runnable examples for all 3 operations.');
  });

  it('uses the singular for a one-operation API', () => {
    expect(coverageSummary(info({ operation_count: 1, total_operation_count: 1 }))).toBe(
      'Runnable examples for all 1 operation.'
    );
  });

  it('names the shortfall when some operations have no HTTP binding', () => {
    expect(coverageSummary(info({ operation_count: 2, total_operation_count: 5 }))).toBe(
      'Runnable examples for 2 of 5 operations.'
    );
  });

  it('says the kit was truncated when the cap was hit', () => {
    expect(
      coverageSummary(info({ operation_count: 250, total_operation_count: 400, truncated: true }))
    ).toBe('Runnable examples for the first 250 of 400 operations.');
  });
});

describe('publicSdkErrorMessage', () => {
  it('explains a rate limit', () => {
    expect(publicSdkErrorMessage(429)).toContain('Too many requests');
  });

  it('explains the public size cap', () => {
    expect(publicSdkErrorMessage(413)).toContain('too large');
  });

  it('explains a download that has become unavailable', () => {
    expect(publicSdkErrorMessage(404)).toBe('This SDK is no longer available for download.');
  });

  it('names the status for anything else', () => {
    expect(publicSdkErrorMessage(500)).toBe('Download failed (500).');
  });

  it("prefers the server's own sentence when it sent one", () => {
    expect(publicSdkErrorMessage(429, 'Slow down.')).toBe('Slow down.');
    expect(publicSdkErrorMessage(500, 'Boom.')).toBe('Boom.');
  });
});

describe('publicSdkErrorFromResponse', () => {
  it('lifts the detail out of the body', async () => {
    await expect(
      publicSdkErrorFromResponse(response(404, '{"detail": "Gone for good"}'))
    ).resolves.toBe('Gone for good');
  });

  it('falls back to the stable copy when the body carries none', async () => {
    await expect(publicSdkErrorFromResponse(response(413, 'nope'))).resolves.toContain(
      'too large'
    );
  });
});
