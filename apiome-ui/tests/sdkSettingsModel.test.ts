/**
 * The form model behind Ship → SDK settings (SDK-3.4, #4494).
 *
 * The screen's one genuinely tricky rule is **tri-state**: at project scope a field is either
 * inherited (its key is absent from the stored body), overridden (the key holds a string), or
 * deliberately none (the key holds `null`). A round trip through `draftFromBody` and
 * `bodyFromDraft` has to preserve all three, because the middle of the three is the only one a
 * plain text input can express on its own.
 *
 * These are pure-function tests: no React, no fetch.
 */

import {
  SDK_ECOSYSTEMS,
  SDK_FIELD_KEYS,
  bodyFromDraft,
  describeSource,
  draftFromBody,
  emptyDraft,
  hasScopeSettings,
  isDraftDirty,
  type SdkSettingsBody,
  type SdkSettingsResponse,
} from '@/app/ade/dashboard/sdk-settings/sdkSettingsModel';

/** A settings response with the fields a test cares about. */
function response(partial: Partial<SdkSettingsResponse> = {}): SdkSettingsResponse {
  return {
    schemaVersion: 'sdk.generation-settings.v1',
    source: 'default',
    contentFingerprint: `sha256:${'0'.repeat(64)}`,
    settings: { packageNamePatterns: {}, licenseHeader: null, userAgent: null },
    resolved: { packageNames: {}, licenseHeader: null, userAgent: null },
    scope: 'tenant',
    scopeBody: null,
    tenantSettingsId: null,
    projectSettingsId: null,
    updatedAt: null,
    updatedBy: null,
    degraded: false,
    ...partial,
  };
}

describe('an empty form', () => {
  it('inherits everything at project scope', () => {
    const draft = emptyDraft('project');
    for (const key of SDK_FIELD_KEYS) {
      expect(draft[key]).toEqual({ inherit: true, value: '' });
    }
  });

  it('inherits nothing at workspace scope, because there is nothing above it', () => {
    const draft = emptyDraft('tenant');
    for (const key of SDK_FIELD_KEYS) {
      expect(draft[key]).toEqual({ inherit: false, value: '' });
    }
  });

  it('sends an empty body, so saving a blank workspace form configures nothing', () => {
    expect(bodyFromDraft(emptyDraft('tenant'), 'tenant')).toEqual({});
  });

  it('sends an empty body at project scope too, so a fresh override inherits everything', () => {
    expect(bodyFromDraft(emptyDraft('project'), 'project')).toEqual({});
  });
});

describe('reading a stored body at project scope', () => {
  const body: SdkSettingsBody = {
    schemaVersion: 'sdk.generation-settings.v1',
    packageNamePatterns: { npm: '@acme/{project}-sdk' },
    licenseHeader: null,
  };

  it('marks a named key as an override', () => {
    expect(draftFromBody(body, 'project').npm).toEqual({
      inherit: false,
      value: '@acme/{project}-sdk',
    });
  });

  it('marks an absent key as inherited', () => {
    expect(draftFromBody(body, 'project').userAgent).toEqual({ inherit: true, value: '' });
    expect(draftFromBody(body, 'project').pypi).toEqual({ inherit: true, value: '' });
  });

  it('marks an explicitly nulled key as deliberately none, not as inherited', () => {
    // The distinction the whole model exists for.
    expect(draftFromBody(body, 'project').licenseHeader).toEqual({ inherit: false, value: '' });
  });

  it('treats a nulled pattern map as clearing every ecosystem at once', () => {
    const draft = draftFromBody({ packageNamePatterns: null }, 'project');
    for (const ecosystem of SDK_ECOSYSTEMS) {
      expect(draft[ecosystem]).toEqual({ inherit: false, value: '' });
    }
  });

  it('starts blank when the scope has saved nothing', () => {
    expect(draftFromBody(null, 'project')).toEqual(emptyDraft('project'));
  });
});

