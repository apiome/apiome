/**
 * Authoring shell integration (UXE-1.2).
 *
 * Exercises the acceptance criteria end to end in a DOM: a copied URL restores
 * scope, a scope change updates the URL and every child link, the palette is
 * keyboard reachable, `/` focuses contextual search, and state badges reflect
 * read-only scope.
 */

import * as React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// ---------------------------------------------------------------------------
// Next.js and NextAuth stand-ins
// ---------------------------------------------------------------------------

const pushMock = jest.fn();

jest.mock('next/link', () => {
  const Link = React.forwardRef<
    HTMLAnchorElement,
    { href: string; children: React.ReactNode } & React.AnchorHTMLAttributes<HTMLAnchorElement>
  >(function MockLink({ href, children, ...rest }, ref) {
    return (
      <a href={href} ref={ref} {...rest}>
        {children}
      </a>
    );
  });
  return { __esModule: true, default: Link };
});

let mockPathname = '/ade/authoring';

/*
 * `useSearchParams` is mocked to return a plain snapshot of the current URL and
 * nothing more: it never subscribes to anything, so it cannot itself trigger a
 * re-render when the provider writes scope with the History API. Next's App
 * Router gives no guarantee it would, so the provider must not depend on it —
 * it reads `window.location` and re-renders off its own scope-changed event.
 */
jest.mock('next/navigation', () => ({
  __esModule: true,
  usePathname: () => mockPathname,
  useRouter: () => ({ push: pushMock, replace: jest.fn(), refresh: jest.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

jest.mock('next-auth/react', () => ({
  __esModule: true,
  useSession: () => ({
    data: { user: { user_id: 'user-1', current_tenant_id: 'tenant-1' } },
    status: 'authenticated',
  }),
}));

import { AuthoringProvider } from '../src/app/ade/authoring/AuthoringContext';
import AuthoringShell from '../src/app/ade/authoring/components/AuthoringShell';
import AuthoringOverview from '../src/app/ade/authoring/components/AuthoringOverview';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const PROJECTS = [
  { id: 'proj-1', name: 'Payments API' },
  { id: 'proj-2', name: 'Billing API' },
];

const VERSIONS = [
  { id: 'ver-1', version_id: '1.0.0', description: 'Draft cut', published: false },
  { id: 'ver-2', version_id: '2.0.0', description: null, published: true },
];

const ALL_FLAGS = ['designer', 'paths', 'scribe', 'slate', 'hosted'];

/**
 * Install a `fetch` stub for the scope endpoints.
 *
 * @param overrides - Replace the projects payload, or make either call fail.
 */
function mockScopeFetch(
  overrides: {
    projects?: typeof PROJECTS;
    projectsFail?: boolean;
    versionsFail?: boolean;
  } = {}
) {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    let body: unknown = { success: false };

    if (url.startsWith('/api/projects')) {
      body = overrides.projectsFail
        ? { success: false, error: 'boom' }
        : { success: true, projects: overrides.projects ?? PROJECTS };
    } else if (url.startsWith('/api/versions')) {
      body = overrides.versionsFail
        ? { success: false, error: 'boom' }
        : { success: true, versions: VERSIONS };
    }

    return { ok: true, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

/**
 * Point the jsdom URL at an Authoring route.
 *
 * @param search - Query string, including the leading `?` when non-empty.
 * @param pathname - Route to report from `usePathname`.
 */
function setUrl(search: string, pathname = '/ade/authoring') {
  mockPathname = pathname;
  window.history.replaceState({}, '', `${pathname}${search}`);
}

/**
 * Render the shell around the Overview surface.
 *
 * @param flags - License flags granted to the session.
 */
function renderShell(flags: string[] = ALL_FLAGS) {
  return render(
    <AuthoringProvider entitledFlags={flags}>
      <AuthoringShell>
        <AuthoringOverview />
      </AuthoringShell>
    </AuthoringProvider>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.clear();
  mockScopeFetch();
  setUrl('');
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('scope restoration from a copied URL', () => {
  it('restores project, version and environment from the query string', async () => {
    setUrl('?projectId=proj-1&versionId=ver-1&env=production');
    renderShell();

    await waitFor(() => {
      expect(screen.getByLabelText('Project')).toHaveTextContent('Payments API');
    });
    expect(screen.getByLabelText('Version')).toHaveTextContent('1.0.0');
    expect(screen.getByLabelText('Environment')).toHaveTextContent('Production');
  });

  it('drops a project the session cannot see, rather than showing it', async () => {
    setUrl('?projectId=proj-forbidden&versionId=ver-1');
    renderShell();

    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get('projectId')).toBeNull();
    });
    expect(new URLSearchParams(window.location.search).get('versionId')).toBeNull();
  });

  it('drops a scope when the viewer has no projects at all', async () => {
    // An empty list is an authoritative "you may see nothing", so the scope
    // must be scrubbed rather than treated as still-loading.
    mockScopeFetch({ projects: [] });
    setUrl('?projectId=secret-proj&versionId=secret-ver');
    renderShell();

    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get('projectId')).toBeNull();
    });
    expect(screen.queryByText('secret-proj')).not.toBeInTheDocument();
  });

  it('keeps the scope when the projects request fails, which proves nothing', async () => {
    mockScopeFetch({ projectsFail: true });
    setUrl('?projectId=proj-1&versionId=ver-1');
    renderShell();

    const status = await screen.findByRole('status', { name: 'Authoring status' });
    await waitFor(() => expect(within(status).queryByText('Loading')).not.toBeInTheDocument());
    // A transient failure must not destroy the viewer's selection.
    expect(new URLSearchParams(window.location.search).get('projectId')).toBe('proj-1');
  });

  it('stops reporting Loading when an in-flight versions request is abandoned', async () => {
    // The projects list resolves without proj-forbidden, which clears the
    // project and aborts the versions request that was already in flight.
    setUrl('?projectId=proj-forbidden&versionId=ver-1');
    renderShell();

    const status = await screen.findByRole('status', { name: 'Authoring status' });
    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get('projectId')).toBeNull();
    });
    await waitFor(() => expect(within(status).queryByText('Loading')).not.toBeInTheDocument());
  });

  it('drops a version that does not belong to the selected project', async () => {
    setUrl('?projectId=proj-1&versionId=ver-other');
    renderShell();

    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get('versionId')).toBeNull();
    });
    expect(new URLSearchParams(window.location.search).get('projectId')).toBe('proj-1');
  });
});

