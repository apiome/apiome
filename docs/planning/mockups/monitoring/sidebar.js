// Shared sidebar for the Monitoring & Observability mockups. The active
// page is derived from the current document filename so every page can
// drop a <div id="sidebar"></div> and include this script.
(function () {
  const sections = [
    {
      title: 'Performance',
      items: [
        { href: 'response-times.html',   icon: 'timer',         label: 'Response Times' },
        { href: 'error-rates.html',      icon: 'alert-triangle',label: 'Error Rates',      badge: '<span class="text-[10px] px-1.5 rounded bg-rose-500/15 text-rose-600 dark:text-rose-400 font-semibold">3</span>' },
        { href: 'request-volume.html',   icon: 'bar-chart-3',   label: 'Request Volume' },
        { href: 'system-resources.html', icon: 'cpu',           label: 'System Resources' },
        { href: 'active-users.html',     icon: 'users',         label: 'Active Users' },
        { href: 'status-page.html',      icon: 'signal',        label: 'Status Page' },
      ],
    },
    {
      title: 'Audit',
      items: [
        { href: 'audit-log.html',       icon: 'scroll-text',  label: 'Audit Log' },
        { href: 'audit-export.html',    icon: 'file-down',    label: 'Export' },
        { href: 'audit-alerts.html',    icon: 'bell-ring',    label: 'Alerts',     badge: '<span class="text-[10px] px-1.5 rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 font-semibold">2</span>' },
        { href: 'audit-retention.html', icon: 'archive',      label: 'Retention' },
      ],
    },
    {
      title: 'Logs',
      items: [
        { href: 'log-search.html',   icon: 'search',      label: 'Search' },
        { href: 'log-stream.html',   icon: 'terminal',    label: 'Live Stream' },
        { href: 'log-patterns.html', icon: 'scan-search', label: 'Patterns',  badge: '<span class="text-[10px] mono text-amber-500">14</span>' },
        { href: 'log-traces.html',   icon: 'git-branch',  label: 'Traces' },
        { href: 'siem-export.html',  icon: 'share-2',     label: 'SIEM Export' },
      ],
    },
    {
      title: 'Alerts',
      items: [
        { href: 'alert-rules.html',          icon: 'bell',                label: 'Rules' },
        { href: 'alert-channels.html',       icon: 'send',                label: 'Channels' },
        { href: 'escalation-policies.html',  icon: 'arrow-up-from-line',  label: 'Escalation' },
        { href: 'incidents.html',            icon: 'siren',               label: 'Incidents', badge: '<span class="text-[10px] px-1.5 rounded bg-rose-500/15 text-rose-600 dark:text-rose-400 font-semibold">1</span>' },
        { href: 'mttr-metrics.html',         icon: 'timer-reset',         label: 'MTTR / MTTA' },
      ],
    },
    {
      title: 'SLO',
      items: [
        { href: 'slo-definition.html', icon: 'target',     label: 'SLO Catalog' },
        { href: 'error-budget.html',   icon: 'gauge',      label: 'Error Budget', badge: '<span class="text-[10px] mono text-emerald-500">73%</span>' },
        { href: 'sla-reports.html',    icon: 'file-text',  label: 'SLA Reports' },
        { href: 'sla-history.html',    icon: 'line-chart', label: 'SLA History' },
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
