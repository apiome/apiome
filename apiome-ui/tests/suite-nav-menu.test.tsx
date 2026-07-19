/**
 * UXE-1.1 — grouped Designer suite navigation.
 *
 * Covers the navigation contract as rendered: group headings, entitlement and
 * release badges, unentitled destinations that explain access without exposing
 * a URL, and the full ARIA menu keyboard pattern.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SuiteNavMenu from '../src/app/components/ade/SuiteNavMenu';
import { getCommercialNavItems, type ExternalNavItem } from '../lib/external-links';

jest.mock('next/link', () => ({
  __esModule: true,
  default: React.forwardRef<HTMLAnchorElement, React.ComponentProps<'a'>>(function MockLink(
    { children, ...props },
    ref
  ) {
    return (
      <a ref={ref} {...props}>
        {children}
      </a>
    );
  }),
}));

/** The suite nav item as an entitled user sees it, on the main app surface. */
function suiteNavItem(flags: string[] = ['designer', 'paths']): ExternalNavItem {
  const item = getCommercialNavItems(new Set(flags)).find((navItem) => navItem.id === 'suite');
  if (!item) throw new Error('suite nav item missing from the commercial registry');
  return item;
}

type RenderOptions = {
  flags?: string[];
  pathname?: string | null;
};

/** Render the menu already open, with a controlled `open` prop the test drives. */
function renderMenu({ flags, pathname = '/ade' }: RenderOptions = {}) {
  const onOpenChange = jest.fn();
  const view = render(
    <SuiteNavMenu
      item={suiteNavItem(flags)}
      isActive={false}
      pathname={pathname}
      open
      onOpenChange={onOpenChange}
    />
  );
  return { ...view, onOpenChange };
}

