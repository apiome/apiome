'use client';

import * as React from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { cn } from '../../../../../lib/utils';
import type { McpDetailTab } from '../../ade/dashboard/mcp/mcpUiPrimitives';

/**
 * `<DetailTabs>` — the endpoint detail tab shell. Unlike the segmented {@link Tabs} primitive, this
 * is the mockup's underline strip: a bottom border with each tab as an underline-on-active link,
 * the active tab inked in brand indigo. Built on Radix tabs so it stays keyboard-accessible and
 * controllable. The canonical seven-tab set lives in {@link MCP_DETAIL_TABS}; a screen may render
 * the full set or any subset it has content for.
 */
const DetailTabs = TabsPrimitive.Root;

const DetailTabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      '-mb-px border-b-2 border-transparent px-3.5 py-2.5 text-sm font-medium transition-colors',
      'text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:rounded-sm',
      'disabled:pointer-events-none disabled:opacity-40',
      'data-[state=active]:border-indigo-500 data-[state=active]:font-semibold',
      'data-[state=active]:text-indigo-700 dark:data-[state=active]:text-indigo-300',
      className,
    )}
    {...props}
  />
));
DetailTabsTrigger.displayName = 'DetailTabsTrigger';

export interface DetailTabsListProps
  extends React.ComponentPropsWithoutRef<typeof TabsPrimitive.List> {
  /**
   * When provided, the strip renders one trigger per tab automatically (default
   * {@link MCP_DETAIL_TABS}). Omit `items` and pass children to compose triggers by hand.
   */
  items?: readonly McpDetailTab[];
  /** Restrict an auto-rendered strip to these tab values, preserving the canonical order. */
  only?: readonly string[];
}

const DetailTabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  DetailTabsListProps
>(({ className, items, only, children, ...props }, ref) => {
  const autoItems = items ? items.filter((tab) => !only || only.includes(tab.value)) : null;
  return (
    <TabsPrimitive.List
      ref={ref}
      className={cn(
        'flex flex-wrap items-center gap-1 border-b border-gray-200 dark:border-gray-700',
        className,
      )}
      {...props}
    >
      {autoItems
        ? autoItems.map((tab) => (
            <DetailTabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
            </DetailTabsTrigger>
          ))
        : children}
    </TabsPrimitive.List>
  );
});
DetailTabsList.displayName = 'DetailTabsList';

const DetailTabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      'mt-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:rounded-md',
      className,
    )}
    {...props}
  />
));
DetailTabsContent.displayName = 'DetailTabsContent';

export { DetailTabs, DetailTabsList, DetailTabsTrigger, DetailTabsContent };
