'use client';

import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
} from 'react';
import { useSession } from 'next-auth/react';
import { useTheme as useNextTheme } from 'next-themes';
import { Theme, themes, getThemeById, getDefaultTheme } from '../config/themes';
import { applyObjTokens } from '@lib/theme/apply-obj-tokens';
import type { ThemePaletteOverrides, ThemeModeName, ThemeChangedDetail } from '@lib/theme/types';
import { THEME_CHANGED_EVENT } from '@lib/theme/types';

interface ThemeContextType {
  currentTheme: Theme;
  setTheme: (themeId: string) => void;
  availableThemes: Theme[];
  isSystemTheme: boolean;
  paletteOverrides: ThemePaletteOverrides;
  setPaletteOverrides: React.Dispatch<React.SetStateAction<ThemePaletteOverrides>>;
  resetPaletteToThemeDefaults: () => void;
  persistThemePreference: () => Promise<void>;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const darkThemeIds = ['dark', 'high-contrast', 'blueprint', 'solarized', 'nord', 'darcula'];

function resolvedLightDark(effectiveTheme: Theme): 'light' | 'dark' {
  return darkThemeIds.includes(effectiveTheme.id) ? 'dark' : 'light';
}

function preferenceModeFromThemeId(id: string): ThemeModeName {
  if (id === 'light' || id === 'dark' || id === 'system') return id;
  return 'system';
}

function emitThemeChanged(detail: ThemeChangedDetail) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(THEME_CHANGED_EVENT, { detail }));
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [currentTheme, setCurrentTheme] = useState<Theme>(getDefaultTheme());
  const [isSystemTheme, setIsSystemTheme] = useState(false);
  const [mounted, setMounted] = useState(false);
  const sessionAppliedRef = useRef(false);
  const [paletteOverrides, setPaletteOverrides] = useState<ThemePaletteOverrides>({});
  const { setTheme: setNextTheme, resolvedTheme, theme: nextTheme } = useNextTheme();
  const { data: session, update: updateSession } = useSession();

  useEffect(() => {
    setMounted(true);
  }, []);

  const getSystemPreferredTheme = useCallback(() => {
    if (typeof window !== 'undefined') {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      return prefersDark
        ? getThemeById('dark') || getDefaultTheme()
        : getThemeById('light') || getDefaultTheme();
    }
    const prefersDark = resolvedTheme === 'dark';
    return prefersDark
      ? getThemeById('dark') || getDefaultTheme()
      : getThemeById('light') || getDefaultTheme();
  }, [resolvedTheme]);

  const applyDomTheme = useCallback(
    (theme: Theme, isSystem: boolean, overrides: ThemePaletteOverrides) => {
      const html = document.documentElement;
      const body = document.body;

      themes.forEach((t) => {
        html.classList.remove(t.cssClass);
        body.classList.remove(t.cssClass);
      });

      const effectiveTheme = isSystem ? getSystemPreferredTheme() : theme;

      html.setAttribute('data-theme', effectiveTheme.id);
      body.setAttribute('data-theme', effectiveTheme.id);

      const isDarkBased = darkThemeIds.includes(effectiveTheme.id);

      if (isSystem) {
        setNextTheme('system');
      } else if (isDarkBased) {
        setNextTheme('dark');
      } else {
        setNextTheme('light');
      }

      html.classList.add(effectiveTheme.cssClass);
      body.classList.add(effectiveTheme.cssClass);

      html.style.setProperty('--background', effectiveTheme.colors.background);
      html.style.setProperty('--foreground', effectiveTheme.colors.foreground);
      applyObjTokens(html, effectiveTheme, overrides);

      body.style.backgroundColor = effectiveTheme.colors.background;
      body.style.color = effectiveTheme.colors.foreground;

      const mode = preferenceModeFromThemeId(theme.id);
      emitThemeChanged({
        theme: mode,
        resolved: resolvedLightDark(effectiveTheme),
        overrides,
      });
    },
    [getSystemPreferredTheme, setNextTheme]
  );

  useEffect(() => {
    if (!mounted) return;

    const uid = (session?.user as { user_id?: string })?.user_id;
    const serverTheme = (session?.user as { theme_name?: ThemeModeName })?.theme_name;
    const serverOverrides = (session?.user as { theme_overrides?: ThemePaletteOverrides })
      ?.theme_overrides;

    if (uid && serverTheme && (serverTheme === 'light' || serverTheme === 'dark' || serverTheme === 'system')) {
      sessionAppliedRef.current = true;
      const theme = getThemeById(serverTheme);
      if (theme) {
        const o = serverOverrides && typeof serverOverrides === 'object' ? serverOverrides : {};
        setPaletteOverrides(o);
        setCurrentTheme(theme);
        setIsSystemTheme(serverTheme === 'system');
        localStorage.setItem('app-theme', serverTheme);
        return;
      }
    }

    const savedThemeId = localStorage.getItem('app-theme');
    const nextThemeSaved = localStorage.getItem('theme');

    const shouldUseSystem = !nextThemeSaved || nextThemeSaved === 'system';

    if (savedThemeId === 'system' || shouldUseSystem) {
      const systemTheme = getThemeById('system');
      if (systemTheme) {
        setCurrentTheme(systemTheme);
        setIsSystemTheme(true);
      }
    } else if (savedThemeId) {
      const theme = getThemeById(savedThemeId);
      if (theme) {
        setCurrentTheme(theme);
        setIsSystemTheme(false);
      }
    } else {
      const systemTheme = getThemeById('system') || getDefaultTheme();
      setCurrentTheme(systemTheme);
      setIsSystemTheme(true);
      localStorage.setItem('app-theme', 'system');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted]);

  useEffect(() => {
    if (!mounted) return;
    const uid = (session?.user as { user_id?: string })?.user_id;
    const serverTheme = (session?.user as { theme_name?: ThemeModeName })?.theme_name;
    const serverOverrides = (session?.user as { theme_overrides?: ThemePaletteOverrides })
      ?.theme_overrides;

    if (!uid || !serverTheme || sessionAppliedRef.current) return;
    if (serverTheme !== 'light' && serverTheme !== 'dark' && serverTheme !== 'system') return;

    const theme = getThemeById(serverTheme);
    if (!theme) return;

    sessionAppliedRef.current = true;
    const o = serverOverrides && typeof serverOverrides === 'object' ? serverOverrides : {};
    setPaletteOverrides(o);
    setCurrentTheme(theme);
    setIsSystemTheme(serverTheme === 'system');
    localStorage.setItem('app-theme', serverTheme);
  }, [mounted, session?.user]);

  useEffect(() => {
    if (!mounted) return;
    applyDomTheme(currentTheme, isSystemTheme, paletteOverrides);
  }, [mounted, currentTheme, isSystemTheme, paletteOverrides, applyDomTheme, resolvedTheme]);

  useEffect(() => {
    if (!mounted) return;

    if (nextTheme === 'system' && !isSystemTheme) {
      const systemTheme = getThemeById('system');
      if (systemTheme) {
        setCurrentTheme(systemTheme);
        setIsSystemTheme(true);
        localStorage.setItem('app-theme', 'system');
      }
    }
  }, [mounted, nextTheme, isSystemTheme]);

  const setTheme = (themeId: string) => {
    const theme = getThemeById(themeId);
    if (theme) {
      const isSystem = themeId === 'system';
      setCurrentTheme(theme);
      setIsSystemTheme(isSystem);
      localStorage.setItem('app-theme', themeId);
    }
  };

  const resetPaletteToThemeDefaults = useCallback(() => {
    setPaletteOverrides({});
  }, []);

  const persistThemePreference = useCallback(async () => {
    const mode = preferenceModeFromThemeId(currentTheme.id);
    const res = await fetch('/api/v1/preferences/theme', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme: mode, overrides: paletteOverrides }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error((err as { error?: string }).error || 'Failed to save theme');
    }
    await updateSession({
      user: {
        ...session?.user,
        theme_name: mode,
        theme_overrides: paletteOverrides,
      },
    });
  }, [currentTheme.id, paletteOverrides, session?.user, updateSession]);

  return (
    <ThemeContext.Provider
      value={{
        currentTheme,
        setTheme,
        availableThemes: themes,
        isSystemTheme,
        paletteOverrides,
        setPaletteOverrides,
        resetPaletteToThemeDefaults,
        persistThemePreference,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
