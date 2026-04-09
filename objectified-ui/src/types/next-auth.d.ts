import type { DefaultSession } from 'next-auth';
import type { ThemeModeName, ThemePaletteOverrides } from '@lib/theme/types';

declare module 'next-auth' {
  interface Session extends DefaultSession {
    user: DefaultSession['user'] & {
      user_id?: string;
      current_tenant_id?: string;
      theme_name?: ThemeModeName;
      theme_overrides?: ThemePaletteOverrides;
    };
  }
}

declare module 'next-auth/jwt' {
  interface JWT {
    theme_name?: string;
    theme_overrides?: string;
  }
}
