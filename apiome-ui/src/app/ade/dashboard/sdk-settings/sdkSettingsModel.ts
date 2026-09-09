/**
 * The editable shape of SDK generation settings — SDK-3.4 (#4494).
 *
 * Pure, React-free translation between the stored `sdk.generation-settings.v1` body and the form
 * the screen renders, so the rule that is easy to get wrong is unit-testable on its own.
 *
 * That rule is **tri-state**. At project scope a field is one of three things, and the API keeps
 * all three apart:
 *
 * | The field is…                   | Stored as             | Effect                          |
 * |---------------------------------|-----------------------|---------------------------------|
 * | inherited                       | the key is *absent*   | the workspace value applies     |
 * | overridden with a value         | the key holds a string| that value applies              |
 * | deliberately none               | the key holds `null`  | nothing applies, workspace or not|
 *
 * The form spells that as one checkbox plus one input: *Inherit* checked is the first row,
 * unchecked with text is the second, unchecked and empty is the third.
 *
 * At workspace scope there is nothing to inherit from, so `inherit` is always false and an empty
 * field simply omits its key — a `PUT` replaces the scope's whole body, so omission is how a
 * workspace default is removed.
 *
 * SDK-3.3 (#4493) added one field that is not a text box: `publicSdkEnabled`, the switch that
 * opens the public browse portal's SDK download and snippets for a project. It keeps the same
 * three states (inherited / explicitly on / explicitly off) but carries a boolean, so it lives
 * beside the text fields rather than among them.
 */

/**
 * Package ecosystems the API accepts a name pattern for. Mirrors REST's `ECOSYSTEMS`.
 *
 * `gomod` arrived with the SDK-2.4 Go client generator (#4488): it is the generated module's
 * `go.mod` path rather than a registry name, but it is configured, merged and validated exactly
 * like the other two, so it lives in the same list.
 */
export const SDK_ECOSYSTEMS = ['npm', 'pypi', 'gomod'] as const;

export type SdkEcosystem = (typeof SDK_ECOSYSTEMS)[number];

/** Every editable field, in the order the form lays them out. */
export const SDK_FIELD_KEYS = ['npm', 'pypi', 'gomod', 'licenseHeader', 'userAgent'] as const;

export type SdkFieldKey = (typeof SDK_FIELD_KEYS)[number];

/** Which scope a form is editing. */
export type SdkSettingsScope = 'tenant' | 'project';

/** One field's editable state. */
export interface SdkFieldDraft {
  /** True when the field takes the workspace value. Always false at workspace scope. */
  inherit: boolean;
  /** The text in the input. Empty with `inherit` false means "deliberately none". */
  value: string;
}

/**
 * The public-SDK switch's editable state — SDK-3.3 (#4493).
 *
 * The same tri-state rule as a text field, but the "value" is a boolean rather than a string, so
 * it has its own shape: inherited, explicitly on, or explicitly off. Being a gate rather than
 * branding, "deliberately none" and "off" are the same answer — an explicit `null` and an
 * explicit `false` both close it — so the form only ever writes a boolean.
 */
export interface SdkToggleDraft {
  /** True when the project takes the workspace answer. Always false at workspace scope. */
  inherit: boolean;
  /** The switch's position when it is not inheriting. */
  value: boolean;
}

/** The whole form: the four text fields plus the public-SDK switch. */
export type SdkSettingsDraft = Record<SdkFieldKey, SdkFieldDraft> & {
  publicSdkEnabled: SdkToggleDraft;
};

/** A stored settings body, exactly as the API returns it in `scopeBody`. */
export interface SdkSettingsBody {
  schemaVersion?: string;
  packageNamePatterns?: Record<string, string | null> | null;
  licenseHeader?: string | null;
  userAgent?: string | null;
  publicSdkEnabled?: boolean | null;
}

/** The merged settings the API reports as in force. */
export interface SdkSettings {
  packageNamePatterns: Record<string, string>;
  licenseHeader: string | null;
  userAgent: string | null;
  /** Whether the public browse portal may serve this project's SDK (SDK-3.3). */
  publicSdkEnabled: boolean;
}

/** The merged settings with their `{tokens}` substituted for the scope. */
export interface SdkResolvedBranding {
  packageNames: Record<string, string>;
  licenseHeader: string | null;
  userAgent: string | null;
}

