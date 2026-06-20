/**
 * gateway-shared.js — shared utilities for all Objectified File Gateway mockup screens.
 */
const GatewayShared = (() => {
  const THEME_KEY = 'file-gateway-theme';

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
    { group: 'Storage & Connections', items: [
      { href: 'storage-connections.html', icon: 'cloud',              label: 'Storage Connections' },
      { href: 'bucket-browser.html',      icon: 'folder-open',        label: 'Bucket Browser' },
      { href: 'schema-inference.html',    icon: 'scan-search',        label: 'Schema Inference' },
    ]},
    { group: 'Format & Parsers', items: [
      { href: 'format-configurator.html', icon: 'file-cog',           label: 'Format Configurator' },
      { href: 'plugin-parsers.html',      icon: 'puzzle',             label: 'Plugin Parsers' },
    ]},
    { group: 'Routing & Dedup', items: [
      { href: 'routing-rules.html',       icon: 'git-branch',         label: 'Routing Rules' },
      { href: 'deduplication.html',       icon: 'copy-check',         label: 'Deduplication' },
    ]},
    { group: 'Monitoring & History', items: [
      { href: 'arrival-monitor.html',     icon: 'bell',               label: 'Arrival Monitor' },
      { href: 'load-history.html',        icon: 'history',            label: 'Load History' },
    ]},
  ];

  return { applyTheme, bindThemeToggle, NAV };
})();
