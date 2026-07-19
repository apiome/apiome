'use client';

/**
 * The Authoring shell (UXE-1.2).
 *
 * Composes the persistent scope header, the secondary navigation and the
 * command palette around whichever surface is routed, and owns the two global
 * keyboard bindings so no surface has to install them itself.
 */

import * as React from 'react';
import {
  matchesAuthoringPaletteShortcut,
  matchesAuthoringSearchShortcut,
} from '@lib/authoring/keybindings';
import { isSlashSearchEnabled } from '@lib/authoring/shortcut-preferences';
import { authoringMainClass, authoringShellClass } from '../authoringClasses';
import AuthoringHeader from './AuthoringHeader';
import AuthoringSecondaryNav from './AuthoringSecondaryNav';
import AuthoringCommandPalette from './AuthoringCommandPalette';
import { focusAuthoringContextSearch } from './AuthoringContextSearch';

/** Props for {@link AuthoringShell}. */
export type AuthoringShellProps = {
  children: React.ReactNode;
};

/**
 * Render the shell chrome around a surface.
 *
 * @param props - The routed surface.
 */
export default function AuthoringShell({ children }: AuthoringShellProps) {
  const [paletteOpen, setPaletteOpen] = React.useState(false);

  /*
   * The palette shortcut is a modifier chord, so it is safe to listen for
   * document-wide and still reach the viewer wherever focus is. Capture phase
   * so it works even when focus sits in a widget that stops propagation.
   */
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!matchesAuthoringPaletteShortcut(event)) return;
      event.preventDefault();
      setPaletteOpen((open) => !open);
    };

    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, []);

  /*
   * The bare `/` search shortcut. Being a single-character shortcut it must be
   * switchable off to meet WCAG 2.2 SC 2.1.4; the preference is read on every
   * keystroke and the palette footer offers the toggle.
   */
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (paletteOpen || !isSlashSearchEnabled()) return;
      if (!matchesAuthoringSearchShortcut(event)) return;
      // Only claim the key when the surface actually offers search, so `/`
      // still types normally on surfaces that have none.
      if (focusAuthoringContextSearch()) event.preventDefault();
    };

    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [paletteOpen]);

  const openPalette = React.useCallback(() => setPaletteOpen(true), []);

  return (
    <div className={authoringShellClass}>
      <AuthoringHeader onOpenCommandPalette={openPalette} />
      <AuthoringSecondaryNav />
      <main className={authoringMainClass}>{children}</main>
      <AuthoringCommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
