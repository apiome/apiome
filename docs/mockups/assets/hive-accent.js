/* ==========================================================================
   Apiome "Hive" — round-3 proposal runtime (colour & accent pass)
   --------------------------------------------------------------------------
   Loaded by proposals/accent-*.html BEFORE assets/hive.js (both deferred, so
   document order is execution order). It adds, on top of the shared shell:

     • capture switches on the query string — the hub page embeds each
       proposal in an <iframe> and the QA script screenshots them:
         ?page-only      render without the rail (the shipped screenshots in
                         apiome-docs are page-only at 1440 × 900)
         ?shot           hide every piece of mockup chrome
         ?theme=dark     pin the theme for this load (writes the shared
                         preference, so only the QA script uses it)
         ?rail=collapsed pin the rail state the same way
     • a "Before" bar (bottom-left) that overlays the shipped page's
       screenshot from apiome-docs/static/img/screens — press B to toggle;
     • a count-up on [data-countup] numbers (skipped under reduced motion);
     • HiveAccent.annot([...]) — the numbered-callout helper every round-2
       page re-implemented inline.

   Nothing in here is product code.
   ========================================================================== */
(function () {
  'use strict';
  const q = new URLSearchParams(location.search);
  const root = document.documentElement;

  /* ---------- capture switches (before hive.js mounts the shell) --------- */
  if (q.has('theme')) { try { localStorage.setItem('hive.theme', q.get('theme')); } catch (e) { /* ignore */ } }
  if (q.has('rail')) { try { localStorage.setItem('hive.rail', q.get('rail')); } catch (e) { /* ignore */ } }
  if (q.has('density')) { try { localStorage.setItem('hive.density', q.get('density')); } catch (e) { /* ignore */ } }
  if (q.has('shot')) root.setAttribute('data-shot', '');
  const pageOnly = q.has('page-only');
  document.addEventListener('DOMContentLoaded', () => {
    if (pageOnly) document.body.setAttribute('data-shell', 'bare');
  }, { once: true });

  /** Where apiome-docs keeps the shipped screenshots, relative to proposals/. */
  const SCREENS = '../../../apiome-docs/static/img/screens/';
  const reduce = () => root.getAttribute('data-motion') === 'reduce' || (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  const HiveAccent = window.HiveAccent = {
    /** Numbered callouts: [[selector, n, dx, dy], …]; shown by the Callouts button. */
    annot(list) {
      list.forEach(([sel, n, dx, dy]) => {
        const el = document.querySelector(sel); if (!el) return;
        const dot = document.createElement('span'); dot.className = 'mock-annot'; dot.textContent = n;
        if (!el.style.position) el.style.position = 'relative';
        dot.style.left = (dx == null ? -10 : dx) + 'px'; dot.style.top = (dy == null ? -10 : dy) + 'px';
        el.appendChild(dot);
      });
    },
    /** Animate every [data-countup] from 0 to its value (tabular digits keep the width). */
    countUp() {
      if (reduce() || root.hasAttribute('data-shot')) return;
      document.querySelectorAll('[data-countup]').forEach((el) => {
        const raw = el.getAttribute('data-countup') || el.textContent;
        const target = parseFloat(raw.replace(/[^0-9.]/g, '')); if (isNaN(target)) return;
        const fmt = (v) => raw.includes(',') ? Math.round(v).toLocaleString('en-US') : String(Math.round(v));
        const t0 = performance.now(), dur = 640;
        const tick = (t) => { const p = Math.min(1, (t - t0) / dur); const e = 1 - Math.pow(1 - p, 3); el.textContent = fmt(target * e); if (p < 1) requestAnimationFrame(tick); };
        el.textContent = '0'; requestAnimationFrame(tick);
      });
    },
  };

  /* ---------- "Before" overlay + bar --------------------------------------- */
  function beforeSrc() {
    const b = document.body;
    const theme = root.getAttribute('data-theme') === 'dark' || ['nord', 'darcula', 'solarized', 'blueprint', 'high-contrast'].includes(root.getAttribute('data-theme') || '') ? 'dark' : 'light';
    const explicit = b.getAttribute('data-before-' + theme);
    if (explicit) return explicit;
    const id = b.getAttribute('data-before'); if (!id) return null;
    return SCREENS + id + '.' + theme + '.png';
  }
  function mountCompare() {
    const b = document.body;
    if (root.hasAttribute('data-shot') || !b.getAttribute('data-before') && !b.getAttribute('data-before-light')) return;
    const label = b.getAttribute('data-before-label') || 'shipped apiome-ui';
    const bar = document.createElement('div');
    bar.className = 'mock-compare'; bar.setAttribute('role', 'toolbar'); bar.setAttribute('aria-label', 'Before / after');
    bar.innerHTML = `<span class="lbl">Round 3 · colour &amp; accent</span><button type="button" data-compare><i data-lucide="images"></i>Show before<span class="kbd">B</span></button><a href="accent-pass.html"><i data-lucide="layout-list"></i>All pages</a>`;
    const ov = document.createElement('div');
    ov.className = 'compare-overlay'; ov.setAttribute('role', 'dialog'); ov.setAttribute('aria-label', 'Before: the shipped page');
    ov.innerHTML = `<div class="tag-before"><i data-lucide="history"></i>Before — ${label} · click or press B to return</div><img alt="The shipped page, as captured for the documentation" />`;
    document.body.appendChild(ov); document.body.appendChild(bar);
    const btn = bar.querySelector('[data-compare]');
    const set = (open) => {
      if (open) { const src = beforeSrc(); if (!src) return; ov.querySelector('img').src = src; }
      ov.classList.toggle('is-open', open);
      btn.innerHTML = open ? `<i data-lucide="sparkles"></i>Show after<span class="kbd">B</span>` : `<i data-lucide="images"></i>Show before<span class="kbd">B</span>`;
      if (window.Hive) Hive.icons();
    };
    btn.addEventListener('click', () => set(!ov.classList.contains('is-open')));
    ov.addEventListener('click', () => set(false));
    document.addEventListener('keydown', (e) => { if (e.key.toLowerCase() === 'b' && !/input|textarea|select/i.test(document.activeElement.tagName) && !e.metaKey && !e.ctrlKey) set(!ov.classList.contains('is-open')); });
    document.addEventListener('hive:prefs', () => { if (ov.classList.contains('is-open')) ov.querySelector('img').src = beforeSrc(); });
  }

  document.addEventListener('hive:mounted', () => { mountCompare(); HiveAccent.countUp(); if (window.Hive) Hive.icons(); });
})();
