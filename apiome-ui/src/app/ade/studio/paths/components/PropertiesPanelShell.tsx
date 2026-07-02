'use client';

import * as React from 'react';
import { X } from 'lucide-react';
import { useSidebarTokens } from '../../../../components/sidebar/sidebar-theme';
import { pathsTheme, PROPERTIES_PANEL_WIDTH_PX } from './paths-theme';

interface PropertiesPanelShellProps {
  /** Icon rendered inside the small accent badge. */
  icon: React.ReactNode;
  /** Primary header label. */
  title: string;
  /** Optional secondary line (path, context). */
  subtitle?: React.ReactNode;
  /** Optional close handler. When provided, renders a close button. */
  onClose?: () => void;
  /** Optional left-aligned leading element in the header (e.g. back button). */
  headerLeading?: React.ReactNode;
  /** Optional right-aligned slot inside the header (before the close button). */
  headerActions?: React.ReactNode;
  /** Width of the panel in pixels. Defaults to 360 (matches sidebar). */
  width?: number;
  /** Optional toolbar rendered directly below the header (filters, tabs). */
  toolbar?: React.ReactNode;
  /** Footer pinned to the bottom (primary action, etc.). */
  footer?: React.ReactNode;
  /** Body content (scrollable). */
  children: React.ReactNode;
  /** Extra className for the outer aside. */
  className?: string;
  /** Override scrolling behavior for the body. Defaults to true. */
  bodyScroll?: boolean;
}

/**
 * Right-side properties panel shell. Mirrors the SidebarShell vocabulary
 * (icon badge header, hairline-divided body, pinned footer) but anchored
 * to the right edge with a left border.
 *
 * Using this shell across all three properties panels (Operation /
 * Parameter / Response) removes three separate bespoke wrappers and
 * aligns the Paths section to the Linear/Vercel look used by the
 * sidebar.
 */
export default function PropertiesPanelShell({
  icon,
  title,
  subtitle,
  onClose,
  headerLeading,
  headerActions,
  width = PROPERTIES_PANEL_WIDTH_PX,
  toolbar,
  footer,
  children,
  className,
  bodyScroll = true,
}: PropertiesPanelShellProps) {
  const tokens = useSidebarTokens();

  return (
    <aside
      className={[
        'shrink-0 flex flex-col h-full relative overflow-hidden',
        'border-l',
        pathsTheme.surface,
        pathsTheme.border,
        className ?? '',
      ].join(' ')}
      style={{ width, minWidth: width }}
    >
      <div
        className={[
          'shrink-0 flex items-center gap-3 px-3 border-b',
          tokens.headerHeight,
          pathsTheme.border,
        ].join(' ')}
      >
        {headerLeading != null && <div className="shrink-0">{headerLeading}</div>}
        <div
          className={[
            'shrink-0 w-7 h-7 rounded-md flex items-center justify-center',
            pathsTheme.iconBadge,
          ].join(' ')}
        >
          <span className="[&>svg]:w-3.5 [&>svg]:h-3.5">{icon}</span>
        </div>
        <div className="min-w-0 flex-1">
          <div
            className={[
              'text-[13px] font-semibold leading-tight truncate',
              pathsTheme.textPrimary,
            ].join(' ')}
          >
            {title}
          </div>
          {subtitle != null && (
            <div
              className={[
                'text-[11px] leading-tight truncate mt-0.5 font-mono',
                pathsTheme.textSecondary,
              ].join(' ')}
            >
              {subtitle}
            </div>
          )}
        </div>
        {headerActions != null && (
          <div className="shrink-0 flex items-center gap-1">{headerActions}</div>
        )}
        {onClose != null && (
          <button
            type="button"
            onClick={onClose}
            className={[
              'shrink-0 rounded-md p-1.5 transition-colors',
              pathsTheme.textTertiary,
              'hover:text-slate-700 dark:hover:text-slate-200',
              pathsTheme.hover,
            ].join(' ')}
            aria-label="Close panel"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {toolbar != null && (
        <div
          className={[
            'shrink-0 px-3 py-2 border-b',
            pathsTheme.borderSoft,
          ].join(' ')}
        >
          {toolbar}
        </div>
      )}

      <div
        className={[
          'flex-1 min-h-0 flex flex-col',
          bodyScroll ? 'overflow-y-auto' : 'overflow-hidden',
        ].join(' ')}
      >
        {children}
      </div>

      {footer != null && (
        <div
          className={[
            'shrink-0 px-3 py-2.5 border-t',
            pathsTheme.border,
            pathsTheme.surface,
          ].join(' ')}
        >
          {footer}
        </div>
      )}
    </aside>
  );
}

/**
 * Default body padding wrapper. Use when you want content inside the
 * scrollable body to inherit the same padding rhythm the sidebar uses.
 */
export function PropertiesPanelBody({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={['px-3 py-3 flex flex-col gap-3', className ?? ''].join(' ')}>{children}</div>;
}
