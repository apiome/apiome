'use client';

/**
 * **A pacticipant's Settings** — `/ade/dashboard/pacts/pacticipants/{handle}/settings` (PFX-8.10,
 * #7307).
 *
 * Authority: `docs/mockups/contracts/pacticipant.html` (Settings). Three sections and an aside:
 *
 * - **General** — **Name**, **Display name**, **Main branch**, **Repository**, **Linked project**
 *   and **Labels**, saved together with **Save changes** (only what changed is sent: one `PATCH`,
 *   then one request per label added or removed) and reset with **Discard**. Renaming keeps the
 *   handle and the history, and the old name keeps resolving; a name another pacticipant has is
 *   refused under **Name**. A role without `pacts:edit` sees the same values without inputs.
 * - **Owner** — the shipped owner panel (PFX-6.4), unchanged.
 * - **Danger zone** — **Delete {name}…** (`pacts:delete` only) opens the delete dialog.
 * - The aside: the handle, when it was registered, the names it had before, and **The same, from
 *   anywhere** (`apiome pact create-or-update-pacticipant`, Pact CLI, REST).
 *
 * After a save the page says what happened in one line — and, when a label failed, which one and
 * why; nothing is dropped silently.
 */

import * as React from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { RefreshCw, Trash2 } from 'lucide-react';
import { Button, CommandBlock, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { useMyPermissions } from '@/app/components/ade/access/useMyPermissions';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import {
  PACTICIPANTS_ROUTE,
  formatWhen,
  pacticipantRoute,
  type Pacticipant,
} from '@lib/pact-pacticipants';
import {
  DELETE_PERMISSION,
  EDIT_PERMISSION,
  formFromPacticipant,
  isDirty,
  isSendable,
  pacticipantCommandAction,
  settingsChanges,
  settingsProblems,
  type SettingsForm,
} from '@lib/pact-pacticipant-settings';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { fetchProjects, type ProjectChoice } from '../pactPublish/publishApi';
import { DeletePacticipantDialog, type DeleteStage } from './DeletePacticipantDialog';
import { PacticipantFields, PacticipantValues } from './PacticipantFields';
import PacticipantOwnerPanel from './PacticipantOwnerPanel';
import { PacticipantSubTabs } from './PacticipantSubTabs';
import { changeLabel, fetchPacticipant, savePacticipant } from './pacticipantsApi';
import { describeFailure } from './describeFailure';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** What the last save did, said in one line. */
type Outcome = { tone: 'ok' | 'danger'; text: string } | null;

/** Props for {@link PacticipantSettingsClient}. */
export interface PacticipantSettingsClientProps {
  /** The pacticipant's handle, from the route. */
  slug: string;
  /** For fixture renders: open the delete dialog at this stage. */
  initialDeleteStage?: DeleteStage;
}

/**
 * The Settings page.
 *
 * @param props - See {@link PacticipantSettingsClientProps}.
 * @returns The page.
 */
export default function PacticipantSettingsClient({
  slug,
  initialDeleteStage,
}: PacticipantSettingsClientProps) {
  const router = useRouter();
  const permissions = useMyPermissions();
  const canEdit = permissions.status === 'ready' && permissions.can(EDIT_PERMISSION);
  const canDelete = permissions.status === 'ready' && permissions.can(DELETE_PERMISSION);

  const [pacticipant, setPacticipant] = React.useState<Pacticipant | null>(null);
  const [readError, setReadError] = React.useState<string | null>(null);
  const [original, setOriginal] = React.useState<SettingsForm | null>(null);
  const [form, setForm] = React.useState<SettingsForm | null>(null);
  const [projects, setProjects] = React.useState<ProjectChoice[] | { error: string } | null>(null);
  const [sent, setSent] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [nameTaken, setNameTaken] = React.useState<string | null>(null);
  const [outcome, setOutcome] = React.useState<Outcome>(null);
  const [deleting, setDeleting] = React.useState(Boolean(initialDeleteStage));

  const adopt = React.useCallback((record: Pacticipant) => {
    const read = formFromPacticipant(record);
    setPacticipant(record);
    setOriginal(read);
    setForm(read);
  }, []);

  const load = React.useCallback(async () => {
    setReadError(null);
    setPacticipant(null);
    try {
      adopt(await fetchPacticipant(slug));
    } catch (caught) {
      setReadError(describeFailure(caught, 'Could not load the pacticipant'));
    }
  }, [adopt, slug]);

  React.useEffect(() => {
    void load();
  }, [load]);

  // The projects: the select for an editor, the linked project's name for everyone.
  React.useEffect(() => {
    let live = true;
    void fetchProjects().then((answer) => {
      if (live) setProjects('error' in answer ? { error: answer.error } : answer);
    });
    return () => {
      live = false;
    };
  }, []);

  const edit = (patch: Partial<SettingsForm>) => {
    setForm((current) => (current ? { ...current, ...patch } : current));
    if ('name' in patch) setNameTaken(null);
    setOutcome(null);
  };

  const save = async () => {
    if (!form || !original || !pacticipant) return;
    setSent(true);
    if (!isSendable(settingsProblems(form))) return;
    const changes = settingsChanges(form, original);
    setSaving(true);
    setOutcome(null);
    let saved = pacticipant;
    if (changes.patch) {
      const answer = await savePacticipant(slug, changes.patch);
      if ('error' in answer) {
        setSaving(false);
        if (answer.status === 409) setNameTaken(answer.error);
        else setOutcome({ tone: 'danger', text: `Nothing was saved: ${answer.error}` });
        return;
      }
      saved = answer;
    }
    const failed: string[] = [];
    for (const label of changes.addLabels) {
      const answer = await changeLabel(slug, label, 'add');
      if ('error' in answer) failed.push(answer.error);
    }
    for (const label of changes.removeLabels) {
      const answer = await changeLabel(slug, label, 'remove');
      if ('error' in answer) failed.push(answer.error);
    }
    if (changes.addLabels.length || changes.removeLabels.length) {
      try {
        saved = await fetchPacticipant(slug);
      } catch {
        // The save went through; the labels shown are then the ones that were sent.
      }
    }
    adopt(saved);
    setSent(false);
    setSaving(false);
    const renamed = changes.patch?.name
      ? ` Renamed to ${saved.name}; the old name ${pacticipant.name} still resolves.`
      : '';
    setOutcome(
      failed.length
        ? { tone: 'danger', text: `Saved, except: ${failed.join('; ')}.${renamed}` }
        : { tone: 'ok', text: `Saved.${renamed}` },
    );
  };

  const name = pacticipant?.name ?? slug;
  const problems = form && sent ? settingsProblems(form) : {};
  const shown = nameTaken ? { ...problems, name: nameTaken } : problems;
  const projectName =
    form?.projectId && Array.isArray(projects)
      ? (projects.find((p) => p.id === form.projectId)?.name ?? null)
      : null;
  const action =
    form && original && pacticipant
      ? pacticipantCommandAction(form, {
          tenant: '',
          original: { slug: pacticipant.slug, form: original },
        })
      : null;

  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="pacticipants" />}
        title={name}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Contracts', href: CONTRACTS_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: name, href: pacticipantRoute(slug) },
          { label: 'Settings' },
        ]}
        description="Name, display name, main branch, repository, owner, linked project and labels."
      />
      <PageBody>
        <div className="ppx" data-testid="pact-pacticipant-settings">
          <PacticipantSubTabs slug={slug} active="settings" />
          {readError ? (
            <EmptyState
              variant="compact"
              tone="danger"
              title="This pacticipant could not be read"
              description={readError}
              action={
                <div className="ppx__actions">
                  <Button variant="soft" onClick={() => void load()}>
                    <RefreshCw aria-hidden />
                    Try again
                  </Button>
                  <Link className="ppx__link" href={PACTICIPANTS_ROUTE}>
                    All pacticipants
                  </Link>
                </div>
              }
            />
          ) : !pacticipant || !form || !original ? (
            <LoadingState message="Reading the pacticipant…" minHeightClassName="min-h-[6rem]" />
          ) : (
            <div className="ppx-settings">
              <div className="ppx-settings__main">
                <section
                  className="ppx__panel"
                  aria-labelledby="ppx-general-title"
                  data-testid="ppx-general"
                >
                  <div className="ppx__panel-head">
                    <h2 id="ppx-general-title" className="ppx__title">
                      General
                    </h2>
                  </div>
                  {permissions.status === 'loading' ? (
                    <LoadingState
                      message="Checking what you may change…"
                      minHeightClassName="min-h-[4rem]"
                    />
                  ) : canEdit ? (
                    <form
                      className="ppx-settings__form"
                      noValidate
                      onSubmit={(event) => {
                        event.preventDefault();
                        void save();
                      }}
                    >
                      <PacticipantFields
                        form={form}
                        onChange={edit}
                        problems={shown}
                        projects={projects}
                        idPrefix="ppx-settings"
                        nameHint="The name pacts use. Renaming keeps the handle and the history; the old name keeps resolving."
                        disabled={saving}
                      />
                      {outcome ? (
                        <p
                          className={outcome.tone === 'ok' ? 'ppx-settings__saved' : 'ppx__error'}
                          role={outcome.tone === 'ok' ? 'status' : 'alert'}
                          data-testid="ppx-settings-outcome"
                        >
                          {outcome.text}
                        </p>
                      ) : null}
                      <div className="ppx__actions">
                        <Button
                          type="submit"
                          disabled={saving || !isDirty(form, original)}
                          data-testid="ppx-settings-save"
                        >
                          {saving ? 'Saving…' : 'Save changes'}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          disabled={saving || !isDirty(form, original)}
                          onClick={() => {
                            setForm(original);
                            setSent(false);
                            setNameTaken(null);
                            setOutcome(null);
                          }}
                        >
                          Discard
                        </Button>
                      </div>
                    </form>
                  ) : (
                    <>
                      <p className="ppx__meta" data-testid="ppx-settings-read-only">
                        You can see these settings; changing them needs the pacts edit permission.
                      </p>
                      <PacticipantValues form={original} projectName={projectName} />
                    </>
                  )}
                </section>

                <PacticipantOwnerPanel pacticipantId={pacticipant.id} />

                {canDelete ? (
                  <section
                    className="ppx__panel ppx-settings__danger"
                    aria-labelledby="ppx-danger-title"
                    data-testid="ppx-danger-zone"
                  >
                    <div className="ppx__panel-head">
                      <h2 id="ppx-danger-title" className="ppx__title">
                        Danger zone
                      </h2>
                    </div>
                    <div className="ppx-settings__danger-row">
                      <div>
                        <p className="ppx__statement ppx-settings__strong">
                          Delete this pacticipant
                        </p>
                        <p className="ppx__meta">
                          Removes its versions, pacts and their results. It can be restored until it
                          is purged.
                        </p>
                      </div>
                      <Button
                        variant="danger-soft"
                        onClick={() => setDeleting(true)}
                        data-testid="ppx-delete-open"
                      >
                        <Trash2 aria-hidden />
                        Delete {name}…
                      </Button>
                    </div>
                  </section>
                ) : null}
              </div>

              <aside className="ppx-settings__aside" aria-label="About this pacticipant">
                <section className="ppx__panel">
                  <dl className="ppx-settings__kv" data-testid="ppx-settings-facts">
                    <dt>Handle</dt>
                    <dd className="ppx__mono">{pacticipant.slug}</dd>
                    <dt>Registered</dt>
                    <dd>{formatWhen(pacticipant.created_at)}</dd>
                    <dt>Previous names</dt>
                    <dd>{pacticipant.aliases?.length ? pacticipant.aliases.join(', ') : 'None'}</dd>
                  </dl>
                </section>
                {action ? (
                  <CommandBlock
                    surfaces={pactCommandSurfaces(action)}
                    unsupported={unsupportedLines(action)}
                    footnote="Replace {tenant} with your workspace’s handle in the REST path."
                    data-testid="ppx-settings-command"
                  />
                ) : null}
              </aside>
            </div>
          )}
        </div>
      </PageBody>
      {pacticipant && canDelete ? (
        <DeletePacticipantDialog
          pacticipant={pacticipant}
          open={deleting}
          initialStage={initialDeleteStage}
          onClose={(deleted) => {
            setDeleting(false);
            // Closed on "deleted": the page is gone, so go to the list. Cancelled or restored: stay.
            if (deleted) router.push(PACTICIPANTS_ROUTE);
          }}
          onLeave={() => router.push(PACTICIPANTS_ROUTE)}
        />
      ) : null}
    </Page>
  );
}
