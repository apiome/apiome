'use client';

import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from 'react';
import { useTheme as useNextTheme } from 'next-themes';
import { Theme, themes, getThemeById, getDefaultTheme } from '../config/themes';

interface ThemeContextType {
  currentTheme: Theme;
  setTheme: (themeId: string) => void;
  availableThemes: Theme[];
  isSystemTheme: boolean;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [currentTheme, setCurrentTheme] = useState<Theme>(getDefaultTheme());
  const [isSystemTheme, setIsSystemTheme] = useState(false);
  const [mounted, setMounted] = useState(false);
  const mountedRef = useRef(false);
  const { setTheme: setNextTheme, resolvedTheme, theme: nextTheme } = useNextTheme();

  // Mark as mounted after hydration
  useEffect(() => {
    setMounted(true);
  }, []);

  // Get the effective theme for system preference.
  // Prefer matchMedia on the client so we always use the actual OS preference (e.g. when
  // switching from Dark to System while OS is light, resolvedTheme can still be 'dark').
  const getSystemPreferredTheme = useCallback(() => {
    if (typeof window !== 'undefined') {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      return prefersDark ? getThemeById('dark') || getDefaultTheme() : getThemeById('light') || getDefaultTheme();
    }
    // SSR/fallback: use resolvedTheme from next-themes when available
    const prefersDark = resolvedTheme === 'dark';
    return prefersDark ? getThemeById('dark') || getDefaultTheme() : getThemeById('light') || getDefaultTheme();
  }, [resolvedTheme]);

  // Apply theme to DOM
  const applyTheme = useCallback((theme: Theme, isSystem: boolean = false) => {
    const html = document.documentElement;
    const body = document.body;

    // Remove all theme classes from html and body
    themes.forEach(t => {
      html.classList.remove(t.cssClass);
      body.classList.remove(t.cssClass);
    });

    // For system theme, we apply the actual light/dark theme but mark it as system
    const effectiveTheme = isSystem ? getSystemPreferredTheme() : theme;

    // Set data-theme attribute for CSS targeting
    html.setAttribute('data-theme', effectiveTheme.id);
    body.setAttribute('data-theme', effectiveTheme.id);

    // Determine if this is a "dark" based theme (needs .dark class for Tailwind dark: variants)
    const darkThemes = ['dark', 'high-contrast', 'blueprint', 'solarized', 'nord', 'darcula'];
    const isDarkBased = darkThemes.includes(effectiveTheme.id);

    // Use next-themes: when following system, set 'system' so it tracks OS and updates .dark;
    // when using a fixed theme, set 'light' or 'dark' so .dark is correct.
    if (isSystem) {
      setNextTheme('system');
    } else if (isDarkBased) {
      setNextTheme('dark');
    } else {
      setNextTheme('light');
    }

    // Add new theme class to both html and body
    html.classList.add(effectiveTheme.cssClass);
    body.classList.add(effectiveTheme.cssClass);

    // Set CSS custom properties directly on html style
    html.style.setProperty('--background', effectiveTheme.colors.background);
    html.style.setProperty('--foreground', effectiveTheme.colors.foreground);

    // Force body background and color
    body.style.backgroundColor = effectiveTheme.colors.background;
    body.style.color = effectiveTheme.colors.foreground;
  }, [getSystemPreferredTheme, setNextTheme]);

