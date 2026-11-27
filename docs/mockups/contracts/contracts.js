/* Contracts mockups — the three behaviours hive.js does not own. Mockup-only. */
(function () {
  document.addEventListener('click', function (e) {
    // Option cards: one active per radiogroup; an option can also reveal its own panel.
    var opt = e.target.closest('.ct-opt');
    if (opt) {
      var group = opt.closest('[role="radiogroup"]');
      if (group) group.querySelectorAll('.ct-opt').forEach(function (o) { o.classList.toggle('is-active', o === opt); });
      var show = opt.getAttribute('data-show');
      if (show && group) {
        var scope = document.getElementById(group.getAttribute('data-panels'));
        if (scope) scope.querySelectorAll('[data-opt-panel]').forEach(function (p) { p.hidden = p.getAttribute('data-opt-panel') !== show; });
      }
    }
    // Status strip: at most one detail row open (DESIGN.md §5.4).
    var chip = e.target.closest('.status-chip');
    if (chip) {
      var strip = chip.closest('.status-strip');
      var wasOpen = chip.classList.contains('is-open');
      strip.querySelectorAll('.status-chip').forEach(function (c) { c.classList.remove('is-open'); c.setAttribute('aria-expanded', 'false'); });
      strip.querySelectorAll('.status-strip__detail').forEach(function (d) { d.hidden = true; });
      if (!wasOpen) {
        chip.classList.add('is-open'); chip.setAttribute('aria-expanded', 'true');
        var d = strip.querySelector('[data-detail-for="' + chip.getAttribute('data-detail') + '"]');
        if (d) d.hidden = false;
      }
    }
    // Wizard: a step button or a Continue/Back button moves to a step.
    var go = e.target.closest('[data-step-go]');
    if (go) {
      var wiz = go.closest('[data-wizard]'); var n = Number(go.getAttribute('data-step-go'));
      wiz.querySelectorAll('.step').forEach(function (s, i) {
        s.classList.toggle('is-active', i + 1 === n); s.classList.toggle('is-done', i + 1 < n);
      });
      wiz.querySelectorAll('.step__line').forEach(function (l, i) { l.classList.toggle('is-done', i + 1 < n); });
      wiz.querySelectorAll('[data-step-panel]').forEach(function (p) { p.hidden = Number(p.getAttribute('data-step-panel')) !== n; });
    }
  });
})();
