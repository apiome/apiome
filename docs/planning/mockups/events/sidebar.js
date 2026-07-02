// Shared sidebar for Auditable Event System mockups. Active page = current filename.
(function () {
  const sections = [
    {
      title: 'Start here',
      items: [
        { href: 'index.html', icon: 'layout-grid', label: 'Hub' },
        { href: 'combinations.html', icon: 'table-2', label: 'Combination matrix' },
      ],
    },
    {
      title: 'Design',
      items: [
        { href: 'rules-bindings.html', icon: 'list-checks', label: 'Rules & bindings' },
        { href: 'workflow-canvas.html', icon: 'workflow', label: 'Workflow canvas', badge: '<span class="text-[10px] px-1.5 rounded bg-violet-500/15 text-violet-600 dark:text-violet-400 font-semibold">React Flow</span>' },
        { href: 'script-editor.html', icon: 'code-2', label: 'Event script IDE', badge: '<span class="text-[10px] px-1.5 rounded bg-fuchsia-500/15 text-fuchsia-600 dark:text-fuchsia-400 font-semibold">Monaco</span>' },
      ],
    },
    {
      title: 'Operate',
      items: [
        { href: 'audit-ledger.html', icon: 'scroll-text', label: 'Audit ledger' },
        { href: 'simulator.html', icon: 'play', label: 'Dry-run simulator' },
        { href: 'parallel-runs.html', icon: 'layers', label: 'Parallel runs' },
      ],
    },
    {
      title: 'Ecosystem',
      items: [
        { href: 'marketplace.html', icon: 'store', label: 'Action marketplace' },
      ],
    },
  ];

  const path = location.pathname.split('/').pop() || 'index.html';

  function renderItem(it) {
    const isActive = it.href === path;
    const linkCls = isActive
      ? 'flex items-center gap-3 rounded-lg px-3 py-2.5 border border-violet-200 dark:border-violet-700/70 bg-violet-500/10'
      : 'flex items-center gap-3 rounded-lg px-3 py-2.5 hover:bg-violet-500/10';
    const iconCls = isActive ? 'w-5 h-5 text-violet-500' : 'w-5 h-5 text-slate-500 dark:text-slate-400';
    const labelCls = isActive
      ? 'text-sm font-semibold flex-1 text-violet-600 dark:text-violet-400'
      : 'text-sm font-medium flex-1 text-slate-700 dark:text-slate-200';
    const badge = it.badge ? it.badge : '';
    const indicator = isActive ? '<span class="h-1.5 w-1.5 rounded-full bg-violet-500"></span>' : '';
    return `<li><a href="${it.href}" class="${linkCls}">
      <i data-lucide="${it.icon}" class="${iconCls}"></i>
      <span class="${labelCls}">${it.label}</span>
      ${badge}${indicator}
    </a></li>`;
  }

  function renderSection(sec, isLast) {
    const items = sec.items.map(renderItem).join('');
    const sep = isLast ? '' : '<hr class="my-4 border-violet-500/10" />';
    return `<div class="${isLast ? 'mb-2' : 'mb-6'}">
      <div class="flex items-center gap-2 px-3 py-2 font-semibold text-[0.65rem] uppercase tracking-[0.08em] text-slate-500 dark:text-slate-400">
        <span class="w-1 h-1 rounded-full bg-violet-500 opacity-60"></span> ${sec.title}
      </div>
      <ul class="m-0 mt-1 list-none space-y-1 p-0">${items}</ul>
    </div>${sep}`;
  }

  const host = document.getElementById('sidebar');
  if (host) {
    host.innerHTML = `
      <div class="mb-5 px-3">
        <p class="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400 font-semibold">Apiome Suite</p>
        <p class="text-sm font-bold text-slate-800 dark:text-slate-100 mt-0.5">Auditable Event System</p>
        <p class="text-[11px] text-slate-500 dark:text-slate-400 mt-1 leading-snug">Rules over imported &amp; live data · catalog + Python · parallel branches · immutable audit</p>
      </div>
      ${sections.map((s, i) => renderSection(s, i === sections.length - 1)).join('')}
      <div class="mt-6 px-3 pt-4 border-t border-violet-500/10">
        <a href="../monitoring/index.html" class="text-xs text-slate-500 hover:text-violet-600 dark:text-slate-400 dark:hover:text-violet-400 flex items-center gap-1.5">
          <i data-lucide="arrow-left" class="w-3.5 h-3.5"></i> Other mockup packs
        </a>
      </div>
    `;
  }
})();
