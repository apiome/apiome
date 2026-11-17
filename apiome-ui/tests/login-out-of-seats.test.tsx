/**
 * "Your workspace is out of seats" — EID-1.3 (#5013).
 *
 * Where a single sign-on lands when the workspace has no member seat left. Pinned: it names the
 * workspace and who is signed in, says the owners were told and that signing in again will add the
 * person, offers Sign out and nothing else, and treats the workspace name as text.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

const signOutEverywhere = jest.fn();
jest.mock('@lib/auth/sign-out-client', () => ({
  signOutEverywhere: (...args: unknown[]) => signOutEverywhere(...args),
}));

import OutOfSeatsScreen from '../src/app/login/out-of-seats/OutOfSeatsScreen';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

describe('the out-of-seats screen', () => {
  beforeEach(() => signOutEverywhere.mockClear());

  it('says what happened, to whom, and what fixes it', () => {
    render(<OutOfSeatsScreen workspace="Northwind" email="lena.fischer@northwind.io" />);

    expect(screen.getByRole('heading', { level: 1, name: 'Your workspace is out of seats' })).toBeInTheDocument();
    expect(screen.getByTestId('out-of-seats-reason')).toHaveTextContent(
      'You signed in, but Northwind has no member seat left, so you were not added to it.'
    );
    expect(screen.getByTestId('out-of-seats-screen')).toHaveTextContent('The workspace’s owners have been notified.');
    expect(screen.getByTestId('out-of-seats-screen')).toHaveTextContent('sign in again and you will be added automatically');
    expect(screen.getByTestId('out-of-seats-signed-in-as')).toHaveTextContent('Signed in as lena.fischer@northwind.io');
  });

  it('offers Sign out, and only that', async () => {
    const user = userEvent.setup();
    render(<OutOfSeatsScreen workspace="Northwind" email="lena.fischer@northwind.io" />);

    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(signOutEverywhere).toHaveBeenCalledWith('/login');
  });

  it('still reads when the workspace and the address are unknown', () => {
    render(<OutOfSeatsScreen workspace={null} email={null} />);
    expect(screen.getByTestId('out-of-seats-reason')).toHaveTextContent('You signed in, but Your workspace has no member seat left');
    expect(screen.queryByTestId('out-of-seats-signed-in-as')).not.toBeInTheDocument();
  });

  it('prints a workspace name as text, never as markup', () => {
    render(<OutOfSeatsScreen workspace={'<img src=x onerror=alert(1)>'} email={null} />);
    expect(screen.getByTestId('out-of-seats-reason')).toHaveTextContent('<img src=x onerror=alert(1)>');
    expect(document.querySelector('img[src="x"]')).toBeNull();
  });
});

/**
 * The documentation site's Workspace single sign-on page (`apiome-docs/screens.json`) is captured
 * from this dump: `A11Y_FIXTURE_DUMP=1 npx jest tests/login-out-of-seats.test.tsx`.
 */
describe('the docs fixture', () => {
  it('renders the screen a blocked sign-in lands on', () => {
    const { container } = render(<OutOfSeatsScreen workspace="Northwind" email="lena.fischer@northwind.io" />);
    writeA11yFixture('login-out-of-seats', container.innerHTML);
  });
});
