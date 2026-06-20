// Shared sidebar for the Multi-Protocol mockups. The active page is
// determined from the current document filename so every page can simply
// drop a <div id="sidebar"></div> and include this script.
(function () {
  const sections = [
    {
      title: 'GraphQL',
      items: [
        { href: 'schema-editor.html',      icon: 'file-code-2',  label: 'Schema Editor' },
        { href: 'operations-builder.html', icon: 'list-tree',    label: 'Operations' },
        { href: 'graphql-playground.html', icon: 'play-circle',  label: 'Playground' },
        { href: 'federation.html',         icon: 'git-merge',    label: 'Federation' },
      ],
    },
    {
      title: 'Protobuf · gRPC',
      items: [
        { href: 'protobuf-designer.html', icon: 'boxes',          label: 'Messages' },
        { href: 'grpc-services.html',     icon: 'radio-tower',    label: 'Services' },
        { href: 'proto-generation.html',  icon: 'package-plus',   label: 'Code Gen' },
        { href: 'grpc-testing.html',      icon: 'flask-conical',  label: 'Testing',     badge: '<span class="text-[10px] px-1.5 rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 font-semibold">2</span>' },
      ],
    },
    {
      title: 'AsyncAPI',
      items: [
        { href: 'asyncapi-editor.html',         icon: 'cable',          label: 'Channels' },
        { href: 'event-patterns.html',          icon: 'workflow',       label: 'Patterns' },
        { href: 'streaming-integration.html',   icon: 'plug-zap',       label: 'Brokers' },
        { href: 'channel-testing.html',         icon: 'send',           label: 'Test & Simulate' },
      ],
    },
    {
      title: 'Conversion · Gateway',
      items: [
        { href: 'schema-translation.html',     icon: 'arrow-left-right', label: 'Translate' },
        { href: 'cross-protocol-gateway.html', icon: 'shuffle',          label: 'Gateway' },
        { href: 'protocol-auth.html',          icon: 'shield-key',       label: 'Auth & Negotiation' },
        { href: 'conversion-testing.html',     icon: 'beaker',           label: 'Round-Trip' },
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
