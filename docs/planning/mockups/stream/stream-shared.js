/**
 * stream-shared.js — shared utilities for all Objectified Stream mockup screens.
 */
const StreamShared = (() => {
  const THEME_KEY = 'stream-theme';

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
    { group: 'Sources & Topics', items: [
      { href: 'broker-connections.html', icon: 'server',          label: 'Broker Connections' },
      { href: 'topic-browser.html',      icon: 'layers',           label: 'Topic Browser' },
      { href: 'schema-registry.html',    icon: 'book-open',        label: 'Schema Registry' },
    ]},
    { group: 'Mapping & Config', items: [
      { href: 'topic-mapper.html',       icon: 'git-branch',       label: 'Topic Mapper' },
      { href: 'consumer-config.html',    icon: 'settings-2',       label: 'Consumer Config' },
    ]},
    { group: 'Monitoring', items: [
      { href: 'consumer-dashboard.html', icon: 'activity',         label: 'Consumer Dashboard' },
      { href: 'lag-monitor.html',        icon: 'gauge',            label: 'Lag Monitor' },
    ]},
    { group: 'Dead Letter & History', items: [
      { href: 'dead-letter-queue.html',  icon: 'circle-x',         label: 'Dead Letter Queue' },
      { href: 'stream-history.html',     icon: 'history',          label: 'Stream History' },
    ]},
  ];

  return { applyTheme, bindThemeToggle, NAV };
})();
