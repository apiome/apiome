const WormholeShared = (() => {
  const THEME_KEY = 'wormhole-theme';

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
      { label: 'Wormhole Map', href: 'wormhole-map.html', icon: 'route', star: true },
    ]},
    { group: 'Bridges', items: [
      { label: 'Bridges', href: 'bridges.html', icon: 'git-merge' },
      { label: 'Bridge Designer', href: 'bridge-designer.html', icon: 'plus-circle' },
      { label: 'Schema Compatibility', href: 'schema-compat.html', icon: 'check-circle' },
    ]},
    { group: 'Policy', items: [
      { label: 'Residency Policy', href: 'residency-policy.html', icon: 'shield' },
      { label: 'Conflict Resolution', href: 'conflict-resolution.html', icon: 'git-compare' },
    ]},
    { group: 'Operations', items: [
      { label: 'Transfer Runs', href: 'transfer-runs.html', icon: 'play-circle' },
      { label: 'Transfer Audit', href: 'transfer-audit.html', icon: 'scroll-text' },
    ]},
  ];

  return { applyTheme, bindThemeToggle, NAV };
})();
