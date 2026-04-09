import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { upsertUserThemePreferences } from '@lib/db/theme-preferences';
import type { ThemeModeName, ThemePaletteOverrides } from '@lib/theme/types';

const OVERRIDE_KEYS: (keyof ThemePaletteOverrides)[] = [
  'primary',
  'secondary',
  'accent',
  'background',
  'surface',
  'text',
];

function parseBody(data: unknown): { theme: ThemeModeName; overrides: ThemePaletteOverrides } | null {
  if (!data || typeof data !== 'object') return null;
  const o = data as Record<string, unknown>;
  const rawTheme = o.theme;
  const theme: ThemeModeName =
    rawTheme === 'light' || rawTheme === 'dark' || rawTheme === 'system' ? rawTheme : 'system';
  const overrides: ThemePaletteOverrides = {};
  const rawOverrides = o.overrides;
  if (rawOverrides && typeof rawOverrides === 'object') {
    const ov = rawOverrides as Record<string, unknown>;
    for (const k of OVERRIDE_KEYS) {
      const v = ov[k];
      if (typeof v === 'string' && v.trim().length > 0) {
        overrides[k] = v.trim().slice(0, 128);
      }
    }
  }
  return { theme, overrides };
}

/**
 * Persists theme mode and optional palette overrides for the signed-in user.
 */
export async function PUT(req: NextRequest) {
  const session = await getServerSession(authOptions);
  const userId = (session?.user as { user_id?: string } | undefined)?.user_id;
  if (!userId) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  let json: unknown;
  try {
    json = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const parsed = parseBody(json);
  if (!parsed) {
    return NextResponse.json({ error: 'Invalid body' }, { status: 400 });
  }

  try {
    await upsertUserThemePreferences(userId, parsed.theme, parsed.overrides);
  } catch (e) {
    console.error('[preferences/theme] upsert failed', e);
    return NextResponse.json({ error: 'Failed to save preferences' }, { status: 500 });
  }

  const res = NextResponse.json({
    success: true,
    theme: parsed.theme,
    overrides: parsed.overrides,
  });

  const hint = JSON.stringify({ theme: parsed.theme, overrides: parsed.overrides });
  res.cookies.set('obj-theme-hint', encodeURIComponent(hint), {
    path: '/',
    maxAge: 60 * 60 * 24 * 365,
    sameSite: 'lax',
  });

  return res;
}
