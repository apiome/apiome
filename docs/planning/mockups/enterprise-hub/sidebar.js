// Shared sidebar for the Enterprise Hub mockups. The active page is
// determined from the current document filename so every page can simply
// drop a <div id="sidebar"></div> and include this script.
(function () {
  const sections = [
    {
      title: 'Tenants',
      items: [
        { href: 'tenant-overview.html',     icon: 'layout-dashboard',  label: 'Overview' },
        { href: 'provisioning-wizard.html', icon: 'wand-sparkles',     label: 'Provisioning' },
        { href: 'tenant-health.html',       icon: 'heart-pulse',       label: 'Health',         badge: '<span class="text-[10px] px-1.5 rounded bg-rose-500/15 text-rose-600 dark:text-rose-400 font-semibold">1</span>' },
        { href: 'schema-sharing.html',      icon: 'share-2',           label: 'Schema Sharing' },
        { href: 'tenant-config.html',       icon: 'sliders-horizontal',label: 'Configuration' },
        { href: 'tenant-lifecycle.html',    icon: 'refresh-cw',        label: 'Lifecycle' },
      ],
    },
    {
      title: 'Cost',
      items: [
        { href: 'usage-tracking.html',      icon: 'database-zap',      label: 'Usage Tracking' },
        { href: 'chargeback-reports.html',  icon: 'file-spreadsheet',  label: 'Chargeback' },
        { href: 'budget-alerts.html',       icon: 'bell-ring',         label: 'Budgets',        badge: '<span class="text-[10px] px-1.5 rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 font-semibold">3</span>' },
        { href: 'cost-optimization.html',   icon: 'sparkles',          label: 'Optimization' },
        { href: 'usage-analytics.html',     icon: 'line-chart',        label: 'Analytics' },
      ],
    },
    {
      title: 'Governance',
      items: [
        { href: 'policy-engine.html',           icon: 'scroll-text',  label: 'Policies' },
        { href: 'compliance-dashboard.html',    icon: 'shield-check', label: 'Compliance',    badge: '<span class="text-[10px] mono text-amber-500">86%</span>' },
        { href: 'standardization-scoring.html', icon: 'trophy',       label: 'Scoring' },
        { href: 'best-practices.html',          icon: 'check-check',  label: 'Best Practices' },
        { href: 'violations.html',              icon: 'alert-octagon',label: 'Violations',    badge: '<span class="text-[10px] px-1.5 rounded bg-rose-500/15 text-rose-600 dark:text-rose-400 font-semibold">12</span>' },
      ],
    },
    {
      title: 'Catalog',
      items: [
        { href: 'service-catalog.html',  icon: 'library-big', label: 'Catalog' },
        { href: 'schema-reuse.html',     icon: 'copy-check',  label: 'Reuse' },
        { href: 'dependency-graph.html', icon: 'network',     label: 'Dependencies' },
        { href: 'team-directory.html',   icon: 'users',       label: 'Teams' },
        { href: 'marketplace.html',      icon: 'store',       label: 'Marketplace' },
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
