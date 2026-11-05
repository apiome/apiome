'use client';

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Plus, Send } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { Skeleton } from '@/app/components/ui/Skeleton';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { fetchMyPermissions, type MyPermissions } from '@/app/ade/dashboard/style-guides/api';

import { DeliveryAttemptList } from './DeliveryAttemptList';
import { DeliveryProfileForm } from './DeliveryProfileForm';
import {
  DeliveryProfilesError,
  createDeliveryProfile,
  deleteDeliveryProfile,
  fetchDeliveryProfiles,
  fetchProfileDeliveries,
  fetchRepositoryOptions,
  fetchStorageCredentialOptions,
  updateDeliveryProfile,
  type ReferenceOption,
} from './deliveryProfilesApi';
import {
  CHANNEL_LABELS,
  createBody,
  destinationSummary,
  draftFromProfile,
  emptyDraft,
  updateBody,
  type DeliveryAttempt,
  type DeliveryProfile,
  type DeliveryProfileDraft,
} from './deliveryProfilesModel';

/** What the panel beside the list shows. */
type Mode =
  | { kind: 'idle' }
  | { kind: 'create' }
  | { kind: 'edit'; profile: DeliveryProfile }
  | { kind: 'trail'; profile: DeliveryProfile };

/** Props for {@link DeliveryProfilesClient}. */
export interface DeliveryProfilesClientProps {
  /** The Export studio tab strip, drawn under the header. */
  tabs?: ReactNode;
}

/**
 * Export studio's **Delivery** tab — the workspace's delivery profiles (MFX-38.4, #4331).
 *
 * A delivery profile saves a destination for finished exports once: a git repository, a webhook or
 * an S3-compatible bucket, with the credential it delivers with. The Review step offers the profiles
 * for a new export ("Deliver when it completes") and for a finished one ("Deliver now"); this tab
 * creates, changes and deletes them, and shows each one's delivery trail across exports.
 *
 * Members without `projects:edit` see the profiles and their trails read-only: the REST layer is the
 * enforcer, this is only the affordance. No secret is ever shown — a webhook's is write-only.
 *
 * @param props See {@link DeliveryProfilesClientProps}.
 * @returns The tab.
 */
