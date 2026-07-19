'use client';

/**
 * Release and environment badges (UXE-1.3).
 *
 * A release status is shown in the Release Center timeline, the Overview hero,
 * the peek drawer and the impact sheet. All four render this, so "Ready" cannot
 * mean promotable in one place and merely built in another.
 *
 * The environment badge is deliberately toneless: preview and production are
 * lanes, not health. Colouring production red or green would make the lane look
 * like a status.
 */

import * as React from 'react';
import {
  describeAuthoringRelease,
  type AuthoringReleaseEnvironment,
  type AuthoringReleaseStatus,
} from '@lib/authoring/releases';
import { cn } from '@lib/utils';
import { authoringMonoClass } from '../../authoringClasses';
import AuthoringToneBadge from './AuthoringToneBadge';

/** Props for {@link AuthoringReleaseBadge}. */
export type AuthoringReleaseBadgeProps = {
  status: AuthoringReleaseStatus;
  /** Immutable release id, e.g. `r-4821`. Rendered in mono beside the badge. */
  releaseId?: string;
  className?: string;
};

/**
 * Render a release status badge.
 *
 * @param props - The status and an optional release id.
 */
export default function AuthoringReleaseBadge({
  status,
  releaseId,
  className,
}: AuthoringReleaseBadgeProps) {
  const descriptor = describeAuthoringRelease(status);

  return (
    <span className={cn('inline-flex items-center gap-2', className)} data-release-status={status}>
      <AuthoringToneBadge
        label={descriptor.label}
        tone={descriptor.tone}
        icon={descriptor.icon}
        description={descriptor.description}
      />
      {releaseId ? <span className={authoringMonoClass}>{releaseId}</span> : null}
    </span>
  );
}

/** Props for {@link AuthoringEnvironmentBadge}. */
export type AuthoringEnvironmentBadgeProps = {
  environment: AuthoringReleaseEnvironment;
  className?: string;
};

/** Labels per deployment lane. */
const ENVIRONMENT_LABELS: Record<AuthoringReleaseEnvironment, { label: string; description: string }> =
  {
    preview: {
      label: 'Preview',
      description: 'A shareable, non-production lane. Changes here do not affect published docs.',
    },
    production: {
      label: 'Production',
      description: 'The live lane. Changes here are visible to your API consumers.',
    },
  };

/**
 * Render a deployment lane badge.
 *
 * @param props - The environment being labelled.
 */
export function AuthoringEnvironmentBadge({
  environment,
  className,
}: AuthoringEnvironmentBadgeProps) {
  const { label, description } = ENVIRONMENT_LABELS[environment];

  return (
    <AuthoringToneBadge
      label={label}
      // Neutral by design: a lane is not a health signal.
      tone="neutral"
      icon={environment === 'production' ? 'Globe' : 'Eye'}
      description={description}
      className={className}
    />
  );
}
