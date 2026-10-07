/**
 * The `/design-system` route (HIVE-10.5, #5341), rendered.
 *
 * `tests/design-system-gallery.test.ts` checks the source: every primitive has a specimen.
 * This suite checks the page those specimens make:
 *
 *   - one `h1`, then an `h2` per gallery, with the absorbed MCP gallery's sections nested at
 *     `h3` beneath its own heading;
 *   - every link in the contents list lands on an element on the page;
 *   - the theme / density / font-scale switchers write the attributes the app reads, so every
 *     specimen can be checked in all nine themes, both densities and all six font scales;
 *   - the supporting specimens behave (the live region speaks, the legacy modal opens and
 *     closes, every toast tone is raised through the app toast);
 *   - `/design-system/mcp` still renders the MCP gallery on its own, and the old
 *     `/design-system/hive` address redirects to the route.
 */

import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

const mockRedirect = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/design-system',
  useSearchParams: () => new URLSearchParams(),
  redirect: (url: string) => mockRedirect(url),
}));

const mockToast = {
  success: jest.fn(),
  error: jest.fn(),
  warning: jest.fn(),
  info: jest.fn(),
};
jest.mock('../src/app/components/ui/toast', () => ({ toast: mockToast }));

// The capability graph lazy-loads Mermaid in an effect; the gallery only needs it not to throw.
jest.mock('mermaid', () => ({
  __esModule: true,
  default: { initialize: jest.fn(), render: jest.fn().mockResolvedValue({ svg: '<svg></svg>' }) },
}));

import DesignSystemPage from '../src/app/design-system/page';
import McpPrimitivesPage from '../src/app/design-system/mcp/page';
import HiveDesignSystemRedirect from '../src/app/design-system/hive/page';
import { DialogProvider } from '../src/app/components/providers/DialogProvider';
import { PREFERENCE_AXES } from '../src/app/design-system/PreferenceAxes';
import { SYSTEM_THEME_ID, themes } from '../src/app/config/themes';
import {
  HIVE_GALLERY_SECTIONS,
  MCP_GALLERY_SECTION,
  SUPPORTING_GALLERY_SECTIONS,
} from '../src/app/design-system/galleries/sections';

/** Render the root route the way the app does: inside the dialog provider the layout mounts. */
function renderRoute() {
  return render(
    <DialogProvider>
      <DesignSystemPage />
    </DialogProvider>
  );
}

beforeAll(() => {
  // jsdom has no layout; Radix and the tables only need these to exist.
  window.HTMLElement.prototype.scrollIntoView = jest.fn();
  window.HTMLElement.prototype.hasPointerCapture = jest.fn();
  window.HTMLElement.prototype.releasePointerCapture = jest.fn();
  if (!window.ResizeObserver) {
    window.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  }
});

afterEach(() => {
  for (const axis of PREFERENCE_AXES) document.documentElement.removeAttribute(axis.attribute);
  document.documentElement.classList.remove('dark');
  jest.clearAllMocks();
});