/** `GET`/`PUT`/`DELETE` response — the settings in force for a scope. */
export interface SdkSettingsResponse {
  schemaVersion: string;
  source: 'default' | 'tenant' | 'project' | 'merged';
  contentFingerprint: string;
  settings: SdkSettings;
  resolved: SdkResolvedBranding;
  scope: SdkSettingsScope;
  scopeBody: SdkSettingsBody | null;
  tenantSettingsId: string | null;
  projectSettingsId: string | null;
  updatedAt: string | null;
  updatedBy: string | null;
  degraded: boolean;
}

/** A field with nothing in it and nothing inherited — the state a fresh form starts in. */
const EMPTY_FIELD: SdkFieldDraft = { inherit: false, value: '' };

/**
 * An empty form for a scope.
 *
 * @param scope Which scope the form edits.
 * @returns A draft with every field inheriting (project scope) or blank (workspace scope).
 */
export function emptyDraft(scope: SdkSettingsScope): SdkSettingsDraft {
  const field: SdkFieldDraft = { inherit: scope === 'project', value: '' };
  return {
    npm: { ...field },
    pypi: { ...field },
    gomod: { ...field },
    licenseHeader: { ...field },
    userAgent: { ...field },
    // Off, matching the API's default: public SDK access is a permission, and "not configured"
    // has to read as "not allowed".
    publicSdkEnabled: { inherit: scope === 'project', value: false },
  };
}

/**
 * Read one field out of a stored body.
 *
 * @param present Whether the body names this key at all.
 * @param stored The stored value, which may be `null`.
 * @param scope Which scope the form edits.
 * @returns The field's draft state.
 */
function fieldFrom(
  present: boolean,
  stored: string | null | undefined,
  scope: SdkSettingsScope,
): SdkFieldDraft {
  // At workspace scope there is nothing above to inherit from, so an absent key and an explicit
  // null are the same thing: a blank field.
  if (scope === 'tenant') return { inherit: false, value: stored ?? '' };
  if (!present) return { ...EMPTY_FIELD, inherit: true };
  return { inherit: false, value: stored ?? '' };
}

/**
 * Turn a scope's stored body into the form's state.
 *
 * @param body The `scopeBody` from the API, or `null` when nothing is saved at this scope.
 * @param scope Which scope the form edits.
 * @returns The draft to render.
 */
export function draftFromBody(
  body: SdkSettingsBody | null | undefined,
  scope: SdkSettingsScope,
): SdkSettingsDraft {
  if (!body) return emptyDraft(scope);
  const patterns = body.packageNamePatterns;
  // `packageNamePatterns: null` clears every ecosystem at once, which is not the same as the key
  // being absent — so an explicitly nulled map makes each ecosystem "deliberately none".
  const patternsCleared = 'packageNamePatterns' in body && patterns === null;
  const patternPresent = (key: SdkEcosystem): boolean =>
    patternsCleared || (!!patterns && key in patterns);
  const patternValue = (key: SdkEcosystem): string | null | undefined =>
    patternsCleared ? null : patterns?.[key];

  return {
    npm: fieldFrom(patternPresent('npm'), patternValue('npm'), scope),
    pypi: fieldFrom(patternPresent('pypi'), patternValue('pypi'), scope),
    gomod: fieldFrom(patternPresent('gomod'), patternValue('gomod'), scope),
    licenseHeader: fieldFrom('licenseHeader' in body, body.licenseHeader, scope),
    userAgent: fieldFrom('userAgent' in body, body.userAgent, scope),
    publicSdkEnabled: toggleFrom('publicSdkEnabled' in body, body.publicSdkEnabled, scope),
  };
}

/**
 * Read the public-SDK switch out of a stored body.
 *
 * @param present Whether the body names the key at all.
 * @param stored The stored value, which may be `null`.
 * @param scope Which scope the form edits.
 * @returns The switch's draft state.
 */
function toggleFrom(
  present: boolean,
  stored: boolean | null | undefined,
  scope: SdkSettingsScope,
): SdkToggleDraft {
  if (scope === 'tenant') return { inherit: false, value: stored === true };
  if (!present) return { inherit: true, value: false };
  // An explicit `null` blocks inheritance and means "none", which for a gate is "off".
  return { inherit: false, value: stored === true };
}

