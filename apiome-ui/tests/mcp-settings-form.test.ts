/**
 * Unit tests for the MCP endpoint-detail "Settings" tab pure helpers (V2-MCP-24.9 / MCAT-10.9).
 *
 * Covers cadence presets/labels/options, form seeding & validation, the change-only PATCH-body
 * builder, the typed-confirm gate, and the teardown-summary parsing/formatting.
 */

import {
  MCP_CADENCE_PRESETS,
  MCP_DELETE_CONFIRM_WORD,
  MCP_SUB_DAILY_CADENCE_CONFIRM_MESSAGE,
  buildSettingsPatchBody,
  cadenceSelectValueFromForm,
  formatTeardownSummary,
  hasSettingsChanges,
  isDeleteConfirmed,
  isSubDailyCadenceSeconds,
  mcpCadenceLabel,
  mcpCadenceOptions,
  mcpSettingsFormFromEndpoint,
  mcpTeardownSummaryFromPayload,
  normalizeCadenceSelectValue,
  parseCadenceSecondsFromForm,
  settingsPatchNeedsSubDailyCadenceConfirm,
  validateMcpSettingsForm,
  MCP_CADENCE_DEFAULT_SELECT_VALUE,
  type McpSettingsForm,
} from '../src/app/components/ade/dashboard/mcp/mcpSettingsForm';
import {
  mcpEndpointDetailFromPayload,
  type McpEndpointDetail,
} from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';

const HOUR = 60 * 60;
const DAY = 24 * HOUR;

function endpoint(overrides: Record<string, unknown> = {}): McpEndpointDetail {
  const parsed = mcpEndpointDetailFromPayload({
    endpoint: {
      id: '11111111-1111-1111-8111-111111111111',
      name: 'Acme Weather',
      slug: 'acme-weather',
      endpoint_url: 'https://mcp.acme.example/sse',
      transport: 'streamable_http',
      visibility: 'private',
      published: false,
      enabled: true,
      discovery_cadence_seconds: DAY,
      ...overrides,
    },
  });
  if (!parsed) throw new Error('fixture failed to parse');
  return parsed;
}

function form(overrides: Partial<McpSettingsForm> = {}): McpSettingsForm {
  return { ...mcpSettingsFormFromEndpoint(endpoint()), ...overrides };
}

describe('mcpEndpointDetailFromPayload — cadence', () => {
  it('parses discovery_cadence_seconds, defaulting absent/zero to null', () => {
    expect(endpoint().discovery_cadence_seconds).toBe(DAY);
    expect(endpoint({ discovery_cadence_seconds: null }).discovery_cadence_seconds).toBeNull();
    expect(endpoint({ discovery_cadence_seconds: undefined }).discovery_cadence_seconds).toBeNull();
  });
});

describe('mcpCadenceLabel', () => {
  it('uses the preset label for an exact preset match', () => {
    expect(mcpCadenceLabel(HOUR)).toBe('Every hour');
    expect(mcpCadenceLabel(DAY)).toBe('Daily');
    expect(mcpCadenceLabel(7 * DAY)).toBe('Weekly');
  });

  it('renders a friendly span for non-preset day/hour/minute values', () => {
    expect(mcpCadenceLabel(3 * DAY)).toBe('Every 3 days');
    expect(mcpCadenceLabel(2 * HOUR)).toBe('Every 2 hours');
    expect(mcpCadenceLabel(90 * 60)).toBe('Every 90 minutes');
  });
});

describe('cadence select normalization', () => {
  it('maps the Radix sentinel to and from the form empty-string default', () => {
    expect(normalizeCadenceSelectValue(MCP_CADENCE_DEFAULT_SELECT_VALUE)).toBe('');
    expect(cadenceSelectValueFromForm('')).toBe(MCP_CADENCE_DEFAULT_SELECT_VALUE);
    expect(cadenceSelectValueFromForm(String(HOUR))).toBe(String(HOUR));
  });

  it('parses preset seconds and treats default/invalid values as null', () => {
    expect(parseCadenceSecondsFromForm(String(HOUR))).toBe(HOUR);
    expect(parseCadenceSecondsFromForm('')).toBeNull();
    expect(parseCadenceSecondsFromForm(MCP_CADENCE_DEFAULT_SELECT_VALUE)).toBeNull();
    expect(parseCadenceSecondsFromForm('default')).toBeNull();
    expect(parseCadenceSecondsFromForm('not-a-number')).toBeNull();
  });
});