  // Initialize theme from localStorage or system preference
  useEffect(() => {
    if (!mounted) return;
    if (mountedRef.current) return;

    mountedRef.current = true;
    // Use same storage key as next-themes: 'theme'
    const savedThemeId = localStorage.getItem('app-theme');
    const nextThemeSaved = localStorage.getItem('theme');

    // Check if next-themes is set to system or if no preference exists
    const shouldUseSystem = !nextThemeSaved || nextThemeSaved === 'system';

    if (savedThemeId === 'system' || shouldUseSystem) {
      // User chose to follow system
      const systemTheme = getThemeById('system');
      if (systemTheme) {
        setCurrentTheme(systemTheme);
        setIsSystemTheme(true);
        applyTheme(systemTheme, true);
      }
    } else if (savedThemeId) {
      const theme = getThemeById(savedThemeId);
      if (theme) {
        setCurrentTheme(theme);
        setIsSystemTheme(false);
        applyTheme(theme, false);
      }
    } else {
      // No saved preference - default to system
      const systemTheme = getThemeById('system') || getDefaultTheme();
      setCurrentTheme(systemTheme);
      setIsSystemTheme(true);
      applyTheme(systemTheme, true);
      localStorage.setItem('app-theme', 'system');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted]);

  // Listen for system preference changes via matchMedia
  useEffect(() => {
    if (!mounted || !isSystemTheme) return;

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

    const handleChange = (e: MediaQueryListEvent) => {
      const effectiveTheme = e.matches
        ? getThemeById('dark') || getDefaultTheme()
        : getThemeById('light') || getDefaultTheme();

      const html = document.documentElement;
      const body = document.body;

      // Remove existing theme classes
      themes.forEach(t => {
        html.classList.remove(t.cssClass);
        body.classList.remove(t.cssClass);
      });

      // Set data-theme attribute
      html.setAttribute('data-theme', effectiveTheme.id);
      body.setAttribute('data-theme', effectiveTheme.id);

      // Set dark class based on system preference
      if (e.matches) {
        html.classList.add('dark');
        setNextTheme('dark');
      } else {
        html.classList.remove('dark');
        setNextTheme('light');
      }

      // Add theme class
      html.classList.add(effectiveTheme.cssClass);
      body.classList.add(effectiveTheme.cssClass);

      // Set CSS custom properties
      html.style.setProperty('--background', effectiveTheme.colors.background);
      html.style.setProperty('--foreground', effectiveTheme.colors.foreground);
      body.style.backgroundColor = effectiveTheme.colors.background;
      body.style.color = effectiveTheme.colors.foreground;
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, [mounted, isSystemTheme, setNextTheme]);

  // Listen for resolved theme changes from next-themes
  useEffect(() => {
    if (!mountedRef.current) return;

    // When resolvedTheme changes and we're using system theme, reapply
    if (isSystemTheme && resolvedTheme) {
      const systemTheme = getThemeById('system');
      if (systemTheme) {
        // Get the actual theme to apply based on system preference
        const effectiveTheme = getSystemPreferredTheme();

        // Apply the dark class correctly based on system preference
        const html = document.documentElement;
        const body = document.body;

        // Remove existing theme classes
        themes.forEach(t => {
          html.classList.remove(t.cssClass);
          body.classList.remove(t.cssClass);
        });

        // Set data-theme attribute
        html.setAttribute('data-theme', effectiveTheme.id);
        body.setAttribute('data-theme', effectiveTheme.id);

        // Determine if dark mode should be applied
        const darkThemes = ['dark', 'high-contrast', 'blueprint', 'solarized', 'nord', 'darcula'];
        const isDarkBased = darkThemes.includes(effectiveTheme.id);

        // Use next-themes to properly set the dark class
        if (isDarkBased) {
          setNextTheme('dark');
        } else {
          setNextTheme('light');
        }

        // Add theme class
        html.classList.add(effectiveTheme.cssClass);
        body.classList.add(effectiveTheme.cssClass);

        // Set CSS custom properties
        html.style.setProperty('--background', effectiveTheme.colors.background);
        html.style.setProperty('--foreground', effectiveTheme.colors.foreground);
        body.style.backgroundColor = effectiveTheme.colors.background;
        body.style.color = effectiveTheme.colors.foreground;
      }
    }
  }, [isSystemTheme, resolvedTheme, getSystemPreferredTheme, setNextTheme]);

  // Sync with next-themes when it changes
  useEffect(() => {
    if (!mountedRef.current) return;

    // If next-themes is set to system, update our theme accordingly
    if (nextTheme === 'system' && !isSystemTheme) {
      const systemTheme = getThemeById('system');
      if (systemTheme) {
        setCurrentTheme(systemTheme);
        setIsSystemTheme(true);
        applyTheme(systemTheme, true);
        localStorage.setItem('app-theme', 'system');
      }
    }
  }, [nextTheme, isSystemTheme, applyTheme]);

  const setTheme = (themeId: string) => {
    const theme = getThemeById(themeId);
    if (theme) {
      const isSystem = themeId === 'system';
      setCurrentTheme(theme);
      setIsSystemTheme(isSystem);
      applyTheme(theme, isSystem);
      localStorage.setItem('app-theme', themeId);
    }
  };

  return (
    <ThemeContext.Provider value={{ currentTheme, setTheme, availableThemes: themes, isSystemTheme }}>
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

