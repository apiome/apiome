/**
 * `/ade/authoring/scribe` — Scribe (UXE-1.2 placeholder).
 *
 * The route exists so the suite dropdown and the shell's secondary navigation
 * have a real destination that keeps scope. The workspace itself ships in
 * UXE-2.2.
 */

import { getAuthoringSurface } from '@lib/authoring/surfaces';
import AuthoringSurfacePlaceholder from '../components/AuthoringSurfacePlaceholder';

export default function AuthoringScribePage() {
  return <AuthoringSurfacePlaceholder surface={getAuthoringSurface('scribe')!} />;
}
