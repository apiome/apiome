'use client';

/**
 * Catalog dashboard screen (MFI-23.3, #4012).
 *
 * Cloned from `src/app/ade/dashboard/projects/page.tsx`, restricted to the Catalog — the
 * non-publishable (`publishable = false`) slice of projects: the OpenAPI-worthy *non*-OpenAPI
 * imports (MFI-23.1). It reaches the read-only `/api/catalog` proxy (MFI-23.2) for the list and
 * reuses the project soft-delete/undelete server actions (a catalog item's id *is* a project id,
 * since the Catalog is a projection over the same `projects` table). Reaches feature parity with the
 * Projects list — card/table views, filter (all/active/attention/deleted), sort
 * (name/created/updated/quality/grade/format), search, soft-delete/undelete — **minus publish** and
 * minus create/edit, because catalog items are minted by the import routing (MFI-23.7), not here.
 *
 * The dedicated CatalogItemCard (MFI-23.4), format/protocol pills (MFI-23.5) and the side-nav entry
 * (MFI-23.6) are separate tickets; this screen ships a self-contained inline card so both views work.
 */

import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import {
  useEffect,
  useState,
  useMemo,
  useCallback,
  useRef,
  type Dispatch,
  type SetStateAction,
} from 'react';
import {
  Trash2,
  Library,
  BookOpen,
  Lock,
  AlertTriangle,
  MoreVertical,
  Undo2,
  ArrowUp,
  ArrowDown,
  ArrowUpDown,
  Search,
  LayoutGrid,
  List,
  Eye,
  ScanLine,
  ArrowLeftRight,
  PanelsTopLeft,
} from 'lucide-react';
import { Button } from '../../../components/ui/Button';
import { Label } from '../../../components/ui/Label';
import { Switch } from '../../../components/ui/Switch';
import { LoadingState } from '../../../components/ui/LoadingState';
import { EmptyState } from '../../../components/ui/EmptyState';
import { toast } from 'sonner';
import { deleteProject, permanentDeleteProject, restoreProject } from '../../../../../lib/db/helper';
import { useDialog } from '../../../components/providers/DialogProvider';
import { getNumericScoreTier } from '../../../utils/numeric-score-tier';
import {
  getProjectQualityHistory,
  type ProjectQualitySnapshot,
} from '../../../utils/project-quality-score-history';
import { ProjectQualityHistoryDialog } from '../../../components/ade/dashboard/ProjectQualityHistoryDialog';
import { CatalogItemCard } from '../../../components/ade/dashboard/catalog/CatalogItemCard';
import { CatalogLintReportDialog } from '../../../components/ade/dashboard/catalog/CatalogLintReportDialog';
import { FormatPill } from '../../../components/ui/catalog/FormatPill';
import { ProtocolPill } from '../../../components/ui/catalog/ProtocolPill';
import { SourceBadge } from '../../../components/ui/catalog/SourceBadge';
import { resolveCatalogSource } from '../../../utils/catalog-format-registry';
import {
  catalogCardInitials,
  catalogCardGradientClass,
  formatShortCatalogId,
} from '../../../utils/catalog-card-presentation';
import {
  dashboardContentStackClass,
  dashboardMainClass,
  dashboardPanelClass,
  dashboardTableWrapClass,
  dashboardTableTheadClass,
  dashboardThClass,
  dashboardThRightClass,
  dashboardTbodyClass,
  dashboardTrHoverClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';
import {
  sortCatalogDashboardRows,
  type CatalogDashboardSortColumn,
  type CatalogDashboardSortDirection,
} from '@/app/utils/catalog-dashboard-sort';
import { cn } from '../../../../../lib/utils';

/**
 * A catalog item — the camelCase shape returned by `/api/catalog` (REST `CatalogItemSchema`,
 * MFI-23.2). Mirrors the Projects envelope plus the imported format/protocol provenance.
 */
interface CatalogItem {
  id: string;
  tenant_id: string;
  creator_id?: string | null;
  name: string;
  slug?: string | null;
  description?: string | null;
  enabled: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  creator_name?: string | null;
  creator_email?: string | null;
  metadata?: { summary?: string } & Record<string, unknown> | null;
  qualityScore?: number | null;
  qualityGrade?: string | null;
  /** Always false for a catalog item (the non-publishable invariant, MFI-23.1). */
  publishable?: boolean;
  /** Imported source format + paradigm/protocol off the latest revision (MFI-7.1/7.2). */
  sourceFormat?: string | null;
  protocol?: string | null;
  /** Format-specific metadata off the latest revision; carries source-material provenance (MFI-7.x). */
  formatMetadata?: Record<string, unknown> | null;
}

/** The six sort options the Catalog screen exposes (MFI-23.3). */
const CATALOG_SORT_OPTIONS: ReadonlyArray<{ column: CatalogDashboardSortColumn; label: string }> = [
  { column: 'name', label: 'Name' },
  { column: 'created', label: 'Created' },
  { column: 'updated', label: 'Updated' },
  { column: 'quality', label: 'Quality' },
  { column: 'grade', label: 'Grade' },
  { column: 'format', label: 'Format' },
];

/**
 * Per-row actions menu for a catalog item: View / Lint / Convert to OpenAPI, then
 * soft-delete / undelete / permanent delete.
 *
 * There is intentionally **no Publish** — catalog items are the non-publishable slice of projects
 * (MFI-23.1) — and no "Edit": items are read-only here (minted by the import routing, MFI-23.7).
 * The delete/restore handlers operate on the item's id, which is a project id, so they reuse the
 * project server actions.
 */
function CatalogItemActions({
  item,
  isDeleted,
  openDropdown,
  setOpenDropdown,
  dropdownPosition,
  setDropdownPosition,
  onOpenDetail,
  onView,
  onLint,
  onConvert,
  onDelete,
  onRestore,
  onPermanentDelete,
}: {
  item: CatalogItem;
  isDeleted: boolean;
  openDropdown: string | null;
  setOpenDropdown: Dispatch<SetStateAction<string | null>>;
  dropdownPosition: { top: number; right: number } | null;
  setDropdownPosition: Dispatch<SetStateAction<{ top: number; right: number } | null>>;
  onOpenDetail: (item: CatalogItem) => void;
  onView: (item: CatalogItem) => void;
  onLint: (item: CatalogItem) => void;
  onConvert: (item: CatalogItem) => void | Promise<void>;
  onDelete: (id: string) => void | Promise<void>;
  onRestore: (item: CatalogItem) => void | Promise<void>;
  onPermanentDelete: (item: CatalogItem) => void | Promise<void>;
}) {
  return (
    <div className="relative inline-flex items-center justify-end gap-0.5">
      {isDeleted ? (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            void onRestore(item);
          }}
          className="rounded-lg p-2 text-emerald-600 transition-colors hover:bg-emerald-50 dark:text-emerald-400 dark:hover:bg-emerald-950/40"
          title="Undelete catalog item"
          aria-label={`Undelete catalog item ${item.name}`}
        >
          <Undo2 className="h-4 w-4" />
        </button>
      ) : null}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
          setDropdownPosition({
            top: rect.bottom + 4,
            right: window.innerWidth - rect.right,
          });
          setOpenDropdown(openDropdown === item.id ? null : item.id);
        }}
        className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 dark:hover:text-white"
        title="Actions"
        aria-label={`Actions for catalog item ${item.name}`}
      >
        <MoreVertical className="h-4 w-4" />
      </button>

      {openDropdown === item.id && dropdownPosition ? (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={(e) => {
              e.stopPropagation();
              setOpenDropdown(null);
            }}
          />
          <div
            className="fixed z-20 w-56 min-w-0 overflow-x-hidden rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-900"
            style={{
              top: `${dropdownPosition.top}px`,
              right: `${dropdownPosition.right}px`,
            }}
          >
            <div className="py-1">
              {!item.deleted_at ? (
                <>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenDropdown(null);
                      onOpenDetail(item);
                    }}
                    className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-white"
                  >
                    <PanelsTopLeft className="h-4 w-4 text-indigo-500" />
                    Details
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenDropdown(null);
                      onView(item);
                    }}
                    className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-white"
                  >
                    <Eye className="h-4 w-4 text-indigo-500" />
                    View
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenDropdown(null);
                      onLint(item);
                    }}
                    className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-white"
                  >
                    <ScanLine className="h-4 w-4 text-indigo-500" />
                    Lint
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenDropdown(null);
                      void onConvert(item);
                    }}
                    className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-white"
                  >
                    <ArrowLeftRight className="h-4 w-4 text-indigo-500" />
                    Convert to OpenAPI
                  </button>
                  <div className="my-1 border-t border-gray-200 dark:border-gray-700" />
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenDropdown(null);
                      void onDelete(item.id);
                    }}
                    className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-white"
                  >
                    <Trash2 className="h-4 w-4 text-red-500" />
                    Delete item
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpenDropdown(null);
                    void onRestore(item);
                  }}
                  className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-white"
                >
                  <Undo2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                  Undelete item
                </button>
              )}
              <div className="my-1 border-t border-gray-200 dark:border-gray-700" />
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setOpenDropdown(null);
                  void onPermanentDelete(item);
                }}
                className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm text-red-600 transition-colors hover:bg-red-50 hover:text-red-700 dark:text-red-400 dark:hover:bg-red-900/20 dark:hover:text-red-300"
              >
                <AlertTriangle className="h-4 w-4" />
                Permanently Delete
              </button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

