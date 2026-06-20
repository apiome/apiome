/**
 * Canvas density lab — model + render pipeline + binding.
 * Tweaked via DensityConfig (microscopic knobs). Export/import JSON.
 */
(function () {
  'use strict';

  /** @typedef {'overview'|'structure'|'detail'} SemanticZoom */
  /** @typedef {'off'|'deps'|'churn'} HeatMode */
  /** @typedef {'minimal'|'pinned'|'required'|'required+pinned'} PropCanvasPolicy */

  /**
   * Default tuning — safe clone for reset.
   */
  const DEFAULT_CONFIG = () => ({
    semanticZoom: /** @type {SemanticZoom} */ ('structure'),
    focusHops: 2,
    dimStrength: 0.78,
    brightBoost: 1,
    heat: /** @type {HeatMode} */ ('off'),
    heatIntensity: 0.55,
    mapViewport: { l: 12, t: 10, w: 46, h: 42 },
    mapSyncLod: true,
    clutterCount: 48,
    clutterPitchPx: 10,
    clutterOpacityMin: 0.15,
    clutterOpacityMax: 0.38,
    edgeFocusOpacity: 0.92,
    edgeDimOpacity: 0.22,
    nestedDashOpacity: 0.65,
    maxPropsInline: 5,
    overviewPad: 8,
    detailSatelliteRadius: 52,
    showPathSummaries: true,
    propCanvasPolicy: /** @type {PropCanvasPolicy} */ ('minimal'),
    pinsClass: { invoice: true, address: false },
    pinsProp: { primary_invoice_id: true, id: false, workspace_id: false },
    selection: /** @type {'customer'|'address'|'get-customers'} */ ('customer'),
  });

  let cfg = DEFAULT_CONFIG();

  const GRAPH = {
    schemas: [
      {
        id: 'customer',
        name: 'Customer',
        domain: 'customers',
        x: 60,
        y: 60,
        w: 220,
        version: 'v2.1',
        props: [
          { id: 'id', line: 'id : uuid', required: true, pinDefault: false },
          { id: 'workspace_id', line: 'workspace_id : uuid', required: true, pinDefault: false },
          { id: 'name', line: 'name : string', required: false, pinDefault: false },
          { id: 'email', line: 'email : email', required: false, pinDefault: false },
          { id: 'addresses', line: 'addresses : Address[]', required: false, pinDefault: false },
          { id: 'primary_invoice_id', line: 'primary_invoice_id : uuid → Invoice', required: false, pinDefault: true },
          { id: 'billing_address', line: 'billing_address : Address', required: false, pinDefault: false },
          { id: 'created_at', line: 'created_at : datetime', required: false, pinDefault: false },
        ],
        hiddenHint: '3 properties hidden',
      },
      {
        id: 'address',
        name: 'Address',
        domain: 'customers',
        x: 60,
        y: 270,
        w: 220,
        version: '',
        props: [
          { id: 'street', line: 'street : string', required: false },
          { id: 'city', line: 'city : string', required: false },
          { id: 'postal', line: 'postal : string', required: false },
          { id: 'country', line: 'country : iso3166', required: false },
        ],
        hiddenHint: '',
      },
      {
        id: 'contactmethod',
        name: 'ContactMethod',
        domain: 'customers',
        x: 60,
        y: 420,
        w: 220,
        version: '',
        props: [
          { id: 'kind', line: 'kind : email | sms', required: false },
          { id: 'value', line: 'value : string', required: false },
        ],
        hiddenHint: '',
      },
    ],
    paths: [
      {
        id: 'get-customers',
        method: 'GET',
        path: '/customers',
        summary: 'List customers · paginated · filterable',
        codes: '200·400·401',
        x: 540,
        y: 60,
        w: 380,
        h: 56,
        consumes: ['customer'],
        selectedDot: true,
      },
      {
        id: 'post-customers',
        method: 'POST',
        path: '/customers',
        summary: 'Create customer · validates with Customer schema',
        codes: '201·400·409',
        x: 540,
        y: 135,
        w: 380,
        h: 56,
        consumes: ['customer'],
      },
      {
        id: 'get-customer-id',
        method: 'GET',
        path: '/customers/{id}',
        summary: 'Read one · returns Customer with addresses[]',
        codes: '200·404',
        x: 540,
        y: 210,
        w: 380,
        h: 56,
        consumes: ['customer', 'address'],
      },
      {
        id: 'del-customer-id',
        method: 'DEL',
        path: '/customers/{id}',
        summary: 'Cascades to Address, ContactMethod',
        codes: '204·404·409',
        x: 540,
        y: 285,
        w: 380,
        h: 56,
        consumes: ['customer', 'address', 'contactmethod'],
      },
    ],
    schemaEdges: [{ from: 'customer', to: 'address', label: 'addresses[]', dashed: true }],
    combinedEdges: [
      { from: 'customer', to: 'get-customers', nested: false },
      { from: 'customer', to: 'post-customers', nested: false },
      { from: 'customer', to: 'get-customer-id', nested: false },
      { from: 'customer', to: 'del-customer-id', nested: false },
      { from: 'address', to: 'get-customer-id', nested: true },
      { from: 'address', to: 'del-customer-id', nested: true },
    ],
  };

  const adjacency = () => {
    const m = new Map();
    const add = (a, b) => {
      if (!m.has(a)) m.set(a, new Set());
      m.get(a).add(b);
    };
    GRAPH.combinedEdges.forEach((e) => {
      add(e.from, e.to);
      add(e.to, e.from);
    });
    GRAPH.schemaEdges.forEach((e) => {
      add(e.from, e.to);
      add(e.to, e.from);
    });
    return m;
  };

  const ADJ = adjacency();

  function focusRootId() {
    if (cfg.selection === 'get-customers') return 'get-customers';
    return cfg.selection;
  }

  function computeFocusSet() {
    const root = focusRootId();
    const out = new Set([root]);
    const pins = new Set();
    // Demo graph has no Invoice class node; pin stands in as an anchored operation consumer.
    if (cfg.pinsClass.invoice) pins.add('post-customers');
    if (cfg.pinsClass.address) pins.add('address');
    pins.forEach((p) => out.add(p));

    let frontier = [root];
    for (let h = 0; h < cfg.focusHops; h++) {
      const next = [];
      frontier.forEach((id) => {
        const nbr = ADJ.get(id);
        if (!nbr) return;
        nbr.forEach((t) => {
          if (!out.has(t)) {
            out.add(t);
            next.push(t);
          }
        });
      });
      frontier = next;
    }
    return out;
  }

  function propVisibleOnCanvas(schemaId, prop) {
    if (cfg.semanticZoom === 'overview') return false;
    const pol = cfg.propCanvasPolicy;
    if (pol === 'minimal') return false;
    if (pol === 'pinned') return !!cfg.pinsProp[prop.id];
    if (pol === 'required') return !!prop.required;
    if (pol === 'required+pinned') return !!prop.required || !!cfg.pinsProp[prop.id];
    return false;
  }

  function schemaCardHeight(schema, linesShown) {
    const header = 28;
    const row = 18;
    const tail = schema.hiddenHint ? 22 : 12;
    return header + linesShown * row + tail;
  }

  function renderGhosts(container) {
    const field = document.getElementById('ghostField');
    if (!field) return;
    field.innerHTML = '';
    field.style.opacity = String(cfg.dimStrength * 0.55);
    field.style.backgroundSize = `${cfg.clutterPitchPx}px ${cfg.clutterPitchPx}px`;

    const frag = document.createDocumentFragment();
    const seed = (i) => {
      const x = Math.sin(i * 12.9898) * 43758.5453;
      return x - Math.floor(x);
    };
    for (let i = 0; i < cfg.clutterCount; i++) {
      const el = document.createElement('div');
      const r = seed(i + 1);
      el.className =
        'absolute rounded-lg border border-stone-200/60 dark:border-stone-700/60 bg-white/30 dark:bg-stone-900/20';
      el.style.left = `${4 + seed(i + 2) * 88}%`;
      el.style.top = `${6 + seed(i + 3) * 78}%`;
      el.style.width = `${40 + seed(i + 4) * 90}px`;
      el.style.height = `${14 + seed(i + 5) * 22}px`;
      el.style.opacity = String(
        cfg.clutterOpacityMin + r * (cfg.clutterOpacityMax - cfg.clutterOpacityMin),
      );
      frag.appendChild(el);
    }
    field.appendChild(frag);
  }

  function renderSvg() {
    const svg = document.getElementById('mainSvg');
    if (!svg) return;

    const focus = computeFocusSet();
    const isFocused = (id) => focus.has(id);

    while (svg.firstChild) svg.removeChild(svg.firstChild);

    const dark = document.documentElement.classList.contains('dark');
    const fillHdr = dark ? '#78350f' : '#92400e';
    const fillMono = dark ? '#e7e5e4' : '#1f2937';
    const fillMuted = '#9ca3af';

    const NS = 'http://www.w3.org/2000/svg';

    function add(tag, attrs, parent = svg) {
      const el = document.createElementNS(NS, tag);
      Object.entries(attrs || {}).forEach(([k, v]) => el.setAttribute(k, String(v)));
      parent.appendChild(el);
      return el;
    }

    add('text', { x: 170, y: 32, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 700, fill: fillHdr });
    svg.lastChild.textContent = 'Schemas';
    add('text', { x: 780, y: 32, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 700, fill: fillHdr });
    svg.lastChild.textContent = 'Paths';
    add('line', {
      x1: 490,
      y1: 20,
      x2: 490,
      y2: 600,
      stroke: '#fcd34d',
      'stroke-dasharray': '4 4',
      opacity: 0.5,
    });

    function drawOverviewClusters() {
      add('rect', {
        x: 40,
        y: 70,
        width: 420,
        height: 200,
        rx: 14,
        fill: dark ? 'rgba(28,25,23,0.85)' : '#ffffff',
        stroke: '#f59e0b',
        'stroke-width': 2,
        opacity: isFocused('customer') ? 1 : 0.35,
      });
      add('text', { x: 58, y: 98, 'font-size': 13, 'font-weight': 700, fill: fillHdr });
      svg.lastChild.textContent = 'customers/';
      add('text', { x: 58, y: 118, 'font-size': 10, fill: fillMuted });
      svg.lastChild.textContent = '18 classes · schema cluster (LOD overview)';
      add('rect', {
        x: 520,
        y: 70,
        width: 420,
        height: 200,
        rx: 14,
        fill: dark ? 'rgba(28,25,23,0.85)' : '#ffffff',
        stroke: '#34d399',
        'stroke-width': 2,
        opacity: isFocused('get-customers') ? 1 : 0.35,
      });
      add('text', { x: 538, y: 98, 'font-size': 13, 'font-weight': 700, fill: fillHdr });
      svg.lastChild.textContent = 'paths · customers/';
      add('text', { x: 538, y: 118, 'font-size': 10, fill: fillMuted });
      svg.lastChild.textContent = '4 operations · consumption bundle';

      add('rect', {
        x: 40,
        y: 290,
        width: 420,
        height: 110,
        rx: 14,
        fill: dark ? 'rgba(28,25,23,0.75)' : '#ffffff',
        stroke: '#d6d3d1',
        'stroke-width': 1.5,
        opacity: 0.45,
      });
      add('text', { x: 58, y: 318, 'font-size': 11, fill: fillMuted });
      svg.lastChild.textContent = 'billing/ · shared/ · off-domain dimmed';

      add('rect', {
        x: 520,
        y: 290,
        width: 420,
        height: 110,
        rx: 14,
        fill: dark ? 'rgba(28,25,23,0.75)' : '#ffffff',
        stroke: '#d6d3d1',
        'stroke-width': 1.5,
        opacity: 0.45,
      });
    }

    function drawSchemaCard(s) {
      const foc = isFocused(s.id);
      const dimOp = foc ? 1 : 1 - cfg.dimStrength * 0.85;
      const strokeW = foc ? 2 : 1.3;

      let props = s.props;
      let hiddenNote = s.hiddenHint;
      let linesShown = props.length;

      if (cfg.semanticZoom === 'structure') {
        linesShown = Math.min(props.length, cfg.maxPropsInline);
        props = props.slice(0, linesShown);
        if (linesShown < s.props.length) hiddenNote = `${s.props.length - linesShown} properties hidden`;
        else hiddenNote = s.hiddenHint || '';
      } else if (cfg.semanticZoom === 'detail') {
        linesShown = props.length;
        hiddenNote = '';
      }

      const h = schemaCardHeight({ hiddenHint: hiddenNote }, linesShown);
      const g = add('g', {
        opacity: dimOp,
        'data-kind': 'schema',
        'data-id': s.id,
        style: 'cursor:pointer',
      });

      add(
        'rect',
        {
          x: s.x - cfg.overviewPad * 0,
          y: s.y,
          width: s.w,
          height: h,
          rx: 10,
          fill: dark ? '#292524' : '#ffffff',
          stroke: '#f59e0b',
          'stroke-width': strokeW,
        },
        g,
      );
      add(
        'rect',
        {
          x: s.x,
          y: s.y,
          width: s.w,
          height: 28,
          rx: 10,
          fill: dark ? 'rgba(180,83,9,0.35)' : '#fef3c7',
        },
        g,
      );
      const t1 = add(
        'text',
        { x: s.x + 14, y: s.y + 18, 'font-size': 12, 'font-weight': 700, fill: fillHdr },
        g,
      );
      t1.textContent = s.name;
      if (s.version) {
        add(
          'text',
          {
            x: s.x + s.w - 14,
            y: s.y + 18,
            'text-anchor': 'end',
            'font-size': 9,
            fill: fillHdr,
            'font-family': 'JetBrains Mono',
          },
          g,
        ).textContent = s.version;
      }

      let yy = s.y + 46;
      props.forEach((p) => {
        add(
          'text',
          {
            x: s.x + 14,
            y: yy,
            'font-size': 10,
            'font-family': 'JetBrains Mono',
            fill: fillMono,
          },
          g,
        ).textContent = p.line;
        yy += 18;
      });

      if (hiddenNote) {
        add(
          'text',
          {
            x: s.x + 14,
            y: yy + 4,
            'font-size': 9,
            fill: fillMuted,
            'font-style': 'italic',
          },
          g,
        ).textContent = hiddenNote;
      }

      if (cfg.semanticZoom === 'detail' && s.id === 'customer') {
        const cx = s.x + s.w / 2;
        const cy = s.y + h + 24;
        s.props.forEach((p, idx) => {
          if (!propVisibleOnCanvas(s.id, p)) return;
          const ang = (idx / Math.max(s.props.length, 1)) * Math.PI * 2;
          const px = cx + Math.cos(ang) * cfg.detailSatelliteRadius;
          const py = cy + Math.sin(ang) * (cfg.detailSatelliteRadius * 0.55);
          add('circle', { cx: px, cy: py, r: 6, fill: '#06b6d4', opacity: 0.35 }, g);
          add(
            'text',
            {
              x: px + 10,
              y: py + 3,
              'font-size': 9,
              'font-family': 'JetBrains Mono',
              fill: '#0891b2',
            },
            g,
          ).textContent = p.id + (p.required ? '*' : '');
          add('line', {
            x1: cx,
            y1: s.y + h,
            x2: px,
            y2: py,
            stroke: '#06b6d4',
            'stroke-width': 1,
            opacity: 0.35,
          });
        });
      }

      g.addEventListener('click', () => {
        cfg.selection = /** @type {'customer'} */ (s.id);
        syncFormFromCfg();
        renderAll();
      });
    }

    function drawPathCard(p) {
      const foc = isFocused(p.id);
      const dimOp = foc ? 1 : 1 - cfg.dimStrength * 0.85;
      const strokeW = p.selectedDot && cfg.selection === 'get-customers' ? 2.5 : foc ? 2 : 1.3;

      const methodColors = {
        GET: { bg: '#dcfce7', fg: '#065f46', stroke: '#10b981' },
        POST: { bg: '#fef3c7', fg: '#92400e', stroke: '#d97706' },
        PUT: { bg: '#dbeafe', fg: '#1e40af', stroke: '#3b82f6' },
        DEL: { bg: '#fee2e2', fg: '#991b1b', stroke: '#ef4444' },
      };
      const mc = methodColors[p.method] || methodColors.GET;

      const g = add('g', {
        opacity: dimOp,
        'data-kind': 'path',
        'data-id': p.id,
        style: 'cursor:pointer',
      });

      add(
        'rect',
        {
          x: p.x,
          y: p.y,
          width: p.w,
          height: p.h,
          rx: 10,
          fill: dark ? '#292524' : '#ffffff',
          stroke: mc.stroke,
          'stroke-width': strokeW,
        },
        g,
      );
      const darkBand =
        p.method === 'GET'
          ? 'rgba(16,185,129,0.15)'
          : p.method === 'POST'
            ? 'rgba(245,158,11,0.15)'
            : p.method === 'DEL'
              ? 'rgba(239,68,68,0.15)'
              : 'rgba(59,130,246,0.15)';
      add(
        'rect',
        {
          x: p.x,
          y: p.y,
          width: 64,
          height: p.h,
          rx: 10,
          fill: dark ? darkBand : mc.bg,
          opacity: 1,
        },
        g,
      );
      add(
        'text',
        {
          x: p.x + 32,
          y: p.y + p.h / 2 + 4,
          'text-anchor': 'middle',
          'font-size': 11,
          'font-weight': 700,
          fill: mc.fg,
          'font-family': 'JetBrains Mono',
        },
        g,
      ).textContent = p.method;

      add(
        'text',
        {
          x: p.x + 76,
          y: p.y + 24,
          'font-size': 12,
          'font-weight': 600,
          fill: fillMono,
          'font-family': 'JetBrains Mono',
        },
        g,
      ).textContent = p.path;

      if (cfg.showPathSummaries && cfg.semanticZoom !== 'overview') {
        add(
          'text',
          {
            x: p.x + 76,
            y: p.y + 42,
            'font-size': 9,
            fill: '#6b7280',
          },
          g,
        ).textContent = p.summary;
      }

      add(
        'text',
        {
          x: p.x + p.w - 14,
          y: p.y + 24,
          'text-anchor': 'end',
          'font-size': 9,
          'font-family': 'JetBrains Mono',
          fill: mc.stroke,
        },
        g,
      ).textContent = p.codes;

      if (p.selectedDot) {
        add('circle', {
          cx: p.x,
          cy: p.y + p.h / 2,
          r: 4,
          fill: '#f59e0b',
        });
      }

      g.addEventListener('click', () => {
        cfg.selection = /** @type {'get-customers'} */ (p.id);
        syncFormFromCfg();
        renderAll();
      });
    }

    function drawEdges() {
      const baseOp = (id) => (isFocused(id) ? cfg.edgeFocusOpacity : cfg.edgeDimOpacity);

      GRAPH.schemaEdges.forEach((e) => {
        const from = GRAPH.schemas.find((s) => s.id === e.from);
        const to = GRAPH.schemas.find((s) => s.id === e.to);
        if (!from || !to) return;
        const y1 = from.y + 120;
        const y2 = to.y + 40;
        const op = Math.min(baseOp(e.from), baseOp(e.to));
        add('path', {
          d: `M${from.x + from.w} ${y1} C ${from.x + from.w + 40} ${y1} ${to.x + to.w + 40} ${y2} ${from.x + from.w} ${y2}`,
          stroke: '#fbbf24',
          'stroke-width': 1.5,
          fill: 'none',
          'stroke-dasharray': e.dashed ? '2 3' : 'none',
          opacity: op * cfg.nestedDashOpacity,
        });
      });

      GRAPH.combinedEdges.forEach((e) => {
        const sc = GRAPH.schemas.find((s) => s.id === e.from);
        const pt = GRAPH.paths.find((p) => p.id === e.to);
        if (!sc || !pt) return;
        const sx = sc.x + sc.w;
        const sy = sc.y + 70;
        const tx = pt.x;
        const ty = pt.y + pt.h / 2;
        const op = Math.min(baseOp(e.from), baseOp(e.to));
        add('path', {
          d: `M${sx} ${sy} C ${sx + 120} ${sy} ${tx - 120} ${ty} ${tx} ${ty}`,
          stroke: e.nested ? '#fb7185' : '#f59e0b',
          'stroke-width': e.nested ? 1.5 : 2,
          fill: 'none',
          'stroke-dasharray': e.nested ? '3 3' : 'none',
          opacity: op * (e.nested ? cfg.nestedDashOpacity : 1),
        });
      });
    }

    if (cfg.semanticZoom === 'overview') {
      drawOverviewClusters();
    } else {
      GRAPH.schemas.forEach(drawSchemaCard);
      GRAPH.paths.forEach(drawPathCard);
      drawEdges();
    }

    const legendY = 380;
    add('rect', {
      x: 540,
      y: legendY,
      width: 380,
      height: cfg.semanticZoom === 'overview' ? 56 : 80,
      rx: 10,
      fill: dark ? 'rgba(120,53,15,0.2)' : '#fffbeb',
      stroke: '#fcd34d',
    });
    add('text', {
      x: 554,
      y: legendY + 22,
      'font-size': 10,
      'font-weight': 700,
      fill: fillHdr,
    }).textContent =
      cfg.semanticZoom === 'overview'
        ? 'Overview LOD · clusters replace cards'
        : 'Combined lens · edges show consumption';

    if (cfg.semanticZoom !== 'overview') {
      add('line', { x1: 554, y1: legendY + 38, x2: 584, y2: legendY + 38, stroke: '#f59e0b', 'stroke-width': 2 });
      add('text', { x: 592, y: legendY + 42, 'font-size': 10, fill: fillMono }).textContent =
        'direct schema in request/response';
      add('line', {
        x1: 554,
        y1: legendY + 58,
        x2: 584,
        y2: legendY + 58,
        stroke: '#fb7185',
        'stroke-width': 1.5,
        'stroke-dasharray': '3 3',
      });
      add('text', { x: 592, y: legendY + 62, 'font-size': 10, fill: fillMono }).textContent =
        'nested via parent class';
    }
  }

  function renderMinimap() {
    const rect = document.getElementById('mapViewportRect');
    if (!rect) return;
    const v = cfg.mapViewport;
    rect.style.left = `${v.l}%`;
    rect.style.top = `${v.t}%`;
    rect.style.width = `${v.w}%`;
    rect.style.height = `${v.h}%`;

    const heat = document.getElementById('mapHeat');
    if (heat) {
      heat.className = 'absolute inset-0 pointer-events-none rounded-xl';
      if (cfg.heat === 'deps')
        heat.style.background = `radial-gradient(circle at 30% 30%, rgba(52,211,153,${cfg.heatIntensity}), transparent 55%)`;
      else if (cfg.heat === 'churn')
        heat.style.background = `radial-gradient(circle at 72% 38%, rgba(248,113,113,${cfg.heatIntensity}), transparent 55%)`;
      else heat.style.background = 'transparent';
    }
  }

  function renderInspector() {
    const schemaPanel = document.getElementById('inspectorSchema');
    const pathPanel = document.getElementById('inspectorPath');
    if (!schemaPanel || !pathPanel) return;

    const isPath = cfg.selection === 'get-customers';
    schemaPanel.classList.toggle('hidden', isPath);
    pathPanel.classList.toggle('hidden', !isPath);

    const metaPath = document.getElementById('inspectorSelectionMeta');
    const metaSchema = document.getElementById('inspectorSelectionMetaSchema');
    if (metaPath) {
      metaPath.textContent =
        'Path operation · consumption edges respect focus + LOD (microscope tunables).';
    }
    if (metaSchema) {
      metaSchema.textContent =
        'Schema class · properties primarily edited in inspector; pin fields to promote satellites in Detail LOD.';
    }

    document.querySelectorAll('.tree-sel').forEach((el) => {
      el.classList.remove('ring-2', 'ring-amber-500', 'ring-offset-1', 'ring-offset-white', 'dark:ring-offset-stone-900');
    });
    const treeSel =
      cfg.selection === 'get-customers'
        ? document.querySelector('[data-select-path="get-customers"]')
        : document.querySelector(`[data-select-schema="${cfg.selection}"]`);
    if (treeSel) {
      treeSel.classList.add('ring-2', 'ring-amber-500', 'ring-offset-1', 'ring-offset-white', 'dark:ring-offset-stone-900');
    }

    const pinRows = document.getElementById('inspectorPinRows');
    if (pinRows) {
      pinRows.innerHTML = '';
      const cust = GRAPH.schemas.find((s) => s.id === 'customer');
      if (cust) {
        cust.props.forEach((p) => {
          const row = document.createElement('label');
          row.className = 'flex items-center gap-2 text-[11px] py-1 border-b border-amber-100 dark:border-stone-800';
          const cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.checked = !!cfg.pinsProp[p.id];
          cb.addEventListener('change', () => {
            cfg.pinsProp[p.id] = cb.checked;
            syncFormFromCfg();
            renderAll();
          });
          row.appendChild(cb);
          const span = document.createElement('span');
          span.className = 'mono flex-1 truncate';
          span.textContent = p.line.split(':')[0].trim();
          row.appendChild(span);
          pinRows.appendChild(row);
        });
      }
    }

    document.getElementById('statusSelection') &&
      (document.getElementById('statusSelection').textContent = isPath
        ? 'GET /customers'
        : 'Customer');

    const lod = document.getElementById('statusLod');
    if (lod) lod.textContent = cfg.semanticZoom;

    const metrics = document.getElementById('metricsReadout');
    if (metrics) {
      const foc = computeFocusSet();
      metrics.textContent = [
        `focus:n=${foc.size}`,
        `hops=${cfg.focusHops}`,
        `dim=${cfg.dimStrength.toFixed(2)}`,
        `ghosts=${cfg.clutterCount}`,
        `heat=${cfg.heat}`,
      ].join(' · ');
    }
  }

  function syncFormFromCfg() {
    const q = (id) => document.getElementById(id);
    const setVal = (id, v) => {
      const el = q(id);
      if (el) el.value = v;
    };
    const setChk = (id, v) => {
      const el = q(id);
      if (el) el.checked = v;
    };

    document.querySelectorAll('[data-zoom]').forEach((b) => {
      b.classList.toggle('seg-active', b.getAttribute('data-zoom') === cfg.semanticZoom);
    });

    setVal('inpFocusHops', cfg.focusHops);
    setVal('inpDim', cfg.dimStrength);
    setVal('inpBright', cfg.brightBoost);
    setVal('inpHeatInt', cfg.heatIntensity);
    setVal('inpMapL', cfg.mapViewport.l);
    setVal('inpMapT', cfg.mapViewport.t);
    setVal('inpMapW', cfg.mapViewport.w);
    setVal('inpMapH', cfg.mapViewport.h);
    setVal('inpClutter', cfg.clutterCount);
    setVal('inpPitch', cfg.clutterPitchPx);
    setVal('inpGhostMin', cfg.clutterOpacityMin);
    setVal('inpGhostMax', cfg.clutterOpacityMax);
    setVal('inpEdgeF', cfg.edgeFocusOpacity);
    setVal('inpEdgeD', cfg.edgeDimOpacity);
    setVal('inpNestOp', cfg.nestedDashOpacity);
    setVal('inpMaxProps', cfg.maxPropsInline);
    setVal('inpSatRad', cfg.detailSatelliteRadius);
    setVal('inpOverviewPad', cfg.overviewPad);

    const heat = q('inpHeat');
    if (heat) heat.value = cfg.heat;

    const pol = q('inpPropPol');
    if (pol) pol.value = cfg.propCanvasPolicy;

    const sel = q('inpSelection');
    if (sel) sel.value = cfg.selection;

    setChk('chkPathSum', cfg.showPathSummaries);
    setChk('chkMapSync', cfg.mapSyncLod);

    setChk('pinInvoice', cfg.pinsClass.invoice);
    setChk('pinAddress', cfg.pinsClass.address);

    const ta = q('cfgJson');
    if (ta) ta.value = JSON.stringify(cfg, null, 2);
  }

  function applyFormToCfg() {
    const q = (id) => document.getElementById(id);
    const num = (id, fallback) => {
      const el = q(id);
      if (!el || el.value === '') return fallback;
      const n = parseFloat(el.value);
      return Number.isFinite(n) ? n : fallback;
    };
    const int = (id, fallback) => Math.round(num(id, fallback));

    cfg.focusHops = Math.max(0, Math.min(4, int('inpFocusHops', cfg.focusHops)));
    cfg.dimStrength = Math.max(0, Math.min(1, num('inpDim', cfg.dimStrength)));
    cfg.brightBoost = Math.max(0.5, Math.min(1.5, num('inpBright', cfg.brightBoost)));
    cfg.heatIntensity = Math.max(0, Math.min(1, num('inpHeatInt', cfg.heatIntensity)));
    cfg.mapViewport = {
      l: Math.max(0, Math.min(88, num('inpMapL', cfg.mapViewport.l))),
      t: Math.max(0, Math.min(88, num('inpMapT', cfg.mapViewport.t))),
      w: Math.max(8, Math.min(92, num('inpMapW', cfg.mapViewport.w))),
      h: Math.max(8, Math.min(92, num('inpMapH', cfg.mapViewport.h))),
    };
    cfg.clutterCount = Math.max(0, Math.min(160, int('inpClutter', cfg.clutterCount)));
    cfg.clutterPitchPx = Math.max(6, Math.min(24, int('inpPitch', cfg.clutterPitchPx)));
    cfg.clutterOpacityMin = Math.max(0, Math.min(1, num('inpGhostMin', cfg.clutterOpacityMin)));
    cfg.clutterOpacityMax = Math.max(0, Math.min(1, num('inpGhostMax', cfg.clutterOpacityMax)));
    cfg.edgeFocusOpacity = Math.max(0, Math.min(1, num('inpEdgeF', cfg.edgeFocusOpacity)));
    cfg.edgeDimOpacity = Math.max(0, Math.min(1, num('inpEdgeD', cfg.edgeDimOpacity)));
    cfg.nestedDashOpacity = Math.max(0, Math.min(1, num('inpNestOp', cfg.nestedDashOpacity)));
    cfg.maxPropsInline = Math.max(0, Math.min(12, int('inpMaxProps', cfg.maxPropsInline)));
    cfg.detailSatelliteRadius = Math.max(24, Math.min(120, int('inpSatRad', cfg.detailSatelliteRadius)));
    cfg.overviewPad = Math.max(0, Math.min(24, int('inpOverviewPad', cfg.overviewPad)));

    const heat = q('inpHeat');
    if (heat) cfg.heat = /** @type {HeatMode} */ (heat.value);

    const pol = q('inpPropPol');
    if (pol) cfg.propCanvasPolicy = /** @type {PropCanvasPolicy} */ (pol.value);

    const sel = q('inpSelection');
    if (sel) cfg.selection = /** @type {'customer'|'address'|'get-customers'} */ (sel.value);

    const ps = q('chkPathSum');
    if (ps) cfg.showPathSummaries = ps.checked;

    const ms = q('chkMapSync');
    if (ms) cfg.mapSyncLod = ms.checked;

    cfg.pinsClass.invoice = !!q('pinInvoice')?.checked;
    cfg.pinsClass.address = !!q('pinAddress')?.checked;
  }

  function lodPresetViewport() {
    if (!cfg.mapSyncLod) return;
    if (cfg.semanticZoom === 'overview') Object.assign(cfg.mapViewport, { l: 18, t: 38, w: 64, h: 44 });
    else if (cfg.semanticZoom === 'structure')
      Object.assign(cfg.mapViewport, { l: 12, t: 10, w: 46, h: 42 });
    else Object.assign(cfg.mapViewport, { l: 8, t: 8, w: 52, h: 56 });
  }

  function renderAll() {
    applyFormToCfg();
    lodPresetViewport();
    syncFormFromCfg();
    renderGhosts();
    renderSvg();
    renderMinimap();
    renderInspector();
    if (window.lucide) lucide.createIcons();
  }

  function bind() {
    document.querySelectorAll('[data-zoom]').forEach((btn) => {
      btn.addEventListener('click', () => {
        cfg.semanticZoom = /** @type {SemanticZoom} */ (btn.getAttribute('data-zoom'));
        renderAll();
      });
    });

    [
      'inpFocusHops',
      'inpDim',
      'inpBright',
      'inpHeat',
      'inpHeatInt',
      'inpMapL',
      'inpMapT',
      'inpMapW',
      'inpMapH',
      'inpClutter',
      'inpPitch',
      'inpGhostMin',
      'inpGhostMax',
      'inpEdgeF',
      'inpEdgeD',
      'inpNestOp',
      'inpMaxProps',
      'inpSatRad',
      'inpOverviewPad',
      'inpPropPol',
      'inpSelection',
    ].forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('change', () => renderAll());
      el.addEventListener('input', () => renderAll());
    });

    document.getElementById('chkPathSum')?.addEventListener('change', () => renderAll());
    document.getElementById('chkMapSync')?.addEventListener('change', () => renderAll());
    document.getElementById('pinInvoice')?.addEventListener('change', () => renderAll());
    document.getElementById('pinAddress')?.addEventListener('change', () => renderAll());

    document.getElementById('btnReset')?.addEventListener('click', () => {
      cfg = DEFAULT_CONFIG();
      renderAll();
    });

    document.getElementById('btnApplyJson')?.addEventListener('click', () => {
      const ta = document.getElementById('cfgJson');
      if (!ta) return;
      try {
        const next = JSON.parse(ta.value);
        cfg = { ...DEFAULT_CONFIG(), ...next };
        renderAll();
      } catch (e) {
        alert('Invalid JSON: ' + (e && e.message));
      }
    });

    document.getElementById('btnCopyJson')?.addEventListener('click', async () => {
      const ta = document.getElementById('cfgJson');
      if (!ta) return;
      try {
        await navigator.clipboard.writeText(ta.value);
      } catch {
        ta.select();
        document.execCommand('copy');
      }
    });

    document.getElementById('btnSyncTree')?.addEventListener('click', () => {
      renderAll();
    });
  }

  window.DensityLab = { renderAll, DEFAULT_CONFIG };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      bind();
      renderAll();
    });
  } else {
    bind();
    renderAll();
  }
})();