describe('isSubDailyCadenceSeconds / settingsPatchNeedsSubDailyCadenceConfirm', () => {
  it('treats cadences below one day as sub-daily', () => {
    expect(isSubDailyCadenceSeconds(HOUR)).toBe(true);
    expect(isSubDailyCadenceSeconds(6 * HOUR)).toBe(true);
    expect(isSubDailyCadenceSeconds(12 * HOUR)).toBe(true);
    expect(isSubDailyCadenceSeconds(DAY)).toBe(false);
    expect(isSubDailyCadenceSeconds(7 * DAY)).toBe(false);
  });

  it('flags a patch that sets a sub-daily cadence', () => {
    const patch = buildSettingsPatchBody(form({ cadence: String(HOUR) }), endpoint());
    expect(settingsPatchNeedsSubDailyCadenceConfirm(patch)).toBe(true);
    expect(MCP_SUB_DAILY_CADENCE_CONFIRM_MESSAGE).toMatch(/rate limit/i);
  });

  it('does not flag daily-or-longer cadence changes or unrelated patches', () => {
    expect(
      settingsPatchNeedsSubDailyCadenceConfirm(
        buildSettingsPatchBody(form({ cadence: String(DAY) }), endpoint({ discovery_cadence_seconds: HOUR })),
      ),
    ).toBe(false);
    expect(settingsPatchNeedsSubDailyCadenceConfirm(buildSettingsPatchBody(form({ name: 'New' }), endpoint()))).toBe(
      false,
    );
    expect(
      settingsPatchNeedsSubDailyCadenceConfirm(
        buildSettingsPatchBody(form({ cadence: '' }), endpoint({ discovery_cadence_seconds: HOUR })),
      ),
    ).toBe(false);
  });

  it('emits null when reverting an explicit cadence back to the server default', () => {
    const patch = buildSettingsPatchBody(
      form({ cadence: MCP_CADENCE_DEFAULT_SELECT_VALUE }),
      endpoint({ discovery_cadence_seconds: DAY }),
    );
    expect(patch).toEqual({ discovery_cadence_seconds: null });
  });
});

describe('mcpCadenceOptions', () => {
  it('always leads with the default option and lists every preset in ascending order', () => {
    const opts = mcpCadenceOptions(null);
    expect(opts[0]).toEqual({ value: '', label: 'Default cadence' });
    const presetValues = opts.slice(1).map((o) => Number(o.value));
    expect(presetValues).toEqual([...presetValues].sort((a, b) => a - b));
    expect(presetValues).toEqual(
      [...MCP_CADENCE_PRESETS].map((p) => p.seconds).sort((a, b) => a - b),
    );
  });

  it('inserts a non-preset current cadence as its own option', () => {
    const custom = 3 * DAY;
    const opts = mcpCadenceOptions(custom);
    const match = opts.find((o) => o.value === String(custom));
    expect(match).toEqual({ value: String(custom), label: 'Every 3 days' });
  });

  it('does not duplicate a current cadence that is already a preset', () => {
    const opts = mcpCadenceOptions(DAY);
    expect(opts.filter((o) => o.value === String(DAY))).toHaveLength(1);
  });
});

describe('mcpSettingsFormFromEndpoint', () => {
  it('seeds every editable field from the endpoint', () => {
    const f = mcpSettingsFormFromEndpoint(endpoint());
    expect(f).toEqual({
      name: 'Acme Weather',
      endpointUrl: 'https://mcp.acme.example/sse',
      transport: 'streamable_http',
      visibility: 'private',
      cadence: String(DAY),
    });
  });

  it('represents an unset cadence as the empty string', () => {
    expect(mcpSettingsFormFromEndpoint(endpoint({ discovery_cadence_seconds: null })).cadence).toBe(
      '',
    );
  });

  it('normalizes unknown transport/visibility to safe defaults', () => {
    const f = mcpSettingsFormFromEndpoint(endpoint({ transport: 'weird', visibility: 'galaxy' }));
    expect(f.transport).toBe('streamable_http');
    expect(f.visibility).toBe('private');
  });
});

