const DataQualityShared = (() => {
  const THEME_KEY = 'data-quality-theme';

  function applyTheme() {
    const stored = localStorage.getItem(THEME_KEY);
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (stored === 'dark' || (!stored && prefersDark)) document.documentElement.classList.add('dark');
    else document.documentElement.classList.remove('dark');
  }

  function bindThemeToggle() {
    applyTheme();
    const btn = document.getElementById('themeBtn');
    if (btn) btn.addEventListener('click', () => {
      document.documentElement.classList.toggle('dark');
      localStorage.setItem(THEME_KEY, document.documentElement.classList.contains('dark') ? 'dark' : 'light');
    });
  }

  const NAV = [
    { group: 'Core', items: [
      { label: 'Overview', href: 'index.html', icon: 'layout-dashboard' },
      { label: 'Rule Builder', href: 'rule-builder.html', icon: 'list-checks', star: true },
    ]},
    { group: 'Rules', items: [
      { label: 'Rule Sets', href: 'rule-sets.html', icon: 'layers' },
      { label: 'Cleanse Policies', href: 'cleanse-policies.html', icon: 'wand-2' },
      { label: 'Quality Score', href: 'quality-score.html', icon: 'bar-chart-2' },
    ]},
    { group: 'Operations', items: [
      { label: 'Run Results', href: 'run-results.html', icon: 'play-circle' },
      { label: 'Quarantine Manager', href: 'quarantine-manager.html', icon: 'archive' },
    ]},
    { group: 'Governance', items: [
      { label: 'Pipeline Gates', href: 'pipeline-gates.html', icon: 'shield-check' },
      { label: 'SLA Alerts', href: 'sla-alerts.html', icon: 'bell-ring' },
    ]},
  ];

  return { applyTheme, bindThemeToggle, NAV };
})();
