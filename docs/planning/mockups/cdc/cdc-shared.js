/**
 * cdc-shared.js — shared utilities for all Apiome CDC mockup screens.
 */
const CDCShared = (() => {
  const THEME_KEY = 'cdc-theme';

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
    { group: 'Sources & Connectors', items: [
      { href: 'source-connections.html', icon: 'database',        label: 'Source Connections' },
      { href: 'replication-slots.html',  icon: 'anchor',          label: 'Replication Slots' },
      { href: 'connector-config.html',   icon: 'sliders',         label: 'Connector Config' },
    ]},
    { group: 'Capture & Schema', items: [
      { href: 'capture-stream.html',     icon: 'waves',           label: 'Capture Stream' },
      { href: 'schema-handler.html',     icon: 'diff',            label: 'Schema Handler' },
    ]},
    { group: 'Backfill & Lag', items: [
      { href: 'backfill-manager.html',   icon: 'hard-drive-download', label: 'Backfill Manager' },
      { href: 'lag-monitor.html',        icon: 'gauge',           label: 'Lag Monitor' },
    ]},
    { group: 'History & Audit', items: [
      { href: 'change-history.html',     icon: 'history',         label: 'Change History' },
      { href: 'slot-health.html',        icon: 'heart-pulse',     label: 'Slot Health' },
    ]},
  ];

  return { applyTheme, bindThemeToggle, NAV };
})();