describe('reading a stored body at workspace scope', () => {
  it('never shows a field as inherited', () => {
    const draft = draftFromBody({ userAgent: 'acme/1.0', licenseHeader: null }, 'tenant');
    expect(draft.userAgent).toEqual({ inherit: false, value: 'acme/1.0' });
    expect(draft.licenseHeader).toEqual({ inherit: false, value: '' });
  });
});

describe('writing the body back', () => {
  it('omits an inherited field', () => {
    const draft = emptyDraft('project');
    draft.userAgent = { inherit: false, value: 'petstore/2.0' };
    expect(bodyFromDraft(draft, 'project')).toEqual({ userAgent: 'petstore/2.0' });
  });

  it('sends null for a project field that is empty and not inherited', () => {
    const draft = emptyDraft('project');
    draft.licenseHeader = { inherit: false, value: '   ' };
    expect(bodyFromDraft(draft, 'project')).toEqual({ licenseHeader: null });
  });

  it('omits an empty workspace field instead, because a PUT replaces the whole body', () => {
    const draft = emptyDraft('tenant');
    draft.licenseHeader = { inherit: false, value: '' };
    draft.userAgent = { inherit: false, value: 'acme/1.0' };
    expect(bodyFromDraft(draft, 'tenant')).toEqual({ userAgent: 'acme/1.0' });
  });

  it('groups the two ecosystems under one key, naming only those it speaks for', () => {
    const draft = emptyDraft('project');
    draft.npm = { inherit: false, value: '@acme/{project}' };
    draft.pypi = { inherit: false, value: '' };
    expect(bodyFromDraft(draft, 'project')).toEqual({
      packageNamePatterns: { npm: '@acme/{project}', pypi: null },
    });
  });

  it('omits the pattern key entirely when both ecosystems inherit', () => {
    const draft = emptyDraft('project');
    draft.userAgent = { inherit: false, value: 'acme/1.0' };
    expect(bodyFromDraft(draft, 'project')).not.toHaveProperty('packageNamePatterns');
  });

  it('trims values, so a stray space is not stored as a pattern', () => {
    const draft = emptyDraft('tenant');
    draft.userAgent = { inherit: false, value: '  acme/1.0  ' };
    expect(bodyFromDraft(draft, 'tenant')).toEqual({ userAgent: 'acme/1.0' });
  });
});

describe('the round trip preserves all three states', () => {
  it.each([
    ['inherited', {} as SdkSettingsBody],
    ['overridden', { userAgent: 'acme/1.0' } as SdkSettingsBody],
    ['deliberately none', { userAgent: null } as SdkSettingsBody],
  ])('survives %s', (_label, body) => {
    const draft = draftFromBody(body, 'project');
    expect(bodyFromDraft(draft, 'project')).toEqual(body);
  });
});

describe('dirty tracking', () => {
  it('is clean when nothing changed', () => {
    const draft = emptyDraft('project');
    expect(isDraftDirty(draft, emptyDraft('project'))).toBe(false);
  });

  it('notices a changed value', () => {
    const draft = emptyDraft('project');
    draft.npm = { inherit: false, value: '@acme/x' };
    expect(isDraftDirty(draft, emptyDraft('project'))).toBe(true);
  });

  it('notices a toggled Inherit even when the text is unchanged', () => {
    const draft = emptyDraft('project');
    draft.npm = { inherit: false, value: '' };
    expect(isDraftDirty(draft, emptyDraft('project'))).toBe(true);
  });

  it('ignores whitespace-only edits, which would otherwise save nothing', () => {
    const baseline = emptyDraft('tenant');
    baseline.npm = { inherit: false, value: '@acme/x' };
    const draft = { ...baseline, npm: { inherit: false, value: '  @acme/x  ' } };
    expect(isDraftDirty(draft, baseline)).toBe(false);
  });
});

describe('what a scope has of its own', () => {
  it('offers nothing to clear when a project inherits everything', () => {
    expect(hasScopeSettings(response({ scope: 'project', tenantSettingsId: 't-1' }))).toBe(false);
  });

  it('offers a clear when the project saved its own row', () => {
    expect(hasScopeSettings(response({ scope: 'project', projectSettingsId: 'p-1' }))).toBe(true);
  });

  it('reads the tenant row at workspace scope', () => {
    expect(hasScopeSettings(response({ scope: 'tenant', tenantSettingsId: 't-1' }))).toBe(true);
    expect(hasScopeSettings(response({ scope: 'tenant', projectSettingsId: 'p-1' }))).toBe(false);
  });

  it('offers nothing before anything has loaded', () => {
    expect(hasScopeSettings(null)).toBe(false);
  });
});

