/* ==========================================================================
   Apiome "Hive" — round-3 facelift runtime (PROPOSALS_FACELIFT.md)
   --------------------------------------------------------------------------
   Loaded after hive.js by the proposals/facelift-*.html mockups.

     • Reads ?fx=rail,hex,… (or ?fx=all / ?fx=none) and sets <html data-fx="…">,
       which assets/facelift.css keys every idea on. Without a query string the
       last choice made on this device applies (localStorage "hive.facelift").
     • Listens for postMessage from the comparison viewer so an idea can be
       switched on and off live, the theme changed, and scrolling kept in step
       between the "before" and "after" frames.
     • Adds a "Facelift" switch to the mock bar (all ideas on / off).
     • Runs the two bits of motion CSS cannot: the rail pill that follows the
       pointer and the one-time count-up on stat numbers. Both respect the
       Preferences "Reduce motion" switch and prefers-reduced-motion.
   ========================================================================== */
(function () {
  'use strict';

  const ALL = ['rail', 'hex', 'type', 'layers', 'color', 'viz', 'timeline', 'voids', 'forms', 'motion', 'admin', 'themes'];
  const KEY = 'hive.facelift';
  const root = document.documentElement;
  const params = new URLSearchParams(location.search);
  let barButton = null; // the mock-bar switch, mounted once hive.js has drawn the bar

  function fromQuery(raw) {
    if (raw === 'all') return ALL.slice();
    if (raw === 'none' || raw === '') return [];
    return raw.split(',').map((s) => s.trim()).filter((s) => ALL.includes(s));
  }
  function initial() {
    if (params.has('fx')) return fromQuery(params.get('fx'));
    try { const s = localStorage.getItem(KEY); if (s != null) return fromQuery(s); } catch (e) { /* ignore */ }
    return [];
  }
  function apply(set, persist) {
    const list = ALL.filter((id) => set.includes(id));
    root.setAttribute('data-fx', list.join(' '));
    if (persist) { try { localStorage.setItem(KEY, list.join(',')); } catch (e) { /* ignore */ } }
    document.dispatchEvent(new CustomEvent('fx:change', { detail: { fx: list } }));
    syncBar();
  }
  function current() { return (root.getAttribute('data-fx') || '').split(/\s+/).filter(Boolean); }
  function reduced() { return root.getAttribute('data-motion') === 'reduce' || (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); }

  window.Facelift = {
    ALL,
    get: current,
    set(ids) { apply(ids, !params.has('fx')); },
    toggle(id) { const c = current(); apply(c.includes(id) ? c.filter((x) => x !== id) : c.concat(id), !params.has('fx')); },
    all() { apply(ALL, !params.has('fx')); },
    none() { apply([], !params.has('fx')); },
  };
  if (window.parent !== window) root.setAttribute('data-fx-embedded', '');
  apply(initial(), false);

  /* ---------- Messages from the comparison viewer ------------------------ */
  let lastSentY = -1;
  window.addEventListener('message', (e) => {
    const m = e.data || {};
    if (m.type === 'fx:set' && Array.isArray(m.set)) apply(m.set, false);
    else if (m.type === 'fx:theme' && window.Hive && m.theme) window.Hive.setTheme(m.theme);
    else if (m.type === 'fx:density' && window.Hive && m.density) window.Hive.setDensity(m.density);
    else if (m.type === 'fx:scroll' && typeof m.y === 'number') { lastSentY = m.y; window.scrollTo(0, m.y); }
    else if (m.type === 'fx:hover' && typeof m.x === 'number') movePillToPoint(m.x, m.y);
  });
  window.addEventListener('scroll', () => {
    if (window.parent === window) return;
    const y = Math.round(window.scrollY);
    if (y === lastSentY) return;
    lastSentY = y;
    window.parent.postMessage({ type: 'fx:scrolled', y, frame: window.name }, '*');
  }, { passive: true });

  /* ---------- Mock bar switch -------------------------------------------- */
  function syncBar() {
    if (!barButton) return;
    const on = current().length > 0;
    barButton.classList.toggle('is-on', on);
    barButton.setAttribute('aria-pressed', on);
    barButton.title = on ? 'Facelift on (all ideas) — click to see the shipped look' : 'Facelift off — click to apply every idea';
  }
  function mountBar() {
    const bar = document.querySelector('.mock-bar');
    if (!bar || barButton) return;
    const sep = document.createElement('span'); sep.className = 'sep';
    barButton = document.createElement('button');
    barButton.innerHTML = '<i data-lucide="sparkles"></i>Facelift';
    barButton.addEventListener('click', () => (current().length ? window.Facelift.none() : window.Facelift.all()));
    const first = bar.querySelector('a');
    bar.insertBefore(barButton, first ? first.nextSibling : null);
    bar.insertBefore(sep, barButton);
    const css = document.createElement('style');
    css.textContent = '.mock-bar button.is-on { background: var(--honey); color: #2A1F00; opacity: 1; }';
    document.head.appendChild(css);
    syncBar();
    if (window.Hive) window.Hive.icons();
  }

  /* ---------- Motion: the rail pill that follows the pointer ------------- */
  let pill = null;
  function mountPill() {
    const nav = document.querySelector('.rail__nav');
    if (!nav || pill) return;
    pill = document.createElement('span');
    pill.className = 'fx-pill';
    nav.appendChild(pill);
    const items = nav.querySelectorAll('.nav-item');
    items.forEach((it) => {
      it.addEventListener('pointerenter', () => moveTo(it));
    });
    nav.addEventListener('pointerleave', () => { pill.classList.remove('is-on'); });
  }
  function moveTo(el) {
    if (!pill || !current().includes('motion') || reduced()) return;
    const nav = el.closest('.rail__nav');
    const top = el.getBoundingClientRect().top - nav.getBoundingClientRect().top + nav.scrollTop;
    pill.style.transform = `translateY(${Math.round(top)}px)`;
    pill.classList.add('is-on');
  }
  function movePillToPoint(x, y) {
    const el = document.elementFromPoint(x, y);
    const item = el && el.closest ? el.closest('.rail__nav .nav-item') : null;
    if (item) moveTo(item); else if (pill) pill.classList.remove('is-on');
  }

  /* ---------- Motion: count-up on [data-count] ---------------------------- */
  let counted = false;
  function countUp() {
    if (counted || !current().includes('motion') || reduced()) return;
    counted = true;
    document.querySelectorAll('[data-count]').forEach((el) => {
      const target = parseFloat(el.getAttribute('data-count'));
      if (Number.isNaN(target)) return;
      const suffix = el.getAttribute('data-count-suffix') || '';
      const decimals = (String(el.getAttribute('data-count')).split('.')[1] || '').length;
      const start = performance.now(); const dur = 720;
      const fmt = (n) => n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
      const tick = (now) => {
        const t = Math.min(1, (now - start) / dur);
        const eased = 1 - Math.pow(1 - t, 3);
        el.firstChild && el.firstChild.nodeType === 3 ? (el.firstChild.nodeValue = fmt(target * eased) + suffix) : (el.textContent = fmt(target * eased) + suffix);
        if (t < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }
  document.addEventListener('fx:change', (e) => { if (e.detail.fx.includes('motion')) countUp(); });

  document.addEventListener('hive:mounted', () => { mountBar(); mountPill(); countUp(); });
})();
