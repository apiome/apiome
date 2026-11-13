/**
 * The Deprecate dialog's pure model (#3482): initial values, validation, the request body and
 * which types may be offered as a replacement.
 */

import {
  MAX_DEPRECATION_MESSAGE,
  buildDeprecateRequestBody,
  deprecateFormFrom,
  replacementOptions,
  todayIsoDate,
  validateDeprecateForm,
  type DeprecateFormData,
} from '../src/app/ade/dashboard/primitives/primitiveLifecycleModel';

const TODAY = '2026-11-13';

const form = (overrides: Partial<DeprecateFormData> = {}): DeprecateFormData => ({
  sunsetDate: '',
  message: '',
  replacementId: '',
  ...overrides,
});

describe('deprecateFormFrom', () => {
  it('starts empty for an active type', () => {
    expect(deprecateFormFrom({})).toEqual({ sunsetDate: '', message: '', replacementId: '' });
  });

  it('pre-fills from a type that is already deprecated', () => {
    expect(
      deprecateFormFrom({
        sunset_date: '2027-01-31',
        deprecation_message: 'Use money-v2.',
        replacement_id: 'prim-9',
      })
    ).toEqual({ sunsetDate: '2027-01-31', message: 'Use money-v2.', replacementId: 'prim-9' });
  });

  it('reads null details as blank', () => {
    expect(
      deprecateFormFrom({ sunset_date: null, deprecation_message: null, replacement_id: null })
    ).toEqual(form());
  });
});

describe('todayIsoDate', () => {
  it('is the UTC calendar date, whatever the local clock says', () => {
    expect(todayIsoDate(new Date('2026-11-13T23:59:59Z'))).toBe('2026-11-13');
    expect(todayIsoDate(new Date('2026-11-14T00:00:00Z'))).toBe('2026-11-14');
  });
});

describe('validateDeprecateForm', () => {
  it('accepts an empty form: every field is optional', () => {
    expect(validateDeprecateForm(form(), TODAY)).toEqual({});
  });

  it('accepts today and any later date', () => {
    expect(validateDeprecateForm(form({ sunsetDate: TODAY }), TODAY)).toEqual({});
    expect(validateDeprecateForm(form({ sunsetDate: '2027-01-31' }), TODAY)).toEqual({});
  });

  it('refuses a sunset date in the past', () => {
    expect(validateDeprecateForm(form({ sunsetDate: '2026-11-12' }), TODAY)).toEqual({
      sunsetDate: 'The sunset date cannot be in the past.',
    });
  });

  it.each(['next spring', '2027-1-5', '31/01/2027', '2027-13-45'])(
    'refuses %s as a date',
    (value) => {
      expect(validateDeprecateForm(form({ sunsetDate: value }), TODAY).sunsetDate).toBe(
        'Enter a date as YYYY-MM-DD.'
      );
    }
  );

  it('caps the message, counting it trimmed', () => {
    const atLimit = 'x'.repeat(MAX_DEPRECATION_MESSAGE);

    expect(validateDeprecateForm(form({ message: `  ${atLimit}  ` }), TODAY)).toEqual({});
    expect(validateDeprecateForm(form({ message: `${atLimit}x` }), TODAY).message).toContain(
      `${MAX_DEPRECATION_MESSAGE} characters`
    );
  });
});

describe('buildDeprecateRequestBody', () => {
  it('sends blanks as null, which clears them on a deprecated type', () => {
    expect(buildDeprecateRequestBody(form({ message: '   ' }))).toEqual({
      sunset_date: null,
      message: null,
      replacement_id: null,
    });
  });

  it('sends the trimmed details', () => {
    expect(
      buildDeprecateRequestBody(
        form({ sunsetDate: '2027-01-31', message: '  Use money-v2.  ', replacementId: 'prim-9' })
      )
    ).toEqual({ sunset_date: '2027-01-31', message: 'Use money-v2.', replacement_id: 'prim-9' });
  });
});

describe('replacementOptions', () => {
  const types = [
    { id: 'self', name: 'money', namespace: 'tenant/acme/v1/types' },
    { id: 'b', name: 'money-v2', namespace: 'tenant/acme/v2/types' },
    { id: 'c', name: 'amount', namespace: null },
    { id: 'd', name: 'old-money', namespace: 'tenant/acme/v0/types', deprecated: true },
    { id: 'e', name: 'older-money', deprecated_at: '2026-01-01T00:00:00Z' },
  ];

  it('leaves out the type itself and every deprecated type, sorted by label', () => {
    expect(replacementOptions(types, 'self')).toEqual([
      { id: 'c', label: 'amount' },
      { id: 'b', label: 'money-v2 — tenant/acme/v2/types' },
    ]);
  });

  it('is empty when nothing else is visible', () => {
    expect(replacementOptions([types[0]], 'self')).toEqual([]);
  });
});