describe('the source sentence', () => {
  it('distinguishes inheriting from overriding', () => {
    expect(describeSource(response({ scope: 'project', source: 'tenant' }))).toContain('inherits');
    expect(describeSource(response({ scope: 'project', source: 'merged' }))).toContain('overrides');
  });

  it('says plainly when nothing is configured', () => {
    expect(describeSource(response())).toContain('no branding');
  });

  it('reads differently for the workspace than for a project', () => {
    expect(describeSource(response({ scope: 'tenant', source: 'tenant' }))).toContain(
      'every project inherits',
    );
  });
});

describe('the public SDK switch (SDK-3.3)', () => {
  it('starts off at both scopes, because a gate has no other safe default', () => {
    expect(emptyDraft('tenant').publicSdkEnabled).toEqual({ inherit: false, value: false });
    expect(emptyDraft('project').publicSdkEnabled).toEqual({ inherit: true, value: false });
  });

  it('reads an absent key at project scope as inherited', () => {
    expect(draftFromBody({ userAgent: 'acme/1.0' }, 'project').publicSdkEnabled).toEqual({
      inherit: true,
      value: false,
    });
  });

  it('reads an explicit true as an override', () => {
    expect(draftFromBody({ publicSdkEnabled: true }, 'project').publicSdkEnabled).toEqual({
      inherit: false,
      value: true,
    });
  });

  it('reads an explicit null as off, not as inherited', () => {
    // For a gate, "deliberately none" and "closed" are the same answer — but it must still block
    // inheritance, which is what `inherit: false` records.
    expect(draftFromBody({ publicSdkEnabled: null }, 'project').publicSdkEnabled).toEqual({
      inherit: false,
      value: false,
    });
  });

  it('never shows the switch as inherited at workspace scope', () => {
    expect(draftFromBody({}, 'tenant').publicSdkEnabled.inherit).toBe(false);
  });

  it('omits its key when inheriting', () => {
    const draft = emptyDraft('project');
    expect(bodyFromDraft(draft, 'project')).not.toHaveProperty('publicSdkEnabled');
  });

  it('writes an explicit false at project scope, to close a workspace that opened it', () => {
    const draft = emptyDraft('project');
    draft.publicSdkEnabled = { inherit: false, value: false };
    expect(bodyFromDraft(draft, 'project').publicSdkEnabled).toBe(false);
  });

  it('omits an off switch at workspace scope, where absent and false mean the same thing', () => {
    // Keeps the invariant that a blank workspace form saves an empty body: there is nothing above
    // a workspace to inherit from, so a stored false adds no information.
    expect(bodyFromDraft(emptyDraft('tenant'), 'tenant')).toEqual({});
  });

  it('writes true at either scope', () => {
    for (const scope of ['tenant', 'project'] as const) {
      const draft = emptyDraft(scope);
      draft.publicSdkEnabled = { inherit: false, value: true };
      expect(bodyFromDraft(draft, scope).publicSdkEnabled).toBe(true);
    }
  });

  it('round-trips all three project states', () => {
    const bodies: SdkSettingsBody[] = [{}, { publicSdkEnabled: true }, { publicSdkEnabled: false }];
    for (const body of bodies) {
      const draft = draftFromBody(body, 'project');
      expect(bodyFromDraft(draft, 'project').publicSdkEnabled).toBe(body.publicSdkEnabled);
    }
  });

  it('counts as a change on its own', () => {
    const baseline = emptyDraft('project');
    const draft = { ...baseline, publicSdkEnabled: { inherit: false, value: true } };
    expect(isDraftDirty(draft, baseline)).toBe(true);
    expect(isDraftDirty(baseline, baseline)).toBe(false);
  });
});
