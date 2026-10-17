/**
 * The Versions header's overflow rows, project switcher rows and copy-link chord
 * (HIVE-11.3, #5599).
 *
 * Authority: `docs/mockups/proposals/versions-status-strip.html` annotations **1** and **2**.
 * The header used to carry six controls — a project `<select>`, Import, Compare, Merge
 * branches, a honey `gitlike` flag and New version. It now carries **Compare · Import · ⋯ ·
 * New version**; the project switcher is the breadcrumb's last step, and the ⋯ menu holds:
 *
 * | Row | Was |
 * | --- | --- |
 * | Merge branches… `gitlike` | the header's Merge branches button and its honey flag |
 * | Sunset timeline | the description link (which stays) and the facts card |
 * | Published surface | the project facts card's link (which stays) |
 * | Export studio | the project facts card's link (which stays), behind the same release gate |
 * | Copy link to project ⌘⇧C | new |
 *
 * Everything here is pure data the page renders through `PageHeader`'s `overflow` and
 * `crumbSwitcher` slots, so it is tested without the page.
 */

import { FolderKanban, GitMerge, Globe, Link2, PackageOpen, Sunset } from 'lucide-react';

import type { BreadcrumbSwitcherItem } from '@/app/components/shell/BreadcrumbSwitcher';
import type { PageHeaderOverflowItem } from '@/app/components/shell/PageHeaderOverflow';
import { FormatPill } from '@/app/components/ui/catalog/FormatPill';
import { isProjectPublishable } from '@/app/utils/catalog-publishable';
import { COPY_PROJECT_LINK_SHORTCUT, formatShortcutKeys } from '@lib/shortcuts';

export { COPY_PROJECT_LINK_SHORTCUT };

import { EXPORT_STUDIO_ROUTE, PUBLISHED_ROUTE } from './ProjectFactsCard';
import { SUNSET_TIMELINE_ROUTE } from './VersionsStatusStrip';
import {
  GITLIKE_FLAG_LABEL,
  GITLIKE_FLAG_TITLE,
  type GitlikeAffordance,
  type Project,
} from './versionsModel';

/** The Versions route, which a project link points at. */
export const VERSIONS_ROUTE = '/ade/dashboard/versions';

/** Where the switcher's footer goes. */
export const ALL_PROJECTS_ROUTE = '/ade/dashboard/projects';

/** The footer row's glyph. */
export const ALL_PROJECTS_ICON = FolderKanban;

/** The ⋯ menu's heading. */
export const VERSIONS_OVERFLOW_HEADING = 'This project';

/** Why Merge branches is unavailable with fewer than two named branches. */
export const MERGE_NEEDS_BRANCHES = 'Create at least two named branches to merge';

/** Why a project-scoped row is unavailable before a project is chosen. */
export const NEEDS_PROJECT = 'Choose a project first';

/** The chord as `aria-keyshortcuts` spells it — both platforms' command modifier. */
export const COPY_PROJECT_LINK_KEYSHORTCUTS = 'Meta+Shift+C Control+Shift+C';

/**
 * The absolute link to a project's Versions page.
 *
 * @param origin `window.location.origin`.
 * @param projectId The project.
 * @returns `https://…/ade/dashboard/versions?projectId=…`.
 */
export function projectVersionsLink(origin: string, projectId: string): string {
  return `${origin}${VERSIONS_ROUTE}?projectId=${encodeURIComponent(projectId)}`;
}

/** What {@link versionsOverflowItems} needs to know. */
export interface VersionsOverflowContext {
  /** How this build treats git-like affordances. */
  gitlike: GitlikeAffordance;
  /** The selected project, or `''`/`null` before one is chosen. */
  projectId: string | null;
  /** How many named branches the project has. */
  branchCount: number;
  /** Whether the Export studio has been released (`lib/feature-release.ts`). */
  exportStudioReleased: boolean;
  /** Open the merge dialog. */
  onOpenMerge: () => void;
  /** Copy the project link. */
  onCopyLink: () => void;
}

/**
 * The ⋯ menu's rows, in mockup order.
 *
 * @param context See {@link VersionsOverflowContext}.
 * @returns The rows for `PageHeader`'s `overflow` slot.
 */
export function versionsOverflowItems({
  gitlike,
  projectId,
  branchCount,
  exportStudioReleased,
  onOpenMerge,
  onCopyLink,
}: VersionsOverflowContext): PageHeaderOverflowItem[] {
  const items: PageHeaderOverflowItem[] = [];

  if (gitlike.visible) {
    items.push({
      id: 'merge',
      label: 'Merge branches…',
      icon: GitMerge,
      onSelect: onOpenMerge,
      disabledReason: !gitlike.enabled
        ? GITLIKE_FLAG_TITLE
        : !projectId
          ? NEEDS_PROJECT
          : branchCount < 2
            ? MERGE_NEEDS_BRANCHES
            : undefined,
      badge: gitlike.marked ? GITLIKE_FLAG_LABEL : undefined,
    });
  }

  items.push(
    {
      id: 'sunset-timeline',
      label: 'Sunset timeline',
      icon: Sunset,
      href: SUNSET_TIMELINE_ROUTE,
    },
    {
      id: 'published',
      label: 'Published surface',
      icon: Globe,
      href: PUBLISHED_ROUTE,
    },
  );

  if (exportStudioReleased) {
    items.push({
      id: 'export-studio',
      label: 'Export studio',
      icon: PackageOpen,
      href: EXPORT_STUDIO_ROUTE,
    });
  }

  items.push({
    id: 'copy-link',
    label: 'Copy link to project',
    icon: Link2,
    onSelect: onCopyLink,
    disabledReason: projectId ? undefined : NEEDS_PROJECT,
    kbd: formatShortcutKeys(COPY_PROJECT_LINK_SHORTCUT),
    keyShortcuts: COPY_PROJECT_LINK_KEYSHORTCUTS,
    separatorBefore: true,
  });

  return items;
}

/**
 * The breadcrumb switcher's rows: one per selectable project, with its format pill.
 *
 * The page passes its `selectableProjects`, which already excludes catalog items (#4587)
 * except a deep-linked one that is the current selection. A publishable project is an
 * OpenAPI project, the same rule the title's format pill follows; a catalog item draws no pill.
 *
 * @param projects The selectable projects.
 * @returns The switcher rows, filterable by name and slug.
 */
export function versionsSwitcherItems(projects: readonly Project[]): BreadcrumbSwitcherItem[] {
  return projects.map((project) => ({
    id: project.id,
    label: project.name,
    keywords: project.slug,
    leading: isProjectPublishable(project) ? <FormatPill format="openapi" /> : undefined,
  }));
}
