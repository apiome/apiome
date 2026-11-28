'use client';

/**
 * **Environments** — `/ade/dashboard/pacts/environments` (PFX-5.7, #6951).
 *
 * Which version of each pacticipant runs where: a grid of pacticipants × environments with the
 * versions deployed to each now (and the application instance) and the releases it supports, then
 * the environments themselves. Each environment opens its own page (what runs there, its
 * deployment history, the deploy simulator); each pacticipant its page.
 *
 * PFX-8.12 (#7309) makes it writable, built to `docs/mockups/contracts/environments.html`: the
 * header's **Record a deployment** (primary), **New environment** and **Record a release**, and
 * each environment's menu (**Edit environment**, **Record a deployment here**, **Delete
 * environment**). A role without `pacts:create` sees none of the header actions; the menu shows
 * only what the role may do (`pacts:edit`, `pacts:create`, `pacts:delete`). After a write the page
 * reads the topology again and says what happened in one status line.
 *
 * A workspace with no environment says so, offers **New environment**, and shows the CLI commands
 * that create one and record a deployment.
 */

import * as React from 'react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Ellipsis, Pencil, Plus, RefreshCw, Rocket, Tag, Trash2 } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { CREATE_ENVIRONMENT_SNIPPET, type Topology, type TopologyEnvironment } from '@lib/pact-environments';
import {
  DELETE_ENVIRONMENT_PERMISSION,
  EDIT_ENVIRONMENT_PERMISSION,
  RECORD_PERMISSION,
  environmentFormFrom,
  type BrokerEnvironment,
  type EnvironmentForm,
} from '@lib/pact-environment-writes';
import { useMyPermissions } from '@/app/components/ade/access/useMyPermissions';
import { CliSnippet } from '../pactPacticipants/PacticipantPanels';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { DeployedVersionsGrid, EnvironmentList } from './EnvironmentPanels';
import { fetchBrokerEnvironments, fetchTopology } from './environmentsApi';
import { EnvironmentDialog } from './EnvironmentDialog';
import { DeleteEnvironmentDialog } from './DeleteEnvironmentDialog';
import { RecordDeploymentDialog } from './RecordDeploymentDialog';
import { RecordReleaseDialog } from './RecordReleaseDialog';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The class of a menu item (shared with the other Contracts menus). */
const MENU_ITEM_CLASS = 'tnt-menu__item';

/** The page's read. */
interface Loaded {
  data: Topology | null;
  error: string | null;
}

/** Which dialog is open. */
type Open =
  | { kind: 'none' }
  | { kind: 'new' }
  | { kind: 'edit'; environment: BrokerEnvironment; form: EnvironmentForm }
  | { kind: 'delete'; environment: TopologyEnvironment }
  | { kind: 'deploy'; environment?: string }
  | { kind: 'release' };

/** What the status line says after a write. */
type Notice = { tone: 'ok' | 'danger'; text: string } | null;

/**
 * The Environments dashboard.
 *
 * @returns The page.
 */
