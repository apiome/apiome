/**
 * Lint decision badge helpers (CLX-1.3, #4850).
 */
import { render, screen } from '@testing-library/react';

import {
  LintDecisionBadge,
  policyDecisionsByFingerprint,
} from '../../src/app/utils/lint-policy-ui';

describe('LintDecisionBadge', () => {
  it('renders waived state distinctly from raw severity', () => {
    render(<LintDecisionBadge state="waived" waived />);
    expect(screen.getByTestId('lint-decision-badge')).toHaveTextContent('Waived');
  });
});

describe('policyDecisionsByFingerprint', () => {
  it('indexes annotated findings by source fingerprint', () => {
    const map = policyDecisionsByFingerprint({
      findings: [
        {
          evidence: { sourceFingerprint: 'lint-1', severity: 'error' },
          effectiveState: 'waived',
          waived: true,
        },
      ],
    });
    expect(map['lint-1']).toEqual({ state: 'waived', waived: true });
  });
});
