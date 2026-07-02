'use client';

import * as Accordion from '@radix-ui/react-accordion';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';

type FAQItem = {
  question: string;
  answer: string;
};

export function FAQAccordion({ items }: { items: FAQItem[] }) {
  return (
    <Accordion.Root
      type="single"
      collapsible
      className="space-y-3"
      defaultValue="item-0"
    >
      {items.map((item, i) => (
        <Accordion.Item
          key={i}
          value={`item-${i}`}
          className={cn(
            'group overflow-hidden rounded-xl glass transition-colors',
            'data-[state=open]:ring-1 data-[state=open]:ring-blue-500/30',
          )}
        >
          <Accordion.Header>
            <Accordion.Trigger
              className={cn(
                'flex w-full items-center justify-between gap-4 px-6 py-5 text-left',
                'text-lg font-semibold text-zinc-900 dark:text-zinc-50',
                'transition-colors hover:bg-white/40 dark:hover:bg-white/5',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
              )}
            >
              <span>{item.question}</span>
              <ChevronDown
                className="h-5 w-5 shrink-0 text-zinc-500 transition-transform duration-300 group-data-[state=open]:rotate-180 dark:text-zinc-400"
                aria-hidden
              />
            </Accordion.Trigger>
          </Accordion.Header>
          <Accordion.Content
            className={cn(
              'overflow-hidden text-zinc-600 dark:text-zinc-400',
              'data-[state=open]:animate-accordion-down data-[state=closed]:animate-accordion-up',
            )}
          >
            <div className="px-6 pb-5 text-[15px] leading-relaxed">{item.answer}</div>
          </Accordion.Content>
        </Accordion.Item>
      ))}
    </Accordion.Root>
  );
}
