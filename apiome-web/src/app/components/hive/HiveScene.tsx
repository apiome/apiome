"use client";

import { useEffect, useRef } from "react";

/**
 * A honeycomb "API hive": a faint hexagonal lattice where sparse cells slowly
 * breathe with light and occasional signals travel cell-to-cell — a picture of
 * an organization's suite of APIs, each a cell in one hive, talking to each
 * other. Canvas 2D (no WebGL), theme-aware, pointer-reactive, paused when
 * off-screen, and degraded to a single static frame under reduced motion.
 */

type Rgb = [number, number, number];

type Palette = {
  lattice: string;
  edgeGlow: Rgb;
  cellA: Rgb;
  cellB: Rgb;
  cellC: Rgb;
  fillAlpha: number;
  strokeAlpha: number;
};

const PALETTES: Record<"light" | "dark", Palette> = {
  light: {
    lattice: "rgba(24, 24, 27, 0.05)",
    edgeGlow: [79, 70, 229],
    cellA: [79, 70, 229], // indigo-600
    cellB: [37, 99, 235], // blue-600
    cellC: [147, 51, 234], // purple-600 (rare)
    fillAlpha: 0.085,
    strokeAlpha: 0.3,
  },
  dark: {
    lattice: "rgba(250, 250, 250, 0.045)",
    edgeGlow: [129, 140, 248],
    cellA: [96, 165, 250], // blue-400
    cellB: [129, 140, 248], // indigo-400
    cellC: [192, 132, 252], // purple-400 (rare)
    fillAlpha: 0.1,
    strokeAlpha: 0.38,
  },
};

type Cell = {
  x: number;
  y: number;
  col: number;
  row: number;
  phase: number;
  speed: number;
  breathes: boolean;
  color: Rgb;
};

type Pulse = {
  path: number[];
  start: number;
};

const pseudo = (i: number, s: number) => {
  // deterministic per-cell hash so the layout feels stable across renders
  const v = Math.sin(i * 12.9898 + s * 78.233) * 43758.5453;
  return v - Math.floor(v);
};

