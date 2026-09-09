'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Braces, Globe, Package, Scale, Tag } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Card, CardContent, CardFooter, CardHeader } from '@/app/components/ui/Card';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Skeleton } from '@/app/components/ui/Skeleton';
import { Spinner } from '@/app/components/ui/Spinner';
import { Switch } from '@/app/components/ui/Switch';
import { Textarea } from '@/app/components/ui/Textarea';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { useUnsavedChangesPrompt } from '@/app/hooks/useUnsavedChangesPrompt';

import {
  SdkSettingsError,
  clearSdkSettings,
  fetchMyPermissions,
  fetchProjectOptions,
  fetchSdkSettings,
  saveSdkSettings,
  type MyPermissions,
  type ProjectOption,
} from './api';
import {
  SDK_FIELD_KEYS,
  bodyFromDraft,
  describeSource,
  draftFromBody,
  emptyDraft,
  hasScopeSettings,
  isDraftDirty,
  type SdkFieldKey,
  type SdkSettingsDraft,
  type SdkToggleDraft,
  type SdkSettingsResponse,
  type SdkSettingsScope,
} from './sdkSettingsModel';

/**
 * SDK settings — `/ade/dashboard/sdk-settings` (SDK-3.4, #4494).
 *
 * ### What this page owns
 *
 * The generation defaults an organisation's artifacts carry: the package name pattern per
 * ecosystem, the licence header stamped onto generated source, and the user-agent generated
 * clients send for API-side traffic attribution. It sits in **Ship**, beside Export studio, for
 * the same reason: both decide the shape of what leaves the platform.
 *
 * SDK-3.3 (#4493) added one more, and it is a different kind of thing: **Public SDK access**, the
 * switch that lets anonymous visitors to the public browse portal download this project's client
 * kit and read its per-operation code examples. The other three fields decide what generated code
 * *looks* like; this one decides who may have it. It is off unless someone turns it on, so a
 * project is never published to the world by inaction.
 *
 * ### One form, two scopes
 *
 * The scope picker chooses between the workspace defaults and one project's override; the form
 * below is the same either way, so there is one set of field rules to learn rather than two
 * screens to keep in step. The API merges the two **key by key**, so a project that overrides
 * only its user-agent still inherits the workspace package pattern.
 *
 * ### The Inherit checkbox is the third state
 *
 * At project scope a field is one of three things — inherited, overridden with a value, or
 * deliberately none — and the last is the one a plain text input cannot express. Unticking
 * *Inherit* and leaving the box empty is how a project says "no licence header at all, whatever
 * the workspace says". `sdkSettingsModel.ts` owns that translation and is where its rules are
 * tested; this component only renders it.
 *
 * ### Non-editors get a read-only screen with the reason on it
 *
 * Controls stay visible and disabled rather than disappearing, so a member can see what the
 * workspace has configured and who to ask. The REST layer is the real enforcer
 * (`projects:view` to read, `projects:edit` to change); this is only the affordance.
 */

/** The scope picker's value for the workspace defaults, which name no project. */
const WORKSPACE = '';

/** One editable field's copy, in the order the form lays them out. */
const FIELDS: {
  key: SdkFieldKey;
  label: string;
  hint: string;
  placeholder: string;
  multiline?: boolean;
}[] = [
  {
    key: 'npm',
    label: 'npm package name',
    hint: 'Lower-case, with an optional @scope/ prefix.',
    placeholder: '@acme/{project}-sdk',
  },
  {
    key: 'pypi',
    label: 'PyPI distribution name',
    hint: 'Letters and digits at both ends; . - _ inside.',
    placeholder: 'acme-{project}',
  },
  {
    key: 'licenseHeader',
    label: 'Licence header',
    hint: 'Prepended to generated source as a comment. May span lines.',
    placeholder: 'Copyright (c) {year} Acme, Inc.\nSPDX-License-Identifier: Apache-2.0',
    multiline: true,
  },
  {
    key: 'userAgent',
    label: 'User agent',
    hint: 'Sent by generated clients, so your API can attribute their traffic.',
    placeholder: 'acme-sdk/{version}',
  },
];

/** The substitution tokens the API accepts, shown once above the form. */
const TOKENS = ['{tenant}', '{project}', '{version}', '{year}'];