describe('scope changes', () => {
  it('writes the new project to the URL and clears the stale version', async () => {
    const user = userEvent.setup();
    setUrl('?projectId=proj-1&versionId=ver-1');
    renderShell();

    await waitFor(() => {
      expect(screen.getByLabelText('Project')).toHaveTextContent('Payments API');
    });

    await user.click(screen.getByLabelText('Project'));
    await user.click(await screen.findByRole('option', { name: /Billing API/ }));

    await waitFor(() => {
      const params = new URLSearchParams(window.location.search);
      expect(params.get('projectId')).toBe('proj-2');
      // Carrying the old version across projects is exactly the stale
      // cross-project data the shell must not render.
      expect(params.get('versionId')).toBeNull();
    });
  });

  it('propagates scope to every secondary navigation link', async () => {
    setUrl('?projectId=proj-1&versionId=ver-1&env=production');
    renderShell();

    const nav = await screen.findByRole('navigation', { name: 'Authoring sections' });
    await waitFor(() => {
      expect(within(nav).getByRole('link', { name: /Scribe/ })).toHaveAttribute(
        'href',
        '/ade/authoring/scribe?projectId=proj-1&versionId=ver-1&env=production'
      );
    });
  });

  it('re-reads scope when the browser navigates back', async () => {
    setUrl('?projectId=proj-1&versionId=ver-1');
    renderShell();

    await waitFor(() => {
      expect(screen.getByLabelText('Project')).toHaveTextContent('Payments API');
    });

    // A real Back: the URL changes underneath, then popstate fires.
    window.history.replaceState({}, '', '/ade/authoring?projectId=proj-2');
    window.dispatchEvent(new PopStateEvent('popstate'));

    await waitFor(() => {
      expect(screen.getByLabelText('Project')).toHaveTextContent('Billing API');
    });
  });

  it('keeps a scope change out of the back stack', async () => {
    const user = userEvent.setup();
    const pushState = jest.spyOn(window.history, 'pushState');
    setUrl('?projectId=proj-1');
    renderShell();

    await waitFor(() => {
      expect(screen.getByLabelText('Project')).toHaveTextContent('Payments API');
    });
    await user.click(screen.getByLabelText('Project'));
    await user.click(await screen.findByRole('option', { name: /Billing API/ }));

    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get('projectId')).toBe('proj-2');
    });
    expect(pushState).not.toHaveBeenCalled();
    pushState.mockRestore();
  });
});

