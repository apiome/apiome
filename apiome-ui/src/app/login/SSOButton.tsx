'use client';

import * as React from 'react';
import { ArrowRight } from 'lucide-react';

import { Button } from '../components/ui/Button';

/** Props for {@link SSOButton}. */
export interface SSOButtonProps {
  /** The provider's display label, e.g. `GitHub`. */
  provider: string;
  /** The provider's brand mark. */
  icon: React.ReactNode;
  /** Start this provider's redirect. */
  onClick: () => void;
  /** Label the button for account creation rather than sign-in. */
  isSignUp?: boolean;
  /** Disable while another path is starting. */
  disabled?: boolean;
}

/**
 * One provider row: brand mark, label, and an arrow that surfaces under the pointer. Shared by
 * the sign-in page and `/signup` (SGN-1.2), so both list providers the same way.
 *
 * @param props Provider label, icon, click handler and mode — see {@link SSOButtonProps}.
 * @returns The full-width outline button for that provider.
 */
export function SSOButton({ provider, icon, onClick, isSignUp, disabled }: SSOButtonProps) {
  const label = isSignUp ? `Sign up with ${provider}` : `Continue with ${provider}`;
  return (
    <Button type="button" variant="outline" size="lg" className="auth-sso" onClick={onClick} disabled={disabled}>
      {/* Decorative brand mark — the button's text label carries the accessible name, so the
          icon is hidden from assistive tech (some react-icons set role="img" without a title,
          which axe reports as a serious violation). */}
      <span aria-hidden="true" className="auth-sso__mark">
        {icon}
      </span>
      <span className="font-semibold">{label}</span>
      <ArrowRight className="auth-sso__arrow" aria-hidden="true" />
    </Button>
  );
}

export default SSOButton;
