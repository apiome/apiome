import { redirect } from 'next/navigation';

/**
 * `/design-system/hive` — the Hive gallery's old address (HIVE-2.1, #5280).
 *
 * The gallery moved to the root `/design-system` route in HIVE-10.5 (#5341). This keeps old
 * links and bookmarks working instead of returning a 404.
 */
export default function HiveDesignSystemRedirect(): never {
  redirect('/design-system');
}
