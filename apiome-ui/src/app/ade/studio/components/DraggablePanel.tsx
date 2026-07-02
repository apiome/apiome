'use client';

import * as React from 'react';
import { createPortal } from 'react-dom';
import { GripVertical } from 'lucide-react';

const STORAGE_PREFIX = 'apiome-draggable-panel-';
const DEFAULT_HEADER_HEIGHT = 40;
const Z_INDEX = 1100;

export interface DraggablePanelProps {
  children: React.ReactNode;
  /** Unique key for persisting position in localStorage */
  storageKey?: string;
  /** Initial position when no saved position exists */
  defaultPosition?: { left: number; top: number };
  /** Height of the header strip used as drag handle (px) */
  headerHeight?: number;
  className?: string;
}

function loadPosition(storageKey: string): { left: number; top: number } | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { left: number; top: number };
    if (typeof parsed?.left === 'number' && typeof parsed?.top === 'number') return parsed;
  } catch {
    // ignore
  }
  return null;
}

function savePosition(storageKey: string, position: { left: number; top: number }): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + storageKey, JSON.stringify(position));
  } catch {
    // ignore
  }
}

export default function DraggablePanel({
  children,
  storageKey,
  defaultPosition = { left: 20, top: 120 },
  headerHeight = DEFAULT_HEADER_HEIGHT,
  className = '',
}: DraggablePanelProps) {
  const saved = storageKey ? loadPosition(storageKey) : null;
  const [position, setPosition] = React.useState<{ left: number; top: number }>(
    () => saved ?? defaultPosition
  );
  const [isDragging, setIsDragging] = React.useState(false);
  const dragStart = React.useRef({ x: 0, y: 0, left: 0, top: 0 });
  const positionRef = React.useRef(position);
  positionRef.current = position;

  const handleMouseDown = React.useCallback(
    (e: React.MouseEvent) => {
      if ((e.target as HTMLElement).closest('button, [role="button"], a')) return;
      e.preventDefault();
      setIsDragging(true);
      dragStart.current = {
        x: e.clientX,
        y: e.clientY,
        left: position.left,
        top: position.top,
      };
    },
    [position]
  );

  React.useEffect(() => {
    if (!isDragging) return;

    const onMove = (e: MouseEvent) => {
      const dx = e.clientX - dragStart.current.x;
      const dy = e.clientY - dragStart.current.y;
      setPosition({
        left: Math.max(0, dragStart.current.left + dx),
        top: Math.max(0, dragStart.current.top + dy),
      });
    };

    const onUp = () => {
      setIsDragging(false);
      if (storageKey) savePosition(storageKey, positionRef.current);
    };

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [isDragging, storageKey]);

  const panelContent = (
    <div
      className={`rounded-xl border border-gray-200/80 dark:border-gray-700/80 bg-white/95 dark:bg-gray-800/95 shadow-lg overflow-hidden ${className}`.trim()}
      style={{
        position: 'fixed',
        left: position.left,
        top: position.top,
        zIndex: Z_INDEX,
      }}
    >
      <div className="relative flex min-w-0">
        {/* Grip inside the panel (left edge of the window) */}
        <div
          role="presentation"
          onMouseDown={handleMouseDown}
          className="shrink-0 flex items-center justify-center w-9 cursor-grab active:cursor-grabbing hover:bg-black/5 dark:hover:bg-white/5 transition-colors border-r border-gray-200/80 dark:border-gray-700/80"
          style={{ minHeight: headerHeight }}
          title="Drag to move panel"
        >
          <GripVertical className="w-4 h-4 text-gray-400 dark:text-gray-500" />
        </div>
        {/* Panel content: remove left border/radius so it blends with the grip column */}
        <div className="min-w-0 flex-1 [&>*]:rounded-l-none [&>*]:border-l-0">
          {children}
        </div>
      </div>
    </div>
  );

  // Portal to document.body so the panel is not clipped by ancestor overflow-hidden (canvas container)
  if (typeof document !== 'undefined') {
    return createPortal(panelContent, document.body);
  }
  return panelContent;
}
