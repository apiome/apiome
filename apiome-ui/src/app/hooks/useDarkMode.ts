'use client';

import { useState, useEffect } from 'react';

/**
 * Hook to detect dark mode based on the .dark class on the document element.
 * This is the single source of truth for dark mode detection across the app,
 * ensuring consistency between Tailwind, Radix, and MUI components.
 */
export function useDarkMode(): boolean {
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const checkDarkMode = () => {
      setIsDark(document.documentElement.classList.contains('dark'));
    };

    // Initial check
    checkDarkMode();

    // Watch for changes to the dark class
    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class']
    });

    return () => observer.disconnect();
  }, []);

  return isDark;
}

export default useDarkMode;

