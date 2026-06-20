// Shared sidebar for the Package Manager mockups. The active page is
// determined from the current document filename so every page can simply
// drop a <div id="sidebar"></div> and include this script.
(function () {
  const sections = [
    {
      title: 'Registry',
      items: [
        { href: 'package-format.html',     icon: 'package',         label: 'Package Format' },
        { href: 'storage-backend.html',    icon: 'database',        label: 'Storage Backend' },
        { href: 'semver-engine.html',      icon: 'git-commit',      label: 'Semver Engine' },
        { href: 'registry-api.html',       icon: 'server-cog',      label: 'Registry API' },
        { href: 'integrity-signatures.html', icon: 'shield-check',  label: 'Integrity & Sigs' },
      ],
    },
    {
      title: 'CLI',
      items: [
        { href: 'cli-core.html',           icon: 'terminal',        label: 'CLI Core' },
        { href: 'install-resolver.html',   icon: 'download-cloud',  label: 'Install',        badge: '<span class="text-[10px] mono text-emerald-500">4 deps</span>' },
        { href: 'publish-workflow.html',   icon: 'upload-cloud',    label: 'Publish' },
        { href: 'lock-file.html',          icon: 'file-lock-2',     label: 'Lock File' },
        { href: 'offline-cache.html',      icon: 'hard-drive',      label: 'Offline Cache' },
      ],
    },
    {
      title: 'Discover',
      items: [
        { href: 'search-browsing.html',    icon: 'search',          label: 'Search' },
        { href: 'package-detail.html',     icon: 'box',             label: 'Package Page' },
        { href: 'rankings.html',           icon: 'trophy',          label: 'Rankings',       badge: '<span class="text-[10px] mono text-amber-500">87</span>' },
        { href: 'vulnerabilities.html',    icon: 'shield-alert',    label: 'Vulnerabilities', badge: '<span class="text-[10px] px-1.5 rounded bg-rose-500/15 text-rose-600 dark:text-rose-400 font-semibold">3</span>' },
        { href: 'license-check.html',      icon: 'scale',           label: 'Licenses' },
      ],
    },
    {
      title: 'Enterprise',
      items: [
        { href: 'cicd-publishing.html',    icon: 'git-merge',       label: 'CI/CD Publish' },
        { href: 'deprecation.html',        icon: 'archive',         label: 'Deprecation' },
        { href: 'private-registry.html',   icon: 'lock',            label: 'Private Registry' },
        { href: 'scopes-teams.html',       icon: 'users-round',     label: 'Scopes & Teams' },
        { href: 'audit-log.html',          icon: 'scroll',          label: 'Audit Log' },
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