/**
 * The format + protocol + source-material pill row for a catalog item (MFI-23.5).
 *
 * Renders the reusable {@link FormatPill}, {@link ProtocolPill} and {@link SourceBadge}: the
 * imported file format, its paradigm/protocol, and where it came from (file name / URL /
 * live-discovery, derived from the item's `formatMetadata`/`metadata`). Unknown formats degrade to
 * a neutral pill inside the pills themselves; when an item carries none of the three, a muted
 * "Format pending" placeholder is shown instead.
 */
function CatalogFormatBadge({ item }: { item: CatalogItem }) {
  const source = resolveCatalogSource(item.formatMetadata, item.metadata);
  if (!item.sourceFormat && !item.protocol && !source) {
    return <span className="text-xs text-gray-400 dark:text-gray-600">Format pending</span>;
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <FormatPill format={item.sourceFormat} />
      <ProtocolPill protocol={item.protocol} />
      {source ? <SourceBadge source={source} /> : null}
    </span>
  );
}

/** Inline quality score + grade badge (server-captured, MFI-23.2). */
function CatalogQualityBadge({ item }: { item: CatalogItem }) {
  const score = typeof item.qualityScore === 'number' ? item.qualityScore : null;
  if (score === null) {
    return (
      <span className="text-xs text-gray-400 dark:text-gray-600" title="No quality score captured yet">
        —
      </span>
    );
  }
  const tier = getNumericScoreTier(score);
  return (
    <span
      className={`inline-flex items-center gap-1 text-sm font-semibold tabular-nums leading-none ${tier?.textClass ?? ''}`}
      title="Quality score captured at import"
    >
      {score}
      {item.qualityGrade ? (
        <span className="text-xs font-medium opacity-70">({item.qualityGrade})</span>
      ) : null}
    </span>
  );
}

