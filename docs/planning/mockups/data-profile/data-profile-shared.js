const DataProfileShared = (() => {
  const THEME_KEY = 'data-profile-theme';

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
      { label: 'Column Profiler', href: 'column-profiler.html', icon: 'bar-chart-2', star: true },
    ]},
    { group: 'Analysis', items: [
      { label: 'PII Scanner', href: 'pii-scanner.html', icon: 'shield-alert' },
      { label: 'Anomaly Heatmap', href: 'anomaly-heatmap.html', icon: 'flame' },
      { label: 'Schema Wizard', href: 'schema-wizard.html', icon: 'wand-2' },
    ]},
    { group: 'Sources', items: [
      { label: 'Source Connections', href: 'source-connections.html', icon: 'plug' },
      { label: 'Dataset Catalog', href: 'dataset-catalog.html', icon: 'folder-open' },
    ]},
    { group: 'Operations', items: [
      { label: 'Profile Runs', href: 'profile-runs.html', icon: 'play-circle' },
      { label: 'Quality Rules', href: 'quality-rules.html', icon: 'check-circle' },
    ]},
  ];

  return { applyTheme, bindThemeToggle, NAV };
})();
