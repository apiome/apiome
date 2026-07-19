'use client';

/**
 * Render an Authoring icon by name (UXE-1.2).
 *
 * Surfaces, commands and state badges name their icon as a string. Resolving
 * that name to a component inside a render body would create a new component
 * type on every render, so resolution happens here instead: this component is
 * declared once, and only the resolved element changes.
 */

import * as React from 'react';
import { resolveAuthoringIcon } from './authoringIcons';

/** Props for {@link AuthoringIcon}. */
export type AuthoringIconProps = {
  /** Icon name declared by a surface, command or badge. */
  name: string | undefined;
  className?: string;
};

/**
 * Render the icon for `name`, decorative by default.
 *
 * Every call site pairs the icon with a visible text label, so the icon itself
 * is always hidden from assistive technology.
 *
 * @param props - Icon name and optional classes.
 */
export default function AuthoringIcon({ name, className }: AuthoringIconProps) {
  // `createElement` rather than binding the result to a capitalized variable:
  // the lookup returns one of a fixed set of module-level components, so there
  // is no new component type per render to remount.
  return React.createElement(resolveAuthoringIcon(name), {
    className,
    'aria-hidden': 'true',
  });
}
