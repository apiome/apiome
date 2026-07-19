'use client';

/**
 * Persistent Authoring context (UXE-1.2).
 *
 * Owns the Tenant → Project → Version → Environment scope for every surface in
 * the `/ade/authoring` route group, keeps it in the URL so a copied link
 * restores the same view, and exposes the operational state the shell reports
 * through its status badges.
 */

import * as React from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { useSession } from 'next-auth/react';
import {
  applyAuthoringScope,
  parseAuthoringScope,
  authoringUrlScopesEqual,
  type AuthoringScope,
  type AuthoringUrlScope,
} from '@lib/authoring/scope';
import {
  getAuthoringEnvironment,
  type AuthoringEnvironment,
  type AuthoringEnvironmentId,
} from '@lib/authoring/environments';
import {
  fetchAuthoringProjects,
  fetchAuthoringVersions,
  isAuthoringScopeReadOnly,
} from '@lib/authoring/scope-client';
import type { AuthoringProjectOption, AuthoringVersionOption } from '@lib/authoring/commands';
import { resolveAuthoringStateBadges, type AuthoringStateBadge } from '@lib/authoring/state-badges';
import {
  clearAuthoringResume,
  readAuthoringResume,
  writeAuthoringResume,
  type AuthoringResumeEntry,
} from '@lib/authoring/resume';
import { resolveAuthoringSurface, type AuthoringSurface } from '@lib/authoring/surfaces';

/** Everything the shell and its surfaces read from context. */
export type AuthoringContextValue = {
  /** Current scope, including the session-owned tenant. */
  scope: AuthoringScope;
  /** Resolved environment lane descriptor. */
  environment: AuthoringEnvironment;
  /** Surface for the current route, when inside the route group. */
  surface: AuthoringSurface | undefined;

  projects: AuthoringProjectOption[];
  versions: AuthoringVersionOption[];
  /** The selected version row, when it resolved. */
  selectedVersion: AuthoringVersionOption | undefined;

  /** License flags granted to this session. */
  entitledFlags: ReadonlySet<string>;

  setProjectId: (projectId: string | null) => void;
  setVersionId: (versionId: string | null) => void;
  setEnvironmentId: (environmentId: AuthoringEnvironmentId) => void;

  /** True while projects or versions are loading. */
  loading: boolean;
  /** True when the selected scope cannot be edited. */
  readOnly: boolean;
  /** False when the browser reports no connection. */
  online: boolean;

  /** Surfaces report their own save state through these. */
  setUnsavedChanges: (unsaved: boolean) => void;
  setSaving: (saving: boolean) => void;
  setConflict: (conflict: boolean) => void;

  /** Ordered status badges for the current state. */
  stateBadges: AuthoringStateBadge[];

  /** The remembered session for this tenant, when one exists. */
  resume: AuthoringResumeEntry | null;
};

/**
 * Event dispatched on `window` after the shell writes scope with the History
 * API, so the provider re-reads the URL it just wrote.
 */
export const AUTHORING_SCOPE_CHANGED_EVENT = 'authoring:scope-changed';

/**
 * Load state of one scope list.
 *
 * `loaded` is an authoritative answer from the server, including an empty one.
 * `failed` is not: it proves nothing about what the viewer may see, so the
 * shell must not act on it as though the list were genuinely empty.
 */
type ListState<T> = {
  status: 'idle' | 'loading' | 'loaded' | 'failed';
  rows: T[];
};

/** Starting state for a list that has not been requested yet. */
function idleList<T>(): ListState<T> {
  return { status: 'idle', rows: [] };
}

const AuthoringContext = React.createContext<AuthoringContextValue | undefined>(undefined);

/** Props for {@link AuthoringProvider}. */
export type AuthoringProviderProps = {
  children: React.ReactNode;
  /** License flags resolved server-side by `getCommercialAccessForSession()`. */
  entitledFlags: readonly string[];
};

/**
 * Provide Authoring scope to a subtree.
 *
 * @param props - Children and the session's license flags.
 */
