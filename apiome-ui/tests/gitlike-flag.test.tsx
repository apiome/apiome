/**
 * `GitlikeFlag` — the outline feature-flag marker (HIVE-13.1, #5614).
 *
 * DESIGN.md §2: honey is never a feature-flag colour, and a feature-flag marker is
 * `.badge--outline`. The flag is drawn only once `FEATURE_GITLIKE` is on.
 */

import { render, screen } from '@testing-library/react';
import { GitlikeFlag } from '../src/app/components/ade/versions/GitlikeFlag';
import {
  GITLIKE_FLAG_LABEL,
  GITLIKE_FLAG_ON_TITLE,
} from '../src/app/components/ade/versions/versionsModel';

describe('GitlikeFlag', () => {
  it('draws nothing while FEATURE_GITLIKE is off (the default)', () => {
    const { container } = render(<GitlikeFlag />);
    expect(container).toBeEmptyDOMElement();
    render(<GitlikeFlag enabled={false} />);
    expect(screen.queryByTestId('gitlike-flag')).not.toBeInTheDocument();
  });

  it('draws an outline badge with a flag glyph and the one word once the flag is on', () => {
    render(<GitlikeFlag enabled />);
    const flag = screen.getByTestId('gitlike-flag');
    expect(flag).toHaveTextContent(GITLIKE_FLAG_LABEL);
    expect(flag).toHaveAttribute('title', GITLIKE_FLAG_ON_TITLE);
    expect(flag.querySelector('svg')).toHaveAttribute('aria-hidden');
    // The outline tone: muted ink on a hairline, and no honey anywhere.
    expect(flag.className).toContain('text-fg-muted');
    expect(flag.className).not.toMatch(/honey/);
    expect(flag).not.toHaveClass('ver-flag');
  });

  it('keeps a caller class and title', () => {
    render(<GitlikeFlag enabled className="ver-menu__flag" title="Custom" />);
    const flag = screen.getByTestId('gitlike-flag');
    expect(flag).toHaveClass('ver-menu__flag');
    expect(flag).toHaveAttribute('title', 'Custom');
  });
});
