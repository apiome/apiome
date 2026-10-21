/**
 * `<ImplementationGuideBanner>` and `implementationGuideFor` (FMT-6.10, #5454): the shared
 * "no implementation guide was consulted" banner the Format details tab renders for every EDI and
 * vertical-messaging format.
 */

import * as React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ImplementationGuideBanner } from '@/app/components/ade/dashboard/catalog/ImplementationGuideBanner';
import {
  implementationGuideFor,
  type FormatCapability,
} from '@/app/components/ade/dashboard/catalog/formatCapabilityRegistry';
import { REGISTRY_SNAPSHOT } from './helpers/payload-analysis-fixture';

const X12: FormatCapability = REGISTRY_SNAPSHOT.formats[0];

function entry(overrides: Partial<FormatCapability>): FormatCapability {
  return { ...X12, ...overrides };
}

describe('implementationGuideFor', () => {
  it('returns the statement of a reviewed family entry', () => {
    expect(implementationGuideFor(X12)?.guides_not_consulted).toHaveLength(2);
  });

  it('returns null without an entry, a statement, or a review', () => {
    expect(implementationGuideFor(null)).toBeNull();
    expect(implementationGuideFor(undefined)).toBeNull();
    expect(implementationGuideFor(entry({ implementation_guide: null }))).toBeNull();
    expect(implementationGuideFor(entry({ implementation_guide: undefined }))).toBeNull();
    expect(implementationGuideFor(entry({ provenance: 'derived' }))).toBeNull();
  });

  it('refuses a statement that claims a guide was consulted, or names none', () => {
    const guide = X12.implementation_guide!;
    expect(implementationGuideFor(entry({ implementation_guide: { ...guide, consulted: true } }))).toBeNull();
    expect(
      implementationGuideFor(entry({ implementation_guide: { ...guide, guides_not_consulted: [] } })),
    ).toBeNull();
    expect(implementationGuideFor(entry({ implementation_guide: { ...guide, statement: '  ' } }))).toBeNull();
  });
});

describe('<ImplementationGuideBanner>', () => {
  it('renders the statement, the guides not consulted and the recorded claims', () => {
    render(<ImplementationGuideBanner capability={X12} />);
    const banner = screen.getByRole('note', { name: 'EDI X12: no implementation guide was consulted' });
    expect(banner).toHaveTextContent('No implementation guide was consulted');
    expect(screen.getByTestId('catalog-implementation-guide-statement')).toHaveTextContent(
      'Only the ASC X12 envelope and segment syntax (ISA/GS/ST) is read.',
    );
    expect(screen.getByTestId('catalog-implementation-guide-not-consulted')).toHaveTextContent(
      'the 4010 and 5010 implementation guides (TR3s) · trading-partner companion guides',
    );
    expect(screen.getByTestId('catalog-implementation-guide-claims')).toHaveTextContent(
      'an ST03 implementation convention reference',
    );
  });

  it('omits the claims line when the format records none', () => {
    const guide = { ...X12.implementation_guide!, claims_recorded: [] };
    render(<ImplementationGuideBanner capability={entry({ implementation_guide: guide })} />);
    expect(screen.getByTestId('catalog-implementation-guide-banner')).toBeInTheDocument();
    expect(screen.queryByTestId('catalog-implementation-guide-claims')).not.toBeInTheDocument();
  });

  it('renders nothing for a format outside the family', () => {
    const { container } = render(
      <ImplementationGuideBanner capability={entry({ implementation_guide: null })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('passes a className through', () => {
    render(<ImplementationGuideBanner capability={X12} className="mt-3" />);
    expect(screen.getByTestId('catalog-implementation-guide-banner')).toHaveClass('mt-3');
  });
});
