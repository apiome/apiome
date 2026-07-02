'use client';

import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

export type Theme = 'light' | 'dark' | 'system';
export type SpecTheme = 'default' | 'monokai' | 'github' | 'darcula' | 'solarized' | 'nord';

interface ThemeContextType {
  theme: Theme;
  specTheme: SpecTheme;
  resolvedTheme: 'light' | 'dark';
  setTheme: (theme: Theme) => void;
  setSpecTheme: (theme: SpecTheme) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export const specThemes: Record<SpecTheme, {
  name: string;
  bgColor: string;
  textColor: string;
  bg: string;
  text: string;
  keyword: string;
  string: string;
  number: string;
  property: string;
  bracket: string
}> = {
  default: {
    name: 'Default',
    bgColor: '#fafafa',
    textColor: '#18181b',
    bg: 'bg-zinc-50 dark:bg-zinc-900',
    text: 'text-zinc-900 dark:text-zinc-100',
    keyword: 'text-purple-600 dark:text-purple-400',
    string: 'text-green-600 dark:text-green-400',
    number: 'text-blue-600 dark:text-blue-400',
    property: 'text-red-600 dark:text-red-400',
    bracket: 'text-zinc-500 dark:text-zinc-400',
  },
  monokai: {
    name: 'Monokai',
    bgColor: '#272822',
    textColor: '#f8f8f2',
    bg: 'bg-[#272822]',
    text: 'text-[#f8f8f2]',
    keyword: 'text-[#f92672]',
    string: 'text-[#e6db74]',
    number: 'text-[#ae81ff]',
    property: 'text-[#a6e22e]',
    bracket: 'text-[#f8f8f2]',
  },
  github: {
    name: 'GitHub',
    bgColor: '#ffffff',
    textColor: '#24292f',
    bg: 'bg-white dark:bg-[#0d1117]',
    text: 'text-[#24292f] dark:text-[#c9d1d9]',
    keyword: 'text-[#cf222e] dark:text-[#ff7b72]',
    string: 'text-[#0a3069] dark:text-[#a5d6ff]',
    number: 'text-[#0550ae] dark:text-[#79c0ff]',
    property: 'text-[#953800] dark:text-[#ffa657]',
    bracket: 'text-[#24292f] dark:text-[#c9d1d9]',
  },
  darcula: {
    name: 'Darcula',
    bgColor: '#282a36',
    textColor: '#f8f8f2',
    bg: 'bg-[#282a36]',
    text: 'text-[#f8f8f2]',
    keyword: 'text-[#ff79c6]',
    string: 'text-[#f1fa8c]',
    number: 'text-[#bd93f9]',
    property: 'text-[#50fa7b]',
    bracket: 'text-[#6272a4]',
  },
  solarized: {
    name: 'Solarized',
    bgColor: '#002b36',
    textColor: '#839496',
    bg: 'bg-[#002b36] dark:bg-[#fdf6e3]',
    text: 'text-[#839496] dark:text-[#657b83]',
    keyword: 'text-[#859900]',
    string: 'text-[#2aa198]',
    number: 'text-[#d33682]',
    property: 'text-[#268bd2]',
    bracket: 'text-[#93a1a1] dark:text-[#586e75]',
  },
  nord: {
    name: 'Nord',
    bgColor: '#2e3440',
    textColor: '#d8dee9',
    bg: 'bg-[#2e3440]',
    text: 'text-[#d8dee9]',
    keyword: 'text-[#81a1c1]',
    string: 'text-[#a3be8c]',
    number: 'text-[#b48ead]',
    property: 'text-[#88c0d0]',
    bracket: 'text-[#4c566a]',
  },
};

function readStoredTheme<T extends string>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  const value = window.localStorage.getItem(key) as T | null;
  return value ?? fallback;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => readStoredTheme<Theme>('theme', 'system'));
  const [specTheme, setSpecThemeState] = useState<SpecTheme>(() =>
    readStoredTheme<SpecTheme>('specTheme', 'default')
  );
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>('light');

  useEffect(() => {
    const updateResolvedTheme = () => {
      if (theme === 'system') {
        const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        setResolvedTheme(systemDark ? 'dark' : 'light');
      } else {
        setResolvedTheme(theme);
      }
    };

    updateResolvedTheme();

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    mediaQuery.addEventListener('change', updateResolvedTheme);
    return () => mediaQuery.removeEventListener('change', updateResolvedTheme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.classList.remove('light', 'dark');
    document.documentElement.classList.add(resolvedTheme);
  }, [resolvedTheme]);

  const setTheme = (newTheme: Theme) => {
    setThemeState(newTheme);
    localStorage.setItem('theme', newTheme);
  };

  const setSpecTheme = (newTheme: SpecTheme) => {
    setSpecThemeState(newTheme);
    localStorage.setItem('specTheme', newTheme);
  };

  return (
    <ThemeContext.Provider value={{ theme, specTheme, resolvedTheme, setTheme, setSpecTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}

