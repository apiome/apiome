// Shared sidebar for the Data Playground mockups. The active page is
// determined from the current document filename so every page can simply
// drop a <div id="sidebar"></div> and include this script.
(function () {
  const sections = [
    {
      title: 'Provisioning',
      items: [
        { href: 'environment-dashboard.html', icon: 'layout-dashboard', label: 'Dashboard',     badge: '<span class="text-[10px] px-1.5 rounded bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-semibold">3</span>' },
        { href: 'provisioning-flow.html',     icon: 'wand-sparkles',    label: 'New Sandbox' },
        { href: 'sample-data-library.html',   icon: 'database',         label: 'Sample Data' },
        { href: 'lifecycle-manager.html',     icon: 'timer',            label: 'Lifecycle' },
        { href: 'isolation-security.html',    icon: 'shield-check',     label: 'Isolation' },
      ],
    },
    {
      title: 'Workspace',
      items: [
        { href: 'schema-editor.html',         icon: 'code-2',           label: 'Schema Editor' },
        { href: 'promote-to-project.html',    icon: 'send',             label: 'Promote' },
        { href: 'ab-comparison.html',         icon: 'columns-2',        label: 'A/B Compare' },
        { href: 'perf-test.html',             icon: 'gauge',            label: 'Perf Test' },
        { href: 'validation-playground.html', icon: 'check-circle-2',   label: 'Validate' },
      ],
    },
    {
      title: 'Learn',
      items: [
        { href: 'scenarios.html',          icon: 'graduation-cap', label: 'Scenarios' },
        { href: 'guided-tutorial.html',    icon: 'list-checks',    label: 'Guided Tour' },
        { href: 'challenge-mode.html',     icon: 'swords',         label: 'Challenges',  badge: '<span class="text-[10px] px-1.5 rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 font-semibold">5</span>' },
        { href: 'cert-prep.html',          icon: 'award',          label: 'Cert Prep' },
        { href: 'community-scenarios.html',icon: 'users-round',    label: 'Community' },
      ],
    },
    {
      title: 'Collaborate',
      items: [
        { href: 'pair-editing.html',     icon: 'mouse-pointer-click', label: 'Pair Editing' },
        { href: 'share-link.html',       icon: 'link-2',              label: 'Share Links' },
        { href: 'session-recording.html',icon: 'video',               label: 'Recording' },
        { href: 'annotations.html',      icon: 'message-square',      label: 'Comments',  badge: '<span class="text-[10px] px-1.5 rounded bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 font-semibold">12</span>' },
        { href: 'fork-sandbox.html',     icon: 'git-branch',          label: 'Fork' },
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