describe('SuiteNavMenu', () => {
  const originalSurface = process.env.NEXT_PUBLIC_APP_SURFACE;

  beforeEach(() => {
    // Studio surface: Design destinations are in-app paths and Authoring
    // destinations are absolute main-app URLs, so both link kinds are covered.
    process.env.NEXT_PUBLIC_APP_SURFACE = 'studio';
  });

  afterEach(() => {
    process.env.NEXT_PUBLIC_APP_SURFACE = originalSurface;
    jest.clearAllMocks();
  });

  describe('structure', () => {
    it('renders Design and Authoring groups with announced, non-focusable headings', () => {
      renderMenu();

      const groups = screen.getAllByRole('group');
      expect(groups).toHaveLength(2);
      expect(groups[0]).toHaveAccessibleName('Design');
      expect(groups[1]).toHaveAccessibleName('Authoring');

      // Headings label their group but are never menu actions themselves.
      expect(screen.queryByRole('menuitem', { name: /^Design$/ })).toBeNull();
      expect(screen.queryByRole('menuitem', { name: /^Authoring$/ })).toBeNull();

      expect(within(groups[0]).getAllByRole('menuitem')).toHaveLength(3);
      expect(within(groups[1]).getAllByRole('menuitem')).toHaveLength(5);
    });

    it('labels the menu after its trigger and links the trigger to it', async () => {
      const user = userEvent.setup();
      const onOpenChange = jest.fn();
      const { rerender } = render(
        <SuiteNavMenu
          item={suiteNavItem()}
          isActive={false}
          pathname="/ade"
          open={false}
          onOpenChange={onOpenChange}
        />
      );

      const trigger = screen.getByRole('button', { name: /Designer/ });
      expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
      expect(trigger).toHaveAttribute('aria-expanded', 'false');

      await user.click(trigger);
      expect(onOpenChange).toHaveBeenCalledWith(true);

      rerender(
        <SuiteNavMenu
          item={suiteNavItem()}
          isActive={false}
          pathname="/ade"
          open
          onOpenChange={onOpenChange}
        />
      );
      const menu = screen.getByRole('menu', { name: 'Designer menu' });
      expect(screen.getByRole('button', { name: /Designer/ })).toHaveAttribute(
        'aria-controls',
        menu.id
      );
    });

    it('marks the destination matching the current route as the current page', () => {
      renderMenu({ pathname: '/paths' });

      const paths = screen.getByRole('menuitem', { name: /Paths Editor/ });
      expect(paths).toHaveAttribute('aria-current', 'page');
      expect(screen.getByRole('menuitem', { name: /Suite Home/ })).not.toHaveAttribute(
        'aria-current'
      );
    });
  });

  describe('entitlements', () => {
    it('explains access for an unentitled destination without exposing its href', () => {
      renderMenu({ flags: ['designer'] });

      const paths = screen.getByRole('menuitem', { name: /Paths Editor/ });
      expect(paths).toHaveAttribute('aria-disabled', 'true');
      expect(paths.tagName).not.toBe('A');
      expect(paths).not.toHaveAttribute('href');
      expect(paths).toHaveTextContent('Ask a tenant admin to enable it.');
    });

    it('keeps entitled destinations navigable', () => {
      renderMenu({ flags: ['designer'] });

      const designer = screen.getByRole('menuitem', { name: /Designer\b/ });
      expect(designer).toHaveAttribute('href', '/editor');
      expect(designer).not.toHaveAttribute('aria-disabled');
    });

    it('badges unreleased authoring destinations and states how access is obtained', () => {
      renderMenu({ flags: ['designer', 'paths', 'scribe'] });

      const scribe = screen.getByRole('menuitem', { name: /Scribe/ });
      expect(scribe).toHaveTextContent('Preview');
      expect(scribe).toHaveAttribute('aria-disabled', 'true');

      const releases = screen.getByRole('menuitem', { name: /Releases/ });
      expect(releases).toHaveTextContent('Coming soon');
      expect(releases).toHaveTextContent('Contact your account team to upgrade.');
      expect(releases).not.toHaveAttribute('href');
    });
  });

  describe('ARIA menu keyboard pattern', () => {
    /** Render-order destination labels, i.e. the expected roving-focus order. */
    const ORDER = [
      'Suite Home',
      'Designer',
      'Paths Editor',
      'Authoring Overview',
      'Scribe',
      'Slate',
      'Releases',
      'Insights',
    ];

    function focusedLabel(): string {
      return document.activeElement?.textContent?.trim() ?? '';
    }

    it('focuses the first destination when the menu opens', () => {
      renderMenu();
      expect(focusedLabel()).toContain(ORDER[0]);
    });

    it('moves focus with the arrow keys and wraps at both ends', async () => {
      const user = userEvent.setup();
      renderMenu();

      await user.keyboard('{ArrowDown}');
      expect(focusedLabel()).toContain('Designer');

      // Up from the first destination wraps to the last.
      await user.keyboard('{ArrowUp}{ArrowUp}');
      expect(focusedLabel()).toContain('Insights');

      // Down from the last wraps back to the first.
      await user.keyboard('{ArrowDown}');
      expect(focusedLabel()).toContain('Suite Home');
    });

    it('jumps to the first and last destination with Home and End', async () => {
      const user = userEvent.setup();
      renderMenu();

      await user.keyboard('{End}');
      expect(focusedLabel()).toContain('Insights');

      await user.keyboard('{Home}');
      expect(focusedLabel()).toContain('Suite Home');
    });

    it('crosses group boundaries, so headings never trap focus', async () => {
      const user = userEvent.setup();
      renderMenu();

      // Third destination is the last in Design; one more enters Authoring.
      await user.keyboard('{ArrowDown}{ArrowDown}');
      expect(focusedLabel()).toContain('Paths Editor');
      await user.keyboard('{ArrowDown}');
      expect(focusedLabel()).toContain('Authoring Overview');
    });

    it('closes on Escape and returns focus to the trigger', async () => {
      const user = userEvent.setup();
      const { onOpenChange, rerender } = renderMenu();

      await user.keyboard('{Escape}');
      expect(onOpenChange).toHaveBeenCalledWith(false);

      rerender(
        <SuiteNavMenu
          item={suiteNavItem()}
          isActive={false}
          pathname="/ade"
          open={false}
          onOpenChange={onOpenChange}
        />
      );
      expect(document.activeElement).toBe(screen.getByRole('button', { name: /Designer/ }));
    });

    it('closes on Tab without returning focus, so focus leaves the menu', async () => {
      const user = userEvent.setup();
      const { onOpenChange } = renderMenu();

      await user.keyboard('{Tab}');
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });

    it('opens from the trigger with ArrowDown', async () => {
      const user = userEvent.setup();
      const onOpenChange = jest.fn();
      render(
        <SuiteNavMenu
          item={suiteNavItem()}
          isActive={false}
          pathname="/ade"
          open={false}
          onOpenChange={onOpenChange}
        />
      );

      screen.getByRole('button', { name: /Designer/ }).focus();
      await user.keyboard('{ArrowDown}');
      expect(onOpenChange).toHaveBeenCalledWith(true);
    });

    it('typeahead jumps forward to the next label starting with the key pressed', async () => {
      const user = userEvent.setup();
      renderMenu();

      await user.keyboard('r');
      expect(focusedLabel()).toContain('Releases');
    });

    it('typeahead buffers consecutive keys to disambiguate shared first letters', async () => {
      const user = userEvent.setup();
      renderMenu();

      // 's' alone reaches Scribe; the buffered 'sl' continues on to Slate.
      await user.keyboard('s');
      expect(focusedLabel()).toContain('Scribe');
      await user.keyboard('l');
      expect(focusedLabel()).toContain('Slate');
    });

    it('typeahead buffer resets after a pause, so the next key starts a new search', async () => {
      const user = userEvent.setup();
      const now = jest.spyOn(Date, 'now');
      try {
        now.mockReturnValue(1_000);
        renderMenu();

        await user.keyboard('r');
        expect(focusedLabel()).toContain('Releases');

        // Past the reset window: 's' searches afresh instead of extending 'r'.
        now.mockReturnValue(2_000);
        await user.keyboard('s');
        expect(focusedLabel()).toContain('Suite Home');
      } finally {
        now.mockRestore();
      }
    });

    it('leaves a leading space to the focused item instead of consuming it', async () => {
      const user = userEvent.setup();
      renderMenu();

      await user.keyboard('[Space]');
      // Focus must not have jumped to some label starting with a space.
      expect(focusedLabel()).toContain('Suite Home');
    });

    it('typeahead reaches unentitled destinations, which stay focusable', async () => {
      const user = userEvent.setup();
      renderMenu({ flags: ['designer'] });

      await user.keyboard('pa');
      expect(document.activeElement).toBe(
        screen.getByRole('menuitem', { name: /Paths Editor/ })
      );
    });
  });
});
