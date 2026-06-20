const ReverseEtlShared = (() => {
  const THEME_KEY = 'reverse-etl-theme';

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
      { label: 'Audience Builder', href: 'audience-builder.html', icon: 'users', star: true },
    ]},
    { group: 'Destinations', items: [
      { label: 'Destinations', href: 'destinations.html', icon: 'send' },
      { label: 'Field Mapping', href: 'field-mapping.html', icon: 'arrow-right-left' },
      { label: 'Sync Schedule', href: 'sync-schedule.html', icon: 'clock' },
    ]},
    { group: 'Operations', items: [
      { label: 'Sync Runs', href: 'sync-runs.html', icon: 'play-circle' },
      { label: 'Delivery Log', href: 'delivery-log.html', icon: 'list' },
    ]},
    { group: 'Usage', items: [
      { label: 'Volume Metering', href: 'volume-metering.html', icon: 'bar-chart-2' },
      { label: 'Segment Library', href: 'segment-library.html', icon: 'bookmark' },
    ]},
  ];

  return { applyTheme, bindThemeToggle, NAV };
})();
