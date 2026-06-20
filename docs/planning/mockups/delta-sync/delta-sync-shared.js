const DeltaSyncShared = (() => {
  const THEME_KEY = 'delta-sync-theme';

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
      { label: 'Watermark Registry', href: 'watermark-registry.html', icon: 'trending-up', star: true },
    ]},
    { group: 'Configuration', items: [
      { label: 'Merge Config', href: 'merge-config.html', icon: 'git-merge' },
      { label: 'Partition Pruner', href: 'partition-pruner.html', icon: 'filter' },
      { label: 'Source Connections', href: 'source-connections.html', icon: 'plug' },
    ]},
    { group: 'Operations', items: [
      { label: 'Drift Detector', href: 'drift-detector.html', icon: 'activity' },
      { label: 'Backfill Planner', href: 'backfill-planner.html', icon: 'history' },
      { label: 'Sync Runs', href: 'sync-runs.html', icon: 'play-circle' },
    ]},
    { group: 'Scheduling', items: [
      { label: 'Sync Schedule', href: 'sync-schedule.html', icon: 'clock' },
    ]},
  ];

  return { applyTheme, bindThemeToggle, NAV };
})();
