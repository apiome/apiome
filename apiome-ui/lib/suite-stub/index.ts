/**
 * OSS default when no commercial @suite/host package is linked.
 * Returns empty registrations so the open-source build has no suite nav or home cards.
 */
import type { SuiteHomeCard, SuiteHostApi, SuiteNavItem } from '../suite-contract';

export function getSuiteNavItems(): SuiteNavItem[] {
  return [];
}

export function getSuiteHomeCards(): SuiteHomeCard[] {
  return [];
}

const suiteHostStub: SuiteHostApi = {
  getSuiteNavItems,
  getSuiteHomeCards,
};

export default suiteHostStub;
