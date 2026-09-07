'use client';

import * as React from 'react';
import { FileJson, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/app/components/ui/Button';
import {
  DataTableFilterChip,
  DataTableSearch,
  DataTableToolbar,
  DataTableToolbarSpacer,
  type DataTableSortState,
} from '@/app/components/ui/DataTable';
import { EmptyState } from '@/app/components/ui/EmptyState';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';

import {
  CONSUMER_FACETS,
  CONSUMER_FACET_LABELS,
  ConsumerFormDialog,
  ConsumerSurfaceDrawer,
  ConsumersTable,
  PactImportDialog,
  SurfacePickerDialog,
  consumerFacetCounts,
  matchesConsumerFacet,
  searchConsumers,
  selectionFromContract,
  sortConsumers,
  type AvailableSurface,
  type ConsumerDraft,
  type ConsumerFacet,
  type ConsumerSortColumn,
  type ConsumerSummary,
  type PickerSelection,
  type SelectionPayloadOperation,
} from '@/app/components/ade/consumers';

import {
  createConsumer,
  declareContract,
  fetchAvailableSurface,
  fetchConsumers,
  importPact,
  retireConsumer,
  updateConsumer,
} from './api';

/**
 * Consumers — `/ade/dashboard/projects/{projectId}/consumers` (CTG-4.1, #4479).
 *
 * The project's consumer registry: who depends on this API, and what each of them declares it
 * uses. It is the missing half of breaking-change analysis — without it, a diff can only be
 * graded against the whole published surface, which over-warns the provider and tells the
 * consumer nothing.
 *
 * ### What this screen owns
 *
 * The rows, the five writes, which chip is active, and which overlay is open. How a row is
 * *drawn* is `ConsumersTable`; what a row *means* is `consumersModel`; the picker, the Pact
 * import, and the surface drawer are their own components.
 *
 * ### The catalogue is fetched when the picker opens, not on mount
 *
 * Enumerating every operation and field of a stored specification is the most expensive read
 * on this screen, and most visits never open the picker. It loads on first open and is kept
 * for the rest of the visit, so a second consumer costs nothing.
 *
 * ### A viewer without write permission gets a read-only screen, not a broken one
 *
 * Every mutation here is gated on `consumer_contracts:*` and REST enforces it. The controls
 * are absent rather than present-and-refused, which is the pattern the governance screens
 * settled on — offering a button whose write will be refused is worse than not offering it.
 */

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** Which overlay, if any, is open over the page. */
type ConsumerOverlay = 'none' | 'register' | 'edit' | 'declare' | 'import' | 'surface';

/** The caller's effective permissions, as `/api/access/permissions/me` reports them. */
interface MyPermissions {
  is_admin: boolean;
  permissions: string[];
}

/**
 * Turn a caught failure into the sentence to show.
 *
 * @param error Whatever was caught.
 * @param fallback What to say when the failure carried no message.
 * @returns The sentence.
 */
function describeFailure(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** Props for {@link ConsumersClient}. */
export interface ConsumersClientProps {
  /** The project this registry belongs to — a slug or an id, as the route carries it. */
  projectRef: string;
}

/**
 * The consumers screen.
 *
 * @param props See {@link ConsumersClientProps}.
 * @returns The header, the list, and the four overlays.
 */
export default function ConsumersClient({ projectRef }: ConsumersClientProps) {
  const [rows, setRows] = React.useState<ConsumerSummary[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  const [query, setQuery] = React.useState('');
  const [facet, setFacet] = React.useState<ConsumerFacet>('all');
  const [sort, setSort] = React.useState<DataTableSortState | null>(null);

  const [overlay, setOverlay] = React.useState<ConsumerOverlay>('none');

  /**
   * Which row an overlay is about, held as an **id** rather than as the row itself.
   *
   * Every write reloads the list, and a stored summary would then describe the contract as it
   * was *before* the write: reopening the picker after saving would start from the previous
   * revision. Deriving the row from `rows` makes that impossible rather than remembered.
   */
  const [activeId, setActiveId] = React.useState<string | null>(null);

  const [catalogue, setCatalogue] = React.useState<AvailableSurface | null>(null);
  const [catalogueLoading, setCatalogueLoading] = React.useState(false);
  const [catalogueError, setCatalogueError] = React.useState('');

  const [permissions, setPermissions] = React.useState<MyPermissions | null>(null);

  const can = React.useCallback(
    (action: string) =>
      Boolean(
        permissions?.is_admin ||
          permissions?.permissions.includes(`consumer_contracts:${action}`),
      ),
    [permissions],
  );

  const load = React.useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await fetchConsumers(projectRef);
      setRows(data.consumers);
    } catch (error) {
      setLoadError(describeFailure(error, "Couldn't load this project's consumers"));
    } finally {
      setLoading(false);
    }
  }, [projectRef]);

  React.useEffect(() => {
    void load();
  }, [load]);

  React.useEffect(() => {
    fetch('/api/access/permissions/me')
      .then((response) => response.json())
      .then((body) => setPermissions(body?.success ? (body.data as MyPermissions) : null))
      .catch(() => setPermissions(null));
  }, []);

  /** Load the picker's catalogue once per visit, on first need. */
  const ensureCatalogue = React.useCallback(async () => {
    if (catalogue || catalogueLoading) return;
    setCatalogueLoading(true);
    setCatalogueError('');
    try {
      setCatalogue(await fetchAvailableSurface(projectRef));
    } catch (error) {
      setCatalogueError(
        describeFailure(error, "Couldn't read this project's specification"),
      );
    } finally {
      setCatalogueLoading(false);
    }
  }, [catalogue, catalogueLoading, projectRef]);

  const visible = React.useMemo(() => {
    const matched = searchConsumers(rows, query).filter((row) =>
      matchesConsumerFacet(row, facet),
    );
    if (!sort) return matched;
    return sortConsumers(matched, sort.column as ConsumerSortColumn, sort.direction);
  }, [rows, query, facet, sort]);

  const counts = React.useMemo(() => consumerFacetCounts(rows), [rows]);

  const active = React.useMemo(
    () => rows.find((row) => row.consumer.id === activeId) ?? null,
    [rows, activeId],
  );

  const initialSelection: PickerSelection = React.useMemo(
    () => selectionFromContract(active?.contract ?? null),
    [active],
  );

  // ---- writes -------------------------------------------------------------------------

  const saveConsumer = async (draft: ConsumerDraft): Promise<string | null> => {
    const payload = {
      name: draft.name.trim(),
      description: draft.description.trim() || null,
      owner: draft.owner.trim() || null,
      contact: draft.contact.trim() || null,
    };
    try {
      if (overlay === 'edit' && active) {
        await updateConsumer(projectRef, active.consumer.slug, payload);
        toast.success(`${payload.name} updated`);
      } else {
        const slug = draft.slug.trim();
        await createConsumer(projectRef, { ...payload, ...(slug ? { slug } : {}) });
        toast.success(`${payload.name} registered`);
      }
      await load();
      return null;
    } catch (error) {
      return describeFailure(error, 'The consumer could not be saved');
    }
  };

  const saveContract = async (
    operations: SelectionPayloadOperation[],
  ): Promise<string | null> => {
    if (!active) return 'No consumer is selected';
    try {
      const result = await declareContract(projectRef, active.consumer.slug, operations);
      // `unresolved` is always present on the wire; reading it defensively keeps a malformed
      // answer from surfacing as a TypeError banner over a write that actually succeeded.
      const unresolved = result.unresolved?.length ?? 0;
      toast.success(
        unresolved > 0
          ? `Revision ${result.contract.revision} stored — ${unresolved} could not be resolved`
          : `Revision ${result.contract.revision} stored`,
      );
      await load();
      return null;
    } catch (error) {
      return describeFailure(error, 'The contract could not be stored');
    }
  };

  const runImport = async (pact: string, consumerSlug: string) => {
    try {
      const result = await importPact(projectRef, pact, consumerSlug);
      await load();
      return {
        outcome: {
          operationCount: result.contract.operation_count,
          fieldCount: result.contract.field_count,
          revision: result.contract.revision,
          unresolved: result.unresolved ?? [],
        },
      };
    } catch (error) {
      return { error: describeFailure(error, 'The Pact document could not be imported') };
    }
  };

  const retire = async (row: ConsumerSummary) => {
    try {
      await retireConsumer(projectRef, row.consumer.slug);
      toast.success(`${row.consumer.name} retired`);
      await load();
    } catch (error) {
      toast.error(describeFailure(error, 'The consumer could not be retired'));
    }
  };

  // ---- render -------------------------------------------------------------------------

  const openOverlay = (next: ConsumerOverlay, row: ConsumerSummary | null) => {
    setActiveId(row?.consumer.id ?? null);
    setOverlay(next);
    if (next === 'declare') void ensureCatalogue();
  };

  const toolbar = (
    <DataTableToolbar>
      <DataTableSearch
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search consumers and declared paths…"
        aria-label="Search consumers"
      />
      {CONSUMER_FACETS.map((entry) => (
        <DataTableFilterChip
          key={entry}
          active={facet === entry}
          count={counts[entry]}
          onClick={() => setFacet(entry)}
        >
          {CONSUMER_FACET_LABELS[entry]}
        </DataTableFilterChip>
      ))}
      <DataTableToolbarSpacer />
    </DataTableToolbar>
  );

  const empty = (
    <EmptyState
      title={query || facet !== 'all' ? 'No consumer matches' : 'No consumers registered yet'}
      description={
        query || facet !== 'all'
          ? 'Clear the search or pick another view.'
          : 'Register the services that call this API, then declare what each of them uses — by importing its Pact file or by picking operations. Until one exists, a change here can only be graded against the whole specification.'
      }
    />
  );

  return (
    <Page>
      <PageHeader
        title="Consumers"
        breadcrumb={[
          { label: 'Dashboard', href: HOME_ROUTE },
          { label: 'Projects', href: '/ade/dashboard/projects' },
          { label: 'Consumers' },
        ]}
        description="Who depends on this API, and which operations and fields each of them uses."
        actions={
          can('create') ? (
            <>
              <Button variant="secondary" onClick={() => openOverlay('import', null)}>
                <FileJson aria-hidden="true" />
                Import Pact file
              </Button>
              <Button onClick={() => openOverlay('register', null)}>
                <Plus aria-hidden="true" />
                Register consumer
              </Button>
            </>
          ) : null
        }
      />

      <PageBody>
        <ConsumersTable
          rows={visible}
          loading={loading}
          error={loadError}
          onRetry={load}
          empty={empty}
          toolbar={toolbar}
          sort={sort}
          onSortChange={setSort}
          onOpen={(row) => openOverlay('surface', row)}
          onEdit={(row) => openOverlay('edit', row)}
          onDeclare={(row) => openOverlay('declare', row)}
          onImport={(row) => openOverlay('import', row)}
          onRetire={retire}
          canEdit={can('edit')}
          canDelete={can('delete')}
        />
      </PageBody>

      <ConsumerFormDialog
        open={overlay === 'register' || overlay === 'edit'}
        onOpenChange={(next) => !next && setOverlay('none')}
        mode={overlay === 'edit' ? 'edit' : 'create'}
        consumer={overlay === 'edit' ? (active?.consumer ?? null) : null}
        onSubmit={saveConsumer}
      />

      <SurfacePickerDialog
        open={overlay === 'declare'}
        onOpenChange={(next) => !next && setOverlay('none')}
        consumerName={active?.consumer.name ?? 'this consumer'}
        catalogue={catalogue}
        loading={catalogueLoading}
        loadError={catalogueError}
        initialSelection={initialSelection}
        onSubmit={saveContract}
      />

      <PactImportDialog
        open={overlay === 'import'}
        onOpenChange={(next) => !next && setOverlay('none')}
        consumerName={active?.consumer.name ?? null}
        consumerSlug={active?.consumer.slug ?? null}
        onImport={runImport}
      />

      <ConsumerSurfaceDrawer
        open={overlay === 'surface'}
        onOpenChange={(next) => !next && setOverlay('none')}
        summary={active}
      />
    </Page>
  );
}
