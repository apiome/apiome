'use server';

import type { ThemeModeName, ThemePaletteOverrides } from '@lib/theme/types';

// db.ts is CommonJS (`module.exports`); keep require to match the rest of lib/db helpers.
// eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS pool (see lib/db/db.ts)
const connectionPool = require('./db');

export type UserThemeRow = {
  theme_name: ThemeModeName;
  overrides: ThemePaletteOverrides;
};

function normalizeOverrides(raw: unknown): ThemePaletteOverrides {
  if (!raw || typeof raw !== 'object') return {};
  const o = raw as Record<string, unknown>;
  const pick = (k: keyof ThemePaletteOverrides) =>
    typeof o[k] === 'string' ? (o[k] as string) : undefined;
  return {
    primary: pick('primary'),
    secondary: pick('secondary'),
    accent: pick('accent'),
    background: pick('background'),
    surface: pick('surface'),
    text: pick('text'),
  };
}

export async function getUserThemePreferences(userId: string): Promise<UserThemeRow | null> {
  const res = await connectionPool.query(
    `SELECT theme_name, overrides FROM odb.user_theme_preferences WHERE user_id = $1`,
    [userId]
  );
  if (res.rows.length === 0) return null;
  const row = res.rows[0];
  const name = row.theme_name as string;
  const theme_name: ThemeModeName =
    name === 'light' || name === 'dark' || name === 'system' ? name : 'system';
  return {
    theme_name,
    overrides: normalizeOverrides(row.overrides),
  };
}

export async function upsertUserThemePreferences(
  userId: string,
  themeName: ThemeModeName,
  overrides: ThemePaletteOverrides
): Promise<void> {
  await connectionPool.query(
    `INSERT INTO odb.user_theme_preferences (user_id, theme_name, overrides, updated_at)
     VALUES ($1, $2, $3::jsonb, CURRENT_TIMESTAMP)
     ON CONFLICT (user_id) DO UPDATE SET
       theme_name = EXCLUDED.theme_name,
       overrides = EXCLUDED.overrides,
       updated_at = CURRENT_TIMESTAMP`,
    [userId, themeName, JSON.stringify(overrides)]
  );
}
