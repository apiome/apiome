// Shared sidebar for the Developer Portal & SDK Platform mockups. The active
// page is derived from the current document filename so every page can drop a
// <div id="sidebar"></div> and include this script.
(function () {
  const sections = [
    {
      title: 'Portal Platform',
      items: [
        { href: 'catalog.html',       icon: 'compass',       label: 'API Catalog' },
        { href: 'docs-hub.html',      icon: 'book-marked',   label: 'Docs Hub' },
        { href: 'registration.html',  icon: 'user-plus',     label: 'Registration' },
        { href: 'dev-analytics.html', icon: 'line-chart',    label: 'Dev Analytics' },
      ],
    },
    {
      title: 'Customization',
      items: [
        { href: 'branding.html',    icon: 'palette',     label: 'Branding & Theme' },
        { href: 'cms.html',         icon: 'file-text',   label: 'Content CMS' },
        { href: 'domains-sso.html', icon: 'globe-lock',  label: 'Domains & SSO' },
      ],
    },
    {
      title: 'SDK Platform',
      items: [
        { href: 'sdk-generator.html', icon: 'package-plus', label: 'SDK Generator' },
        { href: 'sdk-qa.html',        icon: 'beaker',       label: 'QA Pipeline',  badge: '<span class="text-[10px] px-1.5 rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 font-semibold">2</span>' },
        { href: 'sdk-publishing.html',icon: 'upload-cloud', label: 'Registries' },
        { href: 'sdk-lifecycle.html', icon: 'git-branch',   label: 'Versioning & LTS' },
        { href: 'sdk-docs.html',      icon: 'book-open',    label: 'SDK Docs' },
      ],
    },
    {
      title: 'Local Dev',
      items: [
        { href: 'mock-server.html',      icon: 'server-cog',  label: 'Mock Server' },
        { href: 'stateful-mocking.html', icon: 'database',    label: 'Stateful Engine' },
        { href: 'playground.html',       icon: 'play-circle', label: 'Playground' },
        { href: 'collaboration.html',    icon: 'users-round', label: 'Collab & Export' },
      ],
    },
    {
      title: 'IDE Extensions',
      items: [
        { href: 'vscode-schema.html', icon: 'code-2',     label: 'VS Code · Schema' },
        { href: 'vscode-cloud.html',  icon: 'cloud-cog',  label: 'VS Code · Cloud' },
        { href: 'jetbrains.html',     icon: 'square-terminal', label: 'JetBrains Plugin' },
        { href: 'schema-diff.html',   icon: 'split-square-horizontal', label: 'Diff & Preview' },
      ],
    },
  ];

  const path = location.pathname.split('/').pop() || 'index.html';

  function renderItem(it) {
    const isActive = it.href === path;
    const linkCls = isActive
      ? 'flex items-center gap-3 rounded-lg px-3 py-2.5 border border-indigo-200 dark:border-indigo-700/70 bg-indigo-500/10'
      : 'flex items-center gap-3 rounded-lg px-3 py-2.5 hover:bg-indigo-500/10';
    const iconCls = isActive ? 'w-5 h-5 text-indigo-500' : 'w-5 h-5 text-slate-500 dark:text-slate-400';
    const labelCls = isActive
      ? 'text-sm font-semibold flex-1 text-indigo-600 dark:text-indigo-400'
      : 'text-sm font-medium flex-1 text-slate-700 dark:text-slate-200';
    const badge = it.badge ? it.badge : '';
    const indicator = isActive ? '<span class="h-1.5 w-1.5 rounded-full bg-indigo-500"></span>' : '';
    return `<li><a href="${it.href}" class="${linkCls}">
      <i data-lucide="${it.icon}" class="${iconCls}"></i>
      <span class="${labelCls}">${it.label}</span>
      ${badge}${indicator}
    </a></li>`;
  }

  function renderSection(sec, isLast) {
    const items = sec.items.map(renderItem).join('');
    const sep = isLast ? '' : '<hr class="my-4 border-indigo-500/10" />';
    return `<div class="${isLast ? 'mb-2' : 'mb-6'}">
      <div class="flex items-center gap-2 px-3 py-2 font-semibold text-[0.65rem] uppercase tracking-[0.08em] text-slate-500 dark:text-slate-400">
        <span class="w-1 h-1 rounded-full bg-indigo-500 opacity-60"></span> ${sec.title}
      </div>
      <ul class="m-0 mt-1 list-none space-y-1 p-0">${items}</ul>
    </div>${sep}`;
  }

  const host = document.getElementById('sidebar');
  if (host) {
    host.innerHTML = sections.map((s, i) => renderSection(s, i === sections.length - 1)).join('');
    if (window.lucide) lucide.createIcons();
  }
})();