export default function DeliveryProfilesClient({ tabs }: DeliveryProfilesClientProps = {}) {
  const [profiles, setProfiles] = useState<DeliveryProfile[]>([]);
  const [repositories, setRepositories] = useState<ReferenceOption[]>([]);
  const [credentials, setCredentials] = useState<ReferenceOption[]>([]);
  const [permissions, setPermissions] = useState<MyPermissions | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>({ kind: 'idle' });
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<{ message: string; errors: string[] } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [trail, setTrail] = useState<DeliveryAttempt[] | null>(null);

  const canEdit = permissions
    ? permissions.is_admin === true ||
      (Array.isArray(permissions.permissions) && permissions.permissions.includes('projects:edit'))
    : false;

  const names = useMemo(
    () => Object.fromEntries([...repositories, ...credentials].map((option) => [option.id, option.label])),
    [repositories, credentials],
  );

  const reload = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setProfiles(await fetchDeliveryProfiles());
    } catch (cause) {
      setLoadError(cause instanceof Error ? cause.message : 'Could not load the delivery profiles');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    let live = true;
    void Promise.all([fetchRepositoryOptions(), fetchStorageCredentialOptions(), fetchMyPermissions()]).then(
      ([repos, creds, perms]) => {
        if (!live) return;
        setRepositories(repos);
        setCredentials(creds);
        setPermissions(perms);
      },
    );
    return () => {
      live = false;
    };
  }, [reload]);

  const openTrail = useCallback(async (profile: DeliveryProfile) => {
    setMode({ kind: 'trail', profile });
    setTrail(null);
    try {
      setTrail(await fetchProfileDeliveries(profile.id));
    } catch {
      setTrail([]);
    }
  }, []);

  const save = useCallback(
    async (draft: DeliveryProfileDraft) => {
      setSaving(true);
      setServerError(null);
      try {
        if (mode.kind === 'edit') {
          await updateDeliveryProfile(mode.profile.id, updateBody(draft, draftFromProfile(mode.profile)));
        } else {
          await createDeliveryProfile(createBody(draft));
        }
        setMode({ kind: 'idle' });
        await reload();
      } catch (cause) {
        setServerError({
          message: cause instanceof Error ? cause.message : 'Could not save the profile',
          errors: cause instanceof DeliveryProfilesError ? cause.errors : [],
        });
      } finally {
        setSaving(false);
      }
    },
    [mode, reload],
  );

  const remove = useCallback(
    async (profile: DeliveryProfile) => {
      setSaving(true);
      try {
        await deleteDeliveryProfile(profile.id);
        setConfirmDelete(null);
        if ((mode.kind === 'edit' || mode.kind === 'trail') && mode.profile.id === profile.id) {
          setMode({ kind: 'idle' });
        }
        await reload();
      } catch (cause) {
        setLoadError(cause instanceof Error ? cause.message : 'Could not delete the profile');
      } finally {
        setSaving(false);
      }
    },
    [mode, reload],
  );

  const startCreate = () => {
    setServerError(null);
    setMode({ kind: 'create' });
  };

  return (
    <Page data-testid="delivery-profiles">
      <PageHeader
        breadcrumb={[{ label: 'Home', href: '/ade/dashboard' }, { label: 'Ship' }, { label: 'Export studio' }]}
        title="Export studio"
        description="Saved destinations finished exports are delivered to: git, webhook or object storage."
        tabs={tabs}
        actions={
          canEdit ? (
            <Button onClick={startCreate} data-testid="xdlv-new">
              <Plus className="h-4 w-4" aria-hidden />
              New profile
            </Button>
          ) : null
        }
      />
      <PageBody>
        {!canEdit && permissions !== null ? (
          <Alert variant="info" className="xdlv-notice">
            Read-only for members. Changing delivery profiles needs <code className="mono">projects:edit</code>.
          </Alert>
        ) : null}
        {loadError ? (
          <Alert variant="danger" className="xdlv-notice">
            {loadError}
          </Alert>
        ) : null}

        <div className="xdlv-layout">
          <section className="xdlv-list" aria-label="Delivery profiles">
            {loading ? (
              <div data-testid="xdlv-loading">
                <span className="sr-only" role="status">
                  Loading delivery profiles…
                </span>
                <Skeleton className="xdlv-skeleton" />
                <Skeleton className="xdlv-skeleton" />
              </div>
            ) : profiles.length === 0 ? (
              <EmptyState
                icon={<Send />}
                title="No delivery profiles yet"
                description="Save a git, webhook or bucket destination to deliver exports by name."
                action={canEdit ? <Button onClick={startCreate}>New profile</Button> : undefined}
              />
            ) : (
              <ul className="xdlv-profiles">
                {profiles.map((profile) => (
                  <li key={profile.id} className="xdlv-profile" data-testid="xdlv-profile"
                    data-selected={mode.kind !== 'idle' && mode.kind !== 'create' && mode.profile.id === profile.id}>
                    <div className="xdlv-profile__head">
                      <span className="xdlv-profile__name">{profile.name}</span>
                      <span className="xdlv-profile__channel">{CHANNEL_LABELS[profile.channel]}</span>
                    </div>
                    <p className="xdlv-profile__dest mono">{destinationSummary(profile, names)}</p>
                    {profile.description ? <p className="xdlv-quiet">{profile.description}</p> : null}
                    <div className="xdlv-profile__actions">
                      <Button size="sm" variant="ghost" onClick={() => void openTrail(profile)}>
                        Deliveries
                      </Button>
                      {canEdit ? (
                        <>
                          <Button size="sm" variant="ghost" onClick={() => {
                            setServerError(null);
                            setMode({ kind: 'edit', profile });
                          }}>
                            Edit
                          </Button>
                          {confirmDelete === profile.id ? (
                            <>
                              <Button title={saving ? 'Wait for the save to finish' : undefined} size="sm" variant="danger" disabled={saving}
                                onClick={() => void remove(profile)}>
                                Delete {profile.name}
                              </Button>
                              <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>
                                Keep
                              </Button>
                            </>
                          ) : (
                            <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(profile.id)}>
                              Delete
                            </Button>
                          )}
                        </>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {mode.kind === 'create' || mode.kind === 'edit' ? (
            <section className="xdlv-panel" aria-label={mode.kind === 'create' ? 'New profile' : `Edit ${mode.profile.name}`}>
              <h2 className="xdlv-panel__title">{mode.kind === 'create' ? 'New profile' : `Edit ${mode.profile.name}`}</h2>
              <DeliveryProfileForm
                key={mode.kind === 'edit' ? mode.profile.id : 'new'}
                initial={mode.kind === 'edit' ? draftFromProfile(mode.profile) : emptyDraft()}
                creating={mode.kind === 'create'}
                repositories={repositories}
                credentials={credentials}
                saving={saving}
                serverError={serverError}
                onSubmit={(draft) => void save(draft)}
                onCancel={() => setMode({ kind: 'idle' })}
              />
            </section>
          ) : null}

          {mode.kind === 'trail' ? (
            <section className="xdlv-panel" aria-label={`Deliveries with ${mode.profile.name}`}>
              <h2 className="xdlv-panel__title">Deliveries with {mode.profile.name}</h2>
              {trail === null ? (
                <Skeleton className="xdlv-skeleton" />
              ) : (
                <DeliveryAttemptList attempts={trail} showProfile={false} label={`Deliveries with ${mode.profile.name}`}
                  emptyMessage="No export has been delivered with this profile yet." />
              )}
            </section>
          ) : null}
        </div>
      </PageBody>
    </Page>
  );
}
