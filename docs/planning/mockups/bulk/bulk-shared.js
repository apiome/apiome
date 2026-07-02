/**
 * bulk-shared.js — shared utilities for all Apiome Bulk mockup screens.
 */
const BulkShared = (() => {
  const THEME_KEY = 'bulk-theme';

  function applyTheme() {
    const stored = localStorage.getItem(THEME_KEY);
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (stored === 'dark' || (!stored && prefersDark)) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }

  function bindThemeToggle(btnId = 'themeBtn') {
    applyTheme();
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener('click', () => {
      document.documentElement.classList.toggle('dark');
      localStorage.setItem(THEME_KEY, document.documentElement.classList.contains('dark') ? 'dark' : 'light');
    });
  }

  const NAV = [
    { group: 'Sources & Files', items: [
      { href: 'source-connections.html', icon: 'plug',             label: 'Source Connections' },
      { href: 'file-browser.html',       icon: 'folder-open',      label: 'File Browser' },
      { href: 'schema-mapper.html',      icon: 'arrow-right-left', label: 'Schema Mapper' },
    ]},
    { group: 'Job Planning', items: [
      { href: 'job-planner.html',        icon: 'sliders-horizontal', label: 'Job Planner' },
      { href: 'partition-view.html',     icon: 'layout-grid',      label: 'Partitions' },
    ]},
    { group: 'Execution', items: [
      { href: 'job-queue.html',          icon: 'list-ordered',     label: 'Job Queue' },
      { href: 'chunk-progress.html',     icon: 'loader',           label: 'Chunk Progress' },
    ]},
    { group: 'History', items: [
      { href: 'run-history.html',        icon: 'history',          label: 'Run History' },
      { href: 'run-detail.html',         icon: 'file-text',        label: 'Run Detail' },
    ]},
  ];

  return { applyTheme, bindThemeToggle, NAV };
})();
