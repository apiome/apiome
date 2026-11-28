'use client';

/**
 * **Environments** — `/ade/dashboard/pacts/environments` (PFX-5.7, #6951).
 *
 * What is running where, what is released to users, and what can move next. Built to
 * `docs/mockups/contracts/environments.html`:
 *
 * * PFX-8.12 (#7309) made it writable: the header's **Record a deployment** (primary), **New
 *   environment** and **Record a release**, and each environment's menu (**Edit environment**,
 *   **Record a deployment here**, **Delete environment**). A role without `pacts:create` sees none
 *   of the header actions; the menu shows only what the role may do.
 * * PFX-8.13 (#7310) replaces the grid with the what-is-where **Board** (services × environments,
 *   a verdict dot per running version, and whether the next version can go — see
 *   {@link EnvironmentBoard}) and adds a **History** view ({@link EnvironmentTimeline}). The column
 *   menu gains **Record an undeployment** and a release on the board **End support** (`pacts:edit`).
 *
 * One facts strip sits over the views (DESIGN.md §5.4); after a write the page reads the board
 * again and says what happened in one status line. A workspace with no environment says so, offers
 * **New environment**, and shows the CLI commands that create one and record a deployment.
 */

import * as React from 'react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { CircleMinus, Ellipsis, History, LayoutGrid, Pencil, Plus, RefreshCw, Rocket, Tag, Trash2 } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import PageHeader from '@/app/components/shell/PageHeader';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import {
  CREATE_ENVIRONMENT_SNIPPET,
  type EnvironmentFacts,
  type NamedPacticipant,
  type Topology,
  type TopologyEnvironment,
} from '@lib/pact-environments';
import {
  DELETE_ENVIRONMENT_PERMISSION,
  EDIT_ENVIRONMENT_PERMISSION,
  RECORD_PERMISSION,
  environmentFormFrom,
  newRecordForm,
  type BrokerEnvironment,
  type EnvironmentForm,
  type RecordForm,
} from '@lib/pact-environment-writes';
import { END_PERMISSION } from '@lib/pact-environment-endings';
import { boardFacts, deployedIn, type Board, type BoardRelease, type EventsPage } from '@lib/pact-environment-board';
import { useMyPermissions } from '@/app/components/ade/access/useMyPermissions';
import { CliSnippet } from '../pactPacticipants/PacticipantPanels';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { fetchBoard, fetchBrokerEnvironments, fetchTopology } from './environmentsApi';
import { EnvironmentBoard, type BoardActions } from './EnvironmentBoard';
import { EnvironmentTimeline } from './EnvironmentTimeline';
import { EnvironmentDialog } from './EnvironmentDialog';
import { DeleteEnvironmentDialog } from './DeleteEnvironmentDialog';
import { RecordDeploymentDialog } from './RecordDeploymentDialog';
import { RecordReleaseDialog } from './RecordReleaseDialog';
import { UndeploymentDialog } from './UndeploymentDialog';
import { EndSupportDialog } from './EndSupportDialog';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The class of a menu item (shared with the other Contracts menus). */
const MENU_ITEM_CLASS = 'tnt-menu__item';

/** The page's reads: the board, and the topology the record dialogs use. */
interface Loaded {
  board: Board | null;
  topology: Topology | null;
  error: string | null;
}

/** Which view is shown. */
export type EnvironmentsView = 'board' | 'history';

/** Which dialog is open. */
type Open =
  | { kind: 'none' }
  | { kind: 'new' }
  | { kind: 'edit'; environment: BrokerEnvironment; form: EnvironmentForm }
  | { kind: 'delete'; environment: TopologyEnvironment }
  | { kind: 'deploy'; environment?: string; form?: RecordForm }
  | { kind: 'release' }
  | { kind: 'undeploy'; environment: EnvironmentFacts }
  | { kind: 'end'; pacticipant: NamedPacticipant; release: BoardRelease };

/** What the status line says after a write. */
type Notice = { tone: 'ok' | 'danger'; text: string } | null;

/** Props for {@link EnvironmentsClient} — starting values for fixture renders only. */
export interface EnvironmentsClientProps {
  initialBoard?: Board;
  initialTopology?: Topology;
  initialView?: EnvironmentsView;
  initialEvents?: EventsPage;
}

/**
 * The Environments page.
 *
 * @param props - See {@link EnvironmentsClientProps}.
 * @returns The page.
 */
