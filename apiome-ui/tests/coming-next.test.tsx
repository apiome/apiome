/**
 * `ComingNext` (HIVE-12.5, #5612): what is not shipped yet, named once as text.
 *
 * The rule it exists to enforce is that an unshipped product is never a control — so the
 * assertions are mostly about what the line does *not* render: no disabled or aria-disabled
 * element, no empty "Coming next:" with nothing after it, and exactly one control (the
 * What's new link) when a follow action is given.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { ComingNext, COMING_NEXT_FOLLOW_LABEL } from '../src/app/components/ui/ComingNext';

const ITEMS = [
  { id: 'developer-suite', label: 'Developer Suite' },
  { id: 'community', label: 'Community' },
];

describe('ComingNext', () => {
  it('names each unshipped thing as a tag, after “Coming next:”', () => {
    render(<ComingNext items={ITEMS} />);

    const line = screen.getByTestId('coming-next');
    expect(line.tagName).toBe('P');
    expect(line).toHaveTextContent(/^Coming next:Developer SuiteCommunity$/);
    expect(screen.getByTestId('coming-next-developer-suite')).toHaveTextContent('Developer Suite');
    expect(screen.getByTestId('coming-next-community')).toHaveTextContent('Community');
  });

  it('renders nothing when there is nothing to announce', () => {
    const { container } = render(<ComingNext items={[]} onFollow={() => undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('has no controls of its own without a follow action', () => {
    render(<ComingNext items={ITEMS} />);
    const line = screen.getByTestId('coming-next');
    expect(within(line).queryAllByRole('button')).toHaveLength(0);
    expect(within(line).queryAllByRole('link')).toHaveLength(0);
  });

  it('follows to What’s new in place with a button', async () => {
    const onFollow = jest.fn();
    const user = userEvent.setup();
    render(<ComingNext items={ITEMS} onFollow={onFollow} followHref="/ignored" />);

    const follow = screen.getByRole('button', { name: COMING_NEXT_FOLLOW_LABEL });
    await user.click(follow);
    expect(onFollow).toHaveBeenCalledTimes(1);
    // `onFollow` wins over `followHref`: one control, not two.
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('follows to a page with a link', () => {
    render(<ComingNext items={ITEMS} followHref="/ade/dashboard/help" />);
    expect(screen.getByRole('link', { name: COMING_NEXT_FOLLOW_LABEL })).toHaveAttribute(
      'href',
      '/ade/dashboard/help'
    );
  });

  it('never renders a disabled or aria-disabled element', () => {
    const { container } = render(<ComingNext items={ITEMS} onFollow={() => undefined} />);
    expect(container.querySelectorAll('[disabled], [aria-disabled]')).toHaveLength(0);
  });

  it('hides its icon from assistive technology', () => {
    const { container } = render(<ComingNext items={ITEMS} />);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <main>
        <ComingNext items={ITEMS} onFollow={() => undefined} />
        <ComingNext items={ITEMS} followHref="/ade/dashboard/help" />
      </main>
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
