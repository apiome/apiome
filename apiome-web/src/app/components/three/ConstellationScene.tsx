"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * A WebGL "data constellation": a slowly drifting field of glowing nodes,
 * connected by lines when they fall within range — a literal picture of
 * schemas, classes, and relationships finding one another. Theme-aware,
 * pointer-reactive, paused when off-screen, and degraded to a single static
 * frame when the user prefers reduced motion.
 */

type Palette = {
  node: THREE.Color;
  nodeBright: THREE.Color;
  line: THREE.Color;
  lineOpacity: number;
};

const PALETTES: Record<"light" | "dark", Palette> = {
  light: {
    node: new THREE.Color("#4f46e5"),
    nodeBright: new THREE.Color("#2563eb"),
    line: new THREE.Color("#6366f1"),
    lineOpacity: 0.16,
  },
  dark: {
    node: new THREE.Color("#60a5fa"),
    nodeBright: new THREE.Color("#a855f7"),
    line: new THREE.Color("#818cf8"),
    lineOpacity: 0.22,
  },
};

function makeSprite(): THREE.Texture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const g = ctx.createRadialGradient(
    size / 2,
    size / 2,
    0,
    size / 2,
    size / 2,
    size / 2,
  );
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.25, "rgba(255,255,255,0.9)");
  g.addColorStop(0.5, "rgba(255,255,255,0.35)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export default function ConstellationScene({
  className,
}: {
  className?: string;
}) {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    const COUNT = window.innerWidth < 640 ? 70 : 130;
    const BOUNDS = { x: 26, y: 16, z: 14 };
    const LINK_DIST = 5.4;
    const MAX_LINKS = COUNT * 8;

    const getTheme = (): "light" | "dark" =>
      document.documentElement.classList.contains("dark") ? "dark" : "light";

    let palette = PALETTES[getTheme()];

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      60,
      mount.clientWidth / mount.clientHeight,
      0.1,
      120,
    );
    camera.position.z = 30;

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const group = new THREE.Group();
    scene.add(group);

    // ── Nodes ──────────────────────────────────────────────────────────────
    const positions = new Float32Array(COUNT * 3);
    const velocities = new Float32Array(COUNT * 3);
    const colors = new Float32Array(COUNT * 3);
    const sizes = new Float32Array(COUNT);

    const pseudo = (i: number, s: number) => {
      // deterministic, no Math.random reliance for SSR-stability of layout feel
      const v = Math.sin(i * 12.9898 + s * 78.233) * 43758.5453;
      return v - Math.floor(v);
    };

    for (let i = 0; i < COUNT; i++) {
      positions[i * 3] = (pseudo(i, 1) - 0.5) * BOUNDS.x * 2;
      positions[i * 3 + 1] = (pseudo(i, 2) - 0.5) * BOUNDS.y * 2;
      positions[i * 3 + 2] = (pseudo(i, 3) - 0.5) * BOUNDS.z * 2;
      velocities[i * 3] = (pseudo(i, 4) - 0.5) * 0.012;
      velocities[i * 3 + 1] = (pseudo(i, 5) - 0.5) * 0.012;
      velocities[i * 3 + 2] = (pseudo(i, 6) - 0.5) * 0.012;
      const bright = pseudo(i, 7) > 0.78;
      const c = bright ? palette.nodeBright : palette.node;
      colors[i * 3] = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;
      sizes[i] = bright ? 1.5 + pseudo(i, 8) * 0.8 : 0.6 + pseudo(i, 9) * 0.6;
    }

    const nodeGeo = new THREE.BufferGeometry();
    nodeGeo.setAttribute(
      "position",
      new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage),
    );
    nodeGeo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    nodeGeo.setAttribute("size", new THREE.BufferAttribute(sizes, 1));

    const sprite = makeSprite();
    const nodeMat = new THREE.ShaderMaterial({
      uniforms: {
        uTexture: { value: sprite },
        uScale: { value: mount.clientHeight * 0.18 },
      },
      vertexShader: /* glsl */ `
        attribute float size;
        varying vec3 vColor;
        uniform float uScale;
        void main() {
          vColor = color;
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          gl_PointSize = size * (uScale / -mv.z);
          gl_Position = projectionMatrix * mv;
        }
      `,
      fragmentShader: /* glsl */ `
        uniform sampler2D uTexture;
        varying vec3 vColor;
        void main() {
          vec4 tex = texture2D(uTexture, gl_PointCoord);
          if (tex.a < 0.02) discard;
          gl_FragColor = vec4(vColor, tex.a);
        }
      `,
      transparent: true,
      depthWrite: false,
      vertexColors: true,
      blending: THREE.NormalBlending,
    });
    const points = new THREE.Points(nodeGeo, nodeMat);
    group.add(points);

    // ── Links ──────────────────────────────────────────────────────────────
    const linkPositions = new Float32Array(MAX_LINKS * 6);
    const linkColors = new Float32Array(MAX_LINKS * 6);
    const linkGeo = new THREE.BufferGeometry();
    linkGeo.setAttribute(
      "position",
      new THREE.BufferAttribute(linkPositions, 3).setUsage(
        THREE.DynamicDrawUsage,
      ),
    );
    linkGeo.setAttribute(
      "color",
      new THREE.BufferAttribute(linkColors, 3).setUsage(THREE.DynamicDrawUsage),
    );
    const linkMat = new THREE.LineBasicMaterial({
      transparent: true,
      opacity: palette.lineOpacity,
      vertexColors: true,
      depthWrite: false,
      blending: THREE.NormalBlending,
    });
    const links = new THREE.LineSegments(linkGeo, linkMat);
    group.add(links);

    const applyPalette = () => {
      palette = PALETTES[getTheme()];
      const colAttr = nodeGeo.getAttribute("color") as THREE.BufferAttribute;
      for (let i = 0; i < COUNT; i++) {
        const bright = pseudo(i, 7) > 0.78;
        const c = bright ? palette.nodeBright : palette.node;
        colAttr.setXYZ(i, c.r, c.g, c.b);
      }
      colAttr.needsUpdate = true;
      linkMat.opacity = palette.lineOpacity;
    };

    const themeObserver = new MutationObserver(applyPalette);
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    // ── Interaction ────────────────────────────────────────────────────────
    const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
    const onPointer = (e: PointerEvent) => {
      pointer.tx = (e.clientX / window.innerWidth - 0.5) * 2;
      pointer.ty = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    window.addEventListener("pointermove", onPointer, { passive: true });

    const rebuildLinks = () => {
      const posAttr = nodeGeo.getAttribute("position") as THREE.BufferAttribute;
      let n = 0;
      const linkDistSq = LINK_DIST * LINK_DIST;
      for (let i = 0; i < COUNT; i++) {
        const ax = posAttr.getX(i),
          ay = posAttr.getY(i),
          az = posAttr.getZ(i);
        for (let j = i + 1; j < COUNT; j++) {
          const dx = ax - posAttr.getX(j);
          const dy = ay - posAttr.getY(j);
          const dz = az - posAttr.getZ(j);
          const dSq = dx * dx + dy * dy + dz * dz;
          if (dSq < linkDistSq && n < MAX_LINKS) {
            const t = 1 - Math.sqrt(dSq) / LINK_DIST; // 0..1 closeness
            const o = n * 6;
            linkPositions[o] = ax;
            linkPositions[o + 1] = ay;
            linkPositions[o + 2] = az;
            linkPositions[o + 3] = posAttr.getX(j);
            linkPositions[o + 4] = posAttr.getY(j);
            linkPositions[o + 5] = posAttr.getZ(j);
            const cr = palette.line.r * t;
            const cg = palette.line.g * t;
            const cb = palette.line.b * t;
            linkColors[o] = cr;
            linkColors[o + 1] = cg;
            linkColors[o + 2] = cb;
            linkColors[o + 3] = cr;
            linkColors[o + 4] = cg;
            linkColors[o + 5] = cb;
            n++;
          }
        }
      }
      linkGeo.setDrawRange(0, n * 2);
      (linkGeo.getAttribute("position") as THREE.BufferAttribute).needsUpdate =
        true;
      (linkGeo.getAttribute("color") as THREE.BufferAttribute).needsUpdate =
        true;
    };

    const drift = () => {
      const posAttr = nodeGeo.getAttribute("position") as THREE.BufferAttribute;
      for (let i = 0; i < COUNT; i++) {
        let x = posAttr.getX(i) + velocities[i * 3];
        let y = posAttr.getY(i) + velocities[i * 3 + 1];
        let z = posAttr.getZ(i) + velocities[i * 3 + 2];
        if (x > BOUNDS.x || x < -BOUNDS.x) velocities[i * 3] *= -1;
        if (y > BOUNDS.y || y < -BOUNDS.y) velocities[i * 3 + 1] *= -1;
        if (z > BOUNDS.z || z < -BOUNDS.z) velocities[i * 3 + 2] *= -1;
        x = Math.max(-BOUNDS.x, Math.min(BOUNDS.x, x));
        y = Math.max(-BOUNDS.y, Math.min(BOUNDS.y, y));
        z = Math.max(-BOUNDS.z, Math.min(BOUNDS.z, z));
        posAttr.setXYZ(i, x, y, z);
      }
      posAttr.needsUpdate = true;
    };

    // ── Render loop ────────────────────────────────────────────────────────
    let raf = 0;
    let running = true;
    let t = 0;

    const renderFrame = () => {
      pointer.x += (pointer.tx - pointer.x) * 0.04;
      pointer.y += (pointer.ty - pointer.y) * 0.04;
      group.rotation.y = t * 0.04 + pointer.x * 0.35;
      group.rotation.x = Math.sin(t * 0.12) * 0.06 + pointer.y * 0.2;
      renderer.render(scene, camera);
    };

    const loop = () => {
      if (!running) return;
      t += 0.016;
      drift();
      rebuildLinks();
      renderFrame();
      raf = requestAnimationFrame(loop);
    };

    if (reduceMotion) {
      rebuildLinks();
      renderFrame();
    } else {
      loop();
    }

    // Pause when scrolled out of view.
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
    io.observe(mount);

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

    // ── Resize ─────────────────────────────────────────────────────────────
    const onResize = () => {
      if (!mount.clientWidth || !mount.clientHeight) return;
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
      nodeMat.uniforms.uScale.value = mount.clientHeight * 0.18;
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(mount);

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      io.disconnect();
      ro.disconnect();
      themeObserver.disconnect();
      window.removeEventListener("pointermove", onPointer);
      document.removeEventListener("visibilitychange", onVisibility);
      renderer.dispose();
      nodeGeo.dispose();
      linkGeo.dispose();
      nodeMat.dispose();
      linkMat.dispose();
      sprite.dispose();
      if (renderer.domElement.parentNode === mount) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, []);

  return <div ref={mountRef} className={className} aria-hidden />;
}