describe('/design-system', () => {
  it('has one title and one heading per gallery', () => {
    renderRoute();
    expect(screen.getAllByRole('heading', { level: 1 }).map((h) => h.textContent)).toEqual([
      'Design system',
    ]);
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      'Hive primitives',
      'Supporting primitives',
      'MCP primitives',
      'Patterns',
    ]);
  });

  it('nests the absorbed MCP gallery one level down', () => {
    renderRoute();
    const mcp = document.getElementById(MCP_GALLERY_SECTION.id);
    expect(mcp).not.toBeNull();
    const nested = within(mcp!).getAllByRole('heading', { level: 3 });
    expect(nested.map((h) => h.textContent)).toContain('HealthPill');
    expect(within(mcp!).queryAllByRole('heading', { level: 2 })).toHaveLength(1);
  });

  it('gives no two elements the same id, now that three galleries share one page', () => {
    renderRoute();
    const ids = [...document.querySelectorAll('[id]')].map((element) => element.id);
    const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
    expect(duplicates).toEqual([]);
  });

  it('lands every contents link on an element of the page', () => {
    renderRoute();
    const contents = screen.getByRole('navigation', { name: 'Design system contents' });
    const hrefs = within(contents)
      .getAllByRole('link')
      .map((link) => link.getAttribute('href'));
    expect(hrefs).toHaveLength(HIVE_GALLERY_SECTIONS.length + SUPPORTING_GALLERY_SECTIONS.length + 2);
    for (const href of hrefs) {
      expect(href).toMatch(/^#/);
      expect(document.getElementById(href!.slice(1))).not.toBeNull();
    }
  });

  it('links each pattern gallery and the standalone MCP page', () => {
    renderRoute();
    for (const href of [
      '/design-system/page-header',
      '/design-system/command-palette',
      '/design-system/shortcuts',
      '/design-system/mcp',
    ]) {
      expect(document.querySelector(`a[href="${href}"]`)).not.toBeNull();
    }
  });

  it('switches theme, density and font scale on <html>, as the preferences pane does', async () => {
    renderRoute();
    const axes = screen.getAllByTestId('preference-axes')[0];
    const user = userEvent.setup();

    await user.selectOptions(within(axes).getByLabelText('Theme'), 'dark');
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(document.documentElement).toHaveClass('dark');

    await user.selectOptions(within(axes).getByLabelText('Theme'), 'light');
    expect(document.documentElement).not.toHaveClass('dark');

    await user.selectOptions(within(axes).getByLabelText('Density'), 'compact');
    expect(document.documentElement).toHaveAttribute('data-density', 'compact');

    const scale = within(axes).getByLabelText('Font scale') as HTMLSelectElement;
    const last = scale.options[scale.options.length - 1].value;
    await user.selectOptions(scale, last);
    expect(document.documentElement).toHaveAttribute('data-font-scale', last);
  });

  it('offers every theme, both densities and all six font scales', () => {
    const [theme, density, fontScale] = PREFERENCE_AXES;
    // Nine themes counting System, which resolves to Light or Dark rather than being a palette
    // of its own — so the switcher offers the other eight, every palette there is.
    expect(themes).toHaveLength(9);
    expect(theme.options.map((option) => option.value)).toEqual(
      themes.filter((entry) => entry.id !== SYSTEM_THEME_ID).map((entry) => entry.id)
    );
    expect(density.options).toHaveLength(2);
    expect(fontScale.options).toHaveLength(6);
  });
});

describe('the supporting specimens', () => {
  it('announces through the live region and echoes what it said', async () => {
    renderRoute();
    const user = userEvent.setup();
    const region = screen.getByTestId('live-region-specimen');
    expect(screen.getByTestId('live-region-echo')).toHaveTextContent('Silent');

    await user.click(screen.getByRole('button', { name: 'Announce next status' }));
    expect(region).toHaveTextContent('Saving…');
    expect(screen.getByTestId('live-region-echo')).toHaveTextContent('Saving…');

    await user.click(screen.getByRole('button', { name: 'Announce next status' }));
    expect(region).toHaveTextContent('Saved');
  });

  it('opens the legacy modal, names it, and closes it', async () => {
    renderRoute();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Open legacy modal' }));
    const dialog = await screen.findByRole('dialog', { name: 'Legacy modal' });
    await user.click(within(dialog).getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog', { name: 'Legacy modal' })).not.toBeInTheDocument();
  });

  it('raises every toast tone through the app toast', async () => {
    renderRoute();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Success toast' }));
    await user.click(screen.getByRole('button', { name: 'Error toast' }));
    await user.click(screen.getByRole('button', { name: 'Warning toast' }));
    await user.click(screen.getByRole('button', { name: 'Info toast' }));
    expect(mockToast.success).toHaveBeenCalledTimes(1);
    expect(mockToast.error).toHaveBeenCalledTimes(1);
    expect(mockToast.warning).toHaveBeenCalledTimes(1);
    expect(mockToast.info).toHaveBeenCalledTimes(1);
  });

  it('draws the stepper in progress, filled and complete', () => {
    renderRoute();
    expect(screen.getByRole('list', { name: 'Setup progress' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Setup progress, filled' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Setup complete' })).toBeInTheDocument();
  });
});

describe('/design-system/mcp', () => {
  it('still renders the MCP gallery on its own page, its sections at h2', () => {
    render(<McpPrimitivesPage />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('MCP UI primitives');
    const sections = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(sections).toContain('HealthPill');
    expect(sections).toContain('CapabilityGraphPanel');
    expect(document.querySelector('a[href="/design-system"]')).not.toBeNull();
    expect(screen.getByTestId('preference-axes')).toBeInTheDocument();
  });
});

describe('/design-system/hive', () => {
  it('redirects to the route that absorbed it', () => {
    HiveDesignSystemRedirect();
    expect(mockRedirect).toHaveBeenCalledWith('/design-system');
  });
});