export default function EnvironmentsClient() {
  const [loaded, setLoaded] = React.useState<Loaded>({ data: null, error: null });
  const [open, setOpen] = React.useState<Open>({ kind: 'none' });
  const [notice, setNotice] = React.useState<Notice>(null);
  const permissions = useMyPermissions();
  const can = (permission: string) => permissions.status === 'ready' && permissions.can(permission);
  const canRecord = can(RECORD_PERMISSION);
  const canEdit = can(EDIT_ENVIRONMENT_PERMISSION);
  const canDelete = can(DELETE_ENVIRONMENT_PERMISSION);

  const load = React.useCallback(async () => {
    setLoaded({ data: null, error: null });
    try {
      setLoaded({ data: await fetchTopology(), error: null });
    } catch (caught) {
      setLoaded({ data: null, error: describeFailure(caught, 'Could not load the environments') });
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const close = () => setOpen({ kind: 'none' });
  const done = (text: string) => {
    close();
    setNotice({ tone: 'ok', text });
    void load();
  };

  const startEdit = async (environment: TopologyEnvironment) => {
    setNotice(null);
    try {
      const found = (await fetchBrokerEnvironments()).find((entry) => entry.uuid === environment.uuid);
      if (!found) {
        setNotice({ tone: 'danger', text: `${environment.displayName} is no longer in this workspace.` });
        void load();
        return;
      }
      setOpen({ kind: 'edit', environment: found, form: environmentFormFrom(found) });
    } catch (caught) {
      setNotice({ tone: 'danger', text: describeFailure(caught, 'Could not read the environment') });
    }
  };

  const { data, error } = loaded;
  const names = data?.environments.map((environment) => environment.name) ?? [];
  const anyMenu = canRecord || canEdit || canDelete;

  const menu = (environment: TopologyEnvironment) => (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <Button variant="ghost" size="sm" aria-label={`${environment.displayName} actions`} data-testid={`penv-menu-${environment.name}`}>
          <Ellipsis aria-hidden />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="tnt-menu" sideOffset={4} align="end">
          {canEdit ? (
            <DropdownMenu.Item className={MENU_ITEM_CLASS} onSelect={() => void startEdit(environment)} data-testid={`penv-edit-${environment.name}`}>
              <Pencil aria-hidden />
              Edit environment
            </DropdownMenu.Item>
          ) : null}
          {canRecord ? (
            <DropdownMenu.Item
              className={MENU_ITEM_CLASS}
              onSelect={() => setOpen({ kind: 'deploy', environment: environment.name })}
              data-testid={`penv-deploy-here-${environment.name}`}
            >
              <Rocket aria-hidden />
              Record a deployment here
            </DropdownMenu.Item>
          ) : null}
          {canDelete ? (
            <>
              <DropdownMenu.Separator className="ppx-versions__menu-sep" />
              <DropdownMenu.Item
                className={`${MENU_ITEM_CLASS} ppx-versions__menu-danger`}
                onSelect={() => setOpen({ kind: 'delete', environment })}
                data-testid={`penv-delete-${environment.name}`}
              >
                <Trash2 aria-hidden />
                Delete environment
              </DropdownMenu.Item>
            </>
          ) : null}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );

  const hasEnvironments = Boolean(data && data.environments.length);
  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="environments" />}
        title="Environments"
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Contracts', href: CONTRACTS_ROUTE },
          { label: 'Environments' },
        ]}
        description="Which version of each pacticipant runs where — and what a deployment would change."
        actions={
          canRecord ? (
            <>
              {hasEnvironments ? (
                <Button variant="outline" onClick={() => setOpen({ kind: 'release' })} data-testid="penv-action-release">
                  <Tag aria-hidden />
                  Record a release
                </Button>
              ) : null}
              <Button
                variant={hasEnvironments ? 'outline' : 'primary'}
                onClick={() => setOpen({ kind: 'new' })}
                data-testid="penv-action-new"
              >
                <Plus aria-hidden />
                New environment
              </Button>
              {hasEnvironments ? (
                <Button onClick={() => setOpen({ kind: 'deploy' })} data-testid="penv-action-deploy">
                  <Rocket aria-hidden />
                  Record a deployment
                </Button>
              ) : null}
            </>
          ) : null
        }
      />
      <PageBody>
        <div className="ppx" data-testid="pact-environments">
          {notice ? (
            <p
              className={notice.tone === 'ok' ? 'penv-notice' : 'ppx__error'}
              role={notice.tone === 'ok' ? 'status' : 'alert'}
              data-testid="penv-notice"
            >
              {notice.text}
            </p>
          ) : null}
          {error ? (
            <EmptyState
              variant="compact"
              tone="danger"
              titleAs="h2"
              title="The environments could not be read"
              description={error}
              action={
                <Button variant="soft" onClick={() => void load()}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              }
            />
          ) : data === null ? (
            <LoadingState message="Reading the environments…" minHeightClassName="min-h-[6rem]" />
          ) : data.environments.length === 0 ? (
            <div className="ppx__empty-note" data-testid="penv-empty">
              <EmptyState
                variant="compact"
                titleAs="h2"
                title="No environments yet"
                description="Add production and staging so can-i-deploy has somewhere to look. Then record each deployment to them — here, or from your pipeline:"
              />
              <CliSnippet label="Create an environment and record a deployment" command={CREATE_ENVIRONMENT_SNIPPET} />
            </div>
          ) : (
            <>
              {data.truncated ? (
                <p className="ppx__error" role="status" data-testid="penv-truncated">
                  This workspace has more than 2000 current deployments or releases; only the first 2000 are shown.
                  Each environment&apos;s deployment history lists every deployment.
                </p>
              ) : null}
              <section className="ppx__panel" aria-labelledby="penv-grid-title">
                <div className="ppx__panel-head">
                  <h2 id="penv-grid-title" className="ppx__title">
                    Deployed versions
                  </h2>
                  <span className="ppx__meta" data-testid="penv-count">
                    {data.environments.length} {data.environments.length === 1 ? 'environment' : 'environments'}
                  </span>
                  <Button variant="ghost" size="sm" className="penv-refresh" onClick={() => void load()} data-testid="penv-refresh">
                    <RefreshCw aria-hidden />
                    Refresh
                  </Button>
                </div>
                <DeployedVersionsGrid topology={data} />
              </section>
              <section className="ppx__panel" aria-labelledby="penv-list-title">
                <div className="ppx__panel-head">
                  <h2 id="penv-list-title" className="ppx__title">
                    Environments
                  </h2>
                </div>
                <EnvironmentList environments={data.environments} actions={anyMenu ? menu : undefined} />
              </section>
            </>
          )}
        </div>
      </PageBody>
      {data ? (
        <>
          <EnvironmentDialog
            open={open.kind === 'new' || open.kind === 'edit'}
            onClose={close}
            onSaved={done}
            editing={open.kind === 'edit' ? { environment: open.environment, form: open.form } : null}
            takenNames={names}
          />
          <RecordDeploymentDialog
            open={open.kind === 'deploy'}
            onClose={close}
            onRecorded={done}
            topology={data}
            environment={open.kind === 'deploy' ? open.environment : undefined}
          />
          <RecordReleaseDialog open={open.kind === 'release'} onClose={close} onRecorded={done} topology={data} />
          {open.kind === 'delete' ? (
            <DeleteEnvironmentDialog open onClose={close} onDeleted={done} environment={open.environment} />
          ) : null}
        </>
      ) : null}
    </Page>
  );
}
