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
import Link from 'next/link';
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
  CheckCircle2,
  Upload,
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
import { ConversionPreviewDialog } from '../../../components/ade/dashboard/catalog/ConversionPreviewDialog';
import { CatalogSupportedFormats } from '../../../components/ade/dashboard/catalog/CatalogSupportedFormats';
import { CatalogStatsRow } from '../../../components/ade/dashboard/catalog/CatalogStatsRow';
import { CatalogNonPublishableBanner } from '../../../components/ade/dashboard/catalog/CatalogNonPublishableBanner';
import {
  CatalogImportDialog,
  type JsonSchemaHandoffPayload,
} from '../../../components/ade/dashboard/catalog/CatalogImportDialog';
import PrimitiveImportDialog, {
  type PrimitiveImportInitialSource,
} from '../primitives/PrimitiveImportDialog';
import { FormatPill } from '../../../components/ui/catalog/FormatPill';
import { ProtocolPill } from '../../../components/ui/catalog/ProtocolPill';
import { SourceBadge } from '../../../components/ui/catalog/SourceBadge';
import { GradeChip } from '../../../components/ui/catalog/GradeChip';
import { resolveCatalogSource, resolveCatalogFormat } from '../../../utils/catalog-format-registry';
import {
  CatalogFormatFacet,
  type CatalogFormatOption,
} from '../../../components/ade/dashboard/catalog/CatalogFormatFacet';
import {
  convertActionLabel,
  convertedProjectHref,
  convertedProjectLabel,
  isConvertedLinkLive,
  type CatalogConversion,
} from '../../../utils/catalog-conversion';
import {
  catalogCardInitials,
  catalogCardGradientClass,
  catalogItemGrade,
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
import {
  loadCatalogViewPreferences,
  persistCatalogViewPreferences,
  type CatalogGroupMode,
} from '@/app/utils/catalog-view-preferences';
import { groupCatalogItemsByParadigm } from '@/app/utils/catalog-paradigm-grouping';
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
  /** The convert-to-OpenAPI back-link (MFI-23.11): present once the item has been converted. */
  conversion?: CatalogConversion | null;
}

/**
 * "Converted → {project}" back-link (MFI-23.11), shared by the card and table views. Renders a link to
 * the publishable Project the item was converted into (or plain text when that Project was since
 * deleted), noting a re-convert. Renders nothing when the item has never been converted.
 */