describe('state badges', () => {
  it('reports Saved for an editable draft version', async () => {
    setUrl('?projectId=proj-1&versionId=ver-1');
    renderShell();

    const status = await screen.findByRole('status', { name: 'Authoring status' });
    await waitFor(() => expect(within(status).getByText('Saved')).toBeInTheDocument());
  });

  it('reports Read only for a published version', async () => {
    setUrl('?projectId=proj-1&versionId=ver-2');
    renderShell();

    const status = await screen.findByRole('status', { name: 'Authoring status' });
    await waitFor(() => expect(within(status).getByText('Read only')).toBeInTheDocument());
  });

  it('reports Read only on the production lane', async () => {
    setUrl('?projectId=proj-1&versionId=ver-1&env=production');
    renderShell();

    const status = await screen.findByRole('status', { name: 'Authoring status' });
    await waitFor(() => expect(within(status).getByText('Read only')).toBeInTheDocument());
  });

  it('pairs every badge with an explanation for assistive technology', async () => {
    setUrl('?projectId=proj-1&versionId=ver-2');
    renderShell();

    const status = await screen.findByRole('status', { name: 'Authoring status' });
    await waitFor(() => expect(within(status).getByText('Read only')).toBeInTheDocument());
    expect(within(status).getByText(/This scope cannot be edited/)).toBeInTheDocument();
  });
});

describe('command palette', () => {
  it('opens with Ctrl+K and closes with Escape', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.keyboard('{Control>}k{/Control}');
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Authoring command palette')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('opens from the header trigger', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole('button', { name: /Search or jump to/ }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('filters commands as the viewer types', async () => {
    const user = userEvent.setup();
    setUrl('?projectId=proj-1&versionId=ver-1');
    renderShell();

    await user.keyboard('{Control>}k{/Control}');
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('combobox'), 'billing');

    await waitFor(() => {
      expect(within(dialog).getByText('Billing API')).toBeInTheDocument();
    });
    expect(within(dialog).queryByText('Insights')).not.toBeInTheDocument();
  });

  it('navigates with the current scope when a destination is chosen', async () => {
    const user = userEvent.setup();
    setUrl('?projectId=proj-1&versionId=ver-1');
    renderShell();

    await waitFor(() => {
      expect(screen.getByLabelText('Version')).toHaveTextContent('1.0.0');
    });

    await user.keyboard('{Control>}k{/Control}');
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('combobox'), 'slate');
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith(
        '/ade/authoring/slate?projectId=proj-1&versionId=ver-1'
      );
    });
  });

  it('explains an unentitled destination instead of hiding it', async () => {
    const user = userEvent.setup();
    renderShell(['designer']);

    await user.keyboard('{Control>}k{/Control}');
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('combobox'), 'scribe');

    expect(await within(dialog).findByText(/plan does not include/i)).toBeInTheDocument();
  });

  it('marks an unentitled destination disabled so it cannot be activated', async () => {
    const user = userEvent.setup();
    renderShell(['designer']);

    await user.keyboard('{Control>}k{/Control}');
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('combobox'), 'scribe');

    const item = await within(dialog).findByRole('option', { name: /Scribe/ });
    expect(item).toHaveAttribute('aria-disabled', 'true');

    await user.keyboard('{Enter}');
    expect(pushMock).not.toHaveBeenCalled();
  });

  it('offers a way to switch the slash shortcut off (WCAG 2.1.4)', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.keyboard('{Control>}k{/Control}');
    const dialog = await screen.findByRole('dialog');
    const toggle = within(dialog).getByRole('button', { name: /Slash search/ });
    expect(toggle).toHaveAttribute('aria-pressed', 'true');

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-pressed', 'false');

    // With the shortcut off, `/` must no longer steal focus.
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    const search = screen.getByLabelText('Search Authoring destinations');
    await user.keyboard('/');
    expect(search).not.toHaveFocus();
  });
});

describe('contextual search', () => {
  it('focuses the surface search field when / is pressed', async () => {
    const user = userEvent.setup();
    renderShell();

    const search = screen.getByLabelText('Search Authoring destinations');
    expect(search).not.toHaveFocus();

    await user.keyboard('/');
    await waitFor(() => expect(search).toHaveFocus());
  });

  it('does not select the existing query, so an accidental / cannot destroy it', async () => {
    const user = userEvent.setup();
    renderShell();

    const search = screen.getByLabelText('Search Authoring destinations');
    await user.click(search);
    await user.keyboard('slate');
    search.blur();

    await user.keyboard('/');
    await waitFor(() => expect(search).toHaveFocus());

    // If the text had been selected, typing would replace it.
    await user.keyboard('x');
    expect(search).toHaveValue('slatex');
  });

  it('lets / be typed normally once the field has focus', async () => {
    const user = userEvent.setup();
    renderShell();

    const search = screen.getByLabelText('Search Authoring destinations');
    await user.click(search);
    await user.keyboard('a/b');

    expect(search).toHaveValue('a/b');
  });
});