export function AuthoringProvider({ children, entitledFlags }: AuthoringProviderProps) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { data: session } = useSession();
  const tenantId =
    (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id ?? null;

  // Bumped whenever the shell writes scope with the History API. `popstate`
  // covers browser Back/Forward; `useSearchParams` covers real router
  // navigations (e.g. a palette destination). All three only *trigger* a
  // re-read — `window.location` is the single source of truth, because
  // `useSearchParams` can lag behind a native history transition.
  const [historyTick, setHistoryTick] = React.useState(0);

  React.useEffect(() => {
    const onChange = () => setHistoryTick((tick) => tick + 1);
    window.addEventListener('popstate', onChange);
    window.addEventListener(AUTHORING_SCOPE_CHANGED_EVENT, onChange);
    return () => {
      window.removeEventListener('popstate', onChange);
      window.removeEventListener(AUTHORING_SCOPE_CHANGED_EVENT, onChange);
    };
  }, []);

  const urlScope = React.useMemo(() => {
    // On the server there is no location, so fall back to the router's params.
    const search =
      typeof window === 'undefined' ? (searchParams?.toString() ?? '') : window.location.search;
    return parseAuthoringScope(new URLSearchParams(search));
    // `searchParams` and `historyTick` are read as change signals.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, historyTick]);

  const [projectsState, setProjectsState] =
    React.useState<ListState<AuthoringProjectOption>>(idleList());
  const [versionsState, setVersionsState] =
    React.useState<ListState<AuthoringVersionOption>>(idleList());
  const [online, setOnline] = React.useState(true);
  const [unsavedChanges, setUnsavedChanges] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [conflict, setConflict] = React.useState(false);
  const [resume, setResume] = React.useState<AuthoringResumeEntry | null>(null);

  const flagSet = React.useMemo(() => new Set(entitledFlags), [entitledFlags]);
  const surface = React.useMemo(() => resolveAuthoringSurface(pathname), [pathname]);
  const environment = React.useMemo(
    () => getAuthoringEnvironment(urlScope.environmentId),
    [urlScope.environmentId]
  );

  /**
   * Write scope into the address bar without a Next.js navigation.
   *
   * `history.replaceState` keeps a scope change out of the back stack — Back
   * should leave Authoring, not walk through every project the viewer tried —
   * while still producing a URL that is correct to copy at any moment.
   */
  const commitScope = React.useCallback(
    (next: AuthoringUrlScope) => {
      if (typeof window === 'undefined') return;
      if (authoringUrlScopesEqual(next, urlScope)) return;

      const params = applyAuthoringScope(new URLSearchParams(window.location.search), next);
      const query = params.toString();
      window.history.replaceState(
        window.history.state,
        '',
        `${window.location.pathname}${query ? `?${query}` : ''}`
      );
      // The History API fires no event of its own, so announce the write on a
      // dedicated channel. A synthetic `popstate` would reach every listener on
      // the page, including unrelated ones that treat it as real navigation.
      window.dispatchEvent(new Event(AUTHORING_SCOPE_CHANGED_EVENT));
    },
    [urlScope]
  );

  const setProjectId = React.useCallback(
    (projectId: string | null) => {
      // Dropping the version on a project change is what keeps stale
      // cross-project data from rendering under the new project's heading.
      commitScope({ ...urlScope, projectId, versionId: null });
    },
    [commitScope, urlScope]
  );

  const setVersionId = React.useCallback(
    (versionId: string | null) => {
      commitScope({ ...urlScope, versionId });
    },
    [commitScope, urlScope]
  );

  const setEnvironmentId = React.useCallback(
    (environmentId: AuthoringEnvironmentId) => {
      commitScope({ ...urlScope, environmentId });
    },
    [commitScope, urlScope]
  );

  // Network state drives the Offline badge.
  React.useEffect(() => {
    if (typeof window === 'undefined') return;
    const update = () => setOnline(window.navigator.onLine !== false);
    update();
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
    };
  }, []);

  // Remembered session, read once per tenant.
  React.useEffect(() => {
    setResume(readAuthoringResume(tenantId));
  }, [tenantId]);

  // Projects for the active tenant. Switching tenants resets to `idle` first so
  // the previous tenant's projects are never offered under the new one.
  React.useEffect(() => {
    if (!tenantId) {
      setProjectsState(idleList());
      return;
    }

    const controller = new AbortController();
    setProjectsState({ status: 'loading', rows: [] });
    fetchAuthoringProjects(controller.signal)
      .then((rows) => {
        if (!controller.signal.aborted) setProjectsState({ status: 'loaded', rows });
      })
      .catch(() => {
        // A failure is not an authoritative "no projects" — see `failed` below.
        if (!controller.signal.aborted) setProjectsState({ status: 'failed', rows: [] });
      });

    // Status is set by whichever branch resolves, and an aborted run is always
    // followed by another effect run that sets its own status — so no code path
    // can leave the shell stranded reporting "Loading".
    return () => controller.abort();
  }, [tenantId]);

  // Versions for the selected project.
  React.useEffect(() => {
    if (!urlScope.projectId) {
      setVersionsState(idleList());
      return;
    }

    const controller = new AbortController();
    setVersionsState({ status: 'loading', rows: [] });
    fetchAuthoringVersions(urlScope.projectId, controller.signal)
      .then((rows) => {
        if (!controller.signal.aborted) setVersionsState({ status: 'loaded', rows });
      })
      .catch(() => {
        if (!controller.signal.aborted) setVersionsState({ status: 'failed', rows: [] });
      });

    return () => controller.abort();
  }, [urlScope.projectId]);

  const projects = projectsState.rows;
  const versions = versionsState.rows;

  /*
   * A project id the session cannot see — a stale bookmark, or a link from
   * someone with wider access — is cleared rather than rendered.
   *
   * This keys off `status === 'loaded'`, not `rows.length`: an empty list is a
   * definitive "you have no projects" and must scrub the scope, whereas a
   * failed request proves nothing and must leave it alone rather than
   * destroying a scope over a transient blip.
   */
  React.useEffect(() => {
    if (projectsState.status !== 'loaded' || !urlScope.projectId) return;
    if (!projectsState.rows.some((project) => project.id === urlScope.projectId)) {
      commitScope({ ...urlScope, projectId: null, versionId: null });
    }
  }, [projectsState, urlScope, commitScope]);

  // Same for a version that does not belong to the selected project.
  React.useEffect(() => {
    if (versionsState.status !== 'loaded' || !urlScope.versionId) return;
    if (!versionsState.rows.some((version) => version.id === urlScope.versionId)) {
      commitScope({ ...urlScope, versionId: null });
    }
  }, [versionsState, urlScope, commitScope]);

  const selectedVersion = React.useMemo(
    () => versions.find((version) => version.id === urlScope.versionId),
    [versions, urlScope.versionId]
  );

  /*
   * Remember a scope only once both halves are confirmed to belong to this
   * session. Writing it earlier would persist a scope the guards above are
   * about to scrub, and then re-offer it on every later visit.
   */
  const scopeAuthorized =
    projectsState.status === 'loaded' &&
    versionsState.status === 'loaded' &&
    Boolean(urlScope.projectId) &&
    projectsState.rows.some((project) => project.id === urlScope.projectId) &&
    Boolean(selectedVersion);

  React.useEffect(() => {
    if (!surface || !scopeAuthorized || !urlScope.projectId || !urlScope.versionId) return;
    const entry = writeAuthoringResume(tenantId, {
      surfaceId: surface.id,
      projectId: urlScope.projectId,
      versionId: urlScope.versionId,
      environmentId: urlScope.environmentId,
    });
    if (entry) setResume(entry);
  }, [
    tenantId,
    surface,
    scopeAuthorized,
    urlScope.projectId,
    urlScope.versionId,
    urlScope.environmentId,
  ]);

  // A remembered entry pointing at a project the viewer can no longer see is
  // forgotten, so it stops being offered on every visit.
  React.useEffect(() => {
    if (projectsState.status !== 'loaded' || !resume) return;
    if (!projectsState.rows.some((project) => project.id === resume.projectId)) {
      clearAuthoringResume(tenantId);
      setResume(null);
    }
  }, [projectsState, resume, tenantId]);

  const loading = projectsState.status === 'loading' || versionsState.status === 'loading';
  const readOnly = isAuthoringScopeReadOnly(selectedVersion, environment.readOnly);
  const entitled = React.useMemo(
    () => !surface?.featureFlag || flagSet.has(surface.featureFlag),
    [surface, flagSet]
  );

  const stateBadges = React.useMemo(
    () =>
      resolveAuthoringStateBadges({
        online,
        loading,
        conflict,
        unsavedChanges,
        saving,
        readOnly,
        entitled,
      }),
    [online, loading, conflict, unsavedChanges, saving, readOnly, entitled]
  );

  const value = React.useMemo<AuthoringContextValue>(
    () => ({
      scope: { ...urlScope, tenantId },
      environment,
      surface,
      projects,
      versions,
      selectedVersion,
      entitledFlags: flagSet,
      setProjectId,
      setVersionId,
      setEnvironmentId,
      loading,
      readOnly,
      online,
      setUnsavedChanges,
      setSaving,
      setConflict,
      stateBadges,
      resume,
    }),
    [
      urlScope,
      tenantId,
      environment,
      surface,
      projects,
      versions,
      selectedVersion,
      flagSet,
      setProjectId,
      setVersionId,
      setEnvironmentId,
      loading,
      readOnly,
      online,
      stateBadges,
      resume,
    ]
  );

  return <AuthoringContext.Provider value={value}>{children}</AuthoringContext.Provider>;
}

/**
 * Read the Authoring context.
 *
 * @returns The current context value.
 * @throws When called outside {@link AuthoringProvider}.
 */
export function useAuthoring(): AuthoringContextValue {
  const context = React.useContext(AuthoringContext);
  if (context === undefined) {
    throw new Error('useAuthoring must be used within AuthoringProvider');
  }
  return context;
}