const Catalog = () => {
  const router = useRouter();
  const { data: session } = useSession();
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();

  const [items, setItems] = useState<CatalogItem[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);
  const [dropdownPosition, setDropdownPosition] = useState<{ top: number; right: number } | null>(null);
  const [showDeleted, setShowDeleted] = useState(false);
  const [sortColumn, setSortColumn] = useState<CatalogDashboardSortColumn>('name');
  const [sortDirection, setSortDirection] = useState<CatalogDashboardSortDirection>('asc');
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards');
  const [searchQuery, setSearchQuery] = useState('');
  const [filterChip, setFilterChip] = useState<'all' | 'active' | 'attention' | 'deleted'>('all');
  // Quality-history dialog (the quality orb opens it; a catalog item's id is a project id).
  const [qualityDialogItem, setQualityDialogItem] = useState<CatalogItem | null>(null);
  // Server-backed lint-report dialog (the lint orb / Lint action open it, MFI-23.10).
  const [lintDialogItem, setLintDialogItem] = useState<CatalogItem | null>(null);

  const currentTenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;

  // Browser-local quality snapshots keyed by item id, recomputed when the item set changes. Most
  // catalog items have no local history (they are server-imported) and resolve to an empty array;
  // the card then falls back to the server-captured quality score/grade for its orbs.
  const qualityHistoryCacheRef = useRef<Record<string, ProjectQualitySnapshot[]>>({});
  const catalogQualityHistoryMap = useMemo(() => {
    const cache = qualityHistoryCacheRef.current;
    const map: Record<string, ProjectQualitySnapshot[]> = {};
    for (const item of items) {
      if (!(item.id in cache)) {
        cache[item.id] = getProjectQualityHistory(item.id);
      }
      map[item.id] = cache[item.id];
    }
    return map;
  }, [items]);

  const sortedItems = useMemo(
    () => sortCatalogDashboardRows(items, sortColumn, sortDirection),
    [items, sortColumn, sortDirection]
  );

  const headerSubtitle = useMemo(() => {
    const n = items.length;
    const scored = items
      .map((i) => i.qualityScore)
      .filter((x): x is number => typeof x === 'number');
    const avg =
      scored.length > 0 ? Math.round(scored.reduce((a, b) => a + b, 0) / scored.length) : null;
    const active = items.filter((i) => i.enabled && !i.deleted_at).length;
    const parts: string[] = [`${n} item${n === 1 ? '' : 's'}`];
    if (avg != null) parts.push(`avg quality ${avg}`);
    parts.push(`${active} active`);
    if (showDeleted) {
      const del = items.filter((i) => i.deleted_at).length;
      if (del > 0) parts.push(`${del} deleted`);
    }
    return parts.join(' · ');
  }, [items, showDeleted]);

  const displayedItems = useMemo(() => {
    let rows = sortedItems;
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      rows = rows.filter(
        (i) =>
          i.name.toLowerCase().includes(q) ||
          (i.slug ?? '').toLowerCase().includes(q) ||
          (i.description ?? '').toLowerCase().includes(q) ||
          (i.sourceFormat ?? '').toLowerCase().includes(q) ||
          (i.protocol ?? '').toLowerCase().includes(q)
      );
    }
    if (filterChip === 'active') {
      rows = rows.filter((i) => i.enabled && !i.deleted_at);
    } else if (filterChip === 'attention') {
      rows = rows.filter((i) => !i.enabled || Boolean(i.deleted_at));
    } else if (filterChip === 'deleted') {
      rows = rows.filter((i) => Boolean(i.deleted_at));
    }
    return rows;
  }, [sortedItems, searchQuery, filterChip]);

  const filterChipCounts = useMemo(() => {
    const all = sortedItems.length;
    const active = sortedItems.filter((i) => i.enabled && !i.deleted_at).length;
    const attention = sortedItems.filter((i) => !i.enabled || Boolean(i.deleted_at)).length;
    const deleted = sortedItems.filter((i) => i.deleted_at).length;
    return { all, active, attention, deleted };
  }, [sortedItems]);

  const sortSummaryLabel = useMemo(() => {
    const arrow = sortDirection === 'asc' ? '↑' : '↓';
    const opt = CATALOG_SORT_OPTIONS.find((o) => o.column === sortColumn);
    return `${opt ? opt.label.toLowerCase() : 'sorted'} ${arrow}`;
  }, [sortColumn, sortDirection]);

  const handleSortClick = useCallback((column: CatalogDashboardSortColumn) => {
    setSortColumn((prevCol) => {
      if (prevCol === column) {
        setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
        return prevCol;
      }
      setSortDirection('asc');
      return column;
    });
  }, []);

  const loadCatalog = useCallback(async () => {
    if (!currentTenantId) {
      setItems([]);
      setListLoading(false);
      return;
    }
    setListLoading(true);
    try {
      const qs = showDeleted ? '?include_deleted=true' : '';
      const response = await fetch(`/api/catalog${qs}`);
      if (!response.ok) {
        throw new Error(`Failed to fetch catalog: ${response.statusText}`);
      }
      const data = await response.json();
      if (data.success && Array.isArray(data.catalog)) {
        setItems(data.catalog as CatalogItem[]);
      } else {
        throw new Error(data.error || 'Failed to load catalog');
      }
    } catch (error) {
      console.error('Failed to load catalog:', error);
      setItems([]);
    } finally {
      setListLoading(false);
    }
  }, [currentTenantId, showDeleted]);

  useEffect(() => {
    if (currentTenantId) void loadCatalog();
  }, [currentTenantId, loadCatalog]);

  useEffect(() => {
    if (!showDeleted && filterChip === 'deleted') {
      setFilterChip('all');
    }
  }, [showDeleted, filterChip]);

  /** Open the item's detail view (MFI-23.9): source material, provenance, normalized summary. */
  const handleOpenDetail = useCallback(
    (item: CatalogItem) => {
      router.push(`/ade/dashboard/catalog/${encodeURIComponent(item.id)}`);
    },
    [router]
  );

  /** Navigate to the item's versions (a catalog item's id is a project id). */
  const handleView = useCallback(
    (item: CatalogItem) => {
      router.push(`/ade/dashboard/versions?projectId=${encodeURIComponent(item.id)}`);
    },
    [router]
  );

  /** Open the server-backed lint report (same report Projects use, MFI-23.10) for an item. */
  const handleOpenLint = useCallback((item: CatalogItem) => {
    setLintDialogItem(item);
  }, []);

  /** Open the quality-history dialog for an item. */
  const handleOpenQuality = useCallback((item: CatalogItem) => {
    setQualityDialogItem(item);
  }, []);

  /**
   * "Convert to OpenAPI" — promotes a non-OpenAPI catalog item into a publishable OpenAPI project.
   * The conversion itself is performed by the import routing (MFI-23.7); until that lands, this
   * explains the path rather than silently doing nothing, so the affordance is discoverable.
   */
  const handleConvert = useCallback(
    async (item: CatalogItem) => {
      await alertDialog({
        title: 'Convert to OpenAPI',
        message: `"${item.name}" will be converted from ${
          item.sourceFormat ? `${item.sourceFormat} ` : ''
        }into a publishable OpenAPI project. This is handled by the import routing (MFI-23.7); re-import the source to produce an OpenAPI project from it.`,
        variant: 'info',
      });
    },
    [alertDialog]
  );

  const handleDelete = async (itemId: string) => {
    const confirmed = await confirmDialog({
      title: 'Delete Catalog Item',
      message:
        'This soft-deletes the catalog item (it is hidden from the catalog). You can undelete it later by turning on "Show deleted".',
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });
    if (!confirmed) return;

    try {
      const result = await deleteProject(itemId);
      const response = JSON.parse(result);
      if (response.success) await loadCatalog();
      else await alertDialog({ message: response.error || 'Failed to delete catalog item', variant: 'error' });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'An error occurred';
      await alertDialog({ message, variant: 'error' });
    }
  };

  const handleRestore = async (item: CatalogItem) => {
    const confirmed = await confirmDialog({
      title: 'Undelete Catalog Item',
      message: `Undelete "${item.name}"? It will return to the catalog with the same enabled/disabled state it had before deletion.`,
      variant: 'info',
      confirmLabel: 'Undelete',
      cancelLabel: 'Cancel',
    });
    if (!confirmed) return;

    try {
      const result = await restoreProject(item.id);
      const response = JSON.parse(result);
      if (response.success) {
        toast.success('Catalog item undeleted.');
        await loadCatalog();
      } else {
        await alertDialog({ message: response.error || 'Failed to undelete catalog item', variant: 'error' });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'An error occurred';
      await alertDialog({ message, variant: 'error' });
    }
  };

  const handlePermanentDelete = async (item: CatalogItem) => {
    const confirmed = await confirmDialog({
      title: 'Permanently Delete Catalog Item',
      message: `Are you absolutely sure you want to permanently delete "${item.name}"?\n\nThis will permanently delete the item and all of its versions and associated data.\n\nThis action CANNOT be undone and all data will be lost forever.`,
      variant: 'danger',
      confirmLabel: 'Permanently Delete',
      cancelLabel: 'Cancel',
    });
    if (!confirmed) return;

    const doubleConfirmed = await confirmDialog({
      title: 'Final Confirmation',
      message: `You are about to permanently destroy all data for catalog item "${item.name}". This is your last chance to cancel.`,
      variant: 'danger',
      confirmLabel: 'Yes, Delete Everything',
      cancelLabel: 'Cancel',
    });
    if (!doubleConfirmed) return;

    try {
      const result = await permanentDeleteProject(item.id);
      const response = JSON.parse(result);
      if (response.success) {
        toast.success('Catalog item and all associated data have been permanently deleted.');
        await loadCatalog();
      } else {
        await alertDialog({ message: response.error || 'Failed to permanently delete catalog item', variant: 'error' });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'An error occurred';
      await alertDialog({ message, variant: 'error' });
    }
  };

  const formatDateTime = (dateString: string) => {
    const d = new Date(dateString);
    const datePart = d.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: '2-digit' });
    const timePart = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
    return `${datePart} ${timePart}`;
  };

  if (!session) {
    return (
      <div className="p-6">
        <LoadingState minHeightClassName="min-h-[220px]" message="Loading catalog..." />
      </div>
    );
  }

  if (!currentTenantId) {
    return (
      <div className="p-6">
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-6">
          <div className="flex items-start gap-3">
            <Lock className="h-6 w-6 text-yellow-600 dark:text-yellow-400 flex-shrink-0 mt-1" />
            <div>
              <h2 className="text-lg font-semibold text-yellow-900 dark:text-yellow-100 mb-2">No Tenant Selected</h2>
              <p className="text-yellow-800 dark:text-yellow-200 mb-3">Please select a tenant before browsing the catalog.</p>
              <Button asChild><a href="/ade/dashboard/tenants">Go to Tenants</a></Button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <header className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <div className="px-6 py-4 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
              <Library className="h-6 w-6 shrink-0 text-indigo-500 dark:text-indigo-400" aria-hidden />
              Catalog
            </h2>
            <p className="text-gray-600 dark:text-gray-400 text-sm mt-1">{headerSubtitle}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            <div className="hidden md:flex h-8 items-center gap-2 rounded-md border border-gray-200 bg-white px-3 dark:border-gray-700 dark:bg-gray-900/40">
              <Search className="h-3.5 w-3.5 shrink-0 text-gray-400" aria-hidden />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-40 bg-transparent text-xs outline-none placeholder:text-gray-400 dark:text-gray-200"
                placeholder="Filter catalog…"
                aria-label="Filter catalog"
              />
            </div>
            <div className="flex items-center gap-1 rounded-md border border-gray-200 p-0.5 dark:border-gray-700">
              <button
                type="button"
                onClick={() => setViewMode('cards')}
                className={cn(
                  'flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors',
                  viewMode === 'cards'
                    ? 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400'
                    : 'text-gray-500 hover:text-indigo-500 dark:text-gray-400'
                )}
                aria-pressed={viewMode === 'cards'}
              >
                <LayoutGrid className="h-3.5 w-3.5" aria-hidden />
                Cards
              </button>
              <button
                type="button"
                onClick={() => setViewMode('table')}
                className={cn(
                  'flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors',
                  viewMode === 'table'
                    ? 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400'
                    : 'text-gray-500 hover:text-indigo-500 dark:text-gray-400'
                )}
                aria-pressed={viewMode === 'table'}
              >
                <List className="h-3.5 w-3.5" aria-hidden />
                Table
              </button>
            </div>
            <div className="flex h-9 items-center gap-2 rounded-md border border-gray-200 px-3 dark:border-gray-700 dark:bg-gray-900/30">
              <Label htmlFor="catalog-show-deleted" className="cursor-pointer text-xs font-medium text-gray-700 dark:text-gray-300">
                Show deleted
              </Label>
              <Switch
                id="catalog-show-deleted"
                checked={showDeleted}
                onCheckedChange={setShowDeleted}
                aria-label="Show soft-deleted catalog items in the list"
              />
            </div>
          </div>
        </div>
      </header>

      <main className={dashboardMainClass} aria-busy={listLoading}>
        <div className={dashboardContentStackClass}>
          {listLoading ? (
            <div className={dashboardTableWrapClass}>
              <LoadingState minHeightClassName="min-h-[220px]" message="Loading catalog…" />
            </div>
          ) : items.length === 0 ? (
            <div className={dashboardTableWrapClass}>
              <div className="p-8">
                <EmptyState
                  icon={<BookOpen className="h-10 w-10" />}
                  title="Your catalog is empty"
                  description={
                    <>
                      The catalog holds <strong>OpenAPI-worthy non-OpenAPI imports</strong> — specs in
                      formats other than OpenAPI/Swagger that aren&apos;t publishable Projects yet.
                      Items land here automatically when you import a non-OpenAPI specification; there
                      is nothing to create by hand.
                    </>
                  }
                  variant="compact"
                  showOrbs={false}
                  iconContainerClassName="from-indigo-500 to-purple-600 shadow-indigo-500/30"
                />
              </div>
            </div>
          ) : (
            <>
              <section className="flex flex-wrap items-center gap-2">
                <span className="mr-2 text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Views:
                </span>
                <button
                  type="button"
                  onClick={() => setFilterChip('all')}
                  className={cn(
                    'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                    filterChip === 'all'
                      ? 'border-indigo-300 bg-indigo-500/10 text-indigo-600 dark:border-indigo-600 dark:text-indigo-400'
                      : 'border-gray-200 text-gray-500 hover:border-indigo-300 dark:border-gray-700 dark:text-gray-400 dark:hover:border-indigo-600'
                  )}
                >
                  All <span className="ml-1 font-mono text-gray-400 dark:text-gray-500">{filterChipCounts.all}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setFilterChip('active')}
                  className={cn(
                    'rounded-full border px-3 py-1 text-xs transition-colors',
                    filterChip === 'active'
                      ? 'border-indigo-300 bg-indigo-500/10 font-medium text-indigo-600 dark:border-indigo-600 dark:text-indigo-400'
                      : 'border-gray-200 text-gray-500 hover:border-indigo-300 dark:border-gray-700 dark:text-gray-400'
                  )}
                >
                  Active <span className="ml-1 font-mono">{filterChipCounts.active}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setFilterChip('attention')}
                  className={cn(
                    'rounded-full border px-3 py-1 text-xs transition-colors',
                    filterChip === 'attention'
                      ? 'border-amber-400 bg-amber-500/10 font-medium text-amber-800 dark:border-amber-700/40 dark:text-amber-300'
                      : 'border-gray-200 text-gray-500 hover:border-amber-300 dark:border-gray-700 dark:text-gray-400'
                  )}
                >
                  Needs attention <span className="ml-1 font-mono">{filterChipCounts.attention}</span>
                </button>
                <button
                  type="button"
                  disabled={!showDeleted}
                  title={!showDeleted ? 'Turn on Show deleted to use this view' : undefined}
                  onClick={() => showDeleted && setFilterChip('deleted')}
                  className={cn(
                    'rounded-full border px-3 py-1 text-xs transition-colors',
                    filterChip === 'deleted'
                      ? 'border-indigo-300 bg-indigo-500/10 font-medium text-indigo-600 dark:border-indigo-600 dark:text-indigo-400'
                      : 'border-gray-200 text-gray-500 hover:border-indigo-300 dark:border-gray-700 dark:text-gray-400',
                    !showDeleted && 'cursor-not-allowed opacity-40 hover:border-gray-200 dark:hover:border-gray-700'
                  )}
                >
                  Deleted <span className="ml-1 font-mono">{filterChipCounts.deleted}</span>
                </button>

                <span className="ml-auto flex items-center gap-2">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Sort:
                  </span>
                  {CATALOG_SORT_OPTIONS.map((opt) => {
                    const active = sortColumn === opt.column;
                    return (
                      <button
                        key={opt.column}
                        type="button"
                        onClick={() => handleSortClick(opt.column)}
                        data-testid={`catalog-sort-${opt.column}`}
                        aria-pressed={active}
                        className={cn(
                          'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors',
                          active
                            ? 'border-indigo-300 bg-indigo-500/10 font-medium text-indigo-600 dark:border-indigo-600 dark:text-indigo-400'
                            : 'border-gray-200 text-gray-500 hover:border-indigo-300 dark:border-gray-700 dark:text-gray-400'
                        )}
                      >
                        {opt.label}
                        {active ? (
                          sortDirection === 'asc' ? (
                            <ArrowUp className="h-3 w-3" aria-hidden />
                          ) : (
                            <ArrowDown className="h-3 w-3" aria-hidden />
                          )
                        ) : (
                          <ArrowUpDown className="h-3 w-3 opacity-40" aria-hidden />
                        )}
                      </button>
                    );
                  })}
                </span>
              </section>

              {displayedItems.length === 0 ? (
                <div className={`${dashboardPanelClass} p-10 text-center text-sm text-gray-600 dark:text-gray-400`}>
                  No catalog items match your filters or search.
                </div>
              ) : viewMode === 'cards' ? (
                <section className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
                  {displayedItems.map((item) => {
                    const isDeleted = Boolean(item.deleted_at);
                    return (
                      <CatalogItemCard
                        key={item.id}
                        item={item}
                        qualityHistory={catalogQualityHistoryMap[item.id] ?? []}
                        avatarGradientClass={catalogCardGradientClass(item.id)}
                        avatarInitials={catalogCardInitials(item.name)}
                        creatorInitials={catalogCardInitials(item.creator_name ?? '?')}
                        shortItemId={formatShortCatalogId(item.id)}
                        onOpenQualityHistory={() => handleOpenQuality(item)}
                        onOpenLintReport={() => handleOpenLint(item)}
                        onOpenDetail={() => handleOpenDetail(item)}
                        formatSlot={<CatalogFormatBadge item={item} />}
                        actionsSlot={
                          <CatalogItemActions
                            item={item}
                            isDeleted={isDeleted}
                            openDropdown={openDropdown}
                            setOpenDropdown={setOpenDropdown}
                            dropdownPosition={dropdownPosition}
                            setDropdownPosition={setDropdownPosition}
                            onOpenDetail={handleOpenDetail}
                            onView={handleView}
                            onLint={handleOpenLint}
                            onConvert={handleConvert}
                            onDelete={handleDelete}
                            onRestore={handleRestore}
                            onPermanentDelete={handlePermanentDelete}
                          />
                        }
                      />
                    );
                  })}
                </section>
              ) : (
                <div className={dashboardTableWrapClass}>
                  <div className="overflow-x-auto">
                    <table className="min-w-full">
                      <thead className={dashboardTableTheadClass}>
                        <tr>
                          <th scope="col" className={`${dashboardThClass} w-64`}>Name</th>
                          <th scope="col" className={dashboardThClass}>Description</th>
                          <th scope="col" className={`${dashboardThClass} w-44`}>Format</th>
                          <th scope="col" className={`${dashboardThClass} w-32`}>Quality</th>
                          <th scope="col" className={`${dashboardThClass} w-40`}>Status</th>
                          <th scope="col" className={`${dashboardThClass} w-56`}>Created By</th>
                          <th scope="col" className={`${dashboardThClass} w-40`}>Created</th>
                          <th scope="col" className={`${dashboardThClass} w-40`}>Updated</th>
                          <th scope="col" className={`${dashboardThRightClass} w-24`}>
                            <span className="sr-only">Actions</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody className={dashboardTbodyClass}>
                        {displayedItems.map((item) => {
                          const isDeleted = Boolean(item.deleted_at);
                          return (
                            <tr
                              key={item.id}
                              data-testid="catalog-row"
                              className={isDeleted ? `${dashboardTrHoverClass} opacity-80` : dashboardTrHoverClass}
                            >
                              <td className="px-6 py-4">
                                <div className="flex flex-col gap-1">
                                  {isDeleted ? (
                                    <div className="max-w-xs truncate text-sm font-semibold text-gray-900 dark:text-white" title={item.name}>
                                      {item.name}
                                    </div>
                                  ) : (
                                    <button
                                      type="button"
                                      onClick={() => handleOpenDetail(item)}
                                      className="max-w-xs truncate text-left text-sm font-semibold text-gray-900 hover:text-indigo-600 hover:underline dark:text-white dark:hover:text-indigo-400"
                                      title={`Open ${item.name}`}
                                    >
                                      {item.name}
                                    </button>
                                  )}
                                  <div className="truncate font-mono text-xs text-gray-500 dark:text-gray-400" title={item.slug ?? ''}>
                                    {item.slug || '—'}
                                  </div>
                                </div>
                              </td>
                              <td className="px-6 py-4">
                                <div className="max-w-md truncate text-sm text-gray-600 dark:text-gray-400" title={item.description ?? ''}>
                                  {item.description?.trim() || <span className="text-gray-400 dark:text-gray-600">No description</span>}
                                </div>
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap">
                                <CatalogFormatBadge item={item} />
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap">
                                <CatalogQualityBadge item={item} />
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap">
                                <div className="flex flex-col gap-2">
                                  {item.enabled ? (
                                    <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400">
                                      <span className="h-1.5 w-1.5 rounded-full bg-green-500" /> Enabled
                                    </span>
                                  ) : (
                                    <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-800 dark:bg-gray-700 dark:text-gray-400">
                                      <span className="h-1.5 w-1.5 rounded-full bg-gray-400" /> Disabled
                                    </span>
                                  )}
                                  {item.deleted_at && (
                                    <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900/30 dark:text-red-400">
                                      <Trash2 className="h-3 w-3" /> Deleted
                                    </span>
                                  )}
                                </div>
                              </td>
                              <td className="px-6 py-4">
                                <div className="truncate text-sm text-gray-900 dark:text-white" title={item.creator_name ?? ''}>
                                  {item.creator_name || '—'}
                                </div>
                                <div className="truncate text-xs text-gray-500 dark:text-gray-400" title={item.creator_email ?? ''}>
                                  {item.creator_email || ''}
                                </div>
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap">
                                <div className="text-sm text-gray-500 dark:text-gray-400" title={formatDateTime(item.created_at)}>
                                  {formatDateTime(item.created_at)}
                                </div>
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap">
                                <div className="text-sm text-gray-500 dark:text-gray-400" title={formatDateTime(item.updated_at)}>
                                  {formatDateTime(item.updated_at)}
                                </div>
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap text-right">
                                <CatalogItemActions
                                  item={item}
                                  isDeleted={isDeleted}
                                  openDropdown={openDropdown}
                                  setOpenDropdown={setOpenDropdown}
                                  dropdownPosition={dropdownPosition}
                                  setDropdownPosition={setDropdownPosition}
                                  onOpenDetail={handleOpenDetail}
                                  onView={handleView}
                                  onLint={handleOpenLint}
                                  onConvert={handleConvert}
                                  onDelete={handleDelete}
                                  onRestore={handleRestore}
                                  onPermanentDelete={handlePermanentDelete}
                                />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <p className="text-right text-xs text-gray-500 dark:text-gray-400">
                Sorted by <span className="font-medium text-indigo-600 dark:text-indigo-400">{sortSummaryLabel}</span>
              </p>
            </>
          )}
        </div>
      </main>

      <ProjectQualityHistoryDialog
        key={qualityDialogItem ? qualityDialogItem.id : 'catalog-quality-dialog-closed'}
        open={qualityDialogItem !== null}
        onOpenChange={(open) => {
          if (!open) setQualityDialogItem(null);
        }}
        projectName={qualityDialogItem?.name ?? ''}
        projectId={qualityDialogItem?.id ?? ''}
        history={qualityDialogItem ? catalogQualityHistoryMap[qualityDialogItem.id] ?? [] : []}
        initialSection="quality"
      />

      <CatalogLintReportDialog
        key={lintDialogItem ? lintDialogItem.id : 'catalog-lint-dialog-closed'}
        itemId={lintDialogItem?.id ?? null}
        itemName={lintDialogItem?.name ?? ''}
        open={lintDialogItem !== null}
        onOpenChange={(open) => {
          if (!open) setLintDialogItem(null);
        }}
      />
    </>
  );
};

export default Catalog;