describe('secondary navigation', () => {
  it('marks the current surface as the active page', async () => {
    setUrl('', '/ade/authoring/releases');
    renderShell();

    const nav = await screen.findByRole('navigation', { name: 'Authoring sections' });
    expect(within(nav).getByRole('link', { name: /Releases/ })).toHaveAttribute(
      'aria-current',
      'page'
    );
    expect(within(nav).getByRole('link', { name: /Overview/ })).not.toHaveAttribute('aria-current');
  });

  it('renders an unentitled destination as disabled, unlinked and explained', async () => {
    renderShell(['designer']);

    const nav = await screen.findByRole('navigation', { name: 'Authoring sections' });
    const scribe = within(nav).getByRole('link', { name: /Scribe/ });

    expect(scribe).toHaveAttribute('aria-disabled', 'true');
    expect(scribe).not.toHaveAttribute('href');
    // Reachable by keyboard, and the reason is an accessible description
    // rather than a pointer-only tooltip.
    expect(scribe).toHaveAttribute('tabIndex', '0');
    expect(scribe).toHaveAccessibleDescription(/not included in your plan/i);
  });
});

describe('scope selectors', () => {
  it('keeps an empty selector focusable and explains why it is empty', async () => {
    // A natively disabled control leaves the tab order, so a keyboard user
    // would never reach it or learn why it cannot be used.
    renderShell();

    const version = await screen.findByLabelText('Version');
    expect(version).not.toBeDisabled();
    expect(version).toHaveAccessibleDescription('Select a project first');
  });

  it('explains an empty project list', async () => {
    mockScopeFetch({ projects: [] });
    renderShell();

    const project = await screen.findByLabelText('Project');
    await waitFor(() => {
      expect(project).toHaveAccessibleDescription('No projects available');
    });
  });
});

describe('resume', () => {
  it('offers to resume the last session when the URL carries no scope', async () => {
    window.localStorage.setItem(
      'authoring.resume.tenant-1',
      JSON.stringify({
        surfaceId: 'slate',
        projectId: 'proj-1',
        versionId: 'ver-1',
        environmentId: 'preview',
        updatedAt: 1,
      })
    );
    renderShell();

    const resume = await screen.findByRole('link', { name: 'Continue authoring' });
    expect(resume).toHaveAttribute(
      'href',
      '/ade/authoring/slate?projectId=proj-1&versionId=ver-1'
    );
  });

  it('does not offer resume when the URL already carries scope, so a copied link wins', async () => {
    window.localStorage.setItem(
      'authoring.resume.tenant-1',
      JSON.stringify({
        surfaceId: 'slate',
        projectId: 'proj-1',
        versionId: 'ver-1',
        environmentId: 'preview',
        updatedAt: 1,
      })
    );
    setUrl('?projectId=proj-2');
    renderShell();

    await waitFor(() => {
      expect(screen.getByLabelText('Project')).toHaveTextContent('Billing API');
    });
    expect(screen.queryByRole('link', { name: 'Continue authoring' })).not.toBeInTheDocument();
  });

  it('never offers a remembered project the viewer can no longer see', async () => {
    window.localStorage.setItem(
      'authoring.resume.tenant-1',
      JSON.stringify({
        surfaceId: 'slate',
        projectId: 'ghost-proj',
        versionId: 'ghost-ver',
        environmentId: 'preview',
        updatedAt: 1,
      })
    );
    renderShell();

    await waitFor(() => {
      expect(screen.getByText('Go to')).toBeInTheDocument();
    });
    expect(screen.queryByRole('link', { name: 'Continue authoring' })).not.toBeInTheDocument();
    // The raw id of an inaccessible project must never be printed.
    expect(screen.queryByText(/ghost-proj/)).not.toBeInTheDocument();
    // ...and the stale entry is forgotten rather than re-offered every visit.
    await waitFor(() => {
      expect(window.localStorage.getItem('authoring.resume.tenant-1')).toBeNull();
    });
  });

  it('does not remember a scope that is about to be scrubbed', async () => {
    setUrl('?projectId=proj-forbidden&versionId=ver-1');
    renderShell();

    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get('projectId')).toBeNull();
    });
    expect(window.localStorage.getItem('authoring.resume.tenant-1')).toBeNull();
  });

  it('remembers a complete scope for the next visit', async () => {
    setUrl('?projectId=proj-1&versionId=ver-1');
    renderShell();

    await waitFor(() => {
      const raw = window.localStorage.getItem('authoring.resume.tenant-1');
      expect(raw).not.toBeNull();
      expect(JSON.parse(raw!)).toMatchObject({
        surfaceId: 'overview',
        projectId: 'proj-1',
        versionId: 'ver-1',
      });
    });
  });
});
