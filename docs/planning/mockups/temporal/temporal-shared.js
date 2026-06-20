/**
 * temporal-shared.js — shared utilities for all Objectified Temporal mockup screens.
 */
const TemporalShared = (() => {
  const THEME_KEY = 'temporal-theme';

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
    { group: 'Workflows', items: [
      { href: 'workflow-list.html',    icon: 'list-tree',      label: 'All Workflows' },
      { href: 'workflow-designer.html',icon: 'git-graph',      label: 'Designer' },
      { href: 'workflow-run.html',     icon: 'play-circle',    label: 'Run Detail' },
    ]},
    { group: 'History & Monitor', items: [
      { href: 'event-history.html',    icon: 'scroll-text',    label: 'Event History' },
      { href: 'activity-monitor.html', icon: 'activity',       label: 'Activity Monitor' },
    ]},
    { group: 'Resilience', items: [
      { href: 'saga-viewer.html',      icon: 'undo-2',         label: 'Saga Viewer' },
    ]},
    { group: 'Infrastructure', items: [
      { href: 'worker-registry.html',  icon: 'server',         label: 'Worker Registry' },
      { href: 'schedule.html',         icon: 'calendar-clock', label: 'Schedules' },
    ]},
  ];

  return { applyTheme, bindThemeToggle, NAV };
})();