export default function HiveScene({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    const getTheme = (): "light" | "dark" =>
      document.documentElement.classList.contains("dark") ? "dark" : "light";

    let palette = PALETTES[getTheme()];

    const SQRT3 = Math.sqrt(3);
    let width = 0;
    let height = 0;
    let dpr = 1;
    let R = 42; // hex radius, center to corner (flat-top)
    let cells: Cell[] = [];
    let byCoord = new Map<string, number>();
    const lattice = document.createElement("canvas");

    const hexPath = (
      c: CanvasRenderingContext2D,
      x: number,
      y: number,
      r: number,
    ) => {
      for (let k = 0; k < 6; k++) {
        const a = (Math.PI / 3) * k;
        const px = x + r * Math.cos(a);
        const py = y + r * Math.sin(a);
        if (k === 0) c.moveTo(px, py);
        else c.lineTo(px, py);
      }
      c.closePath();
    };

    const buildGrid = () => {
      R = width < 640 ? 32 : 42;
      const colW = 1.5 * R;
      const rowH = SQRT3 * R;
      cells = [];
      byCoord = new Map();
      const cols = Math.ceil(width / colW) + 2;
      const rows = Math.ceil(height / rowH) + 2;
      let i = 0;
      for (let col = -1; col <= cols; col++) {
        const odd = ((col % 2) + 2) % 2 === 1;
        for (let row = -1; row <= rows; row++) {
          const x = col * colW;
          const y = row * rowH + (odd ? rowH / 2 : 0);
          const breathes = pseudo(i, 3) > 0.84;
          const pick = pseudo(i, 4);
          cells.push({
            x,
            y,
            col,
            row,
            phase: pseudo(i, 1) * Math.PI * 2,
            speed: 0.35 + pseudo(i, 2) * 0.4,
            breathes,
            color:
              pick < 0.5
                ? palette.cellA
                : pick < 0.85
                  ? palette.cellB
                  : palette.cellC,
          });
          byCoord.set(`${col},${row}`, i);
          i++;
        }
      }
    };

    const neighborsOf = (cell: Cell): number[] => {
      const odd = ((cell.col % 2) + 2) % 2 === 1;
      const deltas = odd
        ? [
            [1, 0],
            [-1, 0],
            [0, 1],
            [0, -1],
            [1, 1],
            [-1, 1],
          ]
        : [
            [1, 0],
            [-1, 0],
            [0, 1],
            [0, -1],
            [1, -1],
            [-1, -1],
          ];
      const out: number[] = [];
      for (const [dc, dr] of deltas) {
        const idx = byCoord.get(`${cell.col + dc},${cell.row + dr}`);
        if (idx !== undefined) out.push(idx);
      }
      return out;
    };

    const drawLattice = () => {
      lattice.width = Math.round(width * dpr);
      lattice.height = Math.round(height * dpr);
      const lctx = lattice.getContext("2d");
      if (!lctx) return;
      lctx.scale(dpr, dpr);
      lctx.clearRect(0, 0, width, height);
      lctx.strokeStyle = palette.lattice;
      lctx.lineWidth = 1;
      lctx.beginPath();
      for (const cell of cells) hexPath(lctx, cell.x, cell.y, R);
      lctx.stroke();
    };

    const applyPalette = () => {
      palette = PALETTES[getTheme()];
      for (let i = 0; i < cells.length; i++) {
        const pick = pseudo(i, 4);
        cells[i].color =
          pick < 0.5
            ? palette.cellA
            : pick < 0.85
              ? palette.cellB
              : palette.cellC;
      }
      drawLattice();
    };

    // ── Interaction ────────────────────────────────────────────────────────
    const pointer = { x: -1e4, y: -1e4, tx: -1e4, ty: -1e4 };
    const onPointer = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      pointer.tx = e.clientX - rect.left;
      pointer.ty = e.clientY - rect.top;
    };
    window.addEventListener("pointermove", onPointer, { passive: true });

    // ── Signals traveling through the hive ─────────────────────────────────
    const pulses: Pulse[] = [];
    const PULSE_STEP = 0.55; // seconds between cells lighting up
    const PULSE_SPAN = 1.4; // seconds a single cell stays lit
    let nextPulseAt = 2.5;

    const spawnPulse = (now: number) => {
      const candidates = cells.filter(
        (c) =>
          c.breathes &&
          c.x > R &&
          c.x < width - R &&
          c.y > R &&
          c.y < height - R,
      );
      if (!candidates.length) return;
      const startCell = candidates[Math.floor(Math.random() * candidates.length)];
      const path = [cells.indexOf(startCell)];
      let current = startCell;
      const visited = new Set(path);
      for (let step = 0; step < 4; step++) {
        const options = neighborsOf(current).filter((n) => !visited.has(n));
        if (!options.length) break;
        const next = options[Math.floor(Math.random() * options.length)];
        path.push(next);
        visited.add(next);
        current = cells[next];
      }
      if (path.length > 1) pulses.push({ path, start: now });
    };

    // ── Render loop ────────────────────────────────────────────────────────
    let raf = 0;
    let running = true;
    let t = 0;

    const drawCell = (cell: Cell, intensity: number) => {
      if (intensity <= 0.01) return;
      const [r, g, b] = cell.color;
      ctx.beginPath();
      hexPath(ctx, cell.x, cell.y, R);
      ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${palette.fillAlpha * Math.min(1, intensity)})`;
      ctx.fill();
      const [er, eg, eb] = palette.edgeGlow;
      ctx.strokeStyle = `rgba(${er}, ${eg}, ${eb}, ${palette.strokeAlpha * Math.min(1, intensity) * 0.55})`;
      ctx.lineWidth = 1;
      ctx.stroke();
    };

    const renderFrame = () => {
      ctx.clearRect(0, 0, width, height);
      ctx.drawImage(lattice, 0, 0, width, height);

      pointer.x += (pointer.tx - pointer.x) * 0.08;
      pointer.y += (pointer.ty - pointer.y) * 0.08;
      const pointerRadius = R * 4.5;

      // Per-cell pulse boost, keyed by cell index.
      const pulseBoost = new Map<number, number>();
      for (let p = pulses.length - 1; p >= 0; p--) {
        const pulse = pulses[p];
        const last = (pulse.path.length - 1) * PULSE_STEP + PULSE_SPAN;
        const age = t - pulse.start;
        if (age > last) {
          pulses.splice(p, 1);
          continue;
        }
        pulse.path.forEach((idx, step) => {
          const local = age - step * PULSE_STEP;
          if (local < 0 || local > PULSE_SPAN) return;
          const env = Math.sin((Math.PI * local) / PULSE_SPAN);
          pulseBoost.set(idx, Math.max(pulseBoost.get(idx) ?? 0, env * 1.6));
        });
      }

      for (let i = 0; i < cells.length; i++) {
        const cell = cells[i];
        let intensity = 0;

        if (cell.breathes) {
          const wave = 0.5 + 0.5 * Math.sin(t * cell.speed + cell.phase);
          intensity += wave * wave * 0.8; // eased so cells rest mostly dark
        }

        const dx = cell.x - pointer.x;
        const dy = cell.y - pointer.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < pointerRadius) {
          const f = 1 - dist / pointerRadius;
          intensity += f * f * 0.7;
        }

        const boost = pulseBoost.get(i);
        if (boost) intensity += boost;

        drawCell(cell, intensity);
      }
    };

    const loop = () => {
      if (!running) return;
      t += 0.016;
      if (t >= nextPulseAt && pulses.length < 2) {
        spawnPulse(t);
        nextPulseAt = t + 3 + Math.random() * 4;
      }
      renderFrame();
      raf = requestAnimationFrame(loop);
    };

    // ── Resize ─────────────────────────────────────────────────────────────
    const onResize = () => {
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      width = rect.width;
      height = rect.height;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      buildGrid();
      drawLattice();
      if (reduceMotion) renderFrame();
    };
    onResize();
    const ro = new ResizeObserver(onResize);
    ro.observe(canvas);

    const themeObserver = new MutationObserver(() => {
      applyPalette();
      if (reduceMotion) renderFrame();
    });
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    if (reduceMotion) {
      // A single quiet frame: lattice plus a few softly lit cells.
      t = 1.4;
      renderFrame();
    } else {
      loop();
    }

    // Pause when scrolled out of view or the tab is hidden.
    const io = new IntersectionObserver(
      ([entry]) => {
        const visible = entry.isIntersecting;
        if (visible && !running && !reduceMotion) {
          running = true;
          loop();
        } else if (!visible) {
          running = false;
          cancelAnimationFrame(raf);
        }
      },
      { threshold: 0 },
    );
    io.observe(canvas);

    const onVisibility = () => {
      if (document.hidden) {
        running = false;
        cancelAnimationFrame(raf);
      } else if (!reduceMotion) {
        running = true;
        loop();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      io.disconnect();
      ro.disconnect();
      themeObserver.disconnect();
      window.removeEventListener("pointermove", onPointer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return <canvas ref={canvasRef} className={className} aria-hidden />;
}
