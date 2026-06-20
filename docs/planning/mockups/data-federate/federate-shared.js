(() => {
  const KEY = 'data-federate-theme';

  function applyTheme() {
    const saved = localStorage.getItem(KEY);
    if (saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }

  function bindThemeToggle() {
    applyTheme();
    const btn = document.getElementById('themeBtn');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const isDark = document.documentElement.classList.toggle('dark');
      localStorage.setItem(KEY, isDark ? 'dark' : 'light');
    });
  }

  const NAV = [
    {
      group: 'Sources & Connections',
      items: [
        { label: 'Source Catalog',    href: 'source-catalog.html',   icon: 'database' },
        { label: 'Virtual Schemas',   href: 'virtual-schemas.html',  icon: 'layers' },
      ],
    },
    {
      group: 'Query & Execution',
      items: [
        { label: 'SQL Editor',        href: 'sql-editor.html',       icon: 'terminal', star: true },
        { label: 'Query Planner',     href: 'query-planner.html',    icon: 'git-branch-plus' },
        { label: 'Dialect Config',    href: 'dialect-config.html',   icon: 'settings-2' },
      ],
    },
    {
      group: 'Schema Mapping',
      items: [
        { label: 'Schema Mapper',     href: 'schema-mapper.html',    icon: 'arrow-left-right' },
        { label: 'Saved Queries',     href: 'saved-queries.html',    icon: 'bookmark' },
      ],
    },
    {
      group: 'History & Materialization',
      items: [
        { label: 'Query History',     href: 'query-history.html',    icon: 'history' },
        { label: 'Materialization',   href: 'materialization.html',  icon: 'database-zap' },
      ],
    },
  ];

  return { applyTheme, bindThemeToggle, NAV };
})();
