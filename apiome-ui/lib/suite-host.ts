import type { LucideIcon } from 'lucide-react';
import { Palette, Route } from 'lucide-react';
import type { SuiteHomeCardIcon } from './suite-contract';

export type { SuiteHomeCard, SuiteNavItem } from './suite-contract';
export { getSuiteHomeCards, getSuiteNavItems } from '@suite/host';

export const SUITE_HOME_CARD_ICONS: Record<SuiteHomeCardIcon, LucideIcon> = {
  palette: Palette,
  route: Route,
};

export function resolveSuiteHomeCardIcon(icon: SuiteHomeCardIcon): LucideIcon {
  return SUITE_HOME_CARD_ICONS[icon];
}