export default function SdkSettingsClient() {
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [permissions, setPermissions] = useState<MyPermissions | null>(null);
  const [scopeRef, setScopeRef] = useState<string>(WORKSPACE);

  const [settings, setSettings] = useState<SdkSettingsResponse | null>(null);
  const [draft, setDraft] = useState<SdkSettingsDraft>(() => emptyDraft('tenant'));
  const [baseline, setBaseline] = useState<SdkSettingsDraft>(() => emptyDraft('tenant'));

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);

  const scope: SdkSettingsScope = scopeRef === WORKSPACE ? 'tenant' : 'project';
  const projectRef = scopeRef === WORKSPACE ? null : scopeRef;

  // Defensive on both fields: the permissions read degrades to `null` on any failure, and a
  // truncated payload must leave the screen read-only rather than crashing it — a member who
  // cannot edit still needs to see what the workspace has configured.
  const canEdit = permissions
    ? permissions.is_admin === true ||
      (Array.isArray(permissions.permissions) &&
        permissions.permissions.includes('projects:edit'))
    : false;
  const readOnly = !canEdit;
  const disabled = readOnly || saving;

  const dirty = useMemo(() => isDraftDirty(draft, baseline), [draft, baseline]);
  useUnsavedChangesPrompt(dirty);

  // The pickers and the read-only gate are loaded once; the settings reload per scope.
  useEffect(() => {
    let live = true;
    void Promise.all([fetchProjectOptions(), fetchMyPermissions()]).then(([rows, perms]) => {
      if (!live) return;
      setProjects(rows);
      setPermissions(perms);
    });
    return () => {
      live = false;
    };
  }, []);

  const load = useCallback(
    async (ref: string) => {
      setLoading(true);
      setError(null);
      setProblems([]);
      try {
        const next = await fetchSdkSettings(ref === WORKSPACE ? null : ref);
        const nextDraft = draftFromBody(next.scopeBody, next.scope);
        setSettings(next);
        setDraft(nextDraft);
        setBaseline(nextDraft);
      } catch (cause) {
        setSettings(null);
        setError(cause instanceof Error ? cause.message : 'Could not load these settings');
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(scopeRef);
  }, [load, scopeRef]);

  /** Apply one field's edit. */
  const setField = useCallback(
    (key: SdkFieldKey, patch: Partial<SdkSettingsDraft[SdkFieldKey]>) => {
      setDraft((current) => ({ ...current, [key]: { ...current[key], ...patch } }));
    },
    [],
  );

  const setPublicSdk = useCallback((patch: Partial<SdkToggleDraft>) => {
    setDraft((current) => ({
      ...current,
      publicSdkEnabled: { ...current.publicSdkEnabled, ...patch },
    }));
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    setProblems([]);
    try {
      const next = await saveSdkSettings(projectRef, bodyFromDraft(draft, scope));
      const nextDraft = draftFromBody(next.scopeBody, next.scope);
      setSettings(next);
      setDraft(nextDraft);
      setBaseline(nextDraft);
    } catch (cause) {
      // A 422 lists every problem at once; showing one and hiding the rest would make fixing
      // them a sequence of round trips.
      setProblems(cause instanceof SdkSettingsError ? cause.errors : []);
      setError(cause instanceof Error ? cause.message : 'Could not save these settings');
    } finally {
      setSaving(false);
    }
  }, [draft, projectRef, scope]);

  const clear = useCallback(async () => {
    setSaving(true);
    setError(null);
    setProblems([]);
    try {
      const next = await clearSdkSettings(projectRef);
      const nextDraft = draftFromBody(next.scopeBody, next.scope);
      setSettings(next);
      setDraft(nextDraft);
      setBaseline(nextDraft);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not clear these settings');
    } finally {
      setSaving(false);
    }
  }, [projectRef]);

  const scopeLabel =
    scope === 'tenant'
      ? 'Workspace defaults'
      : projects.find((row) => row.id === scopeRef)?.name || 'This project';

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: 'Home', href: '/ade/dashboard' },
          { label: 'Ship' },
          { label: 'SDK settings' },
        ]}
        title="SDK settings"
        description="How generated packages are named and branded, for this workspace and per project."
      />
      <PageBody>
        {readOnly && permissions !== null ? (
          <Alert variant="info" className="sdks-notice">
            Read-only for members. Changing generation settings needs <code className="mono">projects:edit</code>.
          </Alert>
        ) : null}

        <div className="sdks-scope">
          <Label htmlFor="sdk-settings-scope" className="sdks-scope__label">
            Scope
          </Label>
          <select
            id="sdk-settings-scope"
            className="hive-control sdks-scope__select"
            value={scopeRef}
            disabled={saving}
            onChange={(event) => setScopeRef(event.target.value)}
          >
            <option value={WORKSPACE}>Workspace defaults</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          <p className="sdks-scope__hint">{describeSource(settings)}</p>
        </div>

        {loading ? (
          <div className="sdks-skeleton" data-testid="sdk-settings-loading">
            <span className="sr-only" role="status">
              Loading SDK settings…
            </span>
            <Skeleton className="sdks-skeleton__header" />
            <Skeleton className="sdks-skeleton__block" />
            <Skeleton className="sdks-skeleton__block" />
          </div>
        ) : (
          <>
            {error ? (
              <Alert variant="error" className="sdks-notice">
                {error}
                {problems.length > 0 ? (
                  <ul className="sdks-problems">
                    {problems.map((problem) => (
                      <li key={problem}>{problem}</li>
                    ))}
                  </ul>
                ) : null}
              </Alert>
            ) : null}

            {settings?.degraded ? (
              <Alert variant="warning" className="sdks-notice">
                Some saved settings could not be read and were skipped. What is shown below is what
                is actually being applied.
              </Alert>
            ) : null}

            <Card className="sdks-card" data-testid="sdk-settings-form">
              <CardHeader className="sdks-card__header">
                <span className="tnt-icon-tile" data-tone="accent">
                  <Package aria-hidden />
                </span>
                <span className="sdks-card__text">
                  <h2 className="sdks-card__title">{scopeLabel}</h2>
                  <p className="sdks-card__desc">
                    Patterns may use{' '}
                    {TOKENS.map((token, index) => (
                      <span key={token}>
                        {index > 0 ? ', ' : ''}
                        <code className="mono">{token}</code>
                      </span>
                    ))}
                    . A package name whose tokens cannot be filled is left unset rather than
                    guessed.
                  </p>
                </span>
              </CardHeader>

              <CardContent className="sdks-body">
                {FIELDS.map((field) => {
                  const state = draft[field.key];
                  const inputId = `sdk-settings-${field.key}`;
                  return (
                    <div className="sdks-field" key={field.key}>
                      <div className="sdks-field__head">
                        <Label htmlFor={inputId} className="sdks-field__label">
                          {field.label}
                        </Label>
                        {scope === 'project' ? (
                          <label className="sdks-field__inherit" htmlFor={`${inputId}-inherit`}>
                            <input
                              id={`${inputId}-inherit`}
                              type="checkbox"
                              className="hive-control sdks-field__box"
                              checked={state.inherit}
                              disabled={disabled}
                              onChange={(event) =>
                                setField(field.key, { inherit: event.target.checked })
                              }
                            />
                            Inherit from workspace
                          </label>
                        ) : null}
                      </div>

                      {field.multiline ? (
                        <Textarea
                          id={inputId}
                          className="sdks-field__control mono"
                          value={state.value}
                          placeholder={field.placeholder}
                          disabled={disabled || state.inherit}
                          onChange={(event) => setField(field.key, { value: event.target.value })}
                        />
                      ) : (
                        <Input
                          id={inputId}
                          className="sdks-field__control mono"
                          value={state.value}
                          placeholder={field.placeholder}
                          disabled={disabled || state.inherit}
                          onChange={(event) => setField(field.key, { value: event.target.value })}
                        />
                      )}

                      <p className="sdks-field__hint">
                        {state.inherit
                          ? 'Takes whatever the workspace defaults say.'
                          : state.value.trim() === '' && scope === 'project'
                            ? 'Empty and not inherited: this project deliberately has none.'
                            : field.hint}
                      </p>
                    </div>
                  );
                })}

                <div className="sdks-field">
                  <div className="sdks-field__head">
                    <Label htmlFor="sdk-settings-publicSdkEnabled" className="sdks-field__label">
                      Public SDK access
                    </Label>
                    {scope === 'project' ? (
                      <label
                        className="sdks-field__inherit"
                        htmlFor="sdk-settings-publicSdkEnabled-inherit"
                      >
                        <input
                          id="sdk-settings-publicSdkEnabled-inherit"
                          type="checkbox"
                          className="hive-control sdks-field__box"
                          checked={draft.publicSdkEnabled.inherit}
                          disabled={disabled}
                          onChange={(event) => setPublicSdk({ inherit: event.target.checked })}
                        />
                        Inherit from workspace
                      </label>
                    ) : null}
                  </div>

                  <div className="sdks-toggle__row">
                    <Switch
                      id="sdk-settings-publicSdkEnabled"
                      aria-label="Allow anonymous visitors to download this SDK"
                      checked={draft.publicSdkEnabled.value}
                      disabled={disabled || draft.publicSdkEnabled.inherit}
                      onCheckedChange={(checked) => setPublicSdk({ value: checked })}
                    />
                    <span className="sdks-toggle__state">
                      {draft.publicSdkEnabled.inherit
                        ? 'Inherited'
                        : draft.publicSdkEnabled.value
                          ? 'Anyone can download the SDK'
                          : 'No public SDK'}
                    </span>
                  </div>

                  <p className="sdks-field__hint">
                    {draft.publicSdkEnabled.inherit
                      ? 'Takes whatever the workspace defaults say.'
                      : draft.publicSdkEnabled.value
                        ? 'Anonymous visitors to the published version can download a client kit ' +
                          'and read per-operation code examples on the public portal.'
                        : 'The public portal shows no SDK download and no code examples, and ' +
                          'their URLs return 404.'}
                  </p>
                </div>
              </CardContent>

              <CardFooter className="sdks-footer">
                <span className="sdks-footer__state" role="status" aria-live="polite">
                  {saving ? (
                    <>
                      <Spinner className="sdks-footer__spinner" aria-hidden /> Saving…
                    </>
                  ) : dirty ? (
                    'Unsaved changes'
                  ) : (
                    'Saved'
                  )}
                </span>
                {hasScopeSettings(settings) ? (
                  <Button variant="secondary" disabled={disabled} onClick={() => void clear()}>
                    {scope === 'project' ? 'Clear override' : 'Clear defaults'}
                  </Button>
                ) : null}
                <Button disabled={disabled || !dirty} onClick={() => void save()}>
                  Save
                </Button>
              </CardFooter>
            </Card>

            <Card className="sdks-card" data-testid="sdk-settings-preview">
              <CardHeader className="sdks-card__header">
                <span className="tnt-icon-tile" data-tone="ok">
                  <Braces aria-hidden />
                </span>
                <span className="sdks-card__text">
                  <h2 className="sdks-card__title">In force</h2>
                  <p className="sdks-card__desc">
                    What these settings resolve to right now, after the workspace and project
                    scopes are merged.
                  </p>
                </span>
                {settings ? (
                  <Badge variant="secondary" className="sdks-fingerprint mono">
                    {settings.contentFingerprint.slice(0, 19)}
                  </Badge>
                ) : null}
              </CardHeader>
              <CardContent className="sdks-preview">
                <dl className="sdks-preview__list">
                  <div className="sdks-preview__row">
                    <dt className="sdks-preview__term">
                      <Package aria-hidden className="sdks-preview__glyph" /> Package names
                    </dt>
                    <dd className="sdks-preview__value mono">
                      {Object.keys(settings?.resolved.packageNames ?? {}).length === 0
                        ? '—'
                        : Object.entries(settings?.resolved.packageNames ?? {})
                            .map(([ecosystem, name]) => `${ecosystem}: ${name}`)
                            .join('  ·  ')}
                    </dd>
                  </div>
                  <div className="sdks-preview__row">
                    <dt className="sdks-preview__term">
                      <Tag aria-hidden className="sdks-preview__glyph" /> User agent
                    </dt>
                    <dd className="sdks-preview__value mono">
                      {settings?.resolved.userAgent || '—'}
                    </dd>
                  </div>
                  <div className="sdks-preview__row">
                    <dt className="sdks-preview__term">
                      <Scale aria-hidden className="sdks-preview__glyph" /> Licence header
                    </dt>
                    <dd className="sdks-preview__value mono sdks-preview__value--block">
                      {settings?.resolved.licenseHeader || '—'}
                    </dd>
                  </div>
                  <div className="sdks-preview__row">
                    <dt className="sdks-preview__term">
                      <Globe aria-hidden className="sdks-preview__glyph" /> Public SDK
                    </dt>
                    <dd className="sdks-preview__value">
                      {settings?.settings.publicSdkEnabled ? 'Enabled' : 'Disabled'}
                    </dd>
                  </div>
                </dl>
              </CardContent>
            </Card>
          </>
        )}
      </PageBody>
    </Page>
  );
}

/** Every field key, re-exported so a test can walk the form without restating the list. */
export { SDK_FIELD_KEYS };
