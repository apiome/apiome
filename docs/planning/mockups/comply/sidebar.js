// Comply mockup — shared sidebar builder
// Usage: document.getElementById('sidebar').innerHTML = buildSidebar('dashboard');
function buildSidebar(active) {
  const nav = [
    {
      label: 'Overview',
      items: [
        { id: 'dashboard',       href: 'dashboard.html',       icon: 'layout-dashboard', label: 'Dashboard' },
      ],
    },
    {
      label: 'Data Classification',
      items: [
        { id: 'field-tagger',    href: 'field-tagger.html',    icon: 'tag',              label: 'Field Tagger' },
        { id: 'data-map',        href: 'data-map.html',        icon: 'map',              label: 'Data Map' },
      ],
    },
    {
      label: 'Regulatory Mapping',
      items: [
        { id: 'framework-mapper',href: 'framework-mapper.html',icon: 'git-merge',        label: 'Framework Mapper' },
        { id: 'gap-analysis',    href: 'gap-analysis.html',    icon: 'alert-triangle',   label: 'Gap Analysis' },
      ],
    },
    {
      label: 'Evidence & Reporting',
      items: [
        { id: 'evidence-report', href: 'evidence-report.html', icon: 'file-check-2',     label: 'Evidence Report' },
      ],
    },
    {
      label: 'Audit Management',
      items: [
        { id: 'audit-window',    href: 'audit-window.html',    icon: 'calendar-range',   label: 'Audit Windows' },
      ],
    },
  ];

  const sections = nav.map(section => {
    const items = section.items.map(item => {
      const isActive = item.id === active;
      const activeClasses = isActive
        ? 'border border-teal-200 dark:border-teal-700/70 bg-teal-500/10'
        : 'hover:bg-teal-500/10 transition-colors';
      const iconClasses = isActive ? 'text-teal-500' : 'text-slate-500 dark:text-slate-400';
      const textClasses  = isActive ? 'text-sm font-semibold flex-1 text-teal-600 dark:text-teal-400' : 'text-sm font-medium flex-1 text-slate-700 dark:text-slate-200';
      const dot = isActive ? '<span class="h-1.5 w-1.5 rounded-full bg-teal-500"></span>' : '';
      return `<li><a href="${item.href}" class="flex items-center gap-3 rounded-lg px-3 py-2.5 ${activeClasses}"><i data-lucide="${item.icon}" class="w-5 h-5 ${iconClasses}"></i><span class="${textClasses}">${item.label}</span>${dot}</a></li>`;
    }).join('');
    return `
      <div class="mb-5">
        <div class="flex items-center gap-2 px-3 py-2 font-semibold text-[0.65rem] uppercase tracking-[0.08em] text-slate-500 dark:text-slate-400">
          <span class="w-1 h-1 rounded-full bg-teal-500 opacity-60"></span> ${section.label}
        </div>
        <ul class="m-0 mt-1 list-none space-y-1 p-0">${items}</ul>
      </div>`;
  }).join('<hr class="my-3 border-teal-500/10" />');

  return `<div class="overflow-auto p-4 h-full">${sections}</div>`;
}