describe('validateMcpSettingsForm', () => {
  it('passes a well-formed form', () => {
    expect(validateMcpSettingsForm(form())).toBeNull();
  });

  it('rejects a blank name', () => {
    expect(validateMcpSettingsForm(form({ name: '   ' }))).toMatch(/name/i);
  });

  it('rejects a blank URL', () => {
    expect(validateMcpSettingsForm(form({ endpointUrl: '' }))).toMatch(/URL/i);
  });

  it('rejects a non-http(s) URL for an HTTP transport', () => {
    expect(
      validateMcpSettingsForm(form({ transport: 'sse', endpointUrl: 'ftp://nope.example' })),
    ).toMatch(/http/i);
  });

  it('allows a non-URL command target for the stdio transport', () => {
    expect(
      validateMcpSettingsForm(form({ transport: 'stdio', endpointUrl: 'python -m my_server' })),
    ).toBeNull();
  });
});

describe('buildSettingsPatchBody', () => {
  it('returns an empty patch when nothing changed', () => {
    const patch = buildSettingsPatchBody(form(), endpoint());
    expect(patch).toEqual({});
    expect(hasSettingsChanges(patch)).toBe(false);
  });

  it('includes only the changed fields (trimmed)', () => {
    const patch = buildSettingsPatchBody(
      form({ name: '  New Name  ', visibility: 'public' }),
      endpoint(),
    );
    expect(patch).toEqual({ name: 'New Name', visibility: 'public' });
    expect(hasSettingsChanges(patch)).toBe(true);
  });

  it('emits transport and url changes', () => {
    const patch = buildSettingsPatchBody(
      form({ transport: 'sse', endpointUrl: 'https://mcp.acme.example/v2/sse' }),
      endpoint(),
    );
    expect(patch).toEqual({
      transport: 'sse',
      endpoint_url: 'https://mcp.acme.example/v2/sse',
    });
  });

  it('emits a cadence change as a number', () => {
    const patch = buildSettingsPatchBody(form({ cadence: String(HOUR) }), endpoint());
    expect(patch).toEqual({ discovery_cadence_seconds: HOUR });
  });

  it('does not emit a cadence when it is unchanged', () => {
    expect(buildSettingsPatchBody(form({ cadence: String(DAY) }), endpoint())).toEqual({});
    expect(
      buildSettingsPatchBody(form({ cadence: '' }), endpoint({ discovery_cadence_seconds: null })),
    ).toEqual({});
  });

  it('emits null when clearing an explicit cadence back to the server default', () => {
    expect(buildSettingsPatchBody(form({ cadence: '' }), endpoint())).toEqual({
      discovery_cadence_seconds: null,
    });
  });

  it('does not emit a blank name even when the field was emptied', () => {
    const patch = buildSettingsPatchBody(form({ name: '   ' }), endpoint());
    expect(patch.name).toBeUndefined();
  });
});

describe('isDeleteConfirmed', () => {
  it('matches the exact confirm word (trimmed)', () => {
    expect(isDeleteConfirmed(MCP_DELETE_CONFIRM_WORD)).toBe(true);
    expect(isDeleteConfirmed('  DELETE  ')).toBe(true);
  });

  it('rejects anything else (including the wrong case)', () => {
    expect(isDeleteConfirmed('delete')).toBe(false);
    expect(isDeleteConfirmed('DELET')).toBe(false);
    expect(isDeleteConfirmed('')).toBe(false);
  });
});

describe('mcpTeardownSummaryFromPayload', () => {
  it('parses the rest delete response', () => {
    expect(
      mcpTeardownSummaryFromPayload({
        success: true,
        credentials_purged: true,
        versions_deleted: 3,
        jobs_deleted: 2,
      }),
    ).toEqual({ credentials_purged: true, versions_deleted: 3, jobs_deleted: 2 });
  });

  it('defends against missing/invalid fields', () => {
    expect(mcpTeardownSummaryFromPayload({})).toEqual({
      credentials_purged: false,
      versions_deleted: 0,
      jobs_deleted: 0,
    });
    expect(mcpTeardownSummaryFromPayload(null)).toEqual({
      credentials_purged: false,
      versions_deleted: 0,
      jobs_deleted: 0,
    });
  });
});

describe('formatTeardownSummary', () => {
  it('pluralizes and mentions purged credentials', () => {
    expect(
      formatTeardownSummary({ credentials_purged: true, versions_deleted: 3, jobs_deleted: 2 }),
    ).toBe('Removed 3 versions, 2 jobs and purged stored credentials.');
  });

  it('uses singular nouns and omits the credentials clause when none purged', () => {
    expect(
      formatTeardownSummary({ credentials_purged: false, versions_deleted: 1, jobs_deleted: 1 }),
    ).toBe('Removed 1 version, 1 job.');
  });
});
