/**
 * `/ade/authoring/releases` — Releases (UXE-1.2 placeholder).
 *
 * The route exists so the suite dropdown and the shell's secondary navigation
 * have a real destination that keeps scope. The workspace itself ships in
 * UXE-2.4.
 */

import { getAuthoringSurface } from '@lib/authoring/surfaces';
import AuthoringSurfacePlaceholder from '../components/AuthoringSurfacePlaceholder';

export default function AuthoringReleasesPage() {
  return <AuthoringSurfacePlaceholder surface={getAuthoringSurface('releases')!} />;
}