function ConvertedBadge({ conversion }: { conversion?: CatalogConversion | null }) {
  if (!conversion) return null;
  const label = convertedProjectLabel(conversion);
  const live = isConvertedLinkLive(conversion);
  const title = conversion.reconverted ? 'Re-converted to an OpenAPI project' : 'Converted to an OpenAPI project';
  return (
    <span
      data-testid="catalog-converted-badge"
      className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
      title={title}
    >
      <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="text-emerald-600/80 dark:text-emerald-400/80">
        {conversion.reconverted ? 'Re-converted →' : 'Converted →'}
      </span>
      {live ? (
        <Link
          href={convertedProjectHref(conversion)}
          onClick={(e) => e.stopPropagation()}
          className="max-w-[12rem] truncate font-semibold underline-offset-2 hover:underline"
        >
          {label}
        </Link>
      ) : (
        <span className="max-w-[12rem] truncate font-semibold text-gray-500 line-through dark:text-gray-400" title="The converted project was deleted">
          {label}
        </span>
      )}
    </span>
  );
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

/** The two grouping modes the card view offers (MFI-24.2), mirroring the sort control. The
 * {@link CatalogGroupMode} type now lives with the persisted view preferences (MFI-28.4). */
const CATALOG_GROUP_OPTIONS: ReadonlyArray<{ mode: CatalogGroupMode; label: string }> = [
  { mode: 'protocol', label: 'Protocol' },
  { mode: 'none', label: 'None' },
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
                    {convertActionLabel(item.conversion)}
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

/**
 * Inline quality score badge (server-captured, MFI-23.2). Shows just the numeric score, tinted by
 * its band — the letter grade now lives in its own table column via {@link GradeChip} (MFI-24.4).
 */
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
  // The four persisted toolbar preferences (MFI-28.4): view mode, card grouping, sort column +
  // direction, and show-deleted are hydrated once from localStorage so a reload restores the last
  // choices, then written back by the effect below whenever any of them changes. The lazy
  // initializers run only on the first render and are SSR-safe (they fall back to defaults on the
  // server).
  const [viewPrefsHydrated] = useState(() => loadCatalogViewPreferences());
  const [showDeleted, setShowDeleted] = useState(viewPrefsHydrated.showDeleted);
  const [sortColumn, setSortColumn] = useState<CatalogDashboardSortColumn>(viewPrefsHydrated.sortColumn);
  const [sortDirection, setSortDirection] = useState<CatalogDashboardSortDirection>(
    viewPrefsHydrated.sortDirection
  );
  const [viewMode, setViewMode] = useState<'cards' | 'table'>(viewPrefsHydrated.viewMode);
  // How the card view is sectioned (MFI-24.2): Protocol groups cards under paradigm headers; None
  // reproduces the flat grid. The table view is always flat regardless of this.
  const [groupMode, setGroupMode] = useState<CatalogGroupMode>(viewPrefsHydrated.groupMode);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterChip, setFilterChip] = useState<'all' | 'active' | 'attention' | 'deleted'>('all');
  // Selected format ids for the format facet (MFI-28.4). An empty set means "all formats". This is
  // intentionally not persisted: it is scoped to the formats actually present in the current list.
  const [selectedFormats, setSelectedFormats] = useState<string[]>([]);
  // Quality-history dialog (the quality orb opens it; a catalog item's id is a project id).
  const [qualityDialogItem, setQualityDialogItem] = useState<CatalogItem | null>(null);
  // Server-backed lint-report dialog (the lint orb / Lint action open it, MFI-23.10).
  const [lintDialogItem, setLintDialogItem] = useState<CatalogItem | null>(null);
  const [convertDialogItem, setConvertDialogItem] = useState<CatalogItem | null>(null);
  // Import flow (MFI-23.12): the catalog owns the alternative (non-OpenAPI) format intake. An import
  // that produces a non-publishable item lands right back in this list, so we just reload on success.
  const [showImportDialog, setShowImportDialog] = useState(false);
  const [primitiveImportSource, setPrimitiveImportSource] = useState<PrimitiveImportInitialSource | null>(null);

  const currentTenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const currentUserId = (session?.user as { user_id?: string } | undefined)?.user_id;

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

  // The per-metric counts (items, active, avg quality, formats, converted) now live in the stats
  // row (MFI-24.1); the header keeps a short, static description of what the Catalog holds.
  const headerSubtitle = 'OpenAPI-worthy non-OpenAPI imports';

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
    // Format facet (MFI-28.4): when one or more formats are selected, keep only items whose
    // registry-resolved source format is in the selection. Items with an unrecognised/absent format
    // resolve to no id and are excluded while any format filter is active.
    if (selectedFormats.length > 0) {
      const wanted = new Set(selectedFormats);
      rows = rows.filter((i) => {
        const id = resolveCatalogFormat(i.sourceFormat)?.id;
        return id !== undefined && wanted.has(id);
      });
    }
    return rows;
  }, [sortedItems, searchQuery, filterChip, selectedFormats]);

  // The distinct formats present in the loaded catalog (MFI-28.4), each resolved to its registry
  // label, sorted alphabetically. This feeds the format facet so it only ever offers formats that
  // actually appear in the list. Derived from the full item set (not the filtered view) so toggling
  // one format never makes the others disappear from the menu.
  const availableFormats = useMemo<CatalogFormatOption[]>(() => {
    const byId = new Map<string, CatalogFormatOption>();
    for (const item of items) {
      const fmt = resolveCatalogFormat(item.sourceFormat);
      if (fmt && !byId.has(fmt.id)) byId.set(fmt.id, { id: fmt.id, label: fmt.label });
    }
    return [...byId.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [items]);

  // Card view sectioned by resolved paradigm (MFI-24.2), in fixed graph→rpc→event→rest→data-schema
  // order with a trailing "Other" bucket; built off the already filtered/sorted list so grouping
  // composes with filter/search/sort. Only consumed when groupMode === 'protocol'.
  const paradigmGroups = useMemo(
    () => groupCatalogItemsByParadigm(displayedItems),
    [displayedItems]
  );

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

  // Persist the toolbar preferences whenever any of them changes (MFI-28.4). Writing on every
  // change (including the initial mount, which just re-writes the hydrated values) keeps
  // localStorage authoritative without a separate save button.
  useEffect(() => {
    persistCatalogViewPreferences({ viewMode, groupMode, sortColumn, sortDirection, showDeleted });
  }, [viewMode, groupMode, sortColumn, sortDirection, showDeleted]);

  // Drop any selected format that is no longer present in the list (e.g. after the last item of a
  // format is deleted), so the facet's active count never counts a format the menu can't show.
  useEffect(() => {
    setSelectedFormats((prev) => {
      const present = new Set(availableFormats.map((f) => f.id));
      const next = prev.filter((id) => present.has(id));
      return next.length === prev.length ? prev : next;
    });
  }, [availableFormats]);

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
   * "Convert to OpenAPI" — opens the reviewed-conversion preview (MFI-22.4). The preview dry-runs
   * the catalog → OpenAPI conversion (MFI-22.6), shows the fidelity report + warning, and only
   * commits (creating a new OpenAPI project/version, MFI-22.5) once the user confirms.
   */
  const handleConvert = useCallback((item: CatalogItem) => {
    setConvertDialogItem(item);
  }, []);

  /** After a successful conversion, refresh the catalog list so the new project is reflected. */
  const handleConverted = useCallback(() => {
    toast.success('Conversion complete — a new OpenAPI project was created.');
    void loadCatalog();
  }, [loadCatalog]);

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

  /**
   * Render a single catalog card. Shared by the flat grid (Group=None) and the per-paradigm sections
   * (Group=Protocol, MFI-24.2) so both render an identical card; the only difference is the wrapper.
   */
  const renderCatalogCard = (item: CatalogItem) => {
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
        conversionSlot={<ConvertedBadge conversion={item.conversion} />}
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
          {/* The header keeps only the primary Import action; every list control (search, view
              toggle, filters, format facet, group, sort, show-deleted) is consolidated into the
              single sticky toolbar below (MFI-28.4). */}
          {currentUserId ? (
            <div className="flex flex-wrap items-center gap-2 lg:justify-end">
              <Button size="sm" onClick={() => setShowImportDialog(true)}>
                <Upload className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                Import
              </Button>
            </div>
          ) : null}
        </div>
      </header>

      <main className={dashboardMainClass} aria-busy={listLoading}>
        <div className={dashboardContentStackClass}>
          {/* Persistent non-publishable info banner (MFI-24.3). Rendered above the gallery, stats and
              toolbar so it shows on both the empty and populated list, matching the mockup. */}
          <CatalogNonPublishableBanner />
          {/* Auto-expand the gallery for an empty catalog (nothing imported yet); collapse it once
              there are items. Keying on that boundary remounts with the right initial state. */}
          <CatalogSupportedFormats
            key={!listLoading && items.length === 0 ? 'formats-open' : 'formats-collapsed'}
            defaultOpen={!listLoading && items.length === 0}
          />
          {listLoading ? (
            <div className={dashboardTableWrapClass}>
              <LoadingState minHeightClassName="min-h-[220px]" message="Loading catalog…" />
            </div>
          ) : (
            <>
              {/* Four metric cards summarising the live catalog (MFI-24.1), computed from the
                  already-fetched list. Renders above the unified toolbar; suppressed on the empty
                  catalog so the empty state leads. */}
              {items.length > 0 ? <CatalogStatsRow items={items} /> : null}

              {/* Unified, sticky list toolbar (MFI-28.4): every list control now lives on one panel
                  with one idiom — search · format facet · view toggle · show-deleted (row one) and
                  the view filter chips · group · sort (row two). The view/group/sort/show-deleted
                  choices are persisted (restored on reload). Rendered in both the empty and populated
                  states so Show deleted stays reachable when the active list is empty but soft-deleted
                  items exist. */}
              <section
                data-testid="catalog-toolbar"
                aria-label="Catalog list controls"
                className="sticky top-0 z-20 flex flex-col gap-3 rounded-lg border border-gray-200 bg-white/95 p-3 shadow-sm backdrop-blur dark:border-gray-700 dark:bg-gray-800/95"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex h-8 items-center gap-2 rounded-md border border-gray-200 bg-white px-3 transition-colors focus-within:border-indigo-400 dark:border-gray-700 dark:bg-gray-900/40 dark:focus-within:border-indigo-500">
                    <Search className="h-3.5 w-3.5 shrink-0 text-gray-400" aria-hidden />
                    <input
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-32 bg-transparent text-xs outline-none placeholder:text-gray-400 sm:w-40 lg:w-52 dark:text-gray-200"
                      placeholder="Filter catalog…"
                      aria-label="Filter catalog"
                    />
                  </div>
                  {/* Format facet (MFI-28.4): filter by the formats actually present in the list. */}
                  <CatalogFormatFacet
                    options={availableFormats}
                    selected={selectedFormats}
                    onChange={setSelectedFormats}
                  />
                  <span className="ml-auto flex flex-wrap items-center gap-2">
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
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2">
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

                <span className="ml-auto flex flex-wrap items-center gap-2">
                  {viewMode === 'cards' ? (
                    <>
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                        Group:
                      </span>
                      {CATALOG_GROUP_OPTIONS.map((opt) => {
                        const active = groupMode === opt.mode;
                        return (
                          <button
                            key={opt.mode}
                            type="button"
                            onClick={() => setGroupMode(opt.mode)}
                            data-testid={`catalog-group-${opt.mode}`}
                            aria-pressed={active}
                            className={cn(
                              'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors',
                              active
                                ? 'border-indigo-300 bg-indigo-500/10 font-medium text-indigo-600 dark:border-indigo-600 dark:text-indigo-400'
                                : 'border-gray-200 text-gray-500 hover:border-indigo-300 dark:border-gray-700 dark:text-gray-400'
                            )}
                          >
                            {opt.label}
                          </button>
                        );
                      })}
                      <span className="mx-1 hidden h-4 w-px bg-gray-200 dark:bg-gray-700 sm:block" aria-hidden />
                    </>
                  ) : null}
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
                </div>
              </section>

              {items.length === 0 ? (
                <div className={dashboardTableWrapClass}>
                  <div className="p-8">
                    <EmptyState
                      icon={<BookOpen className="h-10 w-10" />}
                      title="Your catalog is empty"
                      description={
                        <>
                          The catalog holds <strong>OpenAPI-worthy non-OpenAPI imports</strong> — specs in
                          formats other than OpenAPI/Swagger that aren&apos;t publishable Projects yet. Use
                          <strong> Import</strong> above to bring in a supported source (gRPC/Protobuf,
                          GraphQL, or AsyncAPI); it is stored in its original format and converted to
                          OpenAPI only when you&apos;re ready.
                        </>
                      }
                      variant="compact"
                      showOrbs={false}
                      iconContainerClassName="from-indigo-500 to-purple-600 shadow-indigo-500/30"
                    />
                  </div>
                </div>
              ) : displayedItems.length === 0 ? (
                <div className={`${dashboardPanelClass} p-10 text-center text-sm text-gray-600 dark:text-gray-400`}>
                  No catalog items match your filters or search.
                </div>
              ) : viewMode === 'cards' ? (
                groupMode === 'protocol' ? (
                  // Group=Protocol: one section per paradigm (header = label + live count + divider),
                  // in fixed graph→rpc→event→rest→data-schema order with empty paradigms omitted.
                  <div className="flex flex-col">
                    {paradigmGroups.map((group) => (
                      <section key={group.id} data-testid={`catalog-paradigm-group-${group.id}`}>
                        <div className="mb-3 mt-5 flex items-center gap-2.5 first:mt-0">
                          <span className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                            {group.label}
                          </span>
                          <span className="text-[11px] text-gray-400 dark:text-gray-500">
                            {group.items.length} item{group.items.length === 1 ? '' : 's'}
                          </span>
                          <span className="h-px flex-1 bg-gray-200 dark:bg-gray-700" aria-hidden />
                        </div>
                        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
                          {group.items.map(renderCatalogCard)}
                        </div>
                      </section>
                    ))}
                  </div>
                ) : (
                  <section className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
                    {displayedItems.map(renderCatalogCard)}
                  </section>
                )
              ) : (
                <div className={dashboardTableWrapClass}>
                  <div className="overflow-x-auto">
                    <table className="min-w-full">
                      <thead className={dashboardTableTheadClass}>
                        {/* 8 mockup columns in order (MFI-24.4): Artifact / Format / Protocol /
                            Source / Quality / Grade / Status / Updated, then the actions column. */}
                        <tr>
                          <th scope="col" className={`${dashboardThClass} w-72`}>Artifact</th>
                          <th scope="col" className={`${dashboardThClass} w-44`}>Format</th>
                          <th scope="col" className={`${dashboardThClass} w-40`}>Protocol</th>
                          <th scope="col" className={`${dashboardThClass} w-44`}>Source</th>
                          <th scope="col" className={`${dashboardThClass} w-28`}>Quality</th>
                          <th scope="col" className={`${dashboardThClass} w-24`}>Grade</th>
                          <th scope="col" className={`${dashboardThClass} w-40`}>Status</th>
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
                              {/* Artifact: avatar (.av.sm) + name + short id, matching the mockup's
                                  nmcell (MFI-24.4). */}
                              <td className="px-6 py-4">
                                <div className="flex items-center gap-3">
                                  <span
                                    className={cn(
                                      'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gradient-to-br font-mono text-[11px] font-bold text-white',
                                      catalogCardGradientClass(item.id)
                                    )}
                                    aria-hidden
                                  >
                                    {catalogCardInitials(item.name)}
                                  </span>
                                  <div className="flex min-w-0 flex-col gap-1">
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
                                    <div className="truncate font-mono text-xs text-gray-500 dark:text-gray-400" title={item.slug ?? formatShortCatalogId(item.id)}>
                                      {item.slug || formatShortCatalogId(item.id)}
                                    </div>
                                    {item.conversion ? (
                                      <div className="mt-1">
                                        <ConvertedBadge conversion={item.conversion} />
                                      </div>
                                    ) : null}
                                  </div>
                                </div>
                              </td>
                              {/* Format / Protocol / Source split out of the bundled pill row so each
                                  gets its own column (MFI-24.4). */}
                              <td className="px-6 py-4 whitespace-nowrap">
                                {item.sourceFormat ? (
                                  <FormatPill format={item.sourceFormat} />
                                ) : (
                                  <span className="text-xs text-gray-400 dark:text-gray-600">—</span>
                                )}
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap">
                                {item.protocol ? (
                                  <ProtocolPill protocol={item.protocol} />
                                ) : (
                                  <span className="text-xs text-gray-400 dark:text-gray-600">—</span>
                                )}
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap">
                                {(() => {
                                  const source = resolveCatalogSource(item.formatMetadata, item.metadata);
                                  return source ? (
                                    <SourceBadge source={source} />
                                  ) : (
                                    <span className="text-xs text-gray-400 dark:text-gray-600">—</span>
                                  );
                                })()}
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap">
                                <CatalogQualityBadge item={item} />
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap">
                                <GradeChip grade={catalogItemGrade(item)} />
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

              {items.length > 0 ? (
                <p className="text-right text-xs text-gray-500 dark:text-gray-400">
                  Sorted by <span className="font-medium text-indigo-600 dark:text-indigo-400">{sortSummaryLabel}</span>
                </p>
              ) : null}
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

      <ConversionPreviewDialog
        key={convertDialogItem ? convertDialogItem.id : 'catalog-convert-dialog-closed'}
        itemId={convertDialogItem?.id ?? null}
        itemName={convertDialogItem?.name ?? ''}
        sourceFormat={convertDialogItem?.sourceFormat ?? null}
        open={convertDialogItem !== null}
        onOpenChange={(open) => {
          if (!open) setConvertDialogItem(null);
        }}
        onConverted={handleConverted}
      />

      {/* Catalog importer (MFI-23.7): store-raw intake — the source is kept in its original format
          and converted only when the user is ready, not at import time. */}
      {currentTenantId && currentUserId ? (
        <CatalogImportDialog
          open={showImportDialog}
          onClose={() => setShowImportDialog(false)}
          onSuccess={() => {
            void loadCatalog();
          }}
          onJsonSchemaAsCurrent={(payload: JsonSchemaHandoffPayload) => {
            setPrimitiveImportSource({
              sourceKind: 'json-schema',
              sourceMethod: 'paste',
              text: payload.text,
              document: payload.document,
              label: payload.label,
            });
          }}
        />
      ) : null}

      {primitiveImportSource ? (
        <PrimitiveImportDialog
          initialSource={primitiveImportSource}
          onClose={() => setPrimitiveImportSource(null)}
          onComplete={() => {
            setPrimitiveImportSource(null);
          }}
          onMessage={(type, message) => {
            if (type === 'success') toast.success(message);
            else toast.error(message);
          }}
        />
      ) : null}
    </>
  );
};

export default Catalog;
