/**
 * scheduler-shared.js — shared utilities for all Apiome Scheduler mockup screens.
 */
const SchedulerShared = (() => {
  const THEME_KEY = 'scheduler-theme';

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
    { group: 'Scheduling', items: [
      { href: 'job-list.html',       icon: 'list-checks',    label: 'All Jobs' },
      { href: 'job-dag.html',        icon: 'network',        label: 'Dependency DAG' },
      { href: 'schedule-editor.html',icon: 'calendar-cog',   label: 'Schedule Editor' },
    ]},
    { group: 'SLA & Alerting', items: [
      { href: 'sla-tracker.html',    icon: 'gauge',          label: 'SLA Tracker' },
      { href: 'escalation-policy.html', icon: 'bell-ring',   label: 'Escalation Policies' },
    ]},
    { group: 'Capacity', items: [
      { href: 'capacity-heatmap.html', icon: 'grid-3x3',     label: 'Capacity Heatmap' },
    ]},
    { group: 'History', items: [
      { href: 'run-timeline.html',   icon: 'chart-gantt',    label: 'Run Timeline' },
      { href: 'job-detail.html',     icon: 'file-clock',     label: 'Job Detail' },
    ]},
  ];

  return { applyTheme, bindThemeToggle, NAV };
})();