export default function EnvironmentsClient({ initialBoard, initialTopology, initialView = 'board', initialEvents }: EnvironmentsClientProps = {}) {
  const [loaded, setLoaded] = React.useState<Loaded>({
    board: initialBoard ?? null,
    topology: initialTopology ?? null,
    error: null,
  });
  const [view, setView] = React.useState<EnvironmentsView>(initialView);
  const [open, setOpen] = React.useState<Open>({ kind: 'none' });
  const [notice, setNotice] = React.useState<Notice>(null);
  const permissions = useMyPermissions();
  const can = (permission: string) => permissions.status === 'ready' && permissions.can(permission);
  const canRecord = can(RECORD_PERMISSION);
  const canEdit = can(EDIT_ENVIRONMENT_PERMISSION);
  const canDelete = can(DELETE_ENVIRONMENT_PERMISSION);
  const canEnd = can(END_PERMISSION);

  const load = React.useCallback(async () => {
    setLoaded({ board: null, topology: null, error: null });
    try {
      const [board, topology] = await Promise.all([fetchBoard(), fetchTopology()]);
      setLoaded({ board, topology, error: null });
    } catch (caught) {
      setLoaded({ board: null, topology: null, error: describeFailure(caught, 'Could not load the environments') });
    }
  }, []);

  React.useEffect(() => {
    if (!initialBoard) void load();
  }, [initialBoard, load]);

  const close = () => setOpen({ kind: 'none' });
  const done = (text: string) => {
    close();
    setNotice({ tone: 'ok', text });
    void load();
  };

  const startEdit = async (environment: EnvironmentFacts) => {
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

  const { board, topology, error } = loaded;
  const names = topology?.environments.map((environment) => environment.name) ?? [];
  const anyMenu = canRecord || canEdit || canDelete || canEnd;

  const menu = (environment: EnvironmentFacts) => {
    const running = board ? deployedIn(board, environment.uuid).length > 0 : false;
    const full = topology?.environments.find((entry) => entry.uuid === environment.uuid);
    return (
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
            {canEnd && running ? (
              <DropdownMenu.Item
                className={MENU_ITEM_CLASS}
                onSelect={() => setOpen({ kind: 'undeploy', environment })}
                data-testid={`penv-undeploy-${environment.name}`}
              >
                <CircleMinus aria-hidden />
                Record an undeployment
              </DropdownMenu.Item>
            ) : null}
            {canDelete && full ? (
              <>
                <DropdownMenu.Separator className="ppx-versions__menu-sep" />
                <DropdownMenu.Item
                  className={`${MENU_ITEM_CLASS} ppx-versions__menu-danger`}
                  onSelect={() => setOpen({ kind: 'delete', environment: full })}
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
  };

  const actions: BoardActions = {
    ...(anyMenu ? { menu } : {}),
    ...(canRecord
      ? {
          deploy: (environment: string, pacticipant: NamedPacticipant, version?: string) =>
            setOpen({
              kind: 'deploy',
              environment,
              form: { ...newRecordForm(environment), pacticipant: pacticipant.slug, version: version ?? '' },
            }),
        }
      : {}),
    ...(canEnd ? { endSupport: (pacticipant: NamedPacticipant, release: BoardRelease) => setOpen({ kind: 'end', pacticipant, release }) } : {}),
  };

  const hasEnvironments = Boolean(board && board.environments.length);
  const facts = board ? boardFacts(board) : null;
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
        description="What is running where, what is released to users, and what can move next."
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
          ) : board === null ? (
            <LoadingState message="Reading the environments…" minHeightClassName="min-h-[6rem]" />
          ) : board.environments.length === 0 ? (
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
              <div className="penv-facts" data-testid="penv-facts">
                <ul className="facts penv-facts__list" aria-label="Summary">
                  <li className="facts__item" data-testid="penv-count">
                    <b>{facts?.environments}</b> {facts?.environments === 1 ? 'environment' : 'environments'}
                  </li>
                  <li className="facts__item">
                    <b>{facts?.services}</b> {facts?.services === 1 ? 'service' : 'services'}
                  </li>
                  <li className="facts__item">
                    <b>{facts?.running}</b> {facts?.running === 1 ? 'version running' : 'versions running'}
                  </li>
                  <li className="facts__item" data-testid="penv-blocked">
                    <b>{facts?.blocked}</b> {facts?.blocked === 1 ? 'blocked promotion' : 'blocked promotions'}
                  </li>
                </ul>
                <Segmented
                  size="sm"
                  value={view}
                  onValueChange={(value) => setView(value as EnvironmentsView)}
                  aria-label="View"
                  className="penv-facts__views"
                >
                  <SegmentedItem value="board" data-testid="penv-view-board">
                    <LayoutGrid aria-hidden />
                    Board
                  </SegmentedItem>
                  <SegmentedItem value="history" data-testid="penv-view-history">
                    <History aria-hidden />
                    History
                  </SegmentedItem>
                </Segmented>
                <Button variant="ghost" size="sm" onClick={() => void load()} data-testid="penv-refresh">
                  <RefreshCw aria-hidden />
                  Refresh
                </Button>
              </div>
              {board.truncated || board.notChecked ? (
                <p className="ppx__muted" role="status" data-testid="penv-truncated">
                  {board.truncated
                    ? 'This workspace has more than 2000 current deployments or releases, or more than 50 services with nothing recorded; only the first are shown. '
                    : ''}
                  {board.notChecked
                    ? `${board.notChecked} ${board.notChecked === 1 ? 'version was' : 'versions were'} not checked on this board; hover a grey dot for why, or open the deploy simulator.`
                    : ''}
                </p>
              ) : null}
              {view === 'board' ? <EnvironmentBoard board={board} actions={actions} /> : <EnvironmentTimeline initial={initialEvents} />}
            </>
          )}
        </div>
      </PageBody>
      {topology ? (
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
            topology={topology}
            environment={open.kind === 'deploy' ? open.environment : undefined}
            initialForm={open.kind === 'deploy' ? open.form : undefined}
          />
          <RecordReleaseDialog open={open.kind === 'release'} onClose={close} onRecorded={done} topology={topology} canEndSupport={canEnd} />
          {open.kind === 'delete' ? (
            <DeleteEnvironmentDialog open onClose={close} onDeleted={done} environment={open.environment} />
          ) : null}
        </>
      ) : null}
      {board && open.kind === 'undeploy' ? (
        <UndeploymentDialog open onClose={close} onRecorded={done} board={board} environment={open.environment} />
      ) : null}
      {open.kind === 'end' ? (
        <EndSupportDialog
          open
          onClose={close}
          onEnded={done}
          pacticipant={open.pacticipant}
          version={open.release.version}
          environment={open.release.environment}
        />
      ) : null}
    </Page>
  );
}
