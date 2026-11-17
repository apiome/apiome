import { describe, expect, it } from 'vitest';
import {
  calendarDay,
  planSentence,
  productSentence,
  toLifecycleNotices,
  type LifecycleRow,
} from '../lifecycle';

/** A lifecycle row, with overrides. */
function row(overrides: Partial<LifecycleRow> = {}): LifecycleRow {
  return {
    slug: 'payments',
    name: 'Payments',
    state: 'published',
    retire_at: null,
    deprecation_message: null,
    plan_slug: 'standard',
    plan_name: 'Standard',
    plan_retire_at: new Date('2027-03-31T00:00:00Z'),
    plan_deprecation_message: ' Move before March. ',
    successor_name: 'Premium',
    ...overrides,
  };
}

describe('product lifecycle on the changelog (APX-1.4)', () => {
  it('reads a calendar day from a Date or a string', () => {
    expect(calendarDay(new Date('2027-03-31T00:00:00Z'))).toBe('2027-03-31');
    expect(calendarDay('2027-06-30T00:00:00+00:00')).toBe('2027-06-30');
    expect(calendarDay(null)).toBeNull();
    expect(calendarDay('soon')).toBeNull();
  });

  it('groups plans under their product, once each', () => {
    const notices = toLifecycleNotices([
      row(),
      row(),
      row({ plan_slug: 'sandbox', plan_name: 'Sandbox', plan_retire_at: null, successor_name: null }),
      row({ slug: 'ledger', name: 'Ledger', state: 'deprecated', retire_at: '2027-06-30T00:00:00Z', plan_slug: null }),
    ]);
    expect(notices.map((n) => [n.productSlug, n.deprecated, n.plans.map((p) => p.slug)])).toEqual([
      ['payments', false, ['standard', 'sandbox']],
      ['ledger', true, []],
    ]);
    expect(notices[0].plans[0]).toEqual({
      slug: 'standard',
      name: 'Standard',
      retireOn: '2027-03-31',
      message: 'Move before March.',
      successorName: 'Premium',
    });
    expect(notices[1].retireOn).toBe('2027-06-30');
  });

  it('words the product and plan sentences', () => {
    const [payments, ledger] = toLifecycleNotices([
      row(),
      row({ slug: 'ledger', name: 'Ledger', state: 'deprecated', retire_at: null, plan_slug: null }),
    ]);
    expect(productSentence(payments)).toBeNull();
    expect(productSentence(ledger)).toBe('Ledger is deprecated.');
    expect(productSentence({ ...ledger, retireOn: '2027-06-30' })).toBe('Ledger is deprecated and retires on 2027-06-30.');
    expect(planSentence(payments.plans[0])).toBe(
      'The Standard plan is deprecated and retires on 2027-03-31. It takes no new subscriptions. Move to Premium; your key keeps working.',
    );
    expect(planSentence({ ...payments.plans[0], retireOn: null, successorName: null })).toBe(
      'The Standard plan is deprecated. It takes no new subscriptions.',
    );
  });
});
