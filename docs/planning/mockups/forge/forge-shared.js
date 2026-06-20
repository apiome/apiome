// Shared utilities for Forge mockup screens
window.ForgeShared = {
  accentColor: 'orange',
  navLinks: [
    { group: 'Pipelines', links: [
      { href: 'pipeline-list.html', icon: 'list-tree',   label: 'All Pipelines', count: '14' },
      { href: 'pipeline-canvas.html', icon: 'workflow',  label: 'Canvas Editor' },
      { href: 'template-library.html', icon: 'library', label: 'Templates', count: '32' },
    ]},
    { group: 'Authoring', links: [
      { href: 'source-connector.html', icon: 'database',  label: 'Source Connectors', count: '8' },
      { href: 'transform-step.html', icon: 'code-2',      label: 'Transform Steps' },
      { href: 'target-loader.html', icon: 'table-2',      label: 'Target Loaders', count: '5' },
    ]},
    { group: 'Testing', links: [
      { href: 'debugger.html', icon: 'bug',             label: 'Debugger' },
      { href: 'ab-test.html', icon: 'split',            label: 'A/B Tests' },
    ]},
    { group: 'History', links: [
      { href: 'run-history.html', icon: 'history',      label: 'Run History' },
    ]},
  ],

  applyTheme() {
    const stored = localStorage.getItem('forge-theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (stored === 'dark' || (!stored && prefersDark)) document.documentElement.classList.add('dark');
  },

  bindThemeToggle(btnId = 'themeBtn') {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener('click', () => {
      document.documentElement.classList.toggle('dark');
      localStorage.setItem('forge-theme', document.documentElement.classList.contains('dark') ? 'dark' : 'light');
    });
  },
};

window.ForgeShared.applyTheme();