/**
 * Render one field back into the value a body carries for it.
 *
 * @param field The field's draft state.
 * @param scope Which scope the form edits.
 * @returns `undefined` to omit the key, otherwise the string or `null` to store.
 */
function bodyValue(
  field: SdkFieldDraft,
  scope: SdkSettingsScope,
): string | null | undefined {
  if (field.inherit) return undefined;
  const value = field.value.trim();
  if (value) return value;
  // Workspace scope: an empty field omits its key, because a `PUT` replaces the whole body and
  // omission is how a default is removed. Project scope: an empty field is a deliberate "none",
  // which is the only way to stop a workspace value from applying.
  return scope === 'tenant' ? undefined : null;
}

/**
 * Turn the form's state into the body to `PUT`.
 *
 * @param draft The form's state.
 * @param scope Which scope the form edits.
 * @returns The `sdk.generation-settings.v1` body, carrying only the keys the form actually says
 *   something about.
 */
export function bodyFromDraft(
  draft: SdkSettingsDraft,
  scope: SdkSettingsScope,
): SdkSettingsBody {
  const body: SdkSettingsBody = {};

  const patterns: Record<string, string | null> = {};
  let namesAny = false;
  for (const ecosystem of SDK_ECOSYSTEMS) {
    const value = bodyValue(draft[ecosystem], scope);
    if (value === undefined) continue;
    patterns[ecosystem] = value;
    namesAny = true;
  }
  if (namesAny) body.packageNamePatterns = patterns;

  const header = bodyValue(draft.licenseHeader, scope);
  if (header !== undefined) body.licenseHeader = header;

  const agent = bodyValue(draft.userAgent, scope);
  if (agent !== undefined) body.userAgent = agent;

  // The switch omits its key when inheriting, and never writes `null`: for a gate, `false` says
  // the same thing and reads unambiguously.
  //
  // At workspace scope an *off* switch omits its key too, exactly as an empty text field does.
  // There is nothing above a workspace to inherit from, so a stored `false` and an absent key
  // resolve identically — and omitting keeps the invariant that a blank workspace form saves an
  // empty body, configuring nothing.
  if (!draft.publicSdkEnabled.inherit) {
    if (draft.publicSdkEnabled.value || scope === 'project') {
      body.publicSdkEnabled = draft.publicSdkEnabled.value;
    }
  }

  return body;
}

/**
 * Whether a draft differs from the last-saved one.
 *
 * @param draft The current form state.
 * @param baseline The state the form was loaded or last saved with.
 * @returns True when there is something to save.
 */
export function isDraftDirty(draft: SdkSettingsDraft, baseline: SdkSettingsDraft): boolean {
  const textChanged = SDK_FIELD_KEYS.some(
    (key) =>
      draft[key].inherit !== baseline[key].inherit ||
      draft[key].value.trim() !== baseline[key].value.trim(),
  );
  const toggleChanged =
    draft.publicSdkEnabled.inherit !== baseline.publicSdkEnabled.inherit ||
    draft.publicSdkEnabled.value !== baseline.publicSdkEnabled.value;
  return textChanged || toggleChanged;
}

/**
 * Whether a scope has anything saved of its own.
 *
 * Drives the "Clear override" affordance: a scope that inherits everything has nothing to clear,
 * and offering the button anyway would make a no-op look like an action.
 *
 * @param response The API's answer for the scope.
 * @returns True when a row exists at exactly this scope.
 */
export function hasScopeSettings(response: SdkSettingsResponse | null): boolean {
  if (!response) return false;
  return response.scope === 'project'
    ? response.projectSettingsId !== null
    : response.tenantSettingsId !== null;
}

/**
 * A one-line summary of where the settings in force came from.
 *
 * @param response The API's answer for the scope.
 * @returns The sentence to show under the heading.
 */
export function describeSource(response: SdkSettingsResponse | null): string {
  if (!response) return 'Loading…';
  switch (response.source) {
    case 'merged':
      return 'This project overrides some of the workspace defaults.';
    case 'project':
      return 'These settings are set on this project. The workspace has no defaults.';
    case 'tenant':
      return response.scope === 'project'
        ? 'This project inherits every workspace default.'
        : 'These are the workspace defaults every project inherits.';
    default:
      return 'Nothing is configured, so generated artifacts carry no branding.';
  }
}
